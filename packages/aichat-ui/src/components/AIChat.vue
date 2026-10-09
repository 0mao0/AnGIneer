<template>
  <BaseChat
    ref="baseChatRef"
    :messages="messages"
    :loading="loading"
    :current-stream-content="currentStreamContent"
    :model-groups="modelGroups"
    :show-model-select="showModelSelect"
    :loading-models="loadingModels"
    :default-model="defaultModel"
    :placeholder="placeholder"
    :context-items="contextItems"
    :title="title"
    :icon="icon"
    :show-context-info="showContextInfo"
    :show-system-messages="showSystemMessages"
    :context-tokens="contextTokens"
    :context-rounds="contextRounds"
    :streaming-thinking-steps="liveThinkingSteps"
    :interim-answers="interimAnswers"
    :progress-stage="progressStage"
    :elapsed-seconds="elapsedSeconds"
    :search-citations="searchInlineCitations"
    :render-message="renderAIChatMessage"
    :hero="hero"
    :suggested-questions="suggestedQuestions"
    :show-new-chat="showNewChat"
    :new-chat-label="newChatLabel"
    @new-chat="emit('newChat')"
    :library-options="libraryOptions"
    :library-value="libraryValue"
    :library-multi="libraryMulti"
    :library-values="libraryValues"
    :library-sections="librarySections"
    :queued-messages="queuedMessages"
    :mention-label="mentionMode === 'document' ? '提及文档 @' : '插入引用 @'"
    @send="handleSend"
    @clear="clearMessages"
    @stop="stopGeneration"
    @remove-queued="removeQueued"
    @promote-queued="promoteQueued"
    @remove-context="handleRemoveContext"
    @ready="handleReady"
    @select-citation="handleSelectCitation"
    @update:library-value="emit('update:libraryValue', $event)"
    @update:library-values="emit('update:libraryValues', $event)"
  >
    <template #hero><slot name="hero" /></template>
    <template v-if="$slots['hero-below']" #hero-below><slot name="hero-below" /></template>
  </BaseChat>
</template>

<script setup lang="ts">
/**
 * 统一 AI 对话组件。
 * 封装 BaseChat + useAIChat + 模型获取 + Markdown 渲染。
 * 通过 scene + sessionId 区分不同场景，后端自动路由。
 */
import { onMounted, ref, computed, watch } from 'vue'
import BaseChat from './BaseChat.vue'
import { useAIChat } from '../composables/useAIChat'
import { renderMarkdownToHtml } from '../utils/markdown'
import type { AIChatTransport } from '../api/types'
import type {
  AIChatMessage,
  AIChatCitation,
  BaseChatContextItem,
  BaseChatLibrarySection,
  BaseChatModelGroup,
  BaseChatSendPayload,
  InlineCitationCandidate,
  InlineCitationSearchPayload
} from '../types'
import { mapReferenceSearchCandidate } from '../utils/citation'

interface Props {
  defaultModel?: string
  placeholder?: string
  contextItems?: BaseChatContextItem[]
  title?: string
  icon?: any
  systemPrompt?: string
  showContextInfo?: boolean
  showSystemMessages?: boolean
  scene?: string
  sessionId?: string
  libraryId?: string
  /** Hero 模式（透传 BaseChat）：无消息时展示居中大输入卡片 */
  hero?: boolean
  /** Hero 空态引导问题（透传 BaseChat）：点击即直发；不传或空数组不渲染（可开可关），内容归宿主定 */
  suggestedQuestions?: string[]
  /** 对话态输入框上方显示「新对话」浮层按钮（透传 BaseChat；hero 空态不出现） */
  showNewChat?: boolean
  /** 新对话浮层按钮文案 */
  newChatLabel?: string
  /** 数据传输层注入；不传时组件退化为纯 UI（模型列表为空、无法发送） */
  transport?: AIChatTransport
  /**
   * @ 提及粒度：reference=内容/表格/公式/图条目（默认，兼容旧宿主）；
   * document=只到文档级（候选来自权限库内文档标题，选中后整文档圈定检索范围）。
   */
  mentionMode?: 'reference' | 'document'
  /** 知识库单选下拉选项（为空时不渲染下拉，向后兼容） */
  libraryOptions?: Array<{ value: string; label: string }>
  /** 当前选中的知识库 id */
  libraryValue?: string
  /** 多库勾选集合（阶段三）；配合 library-multi 启用多选选择器 */
  libraryValues?: string[]
  /** 知识库两级分组（可选）：传了且多选时下拉按「组 → 库」两级勾选渲染；缺省平铺选项 */
  librarySections?: BaseChatLibrarySection[]
  /** 多选模式开关（默认 false=单选，向后兼容） */
  libraryMulti?: boolean
  /** 模型选择器显隐（默认 true；游客态宿主传 false，不展示可选模型） */
  showModelSelect?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  defaultModel: '',
  placeholder: '输入消息，按Enter发送\n按Shift+Enter换行...',
  contextItems: () => [],
  title: 'AI 助手',
  icon: undefined,
  systemPrompt: '',
  showContextInfo: true,
  showSystemMessages: false,
  scene: 'docs',
  sessionId: 'default',
  libraryId: 'default',
  hero: false,
  suggestedQuestions: () => [],
  showNewChat: false,
  newChatLabel: '新对话',
  transport: undefined,
  mentionMode: 'reference',
  libraryOptions: () => [],
  libraryValue: '',
  libraryValues: () => [],
  librarySections: () => [],
  libraryMulti: false,
  showModelSelect: true
})

