<template>
  <div class="split-pane split-pane-right">
    <div class="pane-title b2-pane-title">
      <div class="b2-title-row">
        <div class="b2-title-main">
          <span class="pane-title-prefix pane-title-prefix-right">解析</span>
          <a-radio-group
            :value="activeTab"
            size="small"
            class="b2-tab-buttons"
            option-type="button"
            button-style="solid"
            @change="onTabChange"
          >
            <a-radio-button value="html">Html</a-radio-button>
            <a-radio-button value="markdown">Markdown</a-radio-button>
            <a-radio-button value="index">索引</a-radio-button>
          </a-radio-group>
        </div>
        <div class="pane-actions-right pane-actions-secondary">
          <template v-if="activeTab === 'markdown'">
            <a-button
              type="primary"
              size="small"
              :disabled="!isContentDirty"
              class="action-btn"
              @click="emit('save-markdown')"
            >
              保存
            </a-button>
            <a-button
              size="small"
              :disabled="!isContentDirty"
              class="action-btn"
              @click="emit('cancel-markdown')"
            >
              取消
            </a-button>
          </template>
          <template v-if="activeTab === 'index'">
            <a-select
              :value="strategyValue"
              size="small"
              class="strategy-select"
              @change="emit('strategy-change', $event)"
            >
              <a-select-option value="A_structured">结构化</a-select-option>
              <a-select-option value="B_mineru_rag">MinerU-RAG</a-select-option>
              <a-select-option value="C_pageindex">PageIndex</a-select-option>
            </a-select>
            <a-button
              type="primary"
              size="small"
              :loading="ingestStatusValue === 'processing'"
              :disabled="!canIngest"
              class="ingest-btn action-btn"
              @click="emit('trigger-ingest')"
            >
              {{ ingestButtonText }}
            </a-button>
          </template>
        </div>
      </div>
    </div>

    <div ref="rightPaneRef" class="b2-content" @scroll.passive="onRightPaneScroll">
      <div v-if="activeTab === 'html'" class="markdown-preview" v-html="renderedMarkdown" />
      <div v-else-if="activeTab === 'markdown'" class="markdown-edit-wrap">
        <a-textarea
          ref="markdownTextareaRef"
          :value="editableContent"
          class="markdown-editor"
          @update:value="emit('update:editableContent', $event)"
        />
      </div>
      <div v-else class="index-list-wrap">
        <div class="index-summary-row index-summary-primary">
          <a-tag color="default">总条目 {{ indexSummaryStats.total }}</a-tag>
          <a-tag color="purple">公式 {{ indexSummaryStats.formula }}</a-tag>
          <a-tag color="cyan">表格 {{ indexSummaryStats.table }}</a-tag>
          <a-tag color="geekblue">图形 {{ indexSummaryStats.figure }}</a-tag>
        </div>
        <a-empty
          v-if="!structuredItems.length"
          description="暂无索引数据，请点击右上角入库"
          class="b2-empty-inline"
        />
        <div v-else class="index-list">
          <div
            v-for="item in structuredItems"
            :key="item.id"
            :class="['index-item', { active: item.id === activeLinkedItemId }]"
            @mouseenter="emit('hover-item', item.id)"
            @mouseleave="emit('hover-item', null)"
            @click="emit('select-item', item.id)"
          >
            <div class="index-item-header">
              <a-tag color="blue">{{ formatItemType(item.item_type) }}</a-tag>
              <span class="index-order">#{{ item.order_index }}</span>
            </div>
            <div class="index-title">{{ item.title || '未命名条目' }}</div>
            <div class="index-content">{{ item.content }}</div>
            <div class="index-sub-content">二级内容：{{ getSecondaryContent(item) }}</div>
          </div>
        </div>
      </div>
      <a-empty
        v-if="!hasParsedContent"
        class="b2-empty"
      >
        <template #description>
          <div class="b2-empty-desc">请先解析文档<br>解析完成后将显示结果</div>
        </template>
      </a-empty>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import type { KnowledgeStrategy, StructuredIndexItem } from '../../types/knowledge'

const props = defineProps<{
  activeTab: 'html' | 'markdown' | 'index'
  renderedMarkdown: string
  editableContent: string
  isContentDirty: boolean
  strategyValue: KnowledgeStrategy
  ingestStatusValue: 'idle' | 'processing' | 'completed' | 'failed'
  canIngest: boolean
  ingestButtonText: string
  structuredItems: StructuredIndexItem[]
  indexSummaryStats: {
    total: number
    formula: number
    table: number
    figure: number
  }
  hasParsedContent: boolean
  contentScrollPercent: number
  activeLinkedItemId: string | null
  activeLineRange: { start: number; end: number } | null
}>()

const emit = defineEmits<{
  'update:activeTab': [value: 'html' | 'markdown' | 'index']
  'update:editableContent': [value: string]
  'save-markdown': []
  'cancel-markdown': []
  'strategy-change': [value: KnowledgeStrategy]
  'trigger-ingest': []
  'content-scroll': [percent: number]
  'hover-item': [id: string | null]
  'select-item': [id: string]
}>()

const rightPaneRef = ref<HTMLElement | null>(null)
const markdownTextareaRef = ref()
const applyingExternalScroll = ref(false)

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
  if (value === 'html' || value === 'markdown' || value === 'index') {
    emit('update:activeTab', value)
  }
}

