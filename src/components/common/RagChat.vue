<template>
  <div class="rag-chat-component">
    <div v-if="title" class="rag-chat-header">
      <span v-if="icon" class="header-icon">
        <component :is="icon" />
      </span>
      <span class="header-title">{{ title }}</span>
    </div>
    <div class="chat-messages" ref="messagesRef">
      <div v-for="(msg, index) in messages" :key="index" :class="['message', msg.role]">
        <div class="message-content">
          <div v-if="msg.role === 'user'" class="user-content">
            {{ msg.content }}
          </div>
          <div v-else class="assistant-content">
            <div class="answer-text" v-html="renderMarkdown(msg.content)" />
            <div v-if="msg.sources?.length" class="sources">
              <div class="sources-title">参考来源：</div>
              <a-tag v-for="source in msg.sources" :key="source" color="blue">
                {{ source }}
              </a-tag>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="chat-input">
      <div class="context-hint" v-if="contextItems.length">
        <a-tag v-for="item in contextItems" :key="item.id" closable @close="removeContext(item.id)">
          {{ item.title }}
        </a-tag>
      </div>
      <a-textarea
        v-model:value="inputText"
        :placeholder="placeholder"
        :auto-size="{ minRows: 2, maxRows: 6 }"
        @keydown.enter.ctrl="sendMessage"
      />
      <div class="input-actions">
        <a-select v-model:value="selectedModel" class="model-select" size="small" :loading="loadingModels">
          <a-select-option v-for="model in models" :key="model.value" :value="model.value">
            {{ model.label }}
          </a-select-option>
        </a-select>
        <a-button type="primary" :loading="loading" @click="sendMessage">
          发送
        </a-button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, onMounted } from 'vue'

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  sources?: string[]
}

interface ModelOption {
  value: string
  label: string
}

interface ContextItem {
  id: string
  title: string
}

interface Props {
  model?: string
  placeholder?: string
  contextItems?: ContextItem[]
  title?: string
  icon?: any
}

const props = withDefaults(defineProps<Props>(), {
  model: '',
  placeholder: '输入问题，基于知识库回答...',
  contextItems: () => [],
  title: '',
  icon: undefined
})

const emit = defineEmits<{
  send: [message: string, model: string]
  ready: []
  removeContext: [id: string]
}>()

const inputText = ref('')
const loading = ref(false)
const loadingModels = ref(false)
const selectedModel = ref(props.model)
const messagesRef = ref<HTMLElement | null>(null)
const models = ref<ModelOption[]>([])

/**
 * 从 API 获取可用模型列表
 */
const fetchModels = async () => {
  loadingModels.value = true
  try {
    const response = await fetch('/api/llm_configs')
    if (response.ok) {
      const data = await response.json()
      // 转换后端模型配置为前端选项格式
      models.value = data
        .filter((m: any) => m.configured)
        .map((m: any) => ({
          value: m.name,
          label: m.name
        }))

      // 如果没有指定默认模型，使用第一个可用模型
      if (!selectedModel.value && models.value.length > 0) {
        selectedModel.value = models.value[0].value
      }
    } else {
      // API 失败时使用默认模型
      models.value = [
        { value: 'default', label: '默认模型' }
      ]
      selectedModel.value = 'default'
    }
  } catch (error) {
    console.error('获取模型列表失败:', error)
    // 网络错误时使用默认模型
    models.value = [
      { value: 'default', label: '默认模型' }
    ]
    selectedModel.value = 'default'
  } finally {
    loadingModels.value = false
  }
}

const messages = ref<ChatMessage[]>([])

const renderMarkdown = (content: string) => {
  return content
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\n/g, '<br/>')
}

const sendMessage = async () => {
  if (!inputText.value.trim()) return

  const userMessage = inputText.value
  messages.value.push({ role: 'user', content: userMessage })
  inputText.value = ''

  loading.value = true
  emit('send', userMessage, selectedModel.value)

  await nextTick()
  scrollToBottom()
}

const scrollToBottom = () => {
  if (messagesRef.value) {
    messagesRef.value.scrollTop = messagesRef.value.scrollHeight
  }
}

const addMessage = (message: ChatMessage) => {
  messages.value.push(message)
  loading.value = false
  nextTick(() => scrollToBottom())
}

const clearMessages = () => {
  messages.value = []
}

/**
 * 移除上下文引用项
 */
const removeContext = (id: string) => {
  emit('removeContext', id)
}

defineExpose({
  addMessage,
  clearMessages,
  messages
})

// 组件挂载时获取模型列表
onMounted(() => {
  fetchModels()
  emit('ready')
})
</script>

<style lang="less" scoped>
.rag-chat-component {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.rag-chat-header {
  display: flex;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color, #e8e8e8);
  background: var(--panel-header-bg, #fafafa);
  font-weight: 500;
  font-size: 14px;
  color: var(--text-primary, rgba(0, 0, 0, 0.88));

  .header-icon {
    margin-right: 8px;
    display: flex;
    align-items: center;
  }
}

.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
  background: var(--bg-primary, #fff);

  .message {
    margin-bottom: 16px;

    &.user {
      text-align: right;

      .user-content {
        display: inline-block;
        background: #1890ff;
        color: #fff;
        padding: 8px 14px;
        border-radius: 12px 12px 0 12px;
        max-width: 80%;
        word-break: break-word;
      }
    }

    &.assistant {
      text-align: left;

      .assistant-content {
        display: inline-block;
        background: #f0f0f0;
        color: #333;
        padding: 12px 16px;
        border-radius: 12px 12px 12px 0;
        max-width: 85%;
        word-break: break-word;

        .answer-text {
          line-height: 1.6;

          :deep(code) {
            background: #e8e8e8;
            padding: 2px 6px;
            border-radius: 4px;
            font-family: monospace;
          }
        }

        .sources {
          margin-top: 12px;
          padding-top: 12px;
          border-top: 1px dashed #d9d9d9;

          .sources-title {
            font-size: 12px;
            color: #666;
            margin-bottom: 8px;
          }
        }
      }
    }
  }
}

.chat-input {
  padding: 12px;
  border-top: 1px solid var(--border-color, #e8e8e8);
  background: var(--bg-secondary, #fafafa);
  transition: background-color 0.3s, border-color 0.3s;

  .context-hint {
    margin-bottom: 8px;
  }

  :deep(.ant-input) {
    border-radius: 8px;
    resize: none;
    background: var(--bg-secondary, #fff);
    color: var(--text-primary, rgba(0, 0, 0, 0.88));
    border-color: var(--border-color, #d9d9d9);

    &::placeholder {
      color: var(--text-secondary, rgba(0, 0, 0, 0.45));
    }
  }

  .input-actions {
    display: flex;
    justify-content: flex-end;
    align-items: center;
    margin-top: 8px;
    gap: 8px;

    :deep(.ant-select-selector) {
      background: var(--bg-secondary, #fff);
      color: var(--text-primary, rgba(0, 0, 0, 0.88));
      border-color: var(--border-color, #d9d9d9);
    }

    :deep(.ant-select-arrow) {
      color: var(--text-secondary, rgba(0, 0, 0, 0.45));
    }

    .model-select {
      width: 100px;
      flex-shrink: 0;

      :deep(.ant-select-selector) {
        font-size: 12px;
      }

      :deep(.ant-select-selection-item) {
        font-size: 12px;
      }
    }
  }
}
</style>
