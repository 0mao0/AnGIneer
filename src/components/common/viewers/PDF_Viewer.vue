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
        :class="['pane-actions-pdf', { 'pane-actions-pdf-compact': isCompactHeader }]"
      >
        <template v-if="!useNativePdfPreview">
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
        </template>
      </div>
      <div
        v-if="isPdf"
        ref="pdfToolbarMeasureRef"
        :class="['pane-actions-pdf', 'pane-actions-pdf-measure']"
        aria-hidden="true"
      >
        <a-button size="small" class="pdf-tool-btn">
          <template #icon>
            <LeftOutlined />
          </template>
        </a-button>
        <a-input-number
          :value="activePdfPage"
          size="small"
          class="pdf-page-input"
        />
        <span class="pdf-toolbar-text">/ {{ displayPdfPageCount }}</span>
        <a-button size="small" class="pdf-tool-btn">
          <template #icon>
            <RightOutlined />
          </template>
        </a-button>
        <a-button size="small" class="pdf-tool-btn">
          <template #icon>
            <ZoomOutOutlined />
          </template>
        </a-button>
        <span class="pdf-toolbar-text">{{ zoomPercentLabel }}</span>
        <a-button size="small" class="pdf-tool-btn">
          <template #icon>
            <ZoomInOutlined />
          </template>
        </a-button>
        <a-button size="small" class="pdf-tool-btn">
          <template #icon>
            <CompressOutlined />
          </template>
        </a-button>
      </div>
      <!-- 右侧占位，用于平衡左侧标题，使中间工具栏居中 -->
      <div v-if="isPdf && !useNativePdfPreview && !isCompactHeader" class="pane-title-right-placeholder" />
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
          @scroll="onPdfScroll"
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
import { computed, ref, shallowRef, watch, onMounted, onBeforeUnmount, nextTick, reactive, toRefs } from 'vue'
import { LeftOutlined, RightOutlined, ZoomInOutlined, ZoomOutOutlined, CompressOutlined } from '@ant-design/icons-vue'
import * as pdfjsLib from 'pdfjs-dist'

import type { KnowledgeTreeNode } from '../../../types/tree'

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
  'select-highlight': [highlight: LinkedHighlight]
}>()

/**
 * PDF 查看器控制器类
 * 封装所有 PDF 渲染、缩放、滚动和状态管理逻辑
 */
class PdfViewerController {
  // --- 常量配置 ---
  private readonly MIN_SCALE = 0.5
  private readonly MAX_SCALE = 2.5
  private readonly SCALE_STEP = 0.1
  private readonly VERTICAL_PADDING = 24
  private readonly PAGE_GAP = 16
  private readonly RENDER_BUFFER = 4
  private readonly FIT_PADDING = 12

  // --- 响应式状态 ---
  public state = reactive({
    localPdfPageCount: 0,
    pageHeights: {} as Record<number, number>,
    estimatedPageHeight: 1100,
    renderedPageRange: { start: 1, end: 1 },
    pdfScale: 1,
    activePdfPage: 1,
    isFitToWindowMode: true,
    isScaleTransitioning: false,
    intrinsicPdfPageWidth: null as number | null,
    hasAppliedInitialFit: false,
    useNativePdfPreview: false,
    nativeFallbackTriggered: false,
    renderedPageMetrics: {} as Record<number, RenderedPageMetrics>,
    isCompactHeader: false,
    applyingExternalPdfScroll: false,
    isPdfUserScrolling: false,
    lastEmittedPdfPercent: -1,
    virtualContentHeight: 0,
    maxPageWidth: 0,
    forceReRenderToken: 0,
  })

  // --- 引用与非响应式成员 ---
  public refs = {
    pdfScroll: ref<HTMLElement | null>(null),
    leftText: ref<HTMLElement | null>(null),
    headerTitle: ref<HTMLElement | null>(null),
    headerMain: ref<HTMLElement | null>(null),
    pdfToolbar: ref<HTMLElement | null>(null),
    pdfToolbarMeasure: ref<HTMLElement | null>(null),
  }

  private pdfDocument = shallowRef<any>(null)
  private pdfLoadingTask = shallowRef<any>(null)
  private pdfLoadToken = 0
  
  private pageElements = new Map<number, HTMLElement>()
  private pageResizeObservers = new Map<number, ResizeObserver>()
  private pageCanvasElements = new Map<number, HTMLCanvasElement>()
  private pageLastRenderedScale = new Map<number, number>()
  private pageRenderTasks = new Map<number, { cancel: () => void; promise: Promise<any> }>()
  private pageRenderRafIds = new Map<number, number>()
  
  private headerResizeObserver = shallowRef<ResizeObserver | null>(null)
  private pdfScrollResizeObserver = shallowRef<ResizeObserver | null>(null)
  
  private pdfUserScrollTimeout: number | null = null
  private pendingPdfSyncPercent: number | null = null
  private pdfSyncRafId: number | null = null
  private fitScaleRafId: number | null = null
  private pendingRangeUpdate = false

  constructor() {
    pdfjsLib.GlobalWorkerOptions.workerSrc = new URL('pdfjs-dist/build/pdf.worker.min.mjs', import.meta.url).toString()
  }

  // --- 计算属性桥接 ---
  public get displayPdfPageCount() {
    if (props.pdfPageCount && props.pdfPageCount > 1) return props.pdfPageCount
    if (this.state.localPdfPageCount > 1) return this.state.localPdfPageCount
    return 1
  }

