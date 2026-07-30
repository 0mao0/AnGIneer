<template>
  <div :class="['split-pane', themeClass]">
    <div ref="headerTitleRef" class="pane-title pane-title-with-actions">
      <div ref="headerMainRef" class="pane-title-main">
        <div class="pane-title-prefix-wrap">
          <span class="pane-title-prefix">原文</span>
        </div>
        <Tag v-if="node.status === 'failed'" color="error" class="parse-state-tag">
          解析失败
        </Tag>
        <Tag v-else-if="node.status === 'cancelled'" class="parse-state-tag">
          已取�?
        </Tag>
      </div>
      <div
        v-if="isPdf"
        ref="pdfToolbarRef"
        :class="['pane-actions-pdf', { 'pane-actions-pdf-compact': compactLevel > 0 }]"
      >
        <template v-if="!useNativePdfPreview">
          <Button
            size="small"
            class="pdf-tool-btn"
            :disabled="activePdfPage <= 1"
            @click="goPrevPage"
          >
            <template #icon><LeftOutlined /></template>
          </Button>
          <InputNumber
            v-if="compactLevel <= 1"
            :value="activePdfPage"
            size="small"
            :min="1"
            :max="displayPdfPageCount"
            class="pdf-page-input"
            @change="onPageInputChange"
          />
          <span v-if="compactLevel <= 5" class="pdf-toolbar-text">/ {{ displayPdfPageCount }}</span>
          <Button
            size="small"
            class="pdf-tool-btn"
            :disabled="activePdfPage >= displayPdfPageCount"
            @click="goNextPage"
          >
            <template #icon><RightOutlined /></template>
          </Button>
          <Button v-if="compactLevel <= 3" size="small" class="pdf-tool-btn" :disabled="pdfScale <= minPdfScale" @click="zoomOut">
            <template #icon><ZoomOutOutlined /></template>
          </Button>
          <span v-if="compactLevel <= 0" class="pdf-toolbar-text">{{ zoomPercentLabel }}</span>
          <Button v-if="compactLevel <= 2" size="small" class="pdf-tool-btn" :disabled="pdfScale >= maxPdfScale" @click="zoomIn">
            <template #icon><ZoomInOutlined /></template>
          </Button>
          <Button v-if="compactLevel <= 4" size="small" class="pdf-tool-btn" title="适应" @click="resetZoom">
            <template #icon><CompressOutlined /></template>
          </Button>
        </template>
      </div>
      <!-- 右侧占位，用于平衡左侧标题，使中间工具栏居中 -->
      <div v-if="isPdf && !useNativePdfPreview && compactLevel <= 1" class="pane-title-right-placeholder" />
    </div>
    <div v-if="node.status === 'processing' || node.status === 'failed' || node.status === 'cancelled'" class="parse-progress-row">
      <div class="parse-progress-content">
        <Steps :current="parseStepIndex" size="small" class="parse-steps">
          <Step title="准备文件" />
          <Step title="格式转换" />
          <Step title="MinerU解析" />
          <Step title="PoPo增强" />
          <Step title="构建索引" />
          <Step title="解析完成" />
        </Steps>
      </div>
    </div>
    <div class="file-preview">
      <div v-if="isPdf" class="pdf-preview-wrap">
        <!-- PDF加载进度指示�?-->
        <div v-if="isPdfLoading" class="pdf-loading-overlay">
          <Spin size="large" />
          <div class="pdf-loading-text">
            <span v-if="pdfLoadingProgress > 0">加载�?{{ pdfLoadingProgress }}%</span>
            <span v-else>正在加载PDF文档...</span>
          </div>
          <Progress
            v-if="pdfLoadingProgress > 0"
            :percent="pdfLoadingProgress"
            :show-info="false"
            size="small"
            class="pdf-loading-progress"
          />
        </div>
        <div v-if="useNativePdfPreview" class="office-frame-wrap">
          <iframe
            :src="nativePdfViewerUrl"
            class="office-viewer"
            frameborder="0"
          />
        </div>
        <div
          v-else
          :class="['pdf-scroll-container', { 'pdf-scroll-container-fit': isFitToWindowMode }]"
          ref="pdfScrollRef"
          @scroll.passive="onPdfScroll"
        >
          <div class="pdf-virtual-spacer" :style="{ height: `${virtualContentHeight}px`, minWidth: maxPageWidth ? `${maxPageWidth}px` : '100%' }">
            <div
              v-for="pageMeta in visiblePdfPages"
              :key="pageMeta.page"
              class="pdf-page-wrapper"
              :style="getPdfPageStyle(pageMeta)"
              :ref="(el) => setPdfPageElement(pageMeta.page, el)"
            >
              <div class="pdf-page-canvas-wrap">
                <canvas
                  :ref="(el) => setPdfCanvasElement(pageMeta.page, el)"
                  :data-page="pageMeta.page"
                  class="pdf-page-canvas"
                />
              </div>
              <div
                v-show="shouldShowPdfHighlights"
                class="pdf-highlight-layer"
                :key="`hl-layer-${pageMeta.page}`"
                :style="getHighlightLayerStyle(pageMeta.page)"
              >
              <div
                v-for="item in getPageHighlights(pageMeta.page)"
                :key="item.id"
                :class="['pdf-highlight-box', { active: item.id === activeHighlightId || item.itemId === activeHighlightId }]"
                :style="{
                  left: `${item.left * 100}%`,
                  top: `${item.top * 100}%`,
                  width: `${item.width * 100}%`,
                  height: `${item.height * 100}%`
                }"
                @mouseenter="emit('hover-highlight', item.itemId)"
                @mouseleave="emit('hover-highlight', null)"
                @click="emit('select-highlight', item)"
              >
                <span v-if="getHighlightTypeLabel(item.type)" class="highlight-type-tag">{{ getHighlightTypeLabel(item.type) }}</span>
              </div>
            </div>
          </div>
        </div>
        </div>
      </div>
      <div v-else-if="isOffice" class="office-preview">
        <div v-if="showNonPdfLoading" class="pdf-loading-overlay">
          <Spin size="large" />
          <div class="pdf-loading-text">文档转换中，请耐心等待...</div>
        </div>
        <div v-else class="office-frame-wrap">
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
      <Empty v-else description="暂不支持该格式预览，请下载后查看">
        <template #extra>
          <Button type="primary" @click="emit('download')">下载文件</Button>
        </template>
      </Empty>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, shallowRef, watch, onMounted, onBeforeUnmount, nextTick, reactive } from 'vue'
import type { Ref, ComputedRef } from 'vue'
import { LeftOutlined, RightOutlined, ZoomInOutlined, ZoomOutOutlined, CompressOutlined } from '@ant-design/icons-vue'
import { Button, Tag, Spin, Progress, Steps, Step, InputNumber, Empty } from 'ant-design-vue'
import * as pdfjsLib from 'pdfjs-dist'
// Vite标准worker导入方式，确保生产构建路径正�?
import pdfjsWorker from 'pdfjs-dist/build/pdf.worker.min.mjs?url'

export interface PDFViewerNode {
  status?: string
  parseStage?: string
  parseError?: string
  key?: string
  filePath?: string
  file_path?: string
}

interface LinkedHighlight {
  id: string
  itemId: string
  structuredItemId?: string
  page: number
  hasRect: boolean
  left: number
  top: number
  width: number
  height: number
  lineStart: number | null
  lineEnd: number | null
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
  scale: number
}

const props = defineProps<{
  node: PDFViewerNode
  theme?: 'light' | 'dark' | 'auto'
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
  textScrollPercent: number
}>()

const emit = defineEmits<{
  download: []
  'text-scroll': [percent: number]
  'hover-highlight': [id: string | null]
  'select-highlight': [highlight: LinkedHighlight]
  'pdf-active-page': [page: number]
}>()

// --- 常量配置 ---
const MIN_SCALE = 0.1
const MAX_SCALE = 5.0
const MAX_PIXEL_SCALE = 3.0
const SCALE_STEP = 0.1
const VERTICAL_PADDING = 24
const PAGE_GAP = 16
const RENDER_BUFFER = 4
const FIT_PADDING = 12
const MIN_PAGE_HEIGHT = 400

