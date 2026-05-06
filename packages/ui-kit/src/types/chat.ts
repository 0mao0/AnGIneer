/**
 * 基础聊天组件消息类型
 */
export type BaseChatMessageRole = 'user' | 'assistant' | 'system'

export interface CitationRichMedia {
  table_html?: string
  math_content?: string
  image_path?: string
  image_paths?: string[]
  rich_media_order?: Array<{ type: 'image' | 'table' | 'math'; path?: string }>
  source_file_name?: string
}

export interface BaseChatCitation {
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
  citations?: BaseChatCitation[]
}

/**
 * 基础聊天组件上下文标签
 */
export interface BaseChatContextItem {
  id: string
  title: string
}

export interface AIChatCitation {
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

export interface AIChatMessage {
  id?: string
  role: BaseChatMessageRole
  content: string
  timestamp?: number
  queryChain?: string
  images?: string[]
  citations?: AIChatCitation[]
  strategy?: string
  task_type?: string
  confidence?: number
  retrieved_items?: Array<{
    item_id: string
    entity_type: string
    doc_id: string
    title: string
    text: string
    score: number
    metadata?: Record<string, any>
  }>
  debug?: Record<string, any>
}

export interface QueryRequest {
  query: string
  scene?: string
  session_id?: string
  library_id?: string
  doc_ids?: string[]
  config?: string
  mode?: string
}

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
  citations?: AIChatCitation[]
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

export type SessionKey = `${string}:${string}`

export interface SessionSnapshot {
  messages: AIChatMessage[]
}

export interface AIChatContextConfig {
  maxRounds: number
  enableCompression: boolean
  compressionThreshold: number
}

/**
 * 基础聊天组件模型选项
 */
export interface BaseChatModelOption {
  value: string
  label: string
}