  public get zoomPercentLabel() {
    return `${Math.round(this.state.pdfScale * 100)}%`
  }

  public get minPdfScale() {
    return this.MIN_SCALE
  }

  public get maxPdfScale() {
    return this.MAX_SCALE
  }

  public get normalizedPdfSource() {
    return props.fileUrl || props.pdfViewerUrl.split('#')[0] || props.pdfViewerUrl
  }

  public get nativePdfViewerUrl() {
    const page = this.clampPage(this.state.activePdfPage)
    const zoom = Math.max(10, Math.round(this.state.pdfScale * 100))
    // 添加 #toolbar=0 以隐藏原生浏览器的 PDF 工具栏，保持 UI 一致性
    return `${this.normalizedPdfSource}#page=${page}&zoom=${zoom}&toolbar=0&navpanes=0&scrollbar=0`
  }

  public get pageLayout() {
    const topByPage: number[] = []
    let cursor = this.VERTICAL_PADDING
    const count = this.displayPdfPageCount
    for (let page = 1; page <= count; page += 1) {
      topByPage[page] = cursor
      cursor += this.pageHeightOf(page)
      if (page < count) {
        cursor += this.PAGE_GAP
      }
    }
    return {
      topByPage,
      totalHeight: Math.max(1, cursor + this.VERTICAL_PADDING)
    }
  }

  // --- 核心方法 ---

  public pageHeightOf(page: number) {
    return this.state.pageHeights[page] || this.state.estimatedPageHeight
  }

  public clampPage(value: number) {
    const total = Math.max(1, this.displayPdfPageCount)
    if (!Number.isFinite(value)) return 1
    return Math.max(1, Math.min(total, Math.round(value)))
  }

  public clampScale(value: number) {
    if (!Number.isFinite(value)) return 1
    return Math.max(this.MIN_SCALE, Math.min(this.MAX_SCALE, Number(value.toFixed(2))))
  }

  /**
   * 更新标题栏紧凑模式
   */
  public updateHeaderCompactMode() {
    if (!props.isPdf) {
      this.state.isCompactHeader = false
      return
    }
    const headerElement = this.refs.headerTitle.value
    if (!headerElement) return

    const headerWidth = headerElement.clientWidth
    const titleElement = this.refs.headerMain.value
    const titleWidth = titleElement?.scrollWidth || 0
    
    // 获取工具栏宽度，优先使用隐藏的测量工具栏
    const measureToolbar = this.refs.pdfToolbarMeasure.value
    const toolbarWidth = measureToolbar?.scrollWidth || 0
    
    if (headerWidth <= 0 || toolbarWidth <= 0) return

    // 如果标题 + 工具栏占用了超过 92% 的宽度，则进入紧凑模式
    // 留出一定的缓冲区避免频繁切换
    const threshold = headerWidth * 0.92
    const requiredWidth = titleWidth + toolbarWidth + 24
    
    const nextCompact = requiredWidth > threshold
    if (this.state.isCompactHeader !== nextCompact) {
      this.state.isCompactHeader = nextCompact
    }
  }

  /**
   * 更新可见页面范围
   */
  public updateRenderedPageRange() {
    const container = this.refs.pdfScroll.value
    const layout = this.pageLayout
    this.state.virtualContentHeight = layout.totalHeight

    if (!container || !props.isPdf) {
      this.state.renderedPageRange = { start: 1, end: Math.max(1, this.displayPdfPageCount) }
      return
    }
    const pageCount = Math.max(1, this.displayPdfPageCount)
    if (pageCount <= 1) {
      this.state.renderedPageRange = { start: 1, end: 1 }
      return
    }
    const viewportTop = container.scrollTop
    const viewportBottom = viewportTop + container.clientHeight
    let firstVisibleIndex = -1
    let lastVisibleIndex = -1

    for (let page = 1; page <= pageCount; page += 1) {
      const pageTop = layout.topByPage[page] || 0
      // 包含 PAGE_GAP 在内，确保没有缝隙导致判定失败
      const pageBottom = pageTop + this.pageHeightOf(page) + this.PAGE_GAP
      const intersectsViewport = pageBottom >= viewportTop && pageTop <= viewportBottom
      if (intersectsViewport) {
        if (firstVisibleIndex === -1) firstVisibleIndex = page
        lastVisibleIndex = page
      }
    }

    if (firstVisibleIndex === -1 || lastVisibleIndex === -1) {
      // 兜底策略：如果因为某种原因没有交集（极小概率），根据 scrollTop 估算最近的页面
      let closestPage = 1
      let minDiff = Number.POSITIVE_INFINITY
      for (let page = 1; page <= pageCount; page += 1) {
        const diff = Math.abs((layout.topByPage[page] || 0) - viewportTop)
        if (diff < minDiff) {
          minDiff = diff
          closestPage = page
        }
      }
      this.state.renderedPageRange = {
        start: Math.max(1, closestPage - this.RENDER_BUFFER),
        end: Math.min(pageCount, closestPage + this.RENDER_BUFFER)
      }
      return
    }

    this.state.renderedPageRange = {
      start: Math.max(1, firstVisibleIndex - this.RENDER_BUFFER),
      end: Math.min(pageCount, lastVisibleIndex + this.RENDER_BUFFER)
    }
  }

