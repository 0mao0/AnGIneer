/**
 * 联动高亮组工具：给定激活目标，收集同一组应同时点亮的高亮框。
 * - 目标节点自身的全部高亮（公式主体、公式编号、合并框等）；
 * - 通过 linkedFormulaItemIds 关联到该目标的解释段高亮（公式的“式中”说明）。
 */
export interface LinkedHighlightLike {
  id: string
  itemId: string
  structuredItemId?: string
  linkedFormulaItemIds?: string[]
}

export interface GraphNodeLike {
  id: string
  block_type?: string
  block_uid?: string
  parent_uid?: string | null
}

const isFormulaLikeNode = (node: GraphNodeLike | undefined): boolean => {
  const type = String(node?.block_type || '').toLowerCase()
  return type === 'formula' || type === 'equation_interline' || type === 'equation'
}

/** 沿 parent_uid 向上找最近的标题块，作为“章节根”。 */
export const findSectionRootId = (
  nodes: GraphNodeLike[],
  nodeId: string | null
): string | null => {
  if (!nodeId) return null
  const byId = new Map<string, GraphNodeLike>()
  for (const node of nodes || []) {
    byId.set(String(node.id || ''), node)
  }
  let current = byId.get(nodeId) || null
  while (current) {
    if (String(current.block_type || '').toLowerCase() === 'title') {
      return String(current.id || '')
    }
    const parentId = String(current.parent_uid || '').trim()
    current = parentId ? byId.get(parentId) || null : null
  }
  return null
}

/** 收集某节点（章节根）下的全部后代节点 id（BFS，不含根自身）。 */
export const collectDescendantNodeIds = (
  nodes: GraphNodeLike[],
  rootId: string | null
): string[] => {
  if (!rootId) return []
  const childrenByParent = new Map<string, string[]>()
  for (const node of nodes || []) {
    const parentId = String(node.parent_uid || '').trim()
    if (!parentId) continue
    const list = childrenByParent.get(parentId) || []
    list.push(String(node.id || ''))
    childrenByParent.set(parentId, list)
  }
  const result: string[] = []
  const queue = [rootId]
  while (queue.length) {
    const current = queue.shift() as string
    for (const child of childrenByParent.get(current) || []) {
      result.push(child)
      queue.push(child)
    }
  }
  return result
}

/**
 * 收集一个激活目标应同时点亮的高亮组：
 * - 普通块：所在章节的标题 + 全部后代块（tag 表示整个章节）；
 * - 公式块：公式自身 + 通过 linkedFormulaItemIds 关联的解释段；
 * - 目标节点自身的全部高亮与关联高亮始终并入。
 */
export const collectGroupHighlightIds = (
  highlights: LinkedHighlightLike[],
  nodes: GraphNodeLike[],
  activeItemId: string | null,
  primaryHighlightId: string | null = null
): string[] => {
  if (!activeItemId) return []
  const nodeList = nodes || []
  const activeNode = nodeList.find(
    node => String(node.id || '') === activeItemId || String(node.block_uid || '') === activeItemId
  )
  let groupNodeIds: string[] = [activeItemId]
  if (activeNode && !isFormulaLikeNode(activeNode)) {
    const sectionRootId = findSectionRootId(nodeList, activeItemId)
    if (sectionRootId) {
      groupNodeIds = [sectionRootId, ...collectDescendantNodeIds(nodeList, sectionRootId)]
    }
  }
  const ids = new Set<string>()
  if (primaryHighlightId) ids.add(primaryHighlightId)
  for (const groupId of groupNodeIds) {
    for (const highlight of highlights || []) {
      if (highlight.itemId === groupId || highlight.structuredItemId === groupId) {
        ids.add(highlight.id)
      }
      if (highlight.linkedFormulaItemIds?.includes(groupId)) {
        ids.add(highlight.id)
      }
    }
  }
  return Array.from(ids)
}

export function collectLinkedHighlightIds(
  highlights: LinkedHighlightLike[],
  activeItemId: string | null,
  primaryHighlightId: string | null = null
): string[] {
  return collectGroupHighlightIds(highlights, [], activeItemId, primaryHighlightId)
}
