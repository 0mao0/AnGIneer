import { computed, ref, watch, type ComputedRef } from 'vue'
import type { DocBlockNode, DocBlocksGraph, StructuredIndexItem } from '../types/knowledge'
import { buildDocBlocksGraphIndex } from './useDocBlocksGraph'
import { findNodeForItem, findNodeForItemExact, isItemActive } from '../utils/knowledge'

export interface GraphViewportState {
  x: number
  y: number
  scale: number
}

export interface ParsedPdfIndexTreeProps {
  activeTab: 'Preview_HTML' | 'Preview_Markdown' | 'Preview_IndexList' | 'Preview_IndexTree' | 'Preview_IndexGraph'
  activeLinkedItemId: string | null
  graphData?: DocBlocksGraph | null
}

interface UseParsedPdfIndexTreeOptions {
  flatIndexItems: ComputedRef<StructuredIndexItem[]>
  emitToggleTreeExpand?: (id: string) => void
  emitToggleGraphExpand?: (id: string) => void
  emitSelectItem?: (id: string) => void
  emitUpdateGraphViewport?: (state: GraphViewportState) => void
}

/**
 * 管理解析文档的 IndexTree / IndexGraph 状态与交互。
 */
export function useParsedPdfIndexTree(
  props: ParsedPdfIndexTreeProps,
  options: UseParsedPdfIndexTreeOptions
) {
  const expandedNodeIds = ref<Set<string>>(new Set())
  const expandedGraphNodeIds = ref<Set<string>>(new Set())
  const graphViewportState = ref<GraphViewportState | null>(null)

  const hasGraphData = computed(() => (
    Boolean(props.graphData?.nodes?.length)
  ))

  const graphNodeLookup = computed(() => {
    const map = new Map<string, DocBlockNode>()
    if (!props.graphData?.nodes?.length) return map
    for (const node of props.graphData.nodes) {
      const id = String(node.id || '').trim()
      if (id) {
        map.set(id, node)
      }
    }
    return map
  })

  const graphIndex = computed(() => buildDocBlocksGraphIndex(props.graphData))
  const nodeMap = computed(() => graphIndex.value.nodeMap)
  const childrenMap = computed(() => graphIndex.value.childrenMap)
  const roots = computed(() => graphIndex.value.roots)

  /* 计算节点向上的祖先路径，用于自动展开树链路。 */
  const getAncestors = (id: string): string[] => {
    const ancestors: string[] = []
    let currentId: string | undefined = id
    while (currentId) {
      const node = nodeMap.value.get(currentId)
      if (node?.parent_uid && nodeMap.value.has(node.parent_uid)) {
        ancestors.unshift(node.parent_uid)
        currentId = node.parent_uid
      } else {
        break
      }
    }
    return ancestors
  }

  /* 展开目标节点的全部祖先，保证当前激活项在树和图中可见。 */
  const expandAncestors = (id: string) => {
    const ancestors = getAncestors(id)
    for (const ancestorId of ancestors) {
      expandedNodeIds.value.add(ancestorId)
      expandedGraphNodeIds.value.add(ancestorId)
    }
  }

  const findActiveItemIndex = (activeId: string | null): number => {
    if (!activeId) return -1
    return options.flatIndexItems.value.findIndex(item => isItemActive(item, activeId))
  }

  /* 将列表侧激活项解析为树/图中的 block 节点 ID。 */
  const resolveActiveNodeId = (activeId: string | null): string | null => {
    if (!activeId) return null
    if (nodeMap.value.has(activeId)) return activeId
    const activeIndex = findActiveItemIndex(activeId)
    if (activeIndex < 0) return null
    const item = options.flatIndexItems.value[activeIndex]
    const node = props.activeTab === 'Preview_IndexTree' || props.activeTab === 'Preview_IndexGraph'
      ? findNodeForItemExact(item, graphNodeLookup.value)
      : findNodeForItem(item, graphNodeLookup.value)
    return node?.id || null
  }

  const activeNodeIdForGraphTree = computed(() => (
    resolveActiveNodeId(props.activeLinkedItemId)
  ))

  /* 切换树节点展开状态并通知外层。 */
  const onTreeToggle = (id: string) => {
    if (expandedNodeIds.value.has(id)) {
      expandedNodeIds.value.delete(id)
    } else {
      expandedNodeIds.value.add(id)
    }
    options.emitToggleTreeExpand?.(id)
  }

  /* 切换图形视图展开状态，并同步处理其全部后代。 */
  const onGraphToggle = (id: string) => {
    const descendants: string[] = []
    const queue = [...(childrenMap.value.get(id) || [])]
    while (queue.length) {
      const childId = queue.shift() as string
      descendants.push(childId)
      const children = childrenMap.value.get(childId) || []
      queue.push(...children)
    }
    if (expandedGraphNodeIds.value.has(id)) {
      expandedGraphNodeIds.value.delete(id)
      descendants.forEach(descendantId => {
        expandedGraphNodeIds.value.delete(descendantId)
      })
    } else {
      expandedGraphNodeIds.value.add(id)
      descendants.forEach(descendantId => {
        expandedGraphNodeIds.value.add(descendantId)
      })
    }
    options.emitToggleGraphExpand?.(id)
  }

  /* 将树/图中的节点选中事件透传给外层工作区。 */
  const onNodeSelect = (id: string) => {
    options.emitSelectItem?.(id)
  }

  /* 同步图形视图的 viewport 变化。 */
  const onViewportUpdate = (state: GraphViewportState) => {
    graphViewportState.value = state
    options.emitUpdateGraphViewport?.(state)
  }

  watch(() => props.activeLinkedItemId, (newId) => {
    const resolvedNodeId = resolveActiveNodeId(newId)
    if (resolvedNodeId) {
      expandAncestors(resolvedNodeId)
    }
  }, { immediate: true })

  watch(() => props.graphData, (data) => {
    expandedNodeIds.value = new Set()
    expandedGraphNodeIds.value = new Set()
    if (data?.nodes?.length) {
      for (const rootId of roots.value) {
        expandedNodeIds.value.add(rootId)
        expandedGraphNodeIds.value.add(rootId)
      }
      const activeNodeId = resolveActiveNodeId(props.activeLinkedItemId)
      if (activeNodeId) {
        expandAncestors(activeNodeId)
      }
    }
  }, { immediate: true })

  return {
    hasGraphData,
    graphNodeLookup,
    nodeMap,
    childrenMap,
    roots,
    expandedNodeIds,
    expandedGraphNodeIds,
    graphViewportState,
    activeNodeIdForGraphTree,
    onTreeToggle,
    onGraphToggle,
    onNodeSelect,
    onViewportUpdate,
    expandAncestors
  }
}
