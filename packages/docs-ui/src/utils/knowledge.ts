import type { SmartTreeNode } from '../types/tree'
import katex from 'katex'

export type PreviewFileType = 'pdf' | 'word' | 'markdown' | 'image' | 'text' | 'file'

export const getFileExtension = (path: string): string => {
  if (!path) return ''
  const match = path.match(/\.([a-zA-Z0-9]+)$/)
  return match ? match[1].toLowerCase() : ''
}

export const getPreviewFileType = (node?: Partial<SmartTreeNode> | null): PreviewFileType => {
  const source = node?.filePath || node?.file_path || node?.title || ''
  const ext = String(source).toLowerCase().split('.').pop() || ''
  if (ext === 'pdf') return 'pdf'
  if (ext === 'doc' || ext === 'docx') return 'word'
  if (ext === 'md' || ext === 'markdown') return 'markdown'
  if (['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'svg'].includes(ext)) return 'image'
  if (['txt', 'json', 'xml', 'csv', 'log', 'js', 'ts', 'py', 'java', 'cpp', 'c', 'h', 'html', 'css'].includes(ext)) return 'text'
  return 'file'
}

export const formatStructuredItemType = (itemType: string): string => {
  if (itemType === 'heading') return '标题'
  if (itemType === 'clause') return '条款'
  if (itemType === 'table') return '表格'
  if (itemType === 'image') return '图片'
  if (itemType === 'title') return '标题'
  if (itemType === 'paragraph') return '正文'
  if (itemType === 'equation_interline') return '公式'
  if (itemType === 'list') return '列表'
  return itemType || '未知'
}

export const stripMarkdownSyntax = (value: string): string => value
  .replace(/!\[[^\]]*\]\([^)]+\)/g, '')
  .replace(/`([^`]+)`/g, '$1')
  .replace(/\*\*([^*]+)\*\*/g, '$1')
  .replace(/\*([^*]+)\*/g, '$1')
  .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
  .replace(/<[^>]+>/g, '')
  .replace(/\s+/g, ' ')
  .trim()

const stageMap: Record<string, string> = {
  queued: '任务排队中',
  initializing: '正在初始化',
  mineru_processing: 'MinerU 解析中',
  reading_markdown: '读取 Markdown',
  saving_markdown: '保存解析结果',
  completed: '解析完成',
  failed: '解析失败'
}

export const mapParseStageText = (stage?: string, parseError?: string): string => {
  if (parseError) return `解析失败：${parseError}`
  const normalized = stage || 'processing'
  return stageMap[normalized] || normalized
}

export const mapNodeStatusText = (status?: string): string => {
  const statusTextMap: Record<string, string> = {
    pending: '待处理',
    uploading: '上传中',
    processing: '解析中',
    completed: '已完成',
    failed: '解析失败'
  }
  return statusTextMap[status || ''] || '未知'
}

const escapeHtml = (content: string): string => content
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')

const escapeHtmlAttribute = (content: string): string => content
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

const resolveAssetUrl = (source: string, sourceFilePath: string): string => {
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
  const basePath = resolveMarkdownAssetBasePath(sourceFilePath)
  if (!basePath) return trimmed
  const normalizedBase = basePath.endsWith('\\') || basePath.endsWith('/') ? basePath : `${basePath}\\`
  const absolutePath = `${normalizedBase}${trimmed}`.replace(/[\\/]+/g, '\\')
  return `/api/files?path=${encodeURIComponent(absolutePath)}`
}

const renderFormula = (formula: string, displayMode: boolean): string => {
  try {
    return katex.renderToString(formula, { throwOnError: false, displayMode })
  } catch {
    const fallbackClass = displayMode ? 'math-block-fallback' : 'math-inline-fallback'
    return `<span class="${fallbackClass}">${escapeHtml(formula)}</span>`
  }
}

const renderInline = (content: string, sourceFilePath: string): string => {
  const placeholders = new Map<string, string>()
  let placeholderIndex = 0
  const setPlaceholder = (html: string) => {
    const key = `__INLINE_${placeholderIndex++}__`
    placeholders.set(key, html)
    return key
  }
  const withImages = content.replace(/!\[([^\]]*)\]\(([^)\s]+)(?:\s+"([^"]+)")?\)/g, (_, alt, src, title) => {
    const resolvedSrc = resolveAssetUrl(String(src), sourceFilePath)
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

const buildMarkdownTable = (tableLines: string[], sourceFilePath: string): string => {
  const parseRow = (line: string) =>
    line
      .trim()
      .replace(/^\||\|$/g, '')
      .split('|')
      .map(cell => cell.trim())

  const headers = parseRow(tableLines[0])
  const bodyLines = tableLines.slice(2)
  const headHtml = `<thead><tr>${headers.map(cell => `<th>${renderInline(cell, sourceFilePath)}</th>`).join('')}</tr></thead>`
  const bodyHtml = bodyLines.length
    ? `<tbody>${bodyLines.map(line => {
      const cells = parseRow(line)
      return `<tr>${cells.map(cell => `<td>${renderInline(cell, sourceFilePath)}</td>`).join('')}</tr>`
    }).join('')}</tbody>`
    : ''
  return `<table>${headHtml}${bodyHtml}</table>`
}

export const renderMarkdownToHtml = (content: string, sourceFilePath: string): string => {
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
    htmlBlocks.push(`<p data-line-start="${paragraphStartLine}">${renderInline(paragraphBuffer.join(' '), sourceFilePath)}</p>`)
    paragraphBuffer = []
    paragraphStartLine = -1
  }

  const flushTable = () => {
    if (!tableBuffer.length) return
    const tableHtml = buildMarkdownTable(tableBuffer, sourceFilePath)
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

    if (/^#{1,6}\s+/.test(trimmed)) {
      flushParagraph()
      flushTable()
      closeLists()
      const level = Math.min(6, trimmed.match(/^#+/)?.[0].length || 1)
      const title = trimmed.replace(/^#{1,6}\s+/, '')
      htmlBlocks.push(`<h${level} data-line-start="${currentLineNumber}">${renderInline(title, sourceFilePath)}</h${level}>`)
      continue
    }

    const unorderedMatch = trimmed.match(/^[-*+]\s+(.+)$/)
    if (unorderedMatch) {
      flushParagraph()
      flushTable()
      if (!inUnorderedList) {
        closeLists()
        htmlBlocks.push('<ul>')
        inUnorderedList = true
      }
      htmlBlocks.push(`<li data-line-start="${currentLineNumber}">${renderInline(unorderedMatch[1], sourceFilePath)}</li>`)
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
      htmlBlocks.push(`<li data-line-start="${currentLineNumber}">${renderInline(orderedMatch[1], sourceFilePath)}</li>`)
      continue
    }

    if (/^<[^>]+>/.test(trimmed)) {
      flushParagraph()
      flushTable()
      closeLists()
      htmlBlocks.push(trimmed)
      continue
    }

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
