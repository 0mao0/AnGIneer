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

/** 取与归一化矩形相交的文本项，按行分组、行内按 left 排序拼接；行间 \n。 */
export function textItemsInRect(
  items: PageTextItem[],
  rect: { left: number; top: number; width: number; height: number },
): string {
  const list = items || []
  if (!list.length) return ''
  const hit = list.filter((it) => {
    return it.left < rect.left + rect.width
      && it.left + it.width > rect.left
      && it.top < rect.top + rect.height
      && it.top + it.height > rect.top
  })
  if (!hit.length) return ''
  const sorted = [...hit].sort((a, b) => a.top - b.top || a.left - b.left)
  const lines: string[] = []
  let cur: PageTextItem[] = []
  for (const it of sorted) {
    const last = cur[cur.length - 1]
    if (cur.length && last && Math.abs(it.top - last.top) > Math.max(it.height, last.height) * 0.7) {
      lines.push(cur.sort((a, b) => a.left - b.left).map((i) => i.text).join(''))
      cur = [it]
    } else {
      cur.push(it)
    }
  }
  if (cur.length) lines.push(cur.sort((a, b) => a.left - b.left).map((i) => i.text).join(''))
  return lines.join('\n').trim()
}

/** 把 matchText 在全文中的命中段标记出来；精确匹配失败时忽略空白差异再匹配。 */
export function buildMatchSegments(text: string, matchText: string): HighlightSegment[] {
  const source = text || ''
  const needle = (matchText || '').trim()
  if (!needle) return source ? [{ text: source, hit: false }] : []
  const plain: HighlightSegment[] = [{ text: source, hit: false }]
  const exact = source.indexOf(needle)
  if (exact >= 0) return splitMatchAt(source, exact, exact + needle.length)
  const compactText = source.replace(/\s+/g, '')
  const compactNeedle = needle.replace(/\s+/g, '')
  const ci = compactText.indexOf(compactNeedle)
  if (ci < 0) return plain
  const start = mapCompactMatchIndex(source, ci)
  const end = mapCompactMatchIndex(source, ci + compactNeedle.length)
  if (start < 0 || end <= start) return plain
  return splitMatchAt(source, start, end)
}

function splitMatchAt(text: string, start: number, end: number): HighlightSegment[] {
  const parts: HighlightSegment[] = []
  if (start > 0) parts.push({ text: text.slice(0, start), hit: false })
  parts.push({ text: text.slice(start, end), hit: true })
  if (end < text.length) parts.push({ text: text.slice(end), hit: false })
  return parts.filter((p) => p.text.length > 0)
}

/** 压缩空白文本的下标 → 原始文本下标（忽略空白计数）。 */
function mapCompactMatchIndex(text: string, compactIndex: number): number {
  let seen = 0
  for (let i = 0; i < text.length; i++) {
    if (!/\s/.test(text[i])) {
      if (seen === compactIndex) return i
      seen++
    }
  }
  // 命中段正好延伸到文本末尾：返回 length 让 slice 取到结尾
  if (seen === compactIndex) return text.length
  return -1
}

export function insetWordRects(rects: SearchWordRect[], verticalRatio = 0.76): SearchWordRect[] {
  return rects.map((rect) => {
    const inset = Math.min((rect.height * (1 - verticalRatio)) / 2, rect.height / 2)
    return {
      left: rect.left,
      top: rect.top + inset,
      width: rect.width,
      height: Math.max(0, rect.height - inset * 2),
    }
  })
}

export function matchTextItemRects(items: PageTextItem[], query: string): SearchWordRect[] {
  const lowerQ = (query || '').replace(/\s+/g, ' ').trim().toLowerCase()
  if (!lowerQ || !Array.isArray(items)) return []
  const runs: Array<{ item: PageTextItem; text: string; start: number; end: number }> = []
  let cursor = 0
  for (const item of items) {
    if (!item) continue
    const text = (item.text || '').replace(/\s+/g, ' ').trim()
    if (!text) continue
    runs.push({ item, text, start: cursor, end: cursor + text.length })
    cursor += text.length + 1 // +1 为条目间空格分隔
  }
  if (!runs.length) return []
  const spaced = runs.map(r => r.text).join(' ').toLowerCase()
  const spacedQ = lowerQ
  const spacedRects = collectMatchRects(spaced, spacedQ, runs)
  if (spacedRects.length) return spacedRects
  // 空格化字形（封面标题常把每个字/字母拆成独立条目）：去掉条目间空格再试一次
  const compactRuns: Array<{ item: PageTextItem; text: string; start: number; end: number }> = []
  let compactCursor = 0
  for (const run of runs) {
    const text = run.text.replace(/\s+/g, '')
    if (!text) continue
    compactRuns.push({ item: run.item, text, start: compactCursor, end: compactCursor + text.length })
    compactCursor += text.length
  }
  const compact = compactRuns.map(r => r.text).join('').toLowerCase()
  const compactQ = lowerQ.replace(/\s+/g, '')
  return collectMatchRects(compact, compactQ, compactRuns)
}

function collectMatchRects(
  full: string,
  lowerQ: string,
  runs: Array<{ item: PageTextItem; text: string; start: number; end: number }>,
): SearchWordRect[] {
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
