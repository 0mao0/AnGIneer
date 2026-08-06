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
            <a-dropdown :trigger="['contextmenu']">
              <div
                :data-tree-node-id="row.id"
                :class="['tree-row', { active: row.id === activeNodeId }]"
                @click="onRowClick(row.id)"
                @contextmenu.prevent
              >
                <a-checkbox
                  class="tree-select-checkbox"
                  :checked="isRowChecked(row.id)"
                  @click.stop
                  @change="onToggleCheck(row.id)"
                />
                <span class="tree-toggle" @click.stop="onToggle(row.id)">
                  <template v-if="row.hasChildren">
                    <RightOutlined v-if="!row.isExpanded" />
                    <DownOutlined v-else />
                  </template>
                  <span v-else class="toggle-placeholder" />
                </span>
                <div class="tree-main">
                  <div class="tree-meta">
                    <span v-if="rowLevelTag(row.id)" :class="['chip', 'lv']">{{ rowLevelTag(row.id) }}</span>
                    <span v-if="rowDisplayTextHtml(row.id)" class="tree-text" v-html="rowDisplayTextHtml(row.id)" />
                    <span v-else-if="!rowSuppressPlainText(row.id)" class="tree-text">{{ rowDisplayText(row.id) }}</span>
                    <span v-if="rowTypeTag(row.id)" class="chip">{{ rowTypeTag(row.id) }}</span>
                    <span v-if="rowPositionTag(row.id)" class="chip pos">{{ rowPositionTag(row.id) }}</span>
                  </div>
                  <div v-if="rowInlineMediaHtml(row.id)" class="tree-inline-media" v-html="rowInlineMediaHtml(row.id)" />
                </div>
                <a-button
                  v-if="nodeMap.get(row.id)"
                  type="text"
                  size="small"
                  class="tree-edit-btn"
                  @click.stop="onEdit(row.id)"
                >
                  <template #icon>
                    <EditOutlined />
                  </template>
                </a-button>
              </div>
              <template #overlay>
                <a-menu @click="(payload) => onContextMenuClick(payload, row.id)">
                  <a-sub-menu key="relevel-actions" title="调整层级">
                    <a-menu-item key="promote">升一级</a-menu-item>
                    <a-menu-item key="demote">降一级</a-menu-item>
                    <a-menu-divider />
                    <a-menu-item
                      v-for="level in [1, 2, 3, 4, 5, 6]"
                      :key="`set-level-${level}`"
                    >
                      设为 L{{ level }}
                    </a-menu-item>
                  </a-sub-menu>
                </a-menu>
              </template>
            </a-dropdown>
          </div>
        </div>
      </div>
    </template>
  </div>
  <a-modal
    v-model:open="previewVisible"
    :title="previewTitle"
    :footer="null"
    width="min(960px, 92vw)"
    centered
  >
    <div class="tree-image-preview" v-html="previewImageHtml" />
  </a-modal>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { RightOutlined, DownOutlined, EditOutlined } from '@ant-design/icons-vue'
import type { DocBlockNode, PreviewIndexInteractionEventMap } from '../../../types/knowledge'
import {
  getNodeDisplayText,
  getNodeLevelTag,
  getNodePositionTag,
  getNodeTypeTag,
  renderMarkdownInlineToHtml,
  renderNodeRichMedia,
  shouldSuppressNodePlainText
} from '../../../utils/knowledge'
import { effectiveField } from '../../../utils/common'

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

/* 图/表/公式节点点击后弹出图片预览 */
const previewNode = ref<DocBlockNode | null>(null)
const previewVisible = ref(false)
const previewTitle = computed(() => {
  const n = previewNode.value
  return n ? `${getNodeTypeTag(n) || '节点'}预览` : ''
})
const previewImageHtml = computed(() => {
  const n = previewNode.value
  if (!n) return ''
  return renderNodeRichMedia(n, props.sourceFilePath, {
    includeMath: false,
    includeTable: false
  })
})

