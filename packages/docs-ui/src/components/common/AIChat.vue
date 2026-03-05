<template>
  <div class="ai-chat-component">
    <!-- 头部 -->
    <div v-if="title" class="ai-chat-header">
      <span v-if="icon" class="header-icon">
        <component :is="icon" />
      </span>
      <span class="header-title">{{ title }}</span>
      <div class="header-actions">
        <a-tag v-if="showContextInfo" class="context-info" size="small">
          {{ contextRounds }}轮 / {{ contextTokens }}tokens
        </a-tag>
        <a-button type="text" size="small" @click="clearMessages">
          <template #icon><ClearOutlined /></template>
          清空
        </a-button>
      </div>
    </div>

    <!-- 消息列表 -->
    <div class="chat-messages" ref="messagesRef">
      <div
        v-for="(msg, index) in displayMessages"
        :key="msg.id || index"
        :class="['message', msg.role]"
      >
        <div class="message-content">
          <!-- 用户消息 -->
          <template v-if="msg.role === 'user'">
            <div class="user-content">
              <!-- 多模态：显示图片 -->
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

          <!-- 助手消息 -->
          <template v-else-if="msg.role === 'assistant'">
            <div class="assistant-content">
              <div class="answer-text" v-html="renderMarkdown(msg.content)" />
            </div>
          </template>

          <!-- 系统消息（不显示或特殊显示） -->
          <template v-else-if="msg.role === 'system' && showSystemMessages">
            <div class="system-content">
              <InfoCircleOutlined />
              <span>系统：{{ msg.content }}</span>
            </div>
          </template>
        </div>
      </div>

      <!-- 流式生成中的内容 -->
      <div v-if="loading && currentStreamContent" class="message assistant streaming">
        <div class="message-content">
          <div class="assistant-content">
            <div class="answer-text" v-html="renderMarkdown(currentStreamContent)" />
            <span class="streaming-cursor">▌</span>
          </div>
        </div>
      </div>

      <!-- 加载状态 -->
      <div v-if="loading && !currentStreamContent" class="message assistant loading">
        <div class="message-content">
          <div class="assistant-content">
            <a-spin size="small" />
            <span class="loading-text">思考中...</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 可拖动边界线 -->
    <div
      class="resize-handle"
      @mousedown="startResize"
      title="拖动调整输入区域高度"
    >
      <div class="resize-indicator"></div>
    </div>

    <!-- 输入区域 -->
    <div class="chat-input" ref="chatInputRef" :style="{ height: inputHeight + 'px' }">
      <!-- 上下文引用提示 -->
      <div class="context-hint" v-if="contextItems.length">
        <a-tag
          v-for="item in contextItems"
          :key="item.id"
          closable
          @close="removeContext(item.id)"
        >
          {{ item.title }}
        </a-tag>
      </div>

      <!-- 图片预览（多模态预留） -->
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

      <!-- 输入框容器 -->
      <div class="input-wrapper">
        <a-textarea
          v-model:value="inputText"
          :placeholder="placeholder"
          :disabled="loading"
          :rows="3"
          @keydown.enter.prevent="handleEnter"
        />

        <!-- 操作栏（嵌入在输入框内） -->
        <div class="input-actions">
          <!-- 左侧：上传按钮（固定） -->
          <div class="left-actions">
            <a-button
              type="text"
              size="small"
              :disabled="loading"
              @click="handleImageUpload"
              title="上传图片（开发中）"
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

          <!-- 中间：模型选择（自适应宽度） -->
          <div class="center-actions">
            <a-select
              v-model:value="selectedModel"
              class="model-select"
              size="small"
              :loading="loadingModels"
              :disabled="loading"
              :title="selectedModel"
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

          <!-- 右侧：发送按钮（固定） -->
          <div class="right-actions">
            <a-button
              v-if="loading"
              type="primary"
              danger
              size="small"
              class="icon-btn"
              @click="stopGeneration"
              title="停止生成"
            >
              <PauseCircleOutlined />
            </a-button>
            <a-button
              v-else
              type="primary"
              size="small"
              class="icon-btn"
              :disabled="!inputText.trim() && !pendingImages.length"
              @click="handleSend"
              title="发送消息 (Enter)"
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
import { ref, computed, nextTick, onMounted, watch } from 'vue'
import {
  ClearOutlined,
  SendOutlined,
  PauseCircleOutlined,
  PictureOutlined,
  CloseCircleOutlined,
  InfoCircleOutlined
} from '@ant-design/icons-vue'
import { useAIChat } from '../../composables/useAIChat'

