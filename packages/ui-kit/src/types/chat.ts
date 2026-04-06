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
  images?: string[]
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