// --- 共享 DOM 引用 ---
const pdfScrollRef = ref<HTMLElement | null>(null)
const leftTextRef = ref<HTMLElement | null>(null)
const headerTitleRef = ref<HTMLElement | null>(null)
const headerMainRef = ref<HTMLElement | null>(null)
const pdfToolbarRef = ref<HTMLElement | null>(null)

// --- PDF Worker 初始�?---
pdfjsLib.GlobalWorkerOptions.workerSrc = pdfjsWorker

// --- Composable: usePdfHeader ---
function usePdfHeader() {
  const compactLevel = ref(0)
  let _toolbarFullWidth = 0
  const headerResizeObserver = shallowRef<ResizeObserver | null>(null)
  const toolbarResizeObserver = shallowRef<ResizeObserver | null>(null)

  function measureToolbarWidth() {
    const toolbar = pdfToolbarRef.value
    if (toolbar) {
      const w = toolbar.scrollWidth || toolbar.clientWidth || toolbar.offsetWidth || toolbar.getBoundingClientRect().width
      if (w > 0) _toolbarFullWidth = w
    }
  }

  function updateHeaderCompactMode() {
    if (!props.isPdf) {
      compactLevel.value = 0
      return
    }
    const headerElement = headerTitleRef.value
    const titleElement = headerMainRef.value
    if (!headerElement) return

    if (_toolbarFullWidth <= 0) {
      measureToolbarWidth()
    }
    const full = _toolbarFullWidth
    if (full <= 0) return

    const headerWidth = headerElement.clientWidth
    const titleWidth = titleElement?.scrollWidth || 0
    if (headerWidth <= 0) return

    const HIDE = [50, 60, 36, 36, 36, 44]
    const levels: number[] = [full]
    for (let i = 0; i < HIDE.length; i++) levels.push(levels[i] - HIDE[i])
    const availWidth = headerWidth - titleWidth - 24
    let level = 6
    for (let lvl = 0; lvl <= 6; lvl++) {
      if (availWidth >= levels[lvl]) { level = lvl; break }
    }
    if (compactLevel.value !== level) compactLevel.value = level
  }

  function setup() {
    measureToolbarWidth()
    updateHeaderCompactMode()
    if (typeof ResizeObserver !== 'undefined') {
      if (headerTitleRef.value) {
        headerResizeObserver.value = new ResizeObserver(() => updateHeaderCompactMode())
        headerResizeObserver.value.observe(headerTitleRef.value)
      }
      if (pdfToolbarRef.value) {
        toolbarResizeObserver.value = new ResizeObserver(() => {
          measureToolbarWidth()
          updateHeaderCompactMode()
        })
        toolbarResizeObserver.value.observe(pdfToolbarRef.value)
      }
    }
  }

  function teardown() {
    headerResizeObserver.value?.disconnect()
    toolbarResizeObserver.value?.disconnect()
  }

  return { compactLevel, updateHeaderCompactMode, setup, teardown }
}

// --- Composable: usePdfVirtualScroll ---
function usePdfVirtualScroll(
  emit: (event: 'text-scroll', percent: number) => void,
  getLocalPdfPageCount: () => number,
) {
  const pageHeights = reactive<Record<number, number>>({})
  const estimatedPageHeight = ref(1100)
  const renderedPageRange = reactive({ start: 1, end: 1 })
  const activePdfPage = ref(1)
  const virtualContentHeight = ref(0)
  const applyingExternalPdfScroll = ref(false)
  const isPdfUserScrolling = ref(false)
  const lastEmittedPdfPercent = ref(-1)

  let pendingRangeUpdate = false
  let pdfUserScrollTimeout: number | null = null
  let pendingPdfSyncPercent: number | null = null
  let pdfSyncRafId: number | null = null
  let _lastEmitTime = 0
  let _layoutDirty = true
  let _cachedLayout: { topByPage: number[]; totalHeight: number } | null = null
  let _cachedPageCount = 0
  let _cachedEstHeight = 0

  const displayPdfPageCount = computed(() => {
    if (props.pdfPageCount && props.pdfPageCount > 1) return props.pdfPageCount
    if (getLocalPdfPageCount() > 1) return getLocalPdfPageCount()
    return 1
  })

  function clampPage(value: number) {
    const total = Math.max(1, displayPdfPageCount.value)
    if (!Number.isFinite(value)) return 1
    return Math.max(1, Math.min(total, Math.round(value)))
  }

  function pageHeightOf(page: number) {
    return pageHeights[page] || estimatedPageHeight.value
  }

  const pageLayout = computed(() => {
    const count = displayPdfPageCount.value
    if (!_layoutDirty && _cachedLayout && count === _cachedPageCount && estimatedPageHeight.value === _cachedEstHeight) {
      return _cachedLayout
    }
    const topByPage: number[] = []
    let cursor = VERTICAL_PADDING
    for (let page = 1; page <= count; page += 1) {
      topByPage[page] = cursor
      const ph = pageHeights[page]
      cursor += (ph > 0) ? ph : estimatedPageHeight.value
      if (page < count) cursor += PAGE_GAP
    }
    _cachedLayout = { topByPage, totalHeight: Math.max(1, cursor + VERTICAL_PADDING) }
    _cachedPageCount = count
    _cachedEstHeight = estimatedPageHeight.value
    _layoutDirty = false
    return _cachedLayout
  })

  function invalidateLayout() { _layoutDirty = true }

  function updateRenderedPageRange() {
    const container = pdfScrollRef.value
    const layout = pageLayout.value
    virtualContentHeight.value = layout.totalHeight
    if (!container || !props.isPdf) {
      renderedPageRange.start = 1
      renderedPageRange.end = Math.max(1, displayPdfPageCount.value)
      return
    }
    const pageCount = Math.max(1, displayPdfPageCount.value)
    if (pageCount <= 1) { renderedPageRange.start = 1; renderedPageRange.end = 1; return }
    const viewportTop = container.scrollTop
    const viewportBottom = viewportTop + container.clientHeight
    let firstVisibleIndex = -1
    let lastVisibleIndex = -1
    for (let page = 1; page <= pageCount; page += 1) {
      const pageTop = layout.topByPage[page] || 0
      const pageBottom = pageTop + pageHeightOf(page) + PAGE_GAP
      const intersectsViewport = pageBottom >= viewportTop && pageTop <= viewportBottom
      if (intersectsViewport) {
        if (firstVisibleIndex === -1) firstVisibleIndex = page
        lastVisibleIndex = page
      }
    }
    if (firstVisibleIndex === -1 || lastVisibleIndex === -1) {
      let closestPage = 1
      let minDiff = Number.POSITIVE_INFINITY
      for (let page = 1; page <= pageCount; page += 1) {
        const diff = Math.abs((layout.topByPage[page] || 0) - viewportTop)
        if (diff < minDiff) { minDiff = diff; closestPage = page }
      }
      renderedPageRange.start = Math.max(1, closestPage - RENDER_BUFFER)
      renderedPageRange.end = Math.min(pageCount, closestPage + RENDER_BUFFER)
      return
    }
    renderedPageRange.start = Math.max(1, firstVisibleIndex - RENDER_BUFFER)
    renderedPageRange.end = Math.min(pageCount, lastVisibleIndex + RENDER_BUFFER)
  }

  function scheduleRenderedPageRangeUpdate() {
    if (pendingRangeUpdate) return
    pendingRangeUpdate = true
    requestAnimationFrame(() => {
      pendingRangeUpdate = false
      updateRenderedPageRange()
    })
  }

  function resolveViewportPage(scrollTop: number, clientHeight: number) {
    const pageCount = Math.max(1, displayPdfPageCount.value)
    const viewportCenter = scrollTop + (clientHeight / 2)
    let bestPage = 1
    let minDistance = Number.POSITIVE_INFINITY
    const layout = pageLayout.value
    for (let page = 1; page <= pageCount; page += 1) {
      const top = layout.topByPage[page] || 0
      const center = top + (pageHeightOf(page) / 2)
      const distance = Math.abs(center - viewportCenter)
      if (distance < minDistance) { minDistance = distance; bestPage = page }
    }
    return bestPage
  }

  function markPdfUserScrolling() {
    isPdfUserScrolling.value = true
    if (pdfUserScrollTimeout !== null) window.clearTimeout(pdfUserScrollTimeout)
    pdfUserScrollTimeout = window.setTimeout(() => {
      isPdfUserScrolling.value = false
      pdfUserScrollTimeout = null
    }, 140)
  }

  function emitPdfScrollPercent(percent: number) {
    pendingPdfSyncPercent = percent
    if (pdfSyncRafId !== null) return
    pdfSyncRafId = requestAnimationFrame((timestamp) => {
      pdfSyncRafId = null
      if (timestamp - _lastEmitTime < 50) return
      _lastEmitTime = timestamp
      const nextPercent = pendingPdfSyncPercent
      pendingPdfSyncPercent = null
      if (nextPercent === null) return
      if (Math.abs(nextPercent - lastEmittedPdfPercent.value) < 0.006) return
      lastEmittedPdfPercent.value = nextPercent
      emit('text-scroll', nextPercent)
    })
  }

  function onPdfScroll(e: Event) {
    const target = e.target as HTMLElement
    if (!target) return
    activePdfPage.value = resolveViewportPage(target.scrollTop, target.clientHeight)
    if (!applyingExternalPdfScroll.value) markPdfUserScrolling()
    scheduleRenderedPageRangeUpdate()
    const { scrollTop, scrollHeight, clientHeight } = target
    if (scrollHeight <= clientHeight) return
    const percent = scrollTop / (scrollHeight - clientHeight)
    if (!applyingExternalPdfScroll.value) emitPdfScrollPercent(percent)
  }

  function scrollToPdfPage(targetPage: number, behavior: ScrollBehavior = 'auto') {
    if (!props.isPdf || !pdfScrollRef.value) return
    const page = clampPage(targetPage)
    const targetTop = Math.max(0, (pageLayout.value.topByPage[page] || 0) - 8)
    activePdfPage.value = page
    const currentTop = pdfScrollRef.value.scrollTop
    scheduleRenderedPageRangeUpdate()
    if (Math.abs(currentTop - targetTop) < pageHeightOf(page)) return
    pdfScrollRef.value.scrollTo({ top: targetTop, behavior })
  }

  function goPrevPage() { scrollToPdfPage(activePdfPage.value - 1, 'smooth') }
  function goNextPage() { scrollToPdfPage(activePdfPage.value + 1, 'smooth') }
  function onPageInputChange(v: any) { const p = Number(v); if (Number.isFinite(p)) scrollToPdfPage(p, 'smooth') }

  return {
    pageHeights, estimatedPageHeight, renderedPageRange, activePdfPage,
    virtualContentHeight, applyingExternalPdfScroll, isPdfUserScrolling,
    lastEmittedPdfPercent, displayPdfPageCount, pageHeightOf,
    pageLayout, updateRenderedPageRange, scheduleRenderedPageRangeUpdate,
    scrollToPdfPage, onPdfScroll, goPrevPage, goNextPage, onPageInputChange,
    invalidateLayout,
  }
}