  /**
   * 调度可见页面范围更新
   */
  public scheduleRenderedPageRangeUpdate() {
    if (this.pendingRangeUpdate) return
    this.pendingRangeUpdate = true
    // 移除不必要的 setTimeout，恢复为直接的 rAF，减少状态同步的延迟
    requestAnimationFrame(() => {
      this.pendingRangeUpdate = false
      this.updateRenderedPageRange()
    })
  }

  /**
   * PDF 文档加载成功后的初始化
   */
  private async onPdfDocumentLoaded(nextDocument: any) {
    this.state.useNativePdfPreview = false
    this.pdfDocument.value = nextDocument
    this.state.localPdfPageCount = Number(nextDocument?.numPages || 0)
    
    // 获取第一页并记录原始宽度，加速自适应缩放响应速度
    if (this.state.localPdfPageCount > 0) {
      try {
        const firstPage = await nextDocument.getPage(1)
        const viewport = firstPage.getViewport({ scale: 1 })
        if (viewport.width > 0) {
          this.state.intrinsicPdfPageWidth = viewport.width
          console.log(`[PDFViewer] Initialized intrinsicPdfPageWidth: ${this.state.intrinsicPdfPageWidth}`)
          // 立即触发一次自适应缩放计算，提高首屏渲染体验
          if (this.state.isFitToWindowMode) {
            this.applyFitToWindowScale()
          }
        }
      } catch (e) {
        console.warn('[PDFViewer] Failed to pre-fetch first page width:', e)
      }
    }
    
    this.scheduleRenderedPageRangeUpdate()
    this.scheduleFitToWindowScale()
    await nextTick()
    this.renderVisiblePages()
  }

  public async loadPdfDocument(source: string) {
    if (!source || !props.isPdf) return
    this.state.useNativePdfPreview = false
    this.state.nativeFallbackTriggered = false
    const nextToken = this.pdfLoadToken + 1
    this.pdfLoadToken = nextToken
    this.destroyPdfLoadingTask()
    this.destroyPdfDocument()
    this.clearPdfRenderState()
    
    // 强制使用 fetch + ArrayBuffer 方式加载，彻底避开代理对 Range 请求处理不当导致的 ERR_ABORTED
    try {
      const response = await fetch(source, { credentials: 'same-origin' })
      if (!response.ok) throw new Error(`Failed to fetch PDF (${response.status})`)
      
      const pdfBinary = new Uint8Array(await response.arrayBuffer())
      if (this.pdfLoadToken !== nextToken) return

      const loadingTask = pdfjsLib.getDocument({
        data: pdfBinary,
        disableRange: true,    // 内存数据不需要 Range 请求
        disableStream: true,   // 内存数据不需要流式
        disableAutoFetch: true
      }) as { promise: Promise<any>, destroy?: () => void }
      
      this.pdfLoadingTask.value = loadingTask
      const nextDocument = await loadingTask.promise
      
      if (this.pdfLoadToken !== nextToken) {
        nextDocument?.destroy?.()
        return
      }
      
      await this.onPdfDocumentLoaded(nextDocument)
    } catch (error) {
      console.error('[PDFViewer] PDF load failed:', error)
      if (this.pdfLoadToken !== nextToken) return
      this.state.useNativePdfPreview = true
      this.pdfDocument.value = null
      this.state.localPdfPageCount = 0
    } finally {
      if (this.pdfLoadToken === nextToken) {
        this.pdfLoadingTask.value = null
      }
    }
  }

  public renderVisiblePages() {
    if (!props.isPdf || !this.pdfDocument.value) return
    const start = this.state.renderedPageRange.start
    const end = this.state.renderedPageRange.end
    for (let page = start; page <= end; page += 1) {
      this.scheduleRenderPage(page)
    }
  }

  public scheduleRenderPage(page: number) {
    const previousRafId = this.pageRenderRafIds.get(page)
    if (previousRafId !== undefined) cancelAnimationFrame(previousRafId)
    
    const rafId = requestAnimationFrame(() => {
      this.pageRenderRafIds.delete(page)
      void this.renderPageToCanvas(page)
    })
    this.pageRenderRafIds.set(page, rafId)
  }

