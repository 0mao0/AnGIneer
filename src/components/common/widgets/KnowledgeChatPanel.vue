<template>
  <BaseChat
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
    :render-message="renderMarkdown"
    @send="handleSend"
    @clear="clearMessages"
    @stop="stopGeneration"
    @remove-context="removeContext"
    @ready="handleReady"
  />
</template>

<script setup lang="ts">
/**
 * 知识域对话面板组件。
 * 在 docs-ui 中承接聊天协议、模型获取与 Markdown 渲染，并复用 ui-kit 的基础聊天 UI。
 */
import { computed, onMounted, ref } from 'vue'
import { BaseChat } from '@angineer/ui-kit'
import { useKnowledgeChat } from '../../../composables/useKnowledgeChat'
import { renderMarkdown } from '../../../utils/knowledge'

interface ModelOption {
  value: string
  label: string
}

interface ContextItem {
  id: string
  title: string
}

interface Props {
  defaultModel?: string
  placeholder?: string
  contextItems?: ContextItem[]
  title?: string
  icon?: any
  systemPrompt?: string
  showContextInfo?: boolean
  showSystemMessages?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  defaultModel: '',
  placeholder: '输入消息，Enter 发送...',
  contextItems: () => [],
  title: 'AI 助手',
  icon: undefined,
  systemPrompt: '',
  showContextInfo: true,
  showSystemMessages: false
})

const emit = defineEmits<{
  send: [message: string, model: string]
  ready: []
  removeContext: [id: string]
  error: [error: Error]
}>()

const {
  messages,
  loading,
  currentStreamContent,
  sendMessage,
  stopGeneration,
  clearMessages,
  getContextTokens,
  getContextRounds
} = useKnowledgeChat({
  defaultModel: props.defaultModel,
  systemPrompt: props.systemPrompt
})

const loadingModels = ref(false)
const models = ref<ModelOption[]>([])

const contextTokens = computed(() => getContextTokens())
const contextRounds = computed(() => getContextRounds())

/**
 * 拉取模型列表并补齐一个兜底项，避免空模型选择框。
 */
const fetchModels = async () => {
  loadingModels.value = true

  try {
    const response = await fetch('/api/llm_configs')
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`)
    }

    const data = await response.json()
    models.value = data
      .filter((model: any) => model.configured)
      .map((model: any) => ({
        value: model.name,
        label: model.name
      }))
  } catch (error) {
    console.error('获取模型列表失败:', error)
    models.value = [{ value: 'default', label: '默认模型' }]
  } finally {
    loadingModels.value = false
  }
}

/**
 * 处理发送动作，并把领域实现细节收敛在 docs-ui 内部。
 */
const handleSend = async (message: string, model: string) => {
  emit('send', message, model)

  try {
    await sendMessage(message, model)
  } catch (error) {
    emit('error', error instanceof Error ? error : new Error(String(error)))
  }
}

/**
 * 把基础组件的上下文移除动作转发给页面层。
 */
const removeContext = (id: string) => {
  emit('removeContext', id)
}

/**
 * 对外透传基础聊天组件 ready 事件。
 */
const handleReady = () => {
  emit('ready')
}

onMounted(() => {
  fetchModels()
})

defineExpose({
  messages,
  clearMessages,
  sendMessage: handleSend
})
</script>
