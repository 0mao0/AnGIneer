<template>
  <div class="base-chat-component">
    <div v-if="title" class="chat-header">
      <span v-if="icon" class="header-icon">
        <component :is="icon" />
      </span>
      <span class="header-title">{{ title }}</span>
      <div class="header-actions">
        <a-tag v-if="showContextInfo" class="context-info" size="small">
          {{ contextRounds }}轮 / {{ contextTokens }}tokens
        </a-tag>
        <a-button type="text" size="small" @click="handleClear">
          <template #icon><ClearOutlined /></template>
          清空
        </a-button>
      </div>
    </div>

    <div ref="messagesRef" class="chat-messages">
      <div
        v-for="(msg, index) in displayMessages"
        :key="msg.id || index"
        :class="['message', msg.role]"
      >
        <div class="message-content">
          <template v-if="msg.role === 'user'">
            <div class="user-content">
              <div v-if="msg.images?.length" class="user-images">
                <img
                  v-for="(img, idx) in msg.images"
                  :key="idx"
                  :src="img"
                  class="uploaded-image"
                  alt="上传的图片"
                />
              </div>
              <div class="user-text">{{ msg.content }}</div>
            </div>
          </template>

          <template v-else-if="msg.role === 'assistant'">
            <div class="assistant-content">
              <div class="answer-text" v-html="renderContent(msg.content)" />
            </div>
          </template>

          <template v-else-if="msg.role === 'system' && showSystemMessages">
            <div class="system-content">
              <InfoCircleOutlined />
              <span>系统：{{ msg.content }}</span>
            </div>
          </template>
        </div>
      </div>

      <div v-if="loading && currentStreamContent" class="message assistant streaming">
        <div class="message-content">
          <div class="assistant-content">
            <div class="answer-text" v-html="renderContent(currentStreamContent)" />
            <span class="streaming-cursor">|</span>
          </div>
        </div>
      </div>

      <div v-if="loading && !currentStreamContent" class="message assistant loading">
        <div class="message-content">
          <div class="assistant-content">
            <a-spin size="small" />
            <span class="loading-text">思考中...</span>
          </div>
        </div>
      </div>
    </div>

    <div
      class="resize-handle"
      title="拖动调整输入区域高度"
      @mousedown="startResize"
    >
      <div class="resize-indicator"></div>
    </div>

    <div ref="chatInputRef" class="chat-input" :style="{ height: `${inputHeight}px` }">
      <div v-if="contextItems.length" class="context-hint">
        <a-tag
          v-for="item in contextItems"
          :key="item.id"
          closable
          @close="handleRemoveContext(item.id)"
        >
          {{ item.title }}
        </a-tag>
      </div>

      <div v-if="pendingImages.length" class="image-preview">
        <div
          v-for="(img, idx) in pendingImages"
          :key="idx"
          class="preview-item"
        >
          <img :src="img" alt="预览" />
          <CloseCircleOutlined class="remove-btn" @click="removeImage(idx)" />
        </div>
      </div>

      <div class="input-wrapper">
        <a-textarea
          v-model:value="inputText"
          :placeholder="placeholder"
          :disabled="loading"
          :rows="3"
          @keydown.enter.prevent="handleEnter"
        />

        <div class="input-actions">
          <div class="left-actions">
            <a-button
              type="text"
              size="small"
              :disabled="loading || !allowImageUpload"
              :title="allowImageUpload ? '上传图片（开发中）' : '图片上传不可用'"
              @click="handleImageUpload"
            >
              <template #icon><PictureOutlined /></template>
            </a-button>
            <input
              ref="imageInputRef"
              type="file"
              accept="image/*"
              multiple
              style="display: none"
              @change="onImageSelected"
            />
          </div>

          <div class="center-actions">
            <a-select
              v-model:value="selectedModel"
              class="model-select"
              size="small"
              :loading="loadingModels"
              :disabled="loading"
              :title="selectedModel"
              @change="onModelChange"
            >
              <a-select-option
                v-for="model in models"
                :key="model.value"
                :value="model.value"
                :title="model.label"
              >
                {{ model.label }}
              </a-select-option>
            </a-select>
          </div>

          <div class="right-actions">
            <a-button
              v-if="loading"
              type="primary"
              danger
              size="small"
              class="icon-btn"
              title="停止生成"
              @click="handleStop"
            >
              <PauseCircleOutlined />
            </a-button>
            <a-button
              v-else
              type="primary"
              size="small"
              class="icon-btn"
              :disabled="!inputText.trim() && !pendingImages.length"
              title="发送消息 (Enter)"
              @click="handleSend"
            >
              <SendOutlined />
            </a-button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 基础聊天组件。
 * 负责通用聊天 UI、输入区交互与消息展示，不直接耦合具体知识域接口。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  ClearOutlined,
  SendOutlined,
  PauseCircleOutlined,
  PictureOutlined,
  CloseCircleOutlined,
  InfoCircleOutlined
} from '@ant-design/icons-vue'
import type { BaseChatContextItem, BaseChatMessage, BaseChatModelOption } from '../../types'

