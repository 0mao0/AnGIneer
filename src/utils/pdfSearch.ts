/**
 * PDF 搜索展示层纯函数：片段命中分段、纸面页码映射、词级矩形匹配与行内插值。
 * 本文件不依赖任何应用模块，便于 node:test 直接运行。
 */

export interface HighlightSegment {
  text: string
  hit: boolean
}

export function buildHighlightSegments(text: string, query: string): HighlightSegment[] {
  const source = text || ''
  const q = (query || '').trim()
  if (!q) return source ? [{ text: source, hit: false }] : []
  const lowerSource = source.toLowerCase()
  const lowerQ = q.toLowerCase()
  const segments: HighlightSegment[] = []
  let cursor = 0
  let pos = lowerSource.indexOf(lowerQ)
  while (pos >= 0) {
    if (pos > cursor) segments.push({ text: source.slice(cursor, pos), hit: false })
    segments.push({ text: source.slice(pos, pos + q.length), hit: true })
    cursor = pos + q.length
    pos = lowerSource.indexOf(lowerQ, cursor)
  }
  if (cursor < source.length) segments.push({ text: source.slice(cursor), hit: false })
  return segments
}

export interface PageTextItem {
  text: string
  left: number
  top: number
  width: number
  height: number
}

export interface SearchWordRect {
  left: number
  top: number
  width: number
  height: number
}

export function matchTextItemRects(items: PageTextItem[], query: string): SearchWordRect[] {
  const lowerQ = (query || '').toLowerCase()
  if (!lowerQ || !Array.isArray(items)) return []
  const runs: Array<{ item: PageTextItem; start: number; end: number }> = []
  let cursor = 0
  for (const item of items) {
    if (!item || !item.text) continue
    runs.push({ item, start: cursor, end: cursor + item.text.length })
    cursor += item.text.length
  }
  if (!runs.length) return []
  const full = runs.map(r => r.item.text).join('').toLowerCase()
  const rects: SearchWordRect[] = []
  let pos = full.indexOf(lowerQ)
  while (pos >= 0) {
    const matchEnd = pos + lowerQ.length
    const overlapped = runs.filter(r => r.start < matchEnd && r.end > pos)
    if (overlapped.length) {
      const left = Math.min(...overlapped.map(r => r.item.left))
      const top = Math.min(...overlapped.map(r => r.item.top))
      const right = Math.max(...overlapped.map(r => r.item.left + r.item.width))
      const bottom = Math.max(...overlapped.map(r => r.item.top + r.item.height))
      rects.push({ left, top, width: Math.max(0, right - left), height: Math.max(0, bottom - top) })
    }
    pos = full.indexOf(lowerQ, pos + 1)
  }
  return rects
}

function charWidth(ch: string): number {
  if (/\s/.test(ch)) return 0.3
  if (/[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]/.test(ch)) return 1
  if (/[a-zA-Z0-9]/.test(ch)) return 0.55
  return 0.8
}

export interface NormalizedRect {
  left: number
  top: number
  width: number
  height: number
}

export function estimateMatchRects(lineText: string, query: string, bbox: NormalizedRect): SearchWordRect[] {
  const source = lineText || ''
  const q = (query || '').trim()
  if (!q || !source) return []
  const widths = Array.from(source).map(charWidth)
  const total = widths.reduce((sum, w) => sum + w, 0)
  if (total <= 0) return []
  const lowerSource = source.toLowerCase()
  const lowerQ = q.toLowerCase()
  const rects: SearchWordRect[] = []
  let pos = lowerSource.indexOf(lowerQ)
  while (pos >= 0) {
    const startWidth = widths.slice(0, pos).reduce((sum, w) => sum + w, 0)
    const matchWidth = widths.slice(pos, pos + lowerQ.length).reduce((sum, w) => sum + w, 0)
    rects.push({
      left: bbox.left + (startWidth / total) * bbox.width,
      top: bbox.top,
      width: (matchWidth / total) * bbox.width,
      height: bbox.height,
    })
    pos = lowerSource.indexOf(lowerQ, pos + 1)
  }
  return rects
}

export interface PrintedPageLabelNode {
  block_type?: string
  plain_text?: string
  page_idx?: number
}

export function buildPrintedPageLabels(
  nodes: PrintedPageLabelNode[],
  extractLabel: (text: string) => string | null,
): Record<number, string> {
  const list = Array.isArray(nodes) ? nodes : []
  const map: Record<number, string> = {}
  let maxPage = -1
  for (const node of list) {
    const page = Number(node?.page_idx)
    if (!Number.isInteger(page)) continue
    if (page > maxPage) maxPage = page
    const type = String(node?.block_type || '').toLowerCase()
    if (type !== 'page_number' && type !== 'page_footer') continue
    const label = extractLabel(String(node?.plain_text || ''))
    if (label && !(page in map)) map[page] = label
  }
  for (let page = 0; page <= maxPage; page += 1) {
    if (!(page in map)) map[page] = String(page + 1)
  }
  return map
}
