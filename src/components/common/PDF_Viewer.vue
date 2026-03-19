<template>
  <div class="split-pane split-pane-left">
    <div ref="headerTitleRef" class="pane-title pane-title-with-actions">
      <div ref="headerMainRef" class="pane-title-main">
        <div class="pane-title-prefix-wrap">
          <span class="pane-title-prefix">原文</span>
        </div>
        <a-tag v-if="node.status === 'failed'" color="error" class="parse-state-tag">
          解析失败
        </a-tag>
      </div>
      <div
        v-if="isPdf"
        ref="pdfToolbarRef"
        :class="['pane-actions-pdf', 'pane-actions-pdf-center', { 'pane-actions-pdf-compact': isCompactHeader }]"
      >
        <a-button
          size="small"
          class="pdf-tool-btn"
          :disabled="activePdfPage <= 1"
          @click="goPrevPage"
        >
          <template #icon>
            <LeftOutlined />
          </template>
        </a-button>
        <a-input-number
          v-if="!isCompactHeader"
          :value="activePdfPage"
          size="small"
          :min="1"
          :max="displayPdfPageCount"
          class="pdf-page-input"
          @change="onPageInputChange"
        />
        <span v-if="!isCompactHeader" class="pdf-toolbar-text">/ {{ displayPdfPageCount }}</span>
        <a-button
          size="small"
          class="pdf-tool-btn"
          :disabled="activePdfPage >= displayPdfPageCount"
          @click="goNextPage"
        >
          <template #icon>
            <RightOutlined />
          </template>
        </a-button>
        <a-button size="small" class="pdf-tool-btn" :disabled="pdfScale <= minPdfScale" @click="zoomOut">
          <template #icon>
            <ZoomOutOutlined />
          </template>
        </a-button>
        <span v-if="!isCompactHeader" class="pdf-toolbar-text">{{ zoomPercentLabel }}</span>
        <a-button size="small" class="pdf-tool-btn" :disabled="pdfScale >= maxPdfScale" @click="zoomIn">
          <template #icon>
            <ZoomInOutlined />
          </template>
        </a-button>
        <a-button size="small" class="pdf-tool-btn" title="适应" @click="resetZoom">
          <template #icon>
            <CompressOutlined />
          </template>
        </a-button>
      </div>
      <div
        v-if="isPdf"
        ref="pdfToolbarMeasureRef"
        class="pane-actions-pdf pane-actions-pdf-measure"
        aria-hidden="true"
      >
        <a-button size="small" class="pdf-tool-btn" :disabled="activePdfPage <= 1">
          <template #icon>
            <LeftOutlined />
          </template>
        </a-button>
        <a-input-number
          :value="activePdfPage"
          size="small"
          :min="1"
          :max="displayPdfPageCount"
          class="pdf-page-input"
        />
        <span class="pdf-toolbar-text">/ {{ displayPdfPageCount }}</span>
        <a-button size="small" class="pdf-tool-btn" :disabled="activePdfPage >= displayPdfPageCount">
          <template #icon>
            <RightOutlined />
          </template>
        </a-button>
        <a-button size="small" class="pdf-tool-btn" :disabled="pdfScale <= minPdfScale">
          <template #icon>
            <ZoomOutOutlined />
          </template>
        </a-button>
        <span class="pdf-toolbar-text">{{ zoomPercentLabel }}</span>
        <a-button size="small" class="pdf-tool-btn" :disabled="pdfScale >= maxPdfScale">
          <template #icon>
            <ZoomInOutlined />
          </template>
        </a-button>
        <a-button size="small" class="pdf-tool-btn" title="适应">
          <template #icon>
            <CompressOutlined />
          </template>
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
      <div v-if="isPdf" class="pdf-preview-wrap">
        <div class="pdf-scroll-container" ref="pdfScrollRef" @scroll="onPdfScroll">
          <div class="pdf-virtual-spacer" :style="{ height: `${virtualContentHeight}px` }">
            <div
              v-for="pageMeta in visiblePdfPages"
              :key="pageMeta.page"
              class="pdf-page-wrapper"
              :style="getPdfPageStyle(pageMeta)"
              :ref="(el) => setPdfPageElement(pageMeta.page, el)"
            >
              <VuePdfEmbed
                :source="normalizedPdfSource"
                :page="pageMeta.page"
                :scale="pdfScale"
                :key="`pdf-${normalizedPdfSource}-${pageMeta.page}-${pdfScale}`"
                @loaded="pageMeta.page === 1 ? handlePdfLoaded($event) : null"
              />
              <div
                v-show="shouldShowPdfHighlights"
                class="pdf-highlight-layer"
                :key="`hl-layer-${pageMeta.page}-${pdfScale}`"
                :style="getHighlightLayerStyle(pageMeta.page)"
              >
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
import { LeftOutlined, RightOutlined, ZoomInOutlined, ZoomOutOutlined, CompressOutlined } from '@ant-design/icons-vue'
import VuePdfEmbed from 'vue-pdf-embed'