// --- Composable: usePdfZoom ---
function usePdfZoom(
  scroll: {
    pageHeights: Record<number, number>
    estimatedPageHeight: Ref<number>
    activePdfPage: Ref<number>
    scheduleRenderedPageRangeUpdate: () => void
    scrollToPdfPage: (page: number, behavior: ScrollBehavior) => void
    displayPdfPageCount: ComputedRef<number>
    invalidateLayout: () => void
  },
  renderedPageMetrics: Record<number, RenderedPageMetrics>,
) {
  const pdfScale = ref(1)
  const isFitToWindowMode = ref(true)
  const isScaleTransitioning = ref(false)
  const hasAppliedInitialFit = ref(false)
  const intrinsicPdfPageWidth = ref<number | null>(null)
  const maxPageWidth = ref(0)

  let fitScaleRafId: number | null = null

  const zoomPercentLabel = computed(() => `${Math.round(pdfScale.value * 100)}%`)
  const normalizedPdfSource = computed(() => props.fileUrl || props.pdfViewerUrl.split('#')[0] || props.pdfViewerUrl)

  const nativePdfViewerUrl = computed(() => {
    const page = clampPage(scroll.activePdfPage.value)
    const zoom = Math.max(10, Math.round(pdfScale.value * 100))
    return `${normalizedPdfSource.value}#page=${page}&zoom=${zoom}&toolbar=0&navpanes=0&scrollbar=0`
  })

  function clampPage(value: number) {
    const total = Math.max(1, scroll.displayPdfPageCount.value)
    if (!Number.isFinite(value)) return 1
    return Math.max(1, Math.min(total, Math.round(value)))
  }

  function clampScale(value: number) {
    if (!Number.isFinite(value)) return 1
    return Math.max(MIN_SCALE, Math.min(MAX_SCALE, Number(value.toFixed(2))))
  }

  function getFitToWindowScale() {
    if (!props.isPdf || !pdfScrollRef.value) return null
    const containerWidth = pdfScrollRef.value.clientWidth
    if (!containerWidth || containerWidth <= FIT_PADDING * 2) return null
    const availableWidth = Math.max(1, containerWidth - FIT_PADDING * 2)
    let baseWidth = 0
    const currentPage = scroll.activePdfPage.value || props.currentPdfPage || 1
    const metrics = renderedPageMetrics[currentPage]
    if (metrics && metrics.width > 0) {
      baseWidth = metrics.width / (pdfScale.value || 1)
    }
    if (baseWidth <= 0) baseWidth = intrinsicPdfPageWidth.value || 0
    if (baseWidth <= 0) {
      const allHeights = Object.values(scroll.pageHeights)
      if (allHeights.length > 0) {
        const avgHeight = allHeights.reduce((s, h) => s + h, 0) / allHeights.length
        baseWidth = (avgHeight / 1.414) / (pdfScale.value || 1)
      }
    }
    if (baseWidth > 0) return availableWidth / baseWidth
    return null
  }

  function applyFitToWindowScale() {
    const nextScale = getFitToWindowScale()
    if (nextScale === null) { isScaleTransitioning.value = false; return }
    const safeScale = clampScale(nextScale)
    if (Math.abs(safeScale - pdfScale.value) >= 0.001) {
      applyPdfScale(safeScale)
    } else {
      isScaleTransitioning.value = false
    }
    requestAnimationFrame(() => { hasAppliedInitialFit.value = true })
  }

  function scheduleFitToWindowScale() {
    if (!isFitToWindowMode.value) return
    if (fitScaleRafId !== null) return
    fitScaleRafId = requestAnimationFrame(() => {
      fitScaleRafId = null
      applyFitToWindowScale()
    })
  }

  function applyPdfScale(nextScale: number) {
    const safeScale = clampScale(nextScale)
    if (Math.abs(safeScale - pdfScale.value) < 0.005) { isScaleTransitioning.value = false; return }
    const oldScale = pdfScale.value
    const scaleRatio = safeScale / oldScale

    const scaledPageHeights: Record<number, number> = {}
    for (const [page, height] of Object.entries(scroll.pageHeights)) {
      scaledPageHeights[Number(page)] = Math.max(MIN_PAGE_HEIGHT, Math.round(height * scaleRatio))
    }
    for (const key of Object.keys(scroll.pageHeights)) delete scroll.pageHeights[Number(key)]
    scroll.invalidateLayout()
    for (const [k, v] of Object.entries(scaledPageHeights)) scroll.pageHeights[Number(k)] = v

    const scaledMetrics: Record<number, RenderedPageMetrics> = {}
    for (const [page, metric] of Object.entries(renderedPageMetrics)) {
      scaledMetrics[Number(page)] = {
        ...metric,
        top: metric.top * scaleRatio, left: metric.left * scaleRatio,
        width: metric.width * scaleRatio, height: metric.height * scaleRatio,
        scale: safeScale,
      }
    }
    for (const key of Object.keys(renderedPageMetrics)) delete renderedPageMetrics[Number(key)]
    for (const [k, v] of Object.entries(scaledMetrics)) renderedPageMetrics[Number(k)] = v

    maxPageWidth.value = maxPageWidth.value * scaleRatio

    if (intrinsicPdfPageWidth.value) {
      const aspectRatio = scroll.estimatedPageHeight.value / (intrinsicPdfPageWidth.value * oldScale) || 1.414
      scroll.estimatedPageHeight.value = Math.round(intrinsicPdfPageWidth.value * safeScale * aspectRatio)
    }

    isScaleTransitioning.value = true
    pdfScale.value = safeScale
    nextTick(() => {
      scroll.scheduleRenderedPageRangeUpdate()
      if (!isFitToWindowMode.value) scroll.scrollToPdfPage(scroll.activePdfPage.value, 'auto')
      requestAnimationFrame(() => requestAnimationFrame(() => { isScaleTransitioning.value = false }))
    })
  }

  function watchIntrinsicWidth() {
    watch(intrinsicPdfPageWidth, (val) => {
      if (val && isFitToWindowMode.value) scheduleFitToWindowScale()
    })
  }

  function watchFitMode() {
    watch(isFitToWindowMode, (val) => {
      if (val) { hasAppliedInitialFit.value = false; scheduleFitToWindowScale() }
    })
  }

  function zoomIn() { isFitToWindowMode.value = false; applyPdfScale(pdfScale.value + SCALE_STEP) }
  function zoomOut() { isFitToWindowMode.value = false; applyPdfScale(pdfScale.value - SCALE_STEP) }
  function resetZoom() { isFitToWindowMode.value = true; hasAppliedInitialFit.value = false; scheduleFitToWindowScale() }

  return {
    pdfScale, isFitToWindowMode, isScaleTransitioning, hasAppliedInitialFit,
    intrinsicPdfPageWidth, maxPageWidth, zoomPercentLabel, normalizedPdfSource,
    nativePdfViewerUrl, clampScale, applyPdfScale, scheduleFitToWindowScale,
    zoomIn, zoomOut, resetZoom, watchIntrinsicWidth, watchFitMode, clampPage,
  }
}

