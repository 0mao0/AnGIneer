import { computed, ref, watch, type ComputedRef, type Ref } from 'vue'
import type { StructuredIndexItem } from '../types/knowledge'
import type { PreviewMode } from './useParsedPdfViewer'
import { collectGroupHighlightIds } from '../utils/highlightGroup'
import { collectItemRefs, hasExactItemRef, isFurnitureNode } from '../utils/knowledge'

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
  contdTargetId?: string | null
  tableMergeId?: string | null
  linkedFormulaItemIds?: string[]
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
  showFurniture?: ComputedRef<boolean>
  /** 定位目标解析完成后回调（PDF 场景用于把命中 bbox 滚动居中）。 */
  onPdfHighlightResolved?: (target: LinkedHighlight) => void
}

interface ResolveLinkedHighlightOptions {
  preferLast?: boolean
}

interface SetActiveLinkedItemOptions {
  preferredPage?: number | null
  preferLastHighlight?: boolean
  groupHighlight?: boolean
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
  tab === 'Preview_Markdown'
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

interface PageRect {
  page: number
  rect: RectBounds | null
}

/**
 * 收集节点跨页 bbox：优先使用 page_bboxes（每个条目带 page_idx + bbox），
 * 否则回退到 bbox + merged_bboxes（沿用节点所在页）。
 */
const collectPageRects = (node: Record<string, any>, defaultPage: number): PageRect[] => {
  const pageBBoxes = node.page_bboxes
  if (Array.isArray(pageBBoxes) && pageBBoxes.length) {
    const pairs: PageRect[] = []
    const seen = new Set<string>()
    for (const entry of pageBBoxes) {
      const rect = normalizeRect(entry?.bbox)
      if (!rect) continue
      const page = Number(entry?.page_idx ?? -1) + 1
      if (!Number.isFinite(page) || page <= 0) continue
      const key = `${page}:${rect.left.toFixed(4)}:${rect.top.toFixed(4)}:${rect.width.toFixed(4)}:${rect.height.toFixed(4)}`
      if (seen.has(key)) continue
      seen.add(key)
      pairs.push({ page, rect })
    }
    if (pairs.length) return pairs
  }
  const bboxPool = Array.isArray(node.merged_bboxes) && node.merged_bboxes.length
    ? [node.bbox, ...node.merged_bboxes]
    : [node.bbox]
  return bboxPool.map(bbox => ({ page: defaultPage, rect: normalizeRect(bbox) }))
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

const relationGapScore = (
  mediaRect: RectBounds,
  candidateRect: RectBounds,
  blockType: string,
  relation: 'caption' | 'footnote'
): number | null => {
  if (!isHorizontallyAlignedToMedia(mediaRect, candidateRect)) return null
  const verticalGapTolerance = Math.max(0.035, mediaRect.height * 0.85)
  const overlapTolerance = Math.max(0.012, mediaRect.height * 0.15)
  if (blockType === 'table' && relation === 'caption') {
    const gap = mediaRect.top - rectBottom(candidateRect)
    if (gap >= -overlapTolerance && gap <= verticalGapTolerance) {
      return Math.abs(gap)
    }
    // 竖排/侧边表题：与表格横向对齐且纵向有交叠
    const verticalOverlap = Math.max(
      0,
      Math.min(rectBottom(mediaRect), rectBottom(candidateRect))
      - Math.max(mediaRect.top, candidateRect.top)
    )
    return verticalOverlap > 0 ? 0 : null
  }
  const gap = candidateRect.top - rectBottom(mediaRect)
  return (gap >= -overlapTolerance && gap <= verticalGapTolerance) ? Math.abs(gap) : null
}

const isMediaRelationRectValid = (
  mediaRects: RectBounds[],
  candidateRect: RectBounds,
  blockType: string,
  relation: 'caption' | 'footnote'
) => {
  if (!mediaRects.length) return true
  return mediaRects.some(mediaRect => (
    relationGapScore(mediaRect, candidateRect, blockType, relation) !== null
  ))
}

const collectPageMediaRects = (
  node: Record<string, any>,
  defaultPage: number
): Map<number, RectBounds[]> => {
  const map = new Map<number, RectBounds[]>()
  collectPageRects(node, defaultPage).forEach(({ page, rect }) => {
    if (!rect) return
    const list = map.get(page) || []
    list.push(rect)
    map.set(page, list)
  })
  return map
}

const resolveMediaRelationPage = (
  mediaRectsByPage: Map<number, RectBounds[]>,
  candidateRect: RectBounds,
  blockType: string,
  relation: 'caption' | 'footnote',
  fallbackPage: number
): number => {
  let bestPage = fallbackPage
  let bestScore = Number.POSITIVE_INFINITY
  mediaRectsByPage.forEach((mediaRects, page) => {
    for (const mediaRect of mediaRects) {
      const score = relationGapScore(mediaRect, candidateRect, blockType, relation)
      if (score !== null && score < bestScore) {
        bestScore = score
        bestPage = page
      }
    }
  })
  return bestPage
}

const filterMediaRelatedHighlights = (
  mediaRectsByPage: Map<number, RectBounds[]>,
  blockType: string,
  highlights: LinkedHighlight[]
) => highlights.filter(item => {
  const mediaRects = mediaRectsByPage.get(item.page) || []
  if (!mediaRects.length) return true
  return isMediaRelationRectValid(
    mediaRects,
    item,
    blockType,
    item.type?.includes('footnote') ? 'footnote' : 'caption'
  )
})

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
  pageRects: PageRect[],
  mediaRectsByPage: Map<number, RectBounds[]>,
  blockType: string,
  payload: Record<string, any> | null | undefined,
  keys: string[],
  pageWidth?: number | null,
  pageHeight?: number | null
): LinkedHighlight[] => {
  if (!payload) return []
  const fallbackPage = pageRects[0]?.page ?? 0
  const highlights = keys.flatMap((key) => {
    const relation = key.includes('footnote') ? 'footnote' : 'caption'
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
      const itemPage = resolveMediaRelationPage(
        mediaRectsByPage,
        rect,
        blockType,
        relation,
        fallbackPage
      )
      if (itemPage <= 0) return []
      return [{
        id: `highlight-${nodeId}-${key}-${index}`,
        itemId: nodeId,
        page: itemPage,
        hasRect: true,
        left: rect.left,
        top: rect.top,
        width: rect.width,
        height: rect.height,
        lineStart: null,
        lineEnd: null,
        type: `${blockType}-${relation}`
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
  const activeLinkedHighlightOverrideId = ref<string | null>(null)
  const sectionGroupExpandEnabled = ref(true)
  // PDF 内点击高亮框后锁定的节点 id：同一节点的所有 bbox（如公式框+编号框）一起高亮
  const pdfClickActiveItemId = ref<string | null>(null)
  let cachedMarkdownContent = ''
  let cachedMarkdownLines: string[] = []
  const isDocumentPreviewActive = computed(() => isDocumentPreviewTab(options.activeTab.value))
  const middleMarkdownLines = computed(() => {
    const content = options.markdownContent.value
    if (content !== cachedMarkdownContent) {
      cachedMarkdownContent = content
      cachedMarkdownLines = content.split('\n')
    }
    return cachedMarkdownLines
  })

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
      || options.activeTab.value === 'Preview_KnowledgeGraph'
    const showFurniture = options.showFurniture?.value ?? true
    const nodes = options.graphData.value?.nodes || []
    const hasBboxData = nodes.length > 0 && nodes.some(node => node.bbox || node.merged_bboxes || node.page_bboxes)
    if (!hasBboxData) return []
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

    // 公式节点 explanation_uids -> 引用它的公式 id，用于 hover 公式时联动解释段落
    const explanationLinkedMap = new Map<string, string[]>()
    nodes.forEach(node => {
      const formulaId = String(node.id || '').trim()
      const uids = node.explanation_uids
      if (!formulaId || !Array.isArray(uids)) return
      uids.forEach((rawUid) => {
        const uid = String(rawUid || '').trim()
        if (!uid) return
        if (!explanationLinkedMap.has(uid)) {
          explanationLinkedMap.set(uid, [])
        }
        const list = explanationLinkedMap.get(uid)!
        if (!list.includes(formulaId)) {
          list.push(formulaId)
        }
      })
    })

    // 展示层全量高亮：页眉/页脚/页码也参与（05 语义层另行收敛）
    const highlightPool = nodes
      .flatMap((node, index) => {
        if (!showFurniture && isFurnitureNode(node)) return []
        const page = (node.page_idx ?? 0) + 1
        const type = node.block_type || 'text'
        const itemId = node.id || `node-${index}`

        const baseHighlights = collectPageRects(node, page).map(({ page: rectPage, rect: normalizedRect }, bboxIndex) => {
          return {
            id: bboxIndex === 0
              ? `highlight-${itemId}`
              : `highlight-${itemId}-merged-${bboxIndex}`,
            itemId,
            page: rectPage,
            hasRect: Boolean(normalizedRect),
            left: normalizedRect?.left ?? 0,
            top: normalizedRect?.top ?? 0,
            width: normalizedRect?.width ?? 0,
            height: normalizedRect?.height ?? 0,
            lineStart: node.markdown_line_start ?? null,
            lineEnd: node.markdown_line_end ?? null,
            text: node.plain_text || '',
            type,
            contdTargetId: node.contd_target_id ?? null,
            tableMergeId: node.table_merge_id ?? null,
            linkedFormulaItemIds: explanationLinkedMap.get(itemId) || undefined,
          }
        })
        const regionHighlights: LinkedHighlight[] = []
        const headerBBox = normalizeRect(node.table_header_bbox)
        if (type === 'table' && headerBBox) {
          regionHighlights.push({
            id: `highlight-${itemId}-table-header`,
            itemId,
            page,
            hasRect: true,
            left: headerBBox.left,
            top: headerBBox.top,
            width: headerBBox.width,
            height: headerBBox.height,
            lineStart: null,
            lineEnd: null,
            type: 'table-header',
            contdTargetId: null,
            tableMergeId: null,
          })
        }
        const numberBBox = normalizeRect(node.equation_number_bbox)
        if (type === 'equation_interline' && numberBBox) {
          regionHighlights.push({
            id: `highlight-${itemId}-equation-number`,
            itemId,
            page,
            hasRect: true,
            left: numberBBox.left,
            top: numberBBox.top,
            width: numberBBox.width,
            height: numberBBox.height,
            lineStart: null,
            lineEnd: null,
            type: 'equation-number',
            contdTargetId: null,
            tableMergeId: null,
          })
        }
        return [...baseHighlights, ...regionHighlights]
      })

    const supplementalHighlights = nodes.flatMap((node, index) => {
      const blockType = String(node.block_type || '').toLowerCase()
      if (!['image', 'table'].includes(blockType)) return []
      const nodeId = String(node.id || `node-${index}`)
      const page = Number(node.page_idx ?? 0) + 1
      const contentJson = node.content_json && typeof node.content_json === 'object'
        ? node.content_json as Record<string, any>
        : null
      const pageRects = collectPageRects(node, page)
      const mediaRectsByPage = collectPageMediaRects(node, page)
      const pageWidth = readFirstNumeric(node, ['page_width'])
      const pageHeight = readFirstNumeric(node, ['page_height'])
      const captionBBoxKeys = blockType === 'table'
        ? ['table_caption_bboxes', 'table_footnote_bboxes']
        : ['image_caption_bboxes', 'image_footnote_bboxes']
      const { captionRefs, footnoteRefs } = collectRelatedBlockRefs(node, null)
      const contentSpanHighlights = filterMediaRelatedHighlights(mediaRectsByPage, blockType, [
        ...collectCaptionSpanHighlights(nodeId, pageRects, mediaRectsByPage, blockType, contentJson, captionBBoxKeys, pageWidth, pageHeight),
      ])
      const nodeById = new Map<string, Record<string, any>>()
      nodes.forEach((n) => {
        const uid = String(n.id || n.block_uid || '').trim()
        if (uid) nodeById.set(uid, n)
      })
      const explicitRefHighlights = filterMediaRelatedHighlights(mediaRectsByPage, blockType, [
        ...captionRefs.flatMap((refId) => {
          const targetRow = nodeById.get(refId)
          const normalizedRect = targetRow ? normalizeRect(node.bbox) : null
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
          const targetRow = nodeById.get(refId)
          const normalizedRect = targetRow ? normalizeRect(targetRow.bbox) : null
          const rowType = String(targetRow?.block_type || targetRow?.type || '').toLowerCase()
          const rowText = String(targetRow?.plain_text || targetRow?.text || '').trim()
          if (!targetRow || !normalizedRect || isStructHeadingCandidate(rowType, rowText)) return []
          return [{
            id: `highlight-${nodeId}-footnote-ref-${refId}`,
            itemId: nodeId,
            page: Number(targetRow.page_idx ?? -1) + 1 || page,
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
      const captionSourceTexts = extractRelatedTextCandidates(node, 'caption', null)
      const footnoteSourceTexts = extractRelatedTextCandidates(node, 'footnote', null)
      const hasCaptionHighlights = [...contentSpanHighlights, ...explicitRefHighlights].some(item => item.type?.includes('caption'))
      const hasFootnoteHighlights = [...contentSpanHighlights, ...explicitRefHighlights].some(item => item.type?.includes('footnote'))
      if (!captionSourceTexts.length && !footnoteSourceTexts.length && !explicitRefHighlights.length && !contentSpanHighlights.length) return []
      const spannedPages = new Set(pageRects.map(item => item.page))
      const matchedRowHighlights = nodes.flatMap((row, rowIndex) => {
        const rowId = String(row.block_uid || row.id || '').trim()
        if (!rowId || rowId === nodeId) return []
        if (captionRefs.includes(rowId) || footnoteRefs.includes(rowId)) return []
        const rowPage = (Number(row.page_idx ?? 0) + 1) || 0
        if (!spannedPages.has(rowPage)) return []
        const rowType = String(row.block_type || '').toLowerCase()
        if (['image', 'table'].includes(rowType)) {
          return []
        }
        if (isFurnitureNode(row)) {
          return []
        }
        const rowTextRaw = String(row.plain_text || '').trim()
        if (isStructHeadingCandidate(rowType, rowTextRaw)) return []
        const rowText = normalizeForMatch(rowTextRaw)
        if (!rowText || rowText.length < 4) return []
        const normalizedRect = normalizeRect(row.bbox)
        if (!normalizedRect) return []
        const rowMediaRects = mediaRectsByPage.get(rowPage) || []
        return [
          ...(!hasCaptionHighlights && captionSourceTexts.length > 0 && matchesRelatedTextCandidate(rowText, captionSourceTexts) && isMediaRelationRectValid(rowMediaRects, normalizedRect, blockType, 'caption')
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
          ...(!hasFootnoteHighlights && footnoteSourceTexts.length > 0 && matchesRelatedTextCandidate(rowText, footnoteSourceTexts) && isMediaRelationRectValid(rowMediaRects, normalizedRect, blockType, 'footnote')
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
    preferredPage: number | null = options.isPdf.value ? options.pdfPage.value : null,
    resolveOptions: ResolveLinkedHighlightOptions = {}
  ): LinkedHighlight | null => {
    if (!id) return null
    const candidates = linkedHighlights.value.filter(item =>
      item.itemId === id || item.structuredItemId === id
    )
    if (!candidates.length) return null
    if (resolveOptions.preferLast) {
      const pageMatchedCandidates = preferredPage !== null
        ? candidates.filter(item => item.page === preferredPage)
        : []
      const preferredCandidates = pageMatchedCandidates.length ? pageMatchedCandidates : candidates
      return preferredCandidates[preferredCandidates.length - 1] || null
    }
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

  /**
   * 当前激活目标应同时点亮的高亮组：
   * 目标自身（公式主体/编号/合并框）+ 通过 linkedFormulaItemIds 关联的解释段。
   */
  const activeLinkedHighlightIds = computed<string[]>(() => {
    const primary = activeLinkedHighlight.value
    return collectGroupHighlightIds(
      linkedHighlights.value,
      options.graphData.value?.nodes || [],
      primary?.itemId || activeLinkedItemId.value,
      primary?.id || null,
      sectionGroupExpandEnabled.value
    )
  })

  const activeLinkedHighlight = computed(() => {
    if (activeLinkedHighlightOverrideId.value) {
      return linkedHighlights.value.find(item => item.id === activeLinkedHighlightOverrideId.value) || null
    }
    if (!activeLinkedItemId.value) return null
    return resolveLinkedHighlight(activeLinkedItemId.value)
  })

  const activeLeftHighlightId = computed(
    () => pdfClickActiveItemId.value || activeLinkedHighlight.value?.id || activeLinkedItemId.value
  )

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
    if (options.activeTab.value === 'Preview_IndexTree' || options.activeTab.value === 'Preview_IndexGraph' || options.activeTab.value === 'Preview_KnowledgeGraph') {
      return target.itemId || target.structuredItemId || fallbackId
    }
    return target.structuredItemId || target.itemId || fallbackId
  }

  /**
   * 统一写入当前激活目标，并保留左侧高亮框的精确 ID。
   */
  const applyResolvedHighlight = (target: LinkedHighlight | null, fallbackId: string | null = null) => {
    activeLinkedItemId.value = target ? resolveRightPaneActiveId(target, fallbackId) : fallbackId
    activeLinkedHighlightOverrideId.value = target?.id || null
  }

  /**
   * 供外部主动设置联动目标，可按需偏向最后一个高亮框。
   */
  const setActiveLinkedItem = (itemId: string | null, setOptions: SetActiveLinkedItemOptions = {}) => {
    sectionGroupExpandEnabled.value = setOptions.groupHighlight !== false
    if (!itemId) {
      activeLinkedItemId.value = null
      activeLinkedHighlightOverrideId.value = null
      return
    }
    const target = resolveLinkedHighlight(
      itemId,
      itemId,
      setOptions.preferredPage ?? (options.isPdf.value ? options.pdfPage.value : null),
      { preferLast: setOptions.preferLastHighlight }
    )
    applyResolvedHighlight(target, itemId)
    if (!target) return
    if (isDocumentPreviewActive.value && target.lineStart !== null && target.lineEnd !== null) {
      scrollRightByLine(target.lineStart)
    }
    if (options.isPdf.value && target.page !== options.pdfPage.value) {
      options.pdfPage.value = target.page
    }
    if (options.isPdf.value) {
      options.onPdfHighlightResolved?.(target)
    }
  }

  const onHoverLinkedItem = (itemId: string | null) => {
    sectionGroupExpandEnabled.value = true
    if (itemId) {
      // 鼠标进入新框时解除"点击整节点锁定"，恢复精确 hover
      pdfClickActiveItemId.value = null
    }
    if (!itemId) {
      activeLinkedItemId.value = null
      activeLinkedHighlightOverrideId.value = null
      return
    }
    const target = resolveLinkedHighlight(itemId, itemId)
    activeLinkedItemId.value = target?.itemId || itemId
    activeLinkedHighlightOverrideId.value = target?.id || null
  }

  const onSelectHighlightFromLeft = (
    payload: string | LinkedHighlight,
    scrollPdfToHighlight?: (highlight: LinkedHighlight) => void,
  ) => {
    sectionGroupExpandEnabled.value = true
    let target: LinkedHighlight | null = null
    if (typeof payload !== 'string') {
      pdfClickActiveItemId.value = payload.itemId || null
      // PDF 内点击：锁定到节点 id（不锁具体框），公式框+编号框等同一节点 bbox 一起高亮
      activeLinkedItemId.value = payload.itemId || payload.structuredItemId || null
      activeLinkedHighlightOverrideId.value = null
      target = payload
    } else {
      target = resolveLinkedHighlight(payload, payload, options.isPdf.value ? options.pdfPage.value : null)
      applyResolvedHighlight(target, payload)
    }
    if (!target) return
    if (isDocumentPreviewActive.value && target.lineStart !== null && target.lineEnd !== null) {
      scrollRightByLine(target.lineStart)
    }
    if (options.isPdf.value) {
      // PDF 内点击 bbox：交给调用方精确聚焦到该块，不再整页对齐顶部
      if (scrollPdfToHighlight && typeof payload !== 'string') {
        scrollPdfToHighlight(target)
      } else if (target.page !== options.pdfPage.value) {
        options.pdfPage.value = target.page
      }
    }
  }

  const onSelectItemFromRight = (
    itemId: string,
    scrollPdfToHighlight?: (highlight: LinkedHighlight) => void,
  ) => {
    sectionGroupExpandEnabled.value = true
    pdfClickActiveItemId.value = itemId
    const target = resolveLinkedHighlight(itemId, itemId, null)
    // 右侧树点击：同样锁定到节点 id，PDF 里整节点（公式框+编号框）一起高亮
    activeLinkedItemId.value = itemId
    activeLinkedHighlightOverrideId.value = null
    if (!target) return
    if (isDocumentPreviewActive.value && target.lineStart !== null && target.lineEnd !== null) {
      scrollRightByLine(target.lineStart)
    }
    if (options.isPdf.value) {
      if (scrollPdfToHighlight) {
        scrollPdfToHighlight(target)
      } else if (target.page !== options.pdfPage.value) {
        options.pdfPage.value = target.page
      }
    }
  }

  const onSelectLineFromRight = (line: number) => {
    sectionGroupExpandEnabled.value = true
    const target = findNearestHighlight(
      Math.max(1, Math.round(line)),
      options.isPdf.value ? options.pdfPage.value : null,
      linkedHighlights.value
    )
    if (!target) return
    activeLinkedItemId.value = target.structuredItemId || target.itemId
    activeLinkedHighlightOverrideId.value = target.id
    if (options.isPdf.value && target.page !== options.pdfPage.value) {
      options.pdfPage.value = target.page
    }
  }

  const resetLinkageState = () => {
    sectionGroupExpandEnabled.value = true
    activeLinkedItemId.value = null
    activeLinkedHighlightOverrideId.value = null
    pdfClickActiveItemId.value = null
  }

  watch(linkedHighlights, () => {
    if (activeLinkedHighlightOverrideId.value && !linkedHighlights.value.some(item => item.id === activeLinkedHighlightOverrideId.value)) {
      activeLinkedHighlightOverrideId.value = null
    }
    if (activeLinkedItemId.value && !linkedHighlights.value.some(item =>
      item.itemId === activeLinkedItemId.value || item.structuredItemId === activeLinkedItemId.value
    )) {
      activeLinkedItemId.value = null
      activeLinkedHighlightOverrideId.value = null
    }
  }, { immediate: true })

  return {
    linkedHighlights,
    activeLinkedItemId,
    activeLinkedHighlightIds,
    activeLeftHighlightId,
    pdfClickActiveItemId,
    activeLinkedLineRange,
    onHoverLinkedItem,
    onSelectHighlightFromLeft,
    onSelectItemFromRight,
    onSelectLineFromRight,
    setActiveLinkedItem,
    resetLinkageState
  }
}