  private async renderPageToCanvas(page: number) {
    if (!props.isPdf) return
    const doc = this.pdfDocument.value
    const canvas = this.pageCanvasElements.get(page)
    if (!doc || !canvas) return

    const lastRenderedScale = this.pageLastRenderedScale.get(page)
    const isScaleChanged = lastRenderedScale !== this.state.pdfScale
    const canvasOk = canvas.width > 0 && canvas.height > 0

    if (this.pageRenderTasks.has(page)) {
      if (!isScaleChanged) return
      
      // Cancel the ongoing task and wait for it to fully abort before starting a new one
      // This prevents Canvas 2D context state corruption (e.g. 180-degree mirror inversion)
      const oldTask = this.pageRenderTasks.get(page)
      oldTask?.cancel()
      try {
        await oldTask?.promise
      } catch (e) {
        // Expected cancellation error
      }
      this.pageRenderTasks.delete(page)
    } else {
      if (!isScaleChanged && canvasOk) return
    }

    try {
      // Prevent race conditions while waiting for getPage
      let isCancelled = false
      const taskPlaceholder = { 
        cancel: () => { isCancelled = true },
        promise: Promise.resolve() 
      }
      this.pageRenderTasks.set(page, taskPlaceholder as any)

      const pdfPage = await doc.getPage(page)
      if (isCancelled || !this.pdfDocument.value || this.pdfDocument.value !== doc) return
      
      const outputScale = window.devicePixelRatio || 1
      
      // 1. 物理像素尺寸 (Canvas) 的 viewport
      const viewport = pdfPage.getViewport({ scale: this.state.pdfScale * outputScale })
      
      // 2. 逻辑像素尺寸 (CSS)
      const cssWidth = Math.max(1, viewport.width / outputScale)
      const cssHeight = Math.max(1, viewport.height / outputScale)
      
      const targetWidth = Math.max(1, Math.floor(viewport.width))
      const targetHeight = Math.max(1, Math.floor(viewport.height))

      const isSizeChanged = canvas.width !== targetWidth || canvas.height !== targetHeight

      if (isSizeChanged) {
        canvas.width = targetWidth
        canvas.height = targetHeight
      }

      canvas.style.width = `${cssWidth}px`
      canvas.style.height = `${cssHeight}px`

      const canvasContext = canvas.getContext('2d', { alpha: false })
      if (!canvasContext) return

      // 重置变换矩阵，防止因前一次渲染任务取消导致上下文处于缩放/翻转状态（解决 180° 翻转问题）
      canvasContext.setTransform(1, 0, 0, 1, 0, 0)
      
      // 每次渲染前清理并填充白色背景，避免重影和透明背景问题
      canvasContext.fillStyle = '#ffffff'
      canvasContext.fillRect(0, 0, targetWidth, targetHeight)

      const renderTask = pdfPage.render({
        canvasContext,
        viewport: viewport,
        intent: 'display'
      })
      this.pageRenderTasks.set(page, renderTask)
      await renderTask.promise
      
      if (this.pageRenderTasks.get(page) === renderTask) {
        this.pageRenderTasks.delete(page)
        this.pageLastRenderedScale.set(page, this.state.pdfScale)
      }
      requestAnimationFrame(() => this.measurePageElement(page))
      
      // 修复 baseViewport 引用错误，使用当前视口的基础宽度
      const baseWidth = viewport.width / (this.state.pdfScale * outputScale)
      if (!this.state.intrinsicPdfPageWidth && baseWidth > 0) {
        this.state.intrinsicPdfPageWidth = baseWidth
        console.log(`[PDFViewer] Set intrinsicPdfPageWidth: ${this.state.intrinsicPdfPageWidth} from page ${page}`)
        if (this.state.isFitToWindowMode) {
          this.scheduleFitToWindowScale()
        }
      }
      
      this.scheduleRenderedPageRangeUpdate()
      if (this.state.isFitToWindowMode && !this.state.hasAppliedInitialFit) {
        this.scheduleFitToWindowScale()
      }
    } catch (error) {
      this.cancelPageRenderTask(page)
      if (this.isRenderCancelledError(error)) return
      
      console.warn(`[PDFViewer] Failed to render page ${page}:`, error)
      // 不再因为单页渲染失败而直接切换到原生预览，除非是文档本身已损坏
      if (error && typeof error === 'object' && (error as any).name === 'PasswordException') {
        this.state.nativeFallbackTriggered = true
        this.state.useNativePdfPreview = true
      }
    }
  }

  private cancelPageRenderTask(page: number) {
    const task = this.pageRenderTasks.get(page)
    task?.cancel()
    this.pageRenderTasks.delete(page)
  }

  private isRenderCancelledError(error: unknown) {
    if (!error || typeof error !== 'object') return false
    return (error as { name?: string }).name === 'RenderingCancelledException'
  }

  public scheduleFitToWindowScale() {
    if (!this.state.isFitToWindowMode) return
    if (this.fitScaleRafId !== null) return
    
    // 增加延迟，确保容器尺寸已经稳定，避免在布局抖动期间频繁计算缩放
    this.fitScaleRafId = requestAnimationFrame(() => {
      this.fitScaleRafId = null
      this.applyFitToWindowScale()
    })
  }

  private applyFitToWindowScale() {
    const nextScale = this.getFitToWindowScale()
    if (nextScale === null) {
      // 只有在真正完成缩放应用后才清除过渡状态
      this.state.isScaleTransitioning = false
      return
    }
    const safeScale = this.clampScale(nextScale)
    // 如果缩放差异极小，则不触发重新缩放
    if (Math.abs(safeScale - this.state.pdfScale) >= 0.001) {
      this.applyPdfScale(safeScale)
    } else {
      this.state.isScaleTransitioning = false
    }
    
    // 在下一帧标记完成，确保渲染任务已提交
    requestAnimationFrame(() => {
      this.state.hasAppliedInitialFit = true
    })
  }

