/**
 * 经验库对话 Composable
 * 基于知识域对话能力封装经验库默认语义与系统提示词
 */
import {
  useKnowledgeChat,
  type KnowledgeChatMessage as SopChatMessage,
  type KnowledgeChatMessageRole as SopChatMessageRole,
  type KnowledgeChatRequest as SopChatRequest,
  type KnowledgeChatStreamEvent as SopChatStreamEvent,
  type KnowledgeChatStreamEventType as SopChatStreamEventType,
  type KnowledgeChatContextConfig as SopChatContextConfig
} from './useKnowledgeChat'

export type {
  SopChatMessage,
  SopChatMessageRole,
  SopChatRequest,
  SopChatStreamEvent,
  SopChatStreamEventType,
  SopChatContextConfig
}

export interface UseSopChatOptions {
  defaultModel?: string
  contextConfig?: Partial<SopChatContextConfig>
  systemPrompt?: string
}

/**
 * 管理经验库对话状态，并补充经验库默认系统提示词。
 */
export function useSopChat(options?: UseSopChatOptions) {
  return useKnowledgeChat({
    ...options,
    systemPrompt: options?.systemPrompt || '你是经验库 SOP 助手，请结合流程、步骤和约束回答用户问题。'
  })
}
