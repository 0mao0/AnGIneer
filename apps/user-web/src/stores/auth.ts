import { defineStore } from 'pinia'
import { docsApiClient } from '../../../shared/apiClient'
import { clearSessionToken, getSessionToken, setSessionToken } from '../../../shared/session'

// 2026-10-09 多库勾选上限移除（设计稿 design-user-kb-access-scope.md R4/B1 定版，已完结清理、git 历史可查）：
// 原 MAX_SELECTED_LIBRARIES = 5 与服务端 ANGINEER_MAX_CHAT_LIBRARIES 截断同批移除，勾选集合无上限（>20 仅服务端记 warning）。

export interface SessionUserInfo {
  username: string
  display_name: string
  /** 平铺绑定清单（V2 关时的旧语义真相源；V2 开时与 accessible_libraries 并行返回） */
  libraries: string[]
  /** 派生集（R6）：V2 开 = 组订阅展开（含组内将来新增，源头排除 evals）；关 = 等于 libraries。
   *  选择器与成员判定优先读本键，缺失回退 libraries（兼容旧响应/回滚层） */
  accessible_libraries?: string[]
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
    /** 派生集 = 检索范围唯一真相源（R6 统一走派生）；消费点（ChatHome 选择器/setActiveLibraries 过滤）都读它 */
    libraries: (state) => state.user?.accessible_libraries ?? state.user?.libraries ?? [],
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
      // 默认勾选 = 派生集全选（R4「无硬顶，全订阅全选」）：登录即回带服务端集合，与隐式（R3 无 @）等价集，scope_hash 稳定
      const scope = resp.user.accessible_libraries ?? resp.user.libraries ?? []
      this.activeLibraryIds = scope.length ? [...scope] : []
      this.activeLibraryId = this.activeLibraryIds[0] || resp.user.default_library || ''
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
        // 派生集复核（R4/R6）：勾选集合出现非派生成员（订阅变更/组内新建库/库退休）→ 重置为派生集全选
        const allowed = me.accessible_libraries ?? me.libraries ?? []
        const allowedSet = new Set(allowed)
        const kept = (this.activeLibraryIds || []).filter((id) => allowedSet.has(id))
        if (kept.length && kept.length === (this.activeLibraryIds || []).length) {
          this.activeLibraryId = this.activeLibraryId || kept[0]
        } else {
          this.activeLibraryIds = allowed.length ? [...allowed] : []
          this.activeLibraryId = this.activeLibraryIds[0] || me.default_library || ''
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
      if (this.libraries.includes(id)) {
        this.setActiveLibraries([id])
      }
    },
    /** 多库勾选（2026-10-09 无上限改版）：过滤非派生集成员，不截断；空集合=回退默认库 */
    setActiveLibraries(ids: string[]) {
      const allowed = new Set(this.libraries)
      const next = (ids || []).filter((id) => allowed.has(id))
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
