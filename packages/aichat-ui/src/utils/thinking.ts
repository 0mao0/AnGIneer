import type { AIChatCitation, ThinkingTraceItem, ThinkingTraceStep } from '../types/chat'

export interface ThinkingGroupStep {
  index: number
  kind: 'pair' | 'note'
  tool?: string
  label?: string
  detail?: string
  callDetail?: string
  resultDetail?: string
  isError?: boolean
  durationMs?: number
  turn?: number
  citations?: AIChatCitation[]
  resultItems?: ThinkingTraceItem[]
  resultNote?: string
}

/**
 * 把"调用 + 返回"配对成一步；轮次/说明类步骤原样保留，方便展示完整执行过程。
 * 所有可见步骤（意图判断、工具调用、结果、最终回答）按顺序编号。
 */
export function groupThinkingSteps(steps: ThinkingTraceStep[]): ThinkingGroupStep[] {
  const groups: ThinkingGroupStep[] = []
  let open: ThinkingGroupStep | null = null

  const pushNote = (step: ThinkingTraceStep) => {
    open = null
    groups.push({
      index: groups.length + 1,
      kind: 'note',
      label: step.kind === 'turn' ? `第 ${step.turn || '?'} 轮` : undefined,
      detail: step.detail,
      turn: step.turn,
    })
  }

  for (const step of steps || []) {
    if (step.kind === 'call') {
      open = {
        index: groups.length + 1,
        kind: 'pair',
        tool: step.tool || 'unknown',
        callDetail: step.detail,
        turn: step.turn,
      }
      groups.push(open)
    } else if (step.kind === 'result') {
      if (open && open.kind === 'pair' && open.tool === step.tool && !open.resultDetail) {
        open.resultDetail = step.detail
        open.isError = step.isError
        open.durationMs = step.durationMs
        open.citations = step.citations
        open.resultItems = step.resultItems
        open.resultNote = step.resultNote
      } else {
        open = {
          index: groups.length + 1,
          kind: 'pair',
          tool: step.tool || 'unknown',
          callDetail: '',
          resultDetail: step.detail,
          isError: step.isError,
          durationMs: step.durationMs,
          citations: step.citations,
          resultItems: step.resultItems,
          resultNote: step.resultNote,
          turn: step.turn,
        }
        groups.push(open)
      }
    } else {
      pushNote(step)
    }
  }
  return groups
}

/**
 * 把工具参数 JSON 转成可读文本，如 {"query":"上航数联"} → query = 上航数联。
 */
export function formatThinkingArgDetail(detail: string): string {
  try {
    const parsed = JSON.parse(detail)
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      return Object.entries(parsed)
        .map(([key, value]) => `${key} = ${typeof value === 'string' ? value : JSON.stringify(value)}`)
        .join('，')
    }
  } catch {
    // 保留原文
  }
  return detail
}

/**
 * 给每个可见步骤生成带序号的标题，说明类与工具调用/返回统一展示，
 * 方便用户按顺序看懂完整思考链路。
 */
export function formatThinkingStepLabel(group: ThinkingGroupStep): string {
  const title = formatThinkingStepTitle(group)
  return group.index ? `${group.index}. ${title}` : title
}

/** 步骤标题（不含序号），供"序号+标题加粗、其余常规"的拆分渲染。 */
export function formatThinkingStepTitle(group: ThinkingGroupStep): string {
  if (group.kind === 'note') return group.label || group.detail || ''
  return group.callDetail ? `调用工具：${group.tool}` : `工具返回：${group.tool}`
}

/** 结果步骤是否带候选条目、可以展开查看。 */
export function isResultExpandable(group: ThinkingGroupStep): boolean {
  return Boolean(group.resultItems && group.resultItems.length > 0)
}

/** 组内候选的最高相关度，用于把分数归一化成直观百分比。 */
export function getResultMaxScore(group: ThinkingGroupStep): number {
  return (group.resultItems || []).reduce(
    (max, item) => Math.max(max, Number(item.score) || 0),
    0
  )
}

/** 相关度按组内最高分归一化展示为百分比；没有有效分数时显示占位符。 */
export function formatResultScore(score?: number, maxScore?: number): string {
  const max = Number(maxScore) || 0
  const value = Number(score) || 0
  if (max <= 0) return '—'
  return `${Math.round((value / max) * 100)}%`
}

/** 统计思考过程里的可见步骤总数。 */
export function countThinkingSteps(groups: ThinkingGroupStep[]): number {
  return (groups || []).length
}

/** 汇总工具执行耗时（ms），用于标题上的总耗时展示。 */
export function sumThinkingDuration(groups: ThinkingGroupStep[]): number {
  return (groups || []).reduce((sum, group) => sum + (group.durationMs || 0), 0)
}

/** 耗时统一展示为秒，最多一位小数。 */
export function formatDuration(ms?: number): string {
  if (!ms || ms <= 0) return ''
  return `${(ms / 1000).toFixed(1)}秒`
}
