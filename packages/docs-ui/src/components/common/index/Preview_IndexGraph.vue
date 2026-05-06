<template>
  <div class="doc-blocks-graph">
    <div v-if="loading" class="graph-loading">
      <a-spin size="small" />
      <span>加载中...</span>
    </div>
    <a-empty v-else-if="!visibleNodes.length" description="暂无结构数据" />
    <div v-show="!loading && visibleNodes.length" ref="networkRef" class="network-container" />
    <div v-if="activeMediaNode && activeMediaHtml" class="graph-media-panel">
      <div class="graph-media-panel-header">
        <span class="graph-media-panel-title" v-html="activeMediaTitleHtml" />
        <span class="graph-media-panel-tag">{{ activeMediaType }}</span>
      </div>
      <div class="graph-media-panel-body" v-html="activeMediaHtml" />
    </div>
    <div v-if="!loading && visibleNodes.length" class="graph-overlay">
      <div class="graph-legend">
        <div class="legend-item">
          <span class="legend-dot root"></span>
          <span>根节点</span>
        </div>
        <div class="legend-item">
          <span class="legend-dot expanded"></span>
          <span>已展开</span>
        </div>
        <div class="legend-item">
          <span class="legend-dot collapsed"></span>
          <span>可展开</span>
        </div>
        <div class="legend-item">
          <span class="legend-dot leaf"></span>
          <span>叶子节点</span>
        </div>
      </div>
      <div class="graph-hint">
        {{ graphHintText }}
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import type { DocBlockNode, PreviewIndexInteractionEventMap } from '../../../types/knowledge'
import {
  getNodeText,
  formatStructuredItemType,
  getNodeDisplayText,
  renderMarkdownInlineToHtml,
  renderNodeRichMedia
} from '../../../utils/knowledge'

declare global {
  interface Window {
    vis: {
      Network: any
      DataSet: new (data?: any[]) => any
    }
  }
}

interface Props {
  loading?: boolean
  nodeMap: Map<string, DocBlockNode>
  childrenMap: Map<string, string[]>
  roots: string[]
  expandedNodeIds: Set<string>
  activeNodeId: string | null
  viewportState: { x: number; y: number; scale: number } | null
  sourceFilePath?: string
}

const props = defineProps<Props>()

const emit = defineEmits<PreviewIndexInteractionEventMap>()

const GRAPH_LIGHTWEIGHT_THRESHOLD = 220
const MAX_RENDERED_GRAPH_NODES = 420

const networkRef = ref<HTMLElement | null>(null)
const network = ref<any>(null)
const nodePositions = ref<Map<string, { x: number; y: number }>>(new Map())
const layoutInitialized = ref(false)
const hoveredNodeId = ref<string | null>(null)
const isDarkTheme = computed(() => Boolean(networkRef.value?.closest('.dark-mode')))
const activeMediaNode = computed(() => {
  const candidateId = hoveredNodeId.value || props.activeNodeId || visibleNodes.value[0] || null
  return candidateId ? props.nodeMap.get(candidateId) || null : null
})
const activeMediaHtml = computed(() => renderNodeRichMedia(activeMediaNode.value, props.sourceFilePath))
const activeMediaTitle = computed(() => activeMediaNode.value
  ? getNodeDisplayText(activeMediaNode.value, activeMediaNode.value.id, 40)
  : '')
const activeMediaTitleHtml = computed(() => renderMarkdownInlineToHtml(activeMediaTitle.value, props.sourceFilePath || ''))
const activeMediaType = computed(() => {
  const blockType = activeMediaNode.value?.block_type
  return blockType ? formatStructuredItemType(blockType) : '节点'
})

const getAncestorPath = (nodeId: string): string[] => {
  const path: string[] = []
  let currentId: string | null = nodeId
  while (currentId) {
    const node = props.nodeMap.get(currentId)
    const parentId = node?.parent_uid || ''
    if (!parentId || !props.nodeMap.has(parentId)) break
    path.unshift(parentId)
    currentId = parentId
  }
  return path
}

const visibleNodeIdsFull = computed(() => {
  const visible: string[] = []
  const visited = new Set<string>()
  const addVisible = (id: string) => {
    if (visited.has(id)) return
    visited.add(id)
    visible.push(id)
    if (props.expandedNodeIds.has(id)) {
      const children = props.childrenMap.get(id) || []
      for (const childId of children) {
        addVisible(childId)
      }
    }
  }
  for (const rootId of props.roots) {
    addVisible(rootId)
  }
  return visible
})

