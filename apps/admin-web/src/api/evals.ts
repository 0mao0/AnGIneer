/** 评测系统 API 客户端（aichat-api）。 */
import { aichatApiClient } from '../../../shared/apiClient'

const api = aichatApiClient

/** 将路径参数编码为 URL 安全的 segment，避免中文/空格/斜杠等导致请求路径解析异常。 */
const encodePathSegment = (value: string): string => encodeURIComponent(value)

export const evalsApi = {
  getDatasets: () => api.get('/evals/datasets'),

  getDataset: (datasetId: string) => api.get(`/evals/datasets/${encodePathSegment(datasetId)}`),

  createDataset: (payload: { title: string; category: string; description?: string }) =>
    api.post('/evals/datasets', payload),

  deleteDataset: (datasetId: string) =>
    api.delete(`/evals/datasets/${encodePathSegment(datasetId)}`),

  getQuestions: (datasetId: string) =>
    api.get(`/evals/datasets/${encodePathSegment(datasetId)}/questions`),

  addQuestion: (datasetId: string, payload: any) =>
    api.post(`/evals/datasets/${encodePathSegment(datasetId)}/questions`, payload),

  updateQuestion: (datasetId: string, questionId: string, payload: any) =>
    api.put(`/evals/datasets/${encodePathSegment(datasetId)}/questions/${encodePathSegment(questionId)}`, payload),

  deleteQuestion: (datasetId: string, questionId: string) =>
    api.delete(`/evals/datasets/${encodePathSegment(datasetId)}/questions/${encodePathSegment(questionId)}`),

  exportDataset: (datasetId: string) =>
    api.get(`/evals/datasets/${encodePathSegment(datasetId)}/export`),

  importDataset: (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return api.post('/evals/datasets/import', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
  },

  startRun: (datasetId: string) =>
    api.post('/evals/runs', { dataset_id: datasetId }),

  deleteRun: (runId: string) =>
    api.delete(`/evals/runs/${encodePathSegment(runId)}`),

  getRun: (runId: string) => api.get(`/evals/runs/${encodePathSegment(runId)}`),

  listRuns: (datasetId?: string) => {
    const params = datasetId ? { dataset_id: datasetId } : {}
    return api.get('/evals/runs', { params })
  },

  compare: (runIdA: string, runIdB: string) =>
    api.get('/evals/compare', { params: { run_id_a: runIdA, run_id_b: runIdB } }),

  analyzeCompare: (runIdA: string, runIdB: string, questionId: string) =>
    api.post('/evals/compare/analyze', { run_id_a: runIdA, run_id_b: runIdB, question_id: questionId }),

  getFolders: () => api.get('/evals/folders'),

  createFolder: (payload: { folder_id: string; title: string; category: string; parent_folder_id?: string }) =>
    api.post('/evals/folders', payload),

  updateFolder: (folderId: string, payload: { title?: string; parent_folder_id?: string; sort_order?: number }) =>
    api.patch(`/evals/folders/${encodePathSegment(folderId)}`, payload),

  deleteFolder: (folderId: string) =>
    api.delete(`/evals/folders/${encodePathSegment(folderId)}`),

  moveDataset: (datasetId: string, payload: { folder_id: string; sort_order: number }) =>
    api.patch(`/evals/datasets/${encodePathSegment(datasetId)}/move`, payload),

  /** 夜间维护：历史列表（倒序，仅管理员会话可见） */
  getNightlyList: () => api.get('/evals/nightly'),

  /** 夜间维护：单日详情（结论 json + report.md 原文） */
  getNightlyDay: (date: string) => api.get(`/evals/nightly/${encodePathSegment(date)}`),

  /** 夜间维护：调度配置（每晚北京时间 + 启用开关 + 上次/下次触发） */
  getNightlySettings: () => api.get('/evals/nightly/settings'),

  /** 夜间维护：保存调度配置 */
  saveNightlySettings: (payload: { enabled: boolean; hour: number; minute: number }) =>
    api.put('/evals/nightly/settings', payload),

  /** 夜间维护：立即启动一次全内置流水线（后台跑，结果异步出） */
  runNightlyNow: () => api.post('/evals/nightly/run-now'),

  /** 夜间维护：立即运行前的执行计划预览（测试集/模型/并发，仅配置名） */
  getNightlyRunPlan: () => api.get('/evals/nightly/run-plan'),

  /** 夜间维护：停止运行中的流水线（当前题完成后收尾，不落结论、不发通知） */
  stopNightly: () => api.post('/evals/nightly/stop'),

  /** 夜间维护：删除一条结论（连带删除对应评测 run；run 在跑则先停） */
  deleteNightlyDay: (date: string) => api.delete(`/evals/nightly/${encodePathSegment(date)}`),

  /** 解析回归（A 层）：本机跑完 --publish 上来的 run 列表（倒序，只读） */
  getParseRegressionRuns: () => api.get('/evals/parse-regression'),

  /** 解析回归：单次 run 详情（结论载荷 + summary.md + A② 逐类目报告） */
  getParseRegressionRun: (runId: string) =>
    api.get(`/evals/parse-regression/${encodePathSegment(runId)}`),
}

export default evalsApi