  private getFitToWindowScale() {
    if (!props.isPdf || !this.refs.pdfScroll.value) return null
    const containerWidth = this.refs.pdfScroll.value.clientWidth
    if (!containerWidth || containerWidth <= this.FIT_PADDING * 2) return null

    const availableWidth = Math.max(1, containerWidth - this.FIT_PADDING * 2)
    
    // 优先使用当前页面的原始宽度进行计算，如果没有则使用全局记录的宽度
    let baseWidth = 0
    
    // 1. 尝试从已渲染页面的 metrics 中获取（最准确，支持多尺寸页面）
    const currentPage = this.state.activePdfPage || props.currentPdfPage || 1
    const metrics = this.state.renderedPageMetrics[currentPage]
    if (metrics && metrics.width > 0) {
      baseWidth = metrics.width / (this.state.pdfScale || 1)
    }
    
    // 2. 如果当前页不可用，尝试使用 intrinsicPdfPageWidth (通常是第一页的宽度)
    if (baseWidth <= 0) {
      baseWidth = this.state.intrinsicPdfPageWidth || 0
    }
    
    // 3. 兜底：如果还是没有，从所有已加载页面的平均宽度推算
    if (baseWidth <= 0) {
      const allHeights = Object.values(this.state.pageHeights)
      if (allHeights.length > 0) {
        // 使用平均高度推算宽度（假设 A4 比例 1:1.414）
        const avgHeight = allHeights.reduce((s, h) => s + h, 0) / allHeights.length
        baseWidth = (avgHeight / 1.414) / (this.state.pdfScale || 1)
      }
    }

    if (baseWidth > 0) {
      return availableWidth / baseWidth
    }

    return null
  }

