<template>
  <div class="pdf-viewer-shell" :class="[themeClass, { 'has-side-panel': sidePanelVisible }]">
    <div ref="splitPaneRef" :class="['split-pane', themeClass]">
    <div ref="headerTitleRef" class="pane-title pane-title-with-actions">
      <div ref="headerMainRef" class="pane-title-main">
        <div class="pane-title-prefix-wrap">
          <span v-if="title" class="pane-title-doc-name" :title="title">{{ title }}</span>
          <span v-else class="pane-title-prefix">原文</span>
        </div>
        <Tag v-if="node.status === 'failed'" color="error" class="parse-state-tag">
          解析失败
        </Tag>
        <Tag v-else-if="node.status === 'cancelled'" class="parse-state-tag">
          已取消
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
            :disabled="!hasPrevPdfPage"
            @click="goPrevPage"
            v-if="compactLevel <= 4"
          >
            <template #icon><LeftOutlined /></template>
          </Button>
          <template v-if="compactLevel <= 5">
            <InputNumber
              :value="activePdfPage"
              size="small"
              :min="1"
              :max="displayPdfPageCount"
              class="pdf-page-input"
              :style="{ width: pageInputWidth + 'px' }"
              :controls="false"
              @change="onPageInputChange"
            />
            <span class="pdf-toolbar-text pdf-toolbar-text-slim">/</span>
          </template>
          <span v-if="compactLevel <= 6" class="pdf-toolbar-text pdf-toolbar-text-slim">{{ displayPdfPageCount }}</span>
          <Button
            size="small"
            class="pdf-tool-btn"
            :disabled="!hasNextPdfPage"
            @click="goNextPage"
            v-if="compactLevel <= 4"
          >
            <template #icon><RightOutlined /></template>
          </Button>
          <Button v-if="compactLevel <= 2" size="small" class="pdf-tool-btn pdf-tool-zoomout-gap" :disabled="pdfScale <= minPdfScale" @click="zoomOut">
            <template #icon><ZoomOutOutlined /></template>
          </Button>
          <span v-if="compactLevel <= 0" class="pdf-toolbar-text">{{ zoomPercentLabel }}</span>
          <Button v-if="compactLevel <= 1" size="small" class="pdf-tool-btn" :disabled="pdfScale >= maxPdfScale" @click="zoomIn">
            <template #icon><ZoomInOutlined /></template>
          </Button>
          <Button v-if="compactLevel <= 3" size="small" class="pdf-tool-btn" title="适应宽度" @click="resetZoom">
            <template #icon><CompressOutlined /></template>
          </Button>
        </template>
      </div>
      <div class="pane-title-right">
        <template v-if="isPdf && !useNativePdfPreview">
          <Button
            size="small"
            class="pdf-tool-btn"
            :class="{ 'pdf-tool-btn-active': showSearchPanel }"
            title="搜索"
            @click="toggleSearchPanel"
          >
            <template #icon><SearchOutlined /></template>
          </Button>
          <Button
            size="small"
            class="pdf-tool-btn"
            :class="{ 'pdf-tool-btn-active': showBbox }"
            title="显示定位框"
            @click="toggleBbox"
          >
            <template #icon><BulbOutlined /></template>
          </Button>
        </template>
        <Button
          v-if="showSidePanelToggle && $slots['side-panel']"
          size="small"
          class="pdf-tool-btn"
          :class="{ 'pdf-tool-btn-active': sidePanelVisible }"
          :title="sidePanelVisible ? '收起解析对比' : '展开解析对比'"
          @click="toggleSidePanel"
        >
          <template #icon>
            <LeftOutlined v-if="sidePanelVisible" />
            <RightOutlined v-else />
          </template>
        </Button>
      </div>
      <!-- 隐形测量镜像：包含全部控件，用于精确测量自然宽度 -->
      <div v-if="isPdf && !useNativePdfPreview" ref="toolbarMeasureRef" class="toolbar-measure" aria-hidden="true">
        <Button size="small" class="pdf-tool-btn"><template #icon><LeftOutlined /></template></Button>
        <InputNumber :value="activePdfPage" size="small" class="pdf-page-input" :style="{ width: pageInputWidth + 'px' }" :controls="false" />
        <span class="pdf-toolbar-text pdf-toolbar-text-slim">/</span>
        <span class="pdf-toolbar-text pdf-toolbar-text-slim">{{ displayPdfPageCount }}</span>
        <Button size="small" class="pdf-tool-btn"><template #icon><RightOutlined /></template></Button>
        <Button size="small" class="pdf-tool-btn pdf-tool-zoomout-gap"><template #icon><ZoomOutOutlined /></template></Button>
        <span class="pdf-toolbar-text">{{ zoomPercentLabel }}</span>
        <Button size="small" class="pdf-tool-btn"><template #icon><ZoomInOutlined /></template></Button>
        <Button size="small" class="pdf-tool-btn"><template #icon><CompressOutlined /></template></Button>
        <Button size="small" class="pdf-tool-btn"><template #icon><SearchOutlined /></template></Button>
        <Button size="small" class="pdf-tool-btn"><template #icon><BulbOutlined /></template></Button>
      </div>
    </div>
    <div v-if="node.status === 'processing' || node.status === 'failed' || node.status === 'cancelled'" class="parse-progress-row">
      <div v-if="node.status !== 'cancelled'" class="parse-progress-content">
        <span class="parse-progress-label">{{ parseProgressHeader }}</span>
        <span v-if="node.status === 'processing' && node.parseStep" class="parse-progress-step" :title="node.parseStep">：{{ node.parseStep }}</span>
      </div>
      <div v-if="node.parseError || node.status === 'cancelled'" class="parse-error-text" :title="node.parseError">{{ node.parseError || '已取消' }}</div>
    </div>
    <!-- 搜索面板 -->
    <div v-if="showSearchPanel && isPdf && !useNativePdfPreview" ref="searchPanelRef" class="search-panel">
      <div class="search-panel-input-row">
        <Input
          v-model:value="searchQuery"
          size="small"
          class="search-input"
          placeholder="搜索 PDF 文本..."
          allow-clear
          @pressEnter="performTextSearch"
          autofocus
        />
        <Button size="small" class="pdf-tool-btn" @click="closeSearchPanel">
          <template #icon><CloseOutlined /></template>
        </Button>
      </div>
      <div v-if="searchResults.length > 0" class="search-results">
        <div class="search-results-count">{{ searchResults.length }} 条结果</div>
        <div
          v-for="(result, idx) in searchResults"
          :key="idx"
          class="search-result-item"
          :class="{ active: idx === searchActiveIndex }"
          @click="jumpToSearchResult(result, idx)"
        >
          <span class="search-result-page">{{ result.page > 0 ? `第 ${displayPageLabel(result.page)} 页` : '-' }}</span>
          <span class="search-result-text" v-html="renderSearchSnippetHtml(result.text, searchQuery)" />
        </div>
      </div>
      <div v-else-if="isSearching" class="search-searching">
        搜索中...
      </div>
      <div v-else-if="searchQuery" class="search-no-results">
        {{ nativeSearchNoTextLayer ? '该 PDF 无文本层（扫描件），无法搜索' : '未找到匹配结果' }}
      </div>
    </div>
    <div class="file-preview">
      <div v-if="isPdf" class="pdf-preview-wrap">
        <!-- PDF加载进度指示器 -->
        <div v-if="isPdfLoading" class="pdf-loading-overlay">
          <Spin size="large" />
          <div class="pdf-loading-text">
            <span v-if="pdfLoadingProgress > 0">加载中 {{ pdfLoadingProgress }}%</span>
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
                :class="['pdf-highlight-box', {
                  'hover-primary': item.id === hoveredHighlightId,
                  'hover-linked': hoveredHighlightId && item.id !== hoveredHighlightId && (
                    item.itemId === hoveredItemId
                    || (item.linkedFormulaItemIds || []).includes(hoveredItemId || '')
                  ),
                  active: !hoveredHighlightId && (item.itemId === activeClickItemId || activeHighlightIds.includes(item.id) || activeHighlightIds.includes(item.itemId) || item.id === activeHighlightId || item.itemId === activeHighlightId)
                }]"
                :style="{
                  left: `${item.left * 100}%`,
                  top: `${item.top * 100}%`,
                  width: `${item.width * 100}%`,
                  height: `${item.height * 100}%`
                }"
                @mouseenter="onHighlightMouseEnter(item, $event.currentTarget as HTMLElement)"
                @mouseleave="onHighlightMouseLeave"
                @click="emit('select-highlight', item)"
              >
                <span v-if="getHighlightTypeLabel(item.type)" class="highlight-type-tag">{{ getHighlightTypeLabel(item.type) }}</span>
              </div>
            </div>
            <!-- 搜索结果黄色高亮（仅命中页显示） -->
            <div
              v-if="pageMeta.page === searchActivePage && searchActiveHighlights.length"
              class="pdf-highlight-layer pdf-search-active-layer"
              :style="getHighlightLayerStyle(pageMeta.page)"
            >
            <div
              v-for="item in searchActiveHighlights"
              :key="`search-${item.id}`"
              class="pdf-highlight-box search-active"
              :style="{
                left: `${item.left * 100}%`,
                top: `${item.top * 100}%`,
                width: `${item.width * 100}%`,
                height: `${item.height * 100}%`
              }"
            />
            </div>
            <!-- 搜索结果词级高亮（命中词细框，仅原生文本 PDF 提供） -->
            <div
              v-if="pageMeta.page === searchActivePage && searchWordRects.length"
              class="pdf-highlight-layer pdf-search-word-layer"
              :style="getHighlightLayerStyle(pageMeta.page)"
            >
              <div
                v-for="(rect, rectIdx) in searchWordRects"
                :key="`search-word-${rectIdx}`"
                class="pdf-highlight-box search-word"
                :style="{
                  left: `${rect.left * 100}%`,
                  top: `${rect.top * 100}%`,
                  width: `${rect.width * 100}%`,
                  height: `${rect.height * 100}%`
                }"
              />
            </div>
            <div
              v-if="hoverTip.visible && hoverTip.segments.length"
              ref="hoverTipEl"
              class="pdf-hover-tip"
              :class="{ 'pdf-hover-tip-flip': hoverTip.flipY }"
              :style="hoverTipStyle"
            >
              <template v-for="(seg, i) in hoverTip.segments" :key="i">
                <strong v-if="seg.hit" class="pdf-hover-tip__match">{{ seg.text }}</strong>
                <template v-else>{{ seg.text }}</template>
              </template>
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
          <OfficePreview v-if="isLocalOffice" :file-url="fileUrl" class="office-viewer" />
          <Empty v-else description="暂不支持该格式在线预览，请下载后查看">
            <template #extra>
              <Button type="primary" @click="emit('download')">下载文件</Button>
            </template>
          </Empty>
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
    <div
      :class="['pdf-viewer-side-panel', { 'pdf-viewer-side-panel-open': sidePanelVisible }]"
      :style="{ width: sidePanelVisible ? `${sidePanelWidth}px` : '0px' }"
      role="complementary"
      aria-label="解析对比面板"
    >
      <slot name="side-panel" />
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * PDF_Viewer — 可直接移植到任何 Vue 3 项目的 PDF 预览组件。
 *
 * ## 依赖
 *   vue ^3.3     ant-design-vue ^4     pdfjs-dist ^6     @ant-design/icons-vue ^7
 *
 * ## 最少 prop（开箱即用）
 *   :node="{ status: 'completed', filePath: '/path/doc.pdf' }"
 *   :isPdf="true"  :isOffice="false"  :isImage="false"  :isText="false"
 *   :pdfViewerUrl="url"  :fileUrl="url"  :textContent=""
 *   :currentPdfPage="1"  :highlights="[]"  :activeHighlightId="null"
 *   :textScrollPercent="0"
 *
 * ## 主题适配
 *   theme='auto'           → 跟随 @media (prefers-color-scheme)
 *   theme='dark'|'light'   → 显式指定
 *   不传 theme 并在父级设  --dp-pane-bg / --dp-title-bg 等 CSS 变量
 *
 * ## 事件
 *   @text-scroll (percent)  @pdf-active-page (page)  @select-highlight (item)
 *   @hover-highlight (id)   @download
 *
 * ## 事件：搜索跳转（新增）
 *   @search-jump (page, textIndex) — 外部可附加二次定位逻辑
 */
