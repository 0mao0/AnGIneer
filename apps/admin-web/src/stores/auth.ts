import { defineStore } from 'pinia'
import { docsApiClient } from '../../../shared/apiClient'

export interface AdminSessionUser {
  username: string
  display_name: string
  is_admin: boolean
  libraries: string[]
  default_library?: string
}

/** 管理员会话：账号密码 → 会话 token；与 user-web 同源共享 ag_session_token。 */
export const useAdminAuthStore = defineStore('adminAuth', {
  state: () => ({
    token: (typeof localStorage !== 'undefined' ? localStorage.getItem('ag_session_token') : null) ?? '',
    user: null as AdminSessionUser | null,
    checking: false,
  }),
  getters: {
    isAuthed: (state) => Boolean(state.token),
  },
  actions: {
    async login(username: string, password: string) {
      const resp = await docsApiClient.post<{ token: string; user: AdminSessionUser }>(
        '/v1/auth/login',
        { username, password }
      )
      if (!resp.user.is_admin) {
        localStorage.removeItem('ag_session_token')
        this.token = ''
        this.user = null
        throw new Error('该账号无管理员权限')
      }
      localStorage.setItem('ag_session_token', resp.token)
      this.token = resp.token
      this.user = resp.user
    },
    async refreshMe() {
      if (!this.token) return
      this.checking = true
      try {
        const me = await docsApiClient.get<AdminSessionUser>('/v1/auth/me')
        if (!me.is_admin) {
          this.logout()
          throw new Error('该账号无管理员权限')
        }
        this.user = me
      } catch (e: any) {
        this.user = null
        if (e?.apiError?.status === 401 || e?.apiError?.status === 403) {
          this.logout()
        }
        throw e
      } finally {
        this.checking = false
      }
    },
    async logout() {
      try {
        if (this.token) {
          await docsApiClient.post('/v1/auth/logout')
        }
      } catch {
        // best-effort：本地一定清理
      }
      localStorage.removeItem('ag_session_token')
      this.token = ''
      this.user = null
    },
  },
})
