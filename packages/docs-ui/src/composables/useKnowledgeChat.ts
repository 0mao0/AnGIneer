/**
 * 知识域对话 Composable
 * 提供流式知识对话的状态管理和消息发送功能
 */
import { ref } from 'vue'
import { generateMessageId, estimateTokens } from '../utils/common'

// 消息角色类型
export type KnowledgeChatMessageRole = 'user' | 'assistant' | 'system'

// 聊天消息类型
export interface KnowledgeChatMessage {
  id?: string
  role: KnowledgeChatMessageRole
  content: string
  timestamp?: number
  // 多模态预留：图片列表
  images?: string[]
}

// 对话请求参数
export interface KnowledgeChatRequest {
  // 当前用户输入
  message: string
  // 历史消息上下文
  history: KnowledgeChatMessage[]
  // 使用的模型（可选）
  model?: string
  // 对话模式（可选，用于后续扩展）
  mode?: 'chat' | 'reasoning' | 'vision'
  // 扩展参数（预留）
  context?: {
    // 引用的规范/文档 ID 列表
    references?: string[]
    // 其他上下文项
    [key: string]: any
  }
}

// 流式响应事件类型
export type KnowledgeChatStreamEventType = 'start' | 'chunk' | 'end' | 'error'

// 流式响应事件
export interface KnowledgeChatStreamEvent {
  type: KnowledgeChatStreamEventType
  messageId?: string
  content?: string
  usage?: {
    promptTokens: number
    completionTokens: number
  }
  error?: string
}

// 上下文管理配置
export interface KnowledgeChatContextConfig {
  // 最大保留消息轮数（一对问答算一轮）
  maxRounds: number
  // 是否启用上下文压缩
  enableCompression: boolean
  // 压缩阈值（token 数）
  compressionThreshold: number
}

// 默认上下文配置
const DEFAULT_CONTEXT_CONFIG: KnowledgeChatContextConfig = {
  maxRounds: 10,
  enableCompression: true,
  compressionThreshold: 4000
}

/**
 * 管理对话上下文，实现滑动窗口和压缩。
 */
function manageContext(
  messages: KnowledgeChatMessage[],
  config: KnowledgeChatContextConfig = DEFAULT_CONTEXT_CONFIG
): KnowledgeChatMessage[] {
  // 保留系统消息
  const systemMessages = messages.filter(m => m.role === 'system')
  let chatMessages = messages.filter(m => m.role !== 'system')

  // 1. 滑动窗口：限制对话轮数
  if (config.maxRounds > 0) {
    // 计算当前轮数（用户消息数）
    const userMessageCount = chatMessages.filter(m => m.role === 'user').length
    if (userMessageCount > config.maxRounds) {
      // 需要丢弃的消息数
      const messagesToRemove = (userMessageCount - config.maxRounds) * 2
      chatMessages = chatMessages.slice(messagesToRemove)
    }
  }

  // 2. 上下文压缩：如果总 token 超过阈值，进行压缩
  if (config.enableCompression) {
    let totalTokens = chatMessages.reduce((sum, m) => sum + estimateTokens(m.content), 0)

    while (totalTokens > config.compressionThreshold && chatMessages.length > 2) {
      // 移除最早的一对对话（用户+助手）
      const removed = chatMessages.splice(0, 2)
      totalTokens -= removed.reduce((sum, m) => sum + estimateTokens(m.content), 0)
    }
  }

  return [...systemMessages, ...chatMessages]
}

/**
 * 管理知识域对话状态与流式消息发送。
 */
