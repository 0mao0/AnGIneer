import { computed, nextTick, ref, watch } from 'vue'
import type { DocBlocksGraph, StructuredIndexItem } from '../types/knowledge'
import { formatStructuredItemType, isItemActive } from '../utils/knowledge'
import { useParsedPdfIndexTree, type GraphViewportState } from './useParsedPdfIndexTree'

export type PreviewMode =
  | 'Preview_HTML'
  | 'Preview_Markdown'
  | 'Preview_IndexList'
  | 'Preview_IndexTree'
  | 'Preview_IndexGraph'

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
  const indexContentScrollRef = ref<{ $el?: HTMLElement } | HTMLElement | null>(null)
  const headerTitleRowRef = ref<HTMLElement | null>(null)
  const applyingExternalScroll = ref(false)
  const indexCurrentPage = ref(1)
  const indexPageSize = 30

  const isIndexMode = computed(() => (
    props.activeTab === 'Preview_IndexList'
    || props.activeTab === 'Preview_IndexTree'
    || props.activeTab === 'Preview_IndexGraph'
  ))

  const indexContentScrollElement = computed<HTMLElement | null>(() => {
    const current = indexContentScrollRef.value
    if (current instanceof HTMLElement) return current
    if (current?.$el instanceof HTMLElement) return current.$el
    return null
  })

  const flatIndexItems = computed<StructuredIndexItem[]>(() => {
    if (props.structuredItems.length > 0) {
      return props.structuredItems
    }
    if (!props.graphData?.nodes?.length) {
      return []
    }
    const excludedTypes = new Set(['header', 'footer', 'page_header', 'page_number'])
    const sortedNodes = [...props.graphData.nodes]
      .filter(node => !excludedTypes.has(node.block_type || ''))
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

  const findActiveItemIndex = (activeId: string | null): number => {
    if (!activeId) return -1
    return flatIndexItems.value.findIndex(item => isItemActive(item, activeId))
  }

  const {
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
      value === 'Preview_HTML'
      || value === 'Preview_Markdown'
      || value === 'Preview_IndexList'
      || value === 'Preview_IndexTree'
      || value === 'Preview_IndexGraph'
    ) {
      if ((value === 'Preview_IndexTree' || value === 'Preview_IndexGraph') && !hasGraphData.value) {
        emit('update:activeTab', 'Preview_IndexList')
        return
      }
      emit('update:activeTab', value)
    }
  }

  const maxIndexPage = computed(() => Math.max(1, Math.ceil(flatIndexItems.value.length / indexPageSize)))

  const onIndexPageChange = (page: number) => {
    indexCurrentPage.value = Math.max(1, Math.min(maxIndexPage.value, page))
    const container = indexContentScrollElement.value
    if (container instanceof HTMLElement) {
      container.scrollTop = 0
    }
  }

  const scrollActiveIndexItemIntoView = () => {
    if (props.activeTab !== 'Preview_IndexList') return
    const container = indexContentScrollElement.value
    if (!(container instanceof HTMLElement)) return
    nextTick(() => {
      const activeElement = container.querySelector('.index-item.active') as HTMLElement | null
      if (!activeElement) return
      activeElement.scrollIntoView({ behavior: 'smooth', block: 'center' })
    })
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

  watch(() => props.activeLinkedItemId, (newId) => {
    const activeIndex = findActiveItemIndex(newId)
    if (activeIndex >= 0) {
      const targetPage = Math.floor(activeIndex / indexPageSize) + 1
      if (targetPage !== indexCurrentPage.value) {
        indexCurrentPage.value = targetPage
      }
    }
    scrollActiveIndexItemIntoView()
  }, { immediate: true })

  watch(flatIndexItems, () => {
    indexCurrentPage.value = Math.max(1, Math.min(indexCurrentPage.value, maxIndexPage.value))
  })

  watch([() => props.activeTab, indexCurrentPage], () => {
    scrollActiveIndexItemIntoView()
  })

  watch(() => props.graphData, (data) => {
    if (!data?.nodes?.length && (props.activeTab === 'Preview_IndexTree' || props.activeTab === 'Preview_IndexGraph')) {
      emit('update:activeTab', 'Preview_IndexList')
    }
  }, { immediate: true })

  return {
    rightPaneRef,
    indexContentScrollRef,
    headerTitleRowRef,
    isIndexMode,
    hasGraphData,
    graphNodeLookup,
    flatIndexItems,
    indexCurrentPage,
    indexPageSize,
    nodeMap,
    childrenMap,
    roots,
    expandedNodeIds,
    expandedGraphNodeIds,
    graphViewportState,
    activeNodeIdForGraphTree,
    onRightPaneScroll,
    onTabChange,
    onIndexPageChange,
    onTreeToggle,
    onGraphToggle,
    onNodeSelect,
    onViewportUpdate,
    expandAncestors,
    setViewMode
  }
}
