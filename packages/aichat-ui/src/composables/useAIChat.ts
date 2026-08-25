/**
 * 统一 AI 对话 Composable
 * 提供流式对话的状态管理、消息发送与会话池隔离功能
 * 通过 scene + sessionId 实现多场景对话隔离，后端自动路由 service mode
 */
import { ref, computed, watch, unref, type Ref, type ComputedRef } from 'vue'
import type {
  AIChatMessage,
  BaseChatSendPayload,
  QueryRequest,
  QueryResponse,
  SessionKey,
  SessionSnapshot,
  AIChatContextConfig,
  ThinkingTraceStep,
} from '../types/chat'
import { generateMessageId, estimateTokens } from '../utils/tree'

/** 根据 scene 和 id 构建会话池 key */
export function buildSessionKey(scene: string, id: string): SessionKey {
  return `${scene}:${id}`
}

/** 全局会话池，按 sessionKey 隔离各场景对话状态 */
const sessionPool = new Map<SessionKey, SessionSnapshot>()

/**
 * 旧版本会把会话池写入 localStorage；当前产品不做历史对话记录，
 * 加载时清理一次旧数据，避免残留。
 */
const LEGACY_SESSION_POOL_STORAGE_KEY = 'angineer:ai-chat-pool:v1'
try {
  if (typeof localStorage !== 'undefined') {
    localStorage.removeItem(LEGACY_SESSION_POOL_STORAGE_KEY)
  }
} catch {
  // 存储不可用或隐私模式下静默忽略
}

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

/** 对引用做轻量去重，避免同一页同一区段重复刷屏 */
function dedupeCitations(
  citations: NonNullable<QueryResponse['citations']>
): NonNullable<QueryResponse['citations']> {
  const seen = new Set<string>()
  return citations.filter(citation => {
    const key = [
      citation.target_id,
      citation.doc_id,
      citation.page_idx,
      citation.section_path,
      citation.marker || ''
    ].join('::')
    if (seen.has(key)) {
      return false
    }
    seen.add(key)
    return true
  })
}

/** 将统一查询响应映射为内部消息格式 */
function mapQueryResponseToChatResponse(qr: QueryResponse) {
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
    confidence: (qr.intent as any)?.confidence as number | undefined,
    gap_analysis: qr.gap_analysis,
    confidence_breakdown: qr.confidence_breakdown,
    thinking_trace: qr.thinking_trace,
    debug: {
      intent: qr.intent,
      fallback_used: qr.fallback_used,
    },
  }
}

const DEFAULT_CONTEXT_CONFIG: AIChatContextConfig = {
  maxRounds: 10,
  enableCompression: true,
  compressionThreshold: 4000
}

