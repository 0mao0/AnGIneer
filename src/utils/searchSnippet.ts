/**
 * 检索结果 snippet 渲染：剥离 HTML 脏标签、渲染 KaTeX 公式、高亮命中词。
 * 输出 HTML 字符串，调用方使用 v-html 展示；普通文本均已转义。
 */
import katex from 'katex'

const MATH_RE = /(\$\$[\s\S]+?\$\$|\$[^$\n]+?\$)/g

/** 裸 LaTeX 命令特征（规范文档公式常见的命令 token），用于识别无 $ 定界符的公式行 */
const BARE_LATEX_CMD_RE = /\\[a-zA-Z]{2,}/g

const KNOWN_LATEX_CMDS = new Set([
  'frac', 'dfrac', 'sqrt', 'sum', 'int', 'prod',
  'Delta', 'Sigma', 'Omega', 'alpha', 'beta', 'gamma', 'delta', 'lambda', 'pi',
  'mathrm', 'text', 'tag', 'left', 'right', 'begin', 'end',
  'cdot', 'times', 'leq', 'geq', 'approx', 'rightarrow', 'leftarrow',
  'sin', 'cos', 'tan', 'log', 'ln', 'partial', 'infty', 'pm', 'mp', 'div',
])

/** 公式行启发式：行内含常见 LaTeX 命令（>=2 个命令，或 1 个已知命令且行内有数学符号/数字/括号）。
 * 含中文的行视为正文（公式是行内的），不按整行公式渲染。 */
const isBareLatexLine = (line: string): boolean => {
  const trimmed = line.trim()
  if (!trimmed) return false
  if (/[\u4e00-\u9fa5]/.test(trimmed)) return false
  const cmdMatches = trimmed.match(BARE_LATEX_CMD_RE)
  if (!cmdMatches) return false
  const knownMatches = cmdMatches.filter(cmd => KNOWN_LATEX_CMDS.has(cmd.replace(/^\\/, '')))
  if (knownMatches.length >= 2) return true
  if (knownMatches.length === 1) {
    return /[=≤≥≈×÷]|\d|[{（）(]/.test(trimmed)
  }
  return false
}

/** 渲染一段裸 LaTeX 公式（无 $ 定界符） */
const renderBareLatex = (source: string): string => {
  const normalized = source.trim()
  try {
    return katex.renderToString(normalized, {
      throwOnError: false,
      displayMode: true,
    })
  } catch {
    return `<span class="math-inline-fallback">${escapeHtml(normalized)}</span>`
  }
}

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

/**
 * 行内裸 LaTeX 片段：连续的可打印 ASCII（字母/数字/符号/空格）内出现 LaTeX 命令，
 * 且片段内无中文（中文作为边界）。示例：
 * - "码头水深 H = T + \DeltaH\tag{A. 0.1} 应满足" → 命中 "H = T + \DeltaH\tag{A. 0.1}"
 * - "B _ {1} = B _ {\mathrm{F}} + 2 d\tag{A. 0.2-1}" → 命中整段
 * - 纯中文句（无命令）不命中
 */
const BARE_INLINE_LATEX_RE =
  /[A-Za-z0-9_={}()+\-*/.,;:≤≥≈×÷±·\s\\]*\\[a-zA-Z]{2,}[A-Za-z0-9_={}()+\-*/.,;:≤≥≈×÷±·\s\\]*(?=\s*[\u4e00-\u9fa5，。；、（）【】]|\s*$)/g

/** 行内裸 LaTeX 渲染（行内模式；含 \tag 的公式需 display 模式才能工作） */
const renderInlineBareLatex = (source: string, query: string): string => {
  const normalized = source.trim()
  if (!normalized) return ''
  let rendered: string
  try {
    rendered = katex.renderToString(normalized, {
      throwOnError: false,
      displayMode: normalized.includes('\\tag'),
    })
  } catch {
    return escapeHtml(normalized)
  }
  const q = (query || '').replace(/\s+/g, ' ').trim()
  const hit = q.length > 0 && normalized.toLowerCase().includes(q.toLowerCase())
  const inner = hit ? `<mark class="search-hit">${rendered}</mark>` : rendered
  return `<span class="bare-latex-inline">${inner}</span>`
}

/** 高亮 + 行内裸 LaTeX 渲染（对 $ 公式已剥离的纯文本） */
const renderPlainWithHitsAndBareLatex = (plain: string, query: string): string => {
  if (!plain) return ''
  const parts: string[] = []
  let last = 0
  BARE_INLINE_LATEX_RE.lastIndex = 0
  let match: RegExpExecArray | null
  while ((match = BARE_INLINE_LATEX_RE.exec(plain)) !== null) {
    const seg = match[0]
    if (!seg.trim()) {
      last = match.index + seg.length
      continue
    }
    parts.push(renderPlainWithHits(plain.slice(last, match.index), query))
    parts.push(renderInlineBareLatex(seg, query))
    last = match.index + seg.length
  }
  parts.push(renderPlainWithHits(plain.slice(last), query))
  return parts.join('')
}

/**
 * 渲染单行：先处理 $ 定界公式，剩余部分高亮转义 + 行内裸 LaTeX 渲染。
 * 若整行（去公式后）是纯裸 LaTeX 公式行，则整行渲染为 display KaTeX。
 */
const renderLine = (line: string, query: string): string => {
  const trimmed = line.trim()
  if (isBareLatexLine(trimmed)) {
    return `<div class="bare-latex-line">${renderBareLatex(trimmed)}</div>`
  }
  const mathSpans: string[] = []
  const protectedText = line.replace(MATH_RE, (m) => {
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
    html += renderPlainWithHitsAndBareLatex(clean.slice(last, match.index), q)
    const math = match[0]
    const hit = lowerQ.length > 0 && math.toLowerCase().includes(lowerQ)
    const rendered = renderMath(math)
    html += hit ? `<mark class="search-hit">${rendered}</mark>` : rendered
    last = match.index + math.length
  }
  html += renderPlainWithHitsAndBareLatex(clean.slice(last), q)
  return html
}

export const renderSearchSnippetHtml = (text: string, query: string): string => {
  const raw = (text || '').replace(/\r/g, '')
  const lines = raw.split('\n')
  return lines.map(line => renderLine(line, query)).join('\n')
}