interface Props {
  messages: BaseChatMessage[]
  loading: boolean
  currentStreamContent?: string
  models?: BaseChatModelOption[]
  loadingModels?: boolean
  defaultModel?: string
  placeholder?: string
  contextItems?: BaseChatContextItem[]
  title?: string
  icon?: any
  showContextInfo?: boolean
  showSystemMessages?: boolean
  contextTokens?: number
  contextRounds?: number
  renderMessage?: (content: string) => string
  allowImageUpload?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  currentStreamContent: '',
  models: () => [],
  loadingModels: false,
  defaultModel: '',
  placeholder: '输入消息，Enter 发送...',
  contextItems: () => [],
  title: 'AI 助手',
  icon: undefined,
  showContextInfo: true,
  showSystemMessages: false,
  contextTokens: 0,
  contextRounds: 0,
  renderMessage: undefined,
  allowImageUpload: true
})

const emit = defineEmits<{
  send: [message: string, model: string]
  ready: []
  clear: []
  stop: []
  removeContext: [id: string]
  modelChange: [model: string]
}>()

const messagesRef = ref<HTMLElement | null>(null)
const chatInputRef = ref<HTMLElement | null>(null)
const imageInputRef = ref<HTMLInputElement | null>(null)
const inputText = ref('')
const pendingImages = ref<string[]>([])
const selectedModel = ref(props.defaultModel)
const inputHeight = ref(150)
const isResizing = ref(false)
const startY = ref(0)
const startHeight = ref(0)
const minInputHeight = 100
const maxInputHeightRatio = 0.5

const displayMessages = computed(() => {
  if (props.showSystemMessages) {
    return props.messages
  }

  return props.messages.filter(message => message.role !== 'system')
})

/**
 * 转义纯文本内容，避免在默认渲染路径中注入 HTML。
 */
