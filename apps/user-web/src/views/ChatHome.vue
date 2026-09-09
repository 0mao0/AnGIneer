<template>
  <div class="chat-home">
    <ChatTopBar @open-history="historyOpen = true" />
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
          :library-options="libraryOptions"
          :library-value="authStore.activeLibraryId"
          :transport="defaultAIChatTransport"
          @send="hasConversation = true"
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
import { computed, defineAsyncComponent, nextTick, onMounted, ref } from 'vue'
import { CloseOutlined } from '@ant-design/icons-vue'
import { AIChat } from '@angineer/aichat-ui'
import type { AIChatMessage, AIChatCitation } from '@angineer/aichat-ui'
import type DocumentViewType from '@/views/DocumentView.vue'
import ChatTopBar from '@/components/ChatTopBar.vue'
import HistoryDrawer from '@/components/HistoryDrawer.vue'
import { defaultAIChatTransport } from '../../../shared/chatTransport'
import { useAuthStore } from '@/stores/auth'
import { knowledgeApi } from '@/api/knowledge'
import {
  deriveTitle,
  listSessions,
  removeSession,
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
const libraryId = computed(() => authStore.libraryId || 'default')

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
  void loadLibraryNames()
  // 空闲预热预览栈：不抢首屏带宽，页面可用后悄悄把它加载完，点引用时无需再等
  const prime = () => { void documentViewLoader() }
  if (typeof requestIdleCallback === 'function') requestIdleCallback(prime, { timeout: 4000 })
  else setTimeout(prime, 1500)
})

const aiChatRef = ref<InstanceType<typeof AIChat> | null>(null)
const docViewRef = ref<InstanceType<typeof DocumentViewType> | null>(null)

const sessionId = ref(`chat-${Date.now().toString(36)}`)
const hasConversation = ref(false)
const historyOpen = ref(false)
const sessions = ref<ChatSessionRecord[]>([])

/** 向量库健康告警（从 AIChat 组件透传） */
const systemWarning = computed(() => aiChatRef.value?.systemWarning ?? '')

/** 溯源面板 */
const panelDocId = ref('')
const panelTitle = ref('')
const panelLibraryId = ref('default')

const refreshSessions = () => {
  sessions.value = listSessions(localStorage, libraryId.value)
}
refreshSessions()

const onMessagesChange = (messages: AIChatMessage[]) => {
  if (!messages.length) return // 新会话/清空不落空记录
  hasConversation.value = true
  saveSession(localStorage, libraryId.value, {
    id: sessionId.value,
    scene: 'docs',
    title: deriveTitle(messages),
    updatedAt: Date.now(),
    messages: messages.filter(m => m.role !== 'system'),
  })
  refreshSessions()
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
  await nextTick() // 等 sessionId watch 切会话完成
  aiChatRef.value?.loadSession(record.messages as AIChatMessage[])
  hasConversation.value = true
}

/** 切换知识库：知识库集合变了就开新会话（旧会话历史按库分桶，留在原库） */
const onLibraryChange = async (id: string) => {
  if (!id || id === authStore.activeLibraryId) return
  authStore.switchLibrary(id)
  closePanel()
  aiChatRef.value?.startNewChat?.()
  sessionId.value = `chat-${Date.now().toString(36)}`
  hasConversation.value = false
  refreshSessions() // 历史按新库重新列
}

const deleteSession = (id: string) => {
  removeSession(localStorage, libraryId.value, id)
  refreshSessions()
}

const startNewChat = () => {
  historyOpen.value = false
  closePanel()
  aiChatRef.value?.startNewChat?.() // 内部：停止生成 + 清消息 + 换会话 key
  sessionId.value = `chat-${Date.now().toString(36)}` // 与内部新 key 对齐
  hasConversation.value = false
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
