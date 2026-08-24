export type SmartTreeNodeStatus =
  | 'pending'
  | 'uploading'
  | 'processing'
  | 'queued'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'partial'

/**
 * 通用树节点。业务字段通过索引签名挂载（如 parseProgress），
 * 更严格的类型由消费方继承本接口后定义。
 */
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

export type TreeNodeAction = 'rename' | 'add-folder' | 'add-file' | 'delete' | 'batch-delete' | 'view'

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
  /** 拖拽后的完整树，调用方可直接用于更新状态 */
  resultTree: SmartTreeNode[]
}

/** SmartTree 通过 defineExpose 暴露的命令式 API（wrapper 组件 ref 透传时使用） */
export interface SmartTreeExposed {
  expandAll: () => void
  collapseAll: () => void
  getSelectedNodes: () => SmartTreeNode[]
  validateFileType: (file: File) => boolean
  getAllowedFileTypesDesc: () => string
  searchText: string
  expandedKeys: string[]
  selectedKeys: string[]
}