const visibleNodes = computed(() => {
  const orderedNodes = visibleNodeIdsFull.value
  if (orderedNodes.length <= MAX_RENDERED_GRAPH_NODES) {
    return orderedNodes
  }
  const priorityIds = new Set<string>(props.roots)
  if (props.activeNodeId) {
    getAncestorPath(props.activeNodeId).forEach(id => priorityIds.add(id))
    priorityIds.add(props.activeNodeId)
  }
  const limited: string[] = []
  for (const nodeId of orderedNodes) {
    if (priorityIds.has(nodeId)) {
      limited.push(nodeId)
    }
  }
  for (const nodeId of orderedNodes) {
    if (limited.length >= MAX_RENDERED_GRAPH_NODES) break
    if (!priorityIds.has(nodeId)) {
      limited.push(nodeId)
    }
  }
  return limited.slice(0, MAX_RENDERED_GRAPH_NODES)
})

const visibleEdges = computed(() => {
  const visibleSet = new Set(visibleNodes.value)
  const edges: Array<{ from: string; to: string; id: string }> = []
  for (const nodeId of visibleSet) {
    const children = props.childrenMap.get(nodeId) || []
    for (const childId of children) {
      if (visibleSet.has(childId)) {
        edges.push({ from: nodeId, to: childId, id: `${nodeId}-${childId}` })
      }
    }
  }
  return edges
})

const hiddenNodeCount = computed(() => Math.max(0, visibleNodeIdsFull.value.length - visibleNodes.value.length))
const useLightweightLayout = computed(() => visibleNodeIdsFull.value.length > GRAPH_LIGHTWEIGHT_THRESHOLD)
const graphHintText = computed(() => {
  if (hiddenNodeCount.value > 0) {
    return `已渲染 ${visibleNodes.value.length}/${visibleNodeIdsFull.value.length} 个节点，请收起部分分支以查看更多`
  }
  if (useLightweightLayout.value) {
    return '大图模式已启用轻量层级布局 | 点击节点展开/折叠 | 拖拽平移 | 滚轮缩放'
  }
  return '点击节点展开/折叠 | 拖拽平移 | 滚轮缩放'
})

const getNodeType = (nodeId: string): 'root' | 'expanded' | 'collapsed' | 'leaf' => {
  if (props.roots.includes(nodeId)) return 'root'
  const children = props.childrenMap.get(nodeId) || []
  if (children.length === 0) return 'leaf'
  if (props.expandedNodeIds.has(nodeId)) return 'expanded'
  return 'collapsed'
}

const getNodeColors = (nodeId: string) => {
  const type = getNodeType(nodeId)
  const isActive = nodeId === props.activeNodeId

  const colorSchemes = isDarkTheme.value
    ? {
      root: {
        border: '#8b5cf6',
        background: '#312e81',
        highlight: { border: '#a78bfa', background: '#4338ca' }
      },
      expanded: {
        border: '#60a5fa',
        background: '#1e3a8a',
        highlight: { border: '#93c5fd', background: '#1d4ed8' }
      },
      collapsed: {
        border: '#f59e0b',
        background: '#78350f',
        highlight: { border: '#fbbf24', background: '#92400e' }
      },
      leaf: {
        border: '#94a3b8',
        background: '#334155',
        highlight: { border: '#cbd5e1', background: '#475569' }
      }
    }
    : {
      root: {
        border: '#7c3aed',
        background: '#ddd6fe',
        highlight: { border: '#5b21b6', background: '#c4b5fd' }
      },
      expanded: {
        border: '#2563eb',
        background: '#bfdbfe',
        highlight: { border: '#1d4ed8', background: '#93c5fd' }
      },
      collapsed: {
        border: '#f59e0b',
        background: '#fef3c7',
        highlight: { border: '#d97706', background: '#fcd34d' }
      },
      leaf: {
        border: '#6b7280',
        background: '#e5e7eb',
        highlight: { border: '#374151', background: '#d1d5db' }
      }
    }

  const colors = colorSchemes[type]

  if (isActive) {
    return {
      border: '#dc2626',
      background: '#fecaca',
      highlight: { border: '#b91c1c', background: '#fca5a5' }
    }
  }

  return colors
}

