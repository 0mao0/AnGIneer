/** API Key 管理客户端 */
import axios from 'axios'
import { getApiClientConfig, registerDataUnwrapInterceptor } from '../../../shared/apiClient'

const api = registerDataUnwrapInterceptor(
  axios.create(getApiClientConfig({ baseURL: '/api' }))
)

export interface KeyItem {
  id: number
  key_prefix: string
  user_name: string
  is_active: boolean
  created_at: string
  last_used_at: string | null
  doc_count?: number
}

export interface StatisticsItem {
  date?: string
  uploaded_by: string
  count: number
}

export const apiKeysApi = {
  list: (): Promise<KeyItem[]> => api.get('/api-keys'),
  create: (data: { user_name: string }): Promise<{ api_key: string }> =>
    api.post('/api-keys', data),
  rename: (keyId: number, name: string): Promise<{ status: string; message: string }> =>
    api.put(`/api-keys/${keyId}/rename`, { name }),
  toggle: (keyId: number, active: boolean): Promise<{ status: string }> =>
    api.post(`/api-keys/${keyId}/${active ? 'reactivate' : 'deactivate'}`),
  del: (keyId: number): Promise<{ status: string; message: string }> =>
    api.delete(`/api-keys/${keyId}`),
  getStatistics: (startDate: string, endDate: string, groupBy: string = 'day'): Promise<{ status: string; data: StatisticsItem[] }> =>
    api.get('/api-keys/statistics', { params: { start_date: startDate, end_date: endDate, group_by: groupBy } }),
}
