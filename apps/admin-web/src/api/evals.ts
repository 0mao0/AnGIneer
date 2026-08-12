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
}

export default evalsApi
