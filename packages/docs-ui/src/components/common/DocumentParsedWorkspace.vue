<template>
  <div class="doc-preview" :class="{ 'dark-mode': darkMode }">
    <div class="preview-content">
      <div class="split-preview">
        <DocumentParsedPaneLeft
          :node="node"
          :activeTab="activeTab"
          :isSharedVisible="isSharedVisible"
          :parseButtonText="parseButtonText"
          :progressPercent="progressPercent"
          :stageText="stageText"
          :isPdf="isPdf"
          :isOffice="isOffice"
          :isImage="isImage"
          :isText="isText"
          :pdfViewerUrl="pdfViewerUrl"
          :officePreviewUrl="officePreviewUrl"
          :fileUrl="fileUrl"
          :textContent="textContent"
          :currentPdfPage="pdfPage"
          :pdfPageCount="inferredPdfPageCount"
          :highlights="linkedHighlights"
          :activeHighlightId="activeLinkedItemId"
          :highlightLinkEnabled="highlightLinkEnabled"
          :showHighlightToggle="showHighlightToggle"
          :textScrollPercent="leftScrollPercent"
          @parse="$emit('parse', node)"
          @toggle-visibility="onVisibilityToggle"
          @download="downloadFile"
          @text-scroll="onLeftTextScrollPercent"
          @hover-highlight="onHoverLinkedItem"
          @select-highlight="onSelectHighlightFromLeft"
          @toggle-highlight-link="toggleHighlightLink"
        />

        <DocumentParsedPaneRight
          v-model:activeTab="activeTab"
          :renderedMarkdown="renderedMarkdown"
          :editableContent="editableContent"
          :isContentDirty="isContentDirty"
          :strategyValue="strategyValue"
          :ingestStatusValue="ingestStatusValue"
          :canIngest="canIngest"
          :ingestButtonText="ingestButtonText"
          :structuredItems="structuredItemsValue"
          :indexSummaryStats="indexSummaryStats"
          :hasParsedContent="hasParsedContent"
          :contentScrollPercent="rightScrollPercent"
          :activeLinkedItemId="activeLinkedItemId"
          :activeLineRange="activeLinkedLineRange"
          @update:editableContent="editableContent = $event"
          @save-markdown="saveMarkdown"
          @cancel-markdown="cancelMarkdownEdit"
          @strategy-change="onStrategyChange"
          @trigger-ingest="triggerIngest"
          @content-scroll="onRightPaneScrollPercent"
          @hover-item="onHoverLinkedItem"
          @select-item="onSelectItemFromRight"
        />
      </div>
    </div>

    <a-modal
      v-model:open="ingestModalVisible"
      :title="ingestStatusValue === 'processing' ? '入库中' : '入库结果'"
      :footer="null"
      :mask-closable="ingestStatusValue !== 'processing'"
      :closable="ingestStatusValue !== 'processing'"
    >
      <div class="ingest-modal-content">
        <a-progress
          :percent="ingestProgressPercent"
          :status="ingestProgressStatus"
          size="default"
        />
        <div class="ingest-stage">{{ ingestStageText }}</div>
        <div v-if="ingestStatusValue === 'completed'" class="ingest-result">
          总条目 {{ structuredTotal }}
        </div>
        <div v-if="ingestStatusValue === 'completed'" class="ingest-result-actions">
          <a-button size="small" @click="openIndexFromIngestModal">查看索引</a-button>
        </div>
      </div>
    </a-modal>

  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import katex from 'katex'
import 'katex/dist/katex.min.css'
import DocumentParsedPaneLeft from './DocumentParsedPaneLeft.vue'
import DocumentParsedPaneRight from './DocumentParsedPaneRight.vue'
import type { SmartTreeNode } from '../../types/tree'
import type { TreeNode } from '../../composables/useKnowledgeTree'
import type { IngestStatus, KnowledgeStrategy, StructuredIndexItem, StructuredStats } from '../../types/knowledge'
import { getFileExtension, mapParseStageText } from '../../utils/knowledge'

interface Props {
  node: TreeNode
  content: string
  structuredItems?: StructuredIndexItem[]
  structuredStats?: StructuredStats
  mineruBlocks?: Record<string, any>[]
  ingestStatus?: IngestStatus
  ingestProgress?: number
  ingestStage?: string
  darkMode?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  darkMode: false
})

const emit = defineEmits<{
  parse: [node: SmartTreeNode]
  'toggle-visible': [node: SmartTreeNode]
  'save-content': [content: string]
  'change-strategy': [strategy: KnowledgeStrategy]
  'query-structured': [itemType?: string, keyword?: string]
  'rebuild-structured': [strategy: KnowledgeStrategy]
}>()

const filePath = computed(() => props.node.filePath || props.node.file_path || '')
const progressPercent = computed(() => Number(props.node.parseProgress || 0))
const ingestStatusValue = computed(() => props.ingestStatus || 'idle')
const ingestProgressPercent = computed(() => Number(props.ingestProgress || 0))
const activeTab = ref<'html' | 'markdown' | 'index'>('html')
const ingestModalVisible = ref(false)
const stageText = computed(() => mapParseStageText(props.node.parseStage, props.node.parseError))
const ingestProgressStatus = computed(() => {
  if (ingestStatusValue.value === 'failed') return 'exception'
  if (ingestStatusValue.value === 'completed') return 'success'
  return 'active'
})
const ingestStageText = computed(() => {
  if (ingestStatusValue.value === 'failed') {
    return props.ingestStage || '入库失败'
  }
  if (ingestStatusValue.value === 'completed') {
    return props.ingestStage || '入库完成'
  }
  return props.ingestStage || '正在入库'
})
const selectedStrategy = ref<KnowledgeStrategy>((props.node.strategy as KnowledgeStrategy) || 'A_structured')
const strategyValue = computed(() => selectedStrategy.value)
const structuredTotal = computed(() => Number(props.structuredStats?.total || 0))
const hasParsedContent = computed(() => Boolean((props.content || '').trim()))
const parseButtonText = computed(() => {
  if (props.node.status === 'completed') return '重新解析'
  if (props.node.status === 'failed') return '重新解析'
  if (props.node.status === 'processing') return '解析中...'
  return '开始解析'
})
const selectedStrategyTotal = computed(() => {
  const stats = selectedStrategyStats.value
  if (!stats) return 0
  return Object.values(stats).reduce((sum, count) => sum + Number(count || 0), 0)
})
const selectedStrategyStats = computed<Record<string, number>>(() => {
  const strategy = strategyValue.value
  return props.structuredStats?.strategies?.[strategy] || {}
})
const indexSummaryStats = computed(() => {
  const stats = selectedStrategyStats.value
  const toCount = (value: unknown) => Number(value || 0)
  return {
    total: selectedStrategyTotal.value,
    formula: toCount(stats.formula),
    table: toCount(stats.table),
    figure: toCount(stats.image) + toCount(stats.figure)
  }
})
const ingestButtonText = computed(() => (selectedStrategyTotal.value > 0 ? '重新入库' : '入库'))
const structuredItemsValue = computed(() => props.structuredItems || [])
const fileExtension = computed(() => getFileExtension(filePath.value))
const isPdf = computed(() => fileExtension.value === 'pdf')
const isOffice = computed(() => ['doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx'].includes(fileExtension.value))
const isImage = computed(() => ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'svg'].includes(fileExtension.value))
const isText = computed(() => ['txt', 'md', 'json', 'xml', 'csv', 'log', 'js', 'ts', 'py', 'java', 'cpp', 'c', 'h', 'html', 'css'].includes(fileExtension.value))