export function useKnowledgeChat(options?: {
  defaultModel?: string
  contextConfig?: Partial<KnowledgeChatContextConfig>
  systemPrompt?: string
}) {
  // 合并上下文配置
  const contextConfig: KnowledgeChatContextConfig = {
    ...DEFAULT_CONTEXT_CONFIG,
    ...options?.contextConfig
  }

  // 状态
  const messages = ref<KnowledgeChatMessage[]>([])
  const inputText = ref('')
  const loading = ref(false)
  const currentStreamContent = ref('')
  const abortController = ref<AbortController | null>(null)

  // 初始化系统提示词
  if (options?.systemPrompt) {
    messages.value.push({
      role: 'system',
      content: options.systemPrompt,
      timestamp: Date.now()
    })
  }

  /**
   * 发送流式消息。
   */
  const sendMessage = async (
    content: string,
    model?: string,
    onChunk?: (chunk: string) => void
  ): Promise<void> => {
    if (!content.trim() || loading.value) return

    // 创建用户消息
    const userMessage: KnowledgeChatMessage = {
      id: generateMessageId(),
      role: 'user',
      content: content.trim(),
      timestamp: Date.now()
    }

    // 添加用户消息到历史
    messages.value.push(userMessage)
    inputText.value = ''
    loading.value = true
    currentStreamContent.value = ''

    // 管理上下文
    const managedMessages = manageContext([...messages.value], contextConfig)

    // 准备请求参数
    const request: KnowledgeChatRequest = {
      message: userMessage.content,
      history: managedMessages.filter(m => m.role !== 'system'),
      model: model || options?.defaultModel,
      mode: 'chat'
    }

    // 创建 AbortController 用于取消请求
    abortController.value = new AbortController()

    try {
      // 发送 SSE 请求
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'text/event-stream'
        },
        body: JSON.stringify(request),
        signal: abortController.value.signal
      })

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }

      if (!response.body) {
        throw new Error('Response body is null')
      }

      // 读取流式响应
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let assistantMessageId = generateMessageId()

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        const chunk = decoder.decode(value, { stream: true })
        const lines = chunk.split('\n')

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6).trim()
            if (data === '[DONE]') continue

            try {
              const event: KnowledgeChatStreamEvent = JSON.parse(data)

              switch (event.type) {
                case 'start':
                  if (event.messageId) {
                    assistantMessageId = event.messageId
                  }
                  break

                case 'chunk':
                  if (event.content) {
                    currentStreamContent.value += event.content
                    onChunk?.(event.content)
                  }
                  break

                case 'end':
                  // 流结束，添加助手消息到历史
                  messages.value.push({
                    id: assistantMessageId,
                    role: 'assistant',
                    content: currentStreamContent.value,
                    timestamp: Date.now()
                  })
                  currentStreamContent.value = ''
                  break

                case 'error':
                  throw new Error(event.error || 'Stream error')
              }
            } catch (e) {
              console.error('Parse SSE data error:', e)
            }
          }
        }
      }
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') {
        console.log('Request aborted')
        // 添加已接收的内容（如果有）
        if (currentStreamContent.value) {
          messages.value.push({
            id: generateMessageId(),
            role: 'assistant',
            content: currentStreamContent.value + '\n\n[已停止生成]',
            timestamp: Date.now()
          })
        }
      } else {
        console.error('Chat error:', error)
        messages.value.push({
          id: generateMessageId(),
          role: 'assistant',
          content: `抱歉，对话出现错误：${error instanceof Error ? error.message : '未知错误'}`,
          timestamp: Date.now()
        })
      }
    } finally {
      loading.value = false
      currentStreamContent.value = ''
      abortController.value = null
    }
  }

  /**
   * 停止当前流式生成。
   */
  const stopGeneration = () => {
    if (abortController.value) {
      abortController.value.abort()
    }
  }

  /**
   * 清空对话历史。
   */
  const clearMessages = () => {
    messages.value = []
    if (options?.systemPrompt) {
      messages.value.push({
        role: 'system',
        content: options.systemPrompt,
        timestamp: Date.now()
      })
    }
  }

  /**
   * 获取当前上下文的 token 估算。
   */
  const getContextTokens = (): number => {
    return messages.value.reduce((sum, m) => sum + estimateTokens(m.content), 0)
  }

  /**
   * 获取当前对话轮数。
   */
  const getContextRounds = (): number => {
    return messages.value.filter(m => m.role === 'user').length
  }

  return {
    // 状态
    messages,
    inputText,
    loading,
    currentStreamContent,
    // 方法
    sendMessage,
    stopGeneration,
    clearMessages,
    getContextTokens,
    getContextRounds,
    // 工具
    generateMessageId
  }
}
