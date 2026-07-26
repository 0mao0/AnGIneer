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
  email: string
  is_active: boolean
  rate_limit_per_minute: number
  created_at: string
  last_used_at: string | null
}

export interface CreateKeyResponse {
  api_key: string
  key_prefix: string
  user_name: string
  email: string
  rate_limit_per_minute: number
  created_at: string
  message: string
}

export const apiKeysApi = {
  list: (): Promise<KeyItem[]> => api.get('/api-keys'),
  create: (data: { user_name: string; email?: string; rate_limit_per_minute?: number }): Promise<CreateKeyResponse> =>
    api.post('/api-keys', data),
  deactivate: (keyId: number): Promise<{ status: string }> => api.post(`/api-keys/${keyId}/deactivate`),
  reactivate: (keyId: number): Promise<{ status: string }> => api.post(`/api-keys/${keyId}/reactivate`),
}