import { computed, ref, shallowRef, watch, onMounted, onBeforeUnmount, nextTick, reactive, useSlots } from 'vue'
import type { Ref, ComputedRef } from 'vue'
import { LeftOutlined, RightOutlined, ZoomInOutlined, ZoomOutOutlined, CompressOutlined, BulbOutlined, SearchOutlined, CloseOutlined } from '@ant-design/icons-vue'
import { Button, Tag, Spin, Progress, InputNumber, Input, Empty } from 'ant-design-vue'
import * as pdfjsLib from 'pdfjs-dist'
// Vite标准worker导入方式，确保生产构建路径正确
import pdfjsWorker from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import OfficePreview from './OfficePreview.vue'
import {
  buildMatchSegments,
  insetWordRects,
  matchTextItemRects,
  pickSearchTargetHighlight,
  textItemsInRect,
  type HighlightSegment,
  type PageTextItem,
  type SearchWordRect,
} from '../../../utils/pdfSearch'
import { renderSearchSnippetHtml } from '../../../utils/searchSnippet'
import { clampPageToRange, computeSeededPageHeights, normalizePageRange } from '../../../utils/pageRange'

export interface PDFViewerNode {
  status?: string
  parseStage?: string
  parseStep?: string
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
  linkedFormulaItemIds?: string[]
  text?: string      // bbox 原文全文，优先展示
  matchText?: string // 雷同段，用于加粗定位
  excerpt?: string   // 兼容别名：matchText 未提供时当 matchText 用
}

interface VirtualPageMeta {
  page: number
  top: number
  height: number
  width: number
}

interface RenderedPageMetrics {
  top: number
  left: number
  width: number
  height: number
  scale: number
}

const props = withDefaults(defineProps<{
  node: PDFViewerNode
  theme?: 'light' | 'dark' | 'auto'
  isPdf: boolean
  isOffice: boolean
  isImage: boolean
  isText: boolean
  pdfViewerUrl: string
  fileUrl: string
  textContent: string
  searchText?: string
  title?: string
  currentPdfPage: number
  pdfPageCount?: number
  pdfPageRange?: number[]
  highlights: LinkedHighlight[]
  activeHighlightId: string | null
  activeHighlightIds?: string[]
  activeClickItemId?: string | null
  /**
   * 外部切换 activeHighlightId 时，将对应高亮 bbox 纵向居中到视口（溯源定位体验）。
   * 注意：启用后任何 activeHighlightId 变化都会居中；避免把 hover 事件映射到
   * activeHighlightId，否则扫过高亮框时视口会跟随滚动。
   */
  centerActiveHighlight?: boolean
  pageLabels?: Record<number, string>
  textScrollPercent: number
  sidePanelOpen?: boolean
  showSidePanelToggle?: boolean
  sidePanelWidth?: number
  pdfAssetBaseUrl?: string
  highlightHoverText?: boolean
  highlightHoverFontSize?: number
  highlightHoverMaxWidth?: number
  highlightHoverMaxHeight?: number
}>(), {
  activeHighlightIds: () => [],
  centerActiveHighlight: false,
  sidePanelOpen: undefined,
  showSidePanelToggle: false,
  sidePanelWidth: 400,
  pdfAssetBaseUrl: `${import.meta.env.BASE_URL}`,
  highlightHoverText: true,
  highlightHoverFontSize: 13,
  highlightHoverMaxWidth: 340,
  highlightHoverMaxHeight: 180,
})

// --- hover 联动：hover 的框加深（hover-primary），同节点其它 bbox 浅橙（hover-linked） ---
const hoveredHighlightId = ref<string | null>(null)
const hoveredItemId = computed(() => {
  if (!hoveredHighlightId.value) return null
  const item = props.highlights.find(h => h.id === hoveredHighlightId.value)
  return item ? item.itemId : null
})

interface HoverTipState {
  visible: boolean
  left: number
  top: number
  width: number
  flipY: boolean
  segments: HighlightSegment[]
}
const hoverTip = ref<HoverTipState>({
  visible: false, left: 0, top: 0, width: 0, flipY: false, segments: [],
})
const hoverTipEl = ref<HTMLElement | null>(null)
let hoverTipToken = 0

const hideHighlightTip = () => { hoverTip.value.visible = false }

async function extractTextInRect(page: number, hl: LinkedHighlight): Promise<string> {
  const items = await loadPageTextItems(page)
  return textItemsInRect(items, { left: hl.left, top: hl.top, width: hl.width, height: hl.height })
}

async function resolveHoverSegments(item: LinkedHighlight): Promise<HighlightSegment[]> {
  const matchText = (item.matchText ?? item.excerpt ?? '').trim()
  if (item.text && item.text.trim()) {
    return buildMatchSegments(item.text, matchText)
  }
  if (!item.hasRect || item.width <= 0 || item.height <= 0) return []
  const extracted = await extractTextInRect(item.page, item)
  if (extracted) return buildMatchSegments(extracted, matchText)
  return matchText ? [{ text: matchText, hit: true }] : []
}

async function onHighlightMouseEnter(item: LinkedHighlight, box: HTMLElement) {
  hoveredHighlightId.value = item.id
  emit('hover-highlight', item.itemId)
  hoverTip.value.visible = false
  if (!props.highlightHoverText) return
  const token = ++hoverTipToken
  const segments = await resolveHoverSegments(item)
  if (token !== hoverTipToken || !segments.length) return
  const container = pdfScrollRef.value
  const spacer = container?.querySelector('.pdf-virtual-spacer') as HTMLElement | null
  if (!container || !spacer) return
  const containerRect = container.getBoundingClientRect()
  const boxRect = box.getBoundingClientRect()
  const vw = containerRect.width
  const maxWidth = Math.min(props.highlightHoverMaxWidth, Math.max(180, vw - 16))
  const width = Math.max(120, Math.min(boxRect.width, maxWidth))
  const visibleLeft = Math.max(8, Math.min(boxRect.left - containerRect.left, vw - width - 8))
  const spacerRect = spacer.getBoundingClientRect()
  const flipY = boxRect.top - containerRect.top < props.highlightHoverMaxHeight + 8
  const tipHeight = Math.min(props.highlightHoverMaxHeight, 180)
  const top = flipY
    ? boxRect.bottom - spacerRect.top + 4
    : boxRect.top - spacerRect.top - tipHeight - 4
  hoverTip.value = {
    visible: true,
    left: visibleLeft + (containerRect.left - spacerRect.left),
    top,
    width,
    flipY,
    segments,
  }
}

