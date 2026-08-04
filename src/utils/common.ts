/**
 * 通用工具函数
 * 包含文本处理、树操作、状态映射等跨组件逻辑
 * 树相关工具函数已本地化，docs-ui 不再依赖 @angineer/ui-kit。
 */

/** 高亮搜索关键词 */
export const highlightText = (text: string, keyword: string): string => {
  if (!keyword) return text
  const escapedKeyword = keyword.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const regex = new RegExp(`(${escapedKeyword})`, 'gi')
  return text.replace(regex, '<mark>$1</mark>')
}

/** 根据文件名推断图标类型 */
export const getFileIconType = (fileName: string): string => {
  const lowerFileName = fileName.toLowerCase()
  if (lowerFileName.endsWith('.pdf')) return 'pdf'
  if (/\.(doc|docx)$/.test(lowerFileName)) return 'word'
  if (/\.(xls|xlsx|csv)$/.test(lowerFileName)) return 'excel'
  if (/\.(ppt|pptx)$/.test(lowerFileName)) return 'ppt'
  if (/\.(jpg|jpeg|png|gif|webp|svg)$/.test(lowerFileName)) return 'image'
  if (/\.(zip|rar|7z|tar|gz)$/.test(lowerFileName)) return 'zip'
  if (lowerFileName.endsWith('.md')) return 'markdown'
  if (/\.(txt|json|yaml|yml|xml)$/.test(lowerFileName)) return 'text'
  return 'file'
}

/** 获取文件图标颜色 */
export const getFileIconColor = (fileName: string): string => {
  const iconType = getFileIconType(fileName)
  const colorMap: Record<string, string> = {
    pdf: '#ff4d4f',
    word: '#1890ff',
    excel: '#52c41a',
    ppt: '#fa8c16',
    image: '#722ed1',
    zip: '#8c8c8c',
    markdown: '#13c2c2',
    text: '#8c8c8c',
    file: '#8c8c8c'
  }
  return colorMap[iconType] || colorMap.file
}

/** 获取状态颜色 */
export const getStatusColor = (status: string): string => {
  const colorMap: Record<string, string> = {
    pending: 'default',
    uploading: 'processing',
    processing: 'processing',
    completed: 'success',
    partial: 'warning',
    failed: 'error',
    cancelled: 'default'
  }
  return colorMap[status] || 'default'
}

/** 获取状态文案 */
export const getStatusText = (status: string): string => {
  const textMap: Record<string, string> = {
    pending: '待处理',
    uploading: '上传中',
    processing: '处理中',
    completed: '已完成',
    partial: '部分完成',
    failed: '失败',
    cancelled: '已取消'
  }
  return textMap[status] || status || '未知'
}

/** 根据关键词过滤树节点 */
export function filterTree<T extends { title: string; children?: T[] }>(nodes: T[], keyword: string): T[] {
  return nodes.reduce<T[]>((result, node) => {
    const title = String(node.title || '').toLowerCase()
    const filteredChildren = node.children ? filterTree(node.children, keyword) : []
    if (title.includes(keyword) || filteredChildren.length > 0) {
      result.push({
        ...node,
        children: filteredChildren
      })
    }
    return result
  }, [])
}

/** 收集搜索命中路径上的父节点 key */
export function getExpandedKeysForSearch<T extends { key: string; title: string; children?: T[] }>(
  nodes: T[],
  keyword: string,
  parentKeys: string[] = []
): string[] {
  return nodes.reduce<string[]>((result, node) => {
    const title = String(node.title || '').toLowerCase()
    const currentParentKeys = [...parentKeys, node.key]
    const childKeys = node.children
      ? getExpandedKeysForSearch(node.children, keyword, currentParentKeys)
      : []
    if (title.includes(keyword)) {
      result.push(...parentKeys)
    }
    result.push(...childKeys)
    return result
  }, [])
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