const fileUrl = computed(() => {
  if (!filePath.value) return ''
  if (filePath.value.startsWith('http')) return filePath.value
  return `/api/files?path=${encodeURIComponent(filePath.value)}`
})
const pdfViewerUrl = computed(() => {
  if (!fileUrl.value) return ''
  const hashParams = `toolbar=0&navpanes=0&scrollbar=0&view=FitH&page=${pdfPage.value}`
  if (fileUrl.value.includes('#')) {
    return `${fileUrl.value}&${hashParams}`
  }
  return `${fileUrl.value}#${hashParams}`
})
const officePreviewUrl = computed(() => {
  if (!fileUrl.value) return ''
  return `https://view.officeapps.live.com/op/embed.aspx?src=${encodeURIComponent(window.location.origin + fileUrl.value)}`
})

const textContent = ref('')
const editableContent = ref('')
const savedContent = ref('')
const syncingFromRight = ref(false)
const syncingFromLeft = ref(false)
const leftScrollPercent = ref(0)
const rightScrollPercent = ref(0)
const visibilityMode = ref<'local' | 'shared'>(props.node.visible ? 'shared' : 'local')
const isSharedVisible = computed(() => visibilityMode.value === 'shared')
const canIngest = computed(() => hasParsedContent.value && !isContentDirty.value)
const isContentDirty = computed(() => editableContent.value !== savedContent.value)
const inferredPdfPageCount = computed(() => {
  const candidates = [
    props.node.page_count,
    props.node.pageCount,
    props.node.pages,
    props.node.total_pages,
    props.node.pdf_page_count,
    props.node.meta?.page_count,
    props.node.meta?.pages
  ]
  
  // Also check blocks for max page number
  const maxPageFromBlocks = (props.mineruBlocks || []).reduce((max, block) => {
    const page = resolvePageNumber(block)
    return page && page > max ? page : max
  }, 0)
  if (maxPageFromBlocks > 0) candidates.push(maxPageFromBlocks)

  for (const candidate of candidates) {
    const pageCount = Number(candidate || 0)
    if (Number.isFinite(pageCount) && pageCount > 0) {
      return Math.round(pageCount)
    }
  }
  return 1
})
const pdfPage = ref(1)
const activeLinkedItemId = ref<string | null>(null)
const highlightLinkEnabled = ref(true)
const showHighlightToggle = computed(() => (props.mineruBlocks || []).length > 0)

const loadTextContent = async () => {
  if (!isText.value || !fileUrl.value) return
  try {
    const response = await fetch(fileUrl.value)
    textContent.value = await response.text()
  } catch (error) {
    textContent.value = '加载文件内容失败'
  }
}

const saveMarkdown = () => {
  if (!isContentDirty.value) {
    return
  }
  emit('save-content', editableContent.value)
  savedContent.value = editableContent.value
}

const cancelMarkdownEdit = () => {
  editableContent.value = savedContent.value
}

const triggerIngest = () => {
  if (!canIngest.value) return
  ingestModalVisible.value = true
  emit('rebuild-structured', strategyValue.value)
}

const openIndexFromIngestModal = () => {
  activeTab.value = 'index'
  ingestModalVisible.value = false
}

const onStrategyChange = (value: KnowledgeStrategy) => {
  selectedStrategy.value = value
  emit('change-strategy', value)
}

const onVisibilityToggle = (checked?: boolean | string | number) => {
  const isShared = typeof checked === 'boolean'
    ? checked
    : visibilityMode.value !== 'shared'
  visibilityMode.value = isShared ? 'shared' : 'local'
  emit('toggle-visible', { ...props.node, visible: isShared })
}

const syncPdfPageByPercent = (percent: number) => {
  if (!isPdf.value) return
  const totalPages = inferredPdfPageCount.value
  if (totalPages <= 1) return
  const nextPage = Math.max(1, Math.min(totalPages, Math.round(percent * (totalPages - 1)) + 1))
  if (nextPage !== pdfPage.value) {
    pdfPage.value = nextPage
  }
}

const onRightPaneScrollPercent = (percent: number) => {
  rightScrollPercent.value = percent
  if (syncingFromLeft.value) return
  syncPdfPageByPercent(percent)
  syncingFromRight.value = true
  leftScrollPercent.value = percent
  requestAnimationFrame(() => {
    syncingFromRight.value = false
  })
}

const onLeftTextScrollPercent = (percent: number) => {
  leftScrollPercent.value = percent
  if (syncingFromRight.value) return
  syncingFromLeft.value = true
  rightScrollPercent.value = percent
  syncPdfPageByPercent(percent)
  requestAnimationFrame(() => {
    syncingFromLeft.value = false
  })
}

const downloadFile = () => {
  if (!fileUrl.value) return
  const link = document.createElement('a')
  link.href = fileUrl.value
  link.download = props.node.title
  link.click()
}

