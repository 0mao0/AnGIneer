/**
 * @deprecated 请使用 @angineer/ui-kit 的 useAIChat 替代。
 * 本模块将在后续版本中移除。
 *
 * 知识域对话 Composable
 * 提供流式知识对话的状态管理、消息发送与会话池隔离功能
 */
import { ref, computed, watch, type Ref } from 'vue'
import { generateMessageId, estimateTokens } from '../utils/common'
import type { CitationRichMedia } from '@angineer/ui-kit'

export type KnowledgeChatMessageRole = 'user' | 'assistant' | 'system'

export interface KnowledgeChatCitation {
  target_id: string
  target_type?: string
  doc_id: string
  doc_title: string
  page_idx: number
  section_path: string
  snippet: string
  content?: string
  content_type?: string
  score: number
  rich_media?: CitationRichMedia
}

export interface KnowledgeChatMessage {
  id?: string
  role: KnowledgeChatMessageRole
  content: string
  timestamp?: number
  queryChain?: string
  images?: string[]
  citations?: KnowledgeChatCitation[]
  strategy?: string
  task_type?: string
  confidence?: number
  retrieved_items?: Array<{
    item_id: string
    entity_type: string
    text: string
    score: number
    metadata?: Record<string, any>
  }>
  debug?: Record<string, any>
}

/** 会话池中单个会话的快照 */
export interface SessionSnapshot {
  messages: KnowledgeChatMessage[]
  inputText: string
}

/** 会话池 key 格式：scene:id */
export type SessionKey = `${string}:${string}`

/** 根据 scene 和 id 构建会话池 key */
export function buildSessionKey(scene: string, id: string): SessionKey {
  return `${scene}:${id}`
}

/** 全局会话池，按 sessionKey 隔离各场景对话状态 */
const sessionPool = new Map<SessionKey, SessionSnapshot>()

/** 获取会话池中指定 key 的快照 */
export function getSessionSnapshot(key: SessionKey): SessionSnapshot | undefined {
  return sessionPool.get(key)
}

/** 获取会话池中所有活跃 key */
export function getActiveSessionKeys(): SessionKey[] {
  return Array.from(sessionPool.keys())
}

/** 删除会话池中指定 key 的快照 */
export function removeSession(key: SessionKey): boolean {
  return sessionPool.delete(key)
}

