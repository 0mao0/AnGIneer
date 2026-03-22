import { ref, computed, shallowRef, type Ref, type ShallowRef, type ComputedRef } from 'vue'
import type { DocBlockNode, DocBlocksGraph } from '../types/knowledge'
import {
  getNodeLevel,
  getNodeText,
  getChildren
} from '../utils/knowledge'

export type ViewMode = 'tree' | 'graph'

export interface UseDocBlocksGraphOptions {
  initialViewMode?: ViewMode
}

export interface DocBlocksGraphIndex {
  nodeMap: Map<string, DocBlockNode>
  childrenMap: Map<string, string[]>
  parentMap: Map<string, string>
  roots: string[]
}

export const buildDocBlocksGraphIndex = (graph: DocBlocksGraph | null | undefined): DocBlocksGraphIndex => {
  const nodeMap = new Map<string, DocBlockNode>()
  const childrenMap = new Map<string, string[]>()
  const parentMap = new Map<string, string>()
  const roots: string[] = []
  if (!graph) {
    return { nodeMap, childrenMap, parentMap, roots }
  }
  for (const node of graph.nodes) {
    nodeMap.set(node.id, node)
    if (node.parent_uid) {
      parentMap.set(node.id, node.parent_uid)
      if (!childrenMap.has(node.parent_uid)) {
        childrenMap.set(node.parent_uid, [])
      }
      childrenMap.get(node.parent_uid)!.push(node.id)
    }
  }
  for (const node of graph.nodes) {
    if (!node.parent_uid || !nodeMap.has(node.parent_uid)) {
      roots.push(node.id)
    }
  }
  return { nodeMap, childrenMap, parentMap, roots }
}

export interface UseDocBlocksGraphReturn {
  graph: ShallowRef<DocBlocksGraph | null>
  loading: Ref<boolean>
  error: Ref<string | null>
  activeNodeId: Ref<string | null>
  expandedNodeIds: Ref<Set<string>>
  expandedGraphNodeIds: Ref<Set<string>>
  viewMode: Ref<ViewMode>
  viewportState: ShallowRef<{ x: number; y: number; scale: number } | null>
  nodeMap: ComputedRef<Map<string, DocBlockNode>>
  childrenMap: ComputedRef<Map<string, string[]>>
  parentMap: ComputedRef<Map<string, string>>
  roots: ComputedRef<string[]>
  loadGraph: (data: DocBlocksGraph) => void
  setActiveNode: (id: string | null) => void
  toggleExpand: (id: string) => void
  toggleGraphExpand: (id: string) => void
  expandAll: () => void
  collapseAll: () => void
  setViewMode: (mode: ViewMode) => void
  setViewportState: (state: { x: number; y: number; scale: number }) => void
  getAncestors: (id: string) => string[]
  expandAncestors: (id: string) => void
  getNodeLevel: (node: DocBlockNode) => number | null
  getNodeText: (node: DocBlockNode) => string
  getChildren: (id: string) => DocBlockNode[]
}

export function useDocBlocksGraph(options: UseDocBlocksGraphOptions = {}): UseDocBlocksGraphReturn {
  const { initialViewMode = 'tree' } = options

  const graph = shallowRef<DocBlocksGraph | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const activeNodeId = ref<string | null>(null)
  const expandedNodeIds = ref<Set<string>>(new Set())
  const expandedGraphNodeIds = ref<Set<string>>(new Set())
  const viewMode = ref<ViewMode>(initialViewMode)
  const viewportState = shallowRef<{ x: number; y: number; scale: number } | null>(null)

  const graphIndex = computed(() => buildDocBlocksGraphIndex(graph.value))
  const nodeMap = computed(() => graphIndex.value.nodeMap)
  const parentMap = computed(() => graphIndex.value.parentMap)
  const childrenMap = computed(() => graphIndex.value.childrenMap)
  const roots = computed(() => graphIndex.value.roots)

  const loadGraph = (data: DocBlocksGraph) => {
    graph.value = data
    error.value = null
    loading.value = false
  }

  const setActiveNode = (id: string | null) => {
    activeNodeId.value = id
  }

  const toggleExpand = (id: string) => {
    if (expandedNodeIds.value.has(id)) {
      expandedNodeIds.value.delete(id)
    } else {
      expandedNodeIds.value.add(id)
    }
  }

  const toggleGraphExpand = (id: string) => {
    if (expandedGraphNodeIds.value.has(id)) {
      expandedGraphNodeIds.value.delete(id)
    } else {
      expandedGraphNodeIds.value.add(id)
    }
  }

  const expandAll = () => {
    if (!graph.value) return
    const allIds = graph.value.nodes.map(n => n.id)
    expandedNodeIds.value = new Set(allIds)
    expandedGraphNodeIds.value = new Set(allIds)
  }

  const collapseAll = () => {
    expandedNodeIds.value = new Set()
    expandedGraphNodeIds.value = new Set(roots.value)
  }

  const setViewMode = (mode: ViewMode) => {
    viewMode.value = mode
  }

  const setViewportState = (state: { x: number; y: number; scale: number }) => {
    viewportState.value = state
  }

  const getAncestors = (id: string): string[] => {
    const ancestors: string[] = []
    let currentId: string | undefined = id
    while (currentId) {
      const parentId = parentMap.value.get(currentId)
      if (parentId) {
        ancestors.unshift(parentId)
        currentId = parentId
      } else {
        break
      }
    }
    return ancestors
  }

  const expandAncestors = (id: string) => {
    const ancestors = getAncestors(id)
    for (const ancestorId of ancestors) {
      expandedNodeIds.value.add(ancestorId)
      expandedGraphNodeIds.value.add(ancestorId)
    }
  }

  return {
    graph,
    loading,
    error,
    activeNodeId,
    expandedNodeIds,
    expandedGraphNodeIds,
    viewMode,
    viewportState,
    nodeMap,
    childrenMap,
    parentMap,
    roots,
    loadGraph,
    setActiveNode,
    toggleExpand,
    toggleGraphExpand,
    expandAll,
    collapseAll,
    setViewMode,
    setViewportState,
    getAncestors,
    expandAncestors,
    getNodeLevel: (node: DocBlockNode) => getNodeLevel(node, nodeMap.value),
    getNodeText,
    getChildren: (id: string) => getChildren(id, nodeMap.value, childrenMap.value)
  }
}
