import { computed, ref, watch, type ComputedRef, type Ref } from 'vue'
import type { StructuredIndexItem } from '../types/knowledge'
import type { PreviewMode } from './useParsedPdfViewer'
import { collectItemRefs, hasExactItemRef } from '../utils/knowledge'

export interface LinkedHighlight {
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

interface RectBounds {
  left: number
  top: number
  width: number
  height: number
}

interface GraphDataLike {
  nodes: any[]
  edges: any[]
  stats?: {
    base_rows?: Record<string, any>[]
  }
}

interface UseWorkspaceLinkageOptions {
  graphData: ComputedRef<GraphDataLike | null | undefined>
  structuredItems: ComputedRef<StructuredIndexItem[]>
  markdownContent: ComputedRef<string>
  activeTab: ComputedRef<PreviewMode>
  isPdf: ComputedRef<boolean>
  pdfPage: Ref<number>
  rightScrollPercent: Ref<number>
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

const normalizeForMatch = (value: string) => value
  .replace(/[０-９]/g, char => String.fromCharCode(char.charCodeAt(0) - 65248))
  .replace(/[Ａ-Ｚａ-ｚ]/g, char => String.fromCharCode(char.charCodeAt(0) - 65248))
  .replace(/\s+/g, ' ')
  .replace(/[^\u4e00-\u9fa5a-zA-Z0-9 ]+/g, ' ')
  .trim()
  .toLowerCase()

const isDocumentPreviewTab = (tab: PreviewMode) => (
  tab === 'Preview_HTML' || tab === 'Preview_Markdown'
)

const normalizeRect = (bbox: unknown): RectBounds | null => {
  if (!Array.isArray(bbox) || bbox.length < 4) return null
  const [x0, y0, x1, y1] = bbox
  return {
    left: Math.max(0, Math.min(Number(x0) || 0, Number(x1) || 0)),
    top: Math.max(0, Math.min(Number(y0) || 0, Number(y1) || 0)),
    width: Math.abs((Number(x1) || 0) - (Number(x0) || 0)),
    height: Math.abs((Number(y1) || 0) - (Number(y0) || 0))
  }
}

const normalizeRectFromBaseRow = (row: Record<string, any>) => {
  const directBox = normalizeRect(row.bbox || row.bbox_norm || row.normalized_bbox)
  if (directBox) return directBox
  const x1 = readFirstNumeric(row, ['bbox_norm_x1', 'bbox_norm.left', 'bbox.left'])
  const y1 = readFirstNumeric(row, ['bbox_norm_y1', 'bbox_norm.top', 'bbox.top'])
  const x2 = readFirstNumeric(row, ['bbox_norm_x2', 'bbox_norm.right', 'bbox.right'])
  const y2 = readFirstNumeric(row, ['bbox_norm_y2', 'bbox_norm.bottom', 'bbox.bottom'])
  if (x1 !== null && y1 !== null && x2 !== null && y2 !== null) {
    return normalizeRect([x1, y1, x2, y2])
  }
  const absX1 = readFirstNumeric(row, ['bbox_abs_x1'])
  const absY1 = readFirstNumeric(row, ['bbox_abs_y1'])
  const absX2 = readFirstNumeric(row, ['bbox_abs_x2'])
  const absY2 = readFirstNumeric(row, ['bbox_abs_y2'])
  const pageWidth = readFirstNumeric(row, ['page_width'])
  const pageHeight = readFirstNumeric(row, ['page_height'])
  if (
    absX1 !== null && absY1 !== null && absX2 !== null && absY2 !== null
    && pageWidth !== null && pageHeight !== null && pageWidth > 0 && pageHeight > 0
  ) {
    return normalizeRect([
      absX1 / pageWidth,
      absY1 / pageHeight,
      absX2 / pageWidth,
      absY2 / pageHeight
    ])
  }
  return null
}

const collectMediaRects = (node: Record<string, any>, baseRow?: Record<string, any> | null): RectBounds[] => {
  const rects = [
    normalizeRect(node.bbox),
    ...(Array.isArray(node.merged_bboxes) ? node.merged_bboxes.map(normalizeRect) : []),
    baseRow ? normalizeRectFromBaseRow(baseRow) : null
  ].filter((rect): rect is RectBounds => Boolean(rect))
  const uniqueMap = new Map<string, RectBounds>()
  rects.forEach((rect) => {
    const key = [
      rect.left.toFixed(4),
      rect.top.toFixed(4),
      rect.width.toFixed(4),
      rect.height.toFixed(4)
    ].join(':')
    if (!uniqueMap.has(key)) {
      uniqueMap.set(key, rect)
    }
  })
  return Array.from(uniqueMap.values())
}

const rectRight = (rect: RectBounds) => rect.left + rect.width

const rectBottom = (rect: RectBounds) => rect.top + rect.height

const horizontalOverlapRatio = (leftRect: RectBounds, rightRect: RectBounds) => {
  const overlapWidth = Math.max(0, Math.min(rectRight(leftRect), rectRight(rightRect)) - Math.max(leftRect.left, rightRect.left))
  const baseWidth = Math.max(0.0001, Math.min(leftRect.width, rightRect.width))
  return overlapWidth / baseWidth
}

const isHorizontallyAlignedToMedia = (mediaRect: RectBounds, candidateRect: RectBounds) => {
  if (horizontalOverlapRatio(mediaRect, candidateRect) >= 0.18) {
    return true
  }
  const candidateCenterX = candidateRect.left + candidateRect.width / 2
  const horizontalPadding = Math.max(0.03, mediaRect.width * 0.35)
  return candidateCenterX >= mediaRect.left - horizontalPadding
    && candidateCenterX <= rectRight(mediaRect) + horizontalPadding
}

const isMediaRelationRectValid = (
  mediaRects: RectBounds[],
  candidateRect: RectBounds,
  blockType: string,
  relation: 'caption' | 'footnote'
) => {
  if (!mediaRects.length) return true
  return mediaRects.some((mediaRect) => {
    if (!isHorizontallyAlignedToMedia(mediaRect, candidateRect)) return false
    const verticalGapTolerance = Math.max(0.035, mediaRect.height * 0.85)
    const overlapTolerance = Math.max(0.012, mediaRect.height * 0.15)
    if (blockType === 'table' && relation === 'caption') {
      const gap = mediaRect.top - rectBottom(candidateRect)
      return gap >= -overlapTolerance && gap <= verticalGapTolerance
    }
    const gap = candidateRect.top - rectBottom(mediaRect)
    return gap >= -overlapTolerance && gap <= verticalGapTolerance
  })
}

const filterMediaRelatedHighlights = (
  mediaRects: RectBounds[],
  blockType: string,
  highlights: LinkedHighlight[]
) => highlights.filter(item => isMediaRelationRectValid(
  mediaRects,
  item,
  blockType,
  item.type?.includes('footnote') ? 'footnote' : 'caption'
))

/**
 * 从任意结构中提取可匹配的文本片段。
 */
const collectTextsFromAny = (source: unknown): string[] => {
  if (typeof source === 'string') {
    const text = source.trim()
    return text ? [text] : []
  }
  if (Array.isArray(source)) {
    return source.flatMap(item => collectTextsFromAny(item))
  }
  if (source && typeof source === 'object') {
    const payload = source as Record<string, any>
    const texts = [
      ...collectTextsFromAny(payload.content),
      ...collectTextsFromAny(payload.text),
      ...collectTextsFromAny(payload.value),
      ...collectTextsFromAny(payload.spans),
      ...collectTextsFromAny(payload.lines),
      ...collectTextsFromAny(payload.blocks),
      ...collectTextsFromAny(payload.children)
    ]
    return texts
  }
  return []
}

/**
 * 将坐标归一化为 PDF 高亮框所需的相对坐标。
 */
const normalizeRectFromPayload = (payload: Record<string, any>, pageWidth?: number | null, pageHeight?: number | null) => {
  const rawBox = payload.bbox || payload.box || payload.rect || payload.boundary
  if (Array.isArray(rawBox) && rawBox.length >= 4) {
    const values = rawBox.slice(0, 4).map(value => Number(value) || 0)
    const maxValue = Math.max(...values.map(value => Math.abs(value)))
    if (maxValue <= 1.2) {
      return normalizeRect(values)
    }
    if (pageWidth && pageHeight && pageWidth > 0 && pageHeight > 0) {
      return normalizeRect([
        values[0] / pageWidth,
        values[1] / pageHeight,
        values[2] / pageWidth,
        values[3] / pageHeight
      ])
    }
  }
  return normalizeRectFromBaseRow(payload)
}

/**
 * 从 caption 或 footnote 的 spans 中提取高亮框。
 */
const collectCaptionSpanHighlights = (
  nodeId: string,
  page: number,
  blockType: string,
  payload: Record<string, any> | null | undefined,
  keys: string[],
  pageWidth?: number | null,
  pageHeight?: number | null
): LinkedHighlight[] => {
  if (!payload) return []
  const highlights = keys.flatMap((key) => {
    const source = payload[key]
    const entries = Array.isArray(source) ? source : source ? [source] : []
    return entries.flatMap((entry, index) => {
      const entryPayload = Array.isArray(entry)
        ? { bbox: entry }
        : entry && typeof entry === 'object'
          ? entry as Record<string, any>
          : null
      if (!entryPayload) return []
      const rect = normalizeRectFromPayload(entryPayload, pageWidth, pageHeight)
      if (!rect) return []
      return [{
        id: `highlight-${nodeId}-${key}-${index}`,
        itemId: nodeId,
        page,
        hasRect: true,
        left: rect.left,
        top: rect.top,
        width: rect.width,
        height: rect.height,
        lineStart: null,
        lineEnd: null,
        type: `${blockType}-${key.includes('footnote') ? 'footnote' : 'caption'}`
      }]
    })
  })
  const uniqueMap = new Map<string, LinkedHighlight>()
  highlights.forEach((item) => {
    const uniqueKey = `${item.page}-${item.left.toFixed(4)}-${item.top.toFixed(4)}-${item.width.toFixed(4)}-${item.height.toFixed(4)}-${item.type}`
    if (!uniqueMap.has(uniqueKey)) {
      uniqueMap.set(uniqueKey, item)
    }
  })
  return Array.from(uniqueMap.values())
}

/**
 * 提取图表节点可用于匹配 caption 的文本候选。
 */
const extractRelatedTextCandidates = (
  node: Record<string, any>,
  relation: 'caption' | 'footnote',
  baseRow?: Record<string, any> | null
): string[] => {
  const contentJson = node.content_json && typeof node.content_json === 'object'
    ? node.content_json as Record<string, any>
    : null
  const rowContentJson = baseRow?.content_json && typeof baseRow.content_json === 'object'
    ? baseRow.content_json as Record<string, any>
    : null
  const blockType = String(node.block_type || baseRow?.block_type || '').toLowerCase()
  const relatedKeys = blockType === 'table'
    ? (relation === 'caption' ? ['table_caption'] : ['table_footnote'])
    : (relation === 'caption' ? ['image_caption'] : ['image_footnote'])
  return buildRelatedTextNeedles([
    ...(relation === 'caption' ? [node.title, node.caption] : [node.footnote]),
    ...relatedKeys.flatMap(key => collectTextsFromAny(contentJson?.[key])),
    ...relatedKeys.flatMap(key => collectTextsFromAny(rowContentJson?.[key]))
  ])
}

const buildRelatedTextNeedles = (values: Array<unknown>): string[] => {
  const needles = values
    .map(value => normalizeForMatch(String(value || '')))
    .filter(value => value.length >= 4)
    .sort((left, right) => right.length - left.length)
  return Array.from(new Set(needles))
}

const isCaptionLikeText = (value: string) => (
  /^(图|表|figure|table)\s*[0-9a-z\u4e00-\u9fa5]/i.test(value)
)

const matchesRelatedTextCandidate = (rowText: string, sourceTexts: string[]) => sourceTexts.some(sourceText => (
  sourceText.includes(rowText)
  || (rowText.length >= 10 && rowText.includes(sourceText))
  || (isCaptionLikeText(rowText) && sourceText.includes(rowText.slice(0, Math.min(rowText.length, 32))))
))

const isStructHeadingCandidate = (blockType: string, text: string) => {
  const normalizedType = String(blockType || '').trim().toLowerCase()
  if (normalizedType === 'title') return true
  if (!['paragraph', 'list', 'list_item'].includes(normalizedType)) return false
  return /^(附录[A-Z]|\d+(?:\.\d+)*)\b/.test(String(text || '').trim())
}

/**
 * 收集节点或原始行中显式产出的 caption / footnote 引用。
 */
const collectRelatedBlockRefs = (
  node: Record<string, any>,
  baseRow?: Record<string, any> | null
) => {
  const readRefs = (payload: Record<string, any> | null | undefined, singularKey: string, pluralKey: string) => {
    if (!payload || typeof payload !== 'object') return []
    const rawValues = [
      payload[singularKey],
      payload[pluralKey]
    ]
    const refs = rawValues.flatMap((value) => {
      if (Array.isArray(value)) {
        return value.map(inner => String(inner || '').trim()).filter(Boolean)
      }
      const text = String(value || '').trim()
      return text ? [text] : []
    })
    return Array.from(new Set(refs))
  }

  return {
    captionRefs: Array.from(new Set([
      ...readRefs(node, 'caption_block_uid', 'caption_block_uids'),
      ...readRefs(baseRow || null, 'caption_block_uid', 'caption_block_uids')
    ])),
    footnoteRefs: Array.from(new Set([
      ...readRefs(node, 'footnote_block_uid', 'footnote_block_uids'),
      ...readRefs(baseRow || null, 'footnote_block_uid', 'footnote_block_uids')
    ]))
  }
}

const scoreHighlightCandidate = (
  item: LinkedHighlight,
  matchedId: string,
  exactItemId: string | null,
  preferredPage: number | null
) => {
  let score = 0
  if (exactItemId && item.itemId === exactItemId) {
    score += 1600
  }
  if (item.structuredItemId === matchedId) {
    score += 1200
  }
  if (item.itemId === matchedId) {
    score += 1000
  }
  if (item.hasRect) {
    score += 360
  }
  if (item.lineStart !== null) {
    score += 40
  }
  if (preferredPage !== null) {
    if (item.page === preferredPage) {
      score += 240
    } else {
      score -= Math.min(180, Math.abs(item.page - preferredPage) * 18)
    }
  }
  const area = item.width * item.height
  if (Number.isFinite(area) && area > 0) {
    score += Math.min(50, area * 12)
  }
  return score
}

const findNearestHighlight = (
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

export function useWorkspaceLinkage(options: UseWorkspaceLinkageOptions) {
  const activeLinkedItemId = ref<string | null>(null)
  const highlightLinkEnabled = ref(true)
  const middleMarkdownLines = computed(() => options.markdownContent.value.split('\n'))
  const showHighlightToggle = computed(() => (options.graphData.value?.nodes || []).length > 0)
  const isDocumentPreviewActive = computed(() => isDocumentPreviewTab(options.activeTab.value))

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

  const getItemLineRange = (item: StructuredIndexItem): { lineStart: number; lineEnd: number } | null => {
    const meta = (item.meta || {}) as Record<string, any>
    const fromMeta = extractLineRange(meta)
    if (fromMeta.lineStart !== null && fromMeta.lineEnd !== null) {
      return fromMeta
    }
    const inferredLine = readFirstNumeric(meta, ['line', 'start_line', 'line_start', 'lineStart'])
    if (inferredLine !== null) {
      const line = Math.max(1, Math.round(inferredLine))
      return { lineStart: line, lineEnd: line }
    }
    return findLineRangeFromMiddle(item)
  }

  const linkedHighlights = computed<LinkedHighlight[]>(() => {
    const isStrictRightPaneLinkage = options.activeTab.value === 'Preview_IndexTree'
      || options.activeTab.value === 'Preview_IndexGraph'
    const nodes = options.graphData.value?.nodes || []
    const baseRows = options.graphData.value?.stats?.base_rows || []
    const baseRowByUid = new Map<string, Record<string, any>>()
    baseRows.forEach((row) => {
      const rowId = String(row.block_uid || row.id || '').trim()
      if (rowId) {
        baseRowByUid.set(rowId, row)
      }
    })
    const nodeSeqKeyMap = new Map<string, string>()
    nodes.forEach(node => {
      const nodeId = String(node.id || '').trim()
      if (!nodeId) return
      const page = Number(node.page_idx ?? 0) + 1
      const blockSeq = Number(node.block_seq ?? 0)
      if (page > 0 && blockSeq > 0) {
        nodeSeqKeyMap.set(nodeId, `p${page}b${blockSeq}`)
      }
    })

    const highlightPool = nodes
      .filter(node => {
        const type = node.block_type || 'text'
        if (['header', 'footer', 'page_header', 'page_number'].includes(type)) {
          return false
        }
        return true
      })
      .flatMap((node, index) => {
        const page = (node.page_idx ?? 0) + 1
        const type = node.block_type || 'text'
        const itemId = node.id || `node-${index}`
        const bboxPool = Array.isArray(node.merged_bboxes) && node.merged_bboxes.length
          ? [node.bbox, ...node.merged_bboxes]
          : [node.bbox]

        return bboxPool.map((bbox, bboxIndex) => {
          const normalizedRect = normalizeRect(bbox)
          return {
            id: bboxIndex === 0
              ? `highlight-${itemId}`
              : `highlight-${itemId}-merged-${bboxIndex}`,
            itemId,
            page,
            hasRect: Boolean(normalizedRect),
            left: normalizedRect?.left ?? 0,
            top: normalizedRect?.top ?? 0,
            width: normalizedRect?.width ?? 0,
            height: normalizedRect?.height ?? 0,
            lineStart: null,
            lineEnd: null,
            type
          }
        })
      })

    const supplementalHighlights = nodes.flatMap((node, index) => {
      const blockType = String(node.block_type || '').toLowerCase()
      if (!['image', 'table'].includes(blockType)) return []
      const nodeId = String(node.id || `node-${index}`)
      const page = Number(node.page_idx ?? 0) + 1
      const baseRow = baseRowByUid.get(nodeId) || null
      const contentJson = node.content_json && typeof node.content_json === 'object'
        ? node.content_json as Record<string, any>
        : null
      const rowContentJson = baseRow?.content_json && typeof baseRow.content_json === 'object'
        ? baseRow.content_json as Record<string, any>
        : null
      const mediaRects = collectMediaRects(node, baseRow)
      const pageWidth = readFirstNumeric(baseRow || node, ['page_width'])
      const pageHeight = readFirstNumeric(baseRow || node, ['page_height'])
      const captionBBoxKeys = blockType === 'table'
        ? ['table_caption_bboxes', 'table_footnote_bboxes']
        : ['image_caption_bboxes', 'image_footnote_bboxes']
      const { captionRefs, footnoteRefs } = collectRelatedBlockRefs(node, baseRow)
      const contentSpanHighlights = filterMediaRelatedHighlights(mediaRects, blockType, [
        ...collectCaptionSpanHighlights(nodeId, page, blockType, contentJson, captionBBoxKeys, pageWidth, pageHeight),
        ...collectCaptionSpanHighlights(nodeId, page, blockType, rowContentJson, captionBBoxKeys, pageWidth, pageHeight)
      ])
      const explicitRefHighlights = filterMediaRelatedHighlights(mediaRects, blockType, [
        ...captionRefs.flatMap((refId) => {
          const targetRow = baseRowByUid.get(refId)
          const normalizedRect = targetRow ? normalizeRectFromBaseRow(targetRow) : null
          const rowType = String(targetRow?.block_type || targetRow?.type || '').toLowerCase()
          const rowText = String(targetRow?.plain_text || targetRow?.text || '').trim()
          if (!targetRow || !normalizedRect || isStructHeadingCandidate(rowType, rowText)) return []
          return [{
            id: `highlight-${nodeId}-caption-ref-${refId}`,
            itemId: nodeId,
            page: Number(targetRow.page_seq || targetRow.page || ((Number(targetRow.page_idx ?? -1) + 1) || page)),
            hasRect: true,
            left: normalizedRect.left,
            top: normalizedRect.top,
            width: normalizedRect.width,
            height: normalizedRect.height,
            lineStart: null,
            lineEnd: null,
            type: `${blockType}-caption`
          }]
        }),
        ...footnoteRefs.flatMap((refId) => {
          const targetRow = baseRowByUid.get(refId)
          const normalizedRect = targetRow ? normalizeRectFromBaseRow(targetRow) : null
          const rowType = String(targetRow?.block_type || targetRow?.type || '').toLowerCase()
          const rowText = String(targetRow?.plain_text || targetRow?.text || '').trim()
          if (!targetRow || !normalizedRect || isStructHeadingCandidate(rowType, rowText)) return []
          return [{
            id: `highlight-${nodeId}-footnote-ref-${refId}`,
            itemId: nodeId,
            page: Number(targetRow.page_seq || targetRow.page || ((Number(targetRow.page_idx ?? -1) + 1) || page)),
            hasRect: true,
            left: normalizedRect.left,
            top: normalizedRect.top,
            width: normalizedRect.width,
            height: normalizedRect.height,
            lineStart: null,
            lineEnd: null,
            type: `${blockType}-footnote`
          }]
        })
      ])
      const captionSourceTexts = extractRelatedTextCandidates(node, 'caption', baseRow)
      const footnoteSourceTexts = extractRelatedTextCandidates(node, 'footnote', baseRow)
      const hasCaptionHighlights = [...contentSpanHighlights, ...explicitRefHighlights].some(item => item.type?.includes('caption'))
      const hasFootnoteHighlights = [...contentSpanHighlights, ...explicitRefHighlights].some(item => item.type?.includes('footnote'))
      if (!captionSourceTexts.length && !footnoteSourceTexts.length && !explicitRefHighlights.length && !contentSpanHighlights.length) return []
      const matchedRowHighlights = baseRows.flatMap((row, rowIndex) => {
        const rowId = String(row.block_uid || row.id || '').trim()
        if (!rowId || rowId === nodeId) return []
        if (captionRefs.includes(rowId) || footnoteRefs.includes(rowId)) return []
        const rowPage = Number(row.page_seq || row.page || ((Number(row.page_idx ?? -1) + 1) || 0))
        if (rowPage !== page) return []
        const rowType = String(row.block_type || row.type || '').toLowerCase()
        if (['image', 'table', 'header', 'footer', 'page_header', 'page_number'].includes(rowType)) {
          return []
        }
        const rowTextRaw = String(row.plain_text || row.text || '').trim()
        if (isStructHeadingCandidate(rowType, rowTextRaw)) return []
        const rowText = normalizeForMatch(rowTextRaw)
        if (!rowText || rowText.length < 4) return []
        const normalizedRect = normalizeRectFromBaseRow(row)
        if (!normalizedRect) return []
        return [
          ...(!hasCaptionHighlights && captionSourceTexts.length > 0 && matchesRelatedTextCandidate(rowText, captionSourceTexts) && isMediaRelationRectValid(mediaRects, normalizedRect, blockType, 'caption')
            ? [{
                id: `highlight-${nodeId}-caption-related-${rowId || rowIndex}`,
                itemId: nodeId,
                page: rowPage,
                hasRect: true,
                left: normalizedRect.left,
                top: normalizedRect.top,
                width: normalizedRect.width,
                height: normalizedRect.height,
                lineStart: null,
                lineEnd: null,
                type: `${blockType}-caption`
              }]
            : []),
          ...(!hasFootnoteHighlights && footnoteSourceTexts.length > 0 && matchesRelatedTextCandidate(rowText, footnoteSourceTexts) && isMediaRelationRectValid(mediaRects, normalizedRect, blockType, 'footnote')
            ? [{
                id: `highlight-${nodeId}-footnote-related-${rowId || rowIndex}`,
                itemId: nodeId,
                page: rowPage,
                hasRect: true,
                left: normalizedRect.left,
                top: normalizedRect.top,
                width: normalizedRect.width,
                height: normalizedRect.height,
                lineStart: null,
                lineEnd: null,
                type: `${blockType}-footnote`
              }]
            : [])
        ]
      })
      const mergedHighlights = [...contentSpanHighlights, ...explicitRefHighlights, ...matchedRowHighlights]
      const uniqueMap = new Map<string, LinkedHighlight>()
      mergedHighlights.forEach((item) => {
        const uniqueKey = `${item.page}-${item.left.toFixed(4)}-${item.top.toFixed(4)}-${item.width.toFixed(4)}-${item.height.toFixed(4)}`
        if (!uniqueMap.has(uniqueKey)) {
          uniqueMap.set(uniqueKey, item)
        }
      })
      return Array.from(uniqueMap.values())
    })
    const allHighlights = [...highlightPool, ...supplementalHighlights]

    if (!options.structuredItems.value.length) {
      return allHighlights
    }

    const blockToItemMap = new Map<string, string>()
    const seqToItemMap = new Map<string, string>()
    const itemLineRanges = new Map<string, { lineStart: number, lineEnd: number }>()

    options.structuredItems.value.forEach((item, index) => {
      const itemId = item.id || `item-${index}`
      const meta = item.meta || {}
      const refs = collectItemRefs(item)
      const hasExactRefs = hasExactItemRef(item)

      refs.forEach(ref => {
        blockToItemMap.set(ref, itemId)
      })

      const pageSeq = Number(meta.page_seq || meta.page || 0)
      const blockSeq = Number(meta.block_seq || 0)
      if (!hasExactRefs && pageSeq > 0 && blockSeq > 0) {
        seqToItemMap.set(`p${pageSeq}b${blockSeq}`, itemId)
      }

      const range = getItemLineRange(item)
      if (range) {
        itemLineRanges.set(itemId, range)
      }
    })

    return allHighlights.map(highlight => {
      const originalId = highlight.itemId
      const seqKey = nodeSeqKeyMap.get(originalId)
      const exactLinkedId = blockToItemMap.get(originalId)
      const linkedId = exactLinkedId || (!isStrictRightPaneLinkage ? seqToItemMap.get(seqKey || '') : undefined)

      if (linkedId) {
        const range = itemLineRanges.get(linkedId)
        return {
          ...highlight,
          structuredItemId: linkedId,
          lineStart: range?.lineStart ?? highlight.lineStart,
          lineEnd: range?.lineEnd ?? highlight.lineEnd
        }
      }

      return highlight
    })
  })

  const resolveLinkedHighlight = (
    id: string | null | undefined,
    exactItemId: string | null = null,
    preferredPage: number | null = options.isPdf.value ? options.pdfPage.value : null
  ): LinkedHighlight | null => {
    if (!id) return null
    const candidates = linkedHighlights.value.filter(item =>
      item.itemId === id || item.structuredItemId === id
    )
    if (!candidates.length) return null
    let target = candidates[0]
    let targetScore = scoreHighlightCandidate(target, id, exactItemId, preferredPage)
    for (let index = 1; index < candidates.length; index += 1) {
      const current = candidates[index]
      const score = scoreHighlightCandidate(current, id, exactItemId, preferredPage)
      if (score > targetScore) {
        target = current
        targetScore = score
      }
    }
    return target
  }

  const activeLinkedHighlight = computed(() => {
    if (!activeLinkedItemId.value) return null
    return resolveLinkedHighlight(activeLinkedItemId.value)
  })

  const activeLeftHighlightId = computed(() => activeLinkedHighlight.value?.itemId || activeLinkedItemId.value)

  const activeLinkedLineRange = computed(() => {
    const current = activeLinkedHighlight.value
    if (!current || current.lineStart === null || current.lineEnd === null) return null
    return {
      start: current.lineStart,
      end: current.lineEnd
    }
  })

  const scrollRightByLine = (lineStart: number) => {
    const lineCount = Math.max(1, options.markdownContent.value.split('\n').length)
    const ratio = Math.max(0, Math.min(1, (lineStart - 1) / lineCount))
    options.rightScrollPercent.value = ratio
  }

  /**
   * 根据当前右侧视图，选择更合适的激活 ID。
   */
  const resolveRightPaneActiveId = (target: LinkedHighlight, fallbackId: string | null = null) => {
    if (options.activeTab.value === 'Preview_IndexTree' || options.activeTab.value === 'Preview_IndexGraph') {
      return target.itemId || target.structuredItemId || fallbackId
    }
    return target.structuredItemId || target.itemId || fallbackId
  }

  const onHoverLinkedItem = (itemId: string | null) => {
    if (!highlightLinkEnabled.value) return
    if (!itemId) {
      activeLinkedItemId.value = null
      return
    }
    const target = resolveLinkedHighlight(itemId, itemId)
    activeLinkedItemId.value = target?.itemId || itemId
  }

  const onSelectHighlightFromLeft = (payload: string | LinkedHighlight) => {
    if (!highlightLinkEnabled.value) return
    const target = typeof payload === 'string'
      ? resolveLinkedHighlight(payload, payload, options.isPdf.value ? options.pdfPage.value : null)
      : payload
    const fallbackId = typeof payload === 'string'
      ? payload
      : payload.itemId || payload.structuredItemId || null
    activeLinkedItemId.value = target ? resolveRightPaneActiveId(target, fallbackId) : fallbackId
    if (!target) return
    if (isDocumentPreviewActive.value && target.lineStart !== null && target.lineEnd !== null) {
      scrollRightByLine(target.lineStart)
    }
    if (options.isPdf.value && target.page !== options.pdfPage.value) {
      options.pdfPage.value = target.page
    }
  }

  const onSelectItemFromRight = (itemId: string) => {
    if (!highlightLinkEnabled.value) return
    const target = resolveLinkedHighlight(itemId, itemId, null)
    activeLinkedItemId.value = target?.structuredItemId || target?.itemId || itemId
    if (!target) return
    if (isDocumentPreviewActive.value && target.lineStart !== null && target.lineEnd !== null) {
      scrollRightByLine(target.lineStart)
    }
    if (options.isPdf.value && target.page !== options.pdfPage.value) {
      options.pdfPage.value = target.page
    }
  }

  const onSelectLineFromRight = (line: number) => {
    if (!highlightLinkEnabled.value) return
    const target = findNearestHighlight(
      Math.max(1, Math.round(line)),
      options.isPdf.value ? options.pdfPage.value : null,
      linkedHighlights.value
    )
    if (!target) return
    activeLinkedItemId.value = target.structuredItemId || target.itemId
    if (options.isPdf.value && target.page !== options.pdfPage.value) {
      options.pdfPage.value = target.page
    }
  }

  const toggleHighlightLink = () => {
    highlightLinkEnabled.value = !highlightLinkEnabled.value
    if (!highlightLinkEnabled.value) {
      activeLinkedItemId.value = null
    }
  }

  const resetLinkageState = () => {
    activeLinkedItemId.value = null
  }

  watch([linkedHighlights, options.pdfPage, highlightLinkEnabled], () => {
    if (!highlightLinkEnabled.value) return
    if (activeLinkedItemId.value && !linkedHighlights.value.some(item =>
      item.itemId === activeLinkedItemId.value || item.structuredItemId === activeLinkedItemId.value
    )) {
      activeLinkedItemId.value = null
    }
  }, { immediate: true })

  return {
    linkedHighlights,
    activeLinkedItemId,
    highlightLinkEnabled,
    showHighlightToggle,
    activeLeftHighlightId,
    activeLinkedLineRange,
    onHoverLinkedItem,
    onSelectHighlightFromLeft,
    onSelectItemFromRight,
    onSelectLineFromRight,
    toggleHighlightLink,
    resetLinkageState
  }
}