  public applyPdfScale(nextScale: number) {
    const safeScale = this.clampScale(nextScale)
    // 使用更严格的阈值判断是否真正发生了缩放变化，避免由于微小偏差引起的重绘闪烁
    if (Math.abs(safeScale - this.state.pdfScale) < 0.005) {
      this.state.isScaleTransitioning = false
      return
    }
    
    // 缩放比例发生变化时，旧的页面高度和测量数据全部失效
    // 必须清空以避免混合不同缩放比例下的高度，导致滚动跳动和白屏
    this.state.pageHeights = {}
    this.state.renderedPageMetrics = {}
    this.state.maxPageWidth = 0
    // 基于新缩放比例估算新的默认高度 (假设 A4 比例)
    if (this.state.intrinsicPdfPageWidth) {
      this.state.estimatedPageHeight = Math.round(this.state.intrinsicPdfPageWidth * safeScale * 1.414)
    }

    this.state.isScaleTransitioning = true
    this.state.pdfScale = safeScale
    nextTick(() => {
      this.scheduleRenderedPageRangeUpdate()
      // 在自适应模式下不强制滚动，让用户维持当前浏览进度
      if (!this.state.isFitToWindowMode) {
        this.scrollToPdfPage(this.state.activePdfPage, 'auto')
      }
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          this.state.isScaleTransitioning = false
        })
      })
    })
  }

  public scrollToPdfPage(targetPage: number, behavior: ScrollBehavior = 'auto') {
    if (!props.isPdf || !this.refs.pdfScroll.value) return
    const page = this.clampPage(targetPage)
    const targetTop = Math.max(0, (this.pageLayout.topByPage[page] || 0) - 8)
    this.state.activePdfPage = page
    this.refs.pdfScroll.value.scrollTo({ top: targetTop, behavior })
    this.scheduleRenderedPageRangeUpdate()
  }

  public onPdfScroll(e: Event) {
    if (this.state.useNativePdfPreview) return
    const target = e.target as HTMLElement
    if (!target) return
    
    this.state.activePdfPage = this.resolveViewportPage(target.scrollTop, target.clientHeight)
    if (!this.state.applyingExternalPdfScroll) {
      this.markPdfUserScrolling()
    }
    this.scheduleRenderedPageRangeUpdate()
    
    const { scrollTop, scrollHeight, clientHeight } = target
    if (scrollHeight <= clientHeight) return

    const percent = scrollTop / (scrollHeight - clientHeight)
    if (!this.state.applyingExternalPdfScroll) {
      this.emitPdfScrollPercent(percent)
    }
  }

  private resolveViewportPage(scrollTop: number, clientHeight: number) {
    const pageCount = Math.max(1, this.displayPdfPageCount)
    const viewportCenter = scrollTop + (clientHeight / 2)
    let bestPage = 1
    let minDistance = Number.POSITIVE_INFINITY
    const layout = this.pageLayout
    for (let page = 1; page <= pageCount; page += 1) {
      const top = layout.topByPage[page] || 0
      const center = top + (this.pageHeightOf(page) / 2)
      const distance = Math.abs(center - viewportCenter)
      if (distance < minDistance) {
        minDistance = distance
        bestPage = page
      }
    }
    return bestPage
  }

  private markPdfUserScrolling() {
    this.state.isPdfUserScrolling = true
    if (this.pdfUserScrollTimeout !== null) window.clearTimeout(this.pdfUserScrollTimeout)
    this.pdfUserScrollTimeout = window.setTimeout(() => {
      this.state.isPdfUserScrolling = false
      this.pdfUserScrollTimeout = null
    }, 140)
  }

  private emitPdfScrollPercent(percent: number) {
    this.pendingPdfSyncPercent = percent
    if (this.pdfSyncRafId !== null) return
    this.pdfSyncRafId = requestAnimationFrame(() => {
      this.pdfSyncRafId = null
      const nextPercent = this.pendingPdfSyncPercent
      this.pendingPdfSyncPercent = null
      if (nextPercent === null) return
      if (Math.abs(nextPercent - this.state.lastEmittedPdfPercent) < 0.006) return
      this.state.lastEmittedPdfPercent = nextPercent
      emit('text-scroll', nextPercent)
    })
  }

  // --- 外部接口与生命周期 ---

  public setPdfCanvasElement(page: number, element: unknown) {
    const canvas = element instanceof HTMLCanvasElement ? element : null
    const previousCanvas = this.pageCanvasElements.get(page)
    if (previousCanvas && previousCanvas !== canvas) {
      // Immediately free canvas memory to prevent "too many active WebGL/Canvas contexts" 
      // which causes white screens during violent scrolling
      previousCanvas.width = 0
      previousCanvas.height = 0
      
      this.pageCanvasElements.delete(page)
      this.cancelPageRenderTask(page)
      this.pageLastRenderedScale.delete(page)
    }
    if (!canvas) return
    this.pageCanvasElements.set(page, canvas)
    if (props.isPdf) this.scheduleRenderPage(page)
  }

  public setPdfPageElement(page: number, el: unknown) {
    const element = el instanceof HTMLElement ? el : (el && typeof el === 'object' && '$el' in (el as any) ? (el as any).$el : null)
    
    const previous = this.pageElements.get(page)
    if (previous && previous !== element) {
      this.pageResizeObservers.get(page)?.disconnect()
      this.pageResizeObservers.delete(page)
      this.pageElements.delete(page)
    }
    
    if (!(element instanceof HTMLElement)) return
    
    this.pageElements.set(page, element)

    const measureHeight = () => {
      this.measurePageElement(page)
    }

    requestAnimationFrame(measureHeight)
    if (typeof ResizeObserver !== 'undefined' && !this.pageResizeObservers.has(page)) {
      const observer = new ResizeObserver(() => measureHeight())
      observer.observe(element)
      this.pageResizeObservers.set(page, observer)
    }
  }

  private updateMaxPageWidth() {
    let max = 0
    for (const key in this.state.renderedPageMetrics) {
      const w = this.state.renderedPageMetrics[key]?.width || 0
      if (w > max) max = w
    }
    this.state.maxPageWidth = max
  }

  private updateEstimatedHeight() {
    const values = Object.values(this.state.pageHeights).filter(h => h > 0)
    if (!values.length) return
    const total = values.reduce((s, i) => s + i, 0)
    this.state.estimatedPageHeight = Math.max(600, Math.round(total / values.length))
  }

  public clearPdfRenderState() {
    this.pageRenderRafIds.forEach(id => cancelAnimationFrame(id))
    this.pageRenderRafIds.clear()
    this.pageRenderTasks.forEach(t => t.cancel())
    this.pageRenderTasks.clear()
    this.pageCanvasElements.clear()
    this.pageLastRenderedScale.clear()
  }

  /**
   * 清理所有页面相关的数据，包括 DOM 引用和观察者。
   * 当文档切换或卸载时必须调用此方法，以防止跨文档的状态干扰。
   */
  public clearAllPageData() {
    console.log('[PDFViewer] Clearing all page data for document switch/unmount')
    this.clearPdfRenderState()
    
    // 断开并清理所有的 ResizeObserver，防止泄露或观察到已销毁的 DOM
    this.pageResizeObservers.forEach(o => o.disconnect())
    this.pageResizeObservers.clear()
    
    // 清理所有的 DOM 引用映射
    this.pageElements.clear()
    
    // 重置响应式状态中的页面级度量
    this.state.pageHeights = {}
    this.state.renderedPageMetrics = {}
    this.state.maxPageWidth = 0
    this.state.hasAppliedInitialFit = false
    this.state.isScaleTransitioning = false
    this.state.intrinsicPdfPageWidth = null
    // 重置缩放，确保新文档能重新计算
    this.state.pdfScale = 1
  }

  public destroyPdfLoadingTask() {
    this.pdfLoadingTask.value?.destroy?.()
    this.pdfLoadingTask.value = null
  }

  public destroyPdfDocument() {
    this.pdfDocument.value?.destroy?.()
    this.pdfDocument.value = null
  }

  private resizeHandler = () => {
    this.scheduleRenderedPageRangeUpdate()
    this.scheduleFitToWindowScale()
  }

  public onMounted() {
    this.updateHeaderCompactMode()
    if (typeof ResizeObserver !== 'undefined') {
      if (this.refs.headerTitle.value) {
        this.headerResizeObserver.value = new ResizeObserver(() => this.updateHeaderCompactMode())
        this.headerResizeObserver.value.observe(this.refs.headerTitle.value)
      }
      if (this.refs.pdfScroll.value) {
        this.pdfScrollResizeObserver.value = new ResizeObserver(() => {
          if (this.state.isFitToWindowMode) this.scheduleFitToWindowScale()
        })
        this.pdfScrollResizeObserver.value.observe(this.refs.pdfScroll.value)
      }
    }
    window.addEventListener('resize', this.resizeHandler)
    this.watchIntrinsicWidth()
    this.watchFitMode()
    nextTick(() => {
      this.scheduleRenderedPageRangeUpdate()
      if (this.state.isFitToWindowMode) this.scheduleFitToWindowScale()
    })
  }

  public onBeforeUnmount() {
    window.removeEventListener('resize', this.resizeHandler)
    if (this.pdfUserScrollTimeout) window.clearTimeout(this.pdfUserScrollTimeout)
    if (this.pdfSyncRafId) cancelAnimationFrame(this.pdfSyncRafId)
    if (this.fitScaleRafId) cancelAnimationFrame(this.fitScaleRafId)
    this.clearAllPageData()
    this.destroyPdfLoadingTask()
    this.destroyPdfDocument()
    this.headerResizeObserver.value?.disconnect()
    this.pdfScrollResizeObserver.value?.disconnect()
  }

  // --- 暴露给 Template 的方法 ---
  public zoomIn() { this.state.isFitToWindowMode = false; this.applyPdfScale(this.state.pdfScale + this.SCALE_STEP) }
  public zoomOut() { this.state.isFitToWindowMode = false; this.applyPdfScale(this.state.pdfScale - this.SCALE_STEP) }
  public resetZoom() { this.state.isFitToWindowMode = true; this.state.hasAppliedInitialFit = false; this.scheduleFitToWindowScale() }
  public goPrevPage() { this.scrollToPdfPage(this.state.activePdfPage - 1, 'smooth') }
  public goNextPage() { this.scrollToPdfPage(this.state.activePdfPage + 1, 'smooth') }
  public onPageInputChange(v: any) { const p = Number(v); if (Number.isFinite(p)) this.scrollToPdfPage(p, 'smooth') }

  public watchIntrinsicWidth() {
    watch(() => this.state.intrinsicPdfPageWidth, (val) => {
      if (val && this.state.isFitToWindowMode) {
        this.scheduleFitToWindowScale()
      }
    })
  }

  public watchFitMode() {
    watch(() => this.state.isFitToWindowMode, (val) => {
      if (val) {
        this.state.hasAppliedInitialFit = false
        this.scheduleFitToWindowScale()
      }
    })
  }

  private measurePageElement(page: number) {
    const element = this.pageElements.get(page)
    if (!element) return
    const mediaElement = element.querySelector('canvas, img')
    if (!(mediaElement instanceof HTMLElement)) return
    if (mediaElement instanceof HTMLCanvasElement) {
      const renderedScale = this.pageLastRenderedScale.get(page)
      const hasRenderedAtCurrentScale = renderedScale !== undefined && Math.abs(renderedScale - this.state.pdfScale) < 0.001
      const hasCanvasSize = mediaElement.width > 0 && mediaElement.height > 0 && mediaElement.style.width !== '' && mediaElement.style.height !== ''
      if (!hasRenderedAtCurrentScale || !hasCanvasSize) return
    }

    const mediaRect = mediaElement.getBoundingClientRect()
    const wrapperRect = element.getBoundingClientRect()
    if (mediaRect.width <= 1 || mediaRect.height <= 1) return

    const nextHeight = Math.max(400, Math.round(mediaRect.height))
    const nextMetrics: RenderedPageMetrics = {
      top: Math.max(0, mediaRect.top - wrapperRect.top),
      left: Math.max(0, mediaRect.left - wrapperRect.left),
      width: Math.max(1, mediaRect.width),
      height: nextHeight,
      scale: this.state.pdfScale
    }

    const currentHeight = this.state.pageHeights[page]
    const currentMetrics = this.state.renderedPageMetrics[page]
    const metricsChanged = !currentMetrics ||
      Math.abs(currentMetrics.scale - nextMetrics.scale) > 0.001 ||
      ['top', 'left', 'width', 'height'].some(k => Math.abs((currentMetrics as any)[k] - (nextMetrics as any)[k]) > 0.5)

    if (currentHeight !== nextHeight) {
      this.state.pageHeights = { ...this.state.pageHeights, [page]: nextHeight }
      this.updateEstimatedHeight()
      this.scheduleRenderedPageRangeUpdate()
    }

    if (metricsChanged) {
      this.state.renderedPageMetrics = { ...this.state.renderedPageMetrics, [page]: nextMetrics }
      this.updateMaxPageWidth()
      if (this.state.isFitToWindowMode && !this.state.hasAppliedInitialFit) {
        this.scheduleFitToWindowScale()
      }
    }
  }
}

