import type { SmartTreeNode, SmartTreeNodeStatus, TreeNodeAction, DropEvent } from '@angineer/smartree'

export type { SmartTreeNode, SmartTreeNodeStatus, TreeNodeAction, DropEvent }

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
