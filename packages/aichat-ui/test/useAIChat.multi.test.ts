import { test } from 'node:test'
import assert from 'node:assert/strict'
import { ref } from 'vue'

import type { QueryRequest, QueryResponse } from '../src/types/chat'

/**
 * 多库勾选载荷断言（阶段三 Task E1）：
 * useAIChat options.libraryIds 传 ref<string[]> 时，QueryRequest 携带 library_ids，
 * 且 library_id 兼容=首项；未传 libraryIds 时 body 不含 library_ids（旧宿主逐位不变）。
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

test('libraryIds 多选载荷：queryRequest 带 library_ids 且 library_id=首项', async () => {
  const { calls, query } = makeQuery()
  const chat = useAIChat({
    scene: 'docs',
    sessionId: 'multi-1',
    libraryId: 'libA',
    libraryIds: ref(['libA', 'libB']),
    query,
  })

  await chat.sendMessage('跨库提问')
  assert.equal(calls.length, 1)
  assert.deepEqual(calls[0].library_ids, ['libA', 'libB'])
  assert.equal(calls[0].library_id, 'libA')
})

test('libraryIds 是响应式 ref：改集合后下一问用新集合', async () => {
  const { calls, query } = makeQuery()
  const libraryIds = ref(['libA'])
  const chat = useAIChat({
    scene: 'docs',
    sessionId: 'multi-2',
    libraryId: 'libA',
    libraryIds,
    query,
  })

  await chat.sendMessage('第一问')
  libraryIds.value = ['libA', 'libB', 'libC']
  await chat.sendMessage('第二问')

  assert.equal(calls.length, 2)
  assert.deepEqual(calls[0].library_ids, ['libA'])
  assert.deepEqual(calls[1].library_ids, ['libA', 'libB', 'libC'])
})

test('未传 libraryIds（旧宿主）：queryRequest 不含 library_ids 键', async () => {
  const { calls, query } = makeQuery()
  const chat = useAIChat({
    scene: 'docs',
    sessionId: 'multi-3',
    libraryId: 'libA',
    query,
  })

  await chat.sendMessage('单库提问')
  assert.equal(calls.length, 1)
  // 计划实现为显式 `library_ids: undefined`，JSON.stringify 时键被剥离（E3 用例验证 body）
  assert.equal(calls[0].library_ids, undefined)
  assert.equal(calls[0].library_id, 'libA')
})

test('assistant 消息 citation 保留 library_id（B1：非首库溯源面板定位）', async () => {
  const query = async (payload: QueryRequest): Promise<QueryResponse> => ({
    query_id: 'q-cit',
    intent: {
      intent_level: 'L1',
      intent_type: 'content_qa',
      parameters: {},
      required_capabilities: ['retrieval'],
      matched_sop: null,
      service_mode: 'semantic_retrieval',
      reason: null,
    },
    answer: '见 [K1] 规定。',
    citations: [{
      target_id: 't1',
      doc_id: 'dB',
      doc_title: 'B规范.pdf',
      marker: 'K1',
      page_idx: 0,
      section_path: '3.1',
      snippet: 'x',
      score: 0.9,
      library_id: 'libB',
    }],
  })
  const chat = useAIChat({
    scene: 'docs',
    sessionId: 'multi-5',
    libraryId: 'libA',
    libraryIds: ref(['libA', 'libB']),
    query,
  })

  await chat.sendMessage('B 库规范怎么说')
  const assistant = chat.messages.value.find(m => m.role === 'assistant')
  assert.equal(assistant?.citations?.length, 1)
  assert.equal(assistant?.citations?.[0]?.marker, 'K1')
  assert.equal(assistant?.citations?.[0]?.library_id, 'libB')
})

test('libraryIds 空数组按未提供处理：不含 library_ids 键', async () => {
  const { calls, query } = makeQuery()
  const chat = useAIChat({
    scene: 'docs',
    sessionId: 'multi-4',
    libraryId: 'libA',
    libraryIds: ref<string[]>([]),
    query,
  })

  await chat.sendMessage('空集合回退')
  assert.equal(calls.length, 1)
  assert.equal(calls[0].library_ids, undefined)
})
