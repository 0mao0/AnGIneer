/** Dream Cycle API client（aichat-api）。 */
import { aichatApiClient } from '../../../shared/apiClient'

const api = aichatApiClient

export interface DreamCycleReportSummary {
  date: string
  total_findings: number
  total_auto_fixed: number
  run_duration_seconds: number
  task_count: number
  error?: string
}

export interface TaskResult {
  task_name: string
  status: string
  message: string
  duration_seconds: number
  findings_count: number
  auto_fixed_count: number
}

export interface DuplicateCandidate {
  entity_a_id: string
  entity_a_name: string
  entity_b_id: string
  entity_b_name: string
  match_method: string
  confidence: number
  suggested_action: string
  suggested_canonical_name: string
}

export interface ContradictionCandidate {
  entity_subject: string
  relation_a: Record<string, any>
  relation_b: Record<string, any>
  contradiction_type: string
  suggested_resolution: string
  confidence: number
}

export interface OrphanEntity {
  entity_id: string
  entity_name: string
  entity_layer: string
  age_days: number
  suggested_action: string
}

export interface SopHealthStats {
  total_sops: number
  active_sops: number
  total_steps: number
  most_used_sop: string
  least_used_sop: string
  sops_with_missing_coverage: Array<Record<string, any>>
  avg_step_count: number
}

export interface DreamCycleReport {
  report_date: string
  generated_at: string
  run_duration_seconds: number
  task_results: TaskResult[]
  duplicate_candidates: DuplicateCandidate[]
  contradiction_candidates: ContradictionCandidate[]
  orphan_entities: OrphanEntity[]
  staleness_candidates: any[]
  sop_health: SopHealthStats | null
  total_findings: number
  total_auto_fixed: number
}

export interface HealthStatus {
  enabled: boolean
  last_run: string | null
  today_completed: boolean
  reports_dir: string
  reports_count: number
}

export const dreamCycleApi = {
  /** 获取历史报告列表 */
  async listReports(limit = 30): Promise<{ reports: DreamCycleReportSummary[]; total: number }> {
    return api.get('/dream-cycle/reports', { params: { limit } })
  },

  /** 获取指定日期的完整报告 */
  async getReport(date: string): Promise<DreamCycleReport> {
    return api.get(`/dream-cycle/reports/${date}`)
  },

  /** 手动触发一次运行 */
  async triggerRun(): Promise<{ status: string; message: string; timestamp: string }> {
    return api.post('/dream-cycle/run')
  },

  /** 确认合并两个实体 */
  async confirmMerge(
    entityAId: string,
    entityBId: string,
    canonicalName?: string,
  ): Promise<{ status: string; message: string }> {
    const params = canonicalName ? { canonical_name: canonicalName } : {}
    return api.post(`/dream-cycle/tasks/dedup/confirm/${entityAId}/${entityBId}`, null, { params })
  },

  /** 驳回去重建议 */
  async dismissDedup(
    entityAId: string,
    entityBId: string,
  ): Promise<{ status: string; message: string }> {
    return api.post(`/dream-cycle/tasks/dedup/dismiss/${entityAId}/${entityBId}`)
  },

  /** 健康检查 */
  async health(): Promise<HealthStatus> {
    return api.get('/dream-cycle/health')
  },

  /** 保留孤立实体（标记为非孤立） */
  async orphanKeep(entityId: string): Promise<{ status: string; message: string }> {
    return api.post(`/dream-cycle/tasks/orphan/keep/${entityId}`)
  },

  /** 确认清理孤立实体（标记为 inactive） */
  async orphanConfirmDelete(entityId: string): Promise<{ status: string; message: string }> {
    return api.post(`/dream-cycle/tasks/orphan/delete/${entityId}`)
  },
}
