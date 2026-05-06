<template>
  <div ref="treeContainerRef" class="doc-blocks-tree" @scroll.passive="onTreeScroll">
    <div v-if="loading" class="tree-loading">
      <a-spin size="small" />
      <span>加载中...</span>
    </div>
    <a-empty v-else-if="!roots.length" description="暂无结构数据" />
    <template v-else>
      <div class="tree-virtual-spacer" :style="{ height: `${totalHeight}px` }">
        <div class="tree-virtual-content" :style="{ transform: `translateY(${offsetY}px)` }">
          <div
            v-for="row in visibleRows"
            :key="row.id"
            class="tree-flat-row"
            :style="{ paddingLeft: `${row.depth * 20 + 10}px` }"
          >
            <IndexTreeFlatRow
              :row="row"
              :node-map="nodeMap"
              :expanded-ids="expandedNodeIds"
              :active-node-id="activeNodeId"
              :selected-node-ids="selectedNodeIds"
              :source-file-path="sourceFilePath"
              @toggle="onToggle"
              @select="onSelect"
              @edit="onEdit"
              @toggle-check="onToggleCheck"
              @context-action="onContextAction"
            />
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import type { DocBlockNode, PreviewIndexInteractionEventMap } from '../../../types/knowledge'
import IndexTreeFlatRow from './IndexTreeFlatRow.vue'

interface FlatRow {
  id: string
  depth: number
  hasChildren: boolean
  isExpanded: boolean
}

interface Props {
  loading?: boolean
  nodeMap: Map<string, DocBlockNode>
  childrenMap: Map<string, string[]>
  roots: string[]
  expandedNodeIds: Set<string>
  activeNodeId: string | null
  selectedNodeIds?: Set<string>
  sourceFilePath?: string
}

const props = defineProps<Props>()

const emit = defineEmits<Pick<PreviewIndexInteractionEventMap, 'toggle' | 'select'> & {
  edit: [id: string]
  'toggle-check': [id: string]
  'context-action': [payload: { nodeId: string; action: 'promote' | 'demote' | 'set-level'; targetLevel?: number }]
}>()

const treeContainerRef = ref<HTMLElement | null>(null)
const scrollTop = ref(0)
const ROW_HEIGHT = 44
const BUFFER_COUNT = 10

const flatRows = computed<FlatRow[]>(() => {
  const rows: FlatRow[] = []
  const traverse = (ids: string[], depth: number) => {
    for (const id of ids) {
      const children = props.childrenMap.get(id) || []
      const hasChildren = children.length > 0
      const isExpanded = props.expandedNodeIds.has(id)
      rows.push({ id, depth, hasChildren, isExpanded })
      if (hasChildren && isExpanded) {
        traverse(children, depth + 1)
      }
    }
  }
  traverse(props.roots, 0)
  return rows
})

const totalHeight = computed(() => flatRows.value.length * ROW_HEIGHT)

const visibleRange = computed(() => {
  const total = flatRows.value.length
  const containerHeight = treeContainerRef.value?.clientHeight || 600
  const startIdx = Math.max(0, Math.floor(scrollTop.value / ROW_HEIGHT) - BUFFER_COUNT)
  const endIdx = Math.min(total, Math.ceil((scrollTop.value + containerHeight) / ROW_HEIGHT) + BUFFER_COUNT)
  return { startIdx, endIdx }
})

const offsetY = computed(() => visibleRange.value.startIdx * ROW_HEIGHT)

const visibleRows = computed(() => flatRows.value.slice(visibleRange.value.startIdx, visibleRange.value.endIdx))

const onTreeScroll = () => {
  if (treeContainerRef.value) {
    scrollTop.value = treeContainerRef.value.scrollTop
  }
}

const onToggle = (id: string) => {
  emit('toggle', id)
}

const onSelect = (id: string) => {
  emit('select', id)
}

const onEdit = (id: string) => {
  emit('edit', id)
}

const onToggleCheck = (id: string) => {
  emit('toggle-check', id)
}

const onContextAction = (payload: { nodeId: string; action: 'promote' | 'demote' | 'set-level'; targetLevel?: number }) => {
  emit('context-action', payload)
}

const scrollActiveNodeIntoView = () => {
  if (!props.activeNodeId) return
  nextTick(() => {
    const idx = flatRows.value.findIndex(r => r.id === props.activeNodeId)
    if (idx < 0) return
    const targetTop = idx * ROW_HEIGHT
    const container = treeContainerRef.value
    if (!container) return
    const viewTop = container.scrollTop
    const viewBottom = viewTop + container.clientHeight
    if (targetTop < viewTop || targetTop > viewBottom - ROW_HEIGHT) {
      container.scrollTop = targetTop - container.clientHeight / 2 + ROW_HEIGHT / 2
    }
  })
}

watch(() => props.activeNodeId, () => {
  scrollActiveNodeIntoView()
})

watch(() => props.expandedNodeIds, () => {
  nextTick(() => scrollActiveNodeIntoView())
}, { deep: true })
</script>

<style lang="less" scoped>
.doc-blocks-tree {
  height: 100%;
  overflow-y: auto;
  font-size: 13px;
}

.tree-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 24px;
  color: var(--dp-sub-text);
}

.tree-virtual-spacer {
  position: relative;
}

.tree-virtual-content {
  position: absolute;
  left: 0;
  right: 0;
  top: 0;
}

.tree-flat-row {
  height: 44px;
  display: flex;
  align-items: center;
  box-sizing: border-box;
}
</style>
