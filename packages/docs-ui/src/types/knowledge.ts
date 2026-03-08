export type KnowledgeStrategy = 'A_structured' | 'B_mineru_rag' | 'C_pageindex'

export type IngestStatus = 'idle' | 'processing' | 'completed' | 'failed'

export interface ParseTaskInfo {
  id: string
  library_id: string
  doc_id: string
  status: 'queued' | 'processing' | 'completed' | 'failed'
  progress: number
  stage: string
  error?: string
}

export interface StructuredIndexItem {
  id: string
  item_type: string
  title?: string
  content: string
  meta?: Record<string, any>
  order_index: number
}

export interface StructuredStats {
  total?: number
  strategies?: Partial<Record<KnowledgeStrategy, Record<string, number>>>
  [key: string]: any
}
