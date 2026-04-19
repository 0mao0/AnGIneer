import type {
  DocBlockNode,
  StructuredNodeUpdatePayload
} from '../../../types/knowledge'

export const ROOT_PARENT_VALUE = '__root__'

export interface IndexTreeOption {
  value: string
  label: string
}

export interface IndexTreeEditForm {
  plain_text: string
  math_content: string
  table_html: string
  caption: string
  footnote: string
  parent_block_uid: string
  derived_title_level: number | null
  merge_into_block_uid: string | undefined
}

export interface SplitSegmentDraft {
  id: string
  plain_text: string
}

/* 按文档顺序构造节点下拉选项。 */
export function buildOrderedNodeOptions(nodeMap: Map<string, DocBlockNode>): IndexTreeOption[] {
  return [...nodeMap.values()]
    .sort((a, b) => {
      if ((a.page_idx || 0) !== (b.page_idx || 0)) return (a.page_idx || 0) - (b.page_idx || 0)
      return (a.block_seq || 0) - (b.block_seq || 0)
    })
    .map(node => ({
      value: node.block_uid || node.id,
      label: `P${Number(node.page_idx || 0) + 1} · B${node.block_seq || 0} · ${(node.plain_text || node.title_path || node.block_type || '未命名').slice(0, 80)}`
    }))
}

/* 基于节点内容初始化编辑表单。 */
export function createEditFormFromNode(node: DocBlockNode): IndexTreeEditForm {
  return {
    plain_text: String(node.plain_text || ''),
    math_content: String(node.math_content || ''),
    table_html: String(node.table_html || ''),
    caption: String(node.caption || ''),
    footnote: String(node.footnote || ''),
    parent_block_uid: node.parent_uid || ROOT_PARENT_VALUE,
    derived_title_level: typeof node.derived_level === 'number' ? node.derived_level : null,
    merge_into_block_uid: undefined
  }
}

/* 仅提取节点真实发生变化的字段。 */
export function buildNodeEditPayload(node: DocBlockNode, form: IndexTreeEditForm): StructuredNodeUpdatePayload | null {
  const payload: StructuredNodeUpdatePayload = {
    blockId: node.block_uid || node.id
  }
  if (form.plain_text !== String(node.plain_text || '')) {
    payload.plain_text = form.plain_text
  }
  if (form.math_content !== String(node.math_content || '')) {
    payload.math_content = form.math_content
  }
  if (form.table_html !== String(node.table_html || '')) {
    payload.table_html = form.table_html
  }
  if (form.caption !== String(node.caption || '')) {
    payload.caption = form.caption
  }
  if (form.footnote !== String(node.footnote || '')) {
    payload.footnote = form.footnote
  }
  const currentParentId = node.parent_uid || null
  const nextParentId = form.parent_block_uid === ROOT_PARENT_VALUE
    ? null
    : (form.parent_block_uid || null)
  if (nextParentId !== currentParentId) {
    payload.parent_block_uid = nextParentId
  }
  const currentLevel = typeof node.derived_level === 'number' ? node.derived_level : null
  const nextLevel = typeof form.derived_title_level === 'number'
    ? form.derived_title_level
    : null
  if (nextLevel !== currentLevel) {
    payload.derived_title_level = nextLevel
  }
  const mergeTargetId = form.merge_into_block_uid || null
  if (mergeTargetId) {
    payload.merge_into_block_uid = mergeTargetId
  }
  return Object.keys(payload).length > 1 ? payload : null
}

/* 将节点更新载荷转成用户可感知的动作标签。 */
export function getNodeEditActionLabels(payload: StructuredNodeUpdatePayload | null): string[] {
  if (!payload) return []
  const actions: string[] = []
  if ('plain_text' in payload) actions.push('更新识别文本')
  if ('math_content' in payload) actions.push('更新公式源码')
  if ('table_html' in payload) actions.push('更新表格 HTML')
  if ('caption' in payload) actions.push('更新题注')
  if ('footnote' in payload) actions.push('更新注释')
  if ('parent_block_uid' in payload) {
    actions.push(payload.parent_block_uid ? '调整父级节点' : '移动到根节点')
  }
  if ('derived_title_level' in payload) {
    actions.push(
      typeof payload.derived_title_level === 'number'
        ? `调整为 L${payload.derived_title_level}`
        : '取消标题层级'
    )
  }
  if ('merge_into_block_uid' in payload) actions.push('合并到目标 block')
  return actions
}

/* 统计拆分片段的有效字数。 */
export function getSplitSegmentCharCount(text: string): number {
  return text.trim().length
}

/* 创建拆分片段草稿对象。 */
export function createSplitSegmentDraft(plain_text = ''): SplitSegmentDraft {
  return {
    id: `${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
    plain_text
  }
}

/* 优先按句读边界拆分文本。 */
export function splitTextBySentenceBoundary(text: string): string[] {
  const normalized = text.trim()
  if (!normalized) return []
  const fragments = normalized
    .split(/(?<=[。！？!?；;])/)
    .map(fragment => fragment.trim())
    .filter(Boolean)
  if (fragments.length >= 2) return fragments
  if (normalized.length < 2) return [normalized]
  const midpoint = Math.max(1, Math.floor(normalized.length / 2))
  return [normalized.slice(0, midpoint).trim(), normalized.slice(midpoint).trim()].filter(Boolean)
}

/* 基于原文生成初始拆分片段。 */
export function buildInitialSplitSegments(text: string): SplitSegmentDraft[] {
  const normalized = text.trim()
  if (!normalized) {
    return [createSplitSegmentDraft(''), createSplitSegmentDraft('')]
  }
  const paragraphParts = normalized
    .split(/\r?\n\s*\r?\n/g)
    .map(part => part.trim())
    .filter(Boolean)
  const lineParts = normalized
    .split(/\r?\n/g)
    .map(part => part.trim())
    .filter(Boolean)
  const rawParts = paragraphParts.length >= 2
    ? paragraphParts
    : (lineParts.length >= 2 ? lineParts : splitTextBySentenceBoundary(normalized))
  const ensuredParts = rawParts.length >= 2 ? rawParts : [normalized, '']
  return ensuredParts.map(part => createSplitSegmentDraft(part))
}