/** 清空整个会话池 */
export function clearSessionPool(): void {
  sessionPool.clear()
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
  query: string
  history: KnowledgeChatMessage[]
  library_id?: string
  doc_ids?: string[]
  mode?: 'auto' | 'retrieval' | 'sql' | 'schema' | 'table'
  include_debug?: boolean
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
    content?: string
    content_type?: string
    score: number
    rich_media?: CitationRichMedia
  }>
  retrieved_items?: Array<{
    item_id: string
    entity_type: string
    doc_id: string
    title: string
    text: string
    score: number
    metadata?: Record<string, any>
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

// 统一查询请求参数
export interface QueryRequest {
  query: string
  scene?: string
  session_id?: string
  library_id?: string
  doc_ids?: string[]
  config?: string
  mode?: string
}

// 统一查询响应
export interface QueryResponse {
  query_id: string
  session_key?: string
  intent: {
    intent_level: string
    intent_type: string
    parameters: Record<string, any>
    required_capabilities: string[]
    matched_sop: string | null
    service_mode: string
    reason: string | null
  }
  answer: string
  citations?: Array<{
    target_id: string
    target_type: string
    doc_id: string
    doc_title: string
    page_idx: number
    section_path: string
    snippet: string
    content?: string
    content_type?: string
    score: number
    rich_media?: CitationRichMedia
  }>
  retrieved_items?: Array<{
    item_id: string
    entity_type: string
    doc_id: string
    title: string
    text: string
    score: number
    metadata?: Record<string, any>
  }>
  sql?: {
    generated_sql: string
    execution_status: string
    result_preview: any
    explanation: string
  }
  fallback_used?: boolean
  latency_ms?: number
}

// 将统一查询响应映射为 KnowledgeChatResponse 格式
function mapQueryResponseToChatResponse(qr: QueryResponse): KnowledgeChatResponse {
  const intentLevelMap: Record<string, string> = {
    L1: 'content_qa',
    L2: 'schema_qa',
    L3: 'analytic_sql',
    L4: 'mixed',
  }
  return {
    query_id: qr.query_id,
    task_type: intentLevelMap[qr.intent?.intent_level] || qr.intent?.intent_type || 'content_qa',
    strategy: qr.intent?.service_mode || 'semantic_retrieval',
    answer: qr.answer || '',
    citations: qr.citations,
    retrieved_items: qr.retrieved_items,
    sql: qr.sql,
    latency_ms: qr.latency_ms,
    debug: {
      intent: qr.intent,
      fallback_used: qr.fallback_used,
    },
  }
}

/**
 * 将任务类型转换为更易读的中文标签。
 */
function formatTaskType(taskType: string | undefined): string {
  const normalized = String(taskType || '').trim()
  const taskTypeMap: Record<string, string> = {
    content_qa: '正文问答',
    definition_qa: '定义问答',
    locate_qa: '定位问答',
    table_qa: '表格问答',
    schema_qa: '结构问答',
    analytic_sql: 'SQL 分析',
    mixed: '混合问答'
  }
  return taskTypeMap[normalized] || normalized || '未知任务'
}

/**
 * 将查询响应格式化为回答气泡顶部的查询链路文案。
 */
function buildQueryChain(payload: KnowledgeChatResponse): string {
  const debug = payload.debug || {}
  const segments = [
    `意图 ${formatTaskType(payload.task_type || String(debug.route || ''))}`,
    debug.executor ? `执行器 ${String(debug.executor)}` : '',
    debug.retrieval_route ? `检索 ${String(debug.retrieval_route)}` : '',
    payload.strategy ? `策略 ${payload.strategy}` : '',
    debug.fallback_used ? '已回退' : ''
  ].filter(Boolean)
  if (!segments.length) {
    return ''
  }
  return `查询链路：${segments.join(' -> ')}`
}

// 上下文管理配置
export interface KnowledgeChatContextConfig {
  maxRounds: number
  enableCompression: boolean
  compressionThreshold: number
}

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
  const systemMessages = messages.filter(m => m.role === 'system')
  let chatMessages = messages.filter(m => m.role !== 'system')

  if (config.maxRounds > 0) {
    const userMessageCount = chatMessages.filter(m => m.role === 'user').length
    if (userMessageCount > config.maxRounds) {
      const messagesToRemove = (userMessageCount - config.maxRounds) * 2
      chatMessages = chatMessages.slice(messagesToRemove)
    }
  }

  if (config.enableCompression) {
    let totalTokens = chatMessages.reduce((sum, m) => sum + estimateTokens(m.content), 0)
    while (totalTokens > config.compressionThreshold && chatMessages.length > 2) {
      const removed = chatMessages.splice(0, 2)
      totalTokens -= removed.reduce((sum, m) => sum + estimateTokens(m.content), 0)
    }
  }

  return [...systemMessages, ...chatMessages]
}

/**
 * 管理知识域对话状态与流式消息发送，支持会话池隔离。
 *
 * 通过 sessionKey（格式 "scene:id"）实现多场景对话隔离：
 * - 切换页面/文档时调用 switchSession 保留各自思考痕迹
 * - 后端根据 scene 字段切换 service mode
 */
