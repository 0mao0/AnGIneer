import { docsApiClient, aichatApiClient } from './apiClient'
import { getSessionToken } from './session'
import type {
  InlineCitationSearchPayload,
  QueryRequest,
  QueryResponse,
  SopFlowState,
  ThinkingTraceItem,
  ThinkingTraceStep,
} from '@angineer/aichat-ui'
import type { AIChatCitation } from '@angineer/aichat-ui'

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
      /** 后端 warning 事件（如向量库维度异常）透出到界面横幅；运行时一直在正常调用，只是这里漏了声明 */
      onWarning?: (message: string) => void
      /** 新 turn 开始前，上一中间轮已流出的正文快照（拒答重答/截断重试等）；
       *  宿主应把它收进「思考过程」折叠区而不是丢弃——直接清空会让用户看到文字消失 */
      onInterimAnswer?: (snapshot: string) => void
      /** 等待期阶段推进：run_start→classify，tool_start→search，首个正文 delta→generate */
      onStage?: (stage: 'classify' | 'search' | 'generate') => void
      /** SOP 流程快照（L3/L4 执行期 live 事件 + run_end 重建终态）：宿主收进流程图卡片 */
      onSopFlow?: (flows: SopFlowState[]) => void
    }
  ): Promise<QueryResponse> => {
    // P7 链路：走 /api/chat/agent（AgentSession 多轮 + SSE 事件流）
    const headers: Record<string, string> = { 'Content-Type': 'application/json' }
    // 租户身份：登录的会话 token 随 SSE 请求注入（aichat 中间件据此强制库隔离）
    const sessionToken = getSessionToken()
    if (sessionToken) headers['Authorization'] = `Bearer ${sessionToken}`
    const response = await fetch('/api/chat/agent', {
      method: 'POST',
      headers,
      body: JSON.stringify({
        query: payload.query,
        scene: payload.scene || 'qa',
        session_id: payload.session_id,
        library_id: payload.library_id || 'default',
        // 多库勾选（阶段三）：仅显式提供时携带；旧宿主不带该键，行为逐位不变
        ...(payload.library_ids?.length ? { library_ids: payload.library_ids } : {}),
        doc_ids: payload.doc_ids || [],
        inline_citations: payload.inline_citations || [],
      }),
      signal: options?.signal,
    })
    if (!response.ok || !response.body) {
      const detail = await response.text().catch(() => '')
      // 403 + detail.code=login_required：游客轮闸/身份作废（计划 D2），宿主据此弹登录。
      // 抛干净的业务文案而不是回显原始 JSON——错误气泡会进对话流，JSON 体不该给用户看
      let code: string | undefined
      try {
        code = JSON.parse(detail)?.detail?.code
      } catch {
        // 非 JSON 响应体（网关错误页等），无 code
      }
      const text = code === 'login_required'
        ? '游客试用需登录后继续，当前对话会保留'
        : `Agent 对话请求失败(${response.status})`
      const err = new Error(text) as Error & { code?: string }
      if (code) err.code = code
      throw err
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''
    let rawAnswer = ''
    let answer = ''
    let runId = ''
    let runReason = ''
    let msgSeqs: number[] = [] // 服务端落库 seq（chat_history），随 run_end 帧下发
    let toolMessages: Array<{ name?: string; content: string }> = []
    let traceMessages: Array<Record<string, any>> = []
    let liveThinkingSteps: ThinkingTraceStep[] = []
    /** SOP 流程快照累积（按 sop_id 去重，live 事件逐帧替换 + run_end 用工具消息终态覆盖） */
    const liveSopFlows = new Map<string, SopFlowState>()
    const upsertSopFlow = (flow: SopFlowState) => {
      liveSopFlows.set(flow.sop_id, flow)
      options?.onSopFlow?.(Array.from(liveSopFlows.values()))
    }
    let stage = ''
    /** 请求起点墙钟（分类阶段帧的 ts）：思考过程折叠头「总耗时」的锚点（2026-09-30） */
    let wallAnchorMs: number | undefined
    const setStage = (next: 'classify' | 'search' | 'generate') => {
      if (stage === next) return
      stage = next
      options?.onStage?.(next)
    }

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
        if (event.type === 'stage') {
          // 后端显式阶段帧（分类开始时即发，2026-09-27）：等待期标签与真实阶段对齐
          const next = String(event.stage || '')
          if (next === 'classify' && Number(event.ts) > 0) {
            // 请求起点锚点：分类自此起算（后端 09-30 起在帧上带 ts）
            wallAnchorMs = Number(event.ts) * 1000
          }
          if (next === 'classify' || next === 'search' || next === 'generate') setStage(next)
        } else if (event.type === 'run_start') {
          runId = String(event.run_id || '')
          setStage('classify')
        } else if (event.type === 'turn_start') {
          // 新 turn 开始：后端约定一个 run 内只有最后一轮 assistant 是最终答案。
          // 中间轮（拒答重答/截断重试等）已流出的正文不清空丢弃，而是快照上抛——
          // 宿主收进思考过程折叠区，避免用户看到「文字出现→消失→再出现」；
          // 流式区仍清空续写新轮，run_end 的权威覆盖逻辑不变
          if (answer) {
            options?.onInterimAnswer?.(answer)
            rawAnswer = ''
            answer = ''
            options?.onAnswerReplace?.('')
          }
          // 新 turn 开始 = 马上是 LLM 生成（含首字前的 prompt 读取），无条件切「生成回答…」——
          // 有工具时避免「检索规范库（xs）」把 prefill 也算进去（实测检索 1.8s 标签 6s）；
          // 无工具题（L0 闲聊/直答）此前会一直卡在「意图理解…」直到首字（2026-09-27 用户实测
          // 7.3s 全程显示意图理解、而步骤只记 0.1s）。若该轮又调工具，tool_start 会切回检索。
          setStage('generate')
        } else if (event.type === 'tool_start' || event.type === 'tool_end') {
          if (event.type === 'tool_start') setStage('search')
          liveThinkingSteps = applyAgentEventToThinking(event, liveThinkingSteps)
          options?.onThinking?.([...liveThinkingSteps])
        } else if (event.type === 'note') {
          liveThinkingSteps = applyAgentEventToThinking(event, liveThinkingSteps)
          options?.onThinking?.([...liveThinkingSteps])
        } else if (event.type === 'sop_flow') {
          // SOP 流程快照（plan/step/done）：payload 自足，整条替换式 upsert
          const flow = normalizeSopFlow(event.payload)
          if (flow) upsertSopFlow(flow)
        } else if (event.type === 'answer') {
          const finalContent = String(event.payload?.content || '')
          if (finalContent) {
            const cleaned = cleanStreamText(finalContent)
            // 边界规则改写（guard 把违规答案替换为拒答话术）：被顶替的流式正文
            // 同样快照上抛——否则用户看到「答案出现→整段被换」且无迹可寻
            if (answer.trim() && cleaned.trim() && cleaned.trim() !== answer.trim()) {
              options?.onInterimAnswer?.(answer)
            }
            rawAnswer = finalContent
            answer = cleaned
            options?.onAnswerReplace?.(answer)
          }
        } else if (event.type === 'message_delta') {
          setStage('generate')
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
          msgSeqs = Array.isArray(event.msg_seqs) ? event.msg_seqs : []
          traceMessages = Array.isArray(event.payload?.messages)
            ? event.payload.messages
            : []
          toolMessages = Array.isArray(event.payload?.messages)
            ? event.payload.messages.filter((m: any) => m.role === 'tool')
            : []
          const runNotes = Array.isArray(event.payload?.notes)
            ? event.payload.notes
            : []
          // SOP 流程终态：run_end 工具消息里的完整 sop_trace 覆盖 live 快照
          //（live 期步骤状态已逐帧回填，这里兜底中途断流/缺 done 快照的情况）
          for (const flow of extractSopFlowsFromToolMessages(traceMessages)) {
            upsertSopFlow(flow)
          }
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
          // 折叠头「总耗时」锚点（2026-09-30）：挂在轨迹首步上随持久化走；
          // = 分类阶段帧 ts（请求起点）→ 末步事件，各步 tag 之和才能与总耗时对上
          if (wallAnchorMs != null && answerFilteredTrace.length) {
            answerFilteredTrace[0] = { ...answerFilteredTrace[0], wallStartMs: wallAnchorMs }
          }
          options?.onThinking?.(answerFilteredTrace)
          liveThinkingSteps = answerFilteredTrace

          // run_end 里的最后一条 assistant 是权威最终答案：
          // 覆盖流式过程里可能出现的工具调用围栏，也兼容后端边界规则替换后的答案。
          const finalAssistant = [...traceMessages]
            .reverse()
            .find((m: any) => m.role === 'assistant' && !m.tool_calls)
          if (finalAssistant) {
            const finalRaw = String(finalAssistant.content || '')
            const cleanedFinal = cleanStreamText(finalRaw)
            if (cleanedFinal && cleanedFinal !== answer) {
              // run_end 权威覆盖发生真实替换时，被顶替的流式正文同样进快照
              if (answer.trim() && cleanedFinal.trim() !== answer.trim()) {
                options?.onInterimAnswer?.(answer)
              }
              rawAnswer = finalRaw
              answer = cleanedFinal
              options?.onAnswerReplace?.(answer)
            }
          }
        } else if (event.type === 'error') {
          throw new Error(String(event.payload?.message || 'Agent 对话错误'))
        } else if (event.type === 'warning') {
          const msg = String(event.message || event.payload?.message || '')
          if (msg) options?.onWarning?.(msg)
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
      msg_seqs: msgSeqs,
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
      sop_flows: Array.from(liveSopFlows.values()),
      fallback_used: false,
    }
  },
  fetchModels: () =>
    aichatApiClient.get<Array<{ name: string; configured: boolean }>>(
      '/llm_configs'
    ),
  searchReferences: (payload: InlineCitationSearchPayload) =>
    docsApiClient.post<{ items?: Record<string, any>[] }>(
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
    // 阶段三 B1：raw.citations 帧不带 library_id（docs-core relevant_citations 无此键），
    // 且去重时 citations 先入会挤掉 items 分支——用同消息 items 的 metadata.library_id
    // （多库扇出逐图标源，retrieve_service 已证）按 marker→target→doc 对账回填
    const items = Array.isArray(raw?.items) ? raw.items : []
    const libByMarker = new Map<string, string>()
    const libByTarget = new Map<string, string>()
    const libByDoc = new Map<string, string>()
    for (const item of items) {
      const lib = String(item?.library_id || item?.metadata?.library_id || '').trim()
      if (!lib) continue
      const cite = String(item?.cite || item?.metadata?.cite || '')
      const target = String(item?.citation_target_id || item?.item_id || item?.id || '')
      const doc = String(item?.doc_id || item?.metadata?.doc_id || '')
      if (cite && !libByMarker.has(cite)) libByMarker.set(cite, lib)
      if (target && !libByTarget.has(target)) libByTarget.set(target, lib)
      if (doc && !libByDoc.has(doc)) libByDoc.set(doc, lib)
    }
    const lookupLib = (marker: string, targetId: string, docId: string): string | undefined =>
      (marker && libByMarker.get(marker))
      || (targetId && libByTarget.get(targetId))
      || (docId && libByDoc.get(docId))
      || undefined
    if (Array.isArray(raw?.citations) && raw.citations.length > 0) {
      for (const citation of raw.citations) {
        const targetId = String(citation.target_id || citation.step_id || '')
        const marker = String(citation.marker || citation.cite || '')
        const docId = String(citation.doc_id || '')
        citations.push({
          target_id: targetId,
          target_type: 'content',
          doc_id: docId,
          doc_title: String(citation.doc_title || citation.source || ''),
          marker,
          page_idx: Number(citation.page_idx || 0),
          section_path: String(citation.section_path || ''),
          snippet: String(citation.snippet || ''),
          score: Number(citation.score || 0),
          library_id: lookupLib(marker, targetId, docId),
        })
      }
    }
    for (const item of items) {
      if (!item?.item_id && !item?.citation_target_id) continue
      citations.push({
        target_id: String(item.citation_target_id || item.item_id || ''),
        target_type: String(item.entity_type || 'content'),
        doc_id: String(item.doc_id || item.metadata?.doc_id || ''),
        doc_title: String(item.doc_title || item.metadata?.doc_title || item.title || ''),
        marker: String(item.cite || item.metadata?.cite || ''),
        page_idx: Number(item.page_idx ?? item.metadata?.page_idx ?? 0),
        section_path: String(item.section_path || item.metadata?.section_path || ''),
        snippet: String(item.text || ''),
        score: Number(item.rerank_score ?? item.score ?? 0),
        library_id: String(item.library_id || item.metadata?.library_id || '') || undefined,
      })
    }
  }
  // 去重
  const seen = new Set<string>()
  return citations.filter((citation) => {
    // 标记在本轮内全局唯一（K/T/E 各自递增），按标记去重最稳；
    // 无标记的条目退回按目标位置去重。
    const key = citation.marker
      ? `marker:${citation.marker}`
      : [citation.target_id, citation.doc_id, citation.page_idx, citation.section_path].join('::')
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

/**
 * 只保留最终回答里真实引用的标记（[K1]/[T1]/[E1]）。
 * 替代按文档名猜测的旧引用过滤。
 */
export function filterCitationsByMarkers(
  citations: AIChatCitation[],
  answer: string
): AIChatCitation[] {
  const used = new Set<string>()
  // 容忍括号内空格（`[ K32]`）：漏判会让该引用被整条滤掉，tag 无从挂载
  const re = /\[\s*([KTE]\s*\d+)\s*\]/g
  let match: RegExpExecArray | null
  while ((match = re.exec(answer || '')) !== null) used.add(match[1].replace(/\s+/g, ''))
  return (citations || []).filter(c => c.marker && used.has(c.marker))
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
  cleaned = stripFencedToolCallBlocks(cleaned)
  cleaned = stripPlainToolCallArtifacts(cleaned).trim()
  return stripOuterMarkdownFence(cleaned)
}

/** 兼容 ```json / 普通 ``` / ~~~ 围栏包裹的工具调用块：完整块移除，未闭合时截断到围栏起点。 */
function stripFencedToolCallBlocks(text: string): string {
  const openerRe = /^(```+|~{3,})\s*([a-zA-Z0-9_-]*)\s*$/gm
  let result = ''
  let cursor = 0
  let match: RegExpExecArray | null
  while ((match = openerRe.exec(text)) !== null) {
    const fenceMark = match[1]
    const bodyStart = openerRe.lastIndex
    const closingRe = new RegExp(`^${escapeRegExp(fenceMark)}\\s*$`, 'gm')
    closingRe.lastIndex = bodyStart
    const close = closingRe.exec(text)
    const body = close ? text.slice(bodyStart, close.index) : text.slice(bodyStart)
    if (fenceBodyIsToolCall(body)) {
      result += text.slice(cursor, match.index)
      if (!close) return result
      cursor = close.index + close[0].length
      openerRe.lastIndex = cursor
    }
  }
  return result + text.slice(cursor)
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/** 围栏内容是否是（或即将是）工具调用 JSON 数组。 */
function fenceBodyIsToolCall(body: string): boolean {
  const firstBracket = body.indexOf('[')
  if (firstBracket < 0) return false
  const scan = scanJsonArray(body, firstBracket)
  if (!scan) return false
  const candidate = body.slice(firstBracket, scan.end)
  if (scan.complete) {
    try {
      const parsed = JSON.parse(candidate)
      return Array.isArray(parsed) && parsed.some(
        (item) => item
          && typeof item === 'object'
          && typeof (item as any).name === 'string'
          && (item as any).arguments
          && typeof (item as any).arguments === 'object'
      )
    } catch {
      return false
    }
  }
  const normalized = candidate.replace(/\s/g, '')
  return normalized.startsWith('[{"') && (
    normalized.includes('"name"') || normalized.includes('"arguments"')
  )
}

/**
 * 剥掉模型把整段回答包裹的代码围栏（``` / ```markdown / ```` 等），
 * 避免流式阶段把整段回答渲染成原始代码块、结束后才“二次渲染”。
 * 仅在围栏完整包裹首尾且中间无其他围栏时剥离，避免误删正文里的代码块。
 */
function stripOuterMarkdownFence(text: string): string {
  const trimmed = String(text || '').trim()
  if (!trimmed) return trimmed
  const fence = /^(```+|~{3,})\s*([a-zA-Z0-9_-]*)\s*$/.exec(trimmed.split('\n')[0])
  if (!fence) return trimmed
  const fenceMark = fence[1]
  const lines = trimmed.split('\n')
  const last = lines[lines.length - 1].trim()
  if (last !== fenceMark) return trimmed
  const body = lines.slice(1, -1).join('\n')
  if (/```|~{3,}/.test(body)) return trimmed
  return body.trim()
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
    // 流式过程里 tool_end 的 result 可能被截断成 JSON 残片，残片不要漏进界面；
    // 但工具错误是纯文本（如「工具执行失败: ...」），必须如实显示，否则故障会被伪装成「见最终轨迹」。
    const text = String(content || '').trim()
    if (!text || text.startsWith('{') || text.startsWith('[')) {
      return '工具已返回结果（完整内容见最终轨迹）'
    }
    return text.slice(0, maxLength)
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

  const normalizeItem = (entry: any, index: number): ThinkingTraceItem | null => {
    if (!entry || typeof entry !== 'object') return null
    const rawMeta = entry.metadata && typeof entry.metadata === 'object' ? entry.metadata : {}
    // 两形态合一：LLM 投影把 metadata 的引用/位置键提升到条目顶层且删掉 item_id
    // （2026-10-16 复盘），这里把顶层键合回 metadata，下游（toCitation 跳页、引用归属）
    // 按既有 metadata 读法照常工作；item_id 缺失的历史行按位置补稳定 key（整条不再被丢）
    const metadata: Record<string, any> = { ...rawMeta }
    for (const key of ['doc_id', 'doc_title', 'cite', 'page_idx', 'page_label', 'section_path', 'library_id']) {
      if (metadata[key] === undefined && entry[key] !== undefined) metadata[key] = entry[key]
    }
    const itemId = String(entry.item_id || entry.id || entry.citation_target_id || '')
      || `item-${index}-${String(entry.doc_id || metadata.doc_title || entry.title || '').slice(0, 24)}`
    const title = String(entry.title || entry.name || metadata.doc_title || '')
    const text = String(entry.text || entry.description || entry.content || '')
    if (!text) return null
    return {
      item_id: itemId,
      entity_type: String(entry.entity_type || 'content'),
      doc_id: String(entry.doc_id || metadata.doc_id || ''),
      doc_title: String(entry.doc_title || metadata.doc_title || title),
      title,
      text,
      cite: String(entry.cite || metadata.cite || ''),
      // 优先展示融合/重排后的相关度（0~1 量级），原始 dense/sparse 分可能超过 1
      score: Number(
        entry.rerank_score
        ?? metadata.fusion_score
        ?? metadata.normalized_score
        ?? entry.score
        ?? 0
      ),
      metadata,
    }
  }

  if (Array.isArray(raw.items)) {
    const items = raw.items
      .map((entry: any, index: number) => normalizeItem(entry, index))
      .filter(Boolean) as ThinkingTraceItem[]
    return items.length ? items : undefined
  }
  if (Array.isArray(raw.entities)) {
    const items = raw.entities
      .map((entry: any, index: number) => normalizeItem(entry, index))
      .filter(Boolean) as ThinkingTraceItem[]
    return items.length ? items : undefined
  }
  return undefined
}

/** 参数绑定快照清洗：只收标量、截断长串、限条目数（展示层用，防脏负载） */
function sanitizeBindings(raw: any): Record<string, string | number | null> | undefined {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return undefined
  const out: Record<string, string | number | null> = {}
  let count = 0
  for (const [key, value] of Object.entries(raw)) {
    if (count >= 8) break
    const name = String(key).slice(0, 40)
    if (value === null || value === undefined) {
      out[name] = null
    } else if (typeof value === 'number' || typeof value === 'boolean') {
      out[name] = Number(value)
    } else if (typeof value === 'string') {
      out[name] = value.length > 60 ? value.slice(0, 60) + '…' : value
    } else {
      continue
    }
    count += 1
  }
  return Object.keys(out).length ? out : undefined
}

/** 结果标量清洗：数字/短字符串保留，其余丢弃 */
function sanitizeStepResult(raw: any): string | number | null | undefined {
  if (raw === null || raw === undefined) return undefined
  if (typeof raw === 'number') return Number.isFinite(raw) ? raw : undefined
  if (typeof raw === 'boolean') return Number(raw)
  if (typeof raw === 'string') return raw.length > 80 ? raw.slice(0, 80) + '…' : raw
  return undefined
}

/** sop_flow 事件 payload → SopFlowState（shape 不认识的返回 undefined，静默丢弃） */
export function normalizeSopFlow(payload: any): SopFlowState | undefined {
  const raw = payload ?? {}
  if (typeof raw.sop_id !== 'string' || !raw.sop_id || !Array.isArray(raw.steps)) return undefined
  const steps = raw.steps.filter((s: any) => s && typeof s.step_id === 'string').map((s: any) => {
    const bindings = sanitizeBindings(s.bindings)
    const result = sanitizeStepResult(s.result)
    return {
      step_id: String(s.step_id),
      step_name: String(s.step_name || s.step_id),
      tool: String(s.tool || 'auto'),
      status: s.status === 'success' ? 'success' : (s.status === 'pending' ? 'pending' : 'failed'),
      ...(Number(s.duration_ms) > 0 ? { duration_ms: Number(s.duration_ms) } : {}),
      ...(s.error ? { error: String(s.error).slice(0, 200) } : {}),
      ...(bindings ? { bindings } : {}),
      ...(result !== undefined ? { result } : {}),
    } as SopFlowState['steps'][number]
  })
  return {
    sop_id: raw.sop_id,
    sop_name: String(raw.sop_name || raw.sop_id),
    total: Number(raw.total) || steps.length,
    done: Number(raw.done) || steps.filter((s: SopFlowState['steps'][number]) => s.status !== 'pending').length,
    running: Boolean(raw.running),
    steps,
  }
}

/**
 * 从 run_end 工具消息重建 SOP 流程终态（回放/断流兜底）。
 * 判据=content JSON 含 sop_trace 数组；步状态与耗时以 trace 记录为准。
 */
export function extractSopFlowsFromToolMessages(
  messages: Array<{ role?: string; content?: string }>
): SopFlowState[] {
  const flows: SopFlowState[] = []
  for (const message of messages) {
    let raw: any
    try {
      raw = JSON.parse(message.content || '{}')
    } catch {
      continue
    }
    if (!raw || typeof raw !== 'object' || !Array.isArray(raw.sop_trace) || !Array.isArray(raw.steps)) continue
    if (typeof raw.sop_id !== 'string' || !raw.sop_id) continue
    const steps = raw.steps.map((entry: any) => {
      const detail = (Array.isArray(raw.sop_trace) ? raw.sop_trace : []).find(
        (t: any) => t && t.step_id === entry?.step_id
      )
      const status = String(entry?.status ?? detail?.status ?? 'pending')
      const durationSec = Number(detail?.duration ?? 0)
      const error = detail?.error ? String(detail.error).slice(0, 200) : undefined
      // 参数绑定/结果：优先取 trace 明细（新字段），旧消息没有则缺省不渲染
      const bindings = sanitizeBindings(detail?.bindings ?? entry?.bindings)
      const result = sanitizeStepResult(
        detail?.result !== undefined ? detail.result : (entry?.outputs as any)?.result
      )
      return {
        step_id: String(entry?.step_id || detail?.step_id || ''),
        step_name: String(entry?.step_name || detail?.step_name || entry?.step_id || ''),
        tool: String(detail?.tool || 'auto'),
        status: status === 'success' ? 'success' : (status === 'pending' ? 'pending' : 'failed'),
        ...(durationSec > 0 ? { duration_ms: Math.round(durationSec * 1000) } : {}),
        ...(error ? { error } : {}),
        ...(bindings ? { bindings } : {}),
        ...(result !== undefined ? { result } : {}),
      } as SopFlowState['steps'][number]
    })
    flows.push({
      sop_id: raw.sop_id,
      sop_name: String(raw.sop_name || raw.sop_id),
      total: steps.length,
      done: steps.filter((s: SopFlowState['steps'][number]) => s.status !== 'pending').length,
      running: false,
      steps,
      ...(Array.isArray(raw.missing_report) && raw.missing_report.length
        ? { missing_report: raw.missing_report }
        : {}),
    })
  }
  return flows
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
  event: { type?: string; turn?: number; payload?: any; ts?: number },
  steps: ThinkingTraceStep[]
): ThinkingTraceStep[] {
  const turn = event?.turn != null ? Number(event.turn) : undefined
  // 事件墙钟（后端每帧带 ts，秒）：折叠头总耗时与每步耗时标签用（2026-09-27）
  const atMs = Number(event?.ts) > 0 ? Number(event.ts) * 1000 : undefined
  const stamp = atMs != null ? { atMs } : {}
  if (event?.type === 'turn_start') {
    return [...steps, { kind: 'turn', detail: '', ...stamp, ...(turn != null ? { turn } : {}) }]
  }
  if (event?.type === 'note') {
    const detail = String(event.payload?.detail || event.payload?.message || '')
    if (!detail) return steps
    const durationMs = Number(event.payload?.duration_ms)
    return [
      ...steps,
      {
        kind: 'note',
        detail,
        ...stamp,
        ...(durationMs > 0 ? { durationMs } : {}),
        // attach=pair：该便签并入上一对工具步显示（预检索完成说明等，2026-09-30）
        ...(event.payload?.attach ? { attach: String(event.payload.attach) } : {}),
        ...(turn != null ? { turn } : {}),
      },
    ]
  }
  if (event?.type === 'tool_start') {
    return [
      ...steps,
      {
        kind: 'call',
        tool: String(event.payload?.name || 'unknown'),
        detail: JSON.stringify(event.payload?.args || {}),
        // 后端预检索（首轮直达，替模型先跑）：标题显示为「预检索」（2026-09-30）
        ...(event.payload?.injected ? { injected: true } : {}),
        ...stamp,
        ...(turn != null ? { turn } : {}),
      },
    ]
  }
  if (event?.type === 'tool_end') {
    const durationMs = Number(event.payload?.duration_ms)
    const reusedMs = Number(event.payload?.reused_ms)
    const resultStep: ThinkingTraceStep = {
      kind: 'result',
      tool: String(event.payload?.name || 'unknown'),
      detail: summarizeToolResult(event.payload?.result),
      isError: Boolean(event.payload?.is_error),
      // 实时 result 可能被截断，完整条目等 run_end 用消息重建
      ...stamp,
      ...(turn != null ? { turn } : {}),
      ...(durationMs > 0 ? { durationMs } : {}),
      // 并行预检复用：预检方真实耗时（供「并行预检 X.Xs」两行标注，2026-09-30）
      ...(reusedMs > 0 ? { reusedMs } : {}),
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
  const list = messages || []
  for (const message of list) {
    if (message?.role === 'assistant') {
      turn += 1
      const toolCalls = Array.isArray(message.tool_calls) ? message.tool_calls : []
      if (toolCalls.length) {
        // 注入消息（首轮直达）的 meta 标记由服务端 meta 透传（injected_tool_call）：标为预检索步
        const injectedFlag = Boolean(message?.injected_tool_call || message?.meta?.injected_tool_call)
        for (const call of toolCalls) {
          steps.push({
            kind: 'call',
            tool: String(call?.name || 'unknown'),
            detail: JSON.stringify(call?.arguments || {}),
            ...(injectedFlag ? { injected: true } : {}),
            turn,
          })
        }
      }
      // 说明：原在此给最终回答消息补「汇总证据并生成最终回答」标记行，2026-09-30 删除——
      // 它不携带新信息（答案正文紧随其后、「模型调用（第 N 轮）」已标出生成轮），且与后端
      // 「生成完成」收尾便签语义相近、顺序颠倒（用户实拍反馈困惑）。
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
    const durationMs = typeof note === 'string' ? 0 : Number((note as any)?.duration_ms)
    const attach = typeof note === 'string' ? '' : String((note as any)?.attach || '')
    if (detail) {
      steps.push({
        kind: 'note',
        detail,
        ...(durationMs > 0 ? { durationMs } : {}),
        ...(attach ? { attach } : {}),
      })
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
          ...(live.atMs != null ? { atMs: live.atMs } : {}),
          ...(live.turn != null ? { turn: live.turn } : {}),
          ...(live.injected ? { injected: true } : {}),
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
          ...(live.atMs != null ? { atMs: live.atMs } : {}),
          ...(live.injected ? { injected: true } : {}),
          ...(live.reusedMs ? { reusedMs: live.reusedMs } : {}),
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
          ...(live.durationMs ? { durationMs: live.durationMs } : {}),
          ...(live.atMs != null ? { atMs: live.atMs } : {}),
          ...(live.turn != null ? { turn: live.turn } : {}),
          ...(live.attach ? { attach: live.attach } : {}),
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
