<template>
  <div class="chat-home">
    <ChatTopBar @open-history="historyOpen = true" @login="loginPrompt = true" />
    <!-- 游客 30 轮闸 / 顶栏登录入口：全屏登录浮层，登录成功后自动消失，当前对话不丢（D2） -->
    <AuthGate v-if="loginPrompt && !authStore.isAuthed" />
    <div v-if="systemWarning" class="system-warning-banner">{{ systemWarning }}</div>
    <div class="chat-body">
      <div class="chat-col">
        <AIChat
          ref="aiChatRef"
          class="chat-instance"
          title=""
          :hero="!hasConversation"
          :show-context-info="false"
          :session-id="sessionId"
          :library-id="libraryId"
          :mention-mode="'document'"
          :library-options="authStore.guestMode ? [] : libraryOptions"
          :library-value="authStore.activeLibraryId"
          :transport="defaultAIChatTransport"
          @send="hasConversation = true"
          @error="onChatError"
          @messages-change="onMessagesChange"
          @select-citation="handleCitationSelect"
          @update:library-value="onLibraryChange"
        >
          <template #hero>
            <h1 class="hero-title">今天，想查点什么？</h1>
          </template>
        </AIChat>
      </div>
      <aside v-if="panelDocId" class="citation-panel">
        <div class="panel-head">
          <span class="panel-title" :title="panelTitle">{{ panelTitle }}</span>
          <a-button type="text" size="small" aria-label="关闭溯源面板" @click="closePanel">
            <template #icon><CloseOutlined /></template>
          </a-button>
        </div>
        <div class="panel-body">
          <DocumentView
            ref="docViewRef"
            :doc-id="panelDocId"
            :library-id="panelLibraryId"
            :title="panelTitle"
            :side-panel-open="false"
          />
        </div>
      </aside>
    </div>
    <HistoryDrawer
      v-model:open="historyOpen"
      :sessions="sessions"
      :current-session-id="sessionId"
      @restore="restoreSession"
      @remove="deleteSession"
      @new-chat="startNewChat"
    />
  </div>
</template>

<script setup lang="ts">
/**
 * 对话优先首页：
 * - Hero 态（无消息）：AIChat hero 模式，居中大输入框；
 * - 对话态：同一 AIChat 实例展示消息流；点引用在右侧溯源面板（复用 DocumentView
 *   的 PDF/Markdown 分支与 bbox 定位）打开目标文档并定位；
 * - 知识库：输入框下拉单选（仅权限内库），@ 提及当前库内文档（文档级圈定检索范围）；
 * - 历史：@messagesChange 落盘 localStorage（chatHistory.ts），抽屉恢复。
 */
import { computed, defineAsyncComponent, nextTick, onMounted, ref, watch } from 'vue'
import { CloseOutlined } from '@ant-design/icons-vue'
import { AIChat } from '@angineer/aichat-ui'
import type { AIChatMessage, AIChatCitation } from '@angineer/aichat-ui'
import type DocumentViewType from '@/views/DocumentView.vue'
import ChatTopBar from '@/components/ChatTopBar.vue'
import HistoryDrawer from '@/components/HistoryDrawer.vue'
import AuthGate from '@/components/AuthGate.vue'
import { defaultAIChatTransport } from '../../../shared/chatTransport'
import { useAuthStore } from '@/stores/auth'
import { knowledgeApi } from '@/api/knowledge'
import {
  deriveTitle,
  fetchSessionMessages,
  listSessions,
  loadActiveSessionId,
  removeSession,
  saveActiveSessionId,
  saveSession,
} from '@/composables/chatHistory'
import type { ChatSessionRecord } from '@/composables/chatHistory'

/**
 * 文档预览栈（pdf.js / KaTeX / xlsx / docx-preview）体积大且首屏用不到：
 * 改异步组件把它挪出对话页分块，页面挂载后在浏览器空闲时预热加载完，
 * 用户点引用时组件已在内存里，不再有额外等待。loader 复用同一 promise 语义，
 * 预热过则秒返回。
 */
const documentViewLoader = () => import('@/views/DocumentView.vue')
const DocumentView = defineAsyncComponent(documentViewLoader)

const authStore = useAuthStore()
/** 游客恒为默认库（D2），登录态按授权库走 */
const libraryId = computed(() => authStore.effectiveLibraryId || 'default')

/** 游客 30 轮闸弹出的登录浮层（login_required 或顶栏「登录」按钮触发） */
const loginPrompt = ref(false)

/** AIChat 错误统一出口：login_required 弹登录（当前对话保留），其余维持组件内展示 */
const onChatError = (error: Error) => {
  if ((error as Error & { code?: string }).code === 'login_required') {
    loginPrompt.value = true
  }
}

// 登录成功（30 轮闸弹窗或顶栏按钮）：关闭弹层 + 刷新历史抽屉——claim 已把游客会话并入账号；
// 登出：guestMode 生效，refreshSessions 内部清空（历史不留给下一位游客/用户）
watch(
  () => authStore.isAuthed,
  () => {
    loginPrompt.value = false
    void refreshSessions()
  }
)

