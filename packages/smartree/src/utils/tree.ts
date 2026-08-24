/** 转义 HTML 特殊字符，供 v-html 高亮安全使用 */
export const escapeHtml = (text: string): string =>
  text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')

/** 高亮搜索关键词：先转义文本再包 <mark>，标题含 HTML 也不会被注入 */
export const highlightText = (text: string, keyword: string): string => {
  if (!keyword) return escapeHtml(text)
  const escapedKeyword = keyword.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const regex = new RegExp(`(${escapedKeyword})`, 'gi')
  return escapeHtml(text).replace(regex, '<mark>$1</mark>')
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
    file: '#8c8c8c',
  }
  return colorMap[iconType] || colorMap.file
}

/** 获取状态标签颜色 */
export const getStatusColor = (status: string): string => {
  const colorMap: Record<string, string> = {
    pending: 'default',
    uploading: 'processing',
    processing: 'processing',
    completed: 'success',
    partial: 'warning',
    failed: 'error',
    cancelled: 'default',
  }
  return colorMap[status] || 'default'
}

/** 获取状态标签文案 */
export const getStatusText = (status: string): string => {
  const textMap: Record<string, string> = {
    pending: '待处理',
    uploading: '上传中',
    processing: '处理中',
    completed: '已完成',
    partial: '部分完成',
    failed: '失败',
    cancelled: '已取消',
  }
  return textMap[status] || status || '未知'
}

/** 根据关键词过滤树节点，保留命中节点的祖先链 */
export function filterTree<T extends { title: string; children?: any }>(nodes: T[], keyword: string): T[] {
  return nodes.reduce<T[]>((result, node) => {
    const title = String(node.title || '').toLowerCase()
    const filteredChildren = node.children ? filterTree(node.children, keyword) : []
    if (title.includes(keyword) || filteredChildren.length > 0) {
      result.push({
        ...node,
        children: filteredChildren,
      })
    }
    return result
  }, [])
}

/** 收集搜索命中路径上的父节点 key */
export function getExpandedKeysForSearch<T extends { key: string; title: string; children?: any }>(
  nodes: T[],
  keyword: string,
  parentKeys: string[] = [],
): string[] {
  return nodes.reduce<string[]>((result, node) => {
    const title = String(node.title || '').toLowerCase()
    const currentParentKeys = [...parentKeys, node.key]
    const childKeys = node.children ? getExpandedKeysForSearch(node.children, keyword, currentParentKeys) : []
    if (title.includes(keyword)) {
      result.push(...parentKeys)
    }
    result.push(...childKeys)
    return result
  }, [])
}

/** 轻量克隆树：保留 Date/Map/函数等非序列化字段（替代 JSON.parse(JSON.stringify())） */
export function cloneTree<T extends { key: string; title: string; children?: any }>(nodes: T[]): T[] {
  return nodes.map((node) => ({
    ...node,
    children: node.children ? cloneTree(node.children) : node.children,
  }))
}

/** 可排序/可组树的扁平节点结构（结构类型，不依赖 SmartTreeNode，避免工具与类型互相引用） */
export interface SortableTreeNode {
  key: string
  title: string
  isFolder?: boolean
  parentId?: string | null
  children?: SortableTreeNode[]
  sort_order?: number
  sortOrder?: number
  [key: string]: any
}

/** 节点排序：先按 sort_order/sortOrder，再按标题中文排序；foldersFirst 时文件夹在前 */
export function sortTreeNodes<T extends SortableTreeNode>(
  nodes: T[],
  options: { foldersFirst?: boolean } = {},
): T[] {
  const order = (n: SortableTreeNode): number => {
    const raw = n.sort_order ?? n.sortOrder
    return typeof raw === 'number' ? raw : Number.MAX_SAFE_INTEGER
  }
  const compare = (a: SortableTreeNode, b: SortableTreeNode): number => {
    const orderDiff = order(a) - order(b)
    if (orderDiff !== 0) return orderDiff
    return String(a.title || '').localeCompare(String(b.title || ''), 'zh-CN')
  }
  const folders = nodes.filter((n) => n.isFolder).sort(compare)
  const files = nodes.filter((n) => !n.isFolder).sort(compare)
  return options.foldersFirst ? [...folders, ...files] : [...files, ...folders]
}

/** 从扁平 folders + items 构建树：按 getParentKey 挂载，各层用 sortTreeNodes 排序；父文件夹未知的节点挂到根级末尾 */
export function buildTreeFromFlat<T extends SortableTreeNode>(options: {
  folders: T[]
  items: T[]
  getParentKey?: (node: T) => string | null
  foldersFirst?: boolean
}): T[] {
  const { folders, items, getParentKey = (n) => n.parentId ?? null, foldersFirst = true } = options
  const knownFolderKeys = new Set(folders.map((f) => f.key))
  const childNodes = (parentKey: string | null): T[] => {
    const children = [
      ...folders.filter((f) => getParentKey(f) === parentKey),
      ...items.filter((i) => getParentKey(i) === parentKey),
    ]
    return sortTreeNodes(children, { foldersFirst })
  }
  for (const folder of folders) {
    folder.children = childNodes(folder.key)
  }
  const orphanItems = items.filter((i) => {
    const parent = getParentKey(i)
    return parent !== null && parent !== undefined && !knownFolderKeys.has(parent)
  })
  return [...childNodes(null), ...orphanItems]
}