// 模型选项类型
interface ModelOption {
  value: string
  label: string
}

// 上下文项类型
interface ContextItem {
  id: string
  title: string
}

// 组件属性
interface Props {
  // 默认模型
  defaultModel?: string
  // 占位提示
  placeholder?: string
  // 上下文引用项
  contextItems?: ContextItem[]
  // 标题
  title?: string
  // 图标
  icon?: any
  // 系统提示词
  systemPrompt?: string
  // 是否显示上下文信息
  showContextInfo?: boolean
  // 是否显示系统消息
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

// 事件定义
const emit = defineEmits<{
  send: [message: string, model: string]
  ready: []
  removeContext: [id: string]
  error: [error: Error]
}>()

// 使用 AI Chat composable
const {
  messages,
  inputText,
  loading,
  currentStreamContent,
  sendMessage,
  stopGeneration,
  clearMessages,
  getContextTokens,
  getContextRounds
} = useAIChat({
  defaultModel: props.defaultModel,
  systemPrompt: props.systemPrompt
})

// 本地状态
const messagesRef = ref<HTMLElement | null>(null)
const chatInputRef = ref<HTMLElement | null>(null)
const loadingModels = ref(false)
const selectedModel = ref(props.defaultModel)
const models = ref<ModelOption[]>([])
const pendingImages = ref<string[]>([])
const imageInputRef = ref<HTMLInputElement | null>(null)

// 输入区域高度调整状态
const inputHeight = ref(150) // 默认高度 150px
const isResizing = ref(false)
const startY = ref(0)
const startHeight = ref(0)
const minInputHeight = 100
const maxInputHeightRatio = 0.5 // 最大占父容器高度的 50%

// 计算属性：显示的消息（过滤系统消息）
const displayMessages = computed(() => {
  return messages.value.filter(m => m.role !== 'system')
})

// 计算属性：上下文信息
const contextTokens = computed(() => getContextTokens())
const contextRounds = computed(() => getContextRounds())

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

      // 如果没有指定默认模型，优先使用 Qwen3-4B
      if (!selectedModel.value && models.value.length > 0) {
        const qwenModel = models.value.find(m =>
          m.value.includes('Qwen3-4B') || m.value.includes('qwen3-4b')
        )
        selectedModel.value = qwenModel?.value || models.value[0].value
      }
    } else {
      // API 失败时使用默认模型
      models.value = [{ value: 'default', label: '默认模型' }]
      selectedModel.value = 'default'
    }
  } catch (error) {
    console.error('获取模型列表失败:', error)
    models.value = [{ value: 'default', label: '默认模型' }]
    selectedModel.value = 'default'
  } finally {
    loadingModels.value = false
  }
}

/**
 * 渲染 Markdown 内容
 */
const renderMarkdown = (content: string): string => {
  if (!content) return ''
  return content
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>')
    .replace(/\n/g, '<br/>')
}

/**
 * 滚动到底部
 */
const scrollToBottom = () => {
  nextTick(() => {
    if (messagesRef.value) {
      messagesRef.value.scrollTop = messagesRef.value.scrollHeight
    }
  })
}

/**
 * 处理 Enter 键事件 - Shift+Enter 换行，Enter 发送
 */
const handleEnter = (e: KeyboardEvent) => {
  if (e.shiftKey) {
    // Shift+Enter 换行，不阻止默认行为
    return
  }
  // Enter 发送消息
  e.preventDefault()
  handleSend()
}

/**
 * 开始拖动调整输入区域高度
 */
const startResize = (e: MouseEvent) => {
  isResizing.value = true
  startY.value = e.clientY
  startHeight.value = inputHeight.value

  document.addEventListener('mousemove', handleResize)
  document.addEventListener('mouseup', stopResize)
}

/**
 * 处理拖动调整
 */
