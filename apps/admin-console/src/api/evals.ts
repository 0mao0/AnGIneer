/** 评测系统 API 客户端。 */
import axios from 'axios'

const api = axios.create({
  baseURL: '/api/evals',
  headers: { 'Content-Type': 'application/json' },
})

export const evalsApi = {
  getDatasets: () => api.get('/datasets').then(r => r.data),

  getDataset: (datasetId: string) => api.get(`/datasets/${datasetId}`).then(r => r.data),

  createDataset: (payload: { title: string; category: string; description?: string }) =>
    api.post('/datasets', payload).then(r => r.data),

  deleteDataset: (datasetId: string) =>
    api.delete(`/datasets/${datasetId}`).then(r => r.data),

  getQuestions: (datasetId: string) =>
    api.get(`/datasets/${datasetId}/questions`).then(r => r.data),

  addQuestion: (datasetId: string, payload: any) =>
    api.post(`/datasets/${datasetId}/questions`, payload).then(r => r.data),

  updateQuestion: (datasetId: string, questionId: string, payload: any) =>
    api.put(`/datasets/${datasetId}/questions/${questionId}`, payload).then(r => r.data),

  deleteQuestion: (datasetId: string, questionId: string) =>
    api.delete(`/datasets/${datasetId}/questions/${questionId}`).then(r => r.data),

  exportDataset: (datasetId: string) =>
    api.get(`/datasets/${datasetId}/export`).then(r => r.data),

  importDataset: (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return axios.post('/api/evals/datasets/import', formData).then(r => r.data)
  },

  startRun: (datasetId: string) =>
    api.post('/runs', { dataset_id: datasetId }).then(r => r.data),

  getRun: (runId: string) => api.get(`/runs/${runId}`).then(r => r.data),

  listRuns: (datasetId?: string) => {
    const params = datasetId ? { dataset_id: datasetId } : {}
    return api.get('/runs', { params }).then(r => r.data)
  },

  compare: (runIdA: string, runIdB: string) =>
    api.get('/compare', { params: { run_id_a: runIdA, run_id_b: runIdB } }).then(r => r.data),

  getFolders: () => api.get('/folders').then(r => r.data),

  createFolder: (payload: { folder_id: string; title: string; category: string; parent_folder_id?: string }) =>
    api.post('/folders', payload).then(r => r.data),

  updateFolder: (folderId: string, payload: { title?: string; parent_folder_id?: string; sort_order?: number }) =>
    api.patch(`/folders/${folderId}`, payload).then(r => r.data),

  deleteFolder: (folderId: string) =>
    api.delete(`/folders/${folderId}`).then(r => r.data),

  moveDataset: (datasetId: string, payload: { folder_id: string; sort_order: number }) =>
    api.patch(`/datasets/${datasetId}/move`, payload).then(r => r.data),
}

export default evalsApi