// --- Composable: usePdfMeasurement ---
function usePdfMeasurement(
  scroll: {
    pageHeights: Record<number, number>
    estimatedPageHeight: Ref<number>
    scheduleRenderedPageRangeUpdate: () => void
    invalidateLayout: () => void
  },
  zoom: {
    pdfScale: Ref<number>
    isFitToWindowMode: Ref<boolean>
    hasAppliedInitialFit: Ref<boolean>
    maxPageWidth: Ref<number>
    scheduleFitToWindowScale: () => void
    intrinsicPdfPageWidth: Ref<number | null>
    isScaleTransitioning: Ref<boolean>
  },
  pageLastRenderedScale: Map<number, number>,
  renderedPageMetrics: Record<number, RenderedPageMetrics>,
) {
  const pageElements = new Map<number, HTMLElement>()
  const pageResizeObservers = new Map<number, ResizeObserver>()

  function updateMaxPageWidth() {
    let max = 0
    for (const key in renderedPageMetrics) {
      const w = renderedPageMetrics[key]?.width || 0
      if (w > max) max = w
    }
    zoom.maxPageWidth.value = max
  }

  function updateEstimatedHeight() {
    const values = Object.values(scroll.pageHeights).filter(h => h > 0)
    if (!values.length) return
    const total = values.reduce((s, i) => s + i, 0)
    scroll.estimatedPageHeight.value = Math.max(MIN_PAGE_HEIGHT, Math.min(6000, Math.round(total / values.length)))
  }

  function clearAllPageData() {
    console.log('[PDFViewer] Clearing all page data for document switch/unmount')
    pageResizeObservers.forEach(o => o.disconnect())
    pageResizeObservers.clear()
    pageElements.clear()
    for (const key of Object.keys(scroll.pageHeights)) delete scroll.pageHeights[Number(key)]
    scroll.invalidateLayout()
    for (const key of Object.keys(renderedPageMetrics)) delete renderedPageMetrics[Number(key)]
    zoom.maxPageWidth.value = 0
    zoom.hasAppliedInitialFit.value = false
    zoom.isScaleTransitioning.value = false
    zoom.intrinsicPdfPageWidth.value = null
    zoom.pdfScale.value = 1
  }

  function measurePageElement(page: number) {
    const element = pageElements.get(page)
    if (!element) return
    const mediaElement = element.querySelector('canvas')
    if (!(mediaElement instanceof HTMLElement)) return
    if (mediaElement instanceof HTMLCanvasElement) {
      const renderedScale = pageLastRenderedScale.get(page)
      const hasRenderedAtCurrentScale = renderedScale !== undefined && Math.abs(renderedScale - zoom.pdfScale.value) < 0.001
      const hasCanvasSize = mediaElement.width > 0 && mediaElement.height > 0
      if (!hasRenderedAtCurrentScale || !hasCanvasSize) return
    }
    const mediaRect = mediaElement.getBoundingClientRect()
    const wrapperRect = element.getBoundingClientRect()
    if (mediaRect.width <= 1 || mediaRect.height <= 1) return
    const nextHeight = Math.max(MIN_PAGE_HEIGHT, Math.round(mediaRect.height + 12))
    const nextMetrics: RenderedPageMetrics = {
      top: Math.max(0, mediaRect.top - wrapperRect.top),
      left: Math.max(0, mediaRect.left - wrapperRect.left),
      width: Math.max(1, mediaRect.width),
      height: Math.round(mediaRect.height),
      scale: zoom.pdfScale.value,
    }
    const currentHeight = scroll.pageHeights[page]
    const currentMetrics = renderedPageMetrics[page]
    const metricsChanged = !currentMetrics ||
      Math.abs(currentMetrics.scale - nextMetrics.scale) > 0.001 ||
      ['top', 'left', 'width', 'height'].some(k => Math.abs((currentMetrics as any)[k] - (nextMetrics as any)[k]) > 0.5)
    if (currentHeight !== nextHeight) {
      scroll.invalidateLayout()
      scroll.pageHeights[page] = nextHeight
      updateEstimatedHeight()
      scroll.scheduleRenderedPageRangeUpdate()
    }
    if (metricsChanged) {
      renderedPageMetrics[page] = nextMetrics
      updateMaxPageWidth()
      if (zoom.isFitToWindowMode.value && !zoom.hasAppliedInitialFit.value) {
        zoom.scheduleFitToWindowScale()
      }
    }
  }

  function setPdfPageElement(page: number, el: unknown) {
    const element = el instanceof HTMLElement ? el : (el && typeof el === 'object' && '$el' in (el as any) ? (el as any).$el : null)
    const previous = pageElements.get(page)
    if (previous && previous !== element) {
      pageResizeObservers.get(page)?.disconnect()
      pageResizeObservers.delete(page)
      pageElements.delete(page)
    }
    if (!(element instanceof HTMLElement)) return
    pageElements.set(page, element)
    const measureHeight = () => measurePageElement(page)
    measureHeight()
    requestAnimationFrame(measureHeight)
    if (typeof ResizeObserver !== 'undefined' && !pageResizeObservers.has(page)) {
      const observer = new ResizeObserver(() => measureHeight())
      observer.observe(element)
      pageResizeObservers.set(page, observer)
    }
  }

  return { measurePageElement, setPdfPageElement, clearAllPageData }
}

