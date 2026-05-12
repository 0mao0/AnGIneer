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
    :search-citations="searchInlineCitations"
    :render-message="renderAIChatMessage"
    :allow-image-upload="false"
    @send="handleSend"
    @clear="clearMessages"
    @stop="stopGeneration"
    @remove-context="handleRemoveContext"
    @ready="handleReady"
    @select-citation="handleSelectCitation"
  />
</template>

<script setup lang="ts">
/**
 * 统一 AI 对话组件。
 * 封装 BaseChat + useAIChat + 模型获取 + Markdown 渲染。
 * 通过 scene + sessionId 区分不同场景，后端自动路由。
 */
import { onMounted, ref, computed } from 'vue'
import BaseChat from './BaseChat.vue'
import { useAIChat } from '../../composables/useAIChat'
import { renderMarkdownToHtml } from '../../utils/markdown'
import { llmApi, referenceApi } from '../../api/client'
import type {
  AIChatMessage,
  AIChatCitation,
  BaseChatContextItem,
  BaseChatSendPayload,
  InlineCitationCandidate,
  InlineCitationSearchPayload
} from '../../types'
import { mapReferenceSearchCandidate } from '../../utils/citation'

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
}

const props = withDefaults(defineProps<Props>(), {
  defaultModel: '',
  placeholder: '输入消息，Enter 发送...',
  contextItems: () => [],
  title: 'AI 助手',
  icon: undefined,
  systemPrompt: '',
  showContextInfo: true,
  showSystemMessages: false,
  scene: 'docs',
  sessionId: 'default',
  libraryId: 'default'
})

interface ModelOption { value: string; label: string }

const emit = defineEmits<{
  send: [message: string, model: string]
  ready: []
  removeContext: [id: string]
  error: [error: Error]
  answerComplete: [message: AIChatMessage]
  selectCitation: [citation: AIChatCitation]
}>()

const sessionIdRef = computed(() => props.sessionId)

const {
  messages,
  loading,
  currentStreamContent,
  contextTokens,
  contextRounds,
  sendMessage,
  stopGeneration,
  clearMessages,
} = useAIChat({
  defaultModel: props.defaultModel,
  systemPrompt: props.systemPrompt,
  libraryId: props.libraryId,
  scene: props.scene,
  sessionId: sessionIdRef,
  getContextItems: () => props.contextItems
})

const loadingModels = ref(false)
const models = ref<ModelOption[]>([])
const baseChatRef = ref<InstanceType<typeof BaseChat> | null>(null)

/** 将 AI 回复内容渲染为 HTML */
const renderAIChatMessage = (content: string) => renderMarkdownToHtml(content, '')

/** 从后端获取可用模型列表 */
const fetchModels = async () => {
  loadingModels.value = true
  try {
    const data = await llmApi.getConfigs()
    models.value = data
      .filter((model: any) => model.configured)
      .map((model: any) => ({ value: model.name, label: model.name }))
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
  const payload: InlineCitationSearchPayload = {
    library_id: props.libraryId,
    query,
    limit: 10,
    types: ['content', 'table', 'formula', 'figure']
  }
  const response = await referenceApi.search(payload)
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
  clearMessages,
  sendMessage,
  handleSend,
  clearComposer: () => baseChatRef.value?.clearComposer?.()
})
</script>
