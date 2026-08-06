/**
 * 通用树组件类型定义
 */
export type SmartTreeNodeStatus =
  | 'pending'
  | 'uploading'
  | 'processing'
  | 'queued'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'partial'

export interface SmartTreeNode {
  key: string
  title: string
  isFolder?: boolean
  isLeaf?: boolean
  level?: number
  status?: SmartTreeNodeStatus
  visible?: boolean
  parentId?: string
  filePath?: string
  children?: SmartTreeNode[]
  [key: string]: any
}

export type TreeNodeAction = 'rename' | 'add-folder' | 'add-file' | 'delete' | 'view'

export interface DropEvent {
  dragKey: string
  dragKeys: string[]
  dragNode: SmartTreeNode
  dragNodes: SmartTreeNode[]
  dropKey: string
  dropNode: SmartTreeNode
  dropToGap: boolean
  targetParentKey: string | null
  siblings: SmartTreeNode[]
}
