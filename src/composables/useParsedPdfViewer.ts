import { computed, ref, watch } from 'vue'
import type { DocBlocksGraph, StructuredIndexItem } from '../types/knowledge'
import {
  formatStructuredItemType,
  isAttachmentNode,
  isFurnitureNode
} from '../utils/knowledge'
import { useParsedPdfIndexTree, type GraphViewportState } from './useParsedPdfIndexTree'

export type PreviewMode =
  | 'Preview_Markdown'
  | 'Preview_IndexTree'
  | 'Preview_IndexGraph'
  | 'Preview_KnowledgeGraph'

export interface ParsedPdfViewerBridgeEventMap {
  'update:activeTab': [value: PreviewMode]
  'content-scroll': [percent: number]
  'toggle-tree-expand': [id: string]
  'toggle-graph-expand': [id: string]
  'select-item': [id: string]
  'update-graph-viewport': [state: GraphViewportState]
}

export interface ParsedPdfViewerStateProps {
  activeTab: PreviewMode
  structuredItems: StructuredIndexItem[]
  contentScrollPercent: number
  activeLinkedItemId: string | null
  sourceFilePath?: string
  graphData?: DocBlocksGraph | null
}

export interface ParsedPdfViewerStateEmit {
  <K extends keyof ParsedPdfViewerBridgeEventMap>(event: K, ...args: ParsedPdfViewerBridgeEventMap[K]): void
}

export function useParsedPdfViewer(
  props: ParsedPdfViewerStateProps,
  emit: ParsedPdfViewerStateEmit
) {
  const rightPaneRef = ref<HTMLElement | null>(null)
  const headerTitleRowRef = ref<HTMLElement | null>(null)
  const applyingExternalScroll = ref(false)

  const isIndexMode = computed(() => (
    props.activeTab === 'Preview_IndexTree'
    || props.activeTab === 'Preview_IndexGraph'
    || props.activeTab === 'Preview_KnowledgeGraph'
  ))

  const graphDerivedIndexItems = computed<StructuredIndexItem[]>(() => {
    if (!props.graphData?.nodes?.length) {
      return []
    }
    const sortedNodes = [...props.graphData.nodes]
      .filter(node => !isFurnitureNode(node) && !isAttachmentNode(node))
      .sort((a, b) => {
        if (a.page_idx !== b.page_idx) return a.page_idx - b.page_idx
        return (a.block_seq || 0) - (b.block_seq || 0)
      })
    return sortedNodes.map((node, index) => {
      const text = (node.plain_text || '').trim()
      const title = text || `${formatStructuredItemType(node.block_type)} @ P${(node.page_idx ?? 0) + 1}`
      return {
        id: node.id,
        item_type: node.block_type || 'segment',
        title,
        content: text || title,
        order_index: index + 1,
        meta: {
          page_seq: (node.page_idx ?? 0) + 1,
          block_seq: node.block_seq ?? 0,
          source: 'doc_blocks_graph'
        }
      }
    })
  })

  const flatIndexItems = computed<StructuredIndexItem[]>(() => {
    const graphItems = graphDerivedIndexItems.value
    if (props.structuredItems.length > 0 && props.structuredItems.length >= graphItems.length) {
      return props.structuredItems
    }
    if (graphItems.length > 0) {
      return graphItems
    }
    return props.structuredItems
  })

  const {
    hasGraphData,
    graphNodeLookup,
    nodeMap,
    childrenMap,
    roots,
    displayRoots,
    expandedNodeIds,
    expandedGraphNodeIds,
    graphViewportState,
    activeNodeIdForGraphTree,
    onTreeToggle,
    onGraphToggle,
    onNodeSelect,
    onViewportUpdate,
    expandAncestors
  } = useParsedPdfIndexTree(props, {
    flatIndexItems,
    emitToggleTreeExpand: (id) => emit('toggle-tree-expand', id),
    emitToggleGraphExpand: (id) => emit('toggle-graph-expand', id),
    emitSelectItem: (id) => emit('select-item', id),
    emitUpdateGraphViewport: (state) => emit('update-graph-viewport', state)
  })

  const getScrollPercent = (element: HTMLElement): number => {
    const maxScrollTop = element.scrollHeight - element.clientHeight
    if (maxScrollTop <= 0) return 0
    return element.scrollTop / maxScrollTop
  }

  const setScrollPercent = (element: HTMLElement, percent: number) => {
    const maxScrollTop = element.scrollHeight - element.clientHeight
    if (maxScrollTop <= 0) return
    element.scrollTop = Math.max(0, Math.min(1, percent)) * maxScrollTop
  }

  const onRightPaneScroll = () => {
    if (applyingExternalScroll.value) return
    const pane = rightPaneRef.value
    if (!pane) return
    emit('content-scroll', getScrollPercent(pane))
  }

  const onTabChange = (event: { target?: { value?: string } } | string) => {
    const value = typeof event === 'string' ? event : event?.target?.value
    if (
      value === 'Preview_Markdown'
      || value === 'Preview_IndexTree'
      || value === 'Preview_IndexGraph'
      || value === 'Preview_KnowledgeGraph'
    ) {
      if ((value === 'Preview_IndexTree' || value === 'Preview_IndexGraph') && !hasGraphData.value) {
        emit('update:activeTab', 'Preview_Markdown')
        return
      }
      emit('update:activeTab', value)
    }
  }

  const setViewMode = (mode: PreviewMode) => {
    emit('update:activeTab', mode)
  }

  watch(() => props.contentScrollPercent, (percent) => {
    const pane = rightPaneRef.value
    if (!pane) return
    applyingExternalScroll.value = true
    setScrollPercent(pane, percent)
    requestAnimationFrame(() => {
      applyingExternalScroll.value = false
    })
  })

  watch(() => props.graphData, (data) => {
    if (!data?.nodes?.length && (props.activeTab === 'Preview_IndexTree' || props.activeTab === 'Preview_IndexGraph')) {
      emit('update:activeTab', 'Preview_Markdown')
    }
  }, { immediate: true })

  return {
    rightPaneRef,
    headerTitleRowRef,
    isIndexMode,
    hasGraphData,
    graphNodeLookup,
    flatIndexItems,
    nodeMap,
    childrenMap,
    roots,
    displayRoots,
    expandedNodeIds,
    expandedGraphNodeIds,
    graphViewportState,
    activeNodeIdForGraphTree,
    onRightPaneScroll,
    onTabChange,
    onTreeToggle,
    onGraphToggle,
    onNodeSelect,
    onViewportUpdate,
    expandAncestors,
    setViewMode
  }
}