const controller = new PdfViewerController()
const { state, refs } = controller
const { 
  pdfScale, activePdfPage, isCompactHeader, isFitToWindowMode, useNativePdfPreview,
  virtualContentHeight, maxPageWidth, renderedPageRange, renderedPageMetrics, isScaleTransitioning,
  hasAppliedInitialFit
} = toRefs(state)

const {
  pdfScroll: pdfScrollRef,
  leftText: leftTextRef,
  headerTitle: headerTitleRef,
  headerMain: headerMainRef,
  pdfToolbar: pdfToolbarRef,
  pdfToolbarMeasure: pdfToolbarMeasureRef,
} = refs

// --- 桥接 Computed ---
const displayPdfPageCount = computed(() => controller.displayPdfPageCount)
const zoomPercentLabel = computed(() => controller.zoomPercentLabel)
const minPdfScale = computed(() => controller.minPdfScale)
const maxPdfScale = computed(() => controller.maxPdfScale)
const normalizedPdfSource = computed(() => controller.normalizedPdfSource)
const nativePdfViewerUrl = computed(() => controller.nativePdfViewerUrl)
const pageLayout = computed(() => controller.pageLayout)
const shouldShowPdfHighlights = computed(() => {
  // 只要有缩放比例且不是正在剧烈变动中，就可以尝试显示高亮
  if (!props.isPdf || useNativePdfPreview.value) return false
  if (isScaleTransitioning.value) return false
  return true
})

// 模板引用占位，防止 Linter 报错
void [headerTitleRef, headerMainRef, pdfToolbarRef, pdfToolbarMeasureRef, minPdfScale, maxPdfScale, normalizedPdfSource, nativePdfViewerUrl, pageLayout, shouldShowPdfHighlights, hasAppliedInitialFit]

