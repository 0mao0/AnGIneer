/**
 * 通用树组件类型定义
 */

/** 树节点数据接口 */
export interface SmartTreeNode {
  key: string
  title: string
  isFolder?: boolean
  isLeaf?: boolean
  level?: number
  status?: 'pending' | 'uploading' | 'processing' | 'completed' | 'failed'
  visible?: boolean
  parentId?: string
  children?: SmartTreeNode[]
  [key: string]: any
}

/** 树节点操作类型 */
export type TreeNodeAction = 'rename' | 'add-folder' | 'add-file' | 'delete' | 'view'
