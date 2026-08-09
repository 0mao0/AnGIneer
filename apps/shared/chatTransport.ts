import { sharedApiClient } from './apiClient'
import type {
  InlineCitationSearchPayload,
  QueryRequest,
  QueryResponse,
} from '@angineer/ui-kit'
import type { AIChatCitation } from '@angineer/ui-kit'

/**
 * AIChat 的默认数据传输层实现（AnGIneer 后端契约）。
 * 之前这份实现硬编码在 ui-kit 内部并反向依赖 apps/shared；
 * 现在挪到应用侧，ui-kit 的 AIChat 只认 AIChatTransport 接口。
 */
export const defaultAIChatTransport = {
  query: async (
    payload: QueryRequest,
    options?: { signal?: AbortSignal; onDelta?: (delta: string) => void }
  ): Promise<QueryResponse> => {
    // P7 链路：走 /api/chat/agent（AgentSession 多轮 + SSE 事件流）
    const response = await fetch('/api/chat/agent', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query: payload.query,
        scene: payload.scene || 'qa',
        session_id: payload.session_id,
        library_id: payload.library_id || 'default',
        doc_ids: payload.doc_ids || [],
        inline_citations: payload.inline_citations || [],
      }),
      signal: options?.signal,
    })
    if (!response.ok || !response.body) {
      const detail = await response.text().catch(() => '')
      throw new Error(`Agent 对话请求失败(${response.status}): ${detail.slice(0, 200)}`)
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''
    let rawAnswer = ''
    let answer = ''
    let runId = ''
    let runReason = ''
    let toolMessages: Array<{ name?: string; content: string }> = []

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''
      for (const line of lines) {
        const trimmed = line.trim()
        if (!trimmed.startsWith('data: ')) continue
        const data = trimmed.slice(6)
        if (data === '[DONE]') continue
        let event: any
        try {
          event = JSON.parse(data)
        } catch {
          continue
        }
        if (event.type === 'run_start') {
          runId = String(event.run_id || '')
        } else if (event.type === 'message_delta') {
          rawAnswer += String(event.payload?.delta || '')
          // 工具调用围栏是跨多个流式分片拼出来的，必须对累积文本过滤，再计算增量
          const cleaned = stripToolCallBlocks(rawAnswer)
          if (cleaned.length < answer.length) {
            // 围栏闭合被移除时直接收敛，避免残留工具调用文本
            answer = cleaned
          }
          const delta = cleaned.slice(answer.length)
          if (delta) {
            answer = cleaned
            options?.onDelta?.(delta)
          }
        } else if (event.type === 'run_end') {
          runReason = String(event.payload?.reason || 'completed')
          toolMessages = Array.isArray(event.payload?.messages)
            ? event.payload.messages.filter((m: any) => m.role === 'tool')
            : []
        } else if (event.type === 'error') {
          throw new Error(String(event.payload?.message || 'Agent 对话错误'))
        }
      }
    }

    const citations = collectCitationsFromToolMessages(toolMessages)
    const scene = payload.scene || 'qa'
    return {
      query_id: runId || `agent-${Date.now().toString(36)}`,
      session_key: payload.session_id || '',
      intent: {
        intent_level: scene === 'complex' ? 'L4' : 'L1',
        intent_type: scene === 'complex' ? '复杂任务' : '概念解析',
        parameters: {},
        required_capabilities: ['retrieval'],
        matched_sop: null,
        service_mode: scene === 'complex' ? 'dynamic_orchestration' : 'semantic_retrieval',
        reason: runReason || null,
      },
      answer,
      citations,
      fallback_used: false,
    }
  },
  fetchModels: () =>
    sharedApiClient.get<Array<{ name: string; configured: boolean }>>(
      '/llm_configs'
    ),
  searchReferences: (payload: InlineCitationSearchPayload) =>
    sharedApiClient.post<{ items?: Record<string, any>[] }>(
      '/knowledge/references/search',
      payload
    ),
}

/** 从 run_end 的 tool 消息 content 中聚合参考依据（knowledge/table/sop） */
function collectCitationsFromToolMessages(
  toolMessages: Array<{ name?: string; content: string }>
): AIChatCitation[] {
  const citations: AIChatCitation[] = []
  for (const message of toolMessages) {
    let raw: any
    try {
      raw = JSON.parse(message.content || '{}')
    } catch {
      continue
    }
    if (Array.isArray(raw?.citations) && raw.citations.length > 0) {
      for (const citation of raw.citations) {
        citations.push({
          target_id: String(citation.target_id || citation.step_id || ''),
          target_type: 'content',
          doc_id: String(citation.doc_id || ''),
          doc_title: String(citation.doc_title || citation.source || ''),
          page_idx: Number(citation.page_idx || 0),
          section_path: String(citation.section_path || ''),
          snippet: String(citation.snippet || ''),
          score: Number(citation.score || 0),
        })
      }
      continue
    }
    if (Array.isArray(raw?.items)) {
      for (const item of raw.items) {
        if (!item?.item_id) continue
        citations.push({
          target_id: String(item.item_id || ''),
          target_type: String(item.entity_type || 'content'),
          doc_id: String(item.doc_id || ''),
          doc_title: String(item.title || ''),
          page_idx: Number(item.metadata?.page_idx || 0),
          section_path: String(item.metadata?.section_path || ''),
          snippet: String(item.text || ''),
          score: Number(item.score || 0),
        })
      }
    }
  }
  // 去重
  const seen = new Set<string>()
  return citations.filter((citation) => {
    const key = [citation.target_id, citation.doc_id, citation.page_idx, citation.section_path].join('::')
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

/** 过滤文本协议里的 tool_calls 块，避免工具调用文本混入最终回答 */
function stripToolCallBlocks(text: string): string {
  return text.replace(/```tool_calls[\s\S]*?```/g, '')
}
