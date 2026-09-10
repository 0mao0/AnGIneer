import { test } from 'node:test'
import assert from 'node:assert/strict'

import type { QueryRequest, QueryResponse } from '../src/types/chat'

/** 与 useAIChat.test.ts 同款：模块加载时读 localStorage，必须提前挂到 globalThis */
const storage = new Map<string, string>()
;(globalThis as any).localStorage = {
  getItem: (key: string) => storage.get(key) ?? null,
  setItem: (key: string, value: string) => { storage.set(key, value) },
  removeItem: (key: string) => { storage.delete(key) },
}

const { useAIChat, QUEUE_LIMIT } = await import('../src/composables/useAIChat.ts')

const tick = () => new Promise((resolve) => setTimeout(resolve, 0))

function makeCannedResponse(index: number): QueryResponse {
  return {
    query_id: `q-${index}`,
    intent: {
      intent_level: 'L1',
      intent_type: 'content_qa',
      parameters: {},
      required_capabilities: ['retrieval'],
      matched_sop: null,
      service_mode: 'semantic_retrieval',
      reason: null,
    },
    answer: `回答${index}`,
    citations: [],
  }
}

/** 可控 query：请求挂起直到测试显式 resolve；signal abort 时按 AbortError 拒绝 */
function makeControllableQuery(delta = '') {
  const calls: QueryRequest[] = []
  const pending: Array<{ resolve: () => void }> = []
  const query = async (
    payload: QueryRequest,
    options?: any
  ): Promise<QueryResponse> => {
    calls.push(payload)
    const index = calls.length
    if (delta) options?.onDelta?.(`${delta}${index}`)
    await new Promise<void>((resolve, reject) => {
      pending.push({ resolve })
      options?.signal?.addEventListener('abort', () => {
        const error = new Error('aborted')
        error.name = 'AbortError'
        reject(error)
      })
    })
    return makeCannedResponse(index)
  }
  return { calls, pending, query }
}

test('生成期间发送进入队列：不触发新请求、不进消息列表', async () => {
  const { calls, pending, query } = makeControllableQuery()
  const chat = useAIChat({ scene: 'docs', sessionId: 'queue-1', query })

  void chat.sendMessage('第一问')
  await tick()
  assert.equal(calls.length, 1)

  await chat.sendMessage('第二问')
  assert.equal(calls.length, 1, '生成中发送不应发起新请求')
  assert.equal(chat.queuedMessages.value.length, 1)
  assert.equal(chat.messages.value.length, 1, '入队消息不进消息列表')

  pending[0].resolve()
  await tick()
  await tick()
  assert.equal(calls.length, 2, '上一轮结束后自动发出队列中的下一条')
  assert.equal(calls[1].query, '第二问')
  assert.equal(chat.queuedMessages.value.length, 0)

  pending[1]?.resolve()
  await tick()
})

test('removeQueued 删除指定条目', async () => {
  const { pending, query } = makeControllableQuery()
  const chat = useAIChat({ scene: 'docs', sessionId: 'queue-2', query })

  void chat.sendMessage('第一问')
  await tick()
  await chat.sendMessage('第二问')
  await chat.sendMessage('第三问')
  assert.equal(chat.queuedMessages.value.length, 2)

  chat.removeQueued(chat.queuedMessages.value[0].id)
  assert.equal(chat.queuedMessages.value.length, 1)
  assert.equal(chat.queuedMessages.value[0].content, '第三问')

  pending[0].resolve()
  await tick()
  await tick()
  pending[1]?.resolve()
  await tick()
})

test('promoteQueued 提到队首并打断当前 run', async () => {
  const { calls, pending, query } = makeControllableQuery()
  const chat = useAIChat({ scene: 'docs', sessionId: 'queue-3', query })

  void chat.sendMessage('A')
  await tick()
  await chat.sendMessage('B')
  await chat.sendMessage('C')
  const targetId = chat.queuedMessages.value[1].id // C

  chat.promoteQueued(targetId)
  await tick()
  await tick()

  assert.equal(calls.length, 2, '打断后立刻发出插队的那条')
  assert.equal(calls[1].query, 'C')
  assert.equal(chat.queuedMessages.value.length, 1)
  assert.equal(chat.queuedMessages.value[0].content, 'B', '其余条目保持原顺序')

  pending[1]?.resolve()
  await tick()
})

test('队列超上限后拒绝入队', async () => {
  const { pending, query } = makeControllableQuery()
  const chat = useAIChat({ scene: 'docs', sessionId: 'queue-4', query })

  void chat.sendMessage('占位')
  await tick()
  for (let i = 0; i < QUEUE_LIMIT; i += 1) {
    await chat.sendMessage(`排队${i}`)
  }
  assert.equal(chat.queuedMessages.value.length, QUEUE_LIMIT)

  await chat.sendMessage('第 N+1 条')
  assert.equal(chat.queuedMessages.value.length, QUEUE_LIMIT, '超限不再入队')

  pending[0].resolve()
  await tick()
  await tick()
})

test('停止后队列暂停：不自动发出，条目保留', async () => {
  const { calls, pending, query } = makeControllableQuery()
  const chat = useAIChat({ scene: 'docs', sessionId: 'queue-5', query })

  void chat.sendMessage('第一问')
  await tick()
  await chat.sendMessage('第二问')
  assert.equal(chat.queuedMessages.value.length, 1)

  chat.stopGeneration()
  await tick()
  await tick()

  assert.equal(calls.length, 1, '停止后不应自动发出队列')
  assert.equal(chat.queuedMessages.value.length, 1, '队列条目保留')

  pending[0]?.resolve()
  await tick()
})

test('startNewChat 清空队列', async () => {
  const { pending, query } = makeControllableQuery()
  const chat = useAIChat({ scene: 'docs', sessionId: 'queue-6', query })

  void chat.sendMessage('第一问')
  await tick()
  await chat.sendMessage('第二问')
  assert.equal(chat.queuedMessages.value.length, 1)

  chat.startNewChat()
  assert.equal(chat.queuedMessages.value.length, 0)

  pending[0]?.resolve()
  await tick()
})

test('插队截断的回答：保留为助手消息，但不留「已停止生成」失败标记', async () => {
  const { pending, query } = makeControllableQuery('部分回答')
  const chat = useAIChat({ scene: 'docs', sessionId: 'queue-7', query })

  void chat.sendMessage('A')
  await tick()
  await chat.sendMessage('B')

  chat.promoteQueued(chat.queuedMessages.value[0].id)
  await tick()
  await tick()

  const assistantMessages = chat.messages.value.filter(m => m.role === 'assistant')
  assert.equal(assistantMessages.length, 1, '被截断的回答保留为一条助手消息')
  assert.ok(assistantMessages[0].content.includes('部分回答'))
  assert.ok(
    !assistantMessages[0].content.includes('已停止生成'),
    '插队是用户主动接话，不该留下失败标记'
  )

  pending[1]?.resolve()
  await tick()
})

test('手动停止仍然保留「已停止生成」标记', async () => {
  const { pending, query } = makeControllableQuery('部分回答')
  const chat = useAIChat({ scene: 'docs', sessionId: 'queue-8', query })

  void chat.sendMessage('A')
  await tick()
  chat.stopGeneration()
  await tick()
  await tick()

  const assistantMessages = chat.messages.value.filter(m => m.role === 'assistant')
  assert.equal(assistantMessages.length, 1)
  assert.ok(assistantMessages[0].content.includes('已停止生成'))

  pending[0]?.resolve()
  await tick()
})
