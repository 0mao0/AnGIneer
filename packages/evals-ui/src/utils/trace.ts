/** 评测 trace 的纯渲染模型：把 AgentEvent 流切成可渲染行。
 *
 * 只做分组与字段提升，不猜语义；未知事件类型原样保留（落通用行），
 * 这样引擎新增工具/事件时页面不会静默丢节点。
 */
import type { EvalTrace, EvalTraceSummary } from '../types/eval'

export interface TracePromptMessage {
  role: string
  content: string
  truncated?: boolean
}

export type TraceRow =
  | {
      kind: 'intent'
      key: string
      level: string
      serviceMode: string
      reason: string
      timing?: number
    }
  | { kind: 'turn'; key: string; turn: number; label: string }
  | {
      kind: 'prompt'
      key: string
      turn: number
      messageCount: number
      promptChars: number
      truncated: boolean
      messagesOmitted: boolean
      messages: TracePromptMessage[]
    }
  | {
      kind: 'tool'
      key: string
      turn: number
      name: string
      args?: Record<string, unknown>
      durationMs?: number
      isError: boolean
      injected: boolean
      result: string
      pending?: boolean
    }
  | {
      kind: 'note'
      key: string
      turn: number
      detail: string
      durationMs?: number
      promptTokens?: number
      ttftMs?: number
    }
  | { kind: 'error'; key: string; turn: number; message: string }
  | { kind: 'run_end'; key: string; summary: EvalTraceSummary }
  | { kind: 'unknown'; key: string; turn: number; type: string; payload: Record<string, unknown> }

export interface TraceRowInput {
  trace?: EvalTrace | null
  intent?: Record<string, unknown> | null
  stageTimings?: Record<string, number> | null
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function asNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}
}

function asStringList(value: unknown): string[] {
  return Array.isArray(value) ? value.map(item => String(item)) : []
}

function normalizePromptMessages(value: unknown): TracePromptMessage[] {
  if (!Array.isArray(value)) return []
  return value.map(item => {
    const record = asRecord(item)
    const content = record.content
    return {
      role: asString(record.role) || '?',
      content:
        typeof content === 'string'
          ? content
          : content === null || content === undefined
            ? ''
            : JSON.stringify(content),
      truncated: Boolean(record.truncated),
    }
  })
}

function normalizeSummary(
  summary: EvalTraceSummary | null | undefined,
  payload: Record<string, unknown>,
  toolCalls: number,
  turns: number
): EvalTraceSummary {
  const raw = asRecord(summary)
  const finalOutcome = asString(raw.final_outcome) || asString(payload.final_outcome)
  return {
    turns: asNumber(raw.turns) ?? asNumber(payload.turns) ?? turns,
    tool_calls: asNumber(raw.tool_calls) ?? toolCalls,
    duration_ms: asNumber(raw.duration_ms),
    agent_loop_ms: asNumber(raw.agent_loop_ms) ?? asNumber(payload.agent_loop_ms),
    reason: asString(raw.reason) || asString(payload.reason),
    final_outcome: finalOutcome || null,
    path_trace: asStringList(raw.path_trace).length
      ? asStringList(raw.path_trace)
      : asStringList(payload.path_trace),
  }
}