/** 管理对话上下文，实现滑动窗口和压缩 */
function manageContext(
  messages: AIChatMessage[],
  config: AIChatContextConfig = DEFAULT_CONTEXT_CONFIG
): AIChatMessage[] {
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
 * 管理统一 AI 对话状态与消息发送，支持会话池隔离。
 *
 * 通过 sessionKey（格式 "scene:id"）实现多场景对话隔离：
 * - 切换页面/文档时调用 switchSession 保留各自思考痕迹
 * - 后端根据 scene 字段切换 service mode
 */
export function useAIChat(options?: {
  defaultModel?: string
  contextConfig?: Partial<AIChatContextConfig>
  systemPrompt?: string
  libraryId?: string | Ref<string>
  scene?: string
  sessionId?: string | Ref<string>
  getContextItems?: () => Array<{ id: string; title: string }>
  /** 问答请求实现注入；不注入时发送会得到明确错误提示 */
  query?: (
    payload: QueryRequest,
    options?: {
      signal?: AbortSignal
      onDelta?: (delta: string) => void
      onThinking?: (steps: ThinkingTraceStep[]) => void
      onAnswerReplace?: (full: string) => void
    }
  ) => Promise<QueryResponse>
}): {
  messages: Ref<AIChatMessage[]>
  loading: Ref<boolean>
  currentStreamContent: Ref<string>
  liveThinkingSteps: Ref<ThinkingTraceStep[]>
  currentSessionKey: Ref<SessionKey>
  contextTokens: ComputedRef<number>
  contextRounds: ComputedRef<number>
  sendMessage: (payload: string | BaseChatSendPayload, model?: string, onChunk?: (chunk: string) => void, sendOptions?: { includeDebug?: boolean; includeRetrieved?: boolean }) => Promise<void>
  stopGeneration: () => void
  clearMessages: () => void
  switchSession: (newScene: string, newId: string) => void
  removeCurrentSession: () => void
  startNewChat: () => void
} {
  const contextConfig: AIChatContextConfig = {
    ...DEFAULT_CONTEXT_CONFIG,
    ...options?.contextConfig
  }

  const scene = options?.scene || 'docs'
  const sessionIdRef: Ref<string> = typeof options?.sessionId === 'object' && 'value' in (options!.sessionId as any)
    ? (options!.sessionId as Ref<string>)
    : ref(options?.sessionId || 'default')
  const currentSessionKey = ref<SessionKey>(buildSessionKey(scene, sessionIdRef.value))

  const messages = ref<AIChatMessage[]>([])
  const loading = ref(false)
  const currentStreamContent = ref('')
  const liveThinkingSteps = ref<ThinkingTraceStep[]>([])
  const abortController = ref<AbortController | null>(null)

  if (options?.systemPrompt) {
    messages.value.push({
      role: 'system',
      content: options.systemPrompt,
      timestamp: Date.now()
    })
  }

  restoreFromPool(currentSessionKey.value)

  watch(sessionIdRef, (newId) => {
    if (newId && buildSessionKey(scene, newId) !== currentSessionKey.value) {
      switchSession(scene, newId)
    }
  })

  /** 将当前会话状态保存到会话池 */
  function saveToPool(): void {
    sessionPool.set(currentSessionKey.value, {
      messages: [...messages.value],
    })
  }

  /** 从会话池恢复指定 key 的状态 */
  function restoreFromPool(key: SessionKey): boolean {
    const snapshot = sessionPool.get(key)
    if (!snapshot) return false
    messages.value = [...snapshot.messages]
    return true
  }

  /** 切换到指定 scene:id 的会话，自动保存当前会话并恢复目标会话 */
  function switchSession(newScene: string, newId: string): void {
    saveToPool()
    const newKey = buildSessionKey(newScene, newId)
    currentSessionKey.value = newKey
    if (!restoreFromPool(newKey)) {
      messages.value = []
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
    if (options?.systemPrompt) {
      messages.value.push({
        role: 'system',
        content: options.systemPrompt,
        timestamp: Date.now()
      })
    }
  }

  /** 新建对话：清空当前消息、中止生成，并切换到全新会话 key（后端按 key 开新会话） */
  function startNewChat(): void {
    stopGeneration()
    sessionPool.delete(currentSessionKey.value)
    const newId = `chat-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
    currentSessionKey.value = buildSessionKey(scene, newId)
    messages.value = []
    if (options?.systemPrompt) {
      messages.value.push({
        role: 'system',
        content: options.systemPrompt,
        timestamp: Date.now(),
      })
    }
  }

  /** 发送消息并获取 AI 回复 */
  const sendMessage = async (
    payload: string | BaseChatSendPayload,
    _model?: string,
    onChunk?: (chunk: string) => void,
    _sendOptions?: { includeDebug?: boolean; includeRetrieved?: boolean }
  ): Promise<void> => {
    const normalizedPayload: BaseChatSendPayload = typeof payload === 'string'
      ? { content: payload, citations: [] }
      : {
        content: String(payload.content || ''),
        citations: Array.isArray(payload.citations) ? payload.citations : []
      }
    const normalizedContent = normalizedPayload.content.trim()
    const inlineCitations = normalizedPayload.citations

    if (!normalizedContent || loading.value) return

    const userMessage: AIChatMessage = {
      id: generateMessageId(),
      role: 'user',
      content: normalizedContent,
      inlineCitations: normalizedPayload.citations,
      timestamp: Date.now()
    }

    messages.value.push(userMessage)
    loading.value = true
    currentStreamContent.value = ''
    liveThinkingSteps.value = []

    manageContext([...messages.value], contextConfig)

    const contextItems = options?.getContextItems?.() || []
    const queryRequest: QueryRequest = {
      query: userMessage.content,
      scene,
      session_id: currentSessionKey.value,
      library_id: String(unref(options?.libraryId) || 'default'),
      doc_ids: contextItems.map(item => item.id),
      inline_citations: inlineCitations,
    }

    abortController.value = new AbortController()

    try {
      if (!options?.query) {
        throw new Error('未配置 AI 数据源（transport.query）')
      }
      let streamed = false
      const queryData: QueryResponse = await options.query(queryRequest, {
        signal: abortController.value.signal,
        onDelta: (delta) => {
          streamed = true
          currentStreamContent.value += delta
          onChunk?.(delta)
        },
        onThinking: (steps) => {
          liveThinkingSteps.value = steps
        },
        onAnswerReplace: (full) => {
          // 边界规则替换最终答案时整体覆盖，避免旧答案残留在界面上
          streamed = true
          currentStreamContent.value = full
        },
      })
      const payload = mapQueryResponseToChatResponse(queryData)
      const citations = dedupeCitations(payload.citations || [])
      let assistantContent = payload.answer || ''

      if (payload.sql?.generated_sql) {
        assistantContent += `\n\nSQL：\n\`\`\`sql\n${payload.sql.generated_sql}\n\`\`\``
        if (payload.sql.explanation) {
          assistantContent += `\n${payload.sql.explanation}`
        }
      }

      if (!streamed) {
        currentStreamContent.value = assistantContent
        onChunk?.(assistantContent)
      } else if (assistantContent && assistantContent !== currentStreamContent.value) {
        // 流式结束后以 transport 的权威答案为基准（兼容替换/清理）
        currentStreamContent.value = assistantContent
      }
      messages.value.push({
        id: payload.query_id || generateMessageId(),
        role: 'assistant',
        content: assistantContent,
        timestamp: Date.now(),
        citations: citations.map(citation => ({
          target_id: citation.target_id,
          target_type: citation.target_type,
          doc_id: citation.doc_id,
          doc_title: citation.doc_title,
          marker: citation.marker,
          page_idx: citation.page_idx,
          page_label: citation.page_label,
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
        gap_analysis: payload.gap_analysis,
        confidence_breakdown: payload.confidence_breakdown,
        thinking_trace: payload.thinking_trace || [],
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

  /** 停止当前流式生成 */
  const stopGeneration = () => {
    if (abortController.value) {
      abortController.value.abort()
    }
  }

  /** 清空对话历史 */
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

  const contextTokens = computed(() =>
    messages.value.reduce((sum, m) => sum + estimateTokens(m.content), 0)
  )

  const contextRounds = computed(() =>
    messages.value.filter(m => m.role === 'user').length
  )

  return {
    messages,
    loading,
    currentStreamContent,
    liveThinkingSteps,
    currentSessionKey,
    contextTokens,
    contextRounds,
    sendMessage,
    stopGeneration,
    clearMessages,
    switchSession,
    removeCurrentSession,
    startNewChat,
  }
}