import type { KnowledgeTreeNode } from '../../types/tree'

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
  node: KnowledgeTreeNode
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
  textScrollPercent: number
}>()

const emit = defineEmits<{
  download: []
  'text-scroll': [percent: number]
  'hover-highlight': [id: string | null]
  'select-highlight': [id: string]
}>()

const pdfScrollRef = ref<HTMLElement | null>(null)
const leftTextRef = ref<HTMLElement | null>(null)
const headerTitleRef = ref<HTMLElement | null>(null)
const headerMainRef = ref<HTMLElement | null>(null)
const pdfToolbarRef = ref<HTMLElement | null>(null)
const pdfToolbarMeasureRef = ref<HTMLElement | null>(null)
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
const minPdfScale = 0.5
const maxPdfScale = 2.5
const pdfScaleStep = 0.1
const pdfScale = ref(1)
const activePdfPage = ref(1)
const pdfVerticalPadding = 24
const pdfPageGap = 16
const renderBufferPages = 2
const isCompactHeader = ref(false)
const headerResizeObserver = ref<ResizeObserver | null>(null)
const isFitToWindowMode = ref(true)
const intrinsicPdfPageWidth = ref<number | null>(null)
const hasAppliedInitialFit = ref(false)
const fitScaleRafId = ref<number | null>(null)
const fitScalePadding = 32
const isScaleTransitioning = ref(false)
const normalizedPdfSource = computed(() => props.pdfViewerUrl.split('#')[0] || props.pdfViewerUrl)
const pageHeightOf = (page: number) => pageHeights.value[page] || estimatedPageHeight.value
const onWindowResize = () => {
  scheduleRenderedPageRangeUpdate()
  scheduleFitToWindowScale()
}
const zoomPercentLabel = computed(() => `${Math.round(pdfScale.value * 100)}%`)
const shouldShowPdfHighlights = computed(() => (
  !props.isPdf
  || !isFitToWindowMode.value
  || hasAppliedInitialFit.value
)
&& !isScaleTransitioning.value)

const updateHeaderCompactMode = () => {
  if (!props.isPdf) {
    isCompactHeader.value = false
    return
  }
  const headerWidth = headerTitleRef.value?.clientWidth || 0
  const titleWidth = headerMainRef.value?.scrollWidth || 0
  const toolbarWidth = Math.max(
    pdfToolbarMeasureRef.value?.scrollWidth || 0,
    pdfToolbarRef.value?.scrollWidth || 0
  )
  if (headerWidth <= 0 || toolbarWidth <= 0) {
    isCompactHeader.value = false
    return
  }
  const requiredWidth = titleWidth + toolbarWidth + 12
  isCompactHeader.value = requiredWidth > headerWidth
}

// Computed page count to use: prefer prop, fallback to local
const displayPdfPageCount = computed(() => {
  if (props.pdfPageCount && props.pdfPageCount > 1) return props.pdfPageCount
  if (localPdfPageCount.value > 1) return localPdfPageCount.value
  return 1
})

