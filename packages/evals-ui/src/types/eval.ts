/** 评测意图层级 */
export type EvalIntentLevel = 'L1' | 'L2' | 'L3' | 'L4'

/** 评测题目难度 */
export type EvalDifficulty = 'easy' | 'medium' | 'hard'

/** 评测题目状态 */
export type EvalQuestionStatus = 'pending' | 'running' | 'passed' | 'failed' | 'error'

/** 评测运行状态 */
export type EvalRunStatus = 'running' | 'completed' | 'failed'

/** 测试集类别 */
export type EvalDatasetCategory = 'knowledge' | 'sop' | 'full_chain'

/** 检索评测标准答案 */
export interface RetrievalGold {
  gold_section_paths: string[]
  gold_chunk_ids: string[]
  gold_doc_ids: string[]
}

/** 正确性断言 */
export interface CorrectnessCheck {
  type: string
  keywords: string[]
}

/** 回答评测标准答案 */
export interface AnswerGold {
  gold_answer: string
  correctness_checks: CorrectnessCheck[]
  semantic_threshold: number
  must_cite_target_ids?: string[]
  must_cite_section_paths?: string[]
  refusal_expected?: boolean
  thought_process?: string
}

/** SQL 评测标准答案 */
export interface SqlGold {
  expected_sql: string
  expected_result?: Record<string, unknown>
}

/** SOP 评测标准答案 */
export interface SopGold {
  expected_sop_id: string
  expected_steps: string[]
  expected_result?: Record<string, unknown>
}

/** 评测题目 */
export interface EvalQuestion {
  question_id: string
  dataset_id: string
  question: string
  task_type: string
  intent_level: EvalIntentLevel
  difficulty: EvalDifficulty
  tags: string[]
  library_id: string
  doc_ids: string[]
  retrieval_gold?: RetrievalGold | null
  answer_gold?: AnswerGold | null
  sql_gold?: SqlGold | null
  sop_gold?: SopGold | null
  sort_order: number
}

/** 测试集 */
export interface EvalDataset {
  dataset_id: string
  title: string
  category: EvalDatasetCategory
  description: string
  schema_version: string
  version: string
  library_id: string
  question_count: number
  source_file: string
  created_at: string
  updated_at: string
}

/** 评测运行详情 */
export interface EvalRunDetail {
  id: number
  run_id: string
  question_id: string
  status: EvalQuestionStatus | 'skipped'
  prediction?: Record<string, unknown> | null
  scores?: Record<string, unknown> | null
  all_scores?: Record<string, Record<string, unknown>> | null
  all_predictions?: Record<string, Record<string, unknown>> | null
  error?: string | null
  latency_ms?: number | null
}

/** 评测运行 */
export interface EvalRun {
  run_id: string
  dataset_id: string
  status: EvalRunStatus
  total_questions: number
  completed_questions: number
  started_at: string
  completed_at?: string | null
  summary_scores?: EvalSummaryScores | null
  details?: EvalRunDetail[]
}

/** 评测汇总得分 */
export interface EvalSummaryScores {
  overall_score: number
  total?: number
  passed?: number
  retrieval_score?: number | null
  answer_score?: number | null
  sql_score?: number | null
  by_level?: Record<string, { total: number; passed: number }>
  error?: string
}

/** 对比结果 */
export interface EvalCompareResult {
  run_a: { run_id: string; status: string; summary_scores: EvalSummaryScores }
  run_b: { run_id: string; status: string; summary_scores: EvalSummaryScores }
  score_diff: Record<string, number>
  question_changes: Array<{
    question_id: string
    status_a: string
    status_b: string
    change: 'improved' | 'regressed'
  }>
}