export function buildTraceRows(input: TraceRowInput): TraceRow[] {
  const trace = input.trace
  const events = trace && Array.isArray(trace.events) ? trace.events : []
  if (!events.length) return []

  const intent = asRecord(input.intent)
  const rows: TraceRow[] = [
    {
      kind: 'intent',
      key: 'intent',
      level: asString(intent.intent_level) || '—',
      serviceMode: asString(intent.service_mode),
      reason: asString(intent.reason),
      timing: asNumber(input.stageTimings?.intent),
    },
  ]

  const pendingTools = new Map<string, { args?: Record<string, unknown>; injected: boolean }>()
  let currentTurn: number | null = null
  let maxTurn = 0
  let toolCalls = 0
  let rowIndex = 0

  const ensureTurn = (turn: number) => {
    if (currentTurn === turn) return
    currentTurn = turn
    maxTurn = Math.max(maxTurn, turn)
    rows.push({
      kind: 'turn',
      key: `turn-${turn}-${rowIndex++}`,
      turn,
      label: turn === 0 ? '预检' : `第 ${turn} 轮`,
    })
  }

  for (const event of events) {
    const type = asString(event?.type)
    const turn = typeof event?.turn === 'number' ? event.turn : 0
    const payload = asRecord(event?.payload)

    // message_* 只服务流式展示；turn_end 的 tool_results 与工具行重复。
    if (
      type === 'run_start' ||
      type === 'turn_end' ||
      type === 'message_start' ||
      type === 'message_delta' ||
      type === 'message_end'
    ) {
      continue
    }

    if (type === 'turn_start') {
      ensureTurn(turn)
      continue
    }

    if (type === 'llm_request') {
      ensureTurn(turn)
      const messages = normalizePromptMessages(payload.messages)
      rows.push({
        kind: 'prompt',
        key: `prompt-${rowIndex++}`,
        turn,
        messageCount: asNumber(payload.message_count) ?? messages.length,
        promptChars: asNumber(payload.prompt_chars) ?? 0,
        truncated: Boolean(payload.truncated),
        messagesOmitted: Boolean(payload.messages_omitted),
        messages,
      })
      continue
    }

    if (type === 'tool_start') {
      const callId = asString(payload.call_id)
      if (callId) {
        pendingTools.set(callId, {
          args: Object.keys(asRecord(payload.args)).length ? asRecord(payload.args) : undefined,
          injected: Boolean(payload.injected),
        })
      }
      continue
    }

    if (type === 'tool_end') {
      ensureTurn(turn)
      const callId = asString(payload.call_id)
      const started = pendingTools.get(callId)
      pendingTools.delete(callId)
      toolCalls += 1
      rows.push({
        kind: 'tool',
        key: `tool-${callId || rowIndex++}`,
        turn,
        name: asString(payload.name) || asString(started?.args?.name) || 'tool',
        args: started?.args,
        durationMs: asNumber(payload.duration_ms),
        isError: Boolean(payload.is_error),
        injected: Boolean(payload.injected) || Boolean(started?.injected),
        result: asString(payload.result),
      })
      continue
    }

    if (type === 'note') {
      ensureTurn(turn)
      rows.push({
        kind: 'note',
        key: `note-${rowIndex++}`,
        turn,
        detail: asString(payload.detail),
        durationMs: asNumber(payload.duration_ms),
        promptTokens: asNumber(payload.prompt_tokens),
        ttftMs: asNumber(payload.first_delta_ms),
      })
      continue
    }

    if (type === 'error') {
      ensureTurn(turn)
      rows.push({
        kind: 'error',
        key: `error-${rowIndex++}`,
        turn,
        message: asString(payload.message) || '未知错误',
      })
      continue
    }

    if (type === 'run_end') {
      rows.push({
        kind: 'run_end',
        key: 'run-end',
        summary: normalizeSummary(input.trace?.summary, payload, toolCalls, maxTurn),
      })
      continue
    }

    // 新事件类型：保留下来，不让页面静默丢节点。
    ensureTurn(turn)
    rows.push({
      kind: 'unknown',
      key: `unknown-${rowIndex++}`,
      turn,
      type: type || 'unknown',
      payload,
    })
  }

  // 只有 tool_start、没有 tool_end 的（中断/异常）：补一张“未完成”卡。
  for (const [callId, started] of pendingTools) {
    rows.push({
      kind: 'tool',
      key: `tool-pending-${callId}`,
      turn: currentTurn ?? 0,
      name: 'tool',
      args: started.args,
      isError: false,
      injected: started.injected,
      result: '',
      pending: true,
    })
  }

  return rows
}