interface LinkedHighlight {
  id: string
  itemId: string
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

const readNumeric = (value: unknown): number | null => {
  const numberValue = Number(value)
  if (!Number.isFinite(numberValue)) return null
  return numberValue
}

const readFirstNumeric = (source: Record<string, any>, keys: string[]): number | null => {
  const readByPath = (payload: Record<string, any>, keyPath: string): unknown => {
    if (!keyPath.includes('.')) return payload[keyPath]
    return keyPath.split('.').reduce<unknown>((value, segment) => {
      if (!value || typeof value !== 'object') return undefined
      return (value as Record<string, any>)[segment]
    }, payload)
  }
  for (const key of keys) {
    const value = readNumeric(readByPath(source, key))
    if (value !== null) {
      return value
    }
  }
  return null
}

const extractLineRange = (meta: Record<string, any>) => {
  const start = readFirstNumeric(meta, ['line_start', 'lineStart', 'markdown_line_start', 'md_line_start', 'start_line'])
  const end = readFirstNumeric(meta, ['line_end', 'lineEnd', 'markdown_line_end', 'md_line_end', 'end_line'])
  if (start === null || end === null) {
    return { lineStart: null, lineEnd: null }
  }
  return { lineStart: Math.max(1, Math.round(start)), lineEnd: Math.max(1, Math.round(end)) }
}

interface PageDimension {
  width: number
  height: number
}

const resolvePageNumber = (meta: Record<string, any>): number | null => {
  const page = readFirstNumeric(meta, ['page', 'page_no', 'pageNo', 'position.page'])
  if (page !== null && page > 0) return Math.max(1, Math.round(page))
  const pageIndex = readFirstNumeric(meta, ['page_idx', 'page_index', 'position.page_idx', 'position.page_index'])
  if (pageIndex !== null && pageIndex >= 0) return Math.round(pageIndex) + 1
  return null
}

const normalizeRect = (
  meta: Record<string, any>,
  rect: [number, number, number, number],
  pageDimension?: PageDimension
) => {
  const [rawX0, rawY0, rawX1, rawY1] = rect
  const minX = Math.min(rawX0, rawX1)
  const minY = Math.min(rawY0, rawY1)
  const maxX = Math.max(rawX0, rawX1)
  const maxY = Math.max(rawY0, rawY1)
  const width = Math.max(0.002, maxX - minX)
  const height = Math.max(0.002, maxY - minY)
  const largestValue = Math.max(Math.abs(maxX), Math.abs(maxY), Math.abs(minX), Math.abs(minY))
  if (largestValue <= 1.2) {
    return {
      left: Math.max(0, Math.min(1, minX)),
      top: Math.max(0, Math.min(1, minY)),
      width: Math.max(0.002, Math.min(1, width)),
      height: Math.max(0.002, Math.min(1, height))
    }
  }
  const pageWidth = pageDimension?.width
    || readFirstNumeric(meta, ['page_width', 'pageWidth', 'width'])
    || Math.max(1, maxX)
  const pageHeight = pageDimension?.height
    || readFirstNumeric(meta, ['page_height', 'pageHeight', 'height'])
    || Math.max(1, maxY)
  return {
    left: Math.max(0, Math.min(1, minX / pageWidth)),
    top: Math.max(0, Math.min(1, minY / pageHeight)),
    width: Math.max(0.002, Math.min(1, width / pageWidth)),
    height: Math.max(0.002, Math.min(1, height / pageHeight))
  }
}

const parseRect = (meta: Record<string, any>): [number, number, number, number] | null => {
  const candidates = [
    meta.bbox,
    meta.rect,
    meta.box,
    meta.pdf_bbox,
    meta.pdf_rect,
    meta.position?.bbox,
    meta.position?.rect
  ]
  for (const candidate of candidates) {
    if (Array.isArray(candidate) && candidate.length >= 4) {
      const values = candidate.slice(0, 4).map(readNumeric)
      if (values.every(value => value !== null)) {
        return values as [number, number, number, number]
      }
    }
    if (candidate && typeof candidate === 'object') {
      const objectValue = candidate as Record<string, any>
      const left = readFirstNumeric(objectValue, ['x0', 'left', 'x'])
      const top = readFirstNumeric(objectValue, ['y0', 'top', 'y'])
      const right = readFirstNumeric(objectValue, ['x1', 'right'])
      const bottom = readFirstNumeric(objectValue, ['y1', 'bottom'])
      if (left !== null && top !== null && right !== null && bottom !== null) {
        return [left, top, right, bottom]
      }
      const width = readFirstNumeric(objectValue, ['w', 'width'])
      const height = readFirstNumeric(objectValue, ['h', 'height'])
      if (left !== null && top !== null && width !== null && height !== null) {
        return [left, top, left + width, top + height]
      }
    }
  }
  return null
}

const normalizeForMatch = (value: string) => value
  .replace(/[０-９]/g, char => String.fromCharCode(char.charCodeAt(0) - 65248))
  .replace(/[Ａ-Ｚａ-ｚ]/g, char => String.fromCharCode(char.charCodeAt(0) - 65248))
  .replace(/\s+/g, ' ')
  .replace(/[^\u4e00-\u9fa5a-zA-Z0-9 ]+/g, ' ')
  .trim()
  .toLowerCase()

const middleMarkdownLines = computed(() => (editableContent.value || props.content || '').split('\n'))

const findLineRangeFromMiddle = (item: StructuredIndexItem): { lineStart: number; lineEnd: number } | null => {
  const source = [item.content, item.title]
    .find(value => typeof value === 'string' && value.trim().length > 0)
  if (!source) return null
  const normalizedNeedle = normalizeForMatch(source)
  if (!normalizedNeedle) return null
  const needle = normalizedNeedle.slice(0, 80)
  let matchIndex = -1
  for (let index = 0; index < middleMarkdownLines.value.length; index += 1) {
    const line = normalizeForMatch(middleMarkdownLines.value[index] || '')
    if (!line) continue
    if (line.includes(needle) || needle.includes(line.slice(0, Math.min(40, line.length)))) {
      matchIndex = index
      break
    }
  }
  if (matchIndex < 0) return null
  const lineStart = matchIndex + 1
  const lineEnd = Math.min(lineStart + 2, middleMarkdownLines.value.length || lineStart)
  return { lineStart, lineEnd }
}

const toLinkedHighlight = (
  itemId: string,
  fallbackId: string,
  meta: Record<string, any>,
  pageDimensions: Map<number, PageDimension>
): LinkedHighlight | null => {
  const pageNumber = resolvePageNumber(meta)
  const lineRange = extractLineRange(meta)
  const inferredLine = readFirstNumeric(meta, ['line', 'start_line', 'line_start', 'lineStart'])
  const lineStart = lineRange.lineStart ?? (inferredLine === null ? null : Math.max(1, Math.round(inferredLine)))
  const lineEnd = lineRange.lineEnd ?? lineStart
  const page = (() => {
    if (pageNumber !== null) return pageNumber
    if (lineStart === null) return 1
    const totalLines = Math.max(1, middleMarkdownLines.value.length || (editableContent.value || props.content || '').split('\n').length)
    const ratio = Math.max(0, Math.min(1, (lineStart - 1) / totalLines))
    return Math.max(
      1,
      Math.min(
        inferredPdfPageCount.value,
        Math.round(ratio * Math.max(1, inferredPdfPageCount.value - 1)) + 1
      )
    )
  })()
  const rect = parseRect(meta)
  const normalizedRect = rect ? normalizeRect(meta, rect, pageDimensions.get(page)) : null
  const type = meta.type || meta.category || 'text'
  return {
    id: `${itemId}-${fallbackId}`,
    itemId,
    page,
    hasRect: Boolean(normalizedRect),
    left: normalizedRect?.left ?? 0,
    top: normalizedRect?.top ?? 0,
    width: normalizedRect?.width ?? 0,
    height: normalizedRect?.height ?? 0,
    lineStart,
    lineEnd,
    type
  }
}

const findNearestMineruHighlight = (
  candidateLine: number | null,
  candidatePage: number | null,
  pool: LinkedHighlight[]
) => {
  if (!pool.length) return null
  if (candidateLine === null && candidatePage === null) return pool[0]
  let best: LinkedHighlight | null = null
  let bestScore = Number.POSITIVE_INFINITY
  pool.forEach(item => {
    if (candidatePage !== null && item.page !== candidatePage) return
    const lineForScore = candidateLine === null ? item.lineStart ?? 1 : candidateLine
    const distance = Math.abs((item.lineStart ?? lineForScore) - lineForScore)
    if (distance < bestScore) {
      best = item
      bestScore = distance
    }
  })
  if (best) return best
  if (candidatePage !== null) {
    return pool.find(item => item.page === candidatePage) || null
  }
  return pool[0]
}

const linkedHighlights = computed<LinkedHighlight[]>(() => {
  const pageDimensions = new Map<number, PageDimension>()
  ;(props.mineruBlocks || []).forEach(raw => {
    const meta = (raw || {}) as Record<string, any>
    const rect = parseRect(meta)
    if (!rect) return
    
    // We used to skip list blocks here, but that could lead to incorrect page dimension calculation
    // if the list block defines the page boundaries and explicit page_width is missing.
    // So we keep all blocks for dimension calculation, but filter them out later for highlights.

    const page = resolvePageNumber(meta) || 1
    const [rawX0, rawY0, rawX1, rawY1] = rect
    const maxX = Math.max(rawX0, rawX1, 1)
    const maxY = Math.max(rawY0, rawY1, 1)
    const explicitWidth = readFirstNumeric(meta, ['page_width', 'pageWidth', 'width'])
    const explicitHeight = readFirstNumeric(meta, ['page_height', 'pageHeight', 'height'])
    const current = pageDimensions.get(page)
    pageDimensions.set(page, {
      width: Math.max(current?.width || 1, explicitWidth || 0, maxX),
      height: Math.max(current?.height || 1, explicitHeight || 0, maxY)
    })
  })

  // 1. Convert all mineru blocks to highlights (Physical World View)
  const mineruPool = (props.mineruBlocks || [])
    .filter(item => {
      const meta = (item || {}) as Record<string, any>
      const type = meta.type || meta.category || 'text'
      
      // Filter out container blocks that have children (we want minimum granularity)
      if (meta.children && Array.isArray(meta.children) && meta.children.length > 0) {
        return false
      }

      // Explicitly skip 'list' type as requested, even if children check fails (e.g. data issue)
      if (type === 'list') {
        return false
      }

      // Skip structural noise blocks
      if (['header', 'footer'].includes(type)) {
        return false
      }
      return true
    })
    .map((item, index) => toLinkedHighlight(item.id || `mineru-${index}`, `mineru-${index}`, item || {}, pageDimensions))
    .filter((item): item is LinkedHighlight => Boolean(item))

  if (!structuredItemsValue.value.length) {
    return mineruPool
  }

  // 2. Build mapping from mineru_block_id to structured_item_id
  const blockToItemMap = new Map<string, string>()
  const itemLineRanges = new Map<string, { lineStart: number, lineEnd: number }>()

  structuredItemsValue.value.forEach((item, index) => {
    const itemId = item.id || `item-${index}`
    const meta = item.meta || {}
    // Collect all possible ID references
    const refs = [meta.mineru_block_id, meta.block_id, meta.source_block_id]
      .filter(v => typeof v === 'string' && v.trim())
    
    refs.forEach(ref => {
      blockToItemMap.set(ref, itemId)
    })

    // Calculate line range
    const range = findLineRangeFromMiddle(item)
    if (range) {
      itemLineRanges.set(itemId, range)
    }
  })

  // 3. Update mineru highlights with linked item IDs
  return mineruPool.map(highlight => {
    // Attempt to find a link
    // The highlight.itemId is currently the mineru block ID (from step 1)
    const originalId = highlight.itemId
    const linkedId = blockToItemMap.get(originalId)
    
    if (linkedId) {
      const range = itemLineRanges.get(linkedId)
      return { 
        ...highlight, 
        itemId: linkedId,
        lineStart: range?.lineStart ?? highlight.lineStart,
        lineEnd: range?.lineEnd ?? highlight.lineEnd
      }
    }
    
    return highlight
  })
})

const activeLinkedHighlight = computed(() => {
  if (!activeLinkedItemId.value) return null
  return linkedHighlights.value.find(item => item.itemId === activeLinkedItemId.value) || null
})

const activeLinkedLineRange = computed(() => {
  const current = activeLinkedHighlight.value
  if (!current || current.lineStart === null || current.lineEnd === null) return null
  return {
    start: current.lineStart,
    end: current.lineEnd
  }
})

const getContentLineCount = () => Math.max(
  1,
  (editableContent.value || props.content || '').split('\n').length
)

const scrollRightByLine = (lineStart: number) => {
  const ratio = Math.max(0, Math.min(1, (lineStart - 1) / getContentLineCount()))
  rightScrollPercent.value = ratio
}

const onHoverLinkedItem = (itemId: string | null) => {
  if (!highlightLinkEnabled.value) return
  activeLinkedItemId.value = itemId
}

const onSelectHighlightFromLeft = (itemId: string) => {
  if (!highlightLinkEnabled.value) return
  activeLinkedItemId.value = itemId
  const target = linkedHighlights.value.find(item => item.itemId === itemId)
  if (!target) return
  if (target.lineStart !== null && target.lineEnd !== null) {
    scrollRightByLine(target.lineStart)
  }
}

const onSelectItemFromRight = (itemId: string) => {
  if (!highlightLinkEnabled.value) return
  activeLinkedItemId.value = itemId
  const target = linkedHighlights.value.find(item => item.itemId === itemId)
  if (!target) return
  if (target.lineStart !== null && target.lineEnd !== null) {
    scrollRightByLine(target.lineStart)
  }
  if (isPdf.value && target.page !== pdfPage.value) {
    pdfPage.value = target.page
  }
}

const toggleHighlightLink = () => {
  highlightLinkEnabled.value = !highlightLinkEnabled.value
  if (!highlightLinkEnabled.value) {
    activeLinkedItemId.value = null
  }
}

watch(filePath, () => {
  if (isText.value) {
    loadTextContent()
  }
}, { immediate: true })

watch(() => props.content, (value) => {
  editableContent.value = value || ''
  savedContent.value = value || ''
}, { immediate: true })

watch(() => props.node.key, () => {
  activeTab.value = 'html'
  ingestModalVisible.value = false
  selectedStrategy.value = (props.node.strategy as KnowledgeStrategy) || 'A_structured'
  pdfPage.value = 1
  activeLinkedItemId.value = null
  leftScrollPercent.value = 0
  rightScrollPercent.value = 0
})

watch(() => props.node.visible, (value) => {
  visibilityMode.value = value ? 'shared' : 'local'
}, { immediate: true })

watch(() => props.node.strategy, (value) => {
  selectedStrategy.value = (value as KnowledgeStrategy) || 'A_structured'
}, { immediate: true })

watch([linkedHighlights, pdfPage, highlightLinkEnabled], () => {
  if (!highlightLinkEnabled.value) return
  const currentPageHighlights = linkedHighlights.value
    .filter(item => item.page === pdfPage.value)
    .filter(item => item.hasRect)
  if (!currentPageHighlights.length) {
    if (activeLinkedItemId.value && !linkedHighlights.value.some(item => item.itemId === activeLinkedItemId.value)) {
      activeLinkedItemId.value = null
    }
    return
  }
  const hasActiveOnPage = currentPageHighlights.some(item => item.itemId === activeLinkedItemId.value)
  if (!hasActiveOnPage) {
    activeLinkedItemId.value = currentPageHighlights[0].itemId
  }
}, { immediate: true })

watch(ingestStatusValue, (value) => {
  if (value === 'processing') {
    ingestModalVisible.value = true
  }
})

const escapeHtml = (content: string): string => content
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')

const escapeHtmlAttribute = (content: string): string => content
  .replace(/&/g, '&amp;')
  .replace(/"/g, '&quot;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')

const fileDirectoryPath = computed(() => {
  const path = filePath.value
  const dir = path.replace(/[\\/][^\\/]*$/, '')
  
  // Special handling for AnGIneer KB structure:
  // Source file is in 'source/' but parsed content and assets are in 'parsed/'
  // We redirect base path to 'parsed/' to correctly resolve relative assets like 'images/xxx.jpg'
  if (dir.endsWith('\\source') || dir.endsWith('/source')) {
    const parent = dir.substring(0, dir.length - 7)
    return `${parent}\\parsed`
  }
  
  return dir
})

const resolveAssetUrl = (source: string): string => {
  const trimmed = source.trim()
  if (!trimmed) return ''
  if (/^(https?:)?\/\//i.test(trimmed) || /^data:/i.test(trimmed) || /^blob:/i.test(trimmed)) {
    return trimmed
  }
  if (trimmed.startsWith('/api/files?')) return trimmed
  if (trimmed.startsWith('/')) return trimmed
  if (/^[a-zA-Z]:[\\/]/.test(trimmed)) {
    return `/api/files?path=${encodeURIComponent(trimmed)}`
  }
  const basePath = fileDirectoryPath.value
  if (!basePath) return trimmed
  const normalizedBase = basePath.endsWith('\\') || basePath.endsWith('/') ? basePath : `${basePath}\\`
  const absolutePath = `${normalizedBase}${trimmed}`.replace(/[\\/]+/g, '\\')
  return `/api/files?path=${encodeURIComponent(absolutePath)}`
}

const renderFormula = (formula: string, displayMode: boolean): string => {
  try {
    return katex.renderToString(formula, { throwOnError: false, displayMode })
  } catch (error) {
    const fallbackClass = displayMode ? 'math-block-fallback' : 'math-inline-fallback'
    return `<span class="${fallbackClass}">${escapeHtml(formula)}</span>`
  }
}

const renderInline = (content: string): string => {
  const placeholders = new Map<string, string>()
  let placeholderIndex = 0
  const setPlaceholder = (html: string) => {
    const key = `__INLINE_${placeholderIndex++}__`
    placeholders.set(key, html)
    return key
  }
  const withImages = content.replace(/!\[([^\]]*)\]\(([^)\s]+)(?:\s+"([^"]+)")?\)/g, (_, alt, src, title) => {
    const resolvedSrc = resolveAssetUrl(String(src))
    if (!resolvedSrc) return ''
    const titleAttr = title ? ` title="${escapeHtmlAttribute(String(title))}"` : ''
    return setPlaceholder(
      `<img class="markdown-image" src="${escapeHtmlAttribute(resolvedSrc)}" alt="${escapeHtmlAttribute(String(alt || ''))}"${titleAttr} />`
    )
  })
  const withFormulas = withImages.replace(/\$([^$\n]+)\$/g, (_, formula) => setPlaceholder(renderFormula(String(formula).trim(), false)))
  const rendered = escapeHtml(withFormulas)
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
  return rendered.replace(/__INLINE_(\d+)__/g, (key) => placeholders.get(key) || key)
}

