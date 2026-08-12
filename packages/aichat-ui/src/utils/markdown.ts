import katex from 'katex'
import 'katex/dist/katex.min.css'

export const escapeHtml = (content: string): string => content
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')

export const escapeHtmlAttribute = (content: string): string => content
  .replace(/&/g, '&amp;')
  .replace(/"/g, '&quot;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')

const resolveMarkdownAssetBasePath = (path: string): string => {
  const dir = path.replace(/[\\/][^\\/]*$/, '')
  if (dir.endsWith('\\source') || dir.endsWith('/source')) {
    const parent = dir.substring(0, dir.length - 7)
    return `${parent}\\parsed`
  }
  return dir
}

/** 将 Markdown 中的相对资源路径解析为可访问的 URL */
export const resolveAssetUrl = (source: string, sourceFilePath?: string): string => {
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
  if (!sourceFilePath) return trimmed
  const basePath = resolveMarkdownAssetBasePath(sourceFilePath)
  if (!basePath) return trimmed
  const normalizedBase = basePath.endsWith('\\') || basePath.endsWith('/') ? basePath : `${basePath}\\`
  const absolutePath = `${normalizedBase}${trimmed}`.replace(/[\\/]+/g, '\\')
  return `/api/files?path=${encodeURIComponent(absolutePath)}`
}

/** 使用 KaTeX 渲染数学公式 */
export const renderFormula = (formula: string, displayMode: boolean): string => {
  const source = (formula || '').trim()
  if (!source) return ''
  const normalizedSource = source
    .replace(/^\\\[\s*([\s\S]*?)\s*\\\]$/u, '$1')
    .replace(/^\\\(\s*([\s\S]*?)\s*\\\)$/u, '$1')
    .replace(/^\$\$\s*([\s\S]*?)\s*\$\$$/u, '$1')
  try {
    return katex.renderToString(normalizedSource, { throwOnError: false, displayMode })
  } catch {
    const fallbackClass = displayMode ? 'math-block-fallback' : 'math-inline-fallback'
    return `<span class="${fallbackClass}">${escapeHtml(normalizedSource)}</span>`
  }
}

/** 简单 Markdown 渲染（用于纯文本消息） */
export const renderMarkdown = (content: string): string => {
  if (!content) return ''
  const trimmedContent = content.trim()
  return trimmedContent
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>')
    .replace(/\n/g, '<br/>')
}

const renderInline = (
  content: string,
  sourceFilePath: string,
  resolveUrl?: (src: string, sourceFilePath: string) => string
): string => {
  const placeholders = new Map<string, string>()
  let placeholderIndex = 0
  const setPlaceholder = (html: string) => {
    const key = `__INLINE_${placeholderIndex++}__`
    placeholders.set(key, html)
    return key
  }
  const latexSupSubPattern = String.raw`(?:\^\{[^{}\n]+\}|\^\\[a-zA-Z]+|\^[A-Za-z0-9]+|_\{[^{}\n]+\}|_\\[a-zA-Z]+|_[A-Za-z0-9]+)`
  const latexStartTokenPattern = String.raw`(?:\\[a-zA-Z]+|[A-Za-z0-9]+(?:${latexSupSubPattern})+)`
  const latexContinueTokenPattern = String.raw`(?:\\[a-zA-Z]+|[A-Za-z0-9]+(?:${latexSupSubPattern})*|[()+\-*/=<>~.,:]+|\{[^{}\n]+\}|\[[^[\]\n]*\])`
  const bareInlineLatexPattern = new RegExp(
    `(^|[\\s(（\\[【,:：;；])(${latexStartTokenPattern}(?:\\s*${latexContinueTokenPattern})*)`,
    'g'
  )
  const withImages = content.replace(/!\[([^\]]*)\]\(([^)\s]+)(?:\s+"([^"]+)")?\)/g, (_, alt, src, title) => {
    const resolvedSrc = (resolveUrl ?? resolveAssetUrl)(String(src), sourceFilePath)
    if (!resolvedSrc) return ''
    const titleAttr = title ? ` title="${escapeHtmlAttribute(String(title))}"` : ''
    return setPlaceholder(
      `<img class="markdown-image" src="${escapeHtmlAttribute(resolvedSrc)}" alt="${escapeHtmlAttribute(String(alt || ''))}"${titleAttr} />`
    )
  })
  const withDelimitedFormulas = withImages
    .replace(/\\\(([\s\S]*?)\\\)/g, (_, formula) => setPlaceholder(renderFormula(String(formula).trim(), false)))
    .replace(/\\\[([\s\S]*?)\\\]/g, (_, formula) => setPlaceholder(renderFormula(String(formula).trim(), true)))
    .replace(/\$\$([\s\S]*?)\$\$/g, (_, formula) => setPlaceholder(renderFormula(String(formula).trim(), true)))
    .replace(/\$([^$\n]+)\$/g, (_, formula) => setPlaceholder(renderFormula(String(formula).trim(), false)))
  const withFormulas = withDelimitedFormulas.replace(bareInlineLatexPattern, (_, prefix, formula) => {
    const normalizedFormula = String(formula || '').trim()
    if (!normalizedFormula) return prefix
    return `${String(prefix || '')}${setPlaceholder(renderFormula(normalizedFormula, false))}`
  })
  const htmlTableTagPattern = /<\/?(?:table|thead|tbody|tfoot|tr|td|th|caption|colgroup|col)\b[^>]*\/?>/gi
  const withProtectedTableTags = withFormulas.replace(htmlTableTagPattern, (match) => setPlaceholder(match))
  const rendered = escapeHtml(withProtectedTableTags)
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
  return rendered.replace(/__INLINE_(\d+)__/g, (key) => placeholders.get(key) || key)
}

