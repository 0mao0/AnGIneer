import { defineStore } from 'pinia'
import { docsApiClient } from '../../../shared/apiClient'

export interface SessionUserInfo {
  username: string
  display_name: string
  libraries: string[]
  default_library?: string
  is_admin?: boolean
}

/** 用户会话：登录 = 账号密码 → 后端签发会话 token；库集合由服务端裁定。 */
export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: (typeof localStorage !== 'undefined' ? localStorage.getItem('ag_session_token') : null) ?? '',
    user: null as SessionUserInfo | null,
    activeLibraryId: '',
    checking: false,
  }),
  getters: {
    isAuthed: (state) => Boolean(state.token),
    libraryId: (state) => state.activeLibraryId || state.user?.default_library || '',
    libraries: (state) => state.user?.libraries ?? [],
  },
  actions: {
    async login(username: string, password: string) {
      const resp = await docsApiClient.post<{ token: string; user: SessionUserInfo }>(
        '/v1/auth/login',
        { username, password }
      )
      localStorage.setItem('ag_session_token', resp.token)
      this.token = resp.token
      this.user = resp.user
      this.activeLibraryId = resp.user.default_library || resp.user.libraries[0] || ''
    },
    async refreshMe() {
      if (!this.token) return
      this.checking = true
      try {
        const me = await docsApiClient.get<SessionUserInfo>('/v1/auth/me')
        this.user = me
        if (!this.activeLibraryId || !(me.libraries || []).includes(this.activeLibraryId)) {
          this.activeLibraryId = me.default_library || me.libraries?.[0] || ''
        }
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
    switchLibrary(id: string) {
      if ((this.user?.libraries ?? []).includes(id)) {
        this.activeLibraryId = id
      }
    },
    async logout() {
      try {
        if (this.token) {
          await docsApiClient.post('/v1/auth/logout')
        }
      } catch {
        // best-effort：本地一定清
      }
      localStorage.removeItem('ag_session_token')
      this.token = ''
      this.user = null
      this.activeLibraryId = ''
    },
  },
})
