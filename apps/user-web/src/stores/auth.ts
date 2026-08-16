import { defineStore } from 'pinia'
import { docsApiClient } from '../../../shared/apiClient'

export interface MeInfo {
  key_prefix: string
  user_name: string
  library_id: string
  library_exists: boolean
}

/**
 * 租户身份（P2）：登录 = 持有 API key（管理员发放，已绑定 library_id）。
 * key 存入 localStorage('ag_api_key')，请求拦截器自动附加 X-API-Key，
 * 后端中间件据此强制库隔离；library_id 以 /me 返回的服务端裁定为准。
 */
export const useAuthStore = defineStore('auth', {
  state: () => ({
    apiKey: (typeof localStorage !== 'undefined' ? localStorage.getItem('ag_api_key') : null) ?? '',
    me: null as MeInfo | null,
    checking: false,
  }),
  getters: {
    isAuthed: (state) => Boolean(state.apiKey),
    libraryId: (state) => state.me?.library_id ?? '',
  },
  actions: {
    async login(key: string) {
      const trimmed = key.trim()
      if (!trimmed) throw new Error('请输入 API Key')
      // 先写入 localStorage，让请求拦截器把 X-API-Key 带上
      localStorage.setItem('ag_api_key', trimmed)
      this.apiKey = trimmed
      await this.refreshMe()
    },
    async refreshMe() {
      if (!this.apiKey) return
      this.checking = true
      try {
        const me = await docsApiClient.get<MeInfo>('/v1/auth/me')
        this.me = me
      } catch (e: any) {
        this.me = null
        if (e?.apiError?.status === 401 || e?.apiError?.status === 403) {
          this.logout()
        }
        throw e
      } finally {
        this.checking = false
      }
    },
    logout() {
      localStorage.removeItem('ag_api_key')
      this.apiKey = ''
      this.me = null
    },
  },
})
