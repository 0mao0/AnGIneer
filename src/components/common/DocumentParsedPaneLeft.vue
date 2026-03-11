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
      <div class="parse-progress-content">
        <a-progress
          :percent="progressPercent"
          :status="node.parseError ? 'exception' : 'active'"
          size="small"
          class="processing-progress"
          :show-info="false"
        />
        <div class="progress-text-info">
          <span class="progress-text">{{ stageText }}</span>
          <span v-if="node.status === 'processing'" class="progress-percentage">{{ progressPercent }}%</span>
        </div>
      </div>
    </div>
    <div class="file-preview">
      <div v-if="isPdf" class="pdf-scroll-container" ref="pdfScrollRef" @scroll="onPdfScroll">
        <div v-for="page in displayPdfPageCount" :key="page" class="pdf-page-wrapper">
          <VuePdfEmbed :source="pdfViewerUrl" :page="page" />
          <div class="pdf-highlight-layer">
            <div
              v-for="item in getPageHighlights(page)"
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
            >
              <span v-if="item.type" class="highlight-type-tag">{{ item.type }}</span>
            </div>
          </div>
        </div>
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
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch, onMounted } from 'vue'
import { LinkOutlined } from '@ant-design/icons-vue'
import VuePdfEmbed from 'vue-pdf-embed'
import * as pdfjsLib from 'pdfjs-dist'

// Set worker source for pdfjs-dist
// In Vite, we need to explicitly import the worker script
// We use a dynamic import to avoid bundling issues if possible, or direct import if needed.
// For simplicity and compatibility, we try to set the workerSrc to a CDN or local path if the import fails.
// However, in a standard Vite setup, we should import the worker file URL.
// We'll use a try-catch block or conditional check.
const setWorker = async () => {
  try {
    // @ts-ignore
    const worker = await import('pdfjs-dist/build/pdf.worker.mjs?url')
    pdfjsLib.GlobalWorkerOptions.workerSrc = worker.default
  } catch (e) {
    console.warn('Failed to load pdf worker via import, falling back to CDN', e)
    pdfjsLib.GlobalWorkerOptions.workerSrc = `https://cdnjs.cloudflare.com/ajax/libs/pdf.js/${pdfjsLib.version}/pdf.worker.min.mjs`
  }
}
setWorker()

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
  type?: string
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
  pdfPageCount?: number
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

const pdfScrollRef = ref<HTMLElement | null>(null)
const leftTextRef = ref<HTMLElement | null>(null)
const applyingExternalScroll = ref(false)
const localPdfPageCount = ref(0)

// Computed page count to use: prefer prop, fallback to local
const displayPdfPageCount = computed(() => {
  if (props.pdfPageCount && props.pdfPageCount > 1) return props.pdfPageCount
  if (localPdfPageCount.value > 1) return localPdfPageCount.value
  return 1
})

// Get highlights for a specific page
const getPageHighlights = (page: number) => {
  if (!props.highlightLinkEnabled) return []
  return props.highlights
    .filter(item => item.page === page)
    .filter(item => item.hasRect !== false)
}

// Handle PDF scroll to sync with text
const onPdfScroll = (e: Event) => {
  const target = e.target as HTMLElement
  if (!target) return
  const { scrollTop, scrollHeight, clientHeight } = target
  if (scrollHeight <= clientHeight) return
  
  const percent = scrollTop / (scrollHeight - clientHeight)
  // Debounce or throttle could be added here if needed
  emit('text-scroll', percent)
}

// Watch for external page change to scroll PDF
watch(() => props.currentPdfPage, (newPage) => {
  if (props.isPdf && pdfScrollRef.value && newPage > 0) {
    // Wait for DOM update
    setTimeout(() => {
      const pages = pdfScrollRef.value?.querySelectorAll('.pdf-page-wrapper')
      if (pages && pages[newPage - 1]) {
        pages[newPage - 1].scrollIntoView({ behavior: 'smooth', block: 'start' })
      }
    }, 100)
  }
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

watch(() => props.pdfViewerUrl, (url) => {
  if (!url || !props.isPdf) return
  
  // Try to load PDF document to get actual page count
  // This is a fallback for when the parser hasn't provided page count yet
  const loadPdf = async () => {
    try {
      // Use the configured worker
      const loadingTask = pdfjsLib.getDocument(url)
      const pdf = await loadingTask.promise
      if (pdf.numPages && pdf.numPages > 0) {
        localPdfPageCount.value = pdf.numPages
      }
    } catch (e) {
      console.warn('Failed to load PDF for page count check', e)
    }
  }
  
  loadPdf()
}, { immediate: true })

// Legacy scroll handler for text viewer
const onLeftTextScroll = (e: Event) => {
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
  padding: 8px 12px;
  border-bottom: 1px solid var(--dp-title-border);
  background: var(--dp-progress-bg);
}

.parse-progress-content {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.processing-progress {
  width: 100%;
}

.progress-text-info {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.progress-text {
  font-size: 11px;
  color: var(--dp-sub-text);
}

.progress-percentage {
  font-size: 11px;
  font-weight: 500;
  color: var(--dp-brand-primary);
}

.file-preview {
  position: relative;
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.pdf-frame-wrap {
  width: 100%;
  height: 100%;
  overflow: hidden;
  position: relative;
}

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
}

.pdf-viewer {
  display: block;
}

.pdf-frame-wrap:hover .pdf-viewer {
  /* No width change on hover to prevent layout shift */
}

.image-viewer {
  width: 100%;
  height: 100%;
  object-fit: contain;
  background: var(--dp-content-bg);
}

.text-viewer {
  width: 100%;
  height: 100%;
  overflow-y: overlay;
  padding: 16px;
  background: var(--dp-bg);
  font-family: 'Menlo', 'Monaco', 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;

  &::-webkit-scrollbar {
    width: 6px;
    height: 6px;
    background: transparent;
  }

  &::-webkit-scrollbar-thumb {
    background: rgba(0, 0, 0, 0.1);
    border-radius: 3px;
    
    &:hover {
      background: rgba(0, 0, 0, 0.2);
    }
  }

  &::-webkit-scrollbar-track {
    background: transparent;
  }
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
  z-index: 10;
}

.highlight-type-tag {
  position: absolute;
  left: 0;
  top: 0;
  background: #1677ff;
  color: #fff;
  font-size: 10px;
  line-height: 1;
  padding: 2px 4px;
  border-bottom-right-radius: 4px;
  white-space: nowrap;
  pointer-events: none;
  opacity: 0;
  transition: opacity 0.2s;
  z-index: 11;
}

.pdf-highlight-box:hover .highlight-type-tag,
.pdf-highlight-box.active .highlight-type-tag {
  opacity: 1;
}

.pdf-scroll-container {
  flex: 1;
  overflow-y: auto;
  position: relative;
  background: var(--dp-bg-tertiary, #f5f5f5);
  padding: 24px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
}

.pdf-page-wrapper {
  position: relative;
  width: 100%;
  max-width: 900px;
  background: white;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  /* Ensure canvas inside VuePdfEmbed fits nicely */
}

/* Ensure images/canvas inside behave responsively */
.pdf-page-wrapper :deep(canvas),
.pdf-page-wrapper :deep(img) {
  display: block;
  width: 100% !important;
  height: auto !important;
}
</style>