// --- Composable: usePdfRendering ---
function usePdfRendering(
  pdfDocumentRef: Ref<any>,
  zoom: {
    pdfScale: Ref<number>
    intrinsicPdfPageWidth: Ref<number | null>
    isFitToWindowMode: Ref<boolean>
    hasAppliedInitialFit: Ref<boolean>
    scheduleFitToWindowScale: () => void
  },
  scroll: {
    renderedPageRange: { start: number; end: number }
    scheduleRenderedPageRangeUpdate: () => void
  },
  measurement: {
    measurePageElement: (page: number) => void
  },
  pageLastRenderedScale: Map<number, number>,
) {
  const pageCanvasElements = new Map<number, HTMLCanvasElement>()
  const pageRenderTasks = new Map<number, { cancel: () => void; promise: Promise<any> }>()
  const pageRenderRafIds = new Map<number, number>()
  const pageRenderFailCount = new Map<number, number>()

  function cancelPageRenderTask(page: number) {
    const task = pageRenderTasks.get(page)
    task?.cancel()
    pageRenderTasks.delete(page)
  }

  function isRenderCancelledError(error: unknown) {
    if (!error || typeof error !== 'object') return false
    return (error as { name?: string }).name === 'RenderingCancelledException'
  }

  function scheduleRenderPage(page: number) {
    const previousRafId = pageRenderRafIds.get(page)
    if (previousRafId !== undefined) cancelAnimationFrame(previousRafId)
    const rafId = requestAnimationFrame(() => {
      pageRenderRafIds.delete(page)
      void renderPageToCanvas(page)
    })
    pageRenderRafIds.set(page, rafId)
  }

  function renderVisiblePages() {
    if (!props.isPdf || !pdfDocumentRef.value) return
    const start = scroll.renderedPageRange.start
    const end = scroll.renderedPageRange.end
    for (let page = start; page <= end; page += 1) scheduleRenderPage(page)
  }

  function setPdfCanvasElement(page: number, element: unknown) {
    const canvas = element instanceof HTMLCanvasElement ? element : null
    const previousCanvas = pageCanvasElements.get(page)
    if (previousCanvas && previousCanvas !== canvas) {
      previousCanvas.width = 0
      previousCanvas.height = 0
      pageCanvasElements.delete(page)
      cancelPageRenderTask(page)
      pageLastRenderedScale.delete(page)
    }
    if (!canvas) return
    pageCanvasElements.set(page, canvas)
    if (props.isPdf) scheduleRenderPage(page)
  }

  function clearPdfRenderState() {
    pageRenderRafIds.forEach(id => cancelAnimationFrame(id))
    pageRenderRafIds.clear()
    pageRenderTasks.forEach(t => t.cancel())
    pageRenderTasks.clear()
    pageCanvasElements.clear()
    pageLastRenderedScale.clear()
    pageRenderFailCount.clear()
  }

  async function renderPageToCanvas(page: number) {
    if (!props.isPdf) return
    const doc = pdfDocumentRef.value
    const canvas = pageCanvasElements.get(page)
    if (!doc || !canvas) return
    const lastRenderedScale = pageLastRenderedScale.get(page)
    const isScaleChanged = lastRenderedScale !== zoom.pdfScale.value
    const canvasOk = canvas.width > 0 && canvas.height > 0
    if (pageRenderTasks.has(page)) {
      if (!isScaleChanged) return
      const oldTask = pageRenderTasks.get(page)
      oldTask?.cancel()
      try { await oldTask?.promise } catch (e) {}
      pageRenderTasks.delete(page)
    } else {
      if (!isScaleChanged && canvasOk) return
    }
    try {
      let isCancelled = false
      const taskPlaceholder = { cancel: () => { isCancelled = true }, promise: Promise.resolve() }
      pageRenderTasks.set(page, taskPlaceholder as any)
      const pdfPage = await doc.getPage(page)
      if (isCancelled || !pdfDocumentRef.value || pdfDocumentRef.value !== doc) return
      const outputScale = window.devicePixelRatio || 1
      const logicalViewport = pdfPage.getViewport({ scale: zoom.pdfScale.value })
      const cssWidth = Math.max(1, logicalViewport.width)
      const cssHeight = Math.max(1, logicalViewport.height)
      const effectiveScale = Math.min(zoom.pdfScale.value * outputScale, MAX_PIXEL_SCALE)
      const viewport = pdfPage.getViewport({ scale: effectiveScale })
      const targetWidth = Math.max(1, Math.floor(viewport.width))
      const targetHeight = Math.max(1, Math.floor(viewport.height))
      const isSizeChanged = canvas.width !== targetWidth || canvas.height !== targetHeight
      if (isSizeChanged) { canvas.width = targetWidth; canvas.height = targetHeight }
      canvas.style.width = `${cssWidth}px`
      canvas.style.height = `${cssHeight}px`
      const canvasContext = canvas.getContext('2d', { alpha: false })
      if (!canvasContext) return
      canvasContext.setTransform(1, 0, 0, 1, 0, 0)
      canvasContext.fillStyle = '#ffffff'
      canvasContext.fillRect(0, 0, targetWidth, targetHeight)
      const renderTask = pdfPage.render({ canvasContext, viewport: viewport, intent: 'print' })
      pageRenderTasks.set(page, renderTask)
      await renderTask.promise
      if (pageRenderTasks.get(page) === renderTask) {
        pageRenderTasks.delete(page)
        pageLastRenderedScale.set(page, zoom.pdfScale.value)
      }
      requestAnimationFrame(() => measurement.measurePageElement(page))
      const baseWidth = cssWidth / zoom.pdfScale.value
      if (!zoom.intrinsicPdfPageWidth.value && baseWidth > 0) {
        zoom.intrinsicPdfPageWidth.value = baseWidth
        if (zoom.isFitToWindowMode.value) zoom.scheduleFitToWindowScale()
      }
      scroll.scheduleRenderedPageRangeUpdate()
      if (zoom.isFitToWindowMode.value && !zoom.hasAppliedInitialFit.value) {
        zoom.scheduleFitToWindowScale()
      }
    } catch (error) {
      cancelPageRenderTask(page)
      if (isRenderCancelledError(error)) return
      const failCount = (pageRenderFailCount.get(page) || 0) + 1
      pageRenderFailCount.set(page, failCount)
      console.warn(`[PDFViewer] Failed to render page ${page} (attempt ${failCount}):`, error)
      if (error && typeof error === 'object' && (error as any).name === 'PasswordException') {
        return
      }
      if (failCount < 3) {
        setTimeout(() => {
          if (pageCanvasElements.has(page)) scheduleRenderPage(page)
        }, 200 * failCount)
      }
    }
  }

  return { renderVisiblePages, renderPageToCanvas, setPdfCanvasElement, clearPdfRenderState }
}