const getPageHighlights = (page: number) => {
  if (props.isPdf && isFitToWindowMode.value && !hasAppliedInitialFit.value) return []
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

const clampPage = (value: number) => {
  const total = Math.max(1, displayPdfPageCount.value)
  if (!Number.isFinite(value)) return 1
  return Math.max(1, Math.min(total, Math.round(value)))
}

const clampScale = (value: number) => {
  if (!Number.isFinite(value)) return 1
  return Math.max(minPdfScale, Math.min(maxPdfScale, Number(value.toFixed(2))))
}

const getRenderedPageWidth = (page: number) => {
  const metricsWidth = renderedPageMetrics.value[page]?.width
  if (metricsWidth && Number.isFinite(metricsWidth) && metricsWidth > 0) {
    return metricsWidth
  }
  const pageElement = pageElements.get(page)
  if (!pageElement) return 0
  const mediaElement = pageElement.querySelector('canvas, img') as HTMLElement | null
  if (!mediaElement) return 0
  const { width } = mediaElement.getBoundingClientRect()
  return Number.isFinite(width) && width > 0 ? width : 0
}

const getFitToWindowScale = () => {
  if (!props.isPdf || !pdfScrollRef.value) return null
  const containerWidth = pdfScrollRef.value.clientWidth
  if (!containerWidth || containerWidth <= fitScalePadding) return null

  const candidatePages = [
    activePdfPage.value,
    props.currentPdfPage || 1,
    visiblePdfPages.value[0]?.page || 1,
    1
  ]
  const measuredWidth = candidatePages
    .map(page => getRenderedPageWidth(clampPage(page)))
    .find(width => width > 0) || 0
  const availableWidth = Math.max(1, containerWidth - fitScalePadding)
  if (measuredWidth > 0) {
    return pdfScale.value * (availableWidth / measuredWidth)
  }

  let basePageWidth = intrinsicPdfPageWidth.value || 0
  if (basePageWidth <= 0) {
    for (const page of candidatePages) {
      const renderedWidth = getRenderedPageWidth(clampPage(page))
      if (renderedWidth > 0) {
        basePageWidth = renderedWidth / Math.max(pdfScale.value, minPdfScale)
        intrinsicPdfPageWidth.value = basePageWidth
        break
      }
    }
  }
  if (basePageWidth <= 0) return null

  return availableWidth / basePageWidth
}

const applyFitToWindowScale = () => {
  const nextScale = getFitToWindowScale()
  if (nextScale === null) {
    isScaleTransitioning.value = false
    return
  }
  const safeScale = clampScale(nextScale)
  if (Math.abs(safeScale - pdfScale.value) >= 0.01) {
    applyPdfScale(safeScale)
  } else {
    isScaleTransitioning.value = false
  }
  hasAppliedInitialFit.value = true
}

const scheduleFitToWindowScale = () => {
  if (!isFitToWindowMode.value) return
  if (fitScaleRafId.value !== null) return
  fitScaleRafId.value = requestAnimationFrame(() => {
    fitScaleRafId.value = null
    applyFitToWindowScale()
  })
}

const scrollToPdfPage = (targetPage: number, behavior: ScrollBehavior = 'auto') => {
  if (!props.isPdf || !pdfScrollRef.value) return
  const page = clampPage(targetPage)
  const targetTop = Math.max(0, (pageLayout.value.topByPage[page] || 0) - 8)
  activePdfPage.value = page
  pdfScrollRef.value.scrollTo({ top: targetTop, behavior })
  scheduleRenderedPageRangeUpdate()
}

const applyPdfScale = (nextScale: number) => {
  const safeScale = clampScale(nextScale)
  if (safeScale === pdfScale.value) return
  isScaleTransitioning.value = true
  pdfScale.value = safeScale
  nextTick(() => {
    scheduleRenderedPageRangeUpdate()
    scrollToPdfPage(activePdfPage.value, 'auto')
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        isScaleTransitioning.value = false
      })
    })
  })
}

const zoomIn = () => {
  isFitToWindowMode.value = false
  applyPdfScale(pdfScale.value + pdfScaleStep)
}
const zoomOut = () => {
  isFitToWindowMode.value = false
  applyPdfScale(pdfScale.value - pdfScaleStep)
}
const resetZoom = () => {
  isFitToWindowMode.value = true
  hasAppliedInitialFit.value = false
  scheduleFitToWindowScale()
}
const goPrevPage = () => scrollToPdfPage(activePdfPage.value - 1, 'smooth')
const goNextPage = () => scrollToPdfPage(activePdfPage.value + 1, 'smooth')

const onPageInputChange = (value: string | number | null) => {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return
  scrollToPdfPage(parsed, 'smooth')
}

const resolveViewportPage = (scrollTop: number, clientHeight: number) => {
  const pageCount = Math.max(1, displayPdfPageCount.value)
  const viewportCenter = scrollTop + (clientHeight / 2)
  let bestPage = 1
  let minDistance = Number.POSITIVE_INFINITY
  for (let page = 1; page <= pageCount; page += 1) {
    const top = pageLayout.value.topByPage[page] || 0
    const center = top + (pageHeightOf(page) / 2)
    const distance = Math.abs(center - viewportCenter)
    if (distance < minDistance) {
      minDistance = distance
      bestPage = page
    }
  }
  return bestPage
}

