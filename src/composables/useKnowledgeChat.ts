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
 * 对引用做轻量去重，避免同一页同一区段重复刷屏。
 */
function dedupeCitations(
  citations: NonNullable<KnowledgeChatResponse['citations']>
): NonNullable<KnowledgeChatResponse['citations']> {
  const seen = new Set<string>()
  return citations.filter(citation => {
    const key = [
      citation.target_id,
      citation.doc_id,
      citation.page_idx,
      citation.section_path
    ].join('::')
    if (seen.has(key)) {
      return false
    }
    seen.add(key)
    return true
  })
}

// 对话请求参数
export interface KnowledgeChatRequest {
  // 当前用户输入
  query: string
  // 历史消息上下文
  history: KnowledgeChatMessage[]
  // 指定知识库
  library_id?: string
  // 限定文档范围
  doc_ids?: string[]
  // 查询模式
  mode?: 'auto' | 'retrieval' | 'sql' | 'schema' | 'table'
  // 返回调试信息
  include_debug?: boolean
  // 返回检索详情
  include_retrieved?: boolean
}

// 知识查询响应
export interface KnowledgeChatResponse {
  query_id: string
  task_type: string
  strategy: string
  answer: string
  citations?: Array<{
    target_id: string
    target_type: string
    doc_id: string
    doc_title: string
    page_idx: number
    section_path: string
    snippet: string
    score: number
  }>
  retrieved_items?: Array<{
    item_id: string
    entity_type: string
    text: string
    score: number
  }>
  sql?: {
    generated_sql: string
    execution_status: string
    result_preview: any
    explanation: string
  }
  confidence?: number
  latency_ms?: number
  debug?: Record<string, any>
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
  libraryId?: string
  getContextItems?: () => Array<{ id: string; title: string }>
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
    _model?: string,
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
    const contextItems = options?.getContextItems?.() || []
    const request: KnowledgeChatRequest = {
      query: userMessage.content,
      history: managedMessages.filter(m => m.role !== 'system'),
      library_id: options?.libraryId || 'default',
      doc_ids: contextItems.map(item => item.id),
      mode: 'auto',
      include_debug: false,
      include_retrieved: false
    }

    // 创建 AbortController 用于取消请求
    abortController.value = new AbortController()

    try {
      // 发送知识查询请求
      const response = await fetch('/api/knowledge/query', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(request),
        signal: abortController.value.signal
      })

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }

      const payload: KnowledgeChatResponse = await response.json()
      const citations = dedupeCitations(payload.citations || [])
      let assistantContent = payload.answer || ''

      if (payload.sql?.generated_sql) {
        assistantContent += `\n\nSQL：\n\`\`\`sql\n${payload.sql.generated_sql}\n\`\`\``
        if (payload.sql.explanation) {
          assistantContent += `\n${payload.sql.explanation}`
        }
      }

      currentStreamContent.value = assistantContent
      onChunk?.(assistantContent)
      messages.value.push({
        id: payload.query_id || generateMessageId(),
        role: 'assistant',
        content: assistantContent,
        timestamp: Date.now(),
        citations: citations.map(citation => ({
          target_id: citation.target_id,
          doc_id: citation.doc_id,
          doc_title: citation.doc_title,
          page_idx: citation.page_idx,
          section_path: citation.section_path,
          snippet: citation.snippet,
          score: citation.score
        }))
      })
      currentStreamContent.value = ''
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
