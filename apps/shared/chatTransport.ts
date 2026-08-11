import { sharedApiClient } from './apiClient'
import type {
  InlineCitationSearchPayload,
  QueryRequest,
  QueryResponse,
  ThinkingTraceItem,
  ThinkingTraceStep,
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
    options?: {
      signal?: AbortSignal
      onDelta?: (delta: string) => void
      onThinking?: (steps: ThinkingTraceStep[]) => void
      /** 后端边界规则替换了最终回答时，用完整答案整体替换流式正文 */
      onAnswerReplace?: (full: string) => void
    }
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
    let traceMessages: Array<Record<string, any>> = []
    let liveThinkingSteps: ThinkingTraceStep[] = []

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
        } else if (event.type === 'tool_start' || event.type === 'tool_end') {
          liveThinkingSteps = applyAgentEventToThinking(event, liveThinkingSteps)
          options?.onThinking?.([...liveThinkingSteps])
        } else if (event.type === 'note') {
          liveThinkingSteps = applyAgentEventToThinking(event, liveThinkingSteps)
          options?.onThinking?.([...liveThinkingSteps])
        } else if (event.type === 'answer') {
          const finalContent = String(event.payload?.content || '')
          if (finalContent) {
            rawAnswer = finalContent
            answer = cleanStreamText(rawAnswer)
            options?.onAnswerReplace?.(answer)
          }
        } else if (event.type === 'message_delta') {
          rawAnswer += String(event.payload?.delta || '')
          // 工具调用围栏是跨多个流式分片拼出来的，必须对累积文本过滤，再计算增量
          const cleaned = cleanStreamText(rawAnswer)
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
          traceMessages = Array.isArray(event.payload?.messages)
            ? event.payload.messages
            : []
          toolMessages = Array.isArray(event.payload?.messages)
            ? event.payload.messages.filter((m: any) => m.role === 'tool')
            : []
          const runNotes = Array.isArray(event.payload?.notes)
            ? event.payload.notes
            : []
          const finalTrace = mergeThinkingTrace(
            buildThinkingTrace(traceMessages, runNotes),
            liveThinkingSteps
          )
          const finalAssistantText = [...traceMessages]
            .reverse()
            .find((m: any) => m.role === 'assistant' && !m.tool_calls)
          const finalAnswerText = String(finalAssistantText?.content || '')
          const answerFilteredTrace = finalTrace.map(step => (
            step.kind === 'result' && step.citations?.length
              ? {
                  ...step,
                  citations: filterCitationsByMarkers(step.citations, finalAnswerText),
                }
              : step
          ))
          if (runReason && runReason !== 'completed') {
            answerFilteredTrace.push({ kind: 'note', detail: `执行结束（${runReason}）` })
          }
          options?.onThinking?.(answerFilteredTrace)
          liveThinkingSteps = answerFilteredTrace

          // run_end 里的最后一条 assistant 是权威最终答案：
          // 覆盖流式过程里可能出现的工具调用围栏，也兼容后端边界规则替换后的答案。
          const finalAssistant = [...traceMessages]
            .reverse()
            .find((m: any) => m.role === 'assistant')
          if (finalAssistant) {
            const finalRaw = String(finalAssistant.content || '')
            const cleanedFinal = cleanStreamText(finalRaw)
            if (cleanedFinal && cleanedFinal !== answer) {
              rawAnswer = finalRaw
              answer = cleanedFinal
              options?.onAnswerReplace?.(answer)
            }
          }
        } else if (event.type === 'error') {
          throw new Error(String(event.payload?.message || 'Agent 对话错误'))
        }
      }
    }

    const citations = filterCitationsByMarkers(
      collectCitationsFromToolMessages(toolMessages),
      answer
    )
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
      thinking_trace: liveThinkingSteps,
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
          marker: String(citation.marker || citation.cite || ''),
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
          doc_title: String(item.metadata?.doc_title || item.title || ''),
          marker: String(item.metadata?.cite || ''),
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
    const key = [citation.target_id, citation.doc_id, citation.page_idx, citation.section_path, citation.marker || ''].join('::')
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

/**
 * 只保留最终回答里真实引用的标记（[K1]/[T1]/[E1]）。
 * 替代按文档名猜测的 filterCitationsByAnswer。
 */
