<template>
  <div class="split-pane split-pane-left">
    <div class="pane-title pane-title-with-actions">
      <div class="pane-title-main">
        <div class="pane-title-prefix-wrap">
          <span class="pane-title-prefix">原文</span>
          <a-switch
            :checked="isSharedVisible"
            class="title-action-switch"
            checked-children="共享"
            un-checked-children="本地"
            @change="emit('toggle-visibility', $event)"
          />
        </div>
        <a-tag v-if="node.status === 'failed'" color="error" class="parse-state-tag">
          解析失败
        </a-tag>
        <a-tag v-else-if="node.status === 'processing'" color="processing" class="parse-state-tag">
          解析中 {{ progressPercent }}%
        </a-tag>
      </div>
      <div class="pane-actions-left">
        <a-button
          v-if="showHighlightToggle"
          size="small"
          class="linkage-btn action-btn"
          :type="highlightLinkEnabled ? 'primary' : 'default'"
          @click="emit('toggle-highlight-link')"
        >
          <template #icon>
            <LinkOutlined />
          </template>
          联动
        </a-button>
        <a-button
          type="primary"
          :loading="node.status === 'processing'"
          class="parse-btn action-btn"
          @click="emit('parse')"
        >
          {{ parseButtonText }}
        </a-button>
      </div>
    </div>
    <div v-if="node.status === 'processing' || node.status === 'failed'" class="parse-progress-row">
      <a-progress
        :percent="progressPercent"
        :status="node.parseError ? 'exception' : 'active'"
        size="small"
        class="processing-progress"
      />
      <span class="progress-text">{{ stageText }}</span>
    </div>
    <div class="file-preview">
      <div v-if="isPdf" class="pdf-frame-wrap">
        <iframe
          :src="pdfViewerUrl"
          class="pdf-viewer"
          frameborder="0"
        />
      </div>
      <div v-else-if="isOffice" class="office-preview">
        <div class="office-frame-wrap">
          <iframe
            :src="officePreviewUrl"
            class="office-viewer"
            frameborder="0"
          />
        </div>
      </div>
      <img
        v-else-if="isImage"
        :src="fileUrl"
        class="image-viewer"
        alt="文档预览"
      />
      <pre
        v-else-if="isText"
        ref="leftTextRef"
        class="text-viewer"
        @scroll.passive="onLeftTextScroll"
      >{{ textContent }}</pre>
      <a-empty v-else description="暂不支持该格式预览，请下载后查看">
        <template #extra>
          <a-button type="primary" @click="emit('download')">下载文件</a-button>
        </template>
      </a-empty>
      <div
        v-if="isPdf && visibleHighlights.length"
        class="pdf-highlight-layer"
      >
        <div
          v-for="item in visibleHighlights"
          :key="item.id"
          :class="['pdf-highlight-box', { active: item.itemId === activeHighlightId }]"
          :style="{
            left: `${item.left * 100}%`,
            top: `${item.top * 100}%`,
            width: `${item.width * 100}%`,
            height: `${item.height * 100}%`
          }"
          @mouseenter="emit('hover-highlight', item.itemId)"
          @mouseleave="emit('hover-highlight', null)"
          @click="emit('select-highlight', item.itemId)"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { LinkOutlined } from '@ant-design/icons-vue'
import type { TreeNode } from '../../composables/useKnowledgeTree'

interface LinkedHighlight {
  id: string
  itemId: string
  page: number
  hasRect?: boolean
  left: number
  top: number
  width: number
  height: number
}

const props = defineProps<{
  node: TreeNode
  activeTab: 'html' | 'markdown' | 'index'
  isSharedVisible: boolean
  parseButtonText: string
  progressPercent: number
  stageText: string
  isPdf: boolean
  isOffice: boolean
  isImage: boolean
  isText: boolean
  pdfViewerUrl: string
  officePreviewUrl: string
  fileUrl: string
  textContent: string
  currentPdfPage: number
  highlights: LinkedHighlight[]
  activeHighlightId: string | null
  highlightLinkEnabled: boolean
  showHighlightToggle: boolean
  textScrollPercent: number
}>()