const emit = defineEmits<{
  send: [message: string, model?: string]
  newChat: []
  ready: []
  removeContext: [id: string]
  error: [error: Error]
  answerComplete: [message: AIChatMessage]
  selectCitation: [citation: AIChatCitation]
  messagesChange: [messages: AIChatMessage[]]
  'update:libraryValue': [libraryId: string]
  'update:libraryValues': [libraryIds: string[]]
}>()

const sessionIdRef = computed(() => props.sessionId)
const libraryIdRef = computed(() => props.libraryId)
// 多库集合（阶段三）：空数组=未提供，useAIChat 载荷不带 library_ids（旧宿主逐位不变）
const libraryIdsRef = computed(() => props.libraryValues)

const {
  messages,
  loading,
  currentStreamContent,
  liveThinkingSteps,
  systemWarning,
  contextTokens,
  contextRounds,
  interimAnswers,
  progressStage,
  elapsedSeconds,
  queuedMessages,
  sendMessage,
  stopGeneration,
  removeQueued,
  promoteQueued,
  clearMessages,
  startNewChat,
  loadMessages,
} = useAIChat({
  defaultModel: props.defaultModel,
  systemPrompt: props.systemPrompt,
  libraryId: libraryIdRef,
  libraryIds: libraryIdsRef,
  scene: props.scene,
  sessionId: sessionIdRef,
  getContextItems: () => props.contextItems,
  query: props.transport?.query,
  onError: (error) => emit('error', error)
})

/** 消息数组任何变化（发送/收到回答/停止/报错）都向上抛出，供宿主做持久化 */
watch(messages, (value) => { emit('messagesChange', [...value]) }, { deep: true })

const loadingModels = ref(false)
/** 模型 × 思考等级分组（2026-10-09 业主定版）：由 fetchModels 结果派生，见 buildModelGroups */
const modelGroups = ref<BaseChatModelGroup[]>([])
const baseChatRef = ref<InstanceType<typeof BaseChat> | null>(null)

/** 档位后缀（配置命名约定 `<端点>-<系列>-<档位>`）；未登记的后缀按原样单列，配置不会从选择器静默消失 */
const LEVEL_RE = /^(.*)-(off|xhigh|ctk)$/
/** 档位标签（2026-10-09 业主定版）：无后缀别名/off/ctk 都是思考关闭的不同参数写法 → 统一显示「关」并只出一条；
 *  同语义取值优先级＝无后缀别名 > -off（reasoning_effort=none）> -ctk（enable_thinking=false 探针配置）。
 *  xhigh → 显示「思考」（与「关」成对：关＝不思考、思考＝开思考；档位表是我们 .env 定义的，
 *  xhigh 是底层取值，悬停提示里可见原值） */
const LEVEL_MERGE: Record<string, string> = { off: '关', ctk: '关', xhigh: '思考' }
const LEVEL_RANK: Record<string, number> = { '': 0, off: 1, ctk: 2 }

/**
 * 配置清单 → 模型分组（按底层 model 归并，10 条配置 → 3 个模型 × 语义档位）。
 * 组标签取首个无后缀别名（配置主人把别名排在前面）；无别名时取首档配置名去后缀。多条无后缀别名只留第一条（行为等价）。
 */
