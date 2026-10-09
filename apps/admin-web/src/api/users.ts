/** 用户管理客户端（/api/users，nginx 白名单 + Basic Auth 保护） */
import { docsApiClient } from '../../../shared/apiClient'

/** V2 两级授权（2026-10-09 设计稿）：组订阅 = 整组授权（excluded_libraries 为组内排除/减法） */
export interface AdminUserGroupSubscription {
  group: string
  excluded_libraries: string[]
}

/** 写协议（创建/编辑/管理员切换共用）：三级键并存——
 *  V2 开：服务端只读 group_subscriptions + direct_library_ids（library_ids 不进订阅表）；
 *  V2 关（回滚层）：服务端只读 library_ids。故三键恒全发，回滚语义不空窗 */
export interface UserAccessPayload {
  library_ids: string[]
  group_subscriptions: AdminUserGroupSubscription[]
  direct_library_ids: string[]
}

export interface AdminUserItem {
  id: number
  username: string
  display_name: string
  is_admin: boolean
  library_ids: string[]
  /** 派生集（V2 开 = 组订阅展开；关 = library_ids 同值）——表格回显/编辑回显真相源（R5/R6） */
  accessible_libraries?: string[]
  /** 编辑回显种子：组订阅现状（组勾选 + 组内扣库反推用） */
  group_subscriptions?: AdminUserGroupSubscription[]
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
  create: (data: { username: string; display_name: string; password: string; is_admin: boolean } & UserAccessPayload): Promise<AdminUserItem> =>
    docsApiClient.post('/users', data),
  update: (id: number, data: { display_name: string; is_admin: boolean } & UserAccessPayload): Promise<{ status: string }> =>
    docsApiClient.put(`/users/${id}`, data),
  resetPassword: (id: number, password: string): Promise<{ status: string }> =>
    docsApiClient.post(`/users/${id}/password`, { password }),
  setActive: (id: number, active: boolean): Promise<{ status: string }> =>
    docsApiClient.post(`/users/${id}/${active ? 'activate' : 'deactivate'}`),
  del: (id: number): Promise<{ status: string }> =>
    docsApiClient.delete(`/users/${id}`),
}
