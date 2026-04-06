/**
 * 通用树组件类型定义
 */
export interface SmartTreeNode {
  key: string
  title: string
  isFolder?: boolean
  isLeaf?: boolean
  level?: number
  status?: 'pending' | 'uploading' | 'processing' | 'completed' | 'failed'
  visible?: boolean
  parentId?: string
  filePath?: string
  children?: SmartTreeNode[]
  [key: string]: any
}

export type TreeNodeAction = 'rename' | 'add-folder' | 'add-file' | 'delete' | 'view'