const buildModelGroups = (list: Array<{ name: string; model?: string }>): BaseChatModelGroup[] => {
  const order: string[] = []
  interface Draft {
    key: string
    label: string
    levels: Map<string, { label: string; value: string; rank: number }>
    levelOrder: string[]
  }
  const byModel = new Map<string, Draft>()
  for (const c of list) {
    const key = c.model || c.name
    if (!byModel.has(key)) {
      byModel.set(key, { key, label: '', levels: new Map(), levelOrder: [] })
      order.push(key)
    }
    const g = byModel.get(key)!
    const m = LEVEL_RE.exec(c.name)
    const suffix = m ? m[2] : ''
    if (!suffix && !g.label) {
      g.label = c.name
    }
    const semantic = suffix ? LEVEL_MERGE[suffix] || suffix : '关'
    const rank = LEVEL_RANK[suffix] ?? 99
    const exist = g.levels.get(semantic)
    if (!exist) {
      g.levels.set(semantic, { label: semantic, value: c.name, rank })
      g.levelOrder.push(semantic)
    } else if (rank < exist.rank) {
      g.levels.set(semantic, { label: semantic, value: c.name, rank })
    }
  }
  return order
    .map((k) => {
      const g = byModel.get(k)!
      if (!g.label) {
        const first = g.levels.get(g.levelOrder[0])
        g.label = first ? first.value.replace(LEVEL_RE, '$1') : k
      }
      return {
        key: g.key,
        label: g.label,
        levels: g.levelOrder.map((s) => {
          const l = g.levels.get(s)!
          return { label: l.label, value: l.value }
        }),
      }
    })
    // 付费模型沉底（沿用旧单下拉的排序约定）
    .sort((a, b) => Number(a.label.includes('(付费)')) - Number(b.label.includes('(付费)')))
}

/** 将 AI 回复内容渲染为 HTML */
const renderAIChatMessage = (content: string) => renderMarkdownToHtml(content, '')

/** 从后端获取可用模型列表 */
const fetchModels = async () => {
  loadingModels.value = true
  try {
    if (!props.transport?.fetchModels) {
      console.warn('[AIChat] 未配置 transport.fetchModels，模型列表为空')
      modelGroups.value = []
      return
    }
    const data = await props.transport.fetchModels()
    modelGroups.value = buildModelGroups(data.filter((model: any) => model.configured))
  } catch (error) {
    console.error('获取模型列表失败:', error)
    modelGroups.value = []
  } finally {
    loadingModels.value = false
  }
}

/** 处理用户发送消息；model 缺省时 sendMessage 走组件内默认选中（供宿主引导问题直发） */
const handleSend = async (payload: string | BaseChatSendPayload, model?: string) => {
  const normalizedPayload: BaseChatSendPayload = typeof payload === 'string'
    ? { content: payload, citations: [] }
    : payload
  emit('send', normalizedPayload.content, model)
  try {
  const sent = await sendMessage(normalizedPayload as any, model)
  // 生成期间发送只入队（返回 false）：此时最后一条 assistant 还是上一轮的，不能当作本轮答案上报
  if (!sent) return
  const lastAssistantMessage = [...messages.value]
      .reverse()
      .find(item => item.role === 'assistant')
    if (lastAssistantMessage) {
      emit('answerComplete', lastAssistantMessage)
    }
  } catch (error) {
    emit('error', error instanceof Error ? error : new Error(String(error)))
  }
}

const searchInlineCitations = async (query: string): Promise<InlineCitationCandidate[]> => {
  if (!props.transport?.searchReferences) {
    console.warn('[AIChat] 未配置 transport.searchReferences，内联引用检索不可用')
    return []
  }
  const payload: InlineCitationSearchPayload = {
    library_id: props.libraryId,
    query,
    limit: 10,
    // document 模式：候选只到文档级（后端按标题匹配当前库内文档）
    types: props.mentionMode === 'document' ? ['document'] : ['content', 'table', 'formula', 'figure']
  }
  const response = await props.transport.searchReferences(payload)
  const items = Array.isArray(response?.items) ? response.items : []
  return items.map((item: Record<string, any>) => mapReferenceSearchCandidate(item, payload))
}

/** 处理移除上下文标签 */
const handleRemoveContext = (id: string) => { emit('removeContext', id) }

/** 处理组件就绪 */
const handleReady = () => { emit('ready') }

/** 处理引用点击 */
const handleSelectCitation = (citation: any) => { emit('selectCitation', citation as AIChatCitation) }

onMounted(() => { fetchModels() })

defineExpose({
  messages,
  systemWarning,
  queuedMessages,
  clearMessages,
  sendMessage,
  handleSend,
  startNewChat,
  removeQueued,
  promoteQueued,
  loadSession: loadMessages,
  clearComposer: () => baseChatRef.value?.clearComposer?.()
})
</script>
