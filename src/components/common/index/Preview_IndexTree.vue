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
            ref="flatRowRefs"
            :data-row-id="row.id"
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
import { computed, nextTick, onMounted, ref, watch } from 'vue'
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
const flatRowRefs = ref<HTMLDivElement[]>([])
const scrollTop = ref(0)
const ESTIMATED_ROW_HEIGHT = 50
const BUFFER_COUNT = 10

/* 每个节点的已测量高度缓存（未测量时为 0 表示用估算值）。 */
const rowHeights = ref<Map<string, number>>(new Map())

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

/* 获取某一行的高度（优先使用实测值，否则返回估算值）。 */
function getRowHeight(rowId: string): number {
  return rowHeights.value.get(rowId) || ESTIMATED_ROW_HEIGHT
}

/* 累计计算所有行的总高度（用于撑开滚动容器）。 */
const totalHeight = computed(() => {
  let h = 0
  for (const row of flatRows.value) {
    h += getRowHeight(row.id)
  }
  return h
})

/* 计算每一行在列表中的起始 Y 偏移量（用于定位可见区域）。 */
const rowOffsets = computed(() => {
  const offsets: number[] = []
  let offset = 0
  for (const row of flatRows.value) {
    offsets.push(offset)
    offset += getRowHeight(row.id)
  }
  return offsets
})

/* 根据当前 scrollTop 找到应该显示的行范围。 */
const visibleRange = computed(() => {
  const total = flatRows.value.length
  if (total === 0) return { startIdx: 0, endIdx: 0 }
  const containerHeight = treeContainerRef.value?.clientHeight || 600
  const scrollPos = scrollTop.value

  let startIdx = 0
  for (let i = 0; i < total; i++) {
    if (rowOffsets.value[i] + getRowHeight(flatRows.value[i].id) > scrollPos - containerHeight * 2) {
      startIdx = Math.max(0, i - BUFFER_COUNT)
      break
    }
    if (i === total - 1) startIdx = Math.max(0, total - BUFFER_COUNT * 3)
  }

  let endIdx = total
  for (let i = startIdx; i < total; i++) {
    if (rowOffsets.value[i] > scrollPos + containerHeight + containerHeight) {
      endIdx = Math.min(total, i + BUFFER_COUNT)
      break
    }
  }

  return { startIdx: Math.max(0, startIdx), endIdx: Math.min(total, endIdx) }
})

/* 可见区域第一个元素的 Y 偏移量（用于 translateY 定位）。 */
const offsetY = computed(() => {
  return rowOffsets.value[visibleRange.value.startIdx] || 0
})

const visibleRows = computed(() => flatRows.value.slice(visibleRange.value.startIdx, visibleRange.value.endIdx))

/* 测量当前可见 DOM 行的实际高度并写入缓存。 */
function measureVisibleRows() {
  if (!flatRowRefs.value || flatRowRefs.value.length === 0) return
  for (const el of flatRowRefs.value) {
    if (!el) continue
    const rowId = el.dataset.rowId
    if (!rowId) continue
    const measured = el.offsetHeight
    if (measured > 0 && measured !== rowHeights.value.get(rowId)) {
      rowHeights.value.set(rowId, measured)
    }
  }
}

/* 监听数据变化后重新测量行高。 */
watch([() => props.roots, () => props.expandedNodeIds], () => {
  nextTick(() => measureVisibleRows())
}, { deep: true })

/* 组件挂载后进行首次测量。 */
onMounted(() => {
  nextTick(() => measureVisibleRows())
})

const onTreeScroll = () => {
  if (treeContainerRef.value) {
    scrollTop.value = treeContainerRef.value.scrollTop
  }
  measureVisibleRows()
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

/* 将活跃节点滚动到可视区域中心。 */
const scrollActiveNodeIntoView = () => {
  if (!props.activeNodeId) return
  nextTick(() => {
    const idx = flatRows.value.findIndex(r => r.id === props.activeNodeId)
    if (idx < 0) return
    const targetTop = rowOffsets.value[idx]
    const container = treeContainerRef.value
    if (!container) return
    const rowH = getRowHeight(props.activeNodeId!)
    const viewTop = container.scrollTop
    const viewBottom = viewTop + container.clientHeight
    if (targetTop < viewTop || targetTop + rowH > viewBottom) {
      container.scrollTop = targetTop - container.clientHeight / 2 + rowH / 2
    }
  })
}

watch(() => props.activeNodeId, () => {
  scrollActiveNodeIntoView()
})
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
  display: flex;
  align-items: flex-start;
  box-sizing: border-box;
}
</style>
