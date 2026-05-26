/**
 * sop-ui 领域类型定义。
 * SmartTreeNode 从 @angineer/ui-kit 统一导出，不在本地重复定义。
 */
import type { InlineCitationDraftValue, SmartTreeNode } from '@angineer/ui-kit'
import type { Node, Edge } from '@vue-flow/core'

export interface SOPTreeNode extends SmartTreeNode {
  isFolder: boolean
  description?: string
  category?: string
  sortOrder?: number
  children?: SOPTreeNode[]
}

/** 条件分支目标。 */
export interface BranchTarget {
  match: string
  goto?: string
  value?: any
}

/** SOP 步骤执行定义。 */
export interface SopExecution {
  tool: string
  inputs: Record<string, any>
  outputs: Record<string, string>
}

/** 流程图内部使用的分支边数据。 */
export interface FlowBranchEdgeData {
  label: string
  isDefault?: boolean
}

/** 流程图节点 UI 元数据。 */
export interface SopStepUiMeta {
  position?: {
    x: number
    y: number
  }
  source_handle?: string
  target_handle?: string
}

export interface SopStepDescription extends InlineCitationDraftValue {}

/** 原始 SOP 步骤定义。 */
export interface RawSopStep {
  id: string
  name?: string
  name_zh?: string
  name_en?: string
  description?: SopStepDescription | string
  execution?: Partial<SopExecution> | null
  tool?: string
  inputs?: Record<string, any>
  outputs?: Record<string, string>
  next_step_id?: string
  on_failure?: string
  notes?: string
  analysis_status?: string
  ui_meta?: SopStepUiMeta | null
  branches?: BranchTarget[]
  condition_var?: string
  default_goto?: string
}

/** 运行时统一使用的 SOP 步骤定义。 */
export interface SopStep {
  id: string
  name?: string
  name_zh?: string
  name_en?: string
  description: SopStepDescription
  execution: SopExecution
  next_step_id?: string
  on_failure?: string
  notes?: string
  analysis_status?: string
  ui_meta?: SopStepUiMeta
  branches?: BranchTarget[]
  condition_var?: string
  default_goto?: string
}

/** 兼容旧结构的原始 SOP 数据。 */
export interface RawSopData {
  id: string
  name_zh: string
  name_en?: string
  description?: string
  folder_id?: string | null
  sort_order?: number
  steps: RawSopStep[]
  blackboard?: Record<string, any> | null
}

/** SOP 完整数据。 */
export interface SopData {
  id: string
  name_zh: string
  name_en?: string
  description?: string
  folder_id?: string | null
  sort_order?: number
  steps: SopStep[]
  blackboard?: Record<string, any> | null
}

/** SOP 文件夹。 */
export interface SopFolder {
  folder_id: string
  title: string
  parent_folder_id?: string | null
  sort_order?: number
}

/** SOP 列表项。 */
export interface SopListItem {
  id: string
  name_zh: string
  name_en?: string
  description?: string
  folder_id?: string | null
  sort_order?: number
  step_count: number
  source?: 'raw' | 'json'
}

const normalizeInlineDescription = (value: unknown): SopStepDescription => {
  if (!value) {
    return { content: '', citations: [] }
  }
  if (typeof value === 'string') {
    return { content: value, citations: [] }
  }
  if (typeof value === 'object') {
    const content = String((value as any).content || '')
    const citations = Array.isArray((value as any).citations) ? (value as any).citations : []
    return { content, citations }
  }
  return { content: String(value), citations: [] }
}

/**
 * 归一化单个 SOP 步骤，兼容旧结构字段。
 */
export const normalizeSopStep = (step: RawSopStep): SopStep => ({
  id: step.id,
  name: step.name,
  name_zh: step.name_zh,
  name_en: step.name_en,
  description: normalizeInlineDescription(step.description),
  execution: {
    tool: step.execution?.tool || step.tool || 'manual',
    inputs: (() => {
      const raw = { ...(step.execution?.inputs || step.inputs || {}) }
      delete raw.branches
      delete raw.condition_var
      delete raw.default_goto
      return raw
    })(),
    outputs: { ...(step.execution?.outputs || step.outputs || {}) },
  },
  next_step_id: step.next_step_id,
  on_failure: step.on_failure,
  notes: step.notes,
  analysis_status: step.analysis_status,
  branches: step.branches,
  condition_var: step.condition_var,
  default_goto: step.default_goto,
  ui_meta: step.ui_meta ? {
    position: step.ui_meta.position
      ? {
          x: Number(step.ui_meta.position.x || 0),
          y: Number(step.ui_meta.position.y || 0),
        }
      : undefined,
    source_handle: step.ui_meta.source_handle || undefined,
    target_handle: step.ui_meta.target_handle || undefined,
  } : undefined,
})

/**
 * 归一化整份 SOP 数据，确保前端运行时统一使用 execution 结构。
 */
export const normalizeSopData = (data: RawSopData): SopData => ({
  id: data.id,
  name_zh: data.name_zh,
  name_en: data.name_en,
  description: data.description,
  folder_id: data.folder_id || null,
  sort_order: typeof data.sort_order === 'number' ? data.sort_order : undefined,
  steps: Array.isArray(data.steps) ? data.steps.map(normalizeSopStep) : [],
  blackboard: data.blackboard || null,
})

/**
 * 将运行时步骤序列化为持久化结构，只写出新 execution 字段。
 */
export const serializeSopStep = (step: SopStep): RawSopStep => ({
  id: step.id,
  name: step.name,
  name_zh: step.name_zh,
  name_en: step.name_en,
  description: step.description,
  execution: {
    tool: step.execution.tool,
    inputs: { ...step.execution.inputs },
    outputs: { ...step.execution.outputs },
  },
  next_step_id: step.next_step_id,
  on_failure: step.on_failure,
  notes: step.notes,
  analysis_status: step.analysis_status,
  branches: step.branches,
  condition_var: step.condition_var,
  default_goto: step.default_goto,
  ui_meta: step.ui_meta
    ? {
        position: step.ui_meta.position
          ? {
              x: step.ui_meta.position.x,
              y: step.ui_meta.position.y,
            }
          : undefined,
        source_handle: step.ui_meta.source_handle,
        target_handle: step.ui_meta.target_handle,
      }
    : undefined,
})

/**
 * 将运行时 SOP 序列化为后端写入结构。
 */
export const serializeSopData = (data: SopData): RawSopData => ({
  id: data.id,
  name_zh: data.name_zh,
  name_en: data.name_en,
  description: data.description,
  folder_id: data.folder_id || null,
  sort_order: data.sort_order,
  steps: data.steps.map(serializeSopStep),
  blackboard: data.blackboard || null,
})

/** Vue Flow 节点类型别名。 */
export type SopFlowNode = Node<{
  step: SopStep
  stepIndex: number
  branchEdges?: Array<{ id: string; label: string; target: string; isDefault?: boolean }>
}>

/** Vue Flow 边类型别名。 */
export type SopFlowEdge = Edge
