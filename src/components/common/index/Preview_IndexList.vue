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
          :class="['index-item', { active: isItemActive(item, activeLinkedItemId) }]"
          :data-item-id="item.id"
          @mouseenter="emit('hover-item', item.id)"
          @mouseleave="emit('hover-item', null)"
          @click="emit('select-item', resolveSelectId(item, nodeMap))"
        >
          <div class="index-item-header">
            <div class="index-tags">
              <a-tag
                v-for="tag in getItemTags(item, nodeMap)"
                :key="`${item.id}-${tag}`"
                color="blue"
              >
                {{ tag }}
              </a-tag>
            </div>
            <span class="index-order">#{{ item.order_index }}</span>
          </div>
          <div v-if="shouldShowItemText(item)" class="index-title" v-html="getDisplayTitleHtml(item)" />
          <div v-if="shouldShowItemText(item) && getPrimaryContent(item)" class="index-content" v-html="getPrimaryContentHtml(item)" />
          <div v-if="shouldShowItemText(item) && getMediaTextBlocks(item).length" class="index-media-summary">
            <div
              v-for="line in getMediaTextBlocks(item)"
              :key="`${item.id}-${line}`"
              class="index-media-text"
              v-html="renderInlineHtml(line)"
            >
            </div>
          </div>
          <div v-if="hasRichMedia(item, nodeMap)" class="index-media" v-html="renderItemRichMedia(item, nodeMap, sourceFilePath)" />
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
import type { StructuredIndexItem, DocBlockNode } from '../../../types/knowledge'
import {
  findNodeForItem,
  getItemTags,
  hasRichMedia,
  renderMarkdownInlineToHtml,
  renderItemRichMedia,
  resolveSelectId,
  isItemActive,
  shouldSuppressNodePlainText
} from '../../../utils/knowledge'
import {
  getDisplayTitle,
  getPrimaryContent,
  getMediaTextBlocks
} from '../../../utils/common'

const props = defineProps<{
  items: StructuredIndexItem[]
  currentPage: number
  pageSize: number
  activeLinkedItemId: string | null
  nodeMap: Map<string, DocBlockNode>
  sourceFilePath?: string
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

const renderInlineHtml = (content: string): string => renderMarkdownInlineToHtml(content, props.sourceFilePath || '')

const shouldShowItemText = (item: StructuredIndexItem): boolean => {
  const node = findNodeForItem(item, props.nodeMap)
  return !shouldSuppressNodePlainText(node)
}

const getDisplayTitleHtml = (item: StructuredIndexItem): string => renderInlineHtml(getDisplayTitle(item))

const getPrimaryContentHtml = (item: StructuredIndexItem): string => renderInlineHtml(getPrimaryContent(item))
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
  display: flex;
  flex-direction: column;
  gap: 10px;
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

:deep(.index-title .katex),
:deep(.index-content .katex),
:deep(.index-media-text .katex) {
  font-size: 1em;
}

:deep(.index-title .katex-display),
:deep(.index-content .katex-display),
:deep(.index-media-text .katex-display) {
  display: inline-block;
  margin: 0;
  vertical-align: middle;
}

:deep(.index-media .media-image) {
  width: 100%;
  max-width: 100%;
  max-height: 320px;
  object-fit: contain;
  border-radius: 6px;
  display: block;
  background: color-mix(in srgb, var(--dp-content-bg) 92%, #f8fafc 8%);
}

:deep(.index-media .media-formula) {
  overflow-x: auto;
  max-width: 100%;
}

:deep(.index-media .katex-display) {
  margin: 0;
  overflow-x: auto;
  overflow-y: hidden;
}

:deep(.index-media .media-table table) {
  width: 100%;
  border-collapse: collapse;
  table-layout: auto;
}

:deep(.index-media .media-table th),
:deep(.index-media .media-table td) {
  border: 1px solid var(--dp-pane-border) !important;
  padding: 6px 8px;
  background: transparent !important;
}
</style>