const buildVisNodes = () => {
  return visibleNodes.value.map(nodeId => {
    const node = props.nodeMap.get(nodeId)
    if (!node) return null
    const type = getNodeType(nodeId)

    let size = 22
    if (type === 'root') size = 30
    else if (type === 'expanded') size = 26
    else if (type === 'collapsed') size = 24
    else size = 20

    const text = getNodeDisplayText(node, nodeId, 26)
    const cachedPos = nodePositions.value.get(nodeId)
    const colors = getNodeColors(nodeId)
    const parentId = node.parent_uid || ''
    const parentPos = parentId ? nodePositions.value.get(parentId) : null
    const siblings = parentId ? (props.childrenMap.get(parentId) || []) : props.roots
    const siblingIndex = Math.max(0, siblings.indexOf(nodeId))
    const siblingOffset = (siblingIndex - (siblings.length - 1) / 2) * 74
    const fallbackX = parentPos ? parentPos.x + 210 : 0
    const fallbackY = parentPos ? parentPos.y + siblingOffset : siblingIndex * 110
    const lightweightLayout = useLightweightLayout.value
    const hasExplicitPos = Boolean(cachedPos) || layoutInitialized.value

    const typeTag = node.block_type ? `[${formatStructuredItemType(node.block_type)}] ` : ''

    return {
      id: nodeId,
      label: text,
      value: size,
      shape: type === 'root' ? 'diamond' : type === 'leaf' ? 'dot' : 'box',
      size,
      mass: Math.max(1.5, Math.min(4, size / 8)),
      physics: !lightweightLayout && !layoutInitialized.value && !cachedPos,
      x: lightweightLayout ? undefined : (cachedPos?.x ?? (hasExplicitPos ? fallbackX : undefined)),
      y: lightweightLayout ? undefined : (cachedPos?.y ?? (hasExplicitPos ? fallbackY : undefined)),
      title: `${typeTag}${getNodeText(node)}\n${type === 'collapsed' ? '点击展开' : type === 'expanded' ? '点击折叠' : ''}`,
      font: {
        size: Math.max(13, Math.min(18, Math.floor(size * 0.62))),
        color: isDarkTheme.value ? '#e2e8f0' : '#1e293b',
        strokeWidth: 2,
        strokeColor: isDarkTheme.value ? 'rgba(15,23,42,0.88)' : 'rgba(255,255,255,0.95)',
        face: 'system-ui, -apple-system, sans-serif'
      },
      margin: {
        top: 8,
        right: 10,
        bottom: 8,
        left: 10
      },
      borderWidth: 2,
      shadow: {
        enabled: true,
        color: 'rgba(0,0,0,0.1)',
        size: 3,
        x: 0,
        y: 1
      },
      color: colors
    }
  }).filter(Boolean)
}

const buildVisEdges = () => {
  return visibleEdges.value.map(edge => {
    const sourceType = getNodeType(edge.from)
    const isFromExpanded = sourceType === 'expanded' || sourceType === 'root'

    return {
      id: edge.id,
      from: edge.from,
      to: edge.to,
      arrows: { to: { enabled: false } },
      smooth: { type: 'curvedCW', roundness: 0.15 },
      color: {
        color: isFromExpanded ? 'rgba(59, 130, 246, 0.35)' : 'rgba(156, 163, 175, 0.25)',
        highlight: '#3b82f6',
        hover: '#60a5fa'
      },
      width: isFromExpanded ? 2 : 1.5,
      dashes: sourceType === 'collapsed'
    }
  })
}

const buildNetworkOptions = () => {
  const lightweightLayout = useLightweightLayout.value
  return {
    autoResize: true,
    physics: lightweightLayout
      ? false
      : {
        solver: 'hierarchicalRepulsion',
        stabilization: {
          enabled: true,
          iterations: 150,
          fit: true,
          updateInterval: 30
        },
        hierarchicalRepulsion: {
          nodeDistance: 170,
          centralGravity: 0.3,
          springLength: 130,
          springConstant: 0.01,
          damping: 0.5
        },
        minVelocity: 0.5
      },
    interaction: {
      hover: true,
      tooltipDelay: 80,
      zoomView: true,
      dragView: true,
      navigationButtons: false,
      keyboard: { enabled: false }
    },
    nodes: {
      borderWidth: 2,
      chosen: {
        node: (values: any, _id: string, _selected: boolean, hovering: boolean) => {
          void _id
          void _selected
          if (hovering) {
            values.borderWidth = 3
            values.shadowSize = 6
          }
        }
      }
    },
    edges: {
      smooth: { type: 'curvedCW', roundness: 0.15 },
      chosen: {
        edge: (values: any, _id: string, _selected: boolean, hovering: boolean) => {
          void _id
          void _selected
          if (hovering) {
            values.width = 3
            values.color = '#3b82f6'
          }
        }
      }
    },
    layout: {
      improvedLayout: !lightweightLayout,
      hierarchical: {
        enabled: true,
        direction: 'LR',
        sortMethod: 'directed',
        nodeSpacing: lightweightLayout ? 120 : 140,
        levelSeparation: lightweightLayout ? 180 : 220,
        treeSpacing: lightweightLayout ? 140 : 170,
        blockShifting: !lightweightLayout,
        edgeMinimization: !lightweightLayout,
        parentCentralization: true
      }
    }
  }
}

