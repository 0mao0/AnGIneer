/**
 * 通用工具函数
 * 包含文本处理、树操作、状态映射等跨组件逻辑
 */

/**
 * 截断文本并添加省略号
 */
export const truncateText = (text: string, length: number = 24): string => {
  if (!text) return ''
  return text.length > length ? text.slice(0, length) + '…' : text
}

/**
 * 高亮文本中的关键词
 */
export const highlightText = (text: string, keyword: string): string => {
  if (!keyword) return text
  const regex = new RegExp(`(${keyword})`, 'gi')
  return text.replace(regex, '<mark style="background: #ffe58f; padding: 0 2px;">$1</mark>')
}

/**
 * 根据文件名获取文件图标类型
 */
export const getFileIconType = (fileName: string): string => {
  const ext = fileName.toLowerCase().split('.').pop() || ''
  const iconMap: Record<string, string> = {
    pdf: 'pdf',
    doc: 'word',
    docx: 'word',
    xls: 'excel',
    xlsx: 'excel',
    ppt: 'ppt',
    pptx: 'ppt',
    txt: 'text',
    md: 'markdown',
    jpg: 'image',
    jpeg: 'image',
    png: 'image',
    gif: 'image',
    zip: 'zip',
    rar: 'zip',
    mp4: 'video',
    mp3: 'audio'
  }
  return iconMap[ext] || 'file'
}

/**
 * 获取文件图标颜色
 */
export const getFileIconColor = (fileName: string): string => {
  const type = getFileIconType(fileName)
  const colorMap: Record<string, string> = {
    pdf: '#ff4d4f',
    word: '#1890ff',
    excel: '#52c41a',
    ppt: '#fa8c16',
    text: '#8c8c8c',
    markdown: '#13c2c2',
    image: '#eb2f96',
    zip: '#722ed1',
    video: '#f5222d',
    audio: '#fa541c',
    file: '#8c8c8c'
  }
  return colorMap[type] || '#8c8c8c'
}

/**
 * 获取状态颜色
 */
export const getStatusColor = (status: string): string => {
  const colors: Record<string, string> = {
    pending: 'default',
    uploading: 'processing',
    processing: 'processing',
    completed: 'success',
    failed: 'error'
  }
  return colors[status] || 'default'
}

/**
 * 获取状态文本
 */
export const getStatusText = (status: string): string => {
  const texts: Record<string, string> = {
    pending: '待处理',
    uploading: '上传中',
    processing: '处理中',
    completed: '已完成',
    failed: '失败'
  }
  return texts[status] || '未知'
}

/**
 * 递归过滤树节点
 */
export function filterTree<T extends { title: string; children?: T[] }>(
  nodes: T[],
  keyword: string
): T[] {
  const result: T[] = []
  const lowerKeyword = keyword.toLowerCase()

  for (const node of nodes) {
    const matchTitle = node.title.toLowerCase().includes(lowerKeyword)
    const filteredChildren = node.children ? filterTree(node.children, keyword) : []

    if (matchTitle || filteredChildren.length > 0) {
      result.push({
        ...node,
        children: filteredChildren.length > 0 ? filteredChildren : node.children
      })
    }
  }

  return result
}

/**
 * 收集所有需要展开的父节点 keys
 */
export function getExpandedKeysForSearch<T extends { key: string; title: string; children?: T[] }>(
  nodes: T[],
  keyword: string,
  parentKeys: string[] = []
): string[] {
  const expandedKeys: string[] = []
  const lowerKeyword = keyword.toLowerCase()
  
  for (const node of nodes) {
    const matchTitle = node.title.toLowerCase().includes(lowerKeyword)
    const childKeys = node.children ? getExpandedKeysForSearch(node.children, keyword, [...parentKeys, node.key]) : []
    
    if (matchTitle || childKeys.length > 0) {
      if (parentKeys.length > 0) {
        expandedKeys.push(...parentKeys)
      }
      expandedKeys.push(...childKeys)
    }
  }
  
  return [...new Set(expandedKeys)]
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
 * 生成唯一消息 ID
 */
export const generateMessageId = (): string => {
  return `msg-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`
}

/**
 * 估算消息的 token 数量
 */
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