const getSecondaryContent = (item: StructuredIndexItem) => {
  const meta = item.meta || {}
  const candidates = [
    meta.children_summary,
    meta.children,
    meta.sub_items,
    meta.caption,
    meta.note,
    meta.headers
  ].filter(Boolean)
  if (candidates.length > 0) {
    const value = candidates[0]
    return typeof value === 'string' ? value : JSON.stringify(value)
  }
  return '含该索引节点下的细分内容'
}

const formatItemType = (itemType: string) => {
  if (itemType === 'heading') return '标题'
  if (itemType === 'clause') return '条款'
  if (itemType === 'table') return '表格'
  if (itemType === 'image') return '图片'
  return itemType || '未知'
}

const getOffsetByLine = (text: string, line: number) => {
  if (line <= 1) return 0
  let currentLine = 1
  let offset = 0
  while (offset < text.length && currentLine < line) {
    if (text[offset] === '\n') {
      currentLine += 1
    }
    offset += 1
  }
  return offset
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

watch(() => props.activeLineRange, (range) => {
  if (!range || props.activeTab !== 'markdown') return
  const textarea = markdownTextareaRef.value?.resizableTextArea?.textArea as HTMLTextAreaElement | undefined
  if (!textarea) return
  const text = props.editableContent || ''
  const start = getOffsetByLine(text, range.start)
  const end = getOffsetByLine(text, range.end + 1)
  textarea.focus({ preventScroll: true })
  textarea.setSelectionRange(start, Math.max(start, end))
}, { immediate: true })
</script>

<style lang="less" scoped>
.split-pane {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
  border: 1px solid var(--dp-pane-border);
  border-radius: 8px;
  background: var(--dp-pane-bg);
  overflow: hidden;
}

.pane-title {
  font-size: 13px;
  color: var(--dp-title-text);
  padding: 6px 10px;
  border-bottom: 1px solid var(--dp-title-border);
  background: var(--dp-title-bg);
  min-height: 44px;
  box-sizing: border-box;
}

.pane-title-prefix {
  font-size: 13px;
  font-weight: 500;
  color: var(--dp-title-strong);
}

.b2-pane-title {
  display: flex;
  align-items: center;
  padding: 6px 8px;
}

.b2-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-height: 30px;
  width: 100%;
  flex-wrap: nowrap;
}

.b2-title-main {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  flex: 1;
  flex-wrap: nowrap;
}

.pane-actions-secondary {
  flex: 0 0 auto;
  justify-content: flex-end;
  gap: 4px;
}

.action-btn {
  height: 26px;
  border-radius: 6px;
  font-size: 12px;
  padding-inline: 10px;
}

.b2-tab-buttons {
  flex: 0 1 auto;
  min-width: 0;
}

:deep(.b2-tab-buttons.ant-radio-group) {
  display: inline-flex;
  padding: 2px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--dp-pane-bg) 88%, var(--dp-pane-border) 12%);
}

:deep(.b2-tab-buttons .ant-radio-button-wrapper) {
  border: 0;
  border-radius: 999px;
  height: 26px;
  line-height: 24px;
  padding-inline: 12px;
  color: var(--dp-sub-text);
  background: transparent;
  font-size: 12px;
  box-shadow: none;
}

:deep(.b2-tab-buttons .ant-radio-button-wrapper:not(:first-child)::before) {
  display: none;
}

:deep(.b2-tab-buttons .ant-radio-button-wrapper-checked:not(.ant-radio-button-wrapper-disabled)) {
  background: var(--dp-pane-bg);
  color: var(--dp-title-strong);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.12);
}

.strategy-select {
  width: 96px;
}

:deep(.strategy-select .ant-select-selector) {
  height: 28px;
  border-radius: 10px;
  padding: 0 10px;
}

:deep(.strategy-select .ant-select-selection-item) {
  line-height: 26px;
}

.b2-content {
  position: relative;
  flex: 1;
  min-height: 0;
  overflow: auto;
  background: var(--dp-content-bg);
  scrollbar-width: none;
}

.b2-content::-webkit-scrollbar {
  width: 0;
  height: 0;
}

.b2-content:hover {
  scrollbar-width: thin;
}

.b2-content:hover::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

.b2-content:hover::-webkit-scrollbar-thumb {
  background: var(--dp-scroll-thumb);
  border-radius: 999px;
}

.markdown-preview {
  min-height: 100%;
  padding: 12px 14px;
  color: var(--dp-title-text);
  line-height: 1.7;
}

.markdown-edit-wrap {
  height: 100%;
  padding: 8px;
  box-sizing: border-box;
}

.markdown-editor {
  height: 100%;
}

:deep(.markdown-editor textarea) {
  height: 100% !important;
  min-height: 100% !important;
  resize: none;
  line-height: 1.6;
  background: var(--dp-content-bg);
  color: var(--dp-title-text);
}

.index-list-wrap {
  padding: 10px;
}

.index-summary-row {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 10px;
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

.index-sub-content {
  margin-top: 6px;
  color: color-mix(in srgb, var(--dp-title-text) 72%, var(--dp-pane-bg) 28%);
  font-size: 12px;
  line-height: 1.5;
}

.b2-empty {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
  background: var(--dp-empty-overlay);
}

.b2-empty-desc {
  line-height: 1.6;
  color: var(--dp-empty-text);
  text-align: center;
}
</style>