const applyViewportState = () => {
  if (!network.value) return
  if (props.viewportState) {
    network.value.moveTo({
      position: { x: props.viewportState.x, y: props.viewportState.y },
      scale: props.viewportState.scale,
      animation: false
    })
    return
  }
  network.value.fit({
    animation: { duration: 300, easingFunction: 'easeInOutQuad' }
  })
}

const finalizeNetworkLayout = () => {
  layoutInitialized.value = true
  requestAnimationFrame(() => {
    freezeNodes()
    applyViewportState()
  })
}

const initNetwork = async () => {
  if (!networkRef.value || !window.vis) return

  const container = networkRef.value
  const data = {
    nodes: new window.vis.DataSet(buildVisNodes()),
    edges: new window.vis.DataSet(buildVisEdges())
  }

  network.value = new window.vis.Network(container, data, buildNetworkOptions())

  network.value.on('click', (params: any) => {
    if (!params.nodes || !params.nodes.length) return
    const nodeId = params.nodes[0]
    const children = props.childrenMap.get(nodeId) || []
    if (children.length) {
      emit('toggle', nodeId)
    }
    emit('select', nodeId)
  })

  if (useLightweightLayout.value) {
    requestAnimationFrame(() => {
      finalizeNetworkLayout()
    })
  } else {
    network.value.once('stabilized', () => {
      finalizeNetworkLayout()
    })
  }

  network.value.on('dragEnd', () => {
    saveViewportState()
  })

  network.value.on('zoom', () => {
    saveViewportState()
  })

  network.value.on('hoverNode', (params: any) => {
    hoveredNodeId.value = String(params.node || '') || null
  })

  network.value.on('blurNode', () => {
    hoveredNodeId.value = null
  })
}

const freezeNodes = () => {
  if (!network.value) return
  const ids = visibleNodes.value
  const positions = network.value.getPositions(ids)
  const updates: any[] = []
  for (const id of ids) {
    const p = positions[id]
    if (p) {
      nodePositions.value.set(id, { x: p.x, y: p.y })
      updates.push({ id, x: p.x, y: p.y, physics: false })
    }
  }
  if (updates.length && network.value) {
    network.value.body.data.nodes.update(updates)
  }
}

const saveViewportState = () => {
  if (!network.value) return
  const position = network.value.getViewPosition()
  const scale = network.value.getScale()
  emit('update-viewport', { x: position.x, y: position.y, scale })
}

const updateNetwork = () => {
  if (!network.value) return
  network.value.setOptions(buildNetworkOptions())
  const existingIds: string[] = network.value.body?.data?.nodes?.getIds?.() || []
  if (existingIds.length > 0) {
    const existingPositions = network.value.getPositions(existingIds)
    for (const id of existingIds) {
      const p = existingPositions[id]
      if (p) {
        nodePositions.value.set(id, { x: p.x, y: p.y })
      }
    }
  }
  const nodes = buildVisNodes()
  const edges = buildVisEdges()
  network.value.body.data.nodes.clear()
  network.value.body.data.nodes.add(nodes)
  network.value.body.data.edges.clear()
  network.value.body.data.edges.add(edges)
  if (!layoutInitialized.value && !useLightweightLayout.value) {
    network.value.stabilize(100)
  } else {
    requestAnimationFrame(() => {
      freezeNodes()
    })
  }
}

/**
 * 将当前激活节点移动到图视图中心。
 */
const focusActiveNode = (nodeId: string) => {
  if (!network.value) return
  requestAnimationFrame(() => {
    if (!network.value) return
    const positions = network.value.getPositions([nodeId])
    const position = positions[nodeId]
    if (!position) return
    network.value.moveTo({
      position: { x: position.x, y: position.y },
      scale: Math.max(network.value.getScale(), 0.9),
      animation: {
        duration: 260,
        easingFunction: 'easeInOutQuad'
      }
    })
  })
}

