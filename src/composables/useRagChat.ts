/**
 * AI 对话 Composable
 * 提供 AI 对话的状态管理和消息发送功能
 */
import { ref, nextTick } from 'vue'

// 聊天消息类型
export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  sources?: { title: string; id: string }[]
}

// RAG 查询参数
export interface RagQueryParams {
  question: string
  libraryId?: string
  k?: number
  useLlm?: boolean
}

// RAG 查询结果
export interface RagQueryResult {
  question: string
  answer: string
  num_sources: number
  sources: { title: string; id: string }[]
}

export function useRagChat(
  queryFn: (params: RagQueryParams) => Promise<RagQueryResult>
) {
  // 状态
  const messages = ref<ChatMessage[]>([
    {
      role: 'assistant',
      content: '您好！我是基于知识库的智能问答助手。您可以向我提问，我会从知识库中检索相关内容进行回答。'
    }
  ])
  const inputText = ref('')
  const loading = ref(false)
  const messagesRef = ref<HTMLElement | null>(null)

  // 发送消息
  const sendMessage = async () => {
    const text = inputText.value.trim()
    if (!text || loading.value) return

    // 添加用户消息
    messages.value.push({
      role: 'user',
      content: text
    })

    inputText.value = ''
    loading.value = true

    // 滚动到底部
    await nextTick()
    scrollToBottom()

    try {
      // 调用 RAG 查询
      const result = await queryFn({
        question: text,
        libraryId: 'default',
        k: 4,
        useLlm: true
      })

      // 添加助手回复
      messages.value.push({
        role: 'assistant',
        content: result.answer,
        sources: result.sources
      })
    } catch (error) {
      messages.value.push({
        role: 'assistant',
        content: '抱歉，查询失败，请稍后重试。'
      })
    } finally {
      loading.value = false
      await nextTick()
      scrollToBottom()
    }
  }

  // 滚动到底部
  const scrollToBottom = () => {
    if (messagesRef.value) {
      messagesRef.value.scrollTop = messagesRef.value.scrollHeight
    }
  }

  // 清空对话
  const clearMessages = () => {
    messages.value = [
      {
        role: 'assistant',
        content: '您好！我是基于知识库的智能问答助手。您可以向我提问，我会从知识库中检索相关内容进行回答。'
      }
    ]
  }

  return {
    // 状态
    messages,
    inputText,
    loading,
    messagesRef,
    // 方法
    sendMessage,
    scrollToBottom,
    clearMessages
  }
}