const visiblePdfPages = computed<VirtualPageMeta[]>(() => {
  const pages: VirtualPageMeta[] = []
  const { start, end } = renderedPageRange.value
  const layout = pageLayout.value
  for (let page = start; page <= end; page += 1) {
    pages.push({ page, top: layout.topByPage[page] || 24, height: controller.pageHeightOf(page) })
  }
  return pages
})

const getPdfPageStyle = (pageMeta: VirtualPageMeta) => ({ top: `${pageMeta.top}px`, minHeight: `${pageMeta.height}px` })
const getHighlightLayerStyle = (page: number) => {
  const m = renderedPageMetrics.value[page]
  return m ? { top: `${m.top}px`, left: `${m.left}px`, width: `${m.width}px`, height: `${m.height}px` } : { inset: '0' }
}
const getHighlightTypeLabel = (type?: string) => {
  const normalizedType = String(type || '').trim().toLowerCase()
  if (!normalizedType) return ''
  const labelMap: Record<string, string> = {
    image: '图片',
    'image-caption': '图片题注',
    'image-footnote': '图片脚注',
    table: '表格',
    'table-caption': '表题',
    'table-footnote': '表注',
    title: '标题',
    paragraph: '正文',
    list: '列表',
    equation_interline: '公式',
    text: '文本'
  }
  return labelMap[normalizedType] || normalizedType.replace(/[_-]+/g, ' ').trim()
}
const getPageHighlights = (page: number) => {
  if (!props.isPdf || !props.highlightLinkEnabled) return []
  // 核心逻辑：只有当该页面的坐标度量（Metrics）已经测量完成，高亮位置才是准确的
  if (!renderedPageMetrics.value[page]) return []
  return props.highlights
    .filter(h => h.page === page && h.hasRect !== false)
    .sort((left, right) => {
      const leftArea = (left.width || 0) * (left.height || 0)
      const rightArea = (right.width || 0) * (right.height || 0)
      return rightArea - leftArea
    })
}

// --- Watchers ---
watch([normalizedPdfSource, () => props.isPdf], async ([source, isPdf]) => {
  if (!isPdf || !source) return
  controller.clearAllPageData()
  Object.assign(state, {
    useNativePdfPreview: false,
    nativeFallbackTriggered: false,
    estimatedPageHeight: 1100,
    renderedPageRange: { start: 1, end: 1 },
    lastEmittedPdfPercent: -1,
    pdfScale: 1,
    isFitToWindowMode: true,
    isScaleTransitioning: true,
    activePdfPage: 1
  })
  await nextTick()
  if (pdfScrollRef.value) pdfScrollRef.value.scrollTop = 0
  controller.scheduleRenderedPageRangeUpdate()
  await controller.loadPdfDocument(source)
}, { immediate: true })

watch([() => renderedPageRange.value.start, () => renderedPageRange.value.end, pdfScale, () => props.isPdf], async () => {
  if (!useNativePdfPreview.value && props.isPdf) {
    await nextTick()
    controller.renderVisiblePages()
  }
})

watch(() => props.currentPdfPage, (newPage) => {
  if (!props.isPdf || newPage <= 0) return
  state.applyingExternalPdfScroll = true
  controller.scrollToPdfPage(newPage, 'auto')
  requestAnimationFrame(() => {
    state.applyingExternalPdfScroll = false
  })
})

watch(() => props.textScrollPercent, (percent) => {
  if (pdfScrollRef.value && props.isPdf && !state.isPdfUserScrolling && !useNativePdfPreview.value) {
    state.applyingExternalPdfScroll = true
    const max = pdfScrollRef.value.scrollHeight - pdfScrollRef.value.clientHeight
    pdfScrollRef.value.scrollTop = percent * max
    requestAnimationFrame(() => { state.applyingExternalPdfScroll = false })
  }
  if (leftTextRef.value && props.isText) {
    const max = leftTextRef.value.scrollHeight - leftTextRef.value.clientHeight
    leftTextRef.value.scrollTop = percent * max
  }
})

// --- 暴露方法给模板 ---
const goPrevPage = () => controller.goPrevPage()
const goNextPage = () => controller.goNextPage()
const onPageInputChange = (v: any) => controller.onPageInputChange(v)
const zoomIn = () => controller.zoomIn()
const zoomOut = () => controller.zoomOut()
const resetZoom = () => controller.resetZoom()
const onPdfScroll = (e: Event) => controller.onPdfScroll(e)
const setPdfCanvasElement = (p: number, el: any) => controller.setPdfCanvasElement(p, el)
const setPdfPageElement = (p: number, el: any) => controller.setPdfPageElement(p, el)
const onLeftTextScroll = () => {
  if (leftTextRef.value) emit('text-scroll', leftTextRef.value.scrollTop / (leftTextRef.value.scrollHeight - leftTextRef.value.clientHeight))
}

onMounted(() => controller.onMounted())
onBeforeUnmount(() => controller.onBeforeUnmount())
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
  margin-left: 0;
  margin-right: 0;
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
  background: var(--dp-bg-tertiary, #f5f5f5);
  display: flex;
  flex-direction: column;
}

.pdf-scroll-container-fit {
  overflow-x: hidden;
}

.pdf-virtual-spacer {
  position: relative;
  width: 100%;
  min-width: min-content; /* 确保虚拟占位符能够撑开容器，支持横向滚动 */
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
</style>
