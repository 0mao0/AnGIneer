import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { DocBlockNode, DocBlocksGraph, StructuredIndexItem } from '../types/knowledge'
import { buildDocBlocksGraphIndex } from './useDocBlocksGraph'

export type PreviewMode =
  | 'Preview_HTML'
  | 'Preview_Markdown'
  | 'Preview_IndexList'
  | 'Preview_IndexTree'
  | 'Preview_IndexGraph'

export interface GraphViewportState {
  x: number
  y: number
  scale: number
}

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
  const isCompactHeader = ref(false)
  const headerResizeObserver = ref<ResizeObserver | null>(null)
  const indexCurrentPage = ref(1)
  const indexPageSize = 30
  const expandedNodeIds = ref<Set<string>>(new Set())
  const expandedGraphNodeIds = ref<Set<string>>(new Set())
  const graphViewportState = ref<GraphViewportState | null>(null)

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

  const updateHeaderCompactMode = () => {
    const width = headerTitleRowRef.value?.clientWidth || 0
    isCompactHeader.value = width > 0 && width < 500
  }

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

  const formatItemType = (itemType: string) => {
    if (itemType === 'heading') return '标题'
    if (itemType === 'clause') return '条款'
    if (itemType === 'table') return '表格'
    if (itemType === 'image') return '图片'
    if (itemType === 'title') return '标题'
    if (itemType === 'paragraph') return '正文'
    if (itemType === 'equation_interline') return '公式'
    if (itemType === 'list') return '列表'
    return itemType || '未知'
  }

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
      const title = text || `${formatItemType(node.block_type)} @ P${(node.page_idx ?? 0) + 1}`
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

  const graphIndex = computed(() => buildDocBlocksGraphIndex(props.graphData))
  const nodeMap = computed(() => graphIndex.value.nodeMap)
  const childrenMap = computed(() => graphIndex.value.childrenMap)
  const roots = computed(() => graphIndex.value.roots)

  const getNodeLevel = (node: DocBlockNode): number | null => {
    if (node.derived_level !== null && node.derived_level !== undefined) {
      return node.derived_level
    }
    const parentId = node.parent_uid
    if (!parentId) return null
    const parent = nodeMap.value.get(parentId)
    if (!parent) return null
    const parentLevel = getNodeLevel(parent)
    if (parentLevel === null) return null
    return parentLevel + 1
  }

  const getNodeText = (node: DocBlockNode): string => (
    node.plain_text?.trim() || node.id
  )

  const getChildren = (id: string): DocBlockNode[] => {
    const childIds = childrenMap.value.get(id) || []
    return childIds
      .map(cid => nodeMap.value.get(cid))
      .filter((node): node is DocBlockNode => node !== undefined)
  }

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

  const expandAncestors = (id: string) => {
    const ancestors = getAncestors(id)
    for (const ancestorId of ancestors) {
      expandedNodeIds.value.add(ancestorId)
      expandedGraphNodeIds.value.add(ancestorId)
    }
  }

  const collectItemRefs = (item: StructuredIndexItem): string[] => {
    const meta = item.meta || {}
    const rawRefs: unknown[] = [
      item.id,
      meta.block_uid,
      meta.blockUid,
      meta.mineru_block_uid,
      meta.mineruBlockUid,
      meta.node_id,
      meta.nodeId,
      meta.block_id,
      meta.blockId,
      meta.source_block_id,
      meta.sourceBlockId,
      meta.mineru_block_id,
      meta.mineruBlockId,
      meta.caption_block_uid,
      meta.footnote_block_uid,
      meta.caption_block_uids,
      meta.footnote_block_uids,
      meta.block_uids,
      meta.node_ids
    ]
    const refs: string[] = []
    rawRefs.forEach(value => {
      if (Array.isArray(value)) {
        value.forEach(inner => {
          const text = String(inner || '').trim()
          if (text) refs.push(text)
        })
        return
      }
      const text = String(value || '').trim()
      if (text) refs.push(text)
    })
    return Array.from(new Set(refs))
  }

  const findNodeForItem = (item: StructuredIndexItem): DocBlockNode | null => {
    const refs = collectItemRefs(item)
    for (const ref of refs) {
      const direct = graphNodeLookup.value.get(ref)
      if (direct) return direct
    }
    const meta = item.meta || {}
    const pageSeq = Number(meta.page_seq || meta.page || 0)
    const blockSeq = Number(meta.block_seq || 0)
    if (pageSeq > 0 && blockSeq > 0) {
      for (const node of graphNodeLookup.value.values()) {
        if ((Number(node.page_idx ?? 0) + 1) === pageSeq && Number(node.block_seq ?? 0) === blockSeq) {
          return node
        }
      }
    }
    return null
  }

  const findActiveItemIndex = (activeId: string | null): number => {
    if (!activeId) return -1
    return flatIndexItems.value.findIndex(item => {
      if (item.id === activeId) return true
      const refs = collectItemRefs(item)
      return refs.includes(activeId)
    })
  }

  const resolveActiveNodeId = (activeId: string | null): string | null => {
    if (!activeId) return null
    if (nodeMap.value.has(activeId)) return activeId
    const activeIndex = findActiveItemIndex(activeId)
    if (activeIndex < 0) return null
    const item = flatIndexItems.value[activeIndex]
    const node = findNodeForItem(item)
    return node?.id || null
  }

  const activeNodeIdForGraphTree = computed(() => (
    resolveActiveNodeId(props.activeLinkedItemId)
  ))

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

  const onTreeToggle = (id: string) => {
    if (expandedNodeIds.value.has(id)) {
      expandedNodeIds.value.delete(id)
    } else {
      expandedNodeIds.value.add(id)
    }
    emit('toggle-tree-expand', id)
  }

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
    emit('toggle-graph-expand', id)
  }

  const onNodeSelect = (id: string) => {
    emit('select-item', id)
  }

  const onViewportUpdate = (state: GraphViewportState) => {
    graphViewportState.value = state
    emit('update-graph-viewport', state)
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
    const resolvedNodeId = resolveActiveNodeId(newId)
    if (resolvedNodeId) {
      expandAncestors(resolvedNodeId)
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
    if (data?.nodes?.length) {
      for (const rootId of roots.value) {
        expandedGraphNodeIds.value.add(rootId)
      }
    }
    if (!data?.nodes?.length && (props.activeTab === 'Preview_IndexTree' || props.activeTab === 'Preview_IndexGraph')) {
      emit('update:activeTab', 'Preview_IndexList')
    }
  }, { immediate: true })

  onMounted(() => {
    updateHeaderCompactMode()
    if (typeof ResizeObserver !== 'undefined' && headerTitleRowRef.value) {
      const observer = new ResizeObserver(() => {
        updateHeaderCompactMode()
      })
      observer.observe(headerTitleRowRef.value)
      headerResizeObserver.value = observer
    }
  })

  onBeforeUnmount(() => {
    headerResizeObserver.value?.disconnect()
  })

  return {
    rightPaneRef,
    indexContentScrollRef,
    headerTitleRowRef,
    isCompactHeader,
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
    getNodeLevel,
    getNodeText,
    getChildren,
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
