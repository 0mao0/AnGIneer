/** 公开题「答题」走既有评测单题通道（业主 2026-10-15 定）：
 *  POST /api/evals/runs（question_id + save:false）→ 服务端沿评测链路作答（题目自带知识库
 *  scope）并判分 → 前端轮询 GET /api/evals/runs/{run_id} 取回答与判分。
 *  单题 run 是既有语义：不进历史列表（is_full_run=0）、完成后 1 小时由
 *  result_store.cleanup_individual_runs 自动清理——「用完就结束了」，本页不落任何新存储。
 *  走 aichatApiClient：baseURL /api、自动带 Bearer（游客无 token 即匿名，接口本就无鉴权）。 */
import { aichatApiClient } from '../../../shared/apiClient'

export interface RunCitation {
  marker?: string
  doc_title?: string
  title?: string
}

export interface RunScores {
  score?: number | null
  evaluated?: boolean
  semantic_score?: number | null
  semantic_reason?: string
  semantic_passed?: boolean
  judge_used?: string
  [key: string]: unknown
}

export interface RunDetail {
  question_id: string
  /** completed | error | running */
  status: string
  /** correct | incorrect | null（未判分） */
  quality?: string | null
  error?: string
  latency_ms?: number
  prediction?: { answer?: string; citations?: RunCitation[] } | null
  scores?: RunScores | null
}

export interface EvalRun {
  run_id: string
  dataset_id: string
  status: string
  total_questions?: number
  completed_questions?: number
  details?: RunDetail[]
  [key: string]: unknown
}

export const evalRunApi = {
  /** 单题评测：save:false = 不期望沉淀（详情不进历史）；allow_concurrent = 与在跑评测
   *  （如夜巡）并发——公开页没有后台那套占用弹框，否则评测运行期间按钮全哑。 */
  startQuestionRun: (datasetId: string, questionId: string) =>
    aichatApiClient.post<EvalRun>('/evals/runs', {
      dataset_id: datasetId,
      question_id: questionId,
      save: false,
      allow_concurrent: true,
    }),
  /** light=true 只取状态/分数小载荷（轮询用）；终态后 light=false 取全量（含 prediction.answer） */
  getRun: (runId: string, light = false) =>
    aichatApiClient.get<EvalRun>(
      `/evals/runs/${encodeURIComponent(runId)}`,
      light ? { params: { light: true } } : undefined,
    ),
}