const escapeHtml = (content: string): string => {
  return content
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

/**
 * 渲染消息内容。
 * 如果上层提供了领域渲染器，则优先使用；否则退回纯文本换行渲染。
 */
const renderContent = (content: string): string => {
  if (props.renderMessage) {
    return props.renderMessage(content)
  }

  return escapeHtml(content).replace(/\n/g, '<br />')
}

/**
 * 将消息区域滚动到底部。
 */
const scrollToBottom = () => {
  nextTick(() => {
    if (messagesRef.value) {
      messagesRef.value.scrollTop = messagesRef.value.scrollHeight
    }
  })
}

/**
 * 在模型列表变化后同步默认模型，避免空选中状态。
 */
const syncSelectedModel = () => {
  if (selectedModel.value) {
    return
  }

  if (props.defaultModel) {
    selectedModel.value = props.defaultModel
    return
  }

  if (props.models.length > 0) {
    selectedModel.value = props.models[0].value
  }
}

/**
 * 处理回车发送与 Shift+Enter 换行。
 */
const handleEnter = (event: KeyboardEvent) => {
  if (event.shiftKey) {
    return
  }

  event.preventDefault()
  handleSend()
}

/**
 * 触发发送事件并在成功发起后清空输入态。
 */
const handleSend = () => {
  const content = inputText.value.trim()
  if (!content && !pendingImages.value.length) {
    return
  }

  emit('send', content, selectedModel.value)
  inputText.value = ''
  pendingImages.value = []
  scrollToBottom()
}

/**
 * 通知上层清空当前会话。
 */
const handleClear = () => {
  emit('clear')
}

/**
 * 通知上层停止当前流式生成。
 */
const handleStop = () => {
  emit('stop')
}

/**
 * 通知上层移除上下文标签。
 */
const handleRemoveContext = (id: string) => {
  emit('removeContext', id)
}

/**
 * 响应模型切换事件。
 */
const onModelChange = (model: string) => {
  selectedModel.value = model
  emit('modelChange', model)
}

/**
 * 打开隐藏的图片选择框。
 */
const handleImageUpload = () => {
  if (!props.allowImageUpload) {
    return
  }

  imageInputRef.value?.click()
}

/**
 * 读取图片为预览数据，供后续多模态能力接入。
 */
const onImageSelected = (event: Event) => {
  const target = event.target as HTMLInputElement
  const files = target.files
  if (!files) {
    return
  }

  Array.from(files).forEach(file => {
    const reader = new FileReader()
    reader.onload = loadEvent => {
      if (loadEvent.target?.result) {
        pendingImages.value.push(loadEvent.target.result as string)
      }
    }
    reader.readAsDataURL(file)
  })

  target.value = ''
}

/**
 * 移除待发送图片预览项。
 */
const removeImage = (index: number) => {
  pendingImages.value.splice(index, 1)
}

/**
 * 开始拖动调整输入区高度。
 */
const startResize = (event: MouseEvent) => {
  isResizing.value = true
  startY.value = event.clientY
  startHeight.value = inputHeight.value

  document.addEventListener('mousemove', handleResize)
  document.addEventListener('mouseup', stopResize)
}

/**
 * 根据鼠标位移实时更新输入区高度。
 */
const handleResize = (event: MouseEvent) => {
  if (!isResizing.value) {
    return
  }

  const deltaY = startY.value - event.clientY
  const newHeight = startHeight.value + deltaY
  const parentHeight = chatInputRef.value?.parentElement?.clientHeight || window.innerHeight
  const maxHeight = parentHeight * maxInputHeightRatio

  inputHeight.value = Math.max(minInputHeight, Math.min(newHeight, maxHeight))
}

/**
 * 结束拖动调整并解绑全局事件。
 */
const stopResize = () => {
  isResizing.value = false
  document.removeEventListener('mousemove', handleResize)
  document.removeEventListener('mouseup', stopResize)
}

watch(() => props.messages.length, scrollToBottom)
watch(() => props.currentStreamContent, scrollToBottom)
watch(() => props.defaultModel, value => {
  selectedModel.value = value
})
watch(() => props.models, syncSelectedModel, { deep: true, immediate: true })

onMounted(() => {
  syncSelectedModel()
  emit('ready')
})

onBeforeUnmount(() => {
  stopResize()
})

defineExpose({
  inputText,
  selectedModel
})
</script>

<style lang="less" scoped>
.base-chat-component {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-primary, #fff);
}

.chat-header {
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

  .header-title {
    flex: 1;
  }

  .header-actions {
    display: flex;
    align-items: center;
    gap: 4px;

    .context-info {
      font-size: 12px;
      color: var(--text-secondary, rgba(0, 0, 0, 0.45));
      margin-right: 4px;
    }

    :deep(.ant-btn) {
      padding: 0 4px;
    }
  }
}

.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  background: var(--bg-primary, #fff);

  .message {
    margin-bottom: 16px;
    display: flex;

    .message-content {
      width: 100%;
      display: flex;
    }

    &.user {
      justify-content: flex-end;

      .message-content {
        justify-content: flex-end;
      }

      .user-content {
        display: inline-block;
        background: #1890ff;
        color: #fff;
        padding: 10px 14px;
        border-radius: 12px 12px 0 12px;
        max-width: 85%;
        min-width: 32px;
        word-break: normal;
        overflow-wrap: break-word;
        white-space: pre-wrap;
        box-shadow: 0 2px 8px rgba(24, 144, 255, 0.2);

        .user-images {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
          margin-bottom: 8px;

          .uploaded-image {
            max-width: 120px;
            max-height: 120px;
            border-radius: 8px;
            object-fit: cover;
          }
        }

        .user-text {
          display: inline;
          line-height: 1.5;
          word-break: normal;
          overflow-wrap: break-word;
          white-space: pre-wrap;
        }
      }
    }

    &.assistant {
      justify-content: flex-start;

      .message-content {
        justify-content: flex-start;
      }

      .assistant-content {
        display: inline-block;
        background: #f5f5f5;
        color: #333;
        padding: 12px 16px;
        border-radius: 12px 12px 12px 0;
        max-width: 85%;
        min-width: 60px;
        overflow-wrap: break-word;
        word-break: normal;

        .answer-text {
          line-height: 1.6;

          :deep(code) {
            background: #e8e8e8;
            padding: 2px 6px;
            border-radius: 4px;
            font-family: 'Courier New', monospace;
            font-size: 0.9em;
          }

          :deep(pre) {
            background: #f0f0f0;
            padding: 12px;
            border-radius: 8px;
            overflow-x: auto;
            margin: 8px 0;

            code {
              background: none;
              padding: 0;
            }
          }

          :deep(strong) {
            font-weight: 600;
          }
        }

        .streaming-cursor {
          animation: blink 1s infinite;
          color: #1890ff;
        }

        .loading-text {
          margin-left: 8px;
          color: #999;
        }
      }

      &.streaming .assistant-content {
        background: #e6f7ff;
      }
    }

    &.system {
      justify-content: center;

      .system-content {
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 6px 12px;
        background: #fff7e6;
        border: 1px solid #ffd591;
        border-radius: 16px;
        font-size: 12px;
        color: #d46b08;
      }
    }
  }
}

@keyframes blink {
  0%, 50% { opacity: 1; }
  51%, 100% { opacity: 0; }
}

.resize-handle {
  height: 8px;
  background: transparent;
  cursor: row-resize;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.2s;

  &:hover {
    background: var(--border-color, #e8e8e8);
  }

  .resize-indicator {
    width: 40px;
    height: 3px;
    background: var(--border-color, #d9d9d9);
    border-radius: 2px;
    transition: background 0.2s;
  }

  &:hover .resize-indicator {
    background: #1890ff;
  }
}

.chat-input {
  padding: 12px 16px;
  border-top: 1px solid var(--border-color, #e8e8e8);
  background: var(--bg-secondary, #fafafa);
  display: flex;
  flex-direction: column;
  overflow: hidden;

  .context-hint {
    margin-bottom: 8px;
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .image-preview {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-bottom: 8px;
    padding: 8px;
    background: #f0f0f0;
    border-radius: 8px;

    .preview-item {
      position: relative;
      width: 80px;
      height: 80px;

      img {
        width: 100%;
        height: 100%;
        object-fit: cover;
        border-radius: 6px;
      }

      .remove-btn {
        position: absolute;
        top: -6px;
        right: -6px;
        font-size: 16px;
        color: #ff4d4f;
        background: #fff;
        border-radius: 50%;
        cursor: pointer;

        &:hover {
          color: #ff7875;
        }
      }
    }
  }

  .input-wrapper {
    position: relative;
    display: flex;
    flex-direction: column;
    flex: 1;
    min-height: 0;

    :deep(.ant-input) {
      flex: 1;
      border-radius: 12px;
      resize: none;
      background: var(--bg-secondary, #fff);
      color: var(--text-primary, rgba(0, 0, 0, 0.88));
      border-color: var(--border-color, #d9d9d9);
      padding: 12px 12px 48px 12px;
      font-size: 14px;
      line-height: 1.6;
      overflow-y: auto;

      &::placeholder {
        color: var(--text-secondary, rgba(0, 0, 0, 0.45));
      }

      &:focus {
        border-color: #1890ff;
        box-shadow: 0 0 0 2px rgba(24, 144, 255, 0.2);
      }
    }
  }

  .input-actions {
    position: absolute;
    bottom: 8px;
    left: 8px;
    right: 8px;
    display: flex;
    align-items: center;
    gap: 8px;
    pointer-events: none;

    .left-actions,
    .center-actions,
    .right-actions {
      pointer-events: auto;
    }

    .left-actions {
      display: flex;
      gap: 8px;
      flex-shrink: 0;
    }

    .center-actions {
      flex: 1;
      min-width: 0;
      display: flex;
      justify-content: flex-end;

      .model-select {
        width: 100%;
        max-width: 180px;

        :deep(.ant-select-selector) {
          font-size: 12px;
          border-radius: 6px;
          background: var(--bg-secondary, rgba(255, 255, 255, 0.8));
          color: var(--text-primary, rgba(0, 0, 0, 0.88));
          border-color: var(--border-color, #d9d9d9);
        }

        :deep(.ant-select-selection-item) {
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
          color: var(--text-primary, rgba(0, 0, 0, 0.88));
        }

        :deep(.ant-select-arrow) {
          color: var(--text-secondary, rgba(0, 0, 0, 0.45));
        }
      }
    }

    .right-actions {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-shrink: 0;

      .icon-btn {
        width: 24px;
        height: 24px;
        padding: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        border-radius: 6px;

        .anticon {
          font-size: 14px;
        }
      }
    }
  }
}
</style>