// --- Composable: usePdfDocument ---
function usePdfDocument(
  shared: {
    pdfDocumentRef: Ref<any>
    localPdfPageCount: Ref<number>
    useNativePdfPreview: Ref<boolean>
    isPdfLoading: Ref<boolean>
    pdfLoadingProgress: Ref<number>
  },
  scroll: {
    scheduleRenderedPageRangeUpdate: () => void
    displayPdfPageCount: ComputedRef<number>
    estimatedPageHeight: Ref<number>
  },
  zoom: {
    clampScale: (v: number) => number
    scheduleFitToWindowScale: () => void
    pdfScale: Ref<number>
    isScaleTransitioning: Ref<boolean>
    hasAppliedInitialFit: Ref<boolean>
    intrinsicPdfPageWidth: Ref<number | null>
  },
  render: {
    renderVisiblePages: () => void
    clearPdfRenderState: () => void
  },
) {
  const useNativePdfPreview = shared.useNativePdfPreview
  const isPdfLoading = shared.isPdfLoading
  const pdfLoadingProgress = shared.pdfLoadingProgress
  const localPdfPageCount = shared.localPdfPageCount
  const pdfDocument = shared.pdfDocumentRef
  const pdfLoadingTask = shallowRef<any>(null)
  let pdfLoadToken = 0

  function destroyPdfLoadingTask() {
    pdfLoadingTask.value?.destroy?.()
    pdfLoadingTask.value = null
  }

  function destroyPdfDocument() {
    pdfDocument.value?.destroy?.()
    pdfDocument.value = null
  }

  async function onPdfDocumentLoaded(nextDocument: any) {
    useNativePdfPreview.value = false
    isPdfLoading.value = false
    pdfLoadingProgress.value = 100
    pdfDocument.value = nextDocument
    localPdfPageCount.value = Number(nextDocument?.numPages || 0)
    if (localPdfPageCount.value > 0) {
      try {
        const firstPage = await nextDocument.getPage(1)
        const viewport = firstPage.getViewport({ scale: 1 })
        if (viewport.width > 0 && viewport.height > 0) {
          zoom.intrinsicPdfPageWidth.value = viewport.width
          if (pdfScrollRef.value) {
            const containerWidth = pdfScrollRef.value.clientWidth
            if (containerWidth > FIT_PADDING * 2) {
              const fitScale = (containerWidth - FIT_PADDING * 2) / viewport.width
              zoom.pdfScale.value = zoom.clampScale(fitScale)
              scroll.estimatedPageHeight.value = Math.round(viewport.height * zoom.pdfScale.value)
            }
          }
        }
      } catch (e) {
        console.warn('[PDFViewer] Failed to pre-fetch first page dimensions:', e)
      }
    }
    scroll.scheduleRenderedPageRangeUpdate()
    await nextTick()
    render.renderVisiblePages()
    requestAnimationFrame(() => {
      zoom.scheduleFitToWindowScale()
      zoom.isScaleTransitioning.value = false
      zoom.hasAppliedInitialFit.value = true
    })
  }

  async function loadPdfDocument(source: string) {
    if (!source || !props.isPdf) return
    useNativePdfPreview.value = false
    isPdfLoading.value = true
    pdfLoadingProgress.value = 0
    const nextToken = pdfLoadToken + 1
    pdfLoadToken = nextToken
    destroyPdfLoadingTask()
    destroyPdfDocument()
    render.clearPdfRenderState()

    try {
      const loadingTask = pdfjsLib.getDocument({
        url: source, credentials: 'same-origin',
        disableRange: false, disableStream: false, disableAutoFetch: false,
        rangeChunkSize: 65536 * 8,
      }) as unknown as { promise: Promise<any>; destroy?: () => void }

      loadingTask.onProgress = ({ loaded, total }: { loaded: number; total: number }) => {
        if (total > 0) pdfLoadingProgress.value = Math.min(99, Math.round((loaded / total) * 100))
      }

      pdfLoadingTask.value = loadingTask
      const nextDocument = await loadingTask.promise
      if (pdfLoadToken !== nextToken) { nextDocument?.destroy?.(); return }
      await onPdfDocumentLoaded(nextDocument)
      return
    } catch (error) {
      console.warn('[PDFViewer] Stream load failed, trying full array buffer load:', error)
      if (pdfLoadToken !== nextToken) return
      destroyPdfLoadingTask()
      destroyPdfDocument()
    }

    try {
      const response = await fetch(source, { credentials: 'same-origin' })
      if (!response.ok) throw new Error(`Failed to fetch PDF (${response.status})`)
      const pdfBinary = new Uint8Array(await response.arrayBuffer())
      if (pdfLoadToken !== nextToken) return
      const loadingTask = pdfjsLib.getDocument({
        data: pdfBinary, disableRange: true, disableStream: true, disableAutoFetch: true
      })
      pdfLoadingTask.value = loadingTask
      const nextDocument = await loadingTask.promise
      if (pdfLoadToken !== nextToken) { nextDocument?.destroy?.(); return }
      await onPdfDocumentLoaded(nextDocument)
      return
    } catch (error) {
      console.error('[PDFViewer] PDF load failed after all attempts:', error)
    }

    if (pdfLoadToken !== nextToken) return
    useNativePdfPreview.value = true
    isPdfLoading.value = false
    pdfDocument.value = null
    localPdfPageCount.value = 0
  }

  function onBeforeUnmount() {
    pdfLoadToken += 1
    destroyPdfLoadingTask()
    destroyPdfDocument()
  }

  return { useNativePdfPreview, isPdfLoading, pdfLoadingProgress, localPdfPageCount, pdfDocument, loadPdfDocument, destroyPdfLoadingTask, destroyPdfDocument, onBeforeUnmount }
}

// --- 组合 Composable 函数 ---
const _pageLastRenderedScale = new Map<number, number>()
const _localPdfPageCount = ref(0)
const _useNativePdfPreview = ref(false)
const _pdfDocumentRef = shallowRef<any>(null)
const _renderedPageMetrics = reactive<Record<number, RenderedPageMetrics>>({})

const header = usePdfHeader()
const scroll = usePdfVirtualScroll(emit, () => _localPdfPageCount.value)
const zoom = usePdfZoom(scroll, _renderedPageMetrics)
const measurement = usePdfMeasurement(scroll, zoom, _pageLastRenderedScale, _renderedPageMetrics)
const render = usePdfRendering(_pdfDocumentRef, zoom, scroll, measurement, _pageLastRenderedScale)
const doc = usePdfDocument(
  { pdfDocumentRef: _pdfDocumentRef, localPdfPageCount: _localPdfPageCount, useNativePdfPreview: _useNativePdfPreview, isPdfLoading: ref(false), pdfLoadingProgress: ref(0) },
  scroll, zoom, render,
)

const zoomPercentLabel = zoom.zoomPercentLabel
const normalizedPdfSource = zoom.normalizedPdfSource
const nativePdfViewerUrl = zoom.nativePdfViewerUrl
const isPdfLoading = doc.isPdfLoading
const pdfLoadingProgress = doc.pdfLoadingProgress
const maxPageWidth = zoom.maxPageWidth
const hasAppliedInitialFit = zoom.hasAppliedInitialFit
const isScaleTransitioning = zoom.isScaleTransitioning
const activePdfPage = scroll.activePdfPage
const compactLevel = header.compactLevel
const displayPdfPageCount = scroll.displayPdfPageCount
const isFitToWindowMode = zoom.isFitToWindowMode
const useNativePdfPreview = doc.useNativePdfPreview
const virtualContentHeight = scroll.virtualContentHeight
const minPdfScale = MIN_SCALE
const maxPdfScale = MAX_SCALE
const pdfScale = zoom.pdfScale

const themeClass = computed(() => {
  if (props.theme === 'dark') return 'dark-mode'
  if (props.theme === 'light') return 'light-mode'
  return ''
})

const shouldShowPdfHighlights = computed(() => {
  if (!props.isPdf || doc.useNativePdfPreview.value) return false
  if (zoom.isScaleTransitioning.value) return false
  return true
})

const showNonPdfLoading = computed(() => {
  if (props.isPdf) return false
  const status = props.node.status
  return status === 'processing' || status === 'pending' || status === 'queued'
})

const parseStepIndex = computed(() => {
  const stage = (props.node.parseStage || '').toLowerCase()
  const order: Record<string, number> = {
    preparing: 0, converting: 1, raw_parse: 2, popo_normalize: 3, indexing: 4, completed: 5,
  }
  return order[stage] !== undefined ? order[stage] : 0
})

void [pdfToolbarRef, headerTitleRef, headerMainRef, isPdfLoading, pdfLoadingProgress, zoomPercentLabel, normalizedPdfSource, nativePdfViewerUrl, shouldShowPdfHighlights, showNonPdfLoading, parseStepIndex, hasAppliedInitialFit, isScaleTransitioning, maxPageWidth, activePdfPage, compactLevel, displayPdfPageCount, virtualContentHeight, minPdfScale, maxPdfScale, pdfScale, isFitToWindowMode, useNativePdfPreview]

const visiblePdfPages = computed<VirtualPageMeta[]>(() => {
  const pages: VirtualPageMeta[] = []
  const { start, end } = scroll.renderedPageRange
  const layout = scroll.pageLayout.value
  for (let page = start; page <= end; page += 1) {
    pages.push({ page, top: layout.topByPage[page] || 24, height: scroll.pageHeightOf(page) })
  }
  return pages
})

