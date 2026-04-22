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
  filePath?: string
  children?: SmartTreeNode[]
  [key: string]: any
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

export interface SOPTreeNode extends SmartTreeNode {
  isFolder: boolean
  description?: string
  category?: string
  children?: SOPTreeNode[]
}

/** 树节点操作类型 */
export type TreeNodeAction = 'rename' | 'add-folder' | 'add-file' | 'delete' | 'view'
