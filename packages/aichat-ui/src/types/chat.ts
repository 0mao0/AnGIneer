import type {
  CitationBinding,
  InlineCitationDraftValue
} from './citation'

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

export interface BaseChatSendPayload extends InlineCitationDraftValue {}

export interface BaseChatCitation {
  target_id: string
  target_type?: string
  doc_id: string
  doc_title: string
  /** 结构化引用标记，如 K1/T1/E1，由后端 MarkerAllocator 分配 */
  marker?: string
  page_idx: number
  page_label?: string
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
  inlineCitations?: CitationBinding[]
  thinking_trace?: ThinkingTraceStep[]
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
  /** 结构化引用标记，如 K1/T1/E1，由后端 MarkerAllocator 分配 */
  marker?: string
  page_idx: number
  page_label?: string
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
  inlineCitations?: CitationBinding[]
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
  gap_analysis?: Array<{
    gap_description: string
    suggested_sources: string[]
  }>
  confidence_breakdown?: {
    high?: string[]
    medium?: string[]
    low?: string[]
  }
  thinking_trace?: ThinkingTraceStep[]
}

export interface ThinkingTraceStep {
  kind: 'call' | 'result' | 'note' | 'turn'
  tool?: string
  detail: string
  turn?: number
  isError?: boolean
  durationMs?: number
  citations?: AIChatCitation[]
  /** 工具返回的完整候选条目（knowledge_search/table_search/entity_search） */
  resultItems?: ThinkingTraceItem[]
  /** 工具返回中需要单独说明的信息，如 entity_search 的自动回退说明 */
  resultNote?: string
}

/** 思考过程中某个工具返回的单条候选 */
export interface ThinkingTraceItem {
  item_id: string
  entity_type?: string
  doc_id: string
  doc_title?: string
  /** 工具返回的 cite 标记（对应 AIChatCitation.marker） */
  cite?: string
  title?: string
  text: string
  score: number
  metadata?: Record<string, any>
}

export interface QueryRequest {
  query: string
  scene?: string
  session_id?: string
  library_id?: string
  doc_ids?: string[]
  config?: string
  mode?: string
  inline_citations?: CitationBinding[]
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
  gap_analysis?: Array<{
    gap_description: string
    suggested_sources: string[]
  }>
  confidence_breakdown?: {
    high?: string[]
    medium?: string[]
    low?: string[]
  }
  thinking_trace?: ThinkingTraceStep[]
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
