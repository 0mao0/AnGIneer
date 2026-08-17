/**
 * docs-ui 领域树类型定义。
 * 类型已本地化，docs-ui 不再依赖 @angineer/ui-kit。
 * SOPTreeNode 已迁移至 @angineer/sop-ui，不在本地定义。
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

export type KnowledgeNodeStatus = SmartTreeNodeStatus
export type KnowledgeStrategy = 'doc_blocks_graph_v1'

export interface KnowledgeTreeNode extends SmartTreeNode {
  isFolder: boolean
  visible: boolean
  status: KnowledgeNodeStatus
  libraryId?: string
  file_path?: string
  parseProgress?: number
  parseStage?: string
  parseStep?: string
  parseError?: string
  parseTaskId?: string
  strategy?: KnowledgeStrategy
  children?: KnowledgeTreeNode[]
}
