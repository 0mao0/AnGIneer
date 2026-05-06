/**
 * 树组件工具函数集合。
 * 从 SmartTree 内部提取，供 ui-kit 和 docs-ui 共享。
 */

/** 高亮搜索关键字 */
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
    failed: 'error'
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
    failed: '失败'
  }
  return textMap[status] || status || '未知'
}

/** 根据关键字过滤树节点 */
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
