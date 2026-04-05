import type { SmartTreeNode } from '../types/tree'
import type { StructuredIndexItem, DocBlockNode } from '../types/knowledge'
import katex from 'katex'
import 'katex/dist/katex.min.css'
import {
  truncateText,
  formatPositionTag
} from './common'

/**
 * 获取节点的显示文本 (带截断)
 */
export const getNodeDisplayText = (node: DocBlockNode | undefined, fallbackId: string, limit = 24): string => {
  const text = node ? getNodeText(node) : fallbackId
  return truncateText(text, limit)
}

/**
 * 获取节点的层级标签 (如 L1, L2)
 */
export const getNodeLevelTag = (node: DocBlockNode | undefined, nodeMap: Map<string, DocBlockNode>): string | null => {
  if (!node) return null
  const level = getNodeLevel(node, nodeMap)
  return level !== null ? `L${level}` : null
}

/**
 * 获取节点的类型标签
 */
export const getNodeTypeTag = (node: DocBlockNode | undefined): string | null => {
  if (!node || !node.block_type) return null
  return formatStructuredItemType(node.block_type)
}

/**
 * 获取节点的位置标签
 */
export const getNodePositionTag = (node: DocBlockNode | undefined): string | null => {
  if (!node) return null
  return formatPositionTag(node.page_idx ?? 0, node.block_seq ?? 0)
}

export type PreviewFileType = 'pdf' | 'word' | 'markdown' | 'image' | 'text' | 'file'

/**
 * 判断条目是否处于激活状态
 */
export const isItemActive = (item: StructuredIndexItem, activeId: string | null): boolean => {
  if (!activeId) return false
  if (item.id === activeId) return true
  const refs = collectItemRefs(item)
  return refs.includes(activeId)
}

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

/**
 * 获取节点的显示文本
 */
export const getNodeText = (node: DocBlockNode): string => {
  const plainText = String(node.plain_text || '').trim()
  if (shouldSuppressNodePlainText(node)) {
    return getNodeFallbackText(node, node.id)
  }
  return plainText || getNodeFallbackText(node, node.id)
}

/**
 * 获取节点的所有直接子节点
 */
export const getChildren = (nodeId: string, nodeMap: Map<string, DocBlockNode>, childrenMap: Map<string, string[]>): DocBlockNode[] => {
  const childIds = childrenMap.get(nodeId) || []
  return childIds
    .map(cid => nodeMap.get(cid))
    .filter((node): node is DocBlockNode => node !== undefined)
}

/**
 * 简单 Markdown 渲染函数
 * @param content Markdown 文本
 */
