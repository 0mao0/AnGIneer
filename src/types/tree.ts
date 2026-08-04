/**
 * docs-ui 领域树类型定义。
 * 类型已本地化，docs-ui 不再依赖 @angineer/ui-kit。
 * SOPTreeNode 已迁移至 @angineer/sop-ui，不在本地定义。
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

export type KnowledgeNodeStatus = 'pending' | 'uploading' | 'processing' | 'completed' | 'failed'
export type KnowledgeStrategy = 'doc_blocks_graph_v1'

export interface KnowledgeTreeNode extends SmartTreeNode {
  isFolder: boolean
  visible: boolean
  status: KnowledgeNodeStatus
  file_path?: string
  parseProgress?: number
  parseStage?: string
  parseError?: string
  parseTaskId?: string
  strategy?: KnowledgeStrategy
  children?: KnowledgeTreeNode[]
}
