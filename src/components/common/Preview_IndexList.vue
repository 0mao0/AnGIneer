<template>
  <div class="index-list-wrap">
    <div class="index-content-scroll">
      <a-empty
        v-if="!items.length"
        description="暂无索引数据，请点击右上角入库"
        class="b2-empty-inline"
      />
      <div v-else class="index-list">
        <div
          v-for="item in pagedItems"
          :key="item.id"
          :class="['index-item', { active: isItemActive(item) }]"
          :data-item-id="item.id"
          @mouseenter="emit('hover-item', item.id)"
          @mouseleave="emit('hover-item', null)"
          @click="emit('select-item', resolveSelectId(item))"
        >
          <div class="index-item-header">
            <div class="index-tags">
              <a-tag
                v-for="tag in getItemTags(item)"
                :key="`${item.id}-${tag}`"
                color="blue"
              >
                {{ tag }}
              </a-tag>
            </div>
            <span class="index-order">#{{ item.order_index }}</span>
          </div>
          <div class="index-title">{{ getDisplayTitle(item) }}</div>
          <div v-if="getPrimaryContent(item)" class="index-content">{{ getPrimaryContent(item) }}</div>
          <div v-if="getMediaTextBlocks(item).length" class="index-media-summary">
            <div
              v-for="line in getMediaTextBlocks(item)"
              :key="`${item.id}-${line}`"
              class="index-media-text"
            >
              {{ line }}
            </div>
          </div>
          <div v-if="hasRichMedia(item)" class="index-media" v-html="renderItemRichMedia(item)" />
        </div>
      </div>
    </div>
    <div
      v-if="items.length > pageSize"
      class="index-pagination"
    >
      <a-pagination
        :current="currentPage"
        :page-size="pageSize"
        :total="items.length"
        size="small"
        :show-size-changer="false"
        @change="emit('page-change', $event)"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import katex from 'katex'
import 'katex/dist/katex.min.css'
import type { StructuredIndexItem, DocBlockNode } from '../../types/knowledge'
import { formatStructuredItemType, stripMarkdownSyntax } from '../../utils/knowledge'

const props = defineProps<{
  items: StructuredIndexItem[]
  currentPage: number
  pageSize: number
  activeLinkedItemId: string | null
  nodeMap: Map<string, DocBlockNode>
}>()

const emit = defineEmits<{
  'hover-item': [id: string | null]
  'select-item': [id: string]
  'page-change': [page: number]
}>()

const pagedItems = computed(() => {
  const start = (props.currentPage - 1) * props.pageSize
  return props.items.slice(start, start + props.pageSize)
})

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

const getNodeLevel = (node: DocBlockNode): number | null => {
  if (node.derived_level !== null && node.derived_level !== undefined) {
    return node.derived_level
  }
  const parentId = node.parent_uid
  if (!parentId) return null
  const parent = props.nodeMap.get(parentId)
  if (!parent) return null
  const parentLevel = getNodeLevel(parent)
  if (parentLevel === null) return null
  return parentLevel + 1
}

const findNodeForItem = (item: StructuredIndexItem): DocBlockNode | null => {
  const refs = collectItemRefs(item)
  for (const ref of refs) {
    const direct = props.nodeMap.get(ref)
    if (direct) return direct
  }
  const meta = item.meta || {}
  const pageSeq = Number(meta.page_seq || meta.page || 0)
  const blockSeq = Number(meta.block_seq || 0)
  if (pageSeq > 0 && blockSeq > 0) {
    for (const node of props.nodeMap.values()) {
      if ((Number(node.page_idx ?? 0) + 1) === pageSeq && Number(node.block_seq ?? 0) === blockSeq) {
        return node
      }
    }
  }
  return null
}

const getItemTags = (item: StructuredIndexItem): string[] => {
  const meta = item.meta || {}
  const node = findNodeForItem(item)
  const tags: string[] = []
  const level = Number(meta.level ?? meta.heading_level ?? meta.derived_level ?? (node ? getNodeLevel(node) : null))
  if (Number.isFinite(level) && level > 0) {
    tags.push(`等级 L${Math.round(level)}`)
  }
  tags.push(`类型 ${formatStructuredItemType(item.item_type)}`)
  const pageSeq = Number(meta.page_seq || meta.page || (node ? Number(node.page_idx ?? 0) + 1 : 0))
  if (pageSeq > 0) {
    tags.push(`页 ${pageSeq}`)
  }
  return Array.from(new Set(tags.filter(Boolean)))
}

const getDisplayTitle = (item: StructuredIndexItem): string => {
  const title = (item.title || '').trim()
  const content = stripMarkdownSyntax((item.content || '').trim())
  const sectionNo = String(item.meta?.section_no || '').trim()
  const numberedPrefix = (title || content).match(/^(\d+(?:\.\d+){1,})/)
  if (sectionNo) {
    if (title && !title.toLowerCase().startsWith('section')) return `${sectionNo} ${title}`.trim()
    if (content) return `${sectionNo} ${content}`.trim()
    return sectionNo
  }
  if (title && title.toLowerCase() !== 'section') {
    return title
  }
  if (numberedPrefix && content && !content.startsWith(numberedPrefix[1])) {
    return `${numberedPrefix[1]} ${content}`.trim()
  }
  return content || title || '未命名条目'
}

const getPrimaryContent = (item: StructuredIndexItem): string => {
  const title = getDisplayTitle(item)
  const content = stripMarkdownSyntax((item.content || '').trim())
  if (!content) return ''
  if (!title) return content
  if (title === content) return ''
  if (content.startsWith(title) && content.length <= title.length + 4) return ''
  return content
}