function onHighlightMouseLeave() {
  hoveredHighlightId.value = null
  hoverTip.value.visible = false
  emit('hover-highlight', null)
}

const hoverTipStyle = computed(() => ({
  left: `${hoverTip.value.left}px`,
  top: `${hoverTip.value.top}px`,
  width: `${hoverTip.value.width}px`,
  maxWidth: `${props.highlightHoverMaxWidth}px`,
  maxHeight: `${props.highlightHoverMaxHeight}px`,
  fontSize: `${props.highlightHoverFontSize}px`,
}))

const emit = defineEmits<{
  download: []
  'text-scroll': [percent: number]
  'hover-highlight': [id: string | null]
  'select-highlight': [highlight: LinkedHighlight]
  'pdf-active-page': [page: number]
  'search-jump': [page: number, lineNumber: number]
  'update:sidePanelOpen': [value: boolean]
  'pdf-loaded': [source: string]
}>()

const slots = useSlots()
const internalSidePanelOpen = ref(false)
const sidePanelOpenValue = computed({
  get: () => props.sidePanelOpen ?? internalSidePanelOpen.value,
  set: (value: boolean) => {
    internalSidePanelOpen.value = value
    emit('update:sidePanelOpen', value)
  }
})
const sidePanelVisible = computed(() => sidePanelOpenValue.value && Boolean(slots['side-panel']))
const toggleSidePanel = () => {
  sidePanelOpenValue.value = !sidePanelOpenValue.value
}

// pdf.js 6.x 需要 cMap / 标准字体 / wasm 三个目录齐备才会启用 worker fetch + wasm 解码
const pdfAssetBaseUrl = computed(() => {
  const base = props.pdfAssetBaseUrl || `${import.meta.env.BASE_URL}`
  return base.endsWith('/') ? base : `${base}/`
})

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
const toolbarMeasureRef = ref<HTMLElement | null>(null)
const splitPaneRef = ref<HTMLElement | null>(null)
const splitPaneResizeObserver = shallowRef<ResizeObserver | null>(null)

// --- PDF Worker 初始化 ---
pdfjsLib.GlobalWorkerOptions.workerSrc = pdfjsWorker

// --- 灯泡（bbox 显示切换）---
const showBbox = ref(true)
const toggleBbox = () => { showBbox.value = !showBbox.value }

// --- 搜索 ---
const displayPageLabel = (page: number) => {
  if (page <= 0) return '-'
  // 搜索结果的 page 为 1 基 PDF 页码，pageLabels 以 graphData 的 page_idx（0 基）为键
  return props.pageLabels?.[page - 1] || String(page)
}

interface SearchResult {
  page: number
  text: string
  lineNumber: number
  highlight?: LinkedHighlight
}
const showSearchPanel = ref(false)
const searchQuery = ref('')
const searchResults = ref<SearchResult[]>([])
const searchActiveIndex = ref(0)
const isSearching = ref(false)
const searchActivePage = ref(0)
const searchActiveLine = ref(0)
const searchPanelRef = ref<HTMLElement | null>(null)
// 原生搜索（未传 searchText 时走 pdf.js 全文）标记扫描件无文本层
const nativeSearchNoTextLayer = ref(false)

// 把 highlights 的 lineStart/lineEnd 映射成 行号→页码
const highlightPageMap = computed(() => {
  const map = new Map<number, number>()
  for (const h of props.highlights) {
    if (h.lineStart != null && h.lineEnd != null && h.lineEnd >= h.lineStart) {
      for (let l = h.lineStart; l <= h.lineEnd; l++) {
        if (!map.has(l)) map.set(l, h.page)
      }
    }
  }
  return map
})

const toggleSearchPanel = () => {
  showSearchPanel.value = !showSearchPanel.value
  if (!showSearchPanel.value) {
    searchResults.value = []
    searchQuery.value = ''
    searchActiveIndex.value = 0
    searchActivePage.value = 0
    searchActiveLine.value = 0
    searchWordRects.value = []
    searchWordLoadToken += 1
    nativeSearchNoTextLayer.value = false
  }
}

const closeSearchPanel = () => {
  showSearchPanel.value = false
  searchResults.value = []
  searchActiveIndex.value = 0
  searchActivePage.value = 0
  searchActiveLine.value = 0
  searchWordRects.value = []
  searchWordLoadToken += 1
  nativeSearchNoTextLayer.value = false
}

const performTextSearch = () => {
  const q = searchQuery.value.trim()
  if (!q) return

  isSearching.value = true
  searchResults.value = []
  searchActiveIndex.value = 0
  searchActivePage.value = 0
  searchActiveLine.value = 0
  searchWordRects.value = []
  searchWordLoadToken += 1
  nativeSearchNoTextLayer.value = false

  // 调用方未提供全文时，回退到 pdf.js 页面文本内容做全文搜索（DredgeAI 等仅传 URL/bbox 的集成）
  if (!props.searchText && !props.textContent) {
    void performNativeTextSearch()
    return
  }

  const lowerQ = q.toLowerCase()
  const sourceText = props.searchText || props.textContent || ''
  const lines = sourceText.split('\n')
  const pageMap = highlightPageMap.value
  const results: SearchResult[] = []
  const highlights = props.highlights || []

  for (let i = 0; i < lines.length && results.length < 200; i++) {
    const line = lines[i]
    const lineLower = line.toLowerCase()
    let pos = lineLower.indexOf(lowerQ)
    while (pos >= 0 && results.length < 200) {
      const start = Math.max(0, pos - 30)
      const end = Math.min(line.length, pos + lowerQ.length + 50)
      // 优先按文本命中 + 行距最近的高亮块定位；无匹配时回退到行号映射
      const target = pickSearchTargetHighlight(q, line, i + 1, highlights)
      const page = target?.page ?? (pageMap.get(i + 1) ?? 0)
      results.push({
        page,
        text: line.slice(start, end),
        lineNumber: i + 1,
        highlight: target ?? undefined,
      })
      pos = lineLower.indexOf(lowerQ, pos + 1)
    }
  }

  searchResults.value = results
  isSearching.value = false
  if (results.length > 0) {
    jumpToSearchResult(results[0], 0)
  }
}

/**
 * 原生全文搜索：未提供 searchText/textContent 时，逐页用 pdf.js 文本内容搜索。
 * 复用 loadPageTextItems（带缓存）与词级高亮链路，扫描件（无文本层）给出提示。
 */
const performNativeTextSearch = async () => {
  const q = searchQuery.value.trim()
  const doc = _pdfDocumentRef.value
  if (!q || !doc) return
  const total = Number(doc.numPages || 0)
  if (!total) {
    isSearching.value = false
    return
  }

  const lowerQ = q.toLowerCase()
  const results: SearchResult[] = []
  let pageItemCount = 0
  let lineCounter = 0

  for (let page = 1; page <= total; page++) {
    let items: PageTextItem[] = []
    try {
      items = await loadPageTextItems(page)
    } catch (error) {
      console.warn('[PDFViewer] Failed to load page text items:', error)
      continue
    }
    pageItemCount += items.length
    for (let i = 0; i < items.length && results.length < 200; i++) {
      const item = items[i]
      if (item.text.toLowerCase().indexOf(lowerQ) < 0) continue
      lineCounter += 1
      // snippet：命中项前后各取相邻文本项拼接上下文（pdf.js 常把文本拆成词/短句项）
      const before = items.slice(Math.max(0, i - 3), i).map(it => it.text).join('')
      const after = items.slice(i + 1, i + 4).map(it => it.text).join('')
      results.push({
        page,
        text: `${before ? `…${before}` : ''}${item.text}${after ? `${after}…` : ''}`,
        lineNumber: lineCounter,
      })
    }
    if (results.length >= 200) break
    // 每 10 页刷新一次列表，边搜边出结果
    if (page % 10 === 0) {
      searchResults.value = [...results]
      await nextTick()
    }
  }

  if (pageItemCount === 0) nativeSearchNoTextLayer.value = true
  searchResults.value = results
  isSearching.value = false
  if (results.length > 0) {
    jumpToSearchResult(results[0], 0)
  }
}