/** 渲染行内 Markdown（不含块级元素） */
export const renderMarkdownInlineToHtml = (
  content: string,
  sourceFilePath: string,
  resolveUrl?: (src: string, sourceFilePath: string) => string
): string => {
  if (!content) return ''
  return renderInline(content, sourceFilePath, resolveUrl)
}

const buildMarkdownTable = (
  tableLines: string[],
  sourceFilePath: string,
  resolveUrl?: (src: string, sourceFilePath: string) => string
): string => {
  const parseRow = (line: string) =>
    line
      .trim()
      .replace(/^\||\|$/g, '')
      .split('|')
      .map(cell => cell.trim())

  const headers = parseRow(tableLines[0])
  const bodyLines = tableLines.slice(2)
  const headHtml = `<thead><tr>${headers.map(cell => `<th>${renderInline(cell, sourceFilePath, resolveUrl)}</th>`).join('')}</tr></thead>`
  const bodyHtml = bodyLines.length
    ? `<tbody>${bodyLines.map(line => {
      const cells = parseRow(line)
      return `<tr>${cells.map(cell => `<td>${renderInline(cell, sourceFilePath, resolveUrl)}</td>`).join('')}</tr>`
    }).join('')}</tbody>`
    : ''
  return `<table>${headHtml}${bodyHtml}</table>`
}