const getPdfPageStyle = (pageMeta: VirtualPageMeta) => ({ top: `${pageMeta.top}px` })
const getHighlightLayerStyle = (page: number) => {
  const m = _renderedPageMetrics[page]
  return m ? { top: `${m.top}px`, left: `${m.left}px`, width: `${m.width}px`, height: `${m.height}px` } : { inset: '0' }
}
const getHighlightTypeLabel = (type?: string) => {
  const normalizedType = String(type || '').trim().toLowerCase()
  if (!normalizedType) return ''
  const labelMap: Record<string, string> = {
    image: '图片', 'image-caption': '图片题注', 'image-footnote': '图片脚注',
    table: '表格', 'table-caption': '表题', 'table-footnote': '表注',
    title: '标题', paragraph: '正文', list: '列表',
    equation_interline: '公式', text: '文本'
  }
  return labelMap[normalizedType] || normalizedType.replace(/[_-]+/g, ' ').trim()
}
const highlightsByPage = computed(() => {
  if (!props.isPdf || !props.highlightLinkEnabled) return new Map<number, LinkedHighlight[]>()
  const map = new Map<number, LinkedHighlight[]>()
  for (const h of props.highlights) {
    if (h.hasRect === false) continue
    let list = map.get(h.page)
    if (!list) { list = []; map.set(h.page, list) }
    list.push(h)
  }
  for (const [, list] of map) {
    list.sort((left, right) => ((right.width || 0) * (right.height || 0)) - ((left.width || 0) * (left.height || 0)))
  }
  return map
})
const getPageHighlights = (page: number) => {
  if (!props.isPdf || !props.highlightLinkEnabled) return []
  if (!_renderedPageMetrics[page]) return []
  return highlightsByPage.value.get(page) || []
}

// --- Watchers ---
watch([normalizedPdfSource, () => props.isPdf], async ([source, isPdf]) => {
  if (!isPdf || !source) return
  measurement.clearAllPageData()
  zoom.intrinsicPdfPageWidth.value = null
  zoom.pdfScale.value = 1
  zoom.isFitToWindowMode.value = true
  zoom.isScaleTransitioning.value = true
  zoom.hasAppliedInitialFit.value = false
  scroll.activePdfPage.value = 1
  scroll.estimatedPageHeight.value = 1100
  scroll.renderedPageRange.start = 1
  scroll.renderedPageRange.end = 1
  scroll.lastEmittedPdfPercent.value = -1
  doc.useNativePdfPreview.value = false
  await nextTick()
  if (pdfScrollRef.value) pdfScrollRef.value.scrollTop = 0
  scroll.scheduleRenderedPageRangeUpdate()
  await doc.loadPdfDocument(source)
}, { immediate: true })

watch([() => scroll.renderedPageRange.start, () => scroll.renderedPageRange.end, zoom.pdfScale, () => props.isPdf], async () => {
  if (!doc.useNativePdfPreview.value && props.isPdf) {
    await nextTick()
    render.renderVisiblePages()
  }
})

watch(() => props.currentPdfPage, (newPage) => {
  if (!props.isPdf || newPage <= 0) return
  scroll.applyingExternalPdfScroll.value = true
  scroll.scrollToPdfPage(newPage, 'auto')
  requestAnimationFrame(() => { scroll.applyingExternalPdfScroll.value = false })
})

watch(() => props.textScrollPercent, (percent) => {
  if (pdfScrollRef.value && props.isPdf && !scroll.isPdfUserScrolling.value && !doc.useNativePdfPreview.value) {
    scroll.applyingExternalPdfScroll.value = true
    const max = pdfScrollRef.value.scrollHeight - pdfScrollRef.value.clientHeight
    pdfScrollRef.value.scrollTop = percent * max
    requestAnimationFrame(() => { scroll.applyingExternalPdfScroll.value = false })
  }
  if (leftTextRef.value && props.isText) {
    const max = leftTextRef.value.scrollHeight - leftTextRef.value.clientHeight
    leftTextRef.value.scrollTop = percent * max
  }
})

// --- 暴露方法给模�?---
const goPrevPage = () => scroll.goPrevPage()
const goNextPage = () => scroll.goNextPage()
const onPageInputChange = (v: any) => scroll.onPageInputChange(v)
const zoomIn = () => zoom.zoomIn()
const zoomOut = () => zoom.zoomOut()
const resetZoom = () => zoom.resetZoom()
const onPdfScroll = (e: Event) => {
  if (!doc.useNativePdfPreview.value) {
    scroll.onPdfScroll(e)
    emit('pdf-active-page', scroll.activePdfPage.value)
  }
}
const setPdfCanvasElement = (p: number, el: any) => render.setPdfCanvasElement(p, el)
const setPdfPageElement = (p: number, el: any) => measurement.setPdfPageElement(p, el)
const onLeftTextScroll = () => {
  if (leftTextRef.value) {
    const maxScroll = leftTextRef.value.scrollHeight - leftTextRef.value.clientHeight
    emit('text-scroll', maxScroll > 0 ? leftTextRef.value.scrollTop / maxScroll : 0)
  }
}

onMounted(() => {
  header.setup()
  zoom.watchIntrinsicWidth()
  zoom.watchFitMode()
  nextTick(() => {
    scroll.scheduleRenderedPageRangeUpdate()
    if (zoom.isFitToWindowMode.value) zoom.scheduleFitToWindowScale()
  })
})

