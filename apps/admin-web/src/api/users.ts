/** 用户管理客户端（/api/users，nginx 白名单 + Basic Auth 保护） */
import { docsApiClient } from '../../../shared/apiClient'

export interface AdminUserItem {
  id: number
  username: string
  display_name: string
  is_admin: boolean
  library_ids: string[]
  is_active: boolean
  created_at: string
  last_login_at: string | null
}

export interface LibraryOptionItem {
  id: string
  name: string
}

export const usersApi = {
  list: (): Promise<AdminUserItem[]> => docsApiClient.get('/users'),
  create: (data: { username: string; display_name: string; password: string; is_admin: boolean; library_ids: string[] }): Promise<AdminUserItem> =>
    docsApiClient.post('/users', data),
  update: (id: number, data: { display_name: string; is_admin: boolean; library_ids: string[] }): Promise<{ status: string }> =>
    docsApiClient.put(`/users/${id}`, data),
  resetPassword: (id: number, password: string): Promise<{ status: string }> =>
    docsApiClient.post(`/users/${id}/password`, { password }),
  setActive: (id: number, active: boolean): Promise<{ status: string }> =>
    docsApiClient.post(`/users/${id}/${active ? 'activate' : 'deactivate'}`),
  del: (id: number): Promise<{ status: string }> =>
    docsApiClient.delete(`/users/${id}`),
}