/** 知识库单选下拉：只列当前用户被授权的库，名称解析失败回退显示 id */
const libraryNames = ref<Record<string, string>>({})
const libraryOptions = computed(() =>
  authStore.libraries.map((id) => ({ value: id, label: libraryNames.value[id] || id }))
)
const loadLibraryNames = async () => {
  try {
    const list = await knowledgeApi.getLibraries() as unknown as { id: string; name: string }[]
    libraryNames.value = Object.fromEntries(list.map((l) => [l.id, l.name]))
  } catch {
    // 名称加载失败时下拉回退显示库 id
  }
}
onMounted(() => {
  // 未登录（游客态）：补签游客 cookie，保证首轮问答即落在 g: 桶（幂等，已登录是安全的 no-op）
  if (!authStore.isAuthed) void authStore.enterGuestMode()
  if (!authStore.guestMode) void loadLibraryNames()
  // 空闲预热预览栈：不抢首屏带宽，页面可用后悄悄把它加载完，点引用时无需再等
  const prime = () => { void documentViewLoader() }
  if (typeof requestIdleCallback === 'function') requestIdleCallback(prime, { timeout: 4000 })
  else setTimeout(prime, 1500)
})

const aiChatRef = ref<InstanceType<typeof AIChat> | null>(null)
const docViewRef = ref<InstanceType<typeof DocumentViewType> | null>(null)
const genSessionId = () => `chat-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`

const sessionId = ref(
  loadActiveSessionId(localStorage, authStore.effectiveLibraryId || 'default') || genSessionId()
)
const hasConversation = ref(false)
const historyOpen = ref(false)
const sessions = ref<ChatSessionRecord[]>([])

/** 向量库健康告警（从 AIChat 组件透传） */
const systemWarning = computed(() => aiChatRef.value?.systemWarning ?? '')

/** 溯源面板 */
const panelDocId = ref('')

const panelTitle = ref('')
const panelLibraryId = ref('default')

const refreshSessions = async () => {
  // 游客不显示历史（产品决策 2026-09-18）：游客档只服务端留存，界面不展示
  if (authStore.guestMode) {
    sessions.value = []
    return
  }
  sessions.value = await listSessions(localStorage, libraryId.value)
}
void refreshSessions()

const onMessagesChange = (messages: AIChatMessage[]) => {
  if (!messages.length) return // 新会话/清空不落空记录
  hasConversation.value = true
  void saveSession(localStorage, libraryId.value, {
    id: sessionId.value,
    scene: 'docs',
    title: deriveTitle(messages),
    updatedAt: Date.now(),
    messages: messages.filter(m => m.role !== 'system'),
  })
  void refreshSessions()
}

const handleCitationSelect = async (citation: AIChatCitation) => {
  if (!citation?.doc_id) return
  panelDocId.value = citation.doc_id
  panelTitle.value = citation.doc_title || citation.doc_id
  panelLibraryId.value = libraryId.value
  // 预热过则秒返回；未预热（用户极快点引用）则在这里补齐，保证组件挂载后再定位
  await documentViewLoader()
  await nextTick()
  // DocumentView 内部有 pending 队列：先于文档加载完成调用也安全
  docViewRef.value?.focusCitation?.(citation as any)
}

const closePanel = () => {
  panelDocId.value = ''
  panelTitle.value = ''
}

const restoreSession = async (record: ChatSessionRecord) => {
  historyOpen.value = false
  closePanel()
  sessionId.value = record.id
  saveActiveSessionId(localStorage, libraryId.value, record.id)
  await nextTick() // 等 sessionId watch 切会话完成
  // 消息以服务端为真相源；详情失败降级 localStorage 缓存（离线/存储降级场景）
  let messages = record.messages as AIChatMessage[]
  try {
    messages = (await fetchSessionMessages(record.id)) as AIChatMessage[]
  } catch {
    // 保留缓存
  }
  aiChatRef.value?.loadSession(messages)
  hasConversation.value = true
}

/** 切换知识库：知识库集合变了就开新会话（旧会话历史按库分桶，留在原库） */
const onLibraryChange = async (id: string) => {
  if (!id || id === authStore.activeLibraryId) return
  authStore.switchLibrary(id)
  closePanel()
  rotateSession()
  void refreshSessions() // 历史按新库重新列
}

/** 活跃会话单一轮换点：生成新 id → 透传组件内部换 key（修双生成 id 互相覆盖，§4） */
const rotateSession = () => {
  const newId = genSessionId()
  saveActiveSessionId(localStorage, libraryId.value, newId)
  aiChatRef.value?.startNewChat?.(newId)
  sessionId.value = newId
  hasConversation.value = false
}

const deleteSession = (id: string) => {
  void removeSession(localStorage, libraryId.value, id)
  void refreshSessions()
}

const startNewChat = () => {
  historyOpen.value = false
  closePanel()
  rotateSession()
}
</script>

<style lang="less" scoped>
.chat-home {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--bg-primary);
}

.system-warning-banner {
  flex-shrink: 0;
  padding: 8px 16px;
  background: #fff7e6;
  border-bottom: 1px solid #ffd591;
  color: #ad6800;
  font-size: 13px;
  line-height: 1.5;
}

.chat-body {
  flex: 1;
  min-height: 0;
  display: flex;
  position: relative;
}

.chat-col {
  flex: 1;
  min-width: 0;
  display: flex;
}

.chat-instance {
  flex: 1;
}

.citation-panel {
  width: 55%;
  min-width: 420px;
  display: flex;
  flex-direction: column;
  border-left: 1px solid var(--border-color);
  background: var(--bg-secondary);

  .panel-head {
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 6px 12px;
    border-bottom: 1px solid var(--border-color);

    .panel-title {
      font-size: 13px;
      color: var(--text-secondary);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
  }

  .panel-body {
    flex: 1;
    min-height: 0;
    overflow: hidden;
  }
}

@media (max-width: 1023px) {
  .citation-panel {
    position: absolute;
    inset: 0;
    width: 100%;
    min-width: 0;
    z-index: 20;
  }
}

.hero-title {
  font-size: 28px;
  font-weight: 600;
  margin: 0 0 20px;
  color: var(--text-primary);
}
</style>