onBeforeUnmount(() => {
  doc.onBeforeUnmount()
  header.teardown()
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
  /* Light mode defaults �?宿主可通过 --dp-*-override 覆盖 */
  --dp-bg: var(--dp-bg-override, #f3f5f8);
  --dp-pane-bg: var(--dp-pane-bg-override, #fff);
  --dp-pane-border: var(--dp-pane-border-override, #e8edf4);
  --dp-title-bg: var(--dp-title-bg-override, #fff);
  --dp-title-border: var(--dp-title-border-override, #edf1f7);
  --dp-title-text: var(--dp-title-text-override, #595959);
  --dp-title-strong: var(--dp-title-strong-override, #4f5d7a);
  --dp-sub-text: var(--dp-sub-text-override, #8c8c8c);
  --dp-progress-bg: var(--dp-progress-bg-override, #f7f9fc);
  --dp-content-bg: var(--dp-content-bg-override, #fff);
  --dp-scroll-thumb: var(--dp-scroll-thumb-override, rgba(15,23,42,0.22));
  --dp-empty-overlay: var(--dp-empty-overlay-override, rgba(255,255,255,0.92));
  --dp-empty-text: var(--dp-empty-text-override, rgba(0,0,0,0.45));
  --dp-segment-bg: var(--dp-segment-bg-override, #dfe5f2);
  --dp-segment-border: var(--dp-segment-border-override, #cdd6e7);
  --dp-segment-selected-bg: var(--dp-segment-selected-bg-override, #fff);
  --dp-segment-selected-text: var(--dp-segment-selected-text-override, #1f2937);
  --dp-math-bg: var(--dp-math-bg-override, #eef3ff);
  --dp-math-color: var(--dp-math-color-override, #1d3a8a);
  --dp-bg-tertiary: var(--dp-bg-tertiary-override, #eef1f5);
}

.pane-title {
  font-size: 13px;
  color: var(--dp-title-text);
  padding: 0 12px;
  border-bottom: 1px solid var(--dp-title-border);
  background: var(--dp-title-bg);
  height: 40px;
  min-height: 40px;
  box-sizing: border-box;
}

.pane-title-with-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  position: relative;
  overflow: hidden;
}

.pane-title-main {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  flex: 1 1 auto;
}

.pane-title-right-placeholder {
  flex: 1 1 0;
  min-width: 0;
}

.pane-title-prefix-wrap {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.pane-title-prefix {
  font-size: 13px;
  font-weight: 500;
  color: var(--dp-title-strong);
  white-space: nowrap;
}

.parse-state-tag {
  margin-inline-start: 2px;
}

.pane-actions-pdf {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  position: relative;
  z-index: 1;
  flex: 0 0 auto;
  margin-left: auto;
  margin-right: auto;
}

.pane-actions-pdf-compact {
  gap: 3px;
  margin-left: 0;
  margin-right: 0;
}

.parse-progress-row {
  padding: 5px 12px;
  border-bottom: 1px solid var(--dp-title-border);
  background: var(--dp-progress-bg);
}

.parse-progress-content {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.parse-steps {
  :deep(.ant-steps-item) {
    flex: 1;
  }
  :deep(.ant-steps-item-container) {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 5px 0;
    position: relative;
  }
  :deep(.ant-steps-item-icon) {
    width: 20px;
    height: 20px;
    line-height: 20px;
    font-size: 10px;
    margin: 0;
    order: 2;
  }
  :deep(.ant-steps-item-content) {
    min-height: 0;
    order: 1;
    margin-bottom: 2px;
  }
  :deep(.ant-steps-item-title) {
    font-size: 10px;
    line-height: 1.2;
  }
  :deep(.ant-steps-item-tail) {
    top: 15px !important;
    padding: 0 6px;
  }
}

.progress-text-info {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.progress-text {
  font-size: 10px;
  color: var(--dp-sub-text);
}

.progress-percentage {
  font-size: 10px;
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

.pdf-preview-wrap {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  position: relative;
}

.pdf-loading-overlay {
  position: absolute;
  inset: 0;
  z-index: 50;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(2px);
}

.pdf-loading-text {
  font-size: 14px;
  color: var(--text-secondary, #666);
}

.pdf-loading-progress {
  width: 240px;
  max-width: 80%;
}

.pdf-tool-btn {
  min-width: 24px;
  height: 22px;
  padding-inline: 4px;
}

.pdf-page-input {
  width: 56px;
}

.pdf-toolbar-text {
  font-size: 14px;
  color: var(--dp-title-text);
  min-width: 34px;
  text-align: center;
}

.office-frame-wrap {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.office-viewer {
  width: 100%;
  height: 100%;
  min-height: 0;
  border: none;
  background: var(--dp-content-bg);
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
  max-width: calc(100% - 4px);
  padding: 2px 6px;
  overflow: hidden;
  color: #fff;
  font-size: 10px;
  line-height: 1.2;
  text-overflow: ellipsis;
  white-space: nowrap;
  background: rgba(22, 119, 255, 0.92);
  border-bottom-right-radius: 4px;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.18s ease;
  z-index: 11;
}

.pdf-highlight-box:hover .highlight-type-tag,
.pdf-highlight-box.active .highlight-type-tag {
  opacity: 1;
}

.pdf-scroll-container {
  flex: 1;
  overflow: auto;
  position: relative;
  background: var(--dp-bg-tertiary);
  display: flex;
  flex-direction: column;
}

.pdf-scroll-container-fit {
  overflow-x: hidden;
}

.pdf-virtual-spacer {
  position: relative;
  width: 100%;
  min-width: min-content; /* 确保虚拟占位符能够撑开容器，支持横向滚�?*/
}

.pdf-page-wrapper {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
  background: white;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  display: flex;
  flex-direction: column;
  align-items: center;
}

.pdf-page-canvas-wrap {
  display: flex;
  justify-content: center;
  align-items: flex-start;
}

.pdf-page-canvas {
  display: block;
}

/* Dark mode �?跟随系统 */
@media (prefers-color-scheme: dark) {
  .split-pane {
    --dp-bg: var(--dp-bg-override, #101319);
    --dp-pane-bg: var(--dp-pane-bg-override, #171b24);
    --dp-pane-border: var(--dp-pane-border-override, #2a3140);
    --dp-title-bg: var(--dp-title-bg-override, #171b24);
    --dp-title-border: var(--dp-title-border-override, #2a3140);
    --dp-title-text: var(--dp-title-text-override, rgba(255,255,255,0.78));
    --dp-title-strong: var(--dp-title-strong-override, rgba(255,255,255,0.92));
    --dp-sub-text: var(--dp-sub-text-override, rgba(255,255,255,0.62));
    --dp-progress-bg: var(--dp-progress-bg-override, #171b24);
    --dp-content-bg: var(--dp-content-bg-override, #171b24);
    --dp-scroll-thumb: var(--dp-scroll-thumb-override, rgba(148,163,184,0.42));
    --dp-empty-overlay: var(--dp-empty-overlay-override, rgba(16,19,25,0.92));
    --dp-empty-text: var(--dp-empty-text-override, rgba(255,255,255,0.6));
    --dp-segment-bg: var(--dp-segment-bg-override, #2a3345);
    --dp-segment-border: var(--dp-segment-border-override, #38445b);
    --dp-segment-selected-bg: var(--dp-segment-selected-bg-override, #3a4660);
    --dp-segment-selected-text: var(--dp-segment-selected-text-override, rgba(255,255,255,0.9));
    --dp-math-bg: var(--dp-math-bg-override, rgba(59,130,246,0.18));
    --dp-math-color: var(--dp-math-color-override, rgba(219,234,254,0.95));
    --dp-bg-tertiary: var(--dp-bg-tertiary-override, #1a1f2e);
  }
}

/* Dark mode �?props.theme='dark' 显式指定 */
.split-pane.dark-mode {
  --dp-bg: var(--dp-bg-override, #101319);
  --dp-pane-bg: var(--dp-pane-bg-override, #171b24);
  --dp-pane-border: var(--dp-pane-border-override, #2a3140);
  --dp-title-bg: var(--dp-title-bg-override, #171b24);
  --dp-title-border: var(--dp-title-border-override, #2a3140);
  --dp-title-text: var(--dp-title-text-override, rgba(255,255,255,0.78));
  --dp-title-strong: var(--dp-title-strong-override, rgba(255,255,255,0.92));
  --dp-sub-text: var(--dp-sub-text-override, rgba(255,255,255,0.62));
  --dp-progress-bg: var(--dp-progress-bg-override, #171b24);
  --dp-content-bg: var(--dp-content-bg-override, #171b24);
  --dp-scroll-thumb: var(--dp-scroll-thumb-override, rgba(148,163,184,0.42));
  --dp-empty-overlay: var(--dp-empty-overlay-override, rgba(16,19,25,0.92));
  --dp-empty-text: var(--dp-empty-text-override, rgba(255,255,255,0.6));
  --dp-segment-bg: var(--dp-segment-bg-override, #2a3345);
  --dp-segment-border: var(--dp-segment-border-override, #38445b);
  --dp-segment-selected-bg: var(--dp-segment-selected-bg-override, #3a4660);
  --dp-segment-selected-text: var(--dp-segment-selected-text-override, rgba(255,255,255,0.9));
  --dp-math-bg: var(--dp-math-bg-override, rgba(59,130,246,0.18));
  --dp-math-color: var(--dp-math-color-override, rgba(219,234,254,0.95));
  --dp-bg-tertiary: var(--dp-bg-tertiary-override, #1a1f2e);
}

/* Light mode �?props.theme='light' 显式指定 */
.split-pane.light-mode {
  --dp-bg: var(--dp-bg-override, #f3f5f8);
  --dp-pane-bg: var(--dp-pane-bg-override, #fff);
  --dp-pane-border: var(--dp-pane-border-override, #e8edf4);
  --dp-title-bg: var(--dp-title-bg-override, #fff);
  --dp-title-border: var(--dp-title-border-override, #edf1f7);
  --dp-title-text: var(--dp-title-text-override, #595959);
  --dp-title-strong: var(--dp-title-strong-override, #4f5d7a);
  --dp-sub-text: var(--dp-sub-text-override, #8c8c8c);
  --dp-progress-bg: var(--dp-progress-bg-override, #f7f9fc);
  --dp-content-bg: var(--dp-content-bg-override, #fff);
  --dp-scroll-thumb: var(--dp-scroll-thumb-override, rgba(15,23,42,0.22));
  --dp-empty-overlay: var(--dp-empty-overlay-override, rgba(255,255,255,0.92));
  --dp-empty-text: var(--dp-empty-text-override, rgba(0,0,0,0.45));
  --dp-segment-bg: var(--dp-segment-bg-override, #dfe5f2);
  --dp-segment-border: var(--dp-segment-border-override, #cdd6e7);
  --dp-segment-selected-bg: var(--dp-segment-selected-bg-override, #fff);
  --dp-segment-selected-text: var(--dp-segment-selected-text-override, #1f2937);
  --dp-math-bg: var(--dp-math-bg-override, #eef3ff);
  --dp-math-color: var(--dp-math-color-override, #1d3a8a);
  --dp-bg-tertiary: var(--dp-bg-tertiary-override, #eef1f5);
}
</style>
