/**
 * docs-ui 领域树类型定义。
 * SmartTreeNode 和 TreeNodeAction 从 @angineer/ui-kit 统一导出，不在本地重复定义。
 * SOPTreeNode 已迁移至 @angineer/sop-ui，不在本地定义。
 */
import type { SmartTreeNode as BaseSmartTreeNode, TreeNodeAction } from '@angineer/ui-kit'

export type { TreeNodeAction }
export type SmartTreeNode = BaseSmartTreeNode

export type KnowledgeNodeStatus = 'pending' | 'uploading' | 'processing' | 'completed' | 'failed'
export type KnowledgeStrategy = 'doc_blocks_graph_v1'

export interface KnowledgeTreeNode extends BaseSmartTreeNode {
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
