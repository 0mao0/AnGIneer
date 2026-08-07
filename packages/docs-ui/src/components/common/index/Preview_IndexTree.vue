<template>
  <div
    ref="treeContainerRef"
    :class="['doc-blocks-tree', { dark }]"
    @scroll.passive="onTreeScroll"
  >
    <div v-if="loading" class="tree-loading">
      <a-spin size="small" />
      <span>加载中...</span>
    </div>
    <a-empty v-else-if="!roots.length" description="暂无结构数据" />
    <template v-else>
      <div class="tree-virtual-spacer" :style="{ height: `${totalHeight}px` }">
        <div class="tree-virtual-content" :style="{ transform: `translateY(${offsetY}px)` }">
          <div
            v-for="row in rowViews"
            :key="row.id"
            ref="flatRowRefs"
            :data-row-id="row.id"
            class="tree-flat-row"
            :style="{ paddingLeft: `${row.depth * 20 + 10}px` }"
          >
            <div
              v-if="row.isGroup"
              :class="['tree-row', 'tree-group-row']"
              @click="onRowClick(row.id)"
            >
              <span
                class="tree-toggle"
                role="button"
                :aria-label="row.isExpanded ? '折叠' : '展开'"
                @click.stop="onToggle(row.id)"
              >
                <template v-if="row.hasChildren">
                  <RightOutlined v-if="!row.isExpanded" />
                  <DownOutlined v-else />
                </template>
                <span v-else class="toggle-placeholder" />
              </span>
              <div class="tree-main">
                <div class="tree-group-title">
                  <FolderOutlined />
                  <span>{{ row.groupLabel }}</span>
                  <span v-if="row.groupCount" class="group-count-text">{{ row.groupCount }} 项</span>
                </div>
              </div>
            </div>
            <a-dropdown v-else :trigger="['contextmenu']">
              <div
                :data-tree-node-id="row.id"
                :class="['tree-row', { active: row.id === activeNodeId, previewable: row.hasPreviewImage, furniture: row.furniture, flat: !row.isGroup && !row.levelTag }]"
                @click="onRowClick(row.id)"
                @contextmenu.prevent
              >
                <a-checkbox
                  class="tree-select-checkbox"
                  :checked="row.checked"
                  @click.stop
                  @change="onToggleCheck(row.id)"
                />
                <span
                  class="tree-toggle"
                  role="button"
                  :aria-label="row.isExpanded ? '折叠' : '展开'"
                  @click.stop="onToggle(row.id)"
                >
                  <template v-if="row.hasChildren">
                    <RightOutlined v-if="!row.isExpanded" />
                    <DownOutlined v-else />
                  </template>
                  <span v-else class="toggle-placeholder" />
                </span>
                <div class="tree-main">
                  <div class="tree-main-row">
                    <div class="tree-text-wrap">
                      <div
                        v-if="row.displayTextHtml"
                        :class="['tree-text', { 'tree-text-title': row.isTitle }]"
                        v-html="row.displayTextHtml"
                      />
                      <div
                        v-else-if="!row.suppressPlainText"
                        :class="['tree-text', { 'tree-text-title': row.isTitle }]"
                      >
                        {{ row.displayText }}
                      </div>
                    </div>
                    <span
                      v-if="row.summaryText || row.hasPreviewImage"
                      class="tree-summary"
                      :title="row.fullMetaText"
                    >
                      <EyeOutlined v-if="row.hasPreviewImage" class="tree-summary-eye" />
                      {{ row.summaryText }}
                    </span>
                  </div>
                  <div v-if="row.inlineMediaHtml" class="tree-inline-media" v-html="row.inlineMediaHtml" />
                </div>
                <a-button
                  v-if="row.hasNode"
                  type="text"
                  size="small"
                  class="tree-edit-btn"
                  aria-label="编辑"
                  @click.stop="onEdit(row.id)"
                >
                  <template #icon>
                    <EditOutlined />
                  </template>
                </a-button>
              </div>
              <template #overlay>
                <a-menu @click="makeContextMenuClick(row.id)">
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
    :footer="null"
    width="min(960px, 92vw)"
    centered
  >
    <template #title>
      <div class="tree-image-preview-header">
        <span class="tree-image-preview-title">{{ previewTitle }}</span>
        <span class="tree-image-preview-toolbar">
          <a-button size="small" title="缩小" :disabled="previewZoom <= 0.25" @click="previewZoomOut">
            <template #icon>
              <ZoomOutOutlined />
            </template>
          </a-button>
          <span class="tree-image-preview-zoom">{{ Math.round(previewZoom * 100) }}%</span>
          <a-button size="small" title="放大" :disabled="previewZoom >= 4" @click="previewZoomIn">
            <template #icon>
              <ZoomInOutlined />
            </template>
          </a-button>
          <a-button size="small" title="旋转" @click="previewRotate">
            <template #icon>
              <RotateRightOutlined />
            </template>
          </a-button>
          <a-button size="small" title="重置" @click="previewReset">
            <template #icon>
              <RedoOutlined />
            </template>
          </a-button>
        </span>
      </div>
    </template>
    <div class="tree-image-preview">
      <div
        :class="['tree-image-preview-stage', { dragging: previewDragging }]"
        @wheel="onPreviewWheel"
        @pointerdown="onPreviewPointerDown"
        @pointermove="onPreviewPointerMove"
        @pointerup="onPreviewPointerUp"
        @pointerleave="onPreviewPointerUp"
      >
        <img
          v-for="(src, index) in previewImages"
          :key="`${src}-${index}`"
          :src="src"
          :alt="previewTitle"
          class="preview-image"
          draggable="false"
          :style="{
            width: `calc(100% * ${previewZoom})`,
            transform: `translate(${previewTranslate.x}px, ${previewTranslate.y}px) rotate(${previewRotateDeg}deg)`
          }"
        />
      </div>
    </div>
  </a-modal>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import {
  RightOutlined,
  DownOutlined,
  EditOutlined,
  EyeOutlined,
  FolderOutlined,
  ZoomInOutlined,
  ZoomOutOutlined,
  RotateRightOutlined,
  RedoOutlined
} from '@ant-design/icons-vue'
import type { DocBlockNode, DisplayRoot, PreviewIndexInteractionEventMap } from '../../../types/knowledge'
import {
  extractPrintedPageLabel,
  getNodeDisplayText,
  getNodeLevelTag,
  getNodePositionTag,
  getNodeTypeTag,
  isFrontMatterGroupId,
  isAttachmentNode,
  isFurnitureNode,
  renderMarkdownInlineToHtml,
  renderNodeRichMedia,
  resolveAssetUrl,
  shouldSuppressNodePlainText
} from '../../../utils/knowledge'
import { effectiveField } from '../../../utils/common'

