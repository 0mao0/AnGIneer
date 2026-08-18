/**
 * 检索结果 snippet 渲染：剥离 HTML 脏标签、渲染 KaTeX 公式、高亮命中词。
 * 输出 HTML 字符串，调用方使用 v-html 展示；普通文本均已转义。
 */
import katex from 'katex'

const MATH_RE = /(\$\$[\s\S]+?\$\$|\$[^$\n]+?\$)/g

interface HighlightSegment {
  text: string
  hit: boolean
}

const escapeHtml = (value: string): string => value
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')

const decodeEntities = (value: string): string => value
  .replace(/&nbsp;/g, ' ')
  .replace(/&lt;/g, '<')
  .replace(/&gt;/g, '>')
  .replace(/&amp;/g, '&')
  .replace(/&quot;/g, '"')
  .replace(/&#39;/g, "'")

/** 按查询词切分文本，命中片段标记 hit。 */
const buildHighlightSegments = (text: string, query: string): HighlightSegment[] => {
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

const renderMath = (source: string): string => {
  const normalized = source
    .replace(/^\$\$\s*([\s\S]*?)\s*\$\$$/u, '$1')
    .replace(/^\$\s*([\s\S]*?)\s*\$$/u, '$1')
  try {
    return katex.renderToString(normalized, {
      throwOnError: false,
      displayMode: source.startsWith('$$'),
    })
  } catch {
    return `<span class="math-inline-fallback">${escapeHtml(normalized)}</span>`
  }
}

const renderPlainWithHits = (plain: string, query: string): string => {
  if (!plain) return ''
  const q = (query || '').replace(/\s+/g, ' ').trim()
  if (!q) return escapeHtml(plain)
  return buildHighlightSegments(plain, q)
    .map(seg => (seg.hit ? `<mark class="search-hit">${escapeHtml(seg.text)}</mark>` : escapeHtml(seg.text)))
    .join('')
}

export const renderSearchSnippetHtml = (text: string, query: string): string => {
  const raw = (text || '').replace(/\r/g, '')
  // 先保护数学片段再剥离 HTML 标签，避免公式里的 < > 被误当标签删除
  const mathSpans: string[] = []
  const protectedText = raw.replace(MATH_RE, (m) => {
    mathSpans.push(m)
    return `\u0000${mathSpans.length - 1}\u0000`
  })
  const stripped = decodeEntities(protectedText.replace(/<[^>]*>/g, ''))
  const clean = stripped.replace(/\u0000(\d+)\u0000/g, (_, index) => mathSpans[Number(index)] ?? '')

  const q = (query || '').replace(/\s+/g, ' ').trim()
  const lowerQ = q.toLowerCase()
  let html = ''
  let last = 0
  MATH_RE.lastIndex = 0
  let match: RegExpExecArray | null
  while ((match = MATH_RE.exec(clean)) !== null) {
    html += renderPlainWithHits(clean.slice(last, match.index), q)
    const math = match[0]
    const hit = lowerQ.length > 0 && math.toLowerCase().includes(lowerQ)
    const rendered = renderMath(math)
    html += hit ? `<mark class="search-hit">${rendered}</mark>` : rendered
    last = match.index + math.length
  }
  html += renderPlainWithHits(clean.slice(last), q)
  return html
}