const emit = defineEmits<{
  parse: []
  'toggle-visibility': [checked?: boolean | string | number]
  download: []
  'text-scroll': [percent: number]
  'hover-highlight': [id: string | null]
  'select-highlight': [id: string]
  'toggle-highlight-link': []
}>()

const leftTextRef = ref<HTMLElement | null>(null)
const applyingExternalScroll = ref(false)

const visibleHighlights = computed(() => {
  if (!props.highlightLinkEnabled) return []
  if (props.isPdf) {
    const pageHighlights = props.highlights
      .filter(item => item.page === props.currentPdfPage)
      .filter(item => item.hasRect !== false)
      .sort((a, b) => a.top - b.top)
    if (props.activeHighlightId) {
      const activeOnly = pageHighlights.filter(item => item.itemId === props.activeHighlightId)
      if (activeOnly.length) {
        return activeOnly
      }
    }
    return pageHighlights
  }
  return props.highlights
})

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

const onLeftTextScroll = () => {
  if (applyingExternalScroll.value) return
  const pane = leftTextRef.value
  if (!pane) return
  emit('text-scroll', getScrollPercent(pane))
}

watch(() => props.textScrollPercent, (percent) => {
  const pane = leftTextRef.value
  if (!pane || !props.isText) return
  applyingExternalScroll.value = true
  setScrollPercent(pane, percent)
  requestAnimationFrame(() => {
    applyingExternalScroll.value = false
  })
})
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

.pane-title-with-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.pane-title-main {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  flex: 1;
}

.pane-title-prefix-wrap {
  display: inline-flex;
  align-items: center;
  gap: 2px;
}

.pane-title-prefix {
  font-size: 13px;
  font-weight: 500;
  color: var(--dp-title-strong);
}

.title-action-switch {
  margin-left: 2px;
}

.parse-state-tag {
  margin-inline-start: 2px;
}

.pane-actions-left {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.action-btn {
  height: 26px;
  border-radius: 6px;
  font-size: 12px;
  padding-inline: 10px;
}

.parse-progress-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-bottom: 1px solid var(--dp-title-border);
  background: var(--dp-progress-bg);
}

.processing-progress {
  flex: 1;
}

.progress-text {
  flex-shrink: 0;
  font-size: 12px;
  color: var(--dp-sub-text);
}

.file-preview {
  position: relative;
  flex: 1;
  min-height: 0;
  display: flex;
  align-items: stretch;
  justify-content: center;
  overflow: hidden;
  background: var(--dp-content-bg);
}

.pdf-frame-wrap,
.office-frame-wrap {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.pdf-viewer,
.office-viewer {
  width: 100%;
  height: 100%;
  min-height: 0;
  border: none;
  background: var(--dp-content-bg);
  transition: width 0.18s ease;
}

.pdf-viewer {
  width: calc(100% + 14px);
}

.pdf-frame-wrap:hover .pdf-viewer {
  width: 100%;
}

.image-viewer {
  width: 100%;
  height: 100%;
  object-fit: contain;
  background: var(--dp-content-bg);
}

.text-viewer {
  margin: 0;
  width: 100%;
  height: 100%;
  overflow: auto;
  background: var(--dp-content-bg);
  color: var(--dp-title-text);
  padding: 10px;
  font-size: 13px;
  line-height: 1.6;
  scrollbar-width: none;
}

.text-viewer::-webkit-scrollbar {
  width: 0;
  height: 0;
}

.text-viewer:hover {
  scrollbar-width: thin;
}

.text-viewer:hover::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

.text-viewer:hover::-webkit-scrollbar-thumb {
  background: var(--dp-scroll-thumb);
  border-radius: 999px;
}

.pdf-highlight-layer {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.pdf-highlight-box {
  position: absolute;
  border: 1px solid rgba(24, 144, 255, 0.42);
  background: rgba(24, 144, 255, 0.08);
  box-shadow: 0 0 0 1px rgba(24, 144, 255, 0.12);
  border-radius: 4px;
  pointer-events: auto;
  transition: background 0.18s ease, border-color 0.18s ease;
}

.pdf-highlight-box.active {
  border-color: rgba(22, 119, 255, 0.95);
  background: rgba(22, 119, 255, 0.24);
}
</style>
