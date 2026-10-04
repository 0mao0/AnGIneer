import { defineStore } from 'pinia'
import { docsApiClient } from '../../../shared/apiClient'
import { clearSessionToken, getSessionToken, setSessionToken } from '../../../shared/session'

/** 多库勾选上限：与 aichat-ui MAX_LIBRARY_SELECTION / 服务端 ANGINEER_MAX_CHAT_LIBRARIES 同值；
 *  跨包导入不值当，宿主侧本地定义（改一处须三处同步） */
const MAX_SELECTED_LIBRARIES = 5

export interface SessionUserInfo {
  username: string
  display_name: string
  libraries: string[]
  default_library?: string
  is_admin?: boolean
}

/** 用户会话：登录 = 账号密码 → 后端签发会话 token；库集合由服务端裁定。
 * 无登录硬门改版后 guestMode 语义 = 未登录态（默认 true，App 挂载时按 token 有效性收敛）。 */
export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: getSessionToken(),
    user: null as SessionUserInfo | null,
    activeLibraryId: '',
    /** 多库勾选集合（阶段三）：activeLibraryId 保持=集合首项（兼容现有单值消费点） */
    activeLibraryIds: [] as string[],
    checking: false,
    guestMode: true,
  }),
  getters: {
    isAuthed: (state) => Boolean(state.token),
    libraryId: (state) => state.activeLibraryId || state.user?.default_library || '',
    libraries: (state) => state.user?.libraries ?? [],
    /** 游客恒只能问默认库（服务端 v0.2.66 闸 + D2 双重约束） */
    effectiveLibraryId: (state) => (state.guestMode ? 'default' : state.activeLibraryId || state.user?.default_library || ''),
  },
  actions: {
    async enterGuestMode() {
      // 幂等签发 HttpOnly ag_guest_id（服务端按 cookie 落 g: 桶，30 轮闸按桶计数）；
      // 已登录调用是安全的 no-op（resolve_pool_owner 永远优先 u:）
      await fetch('/api/chat/guest', { method: 'POST' }).catch(() => {})
      this.guestMode = true
    },
    exitGuestMode() {
      this.guestMode = false
    },
    async login(username: string, password: string) {
      const resp = await docsApiClient.post<{ token: string; user: SessionUserInfo }>(
        '/v1/auth/login',
        { username, password }
      )
      setSessionToken(resp.token)
      this.token = resp.token
      this.user = resp.user
      this.activeLibraryId = resp.user.default_library || resp.user.libraries[0] || ''
      this.activeLibraryIds = this.activeLibraryId ? [this.activeLibraryId] : []
      // 登录即并入游客档（计划 §4「登录后并入」）：老账号 +1 条会话，失败不阻断登录
      if (this.guestMode) {
        this.guestMode = false
        fetch('/api/chat/sessions/claim', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${getSessionToken()}`,
          },
          body: '{}',
        }).catch(() => {})
      }
    },
    async refreshMe() {
      if (!this.token) return
      this.checking = true
      try {
        const me = await docsApiClient.get<SessionUserInfo>('/v1/auth/me')
        this.user = me
        if (!this.activeLibraryId || !(me.libraries || []).includes(this.activeLibraryId)) {
          this.activeLibraryId = me.default_library || me.libraries?.[0] || ''
          this.activeLibraryIds = this.activeLibraryId ? [this.activeLibraryId] : []
        } else if (!this.activeLibraryIds.length) {
          // 集合未初始化但单值有效（刷新后恢复）：并入首项
          this.activeLibraryIds = [this.activeLibraryId]
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
      // 宿主交互入口已改 setActiveLibraries；保留兼容（行为不变：未授权 id 静默忽略，集合收敛为单元素）
      if ((this.user?.libraries ?? []).includes(id)) {
        this.setActiveLibraries([id])
      }
    },
    /** 多库勾选（阶段三）：过滤未授权 + 截断到上限（与前端选择器/服务端兜底一致）；空集合=回退默认库 */
    setActiveLibraries(ids: string[]) {
      const allowed = new Set(this.libraries)
      const next = (ids || []).filter((id) => allowed.has(id)).slice(0, MAX_SELECTED_LIBRARIES)
      // 清空语义（定稿）：空集合 = 回退默认库（与旧 switchLibrary 默认回退一致，
      // 不出现「无库可检索」态）
      this.activeLibraryIds = next.length
        ? next
        : [this.user?.default_library || this.libraries[0] || 'default']
      this.activeLibraryId = this.activeLibraryIds[0]
    },
    async logout() {
      try {
        if (this.token) {
          await docsApiClient.post('/v1/auth/logout')
        }
      } catch {
        // best-effort：本地一定清
      }
      clearSessionToken()
      this.token = ''
      this.user = null
      this.activeLibraryId = ''
      this.activeLibraryIds = []
      this.guestMode = true // 登出落回游客态（直接可聊，不再见登录门）
      void fetch('/api/chat/guest', { method: 'POST' }).catch(() => {}) // 补签游客 cookie，下一轮落 g: 桶
    },
    /** 跨应用/跨标签页同步：重读共享 token，为空则退出，否则刷新用户信息。 */
    async syncExternal() {
      const t = getSessionToken()
      if (t === this.token) return
      if (!t) {
        clearSessionToken()
        this.token = ''
        this.user = null
        this.activeLibraryId = ''
        this.activeLibraryIds = []
        return
      }
      this.token = t
      try {
        await this.refreshMe()
      } catch {
        // 会话无效时 refreshMe 内部已登出，这里吞掉即可
      }
    },
  },
})