const isImagePreviewNode = (node: DocBlockNode): boolean => {
  if (!['image', 'table', 'equation_interline', 'formula'].includes(node.block_type)) return false
  return Boolean(
    (Array.isArray(node.image_paths) && node.image_paths.length > 0)
    || node.image_path
    || (Array.isArray(node.rich_media_order) && node.rich_media_order.some(item => item.type === 'image' && item.path))
  )
}

/* ---- 行渲染（原 IndexTreeFlatRow 逻辑，按 rowId 取节点） ---- */
const rowNode = (rowId: string) => props.nodeMap.get(rowId)
const rowLevelTag = (rowId: string) => getNodeLevelTag(rowNode(rowId), props.nodeMap)
const rowTypeTag = (rowId: string) => getNodeTypeTag(rowNode(rowId))
const rowPositionTag = (rowId: string) => getNodePositionTag(rowNode(rowId))
const rowSuppressPlainText = (rowId: string) => shouldSuppressNodePlainText(rowNode(rowId))
const rowDisplayText = (rowId: string) => getNodeDisplayText(rowNode(rowId), rowId)
const rowDisplayTextHtml = (rowId: string) => {
  const node = rowNode(rowId)
  if (rowSuppressPlainText(rowId)) return ''
  const rawText = String(effectiveField(node, 'plain_text') || '').trim() || rowId
  return renderMarkdownInlineToHtml(rawText, props.sourceFilePath || '')
}
const rowIsFormulaOrTable = (rowId: string) => {
  const node = rowNode(rowId)
  if (!node) return false
  return node.block_type === 'equation_interline'
    || node.block_type === 'formula'
    || node.block_type === 'table'
}
const rowHasRichMedia = (rowId: string) => {
  const n = rowNode(rowId)
  if (!n) return false
  return Boolean(
    (Array.isArray(n.rich_media_order) && n.rich_media_order.length > 0)
    || n.table_html
    || n.math_content
    || (Array.isArray(n.image_paths) && n.image_paths.length > 0)
  )
}
const rowInlineMediaHtml = (rowId: string) => {
  if (!rowHasRichMedia(rowId)) return ''
  return renderNodeRichMedia(rowNode(rowId), props.sourceFilePath, {
    includeImages: !rowIsFormulaOrTable(rowId)
  })
}
const isRowChecked = (rowId: string) => Boolean(props.selectedNodeIds?.has(rowId))

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
    if (rowOffsets.value[i] + getRowHeight(flatRows.value[i].id) > scrollPos) {
      startIdx = Math.max(0, i - BUFFER_COUNT)
      break
    }
    startIdx = i
  }

  let endIdx = total
  for (let i = startIdx; i < total; i++) {
    if (rowOffsets.value[i] > scrollPos + containerHeight) {
      endIdx = Math.min(total, i + BUFFER_COUNT)
      break
    }
  }

  const safeStart = Math.max(0, Math.min(startIdx, total - 1))
  const safeEnd = Math.max(safeStart, Math.min(total, endIdx))
  return { startIdx: safeStart, endIdx: safeEnd }
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
/* roots changed: reset row-height cache and scroll to top */
watch(() => props.roots, () => {
  rowHeights.value = new Map()
  scrollTop.value = 0
  if (treeContainerRef.value) {
    treeContainerRef.value.scrollTop = 0
  }
  nextTick(() => measureVisibleRows())
})

/* expand/collapse changed: re-measure visible rows */
watch(() => props.expandedNodeIds, () => {
  nextTick(() => measureVisibleRows())
})

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

const onRowClick = (rowId: string) => {
  const node = props.nodeMap.get(rowId)
  if (node && isImagePreviewNode(node)) {
    previewNode.value = node
    previewVisible.value = true
  }
  emit('select', rowId)
}

const onEdit = (id: string) => {
  emit('edit', id)
}

const onToggleCheck = (id: string) => {
  emit('toggle-check', id)
}

