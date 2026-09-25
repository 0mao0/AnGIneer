import { defineStore } from 'pinia'
import { docsApiClient } from '../../../shared/apiClient'
import { clearSessionToken, getSessionToken, setSessionToken } from '../../../shared/session'

export interface AdminSessionUser {
  username: string
  display_name: string
  is_admin: boolean
  libraries: string[]
  default_library?: string
}

/** 管理员会话：账号密码 → 会话 token；与 user-web 共享同一份 cookie 会话。 */
export const useAdminAuthStore = defineStore('adminAuth', {
  state: () => ({
    token: getSessionToken(),
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
        clearSessionToken()
        this.token = ''
        this.user = null
        throw new Error('该账号无管理员权限')
      }
      setSessionToken(resp.token)
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
      clearSessionToken()
      this.token = ''
      this.user = null
    },
    /** 跨应用同步：重读共享 token，为空则退出，否则刷新用户信息（非管理员会触发登出）。 */
    async syncExternal() {
      const t = getSessionToken()
      if (t === this.token) return
      if (!t) {
        clearSessionToken()
        this.token = ''
        this.user = null
        return
      }
      this.token = t
      try {
        await this.refreshMe()
      } catch {
        // 会话无效/非管理员时 refreshMe 内部已登出
      }
    },
  },
})
