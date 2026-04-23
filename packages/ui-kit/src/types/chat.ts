/**
 * 基础聊天组件消息类型
 */
export type BaseChatMessageRole = 'user' | 'assistant' | 'system'

/**
 * 基础聊天组件消息对象
 */
export interface BaseChatMessage {
  id?: string
  role: BaseChatMessageRole
  content: string
  timestamp?: number
  queryChain?: string
  images?: string[]
  citations?: Array<{
    target_id: string
    doc_id: string
    doc_title: string
    page_idx: number
    section_path: string
    snippet: string
    score: number
  }>
}

/**
 * 基础聊天组件上下文标签
 */
export interface BaseChatContextItem {
  id: string
  title: string
}

/**
 * 基础聊天组件模型选项
 */
export interface BaseChatModelOption {
  value: string
  label: string
}