export const renderMarkdown = (content: string): string => {
  if (!content) return ''
  // 移除首尾空白和空行
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

const normalizeComparableMathText = (content: string): string => content
  .trim()
  .replace(/^\\\[\s*([\s\S]*?)\s*\\\]$/u, '$1')
  .replace(/^\\\(\s*([\s\S]*?)\s*\\\)$/u, '$1')
  .replace(/^\$\$\s*([\s\S]*?)\s*\$\$$/u, '$1')
  .replace(/^\$\s*([\s\S]*?)\s*\$$/u, '$1')
  .replace(/\s+/g, '')

const getNodeFallbackText = (node: DocBlockNode, fallbackId: string): string => {
  const plainText = String(node.plain_text || '').trim()
  const candidates = [node.title, node.caption, node.footnote]
    .map(value => String(value || '').trim())
    .filter(value => value && value !== plainText)
  if (candidates.length > 0) {
    return candidates[0]
  }
  const typeLabel = formatStructuredItemType(node.block_type || '')
  const positionLabel = formatPositionTag(node.page_idx ?? 0, node.block_seq ?? 0)
  return [typeLabel, positionLabel].filter(Boolean).join(' ') || fallbackId
}

export const isNodeMathRichMediaRedundant = (node: DocBlockNode | undefined | null): boolean => {
  if (!node?.math_content) return false
  const plainText = String(node.plain_text || '').trim()
  const mathContent = String(node.math_content || '').trim()
  if (!plainText || !mathContent) return false
  const normalizedPlainText = normalizeComparableMathText(plainText)
  const normalizedMathContent = normalizeComparableMathText(mathContent)
  if (!normalizedPlainText || !normalizedMathContent) return false
  return normalizedPlainText === normalizedMathContent
    || normalizedPlainText.endsWith(normalizedMathContent)
    || normalizedMathContent.endsWith(normalizedPlainText)
}

export const shouldSuppressNodePlainText = (node: DocBlockNode | undefined | null): boolean => {
  if (!node) return false
  const plainText = String(node.plain_text || '').trim()
  if (!plainText) return false
  if (node.block_type === 'equation_interline' && (node.math_content || node.image_path)) {
    return true
  }
  if (node.math_content && node.image_path) {
    return true
  }
  return isNodeMathRichMediaRedundant(node)
}

/**
 * 获取节点在树中的层级
 */
export const getNodeLevel = (node: DocBlockNode, nodeMap: Map<string, DocBlockNode>): number | null => {
  if (node.derived_level !== null && node.derived_level !== undefined) {
    return node.derived_level
  }
  const parentId = node.parent_uid
  if (!parentId) return null
  const parent = nodeMap.get(parentId)
  if (!parent) return null
  const parentLevel = getNodeLevel(parent, nodeMap)
  if (parentLevel === null) return null
  return parentLevel + 1
}

/**
 * 为索引条目精确查找对应的文档节点。
 */
export const findNodeForItemExact = (item: StructuredIndexItem, nodeMap: Map<string, DocBlockNode>): DocBlockNode | null => {
  const refs = collectItemRefs(item)
  for (const ref of refs) {
    const direct = nodeMap.get(ref)
    if (direct) return direct
  }
  return null
}

/**
 * 为索引条目查找对应的文档节点
 */
export const findNodeForItem = (item: StructuredIndexItem, nodeMap: Map<string, DocBlockNode>): DocBlockNode | null => {
  const direct = findNodeForItemExact(item, nodeMap)
  if (direct) return direct
  if (hasExactItemRef(item, nodeMap)) return null
  const meta = item.meta || {}
  const pageSeq = Number(meta.page_seq || meta.page || 0)
  const blockSeq = Number(meta.block_seq || 0)
  if (pageSeq > 0 && blockSeq > 0) {
    for (const node of nodeMap.values()) {
      if ((Number(node.page_idx ?? 0) + 1) === pageSeq && Number(node.block_seq ?? 0) === blockSeq) {
        return node
      }
    }
  }
  return null
}

/**
 * 获取索引条目的标签列表 (层级、类型、页码等)
 */
export const getItemTags = (item: StructuredIndexItem, nodeMap: Map<string, DocBlockNode>): string[] => {
  const meta = item.meta || {}
  const node = findNodeForItem(item, nodeMap)
  const tags: string[] = []
  const level = Number(meta.level ?? meta.heading_level ?? meta.derived_level ?? (node ? getNodeLevel(node, nodeMap) : null))
  if (Number.isFinite(level) && level > 0) {
    tags.push(`等级 L${Math.round(level)}`)
  }
  tags.push(`类型 ${formatStructuredItemType(item.item_type)}`)
  const pageSeq = Number(meta.page_seq || meta.page || (node ? Number(node.page_idx ?? 0) + 1 : 0))
  if (pageSeq > 0) {
    tags.push(`页 ${pageSeq}`)
  }
  return Array.from(new Set(tags.filter(Boolean)))
}

/**
 * 判断索引条目是否包含富媒体 (表格、公式、图片)
 */
export const hasRichMedia = (item: StructuredIndexItem, nodeMap: Map<string, DocBlockNode>): boolean => {
  const node = findNodeForItem(item, nodeMap)
  if (!node) return false
  return Boolean(node.table_html || node.math_content || node.image_path)
}

/**
 * 渲染文档节点的富媒体内容。
 */
export const renderNodeRichMedia = (
  node: DocBlockNode | undefined | null,
  sourceFilePath?: string,
  options: { includeMath?: boolean } = {}
): string => {
  if (!node) return ''
  const includeMath = options.includeMath !== false
  const sections: string[] = []
  if (node.table_html) {
    sections.push(`<div class="media-table">${node.table_html}</div>`)
  }
  if (node.image_path) {
    const src = resolveAssetUrl(node.image_path, sourceFilePath)
    if (src) {
      sections.push(`<img class="media-image" src="${escapeHtmlAttribute(src)}" alt="${escapeHtmlAttribute(node.plain_text || 'image')}" />`)
    }
  }
  if (includeMath && node.math_content) {
    sections.push(`<div class="media-formula">${renderFormula(node.math_content, true)}</div>`)
  }
  return sections.join('')
}

/**
 * 渲染索引条目的富媒体内容
 */
export const renderItemRichMedia = (item: StructuredIndexItem, nodeMap: Map<string, DocBlockNode>, sourceFilePath?: string): string => {
  const node = findNodeForItem(item, nodeMap)
  return renderNodeRichMedia(node, sourceFilePath)
}

/**
 * 解析索引条目的跳转 ID (优先跳转到节点 ID)
 */
export const resolveSelectId = (item: StructuredIndexItem, nodeMap: Map<string, DocBlockNode>): string => {
  const node = findNodeForItem(item, nodeMap)
  if (node) {
    return node.id
  }
  return item.id
}

const renderInline = (content: string, sourceFilePath: string): string => {
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
    const resolvedSrc = resolveAssetUrl(String(src), sourceFilePath)
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
  const rendered = escapeHtml(withFormulas)
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
  return rendered.replace(/__INLINE_(\d+)__/g, (key) => placeholders.get(key) || key)
}

export const renderMarkdownInlineToHtml = (content: string, sourceFilePath: string): string => {
  if (!content) return ''
  return renderInline(content, sourceFilePath)
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

/**
 * 收集条目的所有关联 ID/引用
 */
export const collectItemRefs = (item: StructuredIndexItem): string[] => {
  const meta = item.meta || {}
  const rawRefs: unknown[] = [
    item.id,
    meta.block_uid,
    meta.blockUid,
    meta.mineru_block_uid,
    meta.mineruBlockUid,
    meta.node_id,
    meta.nodeId,
    meta.block_id,
    meta.blockId,
    meta.source_block_id,
    meta.sourceBlockId,
    meta.mineru_block_id,
    meta.mineruBlockId,
    meta.caption_block_uid,
    meta.footnote_block_uid,
    meta.caption_block_uids,
    meta.footnote_block_uids,
    meta.block_uids,
    meta.node_ids
  ]
  const refs: string[] = []
  rawRefs.forEach(value => {
    if (Array.isArray(value)) {
      value.forEach(inner => {
        const text = String(inner || '').trim()
        if (text) refs.push(text)
      })
      return
    }
    const text = String(value || '').trim()
    if (text) refs.push(text)
  })
  return Array.from(new Set(refs))
}

/**
 * 判断条目是否已经携带可用于精确联动的引用字段。
 */
export const hasExactItemRef = (item: StructuredIndexItem, nodeMap?: Map<string, DocBlockNode>): boolean => {
  const meta = item.meta || {}
  const rawRefs: unknown[] = [
    meta.block_uid,
    meta.blockUid,
    meta.mineru_block_uid,
    meta.mineruBlockUid,
    meta.node_id,
    meta.nodeId,
    meta.block_id,
    meta.blockId,
    meta.source_block_id,
    meta.sourceBlockId,
    meta.mineru_block_id,
    meta.mineruBlockId,
    meta.caption_block_uid,
    meta.footnote_block_uid,
    meta.caption_block_uids,
    meta.footnote_block_uids,
    meta.block_uids,
    meta.node_ids
  ]
  const hasMetaRefs = rawRefs.some(value => Array.isArray(value)
    ? value.some(inner => String(inner || '').trim())
    : Boolean(String(value || '').trim()))
  if (hasMetaRefs) return true
  return nodeMap?.has(item.id) || false
}
