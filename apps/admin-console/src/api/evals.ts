/** 评测系统 API 客户端。 */
import axios from 'axios'
import { getApiClientConfig, registerDataUnwrapInterceptor } from '../../../shared/apiClient'

const api = registerDataUnwrapInterceptor(axios.create(getApiClientConfig({ baseURL: '/api/evals' })))

export const evalsApi = {
  getDatasets: () => api.get('/datasets'),

  getDataset: (datasetId: string) => api.get(`/datasets/${datasetId}`),

  createDataset: (payload: { title: string; category: string; description?: string }) =>
    api.post('/datasets', payload),

  deleteDataset: (datasetId: string) =>
    api.delete(`/datasets/${datasetId}`),

  getQuestions: (datasetId: string) =>
    api.get(`/datasets/${datasetId}/questions`),

  addQuestion: (datasetId: string, payload: any) =>
    api.post(`/datasets/${datasetId}/questions`, payload),

  updateQuestion: (datasetId: string, questionId: string, payload: any) =>
    api.put(`/datasets/${datasetId}/questions/${questionId}`, payload),

  deleteQuestion: (datasetId: string, questionId: string) =>
    api.delete(`/datasets/${datasetId}/questions/${questionId}`),

  exportDataset: (datasetId: string) =>
    api.get(`/datasets/${datasetId}/export`),

  importDataset: (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return api.post('/datasets/import', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
  },

  startRun: (datasetId: string) =>
    api.post('/runs', { dataset_id: datasetId }),

  getRun: (runId: string) => api.get(`/runs/${runId}`),

  listRuns: (datasetId?: string) => {
    const params = datasetId ? { dataset_id: datasetId } : {}
    return api.get('/runs', { params })
  },

  compare: (runIdA: string, runIdB: string) =>
    api.get('/compare', { params: { run_id_a: runIdA, run_id_b: runIdB } }),

  getFolders: () => api.get('/folders'),

  createFolder: (payload: { folder_id: string; title: string; category: string; parent_folder_id?: string }) =>
    api.post('/folders', payload),

  updateFolder: (folderId: string, payload: { title?: string; parent_folder_id?: string; sort_order?: number }) =>
    api.patch(`/folders/${folderId}`, payload),

  deleteFolder: (folderId: string) =>
    api.delete(`/folders/${folderId}`),

  moveDataset: (datasetId: string, payload: { folder_id: string; sort_order: number }) =>
    api.patch(`/datasets/${datasetId}/move`, payload),
}

export default evalsApi
