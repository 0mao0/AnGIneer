<template>
  <BaseChat
    ref="baseChatRef"
    :messages="messages"
    :loading="loading"
    :current-stream-content="currentStreamContent"
    :models="models"
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
    :search-citations="searchInlineCitations"
    :render-message="renderAIChatMessage"
    :allow-image-upload="false"
    :hero="hero"
    :library-options="libraryOptions"
    :library-value="libraryValue"
    :mention-label="mentionMode === 'document' ? '提及文档 @' : '插入引用 @'"
    @send="handleSend"
    @clear="clearMessages"
    @stop="stopGeneration"
    @remove-context="handleRemoveContext"
    @ready="handleReady"
    @select-citation="handleSelectCitation"
    @update:library-value="emit('update:libraryValue', $event)"
  >
    <template #hero><slot name="hero" /></template>
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
  transport: undefined,
  mentionMode: 'reference',
  libraryOptions: () => [],
  libraryValue: ''
})

interface ModelOption { value: string; label: string }

const emit = defineEmits<{
  send: [message: string, model: string]
  ready: []
  removeContext: [id: string]
  error: [error: Error]
  answerComplete: [message: AIChatMessage]
  selectCitation: [citation: AIChatCitation]
  messagesChange: [messages: AIChatMessage[]]
  'update:libraryValue': [libraryId: string]
}>()

const sessionIdRef = computed(() => props.sessionId)
const libraryIdRef = computed(() => props.libraryId)

const {
  messages,
  loading,
  currentStreamContent,
  liveThinkingSteps,
  systemWarning,
  contextTokens,
  contextRounds,
  sendMessage,
  stopGeneration,
  clearMessages,
  startNewChat,
  loadMessages,
} = useAIChat({
  defaultModel: props.defaultModel,
  systemPrompt: props.systemPrompt,
  libraryId: libraryIdRef,
  scene: props.scene,
  sessionId: sessionIdRef,
  getContextItems: () => props.contextItems,
  query: props.transport?.query
})

/** 消息数组任何变化（发送/收到回答/停止/报错）都向上抛出，供宿主做持久化 */
watch(messages, (value) => { emit('messagesChange', [...value]) }, { deep: true })

const loadingModels = ref(false)
const models = ref<ModelOption[]>([])
const baseChatRef = ref<InstanceType<typeof BaseChat> | null>(null)

/** 将 AI 回复内容渲染为 HTML */
const renderAIChatMessage = (content: string) => renderMarkdownToHtml(content, '')

/** 从后端获取可用模型列表 */
const fetchModels = async () => {
  loadingModels.value = true
  try {
    if (!props.transport?.fetchModels) {
      console.warn('[AIChat] 未配置 transport.fetchModels，模型列表为空')
      models.value = []
      return
    }
    const data = await props.transport.fetchModels()
    models.value = data
      .filter((model: any) => model.configured)
      .map((model: any) => ({ value: model.name, label: model.name }))
      .sort((a, b) => Number(a.label.includes('(付费)')) - Number(b.label.includes('(付费)')))
  } catch (error) {
    console.error('获取模型列表失败:', error)
    models.value = [{ value: 'default', label: '默认模型' }]
  } finally {
    loadingModels.value = false
  }
}

/** 处理用户发送消息 */
const handleSend = async (payload: string | BaseChatSendPayload, model: string) => {
  const normalizedPayload: BaseChatSendPayload = typeof payload === 'string'
    ? { content: payload, citations: [] }
    : payload
  emit('send', normalizedPayload.content, model)
  try {
    await sendMessage(normalizedPayload as any, model)
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
  clearMessages,
  sendMessage,
  handleSend,
  startNewChat,
  loadSession: loadMessages,
  clearComposer: () => baseChatRef.value?.clearComposer?.()
})
</script>
