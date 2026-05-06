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
  failed_correctness_checks?: Array<{ type?: string; keywords?: string[] }>
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