const onContextMenuClick = (payload: { key: string }, rowId: string) => {
  if (payload.key === 'promote' || payload.key === 'demote') {
    emit('context-action', { nodeId: rowId, action: payload.key })
    return
  }
  if (payload.key.startsWith('set-level-')) {
    const targetLevel = Number(payload.key.replace('set-level-', ''))
    if (Number.isFinite(targetLevel) && targetLevel > 0) {
      emit('context-action', { nodeId: rowId, action: 'set-level', targetLevel })
    }
  }
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

.tree-image-preview {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  max-height: 72vh;
  overflow: auto;
}

.tree-image-preview :deep(.media-image) {
  display: block;
  max-width: 100%;
  max-height: 68vh;
  width: auto;
  height: auto;
  object-fit: contain;
  border-radius: 8px;
  background: var(--dp-surface-bg);
}

/* ---- 行渲染样式（原 IndexTreeFlatRow，缺失 CSS 变量补默认值） ---- */
.tree-row {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  cursor: pointer;
  padding: 6px 8px;
  border-radius: 10px;
  border: 1px solid var(--dp-pane-border, #e8edf4);
  background: var(--dp-index-card-bg, #fafcff);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  transition: all 0.16s ease;

  &:hover {
    border-color: var(--dp-hover-border, #a5b4fc);
    background: var(--dp-hover-bg, #f0f3ff);
  }

  &.active {
    border-color: var(--dp-active-border, #7c9cf5);
    box-shadow: 0 0 0 2px var(--dp-active-shadow, rgba(124, 156, 245, 0.25));
    background: var(--dp-active-bg, #eef2ff);
  }
}

.tree-select-checkbox {
  flex: 0 0 auto;
  margin-top: 2px;
}

.tree-edit-btn {
  flex: 0 0 auto;
  margin-left: 4px;
}

.tree-toggle {
  width: 16px;
  display: inline-flex;
  justify-content: center;
  align-items: center;
  color: var(--dp-sub-text, #8c8c8c);
  font-size: 10px;
}

.toggle-placeholder {
  width: 16px;
  height: 16px;
}

.tree-main {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
  min-width: 0;
}

.tree-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  min-width: 0;
}

.tree-text {
  display: block;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--dp-title-text, #4f5d7a);
}

.tree-text :deep(.katex) {
  font-size: 1em;
}

.tree-text :deep(.katex-display) {
  display: inline-block;
  margin: 0;
  vertical-align: middle;
}

.tree-inline-media {
  width: 100%;
  padding: 8px;
  border-radius: 8px;
  border: 1px solid var(--dp-pane-border, #e8edf4);
  background: var(--dp-inline-media-bg, #f8fafc);
}

.tree-inline-media :deep(.media-table) {
  overflow: auto;
  max-width: 100%;
}

.tree-inline-media :deep(table) {
  border-collapse: collapse;
  width: 100%;
  min-width: 240px;
  table-layout: auto;
}

.tree-inline-media :deep(th),
.tree-inline-media :deep(td) {
  border: 1px solid rgba(148, 163, 184, 0.7) !important;
  padding: 6px 8px;
  background: transparent !important;
}

.tree-inline-media :deep(.media-formula) {
  overflow-x: auto;
  max-width: 100%;
}

.tree-inline-media :deep(.katex-display) {
  margin: 0;
  padding: 4px 0;
  overflow-x: auto;
  overflow-y: hidden;
}

.tree-inline-media :deep(.media-image) {
  display: block;
  width: 100%;
  max-width: 100%;
  max-height: 320px;
  object-fit: contain;
  border-radius: 8px;
  background: var(--dp-surface-bg, #ffffff);
}

.chip {
  font-size: 10px;
  line-height: 1;
  padding: 3px 6px;
  border-radius: 999px;
  border: 1px solid var(--chip-default-border, #e2e8f0);
  background: var(--chip-default-bg, #f1f5f9);
  color: var(--chip-default-text, #64748b);
  flex-shrink: 0;

  &.lv {
    border-color: var(--chip-lv-border, #c7d2fe);
    background: var(--chip-lv-bg, #eef2ff);
    color: var(--chip-lv-text, #4f46e5);
  }

  &.pos {
    border-color: var(--chip-pos-border, #cffafe);
    background: var(--chip-pos-bg, #ecfeff);
    color: var(--chip-pos-text, #0e7490);
  }
}
</style>