const getMediaTextBlocks = (item: StructuredIndexItem): string[] => {
  const meta = item.meta || {}
  const lines: string[] = []
  const append = (label: string, value: unknown) => {
    const text = stripMarkdownSyntax(String(value || '').trim())
    if (!text) return
    lines.push(`${label}：${text}`)
  }
  append('题目', meta.caption || meta.table_caption || meta.image_caption || meta.title)
  append('内容', meta.text || meta.body || meta.content || item.content)
  append('脚注', meta.footnote || meta.table_footnote || meta.image_footnote || meta.note)
  return Array.from(new Set(lines))
}

const escapeHtml = (content: string): string => content
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')

const escapeHtmlAttribute = (content: string): string => content
  .replace(/&/g, '&amp;')
  .replace(/"/g, '&quot;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')

const renderFormula = (formula: string): string => {
  const source = formula.trim()
  if (!source) return ''
  try {
    return katex.renderToString(source, { throwOnError: false, displayMode: true })
  } catch {
    return `<code>${escapeHtml(source)}</code>`
  }
}

const resolveMediaSource = (source: string): string => {
  const trimmed = source.trim()
  if (!trimmed) return ''
  if (/^(https?:)?\/\//i.test(trimmed) || /^data:/i.test(trimmed) || /^blob:/i.test(trimmed)) return trimmed
  if (trimmed.startsWith('/api/files?') || trimmed.startsWith('/')) return trimmed
  if (/^[a-zA-Z]:[\\/]/.test(trimmed)) {
    return `/api/files?path=${encodeURIComponent(trimmed)}`
  }
  return trimmed
}

const hasRichMedia = (item: StructuredIndexItem): boolean => {
  const node = findNodeForItem(item)
  if (!node) return false
  return Boolean(node.table_html || node.math_content || node.image_path)
}

const renderItemRichMedia = (item: StructuredIndexItem): string => {
  const node = findNodeForItem(item)
  if (!node) return ''
  if (node.table_html) {
    return `<div class="media-table">${node.table_html}</div>`
  }
  if (node.math_content) {
    return `<div class="media-formula">${renderFormula(node.math_content)}</div>`
  }
  if (node.image_path) {
    const src = resolveMediaSource(node.image_path)
    if (!src) return ''
    return `<img class="media-image" src="${escapeHtmlAttribute(src)}" alt="${escapeHtmlAttribute(node.plain_text || 'image')}" />`
  }
  return ''
}

const isItemActive = (item: StructuredIndexItem): boolean => {
  if (!props.activeLinkedItemId) return false
  const activeId = props.activeLinkedItemId
  if (item.id === activeId) return true
  const refs = collectItemRefs(item)
  return refs.includes(activeId)
}

const resolveSelectId = (item: StructuredIndexItem) => {
  const node = findNodeForItem(item)
  if (node) {
    return node.id
  }
  return item.id
}
</script>

<style lang="less" scoped>
.index-list-wrap {
  padding: 10px;
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.index-content-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  margin: 0 -4px;
  padding: 0 4px;

  &::-webkit-scrollbar {
    width: 6px;
    height: 6px;
    background: transparent;
  }

  &::-webkit-scrollbar-thumb {
    background: rgba(100, 116, 139, 0.25);
    border-radius: 3px;

    &:hover {
      background: rgba(100, 116, 139, 0.4);
    }
  }

  &::-webkit-scrollbar-track {
    background: transparent;
  }
}

.index-pagination {
  flex-shrink: 0;
  padding-top: 10px;
  display: flex;
  justify-content: flex-end;
}

.index-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.index-item {
  border: 1px solid var(--dp-pane-border);
  border-radius: 8px;
  background: var(--dp-index-card-bg);
  padding: 10px;
  cursor: pointer;
}

.index-item.active {
  border-color: rgba(22, 119, 255, 0.8);
  box-shadow: 0 0 0 2px rgba(22, 119, 255, 0.14);
  background: color-mix(in srgb, var(--dp-index-card-bg) 80%, #e6f4ff 20%);
}

.index-item-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.index-tags {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.index-order {
  color: var(--dp-sub-text);
  font-size: 12px;
}

.index-title {
  font-weight: 600;
  color: var(--dp-title-strong);
  margin-bottom: 4px;
}

.index-content {
  color: var(--dp-title-text);
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.index-media {
  margin-top: 8px;
  padding: 8px;
  border-radius: 8px;
  border: 1px solid var(--dp-pane-border);
  background: color-mix(in srgb, var(--dp-content-bg) 90%, #f1f5f9 10%);
}

.index-media-summary {
  margin-top: 6px;
  padding: 8px;
  border-radius: 8px;
  border: 1px solid var(--dp-pane-border);
  background: color-mix(in srgb, var(--dp-content-bg) 92%, #eef2ff 8%);
}

.index-media-text {
  color: var(--dp-title-text);
  font-size: 12px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
}

:deep(.index-media .media-image) {
  width: 100%;
  max-height: 320px;
  object-fit: contain;
  border-radius: 6px;
  display: block;
}

:deep(.index-media .media-formula) {
  overflow-x: auto;
}

:deep(.index-media .media-table table) {
  width: 100%;
  border-collapse: collapse;
}

:deep(.index-media .media-table th),
:deep(.index-media .media-table td) {
  border: 1px solid var(--dp-pane-border);
  padding: 6px 8px;
}
</style>
