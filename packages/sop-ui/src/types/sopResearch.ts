export interface ResearchProject {
  project_id: string
  title: string
  library_id: string
  doc_id: string
  doc_title: string
  status: string
  created_at: string
  updated_at: string
}

export interface ResearchRun {
  run_id: string
  project_id: string
  status: string
  progress: number
  stage: string
  stage_message: string
  stage_current: number
  stage_total: number
  stage_detail: string
  started_at: string
  finished_at: string
  error: string
}

export interface ResearchCandidate {
  candidate_id: string
  run_id: string
  section_path: string
  candidate_type: string
  title: string
  summary: string
  evidence_block_ids: string[]
  raw_score: number
  expected_inputs?: Record<string, any>
  expected_outputs?: Record<string, any>
}

export interface SopResearchDraft {
  draft_id: string
  run_id: string
  candidate_id: string
  title: string
  sop_id_suggested: string
  json_path: string
  review_status: string
  score_total: number
  score_rule: number
  score_model: number
  evidence_block_ids: string[]
  created_at: string
  updated_at: string
}

export interface EvalResearchDraft {
  draft_id: string
  run_id: string
  source_sop_draft_id: string
  dataset_title: string
  question_count: number
  json_path: string
  review_status: string
  created_at: string
  updated_at: string
}

export interface ResearchValidationIssue {
  code: string
  severity: string
  message: string
  location?: string
}

export type ResearchRunStage =
  | 'running' | 'queued' | 'evidence_prepare' | 'candidate_extract' | 'socratic_expand'
  | 'sop_synthesize' | 'eval_generate' | 'rule_validate' | 'score_and_rank'
  | 'completed' | 'failed' | 'cancel_requested' | 'cancelled'
