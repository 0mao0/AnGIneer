/** API Key 管理客户端 */
import { docsApiClient } from '../../../shared/apiClient'

const api = docsApiClient

export interface KeyItem {
  id: number
  key_prefix: string
  user_name: string
  is_active: boolean
  created_at: string
  last_used_at: string | null
  scope: string
  library_id: string
  library_name?: string
  doc_count?: number
}

export interface StatisticsItem {
  date?: string
  uploaded_by: string
  count: number
  page_count?: number
}

export const apiKeysApi = {
  list: (): Promise<KeyItem[]> => api.get('/api-keys'),
  create: (data: { user_name: string; scope?: 'doc' | 'chat' | 'both'; library_id: string }): Promise<{ api_key: string; scope: string }> =>
    api.post('/api-keys', data),
  rename: (keyId: number, name: string): Promise<{ status: string; message: string }> =>
    api.put(`/api-keys/${keyId}/rename`, { name }),
  update: (keyId: number, data: { user_name: string; scope: string; library_id: string }): Promise<{ status: string; message: string }> =>
    api.put(`/api-keys/${keyId}`, data),
  toggle: (keyId: number, active: boolean): Promise<{ status: string }> =>
    api.post(`/api-keys/${keyId}/${active ? 'reactivate' : 'deactivate'}`),
  del: (keyId: number): Promise<{ status: string; message: string }> =>
    api.delete(`/api-keys/${keyId}`),
  getStatistics: (startDate: string, endDate: string, groupBy: string = 'day'): Promise<{ status: string; data: StatisticsItem[] }> =>
    api.get('/api-keys/statistics', { params: { start_date: startDate, end_date: endDate, group_by: groupBy } }),
}
