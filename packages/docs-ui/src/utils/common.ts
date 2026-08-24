/**
 * 通用工具函数
 * 包含文本处理、树操作、状态映射等跨组件逻辑
 * 树相关工具函数统一由 @angineer/smartree 提供。
 */

export {
  highlightText,
  getFileIconType,
  getFileIconColor,
  getStatusColor,
  getStatusText,
  filterTree,
  getExpandedKeysForSearch
} from '@angineer/smartree'

/** 读取节点字段：<field>_corrected 并列字段优先，原始字段兜底 */
export const effectiveField = <T = unknown>(
  node: object | null | undefined,
  field: string,
): T | undefined => {
  if (!node) return undefined
  const record = node as Record<string, unknown>
  const corrected = record[`${field}_corrected`]
  return (corrected ?? record[field]) as T | undefined
}

/** 生成唯一消息 ID */
export function generateMessageId(): string {
  return `msg-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`
}

/** 估算消息的 token 数量 */
export function estimateTokens(content: string): number {
  if (!content) return 0
  let tokens = 0
  for (const char of content) {
    if (/[\u4e00-\u9fa5]/.test(char)) {
      tokens += 1.5
    } else {
      tokens += 0.5
    }
  }
  return Math.ceil(tokens)
}

/**
 * 截断文本并添加省略号
 */
export const truncateText = (text: string, length: number = 24): string => {
  if (!text) return ''
  return text.length > length ? text.slice(0, length) + '…' : text
}

/**
 * 格式化位置标签 (P1b1 格式)
 */
export const formatPositionTag = (pageIdx: number | string, blockSeq: number | string): string | null => {
  const page = Number(pageIdx ?? 0) + 1
  const block = Number(blockSeq ?? 0)
  if (!Number.isFinite(page) || page <= 0 || !Number.isFinite(block) || block <= 0) {
    return null
  }
  return `P${page}b${block}`
}

/**
 * 移除 Markdown 语法
 */
export const stripMarkdownSyntax = (value: string): string => value
  .replace(/!\[[^\]]*\]\([^)]+\)/g, '')
  .replace(/`([^`]+)`/g, '$1')
  .replace(/\*\*([^*]+)\*\*/g, '$1')
  .replace(/\*([^*]+)\*/g, '$1')
  .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
  .replace(/<[^>]+>/g, '')
  .replace(/\s+/g, ' ')
  .trim()

/**
 * 获取条目的显示标题
 */
export const getDisplayTitle = (item: any): string => {
  const title = (item.title || '').trim()
  const content = stripMarkdownSyntax((item.content || '').trim())
  const sectionNo = String(item.meta?.section_no || '').trim()
  const numberedPrefix = (title || content).match(/^(\d+(?:\.\d+){1,})/)
  if (sectionNo) {
    if (title && !title.toLowerCase().startsWith('section')) return `${sectionNo} ${title}`.trim()
    if (content) return `${sectionNo} ${content}`.trim()
    return sectionNo
  }
  if (title && title.toLowerCase() !== 'section') {
    return title
  }
  if (numberedPrefix && content && !content.startsWith(numberedPrefix[1])) {
    return `${numberedPrefix[1]} ${content}`.trim()
  }
  return content || title || '未命名条目'
}

/**
 * 获取条目的主要正文内容 (避免与标题重复)
 */
export const getPrimaryContent = (item: any): string => {
  const title = getDisplayTitle(item)
  const content = stripMarkdownSyntax((item.content || '').trim())
  if (!content) return ''
  if (!title) return content
  if (title === content) return ''
  if (content.startsWith(title) && content.length <= title.length + 4) return ''
  return content
}

/**
 * 获取多媒体摘要文本块 (图片标题、表格内容、脚注等)
 */
export const getMediaTextBlocks = (item: any): string[] => {
  const meta = item.meta || {}
  const lines: string[] = []
  const append = (label: string, value: unknown) => {
    const text = stripMarkdownSyntax(String(value || '').trim())
    if (!text) return
    lines.push(`${label}：${text}`)
  }
  append('题目', meta.caption || meta.table_caption || meta.image_caption || meta.title)
  append('内容', meta.text || meta.body || meta.content || item.content)
  append('脚注', meta.footnote || meta.table_footnote || meta.image_footnote || meta.note)
  return Array.from(new Set(lines))
}

/**
 * 将输入值转换为有效的行号（正整数）
 * @param value 输入值
 * @returns 有效行号或 null
 */
export const toValidLine = (value: unknown): number | null => {
  const line = Number(value || 0)
  if (!Number.isFinite(line) || line <= 0) return null
  return Math.round(line)
}

/**
 * 根据行号获取文本偏移量
 */
export const getOffsetByLine = (text: string, line: number): number => {
  if (line <= 1) return 0
  let currentLine = 1
  let offset = 0
  while (offset < text.length && currentLine < line) {
    if (text[offset] === '\n') {
      currentLine += 1
    }
    offset += 1
  }
  return offset
}