const setPdfPageElement = (page: number, el: unknown) => {
  const vueElement = (
    el && typeof el === 'object' && '$el' in (el as Record<string, unknown>)
      ? (el as { $el?: unknown }).$el
      : null
  )
  const element = el instanceof HTMLElement
    ? el
    : (vueElement instanceof HTMLElement ? vueElement : null)
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
    const nextBaseWidth = nextMetrics.width / Math.max(pdfScale.value, minPdfScale)
    if (Number.isFinite(nextBaseWidth) && nextBaseWidth > 0 && !intrinsicPdfPageWidth.value) {
      intrinsicPdfPageWidth.value = nextBaseWidth
    }

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
      if (isFitToWindowMode.value && !hasAppliedInitialFit.value) {
        scheduleFitToWindowScale()
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
  activePdfPage.value = resolveViewportPage(target.scrollTop, target.clientHeight)
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
  scrollToPdfPage(newPage, 'auto')
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

/**
 * 处理 PDF 加载完成事件
 * 从 VuePdfEmbed 组件获取页数信息，避免重复加载 PDF
 */
const handlePdfLoaded = (pdf: { numPages: number }) => {
  if (pdf && pdf.numPages && pdf.numPages > 0) {
    localPdfPageCount.value = pdf.numPages
  }
}

watch(() => props.pdfViewerUrl, (url) => {
  if (!url || !props.isPdf) return
}, { immediate: true })

watch(
  [() => props.isPdf, () => props.node.status, displayPdfPageCount, zoomPercentLabel],
  () => {
    nextTick(() => {
      updateHeaderCompactMode()
    })
  },
  { immediate: true }
)

watch([() => props.isPdf, displayPdfPageCount], async () => {
  if (!props.isPdf) {
    renderedPageRange.value = { start: 1, end: 1 }
    isScaleTransitioning.value = false
    return
  }
  activePdfPage.value = clampPage(props.currentPdfPage || 1)
  await nextTick()
  scheduleRenderedPageRangeUpdate()
}, { immediate: true })

watch(normalizedPdfSource, async () => {
  pageHeights.value = {}
  renderedPageMetrics.value = {}
  estimatedPageHeight.value = 1100
  renderedPageRange.value = { start: 1, end: 1 }
  lastEmittedPdfPercent.value = -1
  pdfScale.value = 1
  isFitToWindowMode.value = true
  intrinsicPdfPageWidth.value = null
  hasAppliedInitialFit.value = false
  isScaleTransitioning.value = true
  activePdfPage.value = 1
  await nextTick()
  scheduleRenderedPageRangeUpdate()
  scheduleFitToWindowScale()
})

// Legacy scroll handler for text viewer
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

onMounted(() => {
  updateHeaderCompactMode()
  if (typeof ResizeObserver !== 'undefined' && headerTitleRef.value) {
    const observer = new ResizeObserver(() => {
      updateHeaderCompactMode()
    })
    observer.observe(headerTitleRef.value)
    headerResizeObserver.value = observer
  }
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
  if (fitScaleRafId.value !== null) {
    cancelAnimationFrame(fitScaleRafId.value)
  }
  headerResizeObserver.value?.disconnect()
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
  padding: 4px 8px;
  border-bottom: 1px solid var(--dp-title-border);
  background: var(--dp-title-bg);
  min-height: 38px;
  box-sizing: border-box;
}

.pane-title-with-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  position: relative;
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
  gap: 6px;
}

.pane-title-prefix {
  font-size: 13px;
  font-weight: 500;
  color: var(--dp-title-strong);
}

.parse-state-tag {
  margin-inline-start: 2px;
}

.pane-actions-left {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex-wrap: nowrap;
  justify-content: flex-end;
  margin-left: auto;
  position: relative;
  z-index: 1;
}

.pane-actions-pdf {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  position: relative;
  z-index: 1;
}

.pane-actions-pdf-center {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
}

.pane-actions-pdf-measure {
  position: absolute;
  top: -9999px;
  left: -9999px;
  visibility: hidden;
  pointer-events: none;
  transform: none;
  white-space: nowrap;
}

.pane-actions-pdf-compact {
  gap: 3px;
}

.action-btn {
  height: 24px;
  border-radius: 6px;
  font-size: 12px;
  padding-inline: 8px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
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

.pdf-preview-wrap {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
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
  font-size: 11px;
  color: var(--dp-title-text);
  min-width: 34px;
  text-align: center;
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
  overflow: auto;
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
  width: max-content;
  max-width: none;
  background: white;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.pdf-page-wrapper :deep(canvas),
.pdf-page-wrapper :deep(img) {
  display: block;
  width: auto !important;
  max-width: none !important;
  height: auto !important;
}
</style>
