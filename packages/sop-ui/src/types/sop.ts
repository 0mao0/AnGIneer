/**
 * sop-ui 领域类型定义。
 * SmartTreeNode 从 @angineer/ui-kit 统一导出，不在本地重复定义。
 */
import type { SmartTreeNode } from '@angineer/ui-kit'
import type { Node, Edge } from '@vue-flow/core'

export interface SOPTreeNode extends SmartTreeNode {
  isFolder: boolean
  description?: string
  category?: string
  children?: SOPTreeNode[]
}

/** SOP 步骤定义 */
export interface SopStep {
  id: string
  name?: string
  name_zh?: string
  name_en?: string
  description?: string
  tool: string
  inputs: Record<string, any>
  outputs: Record<string, string>
  next_step_id?: string
  on_failure?: string
  notes?: string
  analysis_status?: string
}

/** SOP 完整数据 */
export interface SopData {
  id: string
  name_zh: string
  name_en?: string
  description?: string
  folder_id?: string
  steps: SopStep[]
  blackboard?: Record<string, any> | null
}

/** SOP 文件夹 */
export interface SopFolder {
  folder_id: string
  title: string
  parent_folder_id?: string | null
}

/** SOP 列表项 */
export interface SopListItem {
  id: string
  name_zh: string
  name_en?: string
  description?: string
  folder_id?: string | null
  step_count: number
  source?: 'raw' | 'json'
}

/** Vue Flow 节点类型别名 */
export type SopFlowNode = Node<{
  step: SopStep
  stepIndex: number
}>

/** Vue Flow 边类型别名 */
export type SopFlowEdge = Edge
