import type { KnowledgeTreeNode } from './tree'

export type KnowledgeStrategy = 'doc_blocks_graph_v1'

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

export interface StructuredNodeUpdatePayload {
  blockId: string
  plain_text?: string
  math_content?: string
  table_html?: string
  title?: string
  caption?: string
  footnote?: string
  parent_block_uid?: string | null
  derived_title_level?: number | null
  merge_into_block_uid?: string | null
}

export interface StructuredSplitSegmentPayload {
  plain_text: string
}

export type StructuredBatchOperationType = 'merge' | 'split' | 'delete' | 'relevel'

export interface StructuredBatchOperationPayload {
  operation: StructuredBatchOperationType
  blockIds: string[]
  targetBlockId?: string | null
  splitSegments?: StructuredSplitSegmentPayload[]
  levelDelta?: number | null
  targetLevel?: number | null
}

export interface StructuredStats {
  total?: number
  strategies?: Partial<Record<KnowledgeStrategy, Record<string, number>>>
  [key: string]: any
}

export interface DocumentStorageManifest {
  doc_root: string
  source_file: string | null
  parsed_markdown: string | null
  edited_markdown: string | null
  assets_dir: string | null
  raw_dir: string | null
  middle_json: string | null
  mineru_blocks: string | null
  history_files: string[]
}

export interface DocBlockNode {
  id: string
  block_uid: string
  block_type: string
  page_idx: number
  block_seq: number
  plain_text: string
  bbox: [number, number, number, number] | null
  bbox_source: string
  derived_level: number | null
  title_path: string | null
  parent_uid: string | null
  derived_by: string
  confidence: number
  image_path: string | null
  image_paths?: string[] | null
  table_html: string | null
  math_content: string | null
  title?: string | null
  caption?: string | null
  footnote?: string | null
  merged_block_uids?: string[] | null
  merged_bboxes?: number[][] | null
  caption_block_uid?: string | null
  caption_block_uids?: string[] | null
  caption_bboxes?: number[][] | null
  footnote_block_uid?: string | null
  footnote_block_uids?: string[] | null
  footnote_bboxes?: number[][] | null
  content_json?: Record<string, any> | null
  rich_media_order?: Array<{ type: 'image' | 'table' | 'math'; path?: string }> | null
}

export interface DocBlockEdge {
  id: string
  from: string
  to: string
  kind: 'strong' | 'weak'
  label: string
  color: string
}

export interface DocBlocksGraph {
  nodes: DocBlockNode[]
  edges: DocBlockEdge[]
  stats?: {
    base_rows?: Record<string, any>[]
    derived_rows?: Record<string, any>[]
  }
}

export interface DocBlocksGraphState {
  activeNodeId: string | null
  expandedNodeIds: Set<string>
  expandedGraphNodeIds: Set<string>
  viewMode: 'tree' | 'graph'
  viewportState: {
    x: number
    y: number
    scale: number
  } | null
}

export interface PDFParsedWorkspaceEventMap {
  parse: [node: KnowledgeTreeNode]
  'query-structured': [itemType?: string, keyword?: string]
  'update-structured-node': [payload: StructuredNodeUpdatePayload]
  'toggle-visible': [node: KnowledgeTreeNode]
}

export interface DocumentResponse {
  content: string
  storage: Record<string, any>
  mineru_blocks?: Record<string, any>[]
  middle_data?: Record<string, any> | null
  graph_data?: { nodes: Record<string, any>[]; edges: Record<string, any>[] } | null
}

export interface KnowledgeParseOptions {
  use_llm?: boolean
  llm_model?: string
}

export interface LlmConfigOption {
  name: string
  model: string
  configured: boolean
}

export interface KnowledgeEvalQuestion {
  question_id: string
  question: string
  task_type: string
  difficulty: string
  tags: string[]
  library_id?: string
  doc_ids?: string[]
  expected_route?: string
  dataset_id?: string
  dataset_title?: string
  gold_answer?: string
  thought_process?: string
}

export interface KnowledgeEvalDataset {
  dataset_id: string
  title: string
  description?: string
  schema_version?: string
  version?: string
  library_id?: string
  question_count: number
  visible_question_count: number
  sql_question_count: number
}

export interface KnowledgeEvalSummary {
  retrieval_score: number | null
  answer_health_score: number | null
  answer_correctness_score: number | null
  checked_answer_total: number
  overall_score: number
  text2sql_success_score: number | null
}

export interface KnowledgeEvalAnswerDetail {
  question_id: string
  question: string
  difficulty: string
  tags: string[]
  task_type?: string
  strategy?: string
  answer_non_empty?: number
  citation_hit?: number
  refusal_correct?: number
  answer_correct_checked?: boolean
  answer_correct?: number | null
  failed_correctness_checks?: Array<{
    type?: string
    keywords?: string[]
    check_type?: string
    keyword_results?: Array<{ keyword: string; normalized: string; found: boolean }>
  }>
  all_checks_detail?: Array<{
    type: string
    check_type: string
    passed: boolean
    keyword_results: Array<{ keyword: string; normalized: string; found: boolean }>
  }>
  answer?: string
  gold_answer?: string
  thought_process?: string
  citations?: Array<{
    target_id: string
    doc_id: string
    doc_title: string
    page_idx: number
    section_path: string
    snippet: string
    score: number
  }>
  retrieval_hit_at_5?: number | null
  retrieval_mrr?: number | null
  retrieval_evaluated?: boolean
  predicted_section_paths?: string[]
  retrieval_gold_section_paths?: string[]
  retrieval_gold_chunk_ids?: string[]
  retrieval_gold_doc_ids?: string[]
}

export interface KnowledgeEvalRunResponse {
  generated_at: string
  available_datasets?: KnowledgeEvalDataset[]
  selected_dataset?: KnowledgeEvalDataset | null
  questions: KnowledgeEvalQuestion[]
  report: {
    summary: KnowledgeEvalSummary
    answer: {
      total: number
      answer_non_empty_rate: number
      citation_hit_rate: number
      refusal_correct_rate: number
      correctness_checked_total: number
      answer_correctness_rate: number
      details: KnowledgeEvalAnswerDetail[]
    }
    retrieval: Record<string, any>
    text2sql: Record<string, any>
  }
}

export interface KnowledgeEvalQuestionsResponse {
  datasets?: KnowledgeEvalDataset[]
  selected_dataset?: KnowledgeEvalDataset | null
  questions: KnowledgeEvalQuestion[]
}

export interface PreviewIndexInteractionEventMap {
  toggle: [id: string]
  select: [id: string]
  'update-viewport': [state: { x: number; y: number; scale: number }]
}

/** 知识解析 API 接口，供 composable 依赖注入 */
export interface KnowledgeParseApi {
  getLlmConfigs: () => Promise<any>
  getParseTask: (taskId: string) => Promise<any>
}

/** 知识结构化索引 API 接口，供 composable 依赖注入 */
export interface KnowledgeStructuredApi {
  getStructuredStats: (docId: string) => Promise<any>
  getStructuredIndex: (docId: string, strategy: KnowledgeStrategy, itemType?: string, keyword?: string) => Promise<any>
  updateDocumentBlock: (libraryId: string, docId: string, payload: StructuredNodeUpdatePayload) => Promise<any>
  batchOperateDocumentBlocks: (libraryId: string, docId: string, payload: StructuredBatchOperationPayload) => Promise<any>
  undoLastDocumentBlockOperation: (libraryId: string, docId: string) => Promise<any>
}