const buildMarkdownTable = (tableLines: string[]): string => {
  const parseRow = (line: string) =>
    line
      .trim()
      .replace(/^\||\|$/g, '')
      .split('|')
      .map(cell => cell.trim())

  const headers = parseRow(tableLines[0])
  const bodyLines = tableLines.slice(2)
  const headHtml = `<thead><tr>${headers.map(cell => `<th>${renderInline(cell)}</th>`).join('')}</tr></thead>`
  const bodyHtml = bodyLines.length
    ? `<tbody>${bodyLines.map(line => {
      const cells = parseRow(line)
      return `<tr>${cells.map(cell => `<td>${renderInline(cell)}</td>`).join('')}</tr>`
    }).join('')}</tbody>`
    : ''
  return `<table>${headHtml}${bodyHtml}</table>`
}

const renderMarkdown = (content: string): string => {
  if (!content) return ''

  const lines = content.replace(/\r\n/g, '\n').split('\n')
  const htmlBlocks: string[] = []
  
  let paragraphBuffer: string[] = []
  let paragraphStartLine = -1
  
  let tableBuffer: string[] = []
  let tableStartLine = -1
  
  let inUnorderedList = false
  let inOrderedList = false
  
  let inCodeBlock = false
  let codeBlockBuffer: string[] = []
  let codeBlockStartLine = -1
  
  let inMathBlock = false
  let mathBlockBuffer: string[] = []
  let mathBlockStartLine = -1

  const flushParagraph = () => {
    if (!paragraphBuffer.length) return
    htmlBlocks.push(`<p data-line-start="${paragraphStartLine}">${renderInline(paragraphBuffer.join(' '))}</p>`)
    paragraphBuffer = []
    paragraphStartLine = -1
  }

  const flushTable = () => {
    if (!tableBuffer.length) return
    const tableHtml = buildMarkdownTable(tableBuffer)
    // Inject data-line-start into the table tag
    htmlBlocks.push(tableHtml.replace('<table', `<table data-line-start="${tableStartLine}"`))
    tableBuffer = []
    tableStartLine = -1
  }

  const closeLists = () => {
    if (inUnorderedList) {
      htmlBlocks.push('</ul>')
      inUnorderedList = false
    }
    if (inOrderedList) {
      htmlBlocks.push('</ol>')
      inOrderedList = false
    }
  }

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index]
    const trimmed = line.trim()
    const currentLineNumber = index + 1

    // 1. Handle Code Blocks
    if (trimmed.startsWith('```')) {
      if (inCodeBlock) {
        inCodeBlock = false
        const code = codeBlockBuffer.join('\n')
        htmlBlocks.push(`<pre data-line-start="${codeBlockStartLine}"><code>${escapeHtml(code)}</code></pre>`)
        codeBlockBuffer = []
        codeBlockStartLine = -1
      } else {
        flushParagraph()
        flushTable()
        closeLists()
        inCodeBlock = true
        codeBlockStartLine = currentLineNumber
      }
      continue
    }
    if (inCodeBlock) {
      codeBlockBuffer.push(line)
      continue
    }

    // 2. Handle Math Blocks
    if (trimmed === '$$') {
      if (inMathBlock) {
        inMathBlock = false
        const formula = mathBlockBuffer.join('\n')
        htmlBlocks.push(`<div class="math-block" data-line-start="${mathBlockStartLine}">${renderFormula(formula, true)}</div>`)
        mathBlockBuffer = []
        mathBlockStartLine = -1
      } else {
        flushParagraph()
        flushTable()
        closeLists()
        inMathBlock = true
        mathBlockStartLine = currentLineNumber
      }
      continue
    }
    if (inMathBlock) {
      mathBlockBuffer.push(line)
      continue
    }

    if (!trimmed) {
      flushParagraph()
      flushTable()
      closeLists()
      continue
    }

    // 3. Handle Tables
    const isTableCandidate = trimmed.includes('|')
    const nextLine = lines[index + 1]?.trim() || ''
    const looksLikeTableHeader = isTableCandidate && /^\|?[:\-\s|]+\|?$/g.test(nextLine)
    
    if (looksLikeTableHeader) {
      flushParagraph()
      closeLists()
      tableStartLine = currentLineNumber
      tableBuffer.push(trimmed)
      tableBuffer.push(nextLine)
      index += 1
      while (index + 1 < lines.length && lines[index + 1].trim().includes('|')) {
        tableBuffer.push(lines[index + 1].trim())
        index += 1
      }
      flushTable()
      continue
    }

    // 4. Handle Headers
    if (/^#{1,6}\s+/.test(trimmed)) {
      flushParagraph()
      flushTable()
      closeLists()
      const level = Math.min(6, trimmed.match(/^#+/)?.[0].length || 1)
      const title = trimmed.replace(/^#{1,6}\s+/, '')
      htmlBlocks.push(`<h${level} data-line-start="${currentLineNumber}">${renderInline(title)}</h${level}>`)
      continue
    }

    // 5. Handle Lists
    const unorderedMatch = trimmed.match(/^[-*+]\s+(.+)$/)
    if (unorderedMatch) {
      flushParagraph()
      flushTable()
      if (!inUnorderedList) {
        closeLists()
        htmlBlocks.push('<ul>')
        inUnorderedList = true
      }
      htmlBlocks.push(`<li data-line-start="${currentLineNumber}">${renderInline(unorderedMatch[1])}</li>`)
      continue
    }

    const orderedMatch = trimmed.match(/^\d+\.\s+(.+)$/)
    if (orderedMatch) {
      flushParagraph()
      flushTable()
      if (!inOrderedList) {
        closeLists()
        htmlBlocks.push('<ol>')
        inOrderedList = true
      }
      htmlBlocks.push(`<li data-line-start="${currentLineNumber}">${renderInline(orderedMatch[1])}</li>`)
      continue
    }

    // 6. Handle HTML
    if (/^<[^>]+>/.test(trimmed)) {
      flushParagraph()
      flushTable()
      closeLists()
      htmlBlocks.push(trimmed)
      continue
    }

    // 7. Paragraphs
    if (paragraphBuffer.length === 0) {
      paragraphStartLine = currentLineNumber
    }
    paragraphBuffer.push(trimmed)
  }

  flushParagraph()
  flushTable()
  closeLists()
  
  if (inCodeBlock) {
    const code = codeBlockBuffer.join('\n')
    htmlBlocks.push(`<pre data-line-start="${codeBlockStartLine}"><code>${escapeHtml(code)}</code></pre>`)
  }
  if (inMathBlock) {
    const formula = mathBlockBuffer.join('\n')
    htmlBlocks.push(`<div class="math-block" data-line-start="${mathBlockStartLine}">${renderFormula(formula, true)}</div>`)
  }

  return htmlBlocks.join('\n')
}

const renderedMarkdown = computed(() => renderMarkdown(editableContent.value || props.content || ''))
</script>

<style lang="less" scoped>
.doc-preview {
  --dp-bg: var(--docs-bg, #f3f5f8);
  --dp-pane-bg: var(--docs-pane-bg, #ffffff);
  --dp-pane-border: var(--docs-pane-border, #e8edf4);
  --dp-title-bg: var(--docs-title-bg, #ffffff);
  --dp-title-border: var(--docs-title-border, #edf1f7);
  --dp-title-text: var(--docs-text, #595959);
  --dp-title-strong: var(--docs-text-strong, #4f5d7a);
  --dp-sub-text: var(--docs-text-subtle, #8c8c8c);
  --dp-progress-bg: var(--docs-progress-bg, #f7f9fc);
  --dp-content-bg: var(--docs-content-bg, #ffffff);
  --dp-code-bg: var(--docs-code-bg, #f6f8fa);
  --dp-inline-code-bg: var(--docs-inline-code-bg, rgba(0, 0, 0, 0.04));
  --dp-scroll-track: transparent;
  --dp-scroll-thumb: rgba(15, 23, 42, 0.22);
  --dp-index-card-bg: var(--docs-index-card-bg, #fafcff);
  --dp-empty-overlay: var(--docs-empty-overlay, rgba(255, 255, 255, 0.92));
  --dp-empty-text: var(--docs-empty-text, rgba(0, 0, 0, 0.45));
  --dp-segment-bg: var(--docs-segment-bg, #dfe5f2);
  --dp-segment-border: var(--docs-segment-border, #cdd6e7);
  --dp-segment-selected-bg: var(--docs-segment-selected-bg, #ffffff);
  --dp-segment-selected-text: var(--docs-segment-selected-text, #1f2937);
  --dp-segment-shared-bg: var(--docs-segment-shared-bg, linear-gradient(90deg, #52c41a 0%, #389e0d 100%));
  --dp-segment-shared-border: var(--docs-segment-shared-border, #389e0d);
  --dp-math-bg: var(--docs-math-bg, #eef3ff);
  --dp-math-color: var(--docs-math-color, #1d3a8a);
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--dp-bg);

  .preview-content {
    flex: 1;
    overflow: hidden;
    padding: 6px;

    .split-preview {
      display: flex;
      height: 100%;
      min-height: 0;
      gap: 8px;

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
        color: var(--dp-title-strong);
        font-weight: 600;
        font-size: 14px;
        white-space: nowrap;
        display: inline-flex;
        align-items: center;
      }

      .pane-title-prefix-right {
        margin-right: 0;
      }

      .parse-state-tag {
        margin-inline-start: 2px;
      }

      .pane-actions-left,
      .pane-actions-right {
        display: flex;
        align-items: center;
        gap: 6px;
        min-width: 0;
        flex-wrap: nowrap;
        white-space: nowrap;
      }

      .action-btn {
        height: 28px;
        padding: 0 10px;
        border-radius: 10px;
        font-size: 12px;
      }

      .index-search-input {
        width: 136px;
      }

      .title-action-switch {
        margin-left: 2px;
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
        margin-bottom: 0;
      }

      .progress-text {
        color: var(--dp-sub-text);
        font-size: 12px;
        white-space: nowrap;
      }

      .file-preview,
      .split-pane-right .b2-content,
      .split-pane-right .index-list-wrap,
      .split-pane-right .markdown-preview {
        scrollbar-width: none;

        &::-webkit-scrollbar {
          width: 0;
          height: 0;
          background: var(--dp-scroll-track);
        }

        &:hover {
          scrollbar-width: thin;
        }

        &:hover::-webkit-scrollbar {
          width: 8px;
          height: 8px;
        }

        &:hover::-webkit-scrollbar-thumb {
          background: var(--dp-scroll-thumb);
          border-radius: 999px;
        }
      }

      .file-preview {
        flex: 1;
        overflow: hidden;
        position: relative;
        min-height: 0;
        background: var(--dp-content-bg);

        .pdf-frame-wrap,
        .office-frame-wrap {
          width: 100%;
          height: 100%;
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

        .office-preview {
          width: 100%;
          height: 100%;
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
        }
      }

      .split-pane-right {
        .b2-pane-title {
          display: flex;
          align-items: center;
          padding: 6px 8px;

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

          .b2-tabs {
            flex: 0 1 auto;
            min-width: 0;
            margin-right: 0;
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

          :deep(.ant-tabs-nav) {
            margin: 0;
          }

          :deep(.ant-tabs-nav::before) {
            display: none;
          }

          :deep(.ant-tabs-nav-wrap) {
            background: color-mix(in srgb, var(--dp-pane-bg) 88%, var(--dp-pane-border) 12%);
            border-radius: 999px;
            padding: 2px;
          }

          :deep(.ant-tabs-tab) {
            margin: 0;
            padding: 2px 10px;
            border-radius: 999px;
            font-size: 12px;
            transition: all 0.2s ease;
          }

          :deep(.ant-tabs-tab + .ant-tabs-tab) {
            margin-left: 2px;
          }

          :deep(.ant-tabs-tab-active) {
            background: var(--dp-pane-bg);
            box-shadow: 0 1px 2px rgba(15, 23, 42, 0.12);
          }

          :deep(.ant-tabs-ink-bar) {
            display: none;
          }

        }

        .b2-content {
          flex: 1;
          min-height: 0;
          overflow: auto;
          position: relative;
          background: var(--dp-content-bg) !important;
        }

        .markdown-preview {
          padding: 10px;
          background: var(--dp-content-bg) !important;
          color: var(--dp-title-text);
          line-height: 1.6;
          word-break: break-word;
          font-size: 13px;

          h1,
          h2,
          h3,
          h4,
          h5,
          h6 {
            color: var(--dp-title-strong);
            margin: 10px 0 6px;
            line-height: 1.35;
          }

          p {
            margin: 0 0 8px;
          }

          ul,
          ol {
            margin: 0 0 10px;
            padding-left: 20px;
          }

          li {
            margin-bottom: 4px;
          }

          :deep(pre) {
            background: var(--dp-code-bg);
            border-radius: 6px;
            padding: 10px;
            overflow: auto;
          }

          :deep(code) {
            background: var(--dp-inline-code-bg);
            padding: 2px 4px;
            border-radius: 4px;
          }

          :deep(table) {
            width: 100%;
            border-collapse: collapse;
            margin: 8px 0;
          }

          :deep(th),
          :deep(td) {
            border: 1px solid var(--dp-pane-border);
            padding: 6px 8px;
            text-align: left;
          }

          :deep(th) {
            background: color-mix(in srgb, var(--dp-content-bg) 78%, var(--dp-pane-border) 22%);
            color: var(--dp-title-strong);
          }

          :deep(.math-inline) {
            padding: 1px 6px;
            border-radius: 6px;
            background: var(--dp-math-bg);
            color: var(--dp-math-color);
            font-family: ui-monospace, Menlo, Consolas, monospace;
          }

          :deep(.math-block) {
            margin: 8px 0;
            padding: 8px 10px;
            border-radius: 8px;
            background: var(--dp-math-bg);
            color: var(--dp-math-color);
            font-family: ui-monospace, Menlo, Consolas, monospace;
            white-space: pre-wrap;
          }

          :deep(.markdown-image) {
            display: block;
            max-width: 100%;
            height: auto;
            margin: 10px auto;
            border-radius: 8px;
          }

          :deep(.math-inline-fallback),
          :deep(.math-block-fallback) {
            color: var(--dp-math-color);
            background: var(--dp-math-bg);
            border-radius: 6px;
          }

          :deep(.math-inline-fallback) {
            padding: 1px 6px;
          }

          :deep(.math-block-fallback) {
            display: inline-block;
            padding: 8px 10px;
          }
        }

        .markdown-edit-wrap {
          display: flex;
          flex-direction: column;
          height: 100%;
          padding: 6px;
          box-sizing: border-box;
        }

        .markdown-editor {
          flex: 1;
          min-height: 280px;
          resize: none;
          font-family: SFMono-Regular, Consolas, 'Liberation Mono', Menlo, monospace;
          font-size: 13px;
          line-height: 1.6;
        }

        .index-list-wrap {
          height: 100%;
          overflow: auto;
          padding: 8px 10px;
          box-sizing: border-box;
          background: var(--dp-content-bg) !important;
        }

        .index-summary-row {
          display: flex;
          align-items: center;
          gap: 6px;
          flex-wrap: wrap;
          margin-bottom: 6px;
        }

        .index-summary-primary {
          margin-bottom: 4px;
        }

        .b2-empty-inline {
          margin-top: 24px;
        }

        .index-list {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }

        .index-item {
          border: 1px solid var(--dp-pane-border);
          border-radius: 8px;
          padding: 8px 10px;
          background: var(--dp-index-card-bg);
        }

        .index-item-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 6px;
        }

        .index-order {
          color: var(--dp-sub-text);
          font-size: 12px;
        }

        .index-title {
          font-size: 13px;
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
      }
    }
  }

  .ingest-modal-content {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding-top: 6px;
  }

  .ingest-stage {
    font-size: 13px;
    color: #595959;
  }

  .ingest-result {
    font-size: 14px;
    color: #1677ff;
    font-weight: 600;
  }

  .ingest-result-actions {
    display: flex;
    gap: 8px;
  }

  &.dark-mode {
    --dp-bg: #101319;
    --dp-pane-bg: #171b24;
    --dp-pane-border: #2a3140;
    --dp-title-bg: #171b24;
    --dp-title-border: #2a3140;
    --dp-title-text: rgba(255, 255, 255, 0.78);
    --dp-title-strong: rgba(255, 255, 255, 0.92);
    --dp-sub-text: rgba(255, 255, 255, 0.62);
    --dp-progress-bg: #171b24;
    --dp-content-bg: #171b24;
    --dp-code-bg: #1d2330;
    --dp-inline-code-bg: rgba(255, 255, 255, 0.12);
    --dp-scroll-thumb: rgba(148, 163, 184, 0.42);
    --dp-index-card-bg: #1d2330;
    --dp-empty-overlay: rgba(16, 19, 25, 0.92);
    --dp-empty-text: rgba(255, 255, 255, 0.6);
    --dp-segment-bg: #2a3345;
    --dp-segment-border: #38445b;
    --dp-segment-selected-bg: #3a4660;
    --dp-segment-selected-text: rgba(255, 255, 255, 0.9);
    --dp-segment-shared-bg: linear-gradient(90deg, #49aa19 0%, #237804 100%);
    --dp-segment-shared-border: #237804;
    --dp-math-bg: rgba(59, 130, 246, 0.18);
    --dp-math-color: rgba(219, 234, 254, 0.95);
    background: var(--dp-bg);

    .preview-content {
      .split-preview {
        .pane-title,
        .parse-progress-row {
          border-color: var(--dp-title-border);
          background: var(--dp-title-bg);
        }
      }

      .file-preview {
        .text-viewer {
          background: var(--dp-code-bg);
          color: var(--dp-title-text);
        }
      }

      .b2-content,
      .markdown-edit-wrap {
        background: var(--dp-content-bg) !important;
      }

      .markdown-preview {
        background: var(--dp-content-bg) !important;
        color: var(--dp-title-text);
      }

      .split-pane-right {
        .b2-content,
        .index-list-wrap {
          background: var(--dp-content-bg) !important;
        }

        .b2-pane-title {
          :deep(.ant-tabs-nav-wrap) {
            background: #232a37;
          }

          :deep(.ant-tabs-tab-active) {
            background: #30384a;
            box-shadow: none;
          }

          :deep(.ant-tabs-tab-btn) {
            color: rgba(255, 255, 255, 0.75);
          }

          :deep(.ant-tabs-tab-active .ant-tabs-tab-btn) {
            color: rgba(255, 255, 255, 0.92);
          }
        }

        :deep(.strategy-select .ant-select-selector) {
          background: #1d2330;
          border-color: var(--dp-pane-border);
          color: var(--dp-title-text);
        }
      }

      .index-summary-row {
        :deep(.ant-tag) {
          background: #1d2330;
          border-color: var(--dp-pane-border);
          color: var(--dp-title-text);
        }
      }

      .b2-empty-inline {
        :deep(.ant-empty-description) {
          color: var(--dp-empty-text);
        }
      }

      :deep(.markdown-editor) {
        background: #1d2330;
        color: var(--dp-title-text);
        border-color: var(--dp-pane-border);
      }

      :deep(.markdown-editor:hover),
      :deep(.markdown-editor:focus),
      :deep(.markdown-editor.ant-input:focus),
      :deep(.markdown-editor.ant-input-focused) {
        border-color: #3a4660;
        box-shadow: none;
      }

      .b2-empty {
        :deep(.ant-empty-image path) {
          fill: rgba(255, 255, 255, 0.16);
        }
      }
    }
  }
}
</style>
