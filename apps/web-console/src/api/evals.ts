/** 评测系统 API 客户端。 */
const baseURL = '/api/evals'

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${baseURL}${url}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  })
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(err.detail || `HTTP ${response.status}`)
  }
  return response.json()
}

export const evalsApi = {
  getDatasets: () => request<{ datasets: any[] }>('/datasets'),

  getDataset: (datasetId: string) => request<any>(`/datasets/${datasetId}`),

  createDataset: (payload: { title: string; category: string; description?: string }) =>
    request<any>('/datasets', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  deleteDataset: (datasetId: string) =>
    request<{ status: string }>(`/datasets/${datasetId}`, { method: 'DELETE' }),

  getQuestions: (datasetId: string) =>
    request<{ questions: any[] }>(`/datasets/${datasetId}/questions`),

  addQuestion: (datasetId: string, payload: any) =>
    request<any>(`/datasets/${datasetId}/questions`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  updateQuestion: (datasetId: string, questionId: string, payload: any) =>
    request<any>(`/datasets/${datasetId}/questions/${questionId}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),

  deleteQuestion: (datasetId: string, questionId: string) =>
    request<{ status: string }>(`/datasets/${datasetId}/questions/${questionId}`, {
      method: 'DELETE',
    }),

  exportDataset: (datasetId: string) => request<any>(`/datasets/${datasetId}/export`),

  importDataset: async (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    const response = await fetch(`${baseURL}/datasets/import`, {
      method: 'POST',
      body: formData,
    })
    if (!response.ok) {
      const err = await response.json().catch(() => ({ detail: response.statusText }))
      throw new Error(err.detail || `HTTP ${response.status}`)
    }
    return response.json()
  },

  startRun: (datasetId: string) =>
    request<any>('/runs', {
      method: 'POST',
      body: JSON.stringify({ dataset_id: datasetId }),
    }),

  getRun: (runId: string) => request<any>(`/runs/${runId}`),

  listRuns: (datasetId?: string) => {
    const url = datasetId ? `/runs?dataset_id=${datasetId}` : '/runs'
    return request<{ runs: any[] }>(url)
  },

  compare: (runIdA: string, runIdB: string) =>
    request<any>(`/compare?run_id_a=${runIdA}&run_id_b=${runIdB}`),
}

export default evalsApi