const handleResize = (e: MouseEvent) => {
  if (!isResizing.value) return

  const deltaY = startY.value - e.clientY
  const newHeight = startHeight.value + deltaY

  // 计算最大高度（父容器高度的 50%）
  const parentHeight = chatInputRef.value?.parentElement?.clientHeight || window.innerHeight
  const maxHeight = parentHeight * maxInputHeightRatio

  // 限制高度在最小值和最大值之间
  inputHeight.value = Math.max(minInputHeight, Math.min(newHeight, maxHeight))
}

/**
 * 停止拖动调整
 */
const stopResize = () => {
  isResizing.value = false
  document.removeEventListener('mousemove', handleResize)
  document.removeEventListener('mouseup', stopResize)
}

/**
 * 处理发送消息
 */
const handleSend = async () => {
  const content = inputText.value.trim()
  if (!content && !pendingImages.value.length) return

  // 构建消息内容（包含图片）
  let messageContent = content

  emit('send', messageContent, selectedModel.value)

  try {
    await sendMessage(messageContent, selectedModel.value, () => {
      scrollToBottom()
    })

    // 清空待发送图片
    pendingImages.value = []
  } catch (error) {
    emit('error', error instanceof Error ? error : new Error(String(error)))
  }

  scrollToBottom()
}

/**
 * 移除上下文引用项
 */
const removeContext = (id: string) => {
  emit('removeContext', id)
}

/**
 * 处理图片上传点击
 */
const handleImageUpload = () => {
  imageInputRef.value?.click()
}

/**
 * 图片选择处理（多模态预留）
 */
const onImageSelected = (event: Event) => {
  const target = event.target as HTMLInputElement
  const files = target.files
  if (!files) return

  // 读取图片为 base64（预留）
  Array.from(files).forEach(file => {
    const reader = new FileReader()
    reader.onload = (e) => {
      if (e.target?.result) {
        pendingImages.value.push(e.target.result as string)
      }
    }
    reader.readAsDataURL(file)
  })

  // 清空 input 以便重复选择同一文件
  target.value = ''
}

/**
 * 移除待发送图片
 */
const removeImage = (index: number) => {
  pendingImages.value.splice(index, 1)
}

// 监听消息变化，自动滚动
watch(() => messages.value.length, scrollToBottom)
watch(currentStreamContent, scrollToBottom)

// 组件挂载时获取模型列表
onMounted(() => {
  fetchModels()
  emit('ready')
})

// 暴露方法给父组件
defineExpose({
  messages,
  clearMessages,
  sendMessage: handleSend
})
</script>

<style lang="less" scoped>
.ai-chat-component {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-primary, #fff);
}

.ai-chat-header {
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

    &.user {
      justify-content: flex-end;

      .user-content {
        display: inline-block;
        background: #1890ff;
        color: #fff;
        padding: 10px 14px;
        border-radius: 12px 12px 0 12px;
        max-width: 95%;
        word-break: break-word;
        white-space: pre-wrap;

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
          line-height: 1.5;
          white-space: pre-wrap;
          word-break: break-word;
        }
      }
    }

    &.assistant {
      justify-content: flex-start;

      .assistant-content {
        display: inline-block;
        background: #f5f5f5;
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

// 可拖动边界线
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

  // 输入框容器 - 占满输入区域高度
  .input-wrapper {
    position: relative;
    display: flex;
    flex-direction: column;
    flex: 1;
    min-height: 0;

    :deep(.ant-input) {
      flex: 1;
      border-radius: 12px;
      resize: none; // 禁用 textarea 自带的 resize，使用外部拖动条
      background: var(--bg-secondary, #fff);
      color: var(--text-primary, rgba(0, 0, 0, 0.88));
      border-color: var(--border-color, #d9d9d9);
      padding: 12px 12px 48px 12px; // 底部留出按钮空间
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

  // 操作栏 - 绝对定位在输入框内部底部
  .input-actions {
    position: absolute;
    bottom: 8px;
    left: 8px;
    right: 8px;
    display: flex;
    align-items: center;
    gap: 8px;
    pointer-events: none; // 允许点击穿透到 textarea

    .left-actions,
    .center-actions,
    .right-actions {
      pointer-events: auto; // 恢复按钮的点击
    }

    // 左侧：上传按钮（固定宽度）
    .left-actions {
      display: flex;
      gap: 8px;
      flex-shrink: 0;
    }

    // 中间：模型选择（自适应宽度）
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

    // 右侧：发送按钮（固定宽度）
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