watch(() => props.expandedNodeIds, () => {
  nextTick(() => {
    updateNetwork()
  })
}, { deep: true })

watch(() => props.activeNodeId, (newId) => {
  if (newId && network.value) {
    updateNetwork()
    focusActiveNode(newId)
  }
})

onMounted(async () => {
  if (!window.vis) {
    const script = document.createElement('script')
    script.src = 'https://unpkg.com/vis-network@9.1.9/dist/vis-network.min.js'
    script.onload = () => {
      nextTick(() => initNetwork())
    }
    document.head.appendChild(script)
  } else {
    await nextTick()
    initNetwork()
  }
})

onBeforeUnmount(() => {
  if (network.value) {
    network.value.destroy()
    network.value = null
  }
})

defineExpose({
  updateNetwork
})
</script>

<style lang="less" scoped>
.doc-blocks-graph {
  height: 100%;
  position: relative;
  background: var(--dp-content-bg);
  border-radius: 8px;
}

.graph-media-panel {
  position: absolute;
  right: 12px;
  bottom: 12px;
  width: min(380px, calc(100% - 24px));
  max-height: min(42%, 320px);
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px;
  background: var(--dp-surface-bg);
  border: 1px solid var(--dp-pane-border);
  border-radius: 10px;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.12);
  backdrop-filter: blur(8px);
  z-index: 6;
}

.graph-media-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
}

.graph-media-panel-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  color: var(--dp-title-strong);
  font-size: 13px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.graph-media-panel-title :deep(.katex) {
  font-size: 1em;
}

.graph-media-panel-title :deep(.katex-display) {
  display: inline-block;
  margin: 0;
  vertical-align: middle;
}

.graph-media-panel-tag {
  flex-shrink: 0;
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid var(--dp-badge-border);
  background: var(--dp-badge-bg);
  color: var(--dp-badge-text);
  font-size: 11px;
  line-height: 1.4;
}

.graph-media-panel-body {
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

:deep(.graph-media-panel-body .media-table) {
  overflow: auto;
  max-width: 100%;
}

:deep(.graph-media-panel-body .media-table table) {
  width: 100%;
  border-collapse: collapse;
  table-layout: auto;
}

:deep(.graph-media-panel-body .media-table th),
:deep(.graph-media-panel-body .media-table td) {
  border: 1px solid var(--dp-pane-border) !important;
  padding: 6px 8px;
  background: transparent !important;
}

:deep(.graph-media-panel-body .media-image) {
  width: 100%;
  max-width: 100%;
  max-height: 220px;
  display: block;
  object-fit: contain;
  border-radius: 8px;
  background: var(--dp-surface-bg);
}

:deep(.graph-media-panel-body .media-formula),
:deep(.graph-media-panel-body .katex-display) {
  max-width: 100%;
  margin: 0;
  overflow-x: auto;
  overflow-y: hidden;
}

.graph-loading {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--dp-sub-text);
  background: var(--dp-surface-bg);
  z-index: 10;
}

.network-container {
  height: 100%;
  width: 100%;
}

.graph-overlay {
  position: absolute;
  top: 10px;
  left: 10px;
  display: flex;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 8px;
  z-index: 5;
  max-width: calc(100% - 20px);
}

.graph-legend {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px 10px;
  background: var(--dp-surface-bg);
  border-radius: 6px;
  border: 1px solid var(--dp-pane-border);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  font-size: 11px;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--dp-sub-text);
}

.legend-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  border: 2px solid;

  &.root {
    background: var(--graph-root-bg);
    border-color: var(--graph-root-border);
    transform: rotate(45deg);
    border-radius: 2px;
  }

  &.expanded {
    background: var(--graph-expanded-bg);
    border-color: var(--graph-expanded-border);
  }

  &.collapsed {
    background: var(--graph-collapsed-bg);
    border-color: var(--graph-collapsed-border);
  }

  &.leaf {
    background: var(--graph-leaf-bg);
    border-color: var(--graph-leaf-border);
  }
}

.graph-hint {
  display: inline-flex;
  align-items: center;
  width: fit-content;
  max-width: 100%;
  padding: 4px 8px;
  background: var(--dp-surface-bg);
  border-radius: 6px;
  border: 1px solid var(--dp-pane-border);
  font-size: 10px;
  line-height: 1.2;
  color: var(--dp-sub-text);
  white-space: nowrap;
}
</style>
