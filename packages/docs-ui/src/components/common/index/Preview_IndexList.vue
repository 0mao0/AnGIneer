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
  getItemTags,
  hasRichMedia,
  renderItemRichMedia,
  resolveSelectId,
  isItemActive
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
