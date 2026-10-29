import { test } from 'node:test'
import assert from 'node:assert/strict'

import type { QueryRequest, QueryResponse, ThinkingTraceStep } from '../src/types/chat'

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
  // 发给后端的是剥掉 scene 前缀的裸 id（历史落库/PUT 与宿主 record.id 同键），池 key 仅进程内用
  assert.equal(calls[0].session_id, 'tab-1')
  assert.equal(calls[1].session_id, newKey.slice('docs:'.length))
})

test('发送消息不会把会话写入 localStorage（不做历史记录）', async () => {
  const { query } = makeQuery()
  const chat = useAIChat({ scene: 'docs', sessionId: 'tab-2', query })

  await chat.sendMessage('你好')
  chat.startNewChat()

  const poolKeys = [...storage.keys()].filter((key) => key.includes('ai-chat-pool'))
  assert.deepEqual(poolKeys, [])
})

test('loadMessages 灌入历史消息并写回会话池', async () => {
  const chat = useAIChat({ scene: 'docs', sessionId: 'load-msgs' })
  const history: Parameters<typeof chat.loadMessages>[0] = [
    { id: 'u1', role: 'user', content: '历史问题', timestamp: 1 },
    { id: 'a1', role: 'assistant', content: '历史回答', timestamp: 2 }
  ]
  chat.loadMessages(history)
  assert.equal(chat.messages.value.length, 2)
  assert.equal(getSessionSnapshot('docs:load-msgs')?.messages.length, 2)
})

test('@文档 提及把文档 id 合并进 doc_ids（document 类型才进，块级引用不进）', async () => {
  const { calls, query } = makeQuery()
  const chat = useAIChat({ scene: 'docs', sessionId: 'doc-mention', query })

  await chat.sendMessage({
    content: '《规范A》里怎么规定',
    citations: [
      {
        id: 'cit_doc1',
        label: '《规范A》',
        triggerText: '规范A',
        range: { start: 0, end: 5 },
        reference: { targetId: 'doc-a', targetType: 'document', docId: 'doc-a', docTitle: '规范A.pdf' },
        status: 'active'
      },
      {
        id: 'cit_blk1',
        label: '第3条',
        triggerText: '第3条',
        range: { start: 6, end: 9 },
        reference: { targetId: 'blk-1', targetType: 'content', docId: 'doc-b', docTitle: '规范B.pdf' },
        status: 'active'
      }
    ]
  })

  assert.equal(calls.length, 1)
  assert.deepEqual(calls[0].doc_ids, ['doc-a'])
  // 内联引用原样透传给后端
  assert.equal(calls[0].inline_citations?.length, 2)
})

/** 思考过程用例的响应骨架：只在差异字段上覆盖 */
function makeResponse(overrides: Partial<QueryResponse> = {}): QueryResponse {
  return {
    query_id: 'q-thinking',
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
    ...overrides,
  }
}

test('宿主只在流式期上报思考步骤（done 帧无 thinking_trace）时，落定消息仍保留思考过程', async () => {
  const steps: ThinkingTraceStep[] = [
    { kind: 'note', detail: '意图判断', atMs: 1_000 },
    { kind: 'note', detail: '处理链路：检索规范库', atMs: 2_000 },
    { kind: 'note', detail: '生成回答', atMs: 3_000 },
  ]
  // 与 DredgeAI 专业问答 transport 同型：status 帧经 onThinking 增量上报，
  // done 帧只回 answer/citations，QueryResponse 不带 thinking_trace
  const query = async (
    _payload: QueryRequest,
    options?: { onThinking?: (live: ThinkingTraceStep[]) => void }
  ): Promise<QueryResponse> => {
    options?.onThinking?.([steps[0]])
    options?.onThinking?.([...steps])
    return makeResponse()
  }

  const chat = useAIChat({ scene: 'docs', sessionId: 'thinking-live', query })
  await chat.sendMessage('这条怎么规定的')

  const assistant = chat.messages.value.find(message => message.role === 'assistant')
  assert.ok(assistant)
  assert.deepEqual(assistant.thinking_trace, steps)
})

test('transport 自带 thinking_trace 时以它为准，流式步骤只作兜底', async () => {
  const finalTrace: ThinkingTraceStep[] = [
    { kind: 'note', detail: '权威轨迹', atMs: 4_000, wallStartMs: 1_000 }
  ]
  const query = async (
    _payload: QueryRequest,
    options?: { onThinking?: (live: ThinkingTraceStep[]) => void }
  ): Promise<QueryResponse> => {
    options?.onThinking?.([{ kind: 'note', detail: '流式轨迹（未含耗时锚点）', atMs: 2_000 }])
    return makeResponse({ thinking_trace: finalTrace })
  }

  const chat = useAIChat({ scene: 'docs', sessionId: 'thinking-authoritative', query })
  await chat.sendMessage('这条怎么规定的')

  const assistant = chat.messages.value.find(message => message.role === 'assistant')
  assert.deepEqual(assistant?.thinking_trace, finalTrace)
})

test('整轮没有思考步骤时消息不落空数组（thinking_trace 缺省）', async () => {
  const { query } = makeQuery()
  const chat = useAIChat({ scene: 'docs', sessionId: 'thinking-empty', query })

  await chat.sendMessage('你好')

  const assistant = chat.messages.value.find(message => message.role === 'assistant')
  assert.equal(assistant?.thinking_trace, undefined)
})