export function filterCitationsByMarkers(
  citations: AIChatCitation[],
  answer: string
): AIChatCitation[] {
  const used = new Set<string>()
  const re = /\[([KTE]\d+)\]/g
  let match: RegExpExecArray | null
  while ((match = re.exec(answer || '')) !== null) used.add(match[1])
  return (citations || []).filter(c => c.marker && used.has(c.marker))
}

/**
 * 只保留最终回答里真正提到的文档引用。
 * 检索候选里的 top-N 引用可能包含无关文档（如其他规范），
 * 但“用于最终回答”的引用必须能在回答正文里对上出处。
 */
export function filterCitationsByAnswer(
  citations: AIChatCitation[],
  answer: string
): AIChatCitation[] {
  const normalizedAnswer = String(answer || '')
  if (!normalizedAnswer) return []
  const docTitleForms = (title: string): string[] => {
    const base = String(title || '').replace(/\.(docx?|pdf|xlsx?|pptx?|md|markdown|txt)$/i, '')
    if (!base) return []
    const extensions = ['pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'md', 'txt']
    const forms = new Set<string>([
      `《${base}》`,
      base,
      `《${title}》`,
      title,
    ])
    for (const ext of extensions) {
      forms.add(`《${base}.${ext}》`)
      forms.add(`${base}.${ext}`)
    }
    return [...forms].filter(Boolean)
  }
  return (citations || []).filter(citation => {
    const forms = docTitleForms(citation.doc_title)
    return forms.some(form => normalizedAnswer.includes(form))
  })
}

/**
 * 流式过滤：既去掉完整工具调用块，也抑制尚未写完的工具调用文本，
 * 避免 `[{"name": "knowledge_search"...` 这类内容逐字漏进界面。
 */
export function cleanStreamText(raw: string): string {
  let cleaned = String(raw || '').replace(/```tool_calls[\s\S]*?```/gi, '')
  const fenceStart = cleaned.search(/```tool_calls/gi)
  if (fenceStart >= 0) {
    cleaned = cleaned.slice(0, fenceStart)
  }
  return stripPlainToolCallArtifacts(cleaned).trim()
}

/** 兼容别名：最终回答清理 */
export function stripToolCallArtifacts(text: string): string {
  return cleanStreamText(text)
}

/** 去掉（或截断）无围栏的纯 JSON 工具调用数组 */
function stripPlainToolCallArtifacts(text: string): string {
  let result = ''
  let cursor = 0
  let i = 0
  while (i < text.length) {
    if (text[i] !== '[') {
      i += 1
      continue
    }
    const scan = scanJsonArray(text, i)
    if (!scan) {
      i += 1
      continue
    }
    const candidate = text.slice(i, scan.end)
    let isToolCall = false
    if (scan.complete) {
      try {
        const parsed = JSON.parse(candidate)
        isToolCall = Array.isArray(parsed) && parsed.some(
          (item) => item
            && typeof item === 'object'
            && typeof (item as any).name === 'string'
            && (item as any).arguments
            && typeof (item as any).arguments === 'object'
        )
      } catch {
        isToolCall = false
      }
    } else {
      // 未闭合时按形状猜测：以对象数组开头且带 name/arguments 关键字的视为工具调用
      const normalized = candidate.replace(/\s/g, '')
      isToolCall = normalized.startsWith('[{"') && (
        normalized.includes('"name"') || normalized.includes('"arguments"')
      )
    }
    if (isToolCall) {
      result += text.slice(cursor, i)
      if (!scan.complete) {
        return result
      }
      cursor = scan.end
      i = scan.end
      continue
    }
    i = scan.end
  }
  return result + text.slice(cursor)
}

/** 扫描从 start 开始的 JSON 数组，返回结束位置与是否闭合 */
function scanJsonArray(text: string, start: number): { end: number; complete: boolean } | null {
  let depth = 0
  let inString = false
  let escaped = false
  for (let j = start; j < text.length; j += 1) {
    const ch = text[j]
    if (inString) {
      if (escaped) {
        escaped = false
      } else if (ch === '\\') {
        escaped = true
      } else if (ch === '"') {
        inString = false
      }
      continue
    }
    if (ch === '"') {
      inString = true
    } else if (ch === '[') {
      depth += 1
    } else if (ch === ']') {
      depth -= 1
      if (depth === 0) {
        return { end: j + 1, complete: true }
      }
    }
  }
  return { end: text.length, complete: false }
}

/** 把工具返回内容压缩成一行要点 */
export function summarizeToolResult(content: string, maxLength = 120): string {
  let raw: any
  try {
    raw = JSON.parse(content || '{}')
  } catch {
    // 流式过程里 tool_end 的 result 可能被截断成片段，不要把这串 JSON 残片漏进界面
    return '工具已返回结果（完整内容见最终轨迹）'
  }
  if (raw && typeof raw === 'object') {
    if (Array.isArray(raw.items)) return `检索到 ${raw.total ?? raw.items.length} 条结果`
    if (Array.isArray(raw.entities)) return `图谱检索到 ${raw.total ?? raw.entities.length} 个实体`
    if (raw.error) return `出错：${String(raw.error).slice(0, maxLength)}`
    if (Array.isArray(raw.sop_trace)) return `SOP ${raw.sop_id || ''} 执行 ${raw.sop_trace.length} 步`
    if (raw.result !== undefined) return String(raw.result).slice(0, maxLength)
  }
  return String(content || '').slice(0, maxLength)
}

/** 从工具返回 JSON 中提取完整候选条目（knowledge_search/table_search/entity_search）。 */
export function extractToolResultItems(content: string): ThinkingTraceItem[] | undefined {
  let raw: any
  try {
    raw = JSON.parse(content || '{}')
  } catch {
    return undefined
  }
  if (!raw || typeof raw !== 'object') return undefined

  const normalizeItem = (entry: any): ThinkingTraceItem | null => {
    if (!entry || typeof entry !== 'object') return null
    const itemId = String(entry.item_id || entry.id || '')
    if (!itemId) return null
    const metadata = entry.metadata && typeof entry.metadata === 'object'
      ? entry.metadata
      : {}
    const title = String(entry.title || entry.name || metadata.doc_title || '')
    const text = String(entry.text || entry.description || entry.content || '')
    if (!text) return null
    return {
      item_id: itemId,
      entity_type: String(entry.entity_type || 'content'),
      doc_id: String(entry.doc_id || ''),
      doc_title: String(metadata.doc_title || entry.doc_title || title),
      title,
      text,
      cite: String(metadata.cite || ''),
      score: Number(entry.score ?? entry.rerank_score ?? 0),
      metadata,
    }
  }

  if (Array.isArray(raw.items)) {
    const items = raw.items.map(normalizeItem).filter(Boolean) as ThinkingTraceItem[]
    return items.length ? items : undefined
  }
  if (Array.isArray(raw.entities)) {
    const items = raw.entities.map(normalizeItem).filter(Boolean) as ThinkingTraceItem[]
    return items.length ? items : undefined
  }
  return undefined
}

/** 提取工具返回中需要单独说明的信息（如 entity_search 自动回退正文）。 */
export function extractToolResultNote(content: string): string | undefined {
  let raw: any
  try {
    raw = JSON.parse(content || '{}')
  } catch {
    return undefined
  }
  if (raw && typeof raw === 'object' && raw.note) {
    return String(raw.note).trim() || undefined
  }
  return undefined
}

/** 把 agent 事件实时转换为思考过程步骤（turn_start / tool_start / tool_end） */
export function applyAgentEventToThinking(
  event: { type?: string; turn?: number; payload?: any },
  steps: ThinkingTraceStep[]
): ThinkingTraceStep[] {
  const turn = event?.turn != null ? Number(event.turn) : undefined
  if (event?.type === 'turn_start') {
    return [...steps, { kind: 'turn', detail: '', ...(turn != null ? { turn } : {}) }]
  }
  if (event?.type === 'note') {
    const detail = String(event.payload?.detail || event.payload?.message || '')
    if (!detail) return steps
    return [...steps, { kind: 'note', detail, ...(turn != null ? { turn } : {}) }]
  }
  if (event?.type === 'tool_start') {
    return [
      ...steps,
      {
        kind: 'call',
        tool: String(event.payload?.name || 'unknown'),
        detail: JSON.stringify(event.payload?.args || {}),
        ...(turn != null ? { turn } : {}),
      },
    ]
  }
  if (event?.type === 'tool_end') {
    const durationMs = Number(event.payload?.duration_ms)
    const resultStep: ThinkingTraceStep = {
      kind: 'result',
      tool: String(event.payload?.name || 'unknown'),
      detail: summarizeToolResult(event.payload?.result),
      isError: Boolean(event.payload?.is_error),
      // 实时 result 可能被截断，完整条目等 run_end 用消息重建
      ...(turn != null ? { turn } : {}),
      ...(durationMs > 0 ? { durationMs } : {}),
    }
    const liveItems = extractToolResultItems(event.payload?.result)
    if (liveItems) resultStep.resultItems = liveItems
    const liveNote = extractToolResultNote(event.payload?.result)
    if (liveNote) resultStep.resultNote = liveNote
    return [...steps, resultStep]
  }
  return steps
}

/** 从 run_end 消息构建完整思考过程轨迹：轮次、工具调用、返回要点与证据 */
export function buildThinkingTrace(
  messages: Array<Record<string, any>>,
  notes: Array<{ detail?: string } | string> = []
): ThinkingTraceStep[] {
  const steps: ThinkingTraceStep[] = []
  let turn = 0
  for (const message of messages || []) {
    if (message?.role === 'assistant') {
      turn += 1
      const toolCalls = Array.isArray(message.tool_calls) ? message.tool_calls : []
      if (toolCalls.length) {
        for (const call of toolCalls) {
          steps.push({
            kind: 'call',
            tool: String(call?.name || 'unknown'),
            detail: JSON.stringify(call?.arguments || {}),
            turn,
          })
        }
      } else if (String(message.content || '').trim()) {
        steps.push({
          kind: 'note',
          detail: '汇总证据并生成最终回答',
          turn,
        })
      }
    } else if (message?.role === 'tool') {
      const resultStep: ThinkingTraceStep = {
        kind: 'result',
        tool: String(message?.name || 'unknown'),
        detail: summarizeToolResult(message?.content),
        isError: Boolean(message?.is_error),
        turn,
        citations: collectCitationsFromToolMessages([
          message as { name?: string; content: string },
        ]),
      }
      const resultItems = extractToolResultItems(message?.content)
      if (resultItems) resultStep.resultItems = resultItems
      const resultNote = extractToolResultNote(message?.content)
      if (resultNote) resultStep.resultNote = resultNote
      steps.push(resultStep)
    }
  }
  for (const note of notes || []) {
    const detail = typeof note === 'string' ? note : String(note?.detail || '')
    if (detail) {
      steps.push({ kind: 'note', detail })
    }
  }
  return steps
}

/**
 * 以实时事件流为骨架，把 run_end 的完整消息合并进来：
 * 实时流负责顺序（轮次/边界说明/取消等），run_end 负责完整结果、引用与耗时。
 */
export function mergeThinkingTrace(
  finalSteps: ThinkingTraceStep[],
  liveSteps: ThinkingTraceStep[]
): ThinkingTraceStep[] {
  const allFinal = (finalSteps || []).map((step, idx) => ({ step, idx }))
  const finalCalls = allFinal.filter(entry => entry.step.kind === 'call')
  const finalResults = allFinal.filter(entry => entry.step.kind === 'result')
  const finalNotes = allFinal.filter(entry => entry.step.kind === 'note')
  const used = new Set<number>()
  const merged: ThinkingTraceStep[] = []

  for (const live of liveSteps || []) {
    if (live.kind === 'call') {
      const entry = finalCalls.shift()
      if (entry) {
        used.add(entry.idx)
        merged.push({
          ...entry.step,
          ...(live.turn != null ? { turn: live.turn } : {}),
        })
      } else {
        merged.push(live)
      }
    } else if (live.kind === 'result') {
      const entry = finalResults.shift()
      if (entry) {
        used.add(entry.idx)
        merged.push({
          ...entry.step,
          durationMs: live.durationMs || entry.step.durationMs,
          isError: live.isError ?? entry.step.isError,
          turn: live.turn ?? entry.step.turn,
        })
      } else {
        merged.push(live)
      }
    } else if (live.kind === 'note') {
      const sameEntryIdx = finalNotes.findIndex(entry => entry.step.detail === live.detail)
      if (sameEntryIdx >= 0) {
        const entry = finalNotes[sameEntryIdx]
        used.add(entry.idx)
        merged.push({
          ...entry.step,
          ...(live.turn != null ? { turn: live.turn } : {}),
        })
        finalNotes.splice(sameEntryIdx, 1)
      } else {
        merged.push(live)
      }
    } else {
      merged.push(live)
    }
  }

  // live 流里没有对应事件（截断守卫、非流式场景）的最终步骤，按原顺序补回
  allFinal.forEach(entry => {
    if (!used.has(entry.idx)) {
      merged.push(entry.step)
    }
  })
  return merged
}
