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
        <div class="pdf-virtual-spacer" :style="{ height: `${virtualContentHeight}px` }">
          <div
            v-for="pageMeta in visiblePdfPages"
            :key="pageMeta.page"
            class="pdf-page-wrapper"
            :style="getPdfPageStyle(pageMeta)"
            :ref="(el) => setPdfPageElement(pageMeta.page, el)"
          >
            <VuePdfEmbed :source="normalizedPdfSource" :page="pageMeta.page" />
            <div class="pdf-highlight-layer" :style="getHighlightLayerStyle(pageMeta.page)">
            <div
              v-for="item in getPageHighlights(pageMeta.page)"
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
import { computed, ref, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
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

interface VirtualPageMeta {
  page: number
  top: number
  height: number
}

interface RenderedPageMetrics {
  top: number
  left: number
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
const pageHeights = ref<Record<number, number>>({})
const estimatedPageHeight = ref(1100)
const renderedPageRange = ref({ start: 1, end: 1 })
const pendingRangeUpdate = ref(false)
const isPdfUserScrolling = ref(false)
const pdfUserScrollTimeout = ref<number | null>(null)
const pendingPdfSyncPercent = ref<number | null>(null)
const pdfSyncRafId = ref<number | null>(null)
const lastEmittedPdfPercent = ref(-1)
const renderedPageMetrics = ref<Record<number, RenderedPageMetrics>>({})
const pageElements = new Map<number, HTMLElement>()
const pageResizeObservers = new Map<number, ResizeObserver>()
const pdfVerticalPadding = 24
const pdfPageGap = 16
const renderBufferPages = 2
const normalizedPdfSource = computed(() => props.pdfViewerUrl.split('#')[0] || props.pdfViewerUrl)
const pageHeightOf = (page: number) => pageHeights.value[page] || estimatedPageHeight.value
const onWindowResize = () => scheduleRenderedPageRangeUpdate()

// Computed page count to use: prefer prop, fallback to local
const displayPdfPageCount = computed(() => {
  if (props.pdfPageCount && props.pdfPageCount > 1) return props.pdfPageCount
  if (localPdfPageCount.value > 1) return localPdfPageCount.value
  return 1
})

const getPageHighlights = (page: number) => {
  if (!props.highlightLinkEnabled) return []
  return props.highlights
    .filter(item => item.page === page)
    .filter(item => item.hasRect !== false)
}

const pageLayout = computed(() => {
  const topByPage: number[] = []
  let cursor = pdfVerticalPadding
  for (let page = 1; page <= displayPdfPageCount.value; page += 1) {
    topByPage[page] = cursor
    cursor += pageHeightOf(page)
    if (page < displayPdfPageCount.value) {
      cursor += pdfPageGap
    }
  }
  return {
    topByPage,
    totalHeight: Math.max(1, cursor + pdfVerticalPadding)
  }
})

const virtualContentHeight = computed(() => pageLayout.value.totalHeight)

const visiblePdfPages = computed<VirtualPageMeta[]>(() => {
  const pages: VirtualPageMeta[] = []
  const start = renderedPageRange.value.start
  const end = renderedPageRange.value.end
  for (let page = start; page <= end; page += 1) {
    pages.push({
      page,
      top: pageLayout.value.topByPage[page] || pdfVerticalPadding,
      height: pageHeightOf(page)
    })
  }
  return pages
})

const getPdfPageStyle = (pageMeta: VirtualPageMeta) => ({
  top: `${pageMeta.top}px`,
  minHeight: `${pageMeta.height}px`
})

const getHighlightLayerStyle = (page: number) => {
  const metrics = renderedPageMetrics.value[page]
  if (!metrics) {
    return {
      inset: '0'
    }
  }
  return {
    top: `${metrics.top}px`,
    left: `${metrics.left}px`,
    width: `${metrics.width}px`,
    height: `${metrics.height}px`
  }
}

const updateEstimatedHeight = () => {
  const values = Object.values(pageHeights.value).filter(height => Number.isFinite(height) && height > 0)
  if (!values.length) return
  const total = values.reduce((sum, item) => sum + item, 0)
  estimatedPageHeight.value = Math.max(600, Math.round(total / values.length))
}

const updateRenderedPageRange = () => {
  const container = pdfScrollRef.value
  if (!container || !props.isPdf) {
    renderedPageRange.value = { start: 1, end: Math.max(1, displayPdfPageCount.value) }
    return
  }
  const pageCount = Math.max(1, displayPdfPageCount.value)
  if (pageCount <= 1) {
    renderedPageRange.value = { start: 1, end: 1 }
    return
  }
  const viewportTop = container.scrollTop
  const viewportBottom = viewportTop + container.clientHeight
  let firstVisibleIndex = -1
  let lastVisibleIndex = -1

  for (let page = 1; page <= pageCount; page += 1) {
    const pageTop = pageLayout.value.topByPage[page] || 0
    const pageBottom = pageTop + pageHeightOf(page)
    const intersectsViewport = pageBottom >= viewportTop && pageTop <= viewportBottom
    if (intersectsViewport) {
      if (firstVisibleIndex === -1) firstVisibleIndex = page
      lastVisibleIndex = page
    }
  }

  if (firstVisibleIndex === -1 || lastVisibleIndex === -1) {
    const fallbackPage = Math.max(1, Math.min(pageCount, props.currentPdfPage || 1))
    renderedPageRange.value = {
      start: Math.max(1, fallbackPage - renderBufferPages),
      end: Math.min(pageCount, fallbackPage + renderBufferPages)
    }
    return
  }

  renderedPageRange.value = {
    start: Math.max(1, firstVisibleIndex - renderBufferPages),
    end: Math.min(pageCount, lastVisibleIndex + renderBufferPages)
  }
}

const scheduleRenderedPageRangeUpdate = () => {
  if (pendingRangeUpdate.value) return
  pendingRangeUpdate.value = true
  requestAnimationFrame(() => {
    pendingRangeUpdate.value = false
    updateRenderedPageRange()
  })
}

const markPdfUserScrolling = () => {
  isPdfUserScrolling.value = true
  if (pdfUserScrollTimeout.value !== null) {
    window.clearTimeout(pdfUserScrollTimeout.value)
  }
  pdfUserScrollTimeout.value = window.setTimeout(() => {
    isPdfUserScrolling.value = false
    pdfUserScrollTimeout.value = null
  }, 140)
}

const emitPdfScrollPercent = (percent: number) => {
  pendingPdfSyncPercent.value = percent
  if (pdfSyncRafId.value !== null) return
  pdfSyncRafId.value = requestAnimationFrame(() => {
    pdfSyncRafId.value = null
    const nextPercent = pendingPdfSyncPercent.value
    pendingPdfSyncPercent.value = null
    if (nextPercent === null) return
    if (Math.abs(nextPercent - lastEmittedPdfPercent.value) < 0.006) return
    lastEmittedPdfPercent.value = nextPercent
    emit('text-scroll', nextPercent)
  })
}

const setPdfPageElement = (page: number, el: Element | null) => {
  const element = el instanceof HTMLElement ? el : null
  const previous = pageElements.get(page)
  if (previous && previous !== element) {
    const prevObserver = pageResizeObservers.get(page)
    prevObserver?.disconnect()
    pageResizeObservers.delete(page)
    pageElements.delete(page)
  }
  if (!element) return
  pageElements.set(page, element)

  const measureHeight = () => {
    const mediaElement = element.querySelector('canvas, img') as HTMLElement | null
    if (!mediaElement) return
    const mediaRect = mediaElement.getBoundingClientRect()
    const wrapperRect = element.getBoundingClientRect()
    const nextHeight = Math.max(400, Math.round(mediaRect.height))
    const nextMetrics: RenderedPageMetrics = {
      top: Math.max(0, mediaRect.top - wrapperRect.top),
      left: Math.max(0, mediaRect.left - wrapperRect.left),
      width: Math.max(1, mediaRect.width),
      height: nextHeight
    }
    const currentHeight = pageHeights.value[page]
    const currentMetrics = renderedPageMetrics.value[page]
    const metricsChanged = !currentMetrics
      || Math.abs(currentMetrics.top - nextMetrics.top) > 0.5
      || Math.abs(currentMetrics.left - nextMetrics.left) > 0.5
      || Math.abs(currentMetrics.width - nextMetrics.width) > 0.5
      || Math.abs(currentMetrics.height - nextMetrics.height) > 0.5

    if (currentHeight !== nextHeight) {
      pageHeights.value = {
        ...pageHeights.value,
        [page]: nextHeight
      }
      updateEstimatedHeight()
      scheduleRenderedPageRangeUpdate()
    }

    if (metricsChanged) {
      renderedPageMetrics.value = {
        ...renderedPageMetrics.value,
        [page]: nextMetrics
      }
    }
  }

  requestAnimationFrame(measureHeight)

  if (typeof ResizeObserver !== 'undefined' && !pageResizeObservers.has(page)) {
    const observer = new ResizeObserver(() => {
      measureHeight()
    })
    observer.observe(element)
    pageResizeObservers.set(page, observer)
  }
}

// Handle PDF scroll to sync with text
const onPdfScroll = (e: Event) => {
  const target = e.target as HTMLElement
  if (!target) return
  markPdfUserScrolling()
  scheduleRenderedPageRangeUpdate()
  const { scrollTop, scrollHeight, clientHeight } = target
  if (scrollHeight <= clientHeight) return
  
  const percent = scrollTop / (scrollHeight - clientHeight)
  emitPdfScrollPercent(percent)
}

// Watch for external page change to scroll PDF
watch(() => props.currentPdfPage, (newPage) => {
  if (!props.isPdf || !pdfScrollRef.value || newPage <= 0) return
  if (isPdfUserScrolling.value) return
  const targetTop = Math.max(0, (pageLayout.value.topByPage[newPage] || 0) - 8)
  pdfScrollRef.value.scrollTo({ top: targetTop, behavior: 'auto' })
  scheduleRenderedPageRangeUpdate()
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
      const loadingTask = pdfjsLib.getDocument(normalizedPdfSource.value)
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

watch([() => props.isPdf, displayPdfPageCount], async () => {
  if (!props.isPdf) {
    renderedPageRange.value = { start: 1, end: 1 }
    return
  }
  await nextTick()
  scheduleRenderedPageRangeUpdate()
}, { immediate: true })

watch(normalizedPdfSource, async () => {
  pageHeights.value = {}
  renderedPageMetrics.value = {}
  estimatedPageHeight.value = 1100
  renderedPageRange.value = { start: 1, end: 1 }
  lastEmittedPdfPercent.value = -1
  await nextTick()
  scheduleRenderedPageRangeUpdate()
})

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

onMounted(() => {
  window.addEventListener('resize', onWindowResize)
  nextTick(() => {
    scheduleRenderedPageRangeUpdate()
  })
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onWindowResize)
  if (pdfUserScrollTimeout.value !== null) {
    window.clearTimeout(pdfUserScrollTimeout.value)
  }
  if (pdfSyncRafId.value !== null) {
    cancelAnimationFrame(pdfSyncRafId.value)
  }
  pageResizeObservers.forEach(observer => observer.disconnect())
  pageResizeObservers.clear()
  pageElements.clear()
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
}

.pdf-virtual-spacer {
  position: relative;
  width: 100%;
}

.pdf-page-wrapper {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
  width: calc(100% - 48px);
  max-width: 900px;
  background: white;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.pdf-page-wrapper :deep(canvas),
.pdf-page-wrapper :deep(img) {
  display: block;
  width: 100% !important;
  height: auto !important;
}
</style>