interface FlatRow {
  id: string
  depth: number
  hasChildren: boolean
  isExpanded: boolean
  isGroup?: boolean
  groupLabel?: string
  groupCount?: number
}

interface Props {
  loading?: boolean
  dark?: boolean
  nodeMap: Map<string, DocBlockNode>
  childrenMap: Map<string, string[]>
  roots: DisplayRoot[]
  expandedNodeIds: Set<string>
  activeNodeId: string | null
  selectedNodeIds?: Set<string>
  sourceFilePath?: string
  showFurniture?: boolean
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
const previewImages = ref<string[]>([])
const previewVisible = ref(false)
const previewZoom = ref(1)
const previewRotateDeg = ref(0)
const previewTranslate = ref({ x: 0, y: 0 })
const previewDragging = ref(false)
const previewDragStart = ref({ x: 0, y: 0 })

const previewTitle = computed(() => {
  const n = previewNode.value
  return n ? `${getNodeTypeTag(n) || '节点'}预览` : ''
})

const isImagePreviewNode = (node: DocBlockNode): boolean => {
  if (!['image', 'table', 'equation_interline', 'formula'].includes(node.block_type)) return false
  return Boolean(
    (Array.isArray(node.image_paths) && node.image_paths.length > 0)
    || node.image_path
    || (Array.isArray(node.rich_media_order) && node.rich_media_order.some(item => item.type === 'image' && item.path))
  )
}

const collectNodePreviewImages = (node: DocBlockNode): string[] => {
  const rawSources = [
    ...(Array.isArray(node.image_paths) ? node.image_paths : []),
    node.image_path,
    ...(node.rich_media_order || [])
      .filter(item => item.type === 'image' && item.path)
      .map(item => String(item.path || '').trim())
  ]
  return Array.from(new Set(
    rawSources
      .map(source => String(source || '').trim())
      .filter(Boolean)
      .map(source => resolveAssetUrl(source, props.sourceFilePath || ''))
      .filter(Boolean)
  ))
}

const openImagePreview = (node: DocBlockNode) => {
  previewNode.value = node
  previewImages.value = collectNodePreviewImages(node)
  previewZoom.value = 1
  previewRotateDeg.value = 0
  previewTranslate.value = { x: 0, y: 0 }
  previewDragging.value = false
  previewVisible.value = true
}

const clampZoom = (value: number) => Math.min(4, Math.max(0.25, Math.round(value * 100) / 100))

const previewZoomIn = () => {
  previewZoom.value = clampZoom(previewZoom.value + 0.25)
}

const previewZoomOut = () => {
  previewZoom.value = clampZoom(previewZoom.value - 0.25)
}

const previewRotate = () => {
  previewRotateDeg.value = (previewRotateDeg.value + 90) % 360
}

const previewReset = () => {
  previewZoom.value = 1
  previewRotateDeg.value = 0
  previewTranslate.value = { x: 0, y: 0 }
}

const onPreviewWheel = (event: WheelEvent) => {
  if (!event.ctrlKey) return
  event.preventDefault()
  const delta = event.deltaY > 0 ? -0.1 : 0.1
  previewZoom.value = clampZoom(previewZoom.value + delta)
}

const onPreviewPointerDown = (event: PointerEvent) => {
  if (previewZoom.value <= 1) return
  previewDragging.value = true
  previewDragStart.value = {
    x: event.clientX - previewTranslate.value.x,
    y: event.clientY - previewTranslate.value.y
  }
}

const onPreviewPointerMove = (event: PointerEvent) => {
  if (!previewDragging.value) return
  previewTranslate.value = {
    x: event.clientX - previewDragStart.value.x,
    y: event.clientY - previewDragStart.value.y
  }
}

const onPreviewPointerUp = () => {
  previewDragging.value = false
}

/* ---- 行渲染（原 IndexTreeFlatRow 逻辑，按 rowId 取节点） ---- */
const rowNode = (rowId: string) => props.nodeMap.get(rowId)

/* 每个节点的已测量高度缓存（未测量时为 0 表示用估算值）。 */
const rowHeights = ref<Map<string, number>>(new Map())

/* page_idx -> 纸面页码（取自 page_number/page_footer 块文本）。 */
const printedPageByPageIdx = computed(() => {
  const map = new Map<number, string>()
  for (const node of props.nodeMap.values()) {
    const type = String(node.block_type || '').toLowerCase()
    if (type !== 'page_number' && type !== 'page_footer') continue
    const label = extractPrintedPageLabel(node.plain_text || '')
    if (label && !map.has(node.page_idx)) {
      map.set(node.page_idx, label)
    }
  }
  for (const node of props.nodeMap.values()) {
    const page = Number(node.page_idx ?? 0)
    if (!map.has(page)) {
      map.set(page, String(page + 1))
    }
  }
  return map
})

const flatRows = computed<FlatRow[]>(() => {
  const rows: FlatRow[] = []
  const traverseChildren = (ids: string[], depth: number) => {
    for (const id of ids) {
      const node = rowNode(id)
      if (isAttachmentNode(node)) continue
      if (!props.showFurniture && isFurnitureNode(node)) continue
      const children = props.childrenMap.get(id) || []
      const hasChildren = children.length > 0
      const isExpanded = props.expandedNodeIds.has(id)
      rows.push({ id, depth, hasChildren, isExpanded })
      if (hasChildren && isExpanded) {
        traverseChildren(children, depth + 1)
      }
    }
  }
  const traverseRoots = (displayRoots: DisplayRoot[], depth: number) => {
    for (const root of displayRoots) {
      if (typeof root === 'string') {
        traverseChildren([root], depth)
        continue
      }
      const visibleChildren = root.children.filter(childId => {
        const child = rowNode(childId)
        return !isAttachmentNode(child)
          && (props.showFurniture || !isFurnitureNode(child))
      })
      const hasChildren = visibleChildren.length > 0
      const isExpanded = props.expandedNodeIds.has(root.id)
      rows.push({
        id: root.id,
        depth,
        hasChildren,
        isExpanded,
        isGroup: true,
        groupLabel: root.label,
        groupCount: root.count,
      })
      if (hasChildren && isExpanded) {
        traverseChildren(visibleChildren, depth + 1)
      }
    }
  }
  traverseRoots(props.roots, 0)
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

/* 根据当前 scrollTop 找到应该显示的行范围（二分定位起始行，线性扫尾部）。 */
const visibleRange = computed(() => {
  const total = flatRows.value.length
  if (total === 0) return { startIdx: 0, endIdx: 0 }
  const containerHeight = treeContainerRef.value?.clientHeight || 600
  const scrollPos = scrollTop.value

  let low = 0
  let high = total
  while (low < high) {
    const mid = (low + high) >> 1
    if (rowOffsets.value[mid] + getRowHeight(flatRows.value[mid].id) > scrollPos) {
      high = mid
    } else {
      low = mid + 1
    }
  }
  const startIdx = Math.max(0, low - BUFFER_COUNT)

  let endIdx = total
  for (let i = startIdx; i < total; i++) {
    if (rowOffsets.value[i] > scrollPos + containerHeight) {
      endIdx = Math.min(total, i + BUFFER_COUNT)
      break
    }
  }

  return { startIdx, endIdx }
})

/* 可见区域第一个元素的 Y 偏移量（用于 translateY 定位）。 */
const offsetY = computed(() => {
  return rowOffsets.value[visibleRange.value.startIdx] || 0
})

const visibleRows = computed(() => flatRows.value.slice(visibleRange.value.startIdx, visibleRange.value.endIdx))

interface RowView {
  id: string
  depth: number
  hasChildren: boolean
  isExpanded: boolean
  isGroup: boolean
  groupLabel: string
  groupCount: number
  levelTag: string | null
  typeTag: string | null
  positionTag: string | null
  pageLabelTag: string | null
  summaryText: string
  fullMetaText: string
  isTitle: boolean
  suppressPlainText: boolean
  displayText: string
  displayTextHtml: string
  inlineMediaHtml: string
  checked: boolean
  hasNode: boolean
  furniture: boolean
  hasPreviewImage: boolean
}

/* 可见行渲染数据：一次计算，模板直接取值，避免重复查询。 */
const rowViews = computed<RowView[]>(() => visibleRows.value.map((row) => {
  const id = row.id
  const node = row.isGroup ? undefined : rowNode(id)
  const suppressPlainText = shouldSuppressNodePlainText(node)
  const isMediaWithCaption = node?.block_type === 'table'
    || node?.block_type === 'image'
    || node?.block_type === 'figure'
  const mediaCaption = isMediaWithCaption ? String(effectiveField(node, 'caption') || '').trim() : ''
  let displayTextHtml = ''
  if (!suppressPlainText) {
    const rawText = String(
      mediaCaption || (isMediaWithCaption ? '' : effectiveField(node, 'plain_text'))
    ).trim() || (isMediaWithCaption ? '' : id)
    displayTextHtml = rawText
      ? renderMarkdownInlineToHtml(rawText, props.sourceFilePath || '')
      : ''
  }
  const isFormulaOrTable = node
    ? (node.block_type === 'equation_interline' || node.block_type === 'formula' || node.block_type === 'table')
    : false
  const hasRichMedia = Boolean(
    node && (
      (Array.isArray(node.rich_media_order) && node.rich_media_order.length > 0)
      || node.table_html
      || node.math_content
      || node.image_path
      || (Array.isArray(node.image_paths) && node.image_paths.length > 0)
    )
  )
  const mediaFootnote = isMediaWithCaption ? String(effectiveField(node, 'footnote') || '').trim() : ''
  const baseInlineMediaHtml = hasRichMedia
    ? renderNodeRichMedia(node, props.sourceFilePath, { includeImages: !isFormulaOrTable })
    : ''
  const inlineMediaHtml = baseInlineMediaHtml + (mediaFootnote
    ? `<div class="media-footnote">${renderMarkdownInlineToHtml(mediaFootnote, props.sourceFilePath || '')}</div>`
    : '')
  const printedPageLabel = node ? printedPageByPageIdx.value.get(node.page_idx) : undefined
  const levelTag = getNodeLevelTag(node, props.nodeMap)
  const typeTag = getNodeTypeTag(node)
  const positionTag = getNodePositionTag(node)
  const pageLabelTag = printedPageLabel ? `${printedPageLabel}页` : null
  const hasPreviewImage = Boolean(node && isImagePreviewNode(node))
  const metaParts = [levelTag, typeTag, positionTag, pageLabelTag].filter(Boolean)
  const summaryParts = [levelTag, pageLabelTag].filter(Boolean)
  return {
    id,
    depth: row.depth,
    hasChildren: row.hasChildren,
    isExpanded: row.isExpanded,
    isGroup: Boolean(row.isGroup),
    groupLabel: row.groupLabel || '',
    groupCount: row.groupCount || 0,
    levelTag,
    typeTag,
    positionTag,
    pageLabelTag,
    summaryText: summaryParts.join(' · '),
    fullMetaText: [...metaParts, hasPreviewImage ? '查看图片' : null].filter(Boolean).join(' · '),
    isTitle: node?.block_type === 'title',
    suppressPlainText,
    displayText: mediaCaption ? mediaCaption.slice(0, 24) : getNodeDisplayText(node, id),
    displayTextHtml,
    inlineMediaHtml,
    checked: Boolean(props.selectedNodeIds?.has(id)),
    hasNode: Boolean(node),
    furniture: isFurnitureNode(node),
    hasPreviewImage
  }
}))

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

/* expand/collapse changed (Set mutated in place): re-measure visible rows */
watch(() => props.expandedNodeIds.size, () => {
  nextTick(() => measureVisibleRows())
})

/* 组件挂载后进行首次测量。 */
onMounted(() => {
  nextTick(() => measureVisibleRows())
})

/* modal closed: clear cached preview node */
watch(previewVisible, (open) => {
  if (!open) {
    previewNode.value = null
    previewImages.value = []
  }
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
  if (isFrontMatterGroupId(rowId)) {
    onToggle(rowId)
    return
  }
  const node = props.nodeMap.get(rowId)
  if (node && isImagePreviewNode(node)) {
    openImagePreview(node)
  }
  const children = props.childrenMap.get(rowId) || []
  if (children.length > 0) {
    onToggle(rowId)
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

const makeContextMenuClick = (rowId: string) => (payload: { key: string }) => {
  onContextMenuClick(payload, rowId)
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

.doc-blocks-tree.dark {
  .tree-row:hover {
    border-color: var(--dp-hover-border, #3b4a63);
    background: var(--dp-hover-bg, #1f2532);
  }

  .tree-row.active {
    border-color: var(--dp-active-border, #7c9cf5);
    box-shadow: 0 0 0 2px var(--dp-active-shadow, rgba(124, 156, 245, 0.28));
    background: var(--dp-active-bg, #232b3d);
  }

  .tree-row.flat {
    background: var(--dp-flat-bg, #141821);
    border-color: var(--dp-flat-border, #2a3140);
  }
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

.tree-flat-row > * {
  flex: 1;
  min-width: 0;
}

.tree-row {
  width: 100%;
}

.tree-image-preview {
  display: flex;
  flex-direction: column;
}

.tree-image-preview-header {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  padding: 0 44px;
  box-sizing: border-box;
  min-height: 32px;
}

.tree-image-preview-title {
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  font-size: 14px;
  font-weight: 600;
  max-width: 35%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tree-image-preview-toolbar {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.tree-image-preview-zoom {
  min-width: 40px;
  text-align: center;
  font-size: 12px;
  color: var(--dp-sub-text, #8c8c8c);
}

.tree-image-preview-stage {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0;
  max-height: 68vh;
  overflow-y: scroll;
  overflow-x: auto;
  padding: 8px;
  border: 1px solid var(--dp-pane-border, #e8edf4);
  border-radius: 8px;
  background: var(--dp-surface-bg, #ffffff);
  user-select: none;
  cursor: grab;
}

.tree-image-preview-stage.dragging {
  cursor: grabbing;
}

.tree-image-preview-stage.dragging .preview-image {
  transition: none;
}

.tree-image-preview-stage .preview-image {
  display: block;
  width: 100%;
  max-width: none;
  height: auto;
  flex-shrink: 0;
  margin-left: auto;
  margin-right: auto;
  border-radius: 8px;
  transform-origin: center center;
  will-change: transform, width;
  transition: width 0.12s ease, transform 0.12s ease;
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

.tree-row.previewable {
  cursor: zoom-in;
}

.tree-row.furniture {
  opacity: 0.65;
}

.tree-row.flat {
  background: var(--dp-flat-bg, #ffffff);
  border-style: dashed;
  border-color: var(--dp-flat-border, #d8dee9);
  box-shadow: none;
}

.tree-row.flat:hover {
  border-style: dashed;
}

.tree-group-row {
  background: var(--dp-index-card-bg, #f1f5f9);
  font-weight: 600;
  cursor: pointer;
}

.tree-group-row:hover {
  border-color: var(--dp-hover-border, #a5b4fc);
  background: var(--dp-hover-bg, #eef2ff);
}

.tree-group-title {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  min-width: 0;
  color: var(--dp-title-strong, #4f5d7a);
}

.tree-group-title .group-count-text {
  margin-left: auto;
  flex-shrink: 0;
  font-size: 12px;
  color: var(--dp-sub-text, #8c8c8c);
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
  align-self: center;
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

.tree-main-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  min-width: 0;
}

.tree-text-wrap {
  flex: 1;
  min-width: 0;
}

.tree-text-title {
  font-weight: 600;
}

.tree-summary {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-top: 1px;
  font-size: 11px;
  color: var(--dp-sub-text, #8c8c8c);
  white-space: nowrap;
}

.tree-summary-eye {
  font-size: 11px;
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
  max-height: 60vh;
  overflow-y: auto;
  overflow-x: hidden;
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

.tree-inline-media :deep(.media-formula-row) {
  display: flex;
  align-items: center;
  gap: 8px;
}

.tree-inline-media :deep(.media-formula-number) {
  display: inline-block;
  font-size: 12px;
  color: var(--dp-sub-text, #64748b);
  vertical-align: middle;
  flex-shrink: 0;
}

.tree-inline-media :deep(.media-footnote) {
  margin-top: 6px;
  font-size: 12px;
  color: var(--dp-sub-text, #64748b);
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

</style>
