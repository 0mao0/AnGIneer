import type { SmartTreeNode } from '../types/tree'
import type { StructuredIndexItem, DocBlockNode } from '../types/knowledge'
import {
  escapeHtml,
  escapeHtmlAttribute,
  resolveAssetUrl,
  renderFormula,
  renderMarkdown,
  renderMarkdownInlineToHtml,
  renderMarkdownToHtml
} from '@angineer/ui-kit/utils/markdown'
import { getFileIconType, getStatusText } from '@angineer/ui-kit/utils/tree'
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

const iconTypeToPreviewType: Record<string, PreviewFileType> = {
  pdf: 'pdf',
  word: 'word',
  markdown: 'markdown',
  image: 'image',
  text: 'text'
}

export const getPreviewFileType = (node?: Partial<SmartTreeNode> | null): PreviewFileType => {
  const source = node?.filePath || node?.file_path || node?.title || ''
  const iconType = getFileIconType(String(source))
  return iconTypeToPreviewType[iconType] || 'file'
}

export const formatStructuredItemType = (itemType: string): string => {
  if (itemType === 'heading') return '标题'
  if (itemType === 'clause') return '条款'
  if (itemType === 'table') return '表格'
  if (itemType === 'image') return '图片'
  if (itemType === 'title') return '标题'
  if (itemType === 'paragraph') return '正文'
  if (itemType === 'equation_interline') return '公式'
  if (itemType === 'formula_summary') return '公式摘要'
  if (itemType === 'formula_param') return '公式参数'
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

const knowledgeStatusOverrides: Record<string, string> = {
  processing: '解析中',
  failed: '解析失败'
}

export const mapNodeStatusText = (status?: string): string => {
  const key = status || ''
  if (knowledgeStatusOverrides[key]) return knowledgeStatusOverrides[key]
  return getStatusText(key)
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

export {
  escapeHtml,
  escapeHtmlAttribute,
  resolveAssetUrl,
  renderFormula,
  renderMarkdown,
  renderMarkdownInlineToHtml,
  renderMarkdownToHtml
}

/**
 * 收集条目的所有关联 ID/引用
 */

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
  return Boolean(node.table_html || node.math_content || node.image_path || (node.image_paths && node.image_paths.length))
}

const collectNodeImageSources = (node: DocBlockNode): string[] => {
  const imageSources = [
    ...(Array.isArray(node.image_paths) ? node.image_paths : []),
    node.image_path
  ]
    .map(value => String(value || '').trim())
    .filter(Boolean)
  return Array.from(new Set(imageSources))
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
  const imageSources = collectNodeImageSources(node)
  
  if (Array.isArray(node.rich_media_order) && node.rich_media_order.length > 0) {
    const renderedImages = new Set<string>()
    let tableRendered = false
    let mathRendered = false
    
    node.rich_media_order.forEach((item) => {
      if (item.type === 'image' && item.path) {
        const src = resolveAssetUrl(item.path, sourceFilePath)
        if (src && !renderedImages.has(src)) {
          renderedImages.add(src)
          const imageAlt = imageSources.length > 1
            ? `${node.plain_text || 'image'}-${renderedImages.size}`
            : (node.plain_text || 'image')
          sections.push(`<img class="media-image" src="${escapeHtmlAttribute(src)}" alt="${escapeHtmlAttribute(imageAlt)}" />`)
        }
      } else if (item.type === 'table' && !tableRendered && node.table_html) {
        tableRendered = true
        sections.push(`<div class="media-table">${node.table_html}</div>`)
      } else if (item.type === 'math' && !mathRendered && includeMath && node.math_content) {
        mathRendered = true
        sections.push(`<div class="media-formula">${renderFormula(node.math_content, true)}</div>`)
      }
    })
    
    imageSources.forEach((imagePath) => {
      const src = resolveAssetUrl(imagePath, sourceFilePath)
      if (src && !renderedImages.has(src)) {
        renderedImages.add(src)
        const imageAlt = imageSources.length > 1
          ? `${node.plain_text || 'image'}-${renderedImages.size}`
          : (node.plain_text || 'image')
        sections.push(`<img class="media-image" src="${escapeHtmlAttribute(src)}" alt="${escapeHtmlAttribute(imageAlt)}" />`)
      }
    })
    
    if (!tableRendered && node.table_html) {
      sections.push(`<div class="media-table">${node.table_html}</div>`)
    }
    if (!mathRendered && includeMath && node.math_content) {
      sections.push(`<div class="media-formula">${renderFormula(node.math_content, true)}</div>`)
    }
  } else {
    imageSources.forEach((imagePath, index) => {
      const src = resolveAssetUrl(imagePath, sourceFilePath)
      if (src) {
        const imageAlt = imageSources.length > 1
          ? `${node.plain_text || 'image'}-${index + 1}`
          : (node.plain_text || 'image')
        sections.push(`<img class="media-image" src="${escapeHtmlAttribute(src)}" alt="${escapeHtmlAttribute(imageAlt)}" />`)
      }
    })
    if (node.table_html) {
      sections.push(`<div class="media-table">${node.table_html}</div>`)
    }
    if (includeMath && node.math_content) {
      sections.push(`<div class="media-formula">${renderFormula(node.math_content, true)}</div>`)
    }
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

/** 从行文本中提取页码提示 */
export const extractPageHintFromLine = (line: string): number | null => {
  const match = line.match(/[（(]\s*(\d{1,4})\s*[）)]\s*$/)
  if (!match) return null
  const page = Number(match[1])
  if (!Number.isFinite(page) || page <= 0) return null
  return Math.round(page)
}

/** 当无结构化索引时，从文档内容中提取标题行作为回退索引 */
export const buildMiddleFallbackItems = (content: string): StructuredIndexItem[] => {
  if (!content.trim()) return []
  const lines = content.split('\n')
  const result: StructuredIndexItem[] = []
  let orderIndex = 0
  lines.forEach((line: string, index: number) => {
    const trimmed = (line || '').trim()
    if (!trimmed) return
    const headingMatch = trimmed.match(/^(#{1,6})\s+(.+)$/)
    const numberedMatch = trimmed.match(/^(\d+(?:\.\d+)*)(?:[、.)])?\s*(.*)$/)
    if (!headingMatch && !numberedMatch) return
    const numberedPrefix = numberedMatch?.[1] || ''
    const numberedText = (numberedMatch?.[2] || '').trim()
    const text = (
      headingMatch?.[2]
      || (numberedPrefix && numberedText ? `${numberedPrefix} ${numberedText}` : numberedPrefix)
      || numberedText
      || ''
    ).trim().slice(0, 200)
    if (!text) return
    const pageHint = extractPageHintFromLine(trimmed)
    result.push({
      id: `middle-${index + 1}`,
      item_type: headingMatch ? 'heading' : 'section',
      title: text,
      content: text,
      order_index: orderIndex++,
      meta: {
        line_start: index + 1,
        line_end: index + 1,
        heading_level: headingMatch ? headingMatch[1].length : undefined,
        page: pageHint ?? undefined,
        page_no: pageHint ?? undefined
      }
    })
  })
  return result
}