/** 将完整 Markdown 文本渲染为 HTML */
export const renderMarkdownToHtml = (
  content: string,
  sourceFilePath: string,
  resolveUrl?: (src: string, sourceFilePath: string) => string
): string => {
  if (!content) return ''

  const lines = content.replace(/\r\n/g, '\n').split('\n')
  const htmlBlocks: string[] = []

  let paragraphBuffer: string[] = []
  let paragraphStartLine = -1

  let tableBuffer: string[] = []
  let tableStartLine = -1

  const listStack: Array<{ kind: 'ul' | 'ol'; indent: number }> = []
  /** 有序列表按缩进层级记录已用编号，跨空行/段落续接，避免每条都从 1 开始 */
  const orderedCounters = new Map<number, number>()

  let inCodeBlock = false
  let codeBlockBuffer: string[] = []
  let codeBlockStartLine = -1

  let inMathBlock = false
  let mathBlockBuffer: string[] = []
  let mathBlockStartLine = -1

  const flushParagraph = () => {
    if (!paragraphBuffer.length) return
    htmlBlocks.push(`<p data-line-start="${paragraphStartLine}">${renderInline(paragraphBuffer.join(' '), sourceFilePath, resolveUrl)}</p>`)
    paragraphBuffer = []
    paragraphStartLine = -1
  }

  const flushTable = () => {
    if (!tableBuffer.length) return
    const tableHtml = buildMarkdownTable(tableBuffer, sourceFilePath, resolveUrl)
    htmlBlocks.push(tableHtml.replace('<table', `<table data-line-start="${tableStartLine}"`))
    tableBuffer = []
    tableStartLine = -1
  }

  const closeLists = () => {
    while (listStack.length) {
      const top = listStack.pop()!
      htmlBlocks.push(`</${top.kind}>`)
    }
  }

  /** 按缩进层级开列表：缩进变浅或同级换类型时先关闭旧列表 */
  const openList = (kind: 'ul' | 'ol', indent: number) => {
    while (listStack.length) {
      const top = listStack[listStack.length - 1]
      if (top.indent > indent || (top.indent === indent && top.kind !== kind)) {
        listStack.pop()
        htmlBlocks.push(`</${top.kind}>`)
      } else {
        break
      }
    }
    flushParagraph()
    flushTable()
    const top = listStack[listStack.length - 1]
    if (!top || top.kind !== kind || top.indent !== indent) {
      listStack.push({ kind, indent })
      if (kind === 'ol') {
        const start = (orderedCounters.get(indent) || 0) + 1
        htmlBlocks.push(`<ol start="${start}">`)
      } else {
        htmlBlocks.push('<ul>')
      }
    }
  }

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index]
    const trimmed = line.trim()
    const currentLineNumber = index + 1

    if (trimmed.startsWith('```')) {
      if (inCodeBlock) {
        inCodeBlock = false
        const code = codeBlockBuffer.join('\n')
        htmlBlocks.push(`<pre data-line-start="${codeBlockStartLine}"><code>${escapeHtml(code)}</code></pre>`)
        codeBlockBuffer = []
        codeBlockStartLine = -1
      } else {
        closeLists()
        flushParagraph()
        flushTable()
        inCodeBlock = true
        codeBlockStartLine = currentLineNumber
      }
      continue
    }
    if (inCodeBlock) {
      codeBlockBuffer.push(line)
      continue
    }

    if (trimmed === '$$') {
      if (inMathBlock) {
        inMathBlock = false
        const formula = mathBlockBuffer.join('\n')
        htmlBlocks.push(`<div class="math-block" data-line-start="${mathBlockStartLine}">${renderFormula(formula, true)}</div>`)
        mathBlockBuffer = []
        mathBlockStartLine = -1
      } else {
        closeLists()
        flushParagraph()
        flushTable()
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
      closeLists()
      flushParagraph()
      flushTable()
      continue
    }

    const isTableCandidate = trimmed.includes('|')
    const nextLine = lines[index + 1]?.trim() || ''
    const looksLikeTableHeader = isTableCandidate && /^\|?[:\-\s|]+\|?$/g.test(nextLine)

    if (looksLikeTableHeader) {
      closeLists()
      flushParagraph()
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

    if (/^#{1,6}\s+/.test(trimmed)) {
      closeLists()
      flushParagraph()
      flushTable()
      const level = Math.min(6, trimmed.match(/^#+/)?.[0].length || 1)
      const title = trimmed.replace(/^#{1,6}\s+/, '')
      htmlBlocks.push(`<h${level} data-line-start="${currentLineNumber}">${renderInline(title, sourceFilePath, resolveUrl)}</h${level}>`)
      continue
    }

    const unorderedMatch = line.match(/^(\s*)[-*+]\s+(.+)$/)
    if (unorderedMatch) {
      openList('ul', unorderedMatch[1].length)
      htmlBlocks.push(`<li data-line-start="${currentLineNumber}">${renderInline(unorderedMatch[2], sourceFilePath, resolveUrl)}</li>`)
      continue
    }

    const orderedMatch = line.match(/^(\s*)\d+\.\s+(.+)$/)
    if (orderedMatch) {
      openList('ol', orderedMatch[1].length)
      orderedCounters.set(
        orderedMatch[1].length,
        (orderedCounters.get(orderedMatch[1].length) || 0) + 1
      )
      htmlBlocks.push(`<li data-line-start="${currentLineNumber}">${renderInline(orderedMatch[2], sourceFilePath, resolveUrl)}</li>`)
      continue
    }

    if (/^<[^>]+>/.test(trimmed)) {
      closeLists()
      flushParagraph()
      flushTable()
      htmlBlocks.push(trimmed)
      continue
    }

    if (paragraphBuffer.length === 0) {
      paragraphStartLine = currentLineNumber
    }
    paragraphBuffer.push(trimmed)
  }

  closeLists()
  flushParagraph()
  flushTable()

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