const jumpToSearchResult = (result: SearchResult, idx: number) => {
  hideHighlightTip()
  searchActiveIndex.value = idx
  searchActivePage.value = result.page
  // 黄色高亮框按高亮块自身的解析版行号渲染；右栏滚动仍用显示版行号
  searchActiveLine.value = result.highlight?.lineStart ?? result.lineNumber
  const targetBbox = result.highlight || searchActiveHighlights.value[0]
  if (targetBbox) {
    scroll.scrollToHighlight(targetBbox, 'center')
  } else if (result.page > 0) {
    scroll.scrollToPdfPage(result.page, 'auto')
  }
  void updateSearchWordHighlights(result)
  emit('search-jump', result.page, result.lineNumber)
}

// 当前选中搜索结果对应的黄色高亮框（该页内行范围覆盖命中行的 bbox）
const searchActiveHighlights = computed<LinkedHighlight[]>(() => {
  if (!searchActivePage.value || !searchActiveLine.value) return []
  const page = searchActivePage.value
  const line = searchActiveLine.value
  return props.highlights.filter(h =>
    h.page === page &&
    h.hasRect !== false &&
    h.lineStart != null && h.lineEnd != null &&
    h.lineStart <= line && line <= h.lineEnd
  )
})

// --- bbox 内词级高亮（仅文本层精确匹配；扫描件无文本层时不提供词级框） ---
const pageTextItemsCache = new Map<number, PageTextItem[]>()
const searchWordRects = ref<SearchWordRect[]>([])
let searchWordLoadToken = 0

async function loadPageTextItems(page: number): Promise<PageTextItem[]> {
  const cached = pageTextItemsCache.get(page)
  if (cached) return cached
  const doc = _pdfDocumentRef.value
  if (!doc || page <= 0) return []
  const pdfPage = await doc.getPage(page)
  const textContent = await pdfPage.getTextContent()
  const viewport = pdfPage.getViewport({ scale: 1 })
  const vw = viewport.width || 1
  const vh = viewport.height || 1
  const items: PageTextItem[] = []
  const rawItems = (textContent?.items || []) as Array<{ str?: string; transform?: number[]; width?: number }>
  for (const item of rawItems) {
    const str = item.str || ''
    if (!str || !item.transform) continue
    // 与 pdf.js 文本层一致：合成 viewport 变换得到渲染坐标（y 已翻转为顶部基准）
    const tx = pdfjsLib.Util.transform(viewport.transform, item.transform)
    const fontHeight = Math.hypot(tx[2], tx[3]) || 1
    const angle = Math.atan2(tx[1], tx[0])
    const cosA = Math.cos(angle)
    const sinA = Math.sin(angle)
    const width = Math.max(0, Number(item.width) || 0) * viewport.scale
    const bx = tx[4]
    const by = tx[5]
    const ex = bx + width * cosA
    const ey = by + width * sinA
    // 上缘取 ascent 方向一个字号，下缘取 0.15 字号的下伸
    const ax = bx + fontHeight * sinA
    const ay = by - fontHeight * cosA
    const dx = ex - fontHeight * 0.15 * sinA
    const dy = ey + fontHeight * 0.15 * cosA
    const xs = [bx, ex, ax, dx]
    const ys = [by, ey, ay, dy]
    const left = Math.min(...xs)
    const top = Math.min(...ys)
    const right = Math.max(...xs)
    const bottom = Math.max(...ys)
    items.push({
      text: str,
      left: Math.max(0, Math.min(1, left / vw)),
      top: Math.max(0, Math.min(1, top / vh)),
      width: Math.max(0, Math.min(1, (right - left) / vw)),
      height: Math.max(0, Math.min(1, (bottom - top) / vh)),
    })
  }
  pageTextItemsCache.set(page, items)
  return items
}

async function updateSearchWordHighlights(result: SearchResult) {
  const token = ++searchWordLoadToken
  searchWordRects.value = []
  if (!result.page || !result.lineNumber) return
  const q = searchQuery.value.trim()
  if (!q) return
  try {
    const items = await loadPageTextItems(result.page)
    if (token !== searchWordLoadToken) return
    const rects = matchTextItemRects(items, q)
    if (rects.length) {
      searchWordRects.value = insetWordRects(rects)
      return
    }
  } catch (error) {
    console.warn('[PDFViewer] Failed to load page text items:', error)
  }
}

// 点击外部关闭搜索面板
const onSearchPanelClickOutside = (e: MouseEvent) => {
  if (searchPanelRef.value && !searchPanelRef.value.contains(e.target as Node)) {
    closeSearchPanel()
  }
}

onMounted(() => document.addEventListener('mousedown', onSearchPanelClickOutside))
onBeforeUnmount(() => document.removeEventListener('mousedown', onSearchPanelClickOutside))

