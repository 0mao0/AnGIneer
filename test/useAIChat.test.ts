import { test } from 'node:test'
import assert from 'node:assert/strict'

import type { QueryRequest, QueryResponse } from '../src/types/chat'

/**
 * 会话池持久化断言用的 localStorage mock：
 * 必须在动态 import useAIChat 之前挂到 globalThis，
 * 否则模块加载时读不到。
 */
const storage = new Map<string, string>()
const localStorageMock = {
  getItem: (key: string) => storage.get(key) ?? null,
  setItem: (key: string, value: string) => { storage.set(key, value) },
  removeItem: (key: string) => { storage.delete(key) },
}
;(globalThis as any).localStorage = localStorageMock

const {
  useAIChat,
  getSessionSnapshot,
} = await import('../src/composables/useAIChat.ts')

function makeQuery() {
  const calls: QueryRequest[] = []
  const query = async (payload: QueryRequest): Promise<QueryResponse> => {
    calls.push(payload)
    return {
      query_id: `q-${calls.length}`,
      intent: {
        intent_level: 'L1',
        intent_type: 'content_qa',
        parameters: {},
        required_capabilities: ['retrieval'],
        matched_sop: null,
        service_mode: 'semantic_retrieval',
        reason: null,
      },
      answer: '测试回答',
      citations: [],
    }
  }
  return { calls, query }
}

test('startNewChat 清空消息、切换会话 key，并让后续请求使用新会话', async () => {
  const { calls, query } = makeQuery()
  const chat = useAIChat({ scene: 'docs', sessionId: 'tab-1', query })
  const oldKey = chat.currentSessionKey.value

  await chat.sendMessage('第一问')
  assert.equal(chat.messages.value.length, 2)
  assert.equal(chat.currentSessionKey.value, oldKey)

  chat.startNewChat()

  const newKey = chat.currentSessionKey.value
  assert.notEqual(newKey, oldKey)
  assert.equal(chat.messages.value.length, 0)
  assert.equal(getSessionSnapshot(oldKey), undefined)

  await chat.sendMessage('第二问')
  assert.equal(calls.length, 2)
  assert.equal(calls[1].session_id, newKey)
})

test('发送消息不会把会话写入 localStorage（不做历史记录）', async () => {
  const { query } = makeQuery()
  const chat = useAIChat({ scene: 'docs', sessionId: 'tab-2', query })

  await chat.sendMessage('你好')
  chat.startNewChat()

  const poolKeys = [...storage.keys()].filter((key) => key.includes('ai-chat-pool'))
  assert.deepEqual(poolKeys, [])
})