export function useKnowledgeChat(options?: {
  defaultModel?: string
  contextConfig?: Partial<KnowledgeChatContextConfig>
  systemPrompt?: string
  libraryId?: string
  scene?: string
  sessionId?: string | Ref<string>
  getContextItems?: () => Array<{ id: string; title: string }>
}) {
  const contextConfig: KnowledgeChatContextConfig = {
    ...DEFAULT_CONTEXT_CONFIG,
    ...options?.contextConfig
  }

  const scene = options?.scene || 'docs'
  const sessionIdRef: Ref<string> = typeof options?.sessionId === 'object' && 'value' in (options!.sessionId as any)
    ? (options!.sessionId as Ref<string>)
    : ref(options?.sessionId || 'default')
  const currentSessionKey = ref<SessionKey>(buildSessionKey(scene, sessionIdRef.value))

  const messages = ref<KnowledgeChatMessage[]>([])
  const inputText = ref('')
  const loading = ref(false)
  const currentStreamContent = ref('')
  const abortController = ref<AbortController | null>(null)

  if (options?.systemPrompt) {
    messages.value.push({
      role: 'system',
      content: options.systemPrompt,
      timestamp: Date.now()
    })
  }

  watch(sessionIdRef, (newId) => {
    if (newId && buildSessionKey(scene, newId) !== currentSessionKey.value) {
      switchSession(scene, newId)
    }
  })

  /** 将当前会话状态保存到会话池 */
  function saveToPool(): void {
    sessionPool.set(currentSessionKey.value, {
      messages: [...messages.value],
      inputText: inputText.value,
    })
  }

  /** 从会话池恢复指定 key 的状态 */
  function restoreFromPool(key: SessionKey): boolean {
    const snapshot = sessionPool.get(key)
    if (!snapshot) return false
    messages.value = [...snapshot.messages]
    inputText.value = snapshot.inputText
    return true
  }

  /** 切换到指定 scene:id 的会话，自动保存当前会话并恢复目标会话 */
  function switchSession(newScene: string, newId: string): void {
    saveToPool()
    const newKey = buildSessionKey(newScene, newId)
    currentSessionKey.value = newKey
    if (!restoreFromPool(newKey)) {
      messages.value = []
      inputText.value = ''
      if (options?.systemPrompt) {
        messages.value.push({
          role: 'system',
          content: options.systemPrompt,
          timestamp: Date.now()
        })
      }
    }
  }

  /** 删除当前会话并清空本地状态 */
  function removeCurrentSession(): void {
    sessionPool.delete(currentSessionKey.value)
    messages.value = []
    inputText.value = ''
    if (options?.systemPrompt) {
      messages.value.push({
        role: 'system',
        content: options.systemPrompt,
        timestamp: Date.now()
      })
    }
  }

  /**
   * 发送流式消息。
   */
  const sendMessage = async (
    content: string,
    _model?: string,
    onChunk?: (chunk: string) => void,
    sendOptions?: { includeDebug?: boolean; includeRetrieved?: boolean }
  ): Promise<void> => {
    if (!content.trim() || loading.value) return

    const userMessage: KnowledgeChatMessage = {
      id: generateMessageId(),
      role: 'user',
      content: content.trim(),
      timestamp: Date.now()
    }

    messages.value.push(userMessage)
    inputText.value = ''
    loading.value = true
    currentStreamContent.value = ''

    const managedMessages = manageContext([...messages.value], contextConfig)

    const contextItems = options?.getContextItems?.() || []
    const request: KnowledgeChatRequest = {
      query: userMessage.content,
      history: managedMessages.filter(m => m.role !== 'system'),
      library_id: options?.libraryId || 'default',
      doc_ids: contextItems.map(item => item.id),
      mode: 'auto',
      include_debug: sendOptions?.includeDebug ?? false,
      include_retrieved: sendOptions?.includeRetrieved ?? false
    }

    abortController.value = new AbortController()

    try {
      let payload: KnowledgeChatResponse

      const queryRequest: QueryRequest = {
        query: userMessage.content,
        scene,
        session_id: currentSessionKey.value,
        library_id: request.library_id || 'default',
        doc_ids: request.doc_ids,
        config: undefined,
        mode: undefined,
      }
      const queryResponse = await fetch('/api/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(queryRequest),
        signal: abortController.value.signal,
      })
      if (!queryResponse.ok) {
        throw new Error(`Query endpoint returned ${queryResponse.status}`)
      }
      const queryData: QueryResponse = await queryResponse.json()
      payload = mapQueryResponseToChatResponse(queryData)
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
        queryChain: buildQueryChain(payload),
        citations: citations.map(citation => ({
          target_id: citation.target_id,
          target_type: citation.target_type,
          doc_id: citation.doc_id,
          doc_title: citation.doc_title,
          page_idx: citation.page_idx,
          section_path: citation.section_path,
          snippet: citation.snippet,
          content: citation.content,
          content_type: citation.content_type,
          score: citation.score,
          rich_media: citation.rich_media
        })),
        strategy: payload.strategy,
        task_type: payload.task_type,
        confidence: payload.confidence,
        retrieved_items: payload.retrieved_items,
        debug: payload.debug
      })
      currentStreamContent.value = ''
      saveToPool()
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') {
        console.log('Request aborted')
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
      saveToPool()
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
    saveToPool()
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

  const contextTokens = computed(getContextTokens)
  const contextRounds = computed(getContextRounds)

  return {
    messages,
    inputText,
    loading,
    currentStreamContent,
    currentSessionKey,
    contextTokens,
    contextRounds,
    sendMessage,
    stopGeneration,
    clearMessages,
    getContextTokens,
    getContextRounds,
    switchSession,
    removeCurrentSession,
    saveToPool,
    generateMessageId
  }
}