// --- Composable: usePdfHeader ---
function usePdfHeader() {
  const compactLevel = ref(0)
  let _toolbarFullWidth = 0
  const headerResizeObserver = shallowRef<ResizeObserver | null>(null)
  const toolbarResizeObserver = shallowRef<ResizeObserver | null>(null)

  function measureToolbarWidth() {
    const measureEl = toolbarMeasureRef.value
    if (measureEl) {
      const w = measureEl.scrollWidth || measureEl.offsetWidth
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

    measureToolbarWidth()
    const full = _toolbarFullWidth
    if (full <= 0) return

    const headerWidth = headerElement.clientWidth
    const titleWidth = titleElement?.scrollWidth || 0
    const rightSection = headerElement.querySelector('.pane-title-right') as HTMLElement | null
    const rightWidth = rightSection?.offsetWidth || 0
    if (headerWidth <= 0) return

    // 优先级：比例 < 放大 < 缩小 < 适应 < 翻页 < 输入框+斜杠 < 总页数 (灯泡永不隐藏)
    const HIDE = [38, 34, 34, 38, 68, 46, 36]
    const MAX_LEVEL = HIDE.length
    const levels: number[] = [full]
    for (let i = 0; i < MAX_LEVEL; i++) levels.push(levels[i] - HIDE[i])

    const availWidth = headerWidth - titleWidth - rightWidth - 24
    let level = MAX_LEVEL
    for (let lvl = 0; lvl <= MAX_LEVEL; lvl++) {
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
      if (toolbarMeasureRef.value) {
        toolbarResizeObserver.value = new ResizeObserver(() => {
          measureToolbarWidth()
          updateHeaderCompactMode()
        })
        toolbarResizeObserver.value.observe(toolbarMeasureRef.value)
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
  renderedPageMetrics: Record<number, RenderedPageMetrics>,
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
  let _cachedRangeKey = ''

  const displayPdfPageCount = computed(() => {
    if (props.pdfPageCount && props.pdfPageCount > 1) return props.pdfPageCount
    if (getLocalPdfPageCount() > 1) return getLocalPdfPageCount()
    return 1
  })

  const activePageRange = computed<number[]>(() => normalizePageRange(props.pdfPageRange, displayPdfPageCount.value))

  function clampPage(value: number) {
    return clampPageToRange(value, activePageRange.value)
  }

  function pageHeightOf(page: number) {
    return pageHeights[page] || estimatedPageHeight.value
  }

  const pageLayout = computed(() => {
    const count = displayPdfPageCount.value
    const rangeKey = activePageRange.value.join(',')
    if (!_layoutDirty && _cachedLayout && count === _cachedPageCount && estimatedPageHeight.value === _cachedEstHeight && rangeKey === _cachedRangeKey) {
      return _cachedLayout
    }
    const topByPage: number[] = []
    let cursor = VERTICAL_PADDING
    const pages = activePageRange.value
    for (const page of pages) {
      topByPage[page] = cursor
      const ph = pageHeights[page]
      cursor += (ph > 0) ? ph : estimatedPageHeight.value
      if (page !== pages[pages.length - 1]) cursor += PAGE_GAP
    }
    _cachedLayout = { topByPage, totalHeight: Math.max(1, cursor + VERTICAL_PADDING) }
    _cachedPageCount = count
    _cachedEstHeight = estimatedPageHeight.value
    _cachedRangeKey = rangeKey
    _layoutDirty = false
    return _cachedLayout
  })

  function invalidateLayout() { _layoutDirty = true }

  /** 用 pdf.js 预取的真实页高种入布局：topByPage 从头精确，跳页/bbox 定位不依赖估算收敛。 */
  function seedRealPageHeights(rawHeights: number[], scale: number) {
    const seeded = computeSeededPageHeights(rawHeights, scale)
    if (!Object.keys(seeded.pageHeights).length) return
    for (const key of Object.keys(pageHeights)) delete pageHeights[Number(key)]
    for (const [page, height] of Object.entries(seeded.pageHeights)) {
      pageHeights[Number(page)] = height
    }
    if (seeded.estimated > 0) estimatedPageHeight.value = seeded.estimated
    invalidateLayout()
    scheduleRenderedPageRangeUpdate()
  }

  function updateRenderedPageRange() {
    const container = pdfScrollRef.value
    const layout = pageLayout.value
    virtualContentHeight.value = layout.totalHeight
    const pages = activePageRange.value
    const firstPage = pages[0]
    const lastPage = pages[pages.length - 1]
    if (!container || !props.isPdf) {
      renderedPageRange.start = firstPage
      renderedPageRange.end = lastPage
      return
    }
    if (pages.length <= 1) { renderedPageRange.start = firstPage; renderedPageRange.end = firstPage; return }
    const viewportTop = container.scrollTop
    const viewportBottom = viewportTop + container.clientHeight
    let firstVisibleIndex = -1
    let lastVisibleIndex = -1
    for (const page of pages) {
      const pageTop = layout.topByPage[page] || 0
      const pageBottom = pageTop + pageHeightOf(page) + PAGE_GAP
      const intersectsViewport = pageBottom >= viewportTop && pageTop <= viewportBottom
      if (intersectsViewport) {
        if (firstVisibleIndex === -1) firstVisibleIndex = page
        lastVisibleIndex = page
      }
    }
    if (firstVisibleIndex === -1 || lastVisibleIndex === -1) {
      let closestPage = firstPage
      let minDiff = Number.POSITIVE_INFINITY
      for (const page of pages) {
        const diff = Math.abs((layout.topByPage[page] || 0) - viewportTop)
        if (diff < minDiff) { minDiff = diff; closestPage = page }
      }
      renderedPageRange.start = Math.max(firstPage, closestPage - RENDER_BUFFER)
      renderedPageRange.end = Math.min(lastPage, closestPage + RENDER_BUFFER)
      return
    }
    renderedPageRange.start = Math.max(firstPage, firstVisibleIndex - RENDER_BUFFER)
    renderedPageRange.end = Math.min(lastPage, lastVisibleIndex + RENDER_BUFFER)
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
    const viewportCenter = scrollTop + (clientHeight / 2)
    let bestPage = activePageRange.value[0]
    let minDistance = Number.POSITIVE_INFINITY
    const layout = pageLayout.value
    for (const page of activePageRange.value) {
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
    // 纵向页面窄于视口时，复位横向滚动，保持与视口中轴线一致
    const pageMetrics = renderedPageMetrics[activePdfPage.value]
    if (target.scrollLeft > 0 && pageMetrics?.width && target.clientWidth > 0 && pageMetrics.width <= target.clientWidth) {
      target.scrollLeft = 0
    }
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
    scheduleRenderedPageRangeUpdate()
    pdfScrollRef.value.scrollTo({ top: targetTop, left: 0, behavior })
  }

  function goPrevPage() { scrollToPdfPage(activePdfPage.value - 1, 'smooth') }
  function goNextPage() { scrollToPdfPage(activePdfPage.value + 1, 'smooth') }
  function onPageInputChange(v: any) { const p = Number(v); if (Number.isFinite(p)) scrollToPdfPage(p, 'smooth') }

  // 聚焦到指定高亮块：按 bbox 位置计算滚动目标，而不是整页对齐顶部。
  // align='quarter' 保持既有行为（仅视口外滚动、落在视口上部 1/4）；
  // align='center' 用于搜索跳转：bbox 纵向居中于视口，且已在视口内也会重新居中。
  // 只提供"滚动能力"，何时调用由调用方决定，便于组件跨项目复用。
  function scrollToHighlight(highlight: LinkedHighlight, align: 'quarter' | 'center' = 'quarter') {
    if (!props.isPdf || !pdfScrollRef.value) return
    const page = clampPage(highlight?.page ?? 0)
    if (!highlight || !highlight.hasRect) {
      scrollToPdfPage(page)
      return
    }
    // 目标页尚未渲染/测量：先跳到该页，渲染后按真实几何再次精确定位（一次点击完成两步）
    if (!(pageHeights[page] > 0)) {
      scrollToPdfPage(page)
      waitForPageMeasured(page, () => scrollToHighlight(highlight, align))
      return
    }
    const layout = pageLayout.value
    const pageTop = layout.topByPage[page] || 0
    const pageHeight = pageHeightOf(page)
    const topRatio = Math.max(0, Math.min(1, Number(highlight.top) || 0))
    const heightRatio = Math.max(0, Math.min(1, Number(highlight.height) || 0))
    const bboxTop = pageTop + topRatio * pageHeight
    const bboxBottom = pageTop + Math.min(1, topRatio + heightRatio) * pageHeight
    const bboxHeight = Math.max(0, bboxBottom - bboxTop)

    const container = pdfScrollRef.value
    // 纵向页面窄于视口时，先复位横向滚动，保证以视口中轴线为准
    const pageMetrics = renderedPageMetrics[page]
    if (pageMetrics?.width && container.clientWidth > 0 && pageMetrics.width <= container.clientWidth) {
      container.scrollLeft = 0
    }
    const viewportTop = container.scrollTop
    const viewportBottom = viewportTop + container.clientHeight
    // 能被点击说明 bbox 已在视口内（哪怕部分可见），保持原位不滚动
    if (align !== 'center' && bboxBottom >= viewportTop && bboxTop <= viewportBottom) return

    const viewportHeight = Math.max(1, container.clientHeight)
    // bbox 不在视口内：滚动到让 bbox 落在视口上部约 1/4 处，既有上下文又不贴顶；
    // 搜索跳转：bbox 纵向居中于视口
    const targetTop = align === 'center'
      ? bboxTop - Math.max(0, (viewportHeight - bboxHeight) / 2)
      : Math.max(0, bboxTop - viewportHeight * 0.25)
    const maxTop = Math.max(0, container.scrollHeight - container.clientHeight)
    applyingExternalPdfScroll.value = true
    activePdfPage.value = page
    scheduleRenderedPageRangeUpdate()
    container.scrollTo({ top: Math.max(0, Math.min(targetTop, maxTop)), behavior: 'auto' })
    requestAnimationFrame(() => { applyingExternalPdfScroll.value = false })
  }

  /** 目标页渲染并测量完成后再回调（最多约 3s 兜底）。 */
  function waitForPageMeasured(page: number, done: () => void) {
    let tries = 0
    const timer = window.setInterval(() => {
      tries += 1
      if (pageHeights[page] > 0 || tries > 60) {
        window.clearInterval(timer)
        done()
      }
    }, 50)
  }

  return {
    pageHeights, estimatedPageHeight, renderedPageRange, activePdfPage,
    virtualContentHeight, applyingExternalPdfScroll, isPdfUserScrolling,
    lastEmittedPdfPercent, displayPdfPageCount, activePageRange, pageHeightOf,
    pageLayout, updateRenderedPageRange, scheduleRenderedPageRangeUpdate,
    scrollToPdfPage, scrollToHighlight, onPdfScroll, goPrevPage, goNextPage, onPageInputChange,
    invalidateLayout, seedRealPageHeights,
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
      const renderTask = pdfPage.render({ canvas, viewport, intent: 'print' })
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
    onDocumentLoaded?: () => void
  },
  scroll: {
    scheduleRenderedPageRangeUpdate: () => void
    displayPdfPageCount: ComputedRef<number>
    estimatedPageHeight: Ref<number>
    seedRealPageHeights: (rawHeights: number[], scale: number) => void
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
  /** 流式加载被 abort 的源：本会话内直接走全量加载，避免每次重复失败尝试。 */
  const failedStreamSources = new Set<string>()

  function destroyPdf() {
    pdfLoadingTask.value?.destroy?.()
    pdfLoadingTask.value = null
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
    // 用 pdf.js 预取全部页真实高度种入布局，保证跳页/bbox 定位一次到位（不阻塞首屏渲染）
    void (async () => {
      try {
        const heights: number[] = []
        const count = localPdfPageCount.value
        for (let p = 1; p <= count; p++) {
          const page = await nextDocument.getPage(p)
          heights.push(page.getViewport({ scale: 1 }).height)
        }
        if (heights.length) {
          scroll.seedRealPageHeights(heights, zoom.pdfScale.value || 1)
        }
      } catch (e) {
        console.warn('[PDFViewer] Failed to pre-fetch page dimensions:', e)
      }
    })()
    await nextTick()
    render.renderVisiblePages()
    requestAnimationFrame(() => {
      zoom.scheduleFitToWindowScale()
      zoom.isScaleTransitioning.value = false
      zoom.hasAppliedInitialFit.value = true
    })
    shared.onDocumentLoaded?.()
  }

  async function loadPdfDocument(source: string) {
    if (!source || !props.isPdf) return
    useNativePdfPreview.value = false
    isPdfLoading.value = true
    pdfLoadingProgress.value = 0
    const nextToken = pdfLoadToken + 1
    pdfLoadToken = nextToken
    destroyPdf()
    render.clearPdfRenderState()

    if (!failedStreamSources.has(source)) {
      try {
        const loadingTask = pdfjsLib.getDocument({
          url: source,
          disableRange: false, disableStream: false, disableAutoFetch: false,
          rangeChunkSize: 65536 * 8,
          cMapUrl: `${pdfAssetBaseUrl.value}cmaps/`,
          standardFontDataUrl: `${pdfAssetBaseUrl.value}standard_fonts/`,
          wasmUrl: `${pdfAssetBaseUrl.value}wasm/`,
        })

        loadingTask.onProgress = ({ loaded, total }: { loaded: number; total: number }) => {
          if (total > 0) pdfLoadingProgress.value = Math.min(99, Math.round((loaded / total) * 100))
        }

        pdfLoadingTask.value = loadingTask
        const nextDocument = await loadingTask.promise
        if (pdfLoadToken !== nextToken) { void loadingTask.destroy(); return }
        await onPdfDocumentLoaded(nextDocument)
        return
      } catch (error) {
        // 加载被中断属预期竞态（文档切换/环境断流），静默降级并缓存，下次直接全量加载
        if (error instanceof Error && error.message === 'Loading aborted') {
          failedStreamSources.add(source)
        } else {
          console.warn('[PDFViewer] Stream load failed, trying full array buffer load:', error)
        }
        if (pdfLoadToken !== nextToken) return
        destroyPdf()
      }
    }

    try {
      const response = await fetch(source)
      if (!response.ok) throw new Error(`Failed to fetch PDF (${response.status})`)
      const pdfBinary = new Uint8Array(await response.arrayBuffer())
      if (pdfLoadToken !== nextToken) return
      const loadingTask = pdfjsLib.getDocument({
        data: pdfBinary, disableRange: true, disableStream: true, disableAutoFetch: true,
        cMapUrl: `${pdfAssetBaseUrl.value}cmaps/`,
        standardFontDataUrl: `${pdfAssetBaseUrl.value}standard_fonts/`,
        wasmUrl: `${pdfAssetBaseUrl.value}wasm/`,
      })
      pdfLoadingTask.value = loadingTask
      const nextDocument = await loadingTask.promise
      if (pdfLoadToken !== nextToken) { void loadingTask.destroy(); return }
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
    destroyPdf()
  }

  return { useNativePdfPreview, isPdfLoading, pdfLoadingProgress, localPdfPageCount, pdfDocument, loadPdfDocument, destroyPdf, onBeforeUnmount }
}

// --- 组合 Composable 函数 ---
const _pageLastRenderedScale = new Map<number, number>()
const _localPdfPageCount = ref(0)
const _useNativePdfPreview = ref(false)
const _pdfDocumentRef = shallowRef<any>(null)
const _renderedPageMetrics = reactive<Record<number, RenderedPageMetrics>>({})

const header = usePdfHeader()
const scroll = usePdfVirtualScroll(emit, () => _localPdfPageCount.value, _renderedPageMetrics)
const zoom = usePdfZoom(scroll, _renderedPageMetrics)
const measurement = usePdfMeasurement(scroll, zoom, _pageLastRenderedScale, _renderedPageMetrics)
const render = usePdfRendering(_pdfDocumentRef, zoom, scroll, measurement, _pageLastRenderedScale)
const doc = usePdfDocument(
  {
    pdfDocumentRef: _pdfDocumentRef,
    localPdfPageCount: _localPdfPageCount,
    useNativePdfPreview: _useNativePdfPreview,
    isPdfLoading: ref(false),
    pdfLoadingProgress: ref(0),
    onDocumentLoaded: () => emit('pdf-loaded', props.fileUrl || props.pdfViewerUrl.split('#')[0] || props.pdfViewerUrl),
  },
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
const hasPrevPdfPage = computed(() => {
  const pages = scroll.activePageRange.value
  return pages.length > 1 && activePdfPage.value > pages[0]
})
const hasNextPdfPage = computed(() => {
  const pages = scroll.activePageRange.value
  return pages.length > 1 && activePdfPage.value < pages[pages.length - 1]
})
watch(() => props.pdfPageRange, () => {
  scroll.invalidateLayout()
  scroll.scheduleRenderedPageRangeUpdate()
  scroll.scrollToPdfPage(activePdfPage.value, 'auto')
})
const isFitToWindowMode = zoom.isFitToWindowMode
const useNativePdfPreview = doc.useNativePdfPreview
const virtualContentHeight = scroll.virtualContentHeight
// docx/xlsx/xls 用本地轻量组件渲染；doc/ppt/pptx 不支持本地预览，转换完成后切到 PDF
const isLocalOffice = computed(() => {
  const m = props.fileUrl.match(/path=([^&#]*)/)
  const decoded = m ? decodeURIComponent(m[1]) : props.fileUrl
  const ext = (decoded.split('.').pop() || '').toLowerCase()
  return ['docx', 'xls', 'xlsx'].includes(ext)
})
const minPdfScale = MIN_SCALE
const maxPdfScale = MAX_SCALE
const pdfScale = zoom.pdfScale
watch(pdfScale, hideHighlightTip)
const pageInputWidth = computed(() => {
  const w = Math.max(32, String(activePdfPage.value).length * 10 + 12)
  return w
})

const themeClass = computed(() => {
  if (props.theme === 'dark') return 'dark-mode'
  if (props.theme === 'light') return 'light-mode'
  return ''
})

const shouldShowPdfHighlights = computed(() => {
  if (!props.isPdf || doc.useNativePdfPreview.value) return false
  if (!showBbox.value) return false
  return true
})

const showNonPdfLoading = computed(() => {
  // docx/xls/xlsx 有本地预览组件，转换期间直接渲染 OfficePreview；
  // 转换完成出 render_pdf 后由 isPdf 切到 PDF viewer（分页正确）
  if (props.isPdf || isLocalOffice.value) return false
  const status = props.node.status
  return status === 'processing' || status === 'pending' || status === 'queued'
})

const PARSE_STAGE_LABELS: Record<string, string> = {
  source_prep: '源文件准备', convert: '格式转换', raw_parse: 'MinerU 解析',
  popo: 'PoPo 强化', structure: '结构化',
  fts: '全文索引（FTS5）', vectors: '向量索引', graph: '知识图谱',
  preparing: '准备文件', converting: '格式转换', popo_normalize: 'PoPo 强化',
  indexing: '构建索引', completed: '解析完成',
  queued: '排队中', processing: '解析中', pending: '等待中',
  failed: '解析失败', cancelled: '已取消', cancel: '已取消',
}
const PARSE_STAGE_KEYS = ['source_prep', 'convert', 'raw_parse', 'popo', 'structure', 'fts', 'vectors', 'graph']

const parseProgressLabel = computed(() => {
  const stage = String(props.node.parseStage || '').toLowerCase()
  return PARSE_STAGE_LABELS[stage] || stage || '—'
})

const parseProgressIndex = computed(() => {
  const stage = String(props.node.parseStage || '').toLowerCase()
  const idx = PARSE_STAGE_KEYS.indexOf(stage)
  return idx >= 0 ? idx : -1
})

const parseProgressCount = computed(() => {
  const idx = parseProgressIndex.value
  return idx >= 0 ? `${idx + 1}/${PARSE_STAGE_KEYS.length}` : '—'
})

// 解析过程栏标题：始终左对齐的「(序号/总数)阶段标题」，如 （3/8）MinerU 解析
const parseProgressHeader = computed(() => {
  const count = parseProgressCount.value
  const label = parseProgressLabel.value
  if (!count || count === '—') return label
  return `（${count}）${label}`
})

void [pdfToolbarRef, headerTitleRef, headerMainRef, isPdfLoading, pdfLoadingProgress, zoomPercentLabel, normalizedPdfSource, nativePdfViewerUrl, shouldShowPdfHighlights, showNonPdfLoading, parseProgressLabel, parseProgressCount, parseProgressHeader, hasAppliedInitialFit, isScaleTransitioning, maxPageWidth, activePdfPage, compactLevel, displayPdfPageCount, virtualContentHeight, minPdfScale, maxPdfScale, pdfScale, isFitToWindowMode, useNativePdfPreview, pageInputWidth]

const visiblePdfPages = computed<VirtualPageMeta[]>(() => {
  const pages: VirtualPageMeta[] = []
  const { start, end } = scroll.renderedPageRange
  const layout = scroll.pageLayout.value
  for (let page = start; page <= end; page += 1) {
    pages.push({
      page,
      top: layout.topByPage[page] || 24,
      height: scroll.pageHeightOf(page),
      width: _renderedPageMetrics[page]?.width || 0,
    })
  }
  return pages
})

const getPdfPageStyle = (pageMeta: VirtualPageMeta) => {
  const containerWidth = pdfScrollRef.value?.clientWidth || 0
  const pageWidth = pageMeta.width || 0
  if (containerWidth > 0 && pageWidth > 0) {
    return {
      top: `${pageMeta.top}px`,
      left: `${Math.max(0, (containerWidth - pageWidth) / 2)}px`,
      transform: 'none',
    }
  }
  return { top: `${pageMeta.top}px` }
}
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
    'table-header': '表头', 'equation-number': '公式编号',
    title: '标题', paragraph: '正文', list: '列表',
    equation_interline: '公式', text: '文本'
  }
  return labelMap[normalizedType] || normalizedType.replace(/[_-]+/g, ' ').trim()
}
const highlightsByPage = computed(() => {
  if (!props.isPdf) return new Map<number, LinkedHighlight[]>()
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
  if (!props.isPdf) return []
  return highlightsByPage.value.get(page) || []
}

// --- Watchers ---
// 记录最后一次由本组件滚动上报的页号，用于识别 currentPdfPage 的“回声”并跳过吸附
let lastReportedPdfPage = 0

watch([normalizedPdfSource, () => props.isPdf], async ([source, isPdf]) => {
  if (!isPdf || !source) return
  measurement.clearAllPageData()
  zoom.intrinsicPdfPageWidth.value = null
  zoom.pdfScale.value = 1
  zoom.isFitToWindowMode.value = true
  zoom.isScaleTransitioning.value = true
  zoom.hasAppliedInitialFit.value = false
  scroll.activePdfPage.value = scroll.activePageRange.value[0] || 1
  lastReportedPdfPage = 0
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
  // 自身滚动上报后被父级原样回传的页号，不触发吸附跳页
  if (newPage === lastReportedPdfPage) return
  scroll.applyingExternalPdfScroll.value = true
  scroll.scrollToPdfPage(newPage, 'auto')
  requestAnimationFrame(() => { scroll.applyingExternalPdfScroll.value = false })
})

// 溯源定位：外部切换 activeHighlightId 时把对应高亮 bbox 纵向居中（默认关闭，避免影响既有联动行为）；
// 与搜索跳转共用 scrollToHighlight('center')，同一高亮去重避免重复跳动。
let lastCenteredHighlightKey = ''
watch([() => props.centerActiveHighlight, () => props.activeHighlightId, () => props.highlights], () => {
  if (!props.centerActiveHighlight || !props.activeHighlightId) return
  const active = props.highlights.find(
    (h) => h.itemId === props.activeHighlightId || h.id === props.activeHighlightId,
  )
  if (!active) return
  const key = `${active.itemId}|${active.page}|${active.top}`
  if (key === lastCenteredHighlightKey) return
  lastCenteredHighlightKey = key
  scroll.scrollToHighlight(active, 'center')
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

// --- 暴露方法给模板 ---
const goPrevPage = () => scroll.goPrevPage()
const goNextPage = () => scroll.goNextPage()
const onPageInputChange = (v: any) => scroll.onPageInputChange(v)
const scrollToHighlight = (highlight: LinkedHighlight, align?: 'quarter' | 'center') => {
  hideHighlightTip()
  return scroll.scrollToHighlight(highlight, align)
}
defineExpose({ scrollToHighlight })
const zoomIn = () => zoom.zoomIn()
const zoomOut = () => zoom.zoomOut()
const resetZoom = () => zoom.resetZoom()
const onPdfScroll = (e: Event) => {
  if (!doc.useNativePdfPreview.value) {
    scroll.onPdfScroll(e)
    lastReportedPdfPage = scroll.activePdfPage.value
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

function setupSplitPaneResizeObserver() {
  if (typeof ResizeObserver === 'undefined' || !splitPaneRef.value) return
  splitPaneResizeObserver.value?.disconnect()
  splitPaneResizeObserver.value = new ResizeObserver(() => {
    if (zoom.isFitToWindowMode.value) zoom.scheduleFitToWindowScale()
  })
  splitPaneResizeObserver.value.observe(splitPaneRef.value)
}

onMounted(() => {
  header.setup()
  zoom.watchIntrinsicWidth()
  zoom.watchFitMode()
  setupSplitPaneResizeObserver()
  nextTick(() => {
    scroll.scheduleRenderedPageRangeUpdate()
    if (zoom.isFitToWindowMode.value) zoom.scheduleFitToWindowScale()
  })
})

onBeforeUnmount(() => {
  doc.onBeforeUnmount()
  header.teardown()
  splitPaneResizeObserver.value?.disconnect()
})
</script>

<style lang="less" scoped>
.pdf-viewer-shell {
  position: relative;
  flex: 1;
  min-width: 0;
  min-height: 0;
  height: 100%;
  display: flex;
  flex-direction: row;
  align-items: stretch;
  border-radius: 8px;
  overflow: hidden;
  --dp-bg: var(--dp-bg-override, var(--dp-bg, #f3f5f8));
  --dp-pane-bg: var(--dp-pane-bg-override, var(--dp-pane-bg, #fff));
  --dp-pane-border: var(--dp-pane-border-override, var(--dp-pane-border, #e8edf4));
  --dp-title-bg: var(--dp-title-bg-override, var(--dp-title-bg, #fff));
  --dp-title-border: var(--dp-title-border-override, var(--dp-title-border, #edf1f7));
  --dp-title-text: var(--dp-title-text-override, var(--dp-title-text, #595959));
  --dp-title-strong: var(--dp-title-strong-override, var(--dp-title-strong, #4f5d7a));
  --dp-sub-text: var(--dp-sub-text-override, var(--dp-sub-text, #8c8c8c));
  --dp-progress-bg: var(--dp-progress-bg-override, var(--dp-progress-bg, #fcfdff));
  --dp-content-bg: var(--dp-content-bg-override, var(--dp-content-bg, #fff));
  --dp-scroll-thumb: var(--dp-scroll-thumb-override, var(--dp-scroll-thumb, rgba(15,23,42,0.22)));
  --dp-empty-overlay: var(--dp-empty-overlay-override, var(--dp-empty-overlay, rgba(255,255,255,0.92)));
  --dp-empty-text: var(--dp-empty-text-override, var(--dp-empty-text, rgba(0,0,0,0.45)));
  --dp-segment-bg: var(--dp-segment-bg-override, var(--dp-segment-bg, #dfe5f2));
  --dp-segment-border: var(--dp-segment-border-override, var(--dp-segment-border, #cdd6e7));
  --dp-segment-selected-bg: var(--dp-segment-selected-bg-override, var(--dp-segment-selected-bg, #fff));
  --dp-segment-selected-text: var(--dp-segment-selected-text-override, var(--dp-segment-selected-text, #1f2937));
  --dp-segment-shared-bg: var(--dp-segment-shared-bg-override, var(--dp-segment-shared-bg, linear-gradient(90deg, #52c41a 0%, #389e0d 100%)));
  --dp-segment-shared-border: var(--dp-segment-shared-border-override, var(--dp-segment-shared-border, #389e0d));
  --dp-math-bg: var(--dp-math-bg-override, var(--dp-math-bg, #eef3ff));
  --dp-math-color: var(--dp-math-color-override, var(--dp-math-color, #1d3a8a));
  --dp-bg-tertiary: var(--dp-bg-tertiary-override, var(--dp-bg-tertiary, #eef1f5));
}

.pdf-viewer-shell.has-side-panel {
  border: 1px solid var(--dp-pane-border);
}

.pdf-viewer-shell.has-side-panel .split-pane {
  border: none;
  border-radius: 0;
}

.pdf-viewer-side-panel {
  flex: 0 0 auto;
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--dp-pane-bg);
  border-left: 1px solid var(--dp-pane-border);
  opacity: 0;
  visibility: hidden;
  pointer-events: none;
  transition: width 0.2s ease, opacity 0.2s ease, border-color 0.2s ease;
}

.pdf-viewer-side-panel-open {
  opacity: 1;
  visibility: visible;
  pointer-events: auto;
}

.split-pane {
  position: relative;
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
  border: 1px solid var(--dp-pane-border);
  border-radius: 8px;
  background: var(--dp-pane-bg);
  overflow: hidden;
  /* Light mode defaults：宿主可通过 --dp-*-override 覆盖 */
  --dp-bg: var(--dp-bg-override, var(--dp-bg, #f3f5f8));
  --dp-pane-bg: var(--dp-pane-bg-override, var(--dp-pane-bg, #fff));
  --dp-pane-border: var(--dp-pane-border-override, var(--dp-pane-border, #e8edf4));
  --dp-title-bg: var(--dp-title-bg-override, var(--dp-title-bg, #fff));
  --dp-title-border: var(--dp-title-border-override, var(--dp-title-border, #edf1f7));
  --dp-title-text: var(--dp-title-text-override, var(--dp-title-text, #595959));
  --dp-title-strong: var(--dp-title-strong-override, var(--dp-title-strong, #4f5d7a));
  --dp-sub-text: var(--dp-sub-text-override, var(--dp-sub-text, #8c8c8c));
  --dp-progress-bg: var(--dp-progress-bg-override, var(--dp-progress-bg, #fcfdff));
  --dp-content-bg: var(--dp-content-bg-override, var(--dp-content-bg, #fff));
  --dp-scroll-thumb: var(--dp-scroll-thumb-override, var(--dp-scroll-thumb, rgba(15,23,42,0.22)));
  --dp-empty-overlay: var(--dp-empty-overlay-override, var(--dp-empty-overlay, rgba(255,255,255,0.92)));
  --dp-empty-text: var(--dp-empty-text-override, var(--dp-empty-text, rgba(0,0,0,0.45)));
  --dp-segment-bg: var(--dp-segment-bg-override, var(--dp-segment-bg, #dfe5f2));
  --dp-segment-border: var(--dp-segment-border-override, var(--dp-segment-border, #cdd6e7));
  --dp-segment-selected-bg: var(--dp-segment-selected-bg-override, var(--dp-segment-selected-bg, #fff));
  --dp-segment-selected-text: var(--dp-segment-selected-text-override, var(--dp-segment-selected-text, #1f2937));
  --dp-math-bg: var(--dp-math-bg-override, var(--dp-math-bg, #eef3ff));
  --dp-math-color: var(--dp-math-color-override, var(--dp-math-color, #1d3a8a));
  --dp-bg-tertiary: var(--dp-bg-tertiary-override, var(--dp-bg-tertiary, #eef1f5));
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
  gap: 8px;
  position: relative;
  overflow: hidden;
}

.pane-title-main {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  flex: 0 1 auto;
}

.pane-title-right {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 2px;
}

/* 隐形测量镜像：不占布局、不可见，但保持自然宽度供 scrollWidth 测量 */
.toolbar-measure {
  position: absolute;
  top: 0;
  left: 0;
  visibility: hidden;
  pointer-events: none;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  white-space: nowrap;
  z-index: -1;
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

.pane-title-doc-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--dp-title-strong);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 320px;
}

/* --- 搜索面板 --- */
.search-panel {
  position: absolute;
  top: 40px;
  right: 0;
  z-index: 100;
  width: 300px;
  max-height: 320px;
  opacity: 0.7;
  backdrop-filter: blur(4px);
  background: var(--dp-pane-bg);
  border: 1px solid rgba(0, 0, 0, 0.32);
  border-radius: 6px;
  box-shadow: 0 10px 32px rgba(0, 0, 0, 0.25), 0 2px 10px rgba(0, 0, 0, 0.14);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.search-panel-input-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  border-bottom: 1px solid var(--dp-pane-border);
}

.search-input {
  flex: 1;
}

.search-results {
  overflow-y: auto;
  max-height: 260px;
}

.search-results-count {
  padding: 6px 12px;
  font-size: 11px;
  color: var(--dp-sub-text);
  border-bottom: 1px solid var(--dp-pane-border);
}

.search-result-item {
  display: flex;
  gap: 10px;
  padding: 6px 12px;
  cursor: pointer;
  border-bottom: 1px solid var(--dp-pane-border);
  transition: background 0.15s;

  &:last-child { border-bottom: none; }

  &:hover {
    background: var(--dp-bg);
  }

  &.active {
    background: rgba(22, 119, 255, 0.10);
    box-shadow: inset 2px 0 0 rgba(22, 119, 255, 0.6);
  }
}

.search-result-page {
  flex-shrink: 0;
  font-size: 11px;
  color: var(--dp-title-strong);
  font-weight: 600;
  min-width: 28px;
  padding-top: 1px;
}

.search-result-text {
  font-size: 11px;
  color: var(--dp-title-text);
  line-height: 1.5;
  word-break: break-all;

  mark {
    background: #ffe58f;
    color: #1f2937;
    padding: 0 1px;
    border-radius: 2px;
  }
}

.search-no-results {
  padding: 24px;
  text-align: center;
  font-size: 13px;
  color: var(--dp-sub-text);
}

.search-searching {
  padding: 24px;
  text-align: center;
  font-size: 13px;
  color: var(--dp-title-text);
}

.parse-state-tag {
  margin-inline-start: 2px;
}

.pane-actions-pdf {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  position: relative;
  z-index: 1;
  flex: 1;
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
  width: 100%;
}

.parse-progress-content {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}

.parse-progress-label {
  font-size: 12px;
  color: var(--dp-title-text);
  white-space: nowrap;
  text-align: left;
  flex-shrink: 0;
}

.parse-progress-step {
  font-size: 12px;
  color: var(--dp-sub-text, #666);
  flex: 1;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.parse-error-text {
  margin-top: 4px;
  font-size: 12px;
  color: var(--dp-error, #ff4d4f);
  white-space: pre-wrap;
  word-break: break-all;
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

/* Office 预览与 PDF 预览同布局：占满面板、内部滚动，不浮在面板上方 */
.office-preview {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  position: relative;
  overflow: hidden;
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
  background: var(--dp-pane-bg, rgba(255, 255, 255, 0.92));
  backdrop-filter: blur(2px);
}

.pdf-loading-text {
  font-size: 14px;
  color: var(--dp-title-text, #595959);
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

/* 缩小按钮与前组（翻页）之间留出 8px 间距 */
.pdf-tool-zoomout-gap {
  margin-left: 4px;
}

.pdf-tool-btn-active {
  color: #1677ff;
  border-color: #1677ff;
}

.pdf-page-input {
  min-width: 0;
}
.pdf-page-input :deep(.ant-input-number-input) {
  padding-inline: 4px;
  text-align: center;
  font-size: 12px;
}

.pdf-toolbar-text {
  font-size: 12px;
  color: var(--dp-title-text);
  min-width: 34px;
  text-align: center;
}

.pdf-toolbar-text-slim {
  min-width: 0;
  padding-inline: 1px;
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
  border-color: rgba(250, 173, 20, 0.95);
  background: rgba(250, 173, 20, 0.30);
  z-index: 10;
}

/* hover 当前框：加深橙色 */
.pdf-highlight-box.hover-primary {
  border-color: rgba(212, 107, 8, 0.98);
  background: rgba(212, 107, 8, 0.55);
  z-index: 10;
}

/* hover 同节点其它 bbox：浅橙色联动 */
.pdf-highlight-box.hover-linked {
  border-color: rgba(250, 173, 20, 0.70);
  background: rgba(250, 173, 20, 0.22);
  z-index: 9;
}

/* 搜索结果黄色高亮 */
.pdf-search-active-layer {
  pointer-events: none;
  z-index: 12;
}

.pdf-highlight-box.search-active {
  border: 1.5px solid rgba(250, 173, 20, 0.95);
  background: rgba(250, 219, 20, 0.30);
  box-shadow: 0 0 0 1px rgba(250, 173, 20, 0.35);
  animation: searchActivePulse 1.2s ease-in-out infinite;
}

@keyframes searchActivePulse {
  0%, 100% { box-shadow: 0 0 0 1px rgba(250, 173, 20, 0.35); }
  50% { box-shadow: 0 0 0 4px rgba(250, 173, 20, 0.12); }
}

/* 搜索结果词级细高亮 */
.pdf-search-word-layer {
  pointer-events: none;
  z-index: 13;
}

.pdf-highlight-box.search-word {
  border: none;
  background: rgba(250, 173, 20, 0.75);
  border-radius: 2px;
  box-shadow: none;
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
  background: rgba(212, 107, 8, 0.96);
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

.pdf-hover-tip {
  position: absolute;
  z-index: 20;
  pointer-events: none;
  overflow: auto;
  padding: 6px 8px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--dp-title-strong, #4f5d7a);
  background: #fff;
  border: 1px solid var(--dp-pane-border, #e8edf4);
  border-radius: 6px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
  &__match {
    color: #d4380d;
    font-weight: 700;
    background: rgba(255, 77, 79, 0.12);
    border-radius: 2px;
  }
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
  flex-shrink: 0; /* 容器是 flex 列，防止占位高度被压缩，保证整篇可滚动 */
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

/* Dark mode：跟随系统 */
@media (prefers-color-scheme: dark) {
  .pdf-viewer-shell .pdf-hover-tip {
    color: #d9d9d9;
    background: #1f1f1f;
    border-color: #434343;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.5);
  }
  .pdf-viewer-shell {
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
  .search-panel {
    border-color: rgba(255, 255, 255, 0.28);
    box-shadow: 0 10px 32px rgba(0, 0, 0, 0.55), 0 2px 10px rgba(0, 0, 0, 0.35);
  }
}

/* Dark mode：props.theme='dark' 显式指定 */
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
.split-pane.dark-mode .search-panel {
  border-color: rgba(255, 255, 255, 0.28);
}

.pdf-viewer-shell.dark-mode {
  .pdf-hover-tip {
    color: #d9d9d9;
    background: #1f1f1f;
    border-color: #434343;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.5);
  }
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

.pdf-viewer-shell.dark-mode .search-panel {
  border-color: rgba(255, 255, 255, 0.28);
}

/* Light mode：props.theme='light' 显式指定 */
.split-pane.light-mode {
  --dp-bg: var(--dp-bg-override, #f3f5f8);
  --dp-pane-bg: var(--dp-pane-bg-override, #fff);
  --dp-pane-border: var(--dp-pane-border-override, #e8edf4);
  --dp-title-bg: var(--dp-title-bg-override, #fff);
  --dp-title-border: var(--dp-title-border-override, #edf1f7);
  --dp-title-text: var(--dp-title-text-override, #595959);
  --dp-title-strong: var(--dp-title-strong-override, #4f5d7a);
  --dp-sub-text: var(--dp-sub-text-override, #8c8c8c);
  --dp-progress-bg: var(--dp-progress-bg-override, #fcfdff);
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

.pdf-viewer-shell.light-mode {
  --dp-bg: var(--dp-bg-override, #f3f5f8);
  --dp-pane-bg: var(--dp-pane-bg-override, #fff);
  --dp-pane-border: var(--dp-pane-border-override, #e8edf4);
  --dp-title-bg: var(--dp-title-bg-override, #fff);
  --dp-title-border: var(--dp-title-border-override, #edf1f7);
  --dp-title-text: var(--dp-title-text-override, #595959);
  --dp-title-strong: var(--dp-title-strong-override, #4f5d7a);
  --dp-sub-text: var(--dp-sub-text-override, #8c8c8c);
  --dp-progress-bg: var(--dp-progress-bg-override, #fcfdff);
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
