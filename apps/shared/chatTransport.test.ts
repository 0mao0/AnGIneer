import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  applyAgentEventToThinking,
  buildThinkingTrace,
  cleanStreamText,
  defaultAIChatTransport,
  extractToolResultItems,
  filterCitationsByMarkers,
  mergeThinkingTrace,
  stripToolCallArtifacts,
} from './chatTransport.ts'
import type { ThinkingTraceItem, ThinkingTraceStep } from '@angineer/aichat-ui'

function sseResponse(events: Array<Record<string, any>>): Response {
  const body = new ReadableStream({
    start(controller) {
      for (const event of events) {
        controller.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`))
      }
      controller.enqueue(new TextEncoder().encode('data: [DONE]\n\n'))
      controller.close()
    },
  })
  return new Response(body, {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  })
}

test('去掉围栏包裹的工具调用块', () => {
  const text = stripToolCallArtifacts(
    '先检索\n```tool_calls\n[{"name": "knowledge_search", "arguments": {"query": "上航数联"}}]\n```'
  )
  assert.equal(text, '先检索')
})

test('去掉没有围栏的纯 JSON 工具调用数组', () => {
  const text = stripToolCallArtifacts(
    '思考过程后\n[{"name": "knowledge_search", "arguments": {"query": "上航数联"}}]'
  )
  assert.equal(text, '思考过程后')
})

test('把 run_end 消息构建为思考过程轨迹', () => {
  const steps = buildThinkingTrace([
    { role: 'user', content: '上航数联是什么' },
    {
      role: 'assistant',
      content: '```tool_calls\n[]\n```',
      tool_calls: [{ name: 'knowledge_search', arguments: { query: '上航数联' } }],
    },
    {
      role: 'tool',
      name: 'knowledge_search',
      content: '{"items": [1, 2, 3], "total": 3}',
    },
  ])
  assert.deepEqual(steps, [
    { kind: 'call', tool: 'knowledge_search', detail: '{"query":"上航数联"}', turn: 1 },
    {
      kind: 'result',
      tool: 'knowledge_search',
      detail: '检索到 3 条结果',
      turn: 1,
      isError: false,
      citations: [],
    },
  ])
})

test('预算截断和最终回答也会出现在轨迹里', () => {
  const steps = buildThinkingTrace(
    [{ role: 'assistant', content: '答案是 X' }],
    [{ detail: '轮次预算已用完（max_turns=2），进入无工具收尾回答' }]
  )
  assert.deepEqual(steps, [
    { kind: 'note', detail: '汇总证据并生成最终回答', turn: 1 },
    { kind: 'note', detail: '轮次预算已用完（max_turns=2），进入无工具收尾回答' },
  ])
})

test('重试后只给真正的最终回答打“汇总证据并生成最终回答”标签', () => {
  const steps = buildThinkingTrace([
    { role: 'user', content: '上航数联是什么' },
    { role: 'assistant', content: '上航数联是智慧工地数字底座平台' },
    { role: 'user', content: '请先调用检索工具获取证据后再回答' },
    {
      role: 'assistant',
      content: '```tool_calls\n[]\n```',
      tool_calls: [{ name: 'knowledge_search', arguments: { query: '上航数联' } }],
    },
    {
      role: 'tool',
      name: 'knowledge_search',
      content: '{"items": [], "total": 0}',
    },
    { role: 'assistant', content: '上航数联是智慧工地数字底座平台' },
  ])
  const labels = steps.filter(
    step => step.kind === 'note' && step.detail === '汇总证据并生成最终回答'
  )
  assert.equal(labels.length, 1)
  assert.equal(labels[0].turn, 3)
})

test('filterCitationsByMarkers 只保留答案中出现的标记', () => {
  const citations = [
    { marker: 'K1', doc_id: 'd1', doc_title: '船闸规范.pdf', page_idx: 0, section_path: '2.2 级别划分', snippet: 'x', score: 1, target_id: 't1' },
    { marker: 'T1', doc_id: 'd2', doc_title: '海港2', page_idx: 0, section_path: '6.4', snippet: 'x', score: 1, target_id: 't2' },
  ]
  const filtered = filterCitationsByMarkers(citations, '依据 [K1]，闸门有 4 个等级。')
  assert.equal(filtered.length, 1)
  assert.equal(filtered[0].marker, 'K1')
})

test('工具消息 items 带 cite 时进入思考轨迹 citations.marker', () => {
  const steps = buildThinkingTrace([
    { role: 'user', content: 'x' },
    {
      role: 'assistant',
      content: '```tool_calls\n[]\n```',
      tool_calls: [{ name: 'knowledge_search', arguments: { query: 'x' } }],
    },
    {
      role: 'tool',
      name: 'knowledge_search',
      content: JSON.stringify({
        total: 1,
        items: [{
          item_id: 'a',
          entity_type: 'content',
          doc_id: 'd1',
          title: 't',
          text: 'x',
          score: 0.9,
          metadata: { doc_title: '船闸规范.pdf', cite: 'K1' },
        }],
      }),
    },
  ])
  const result = steps.find(step => step.kind === 'result')
  assert.equal(result?.citations?.[0]?.marker, 'K1')
})

test('extractToolResultItems 带出 cite 标记', () => {
  const items = extractToolResultItems(JSON.stringify({
    items: [{
      item_id: 'a',
      entity_type: 'content',
      doc_id: 'd',
      title: 't',
      text: 'x',
      metadata: { cite: 'K2' },
    }],
  }))
  assert.equal(items?.[0]?.cite, 'K2')
})

test('run_end 消息里的完整检索条目进入思考轨迹', () => {
  const steps = buildThinkingTrace([
    {
      role: 'assistant',
      content: '',
      tool_calls: [{ name: 'knowledge_search', arguments: { query: '上航数联' } }],
    },
    {
      role: 'tool',
      name: 'knowledge_search',
      content: JSON.stringify({
        total: 2,
        items: [
          {
            item_id: 'a',
            entity_type: 'content',
            doc_id: 'd1',
            title: '推广产品',
            text: '第一条内容',
            score: 0.9,
            metadata: { doc_title: '推广产品.docx', section_path: '产品一：上航数联' },
          },
          {
            item_id: 'b',
            entity_type: 'content',
            doc_id: 'd2',
            title: 'probe',
            text: '第二条内容',
            score: 0.8,
            metadata: { doc_title: 'probe.pdf', section_path: '产品一：上航数联' },
          },
        ],
      }),
    },
  ])
  const result = steps.find(step => step.kind === 'result')
  assert.equal(result?.resultItems?.length, 2)
  assert.equal(result?.resultItems?.[0]?.doc_title, '推广产品.docx')
  assert.equal(result?.citations?.length, 2)
})

test('note 事件实时进入思考轨迹', () => {
  const steps = applyAgentEventToThinking(
    { type: 'note', turn: 1, payload: { detail: '输出被长度截断（finish_reason=length）' } },
    []
  )
  assert.equal(steps.length, 1)
  assert.equal(steps[0].kind, 'note')
  assert.equal(steps[0].detail, '输出被长度截断（finish_reason=length）')
})

test('mergeThinkingTrace 保留实时说明并用完整结果替换', () => {
  const item: ThinkingTraceItem = {
    item_id: 'a',
    entity_type: 'content',
    doc_id: 'd1',
    doc_title: '推广产品.docx',
    title: '推广产品',
    text: '第一条内容',
    score: 0.9,
    metadata: { section_path: '产品一：上航数联' },
  }
  const finalSteps: ThinkingTraceStep[] = [
    { kind: 'call', tool: 'knowledge_search', detail: '{"query":"x"}', turn: 1 },
    {
      kind: 'result',
      tool: 'knowledge_search',
      detail: '检索到 2 条结果',
      turn: 1,
      citations: [],
      resultItems: [item],
    },
    { kind: 'note', detail: '汇总证据并生成最终回答', turn: 1 },
  ]
  const liveSteps: ThinkingTraceStep[] = [
    { kind: 'turn', detail: '', turn: 1 },
    { kind: 'call', tool: 'knowledge_search', detail: '{"query":"x"}', turn: 1 },
    {
      kind: 'result',
      tool: 'knowledge_search',
      detail: '工具已返回结果（完整内容见最终轨迹）',
      durationMs: 6969,
      turn: 1,
    },
    { kind: 'note', detail: '输出被长度截断（finish_reason=length）' },
  ]

  const merged = mergeThinkingTrace(finalSteps, liveSteps)
  assert.equal(merged.length, 5)
  assert.equal(merged[0].kind, 'turn')
  const result = merged.find(step => step.kind === 'result')
  assert.equal(result?.detail, '检索到 2 条结果')
  assert.equal(result?.durationMs, 6969)
  assert.ok(merged.some(step => step.kind === 'note' && step.detail === '输出被长度截断（finish_reason=length）'))
  assert.ok(merged.some(step => step.kind === 'note' && step.detail === '汇总证据并生成最终回答'))
})

test('mergeThinkingTrace 补回没有实时事件对应的截断守卫步骤', () => {
  const finalSteps: ThinkingTraceStep[] = [
    { kind: 'call', tool: 'knowledge_search', detail: '{"query":"x"}', turn: 1 },
    {
      kind: 'result',
      tool: 'knowledge_search',
      detail: '输出被长度截断，参数可能不完整，请重新发起调用',
      isError: true,
      turn: 1,
    },
    { kind: 'note', detail: '汇总证据并生成最终回答', turn: 2 },
  ]
  const liveSteps: ThinkingTraceStep[] = [
    { kind: 'turn', detail: '', turn: 1 },
    { kind: 'note', detail: '输出被长度截断（finish_reason=length），本轮工具调用已作废' },
    { kind: 'turn', detail: '', turn: 2 },
  ]

  const merged = mergeThinkingTrace(finalSteps, liveSteps)
  const kinds = merged.map(step => step.kind)
  assert.equal(kinds.filter(kind => kind === 'call').length, 1)
  assert.equal(kinds.filter(kind => kind === 'result').length, 1)
  const result = merged.find(step => step.kind === 'result')
  assert.equal(result?.isError, true)
  assert.ok(merged.some(step => step.kind === 'note' && step.detail === '汇总证据并生成最终回答'))
})

test('note/answer 事件与 run_end 权威答案替换', async () => {
  const events = [
    { type: 'run_start', run_id: 'r1', turn: 0, payload: {} },
    { type: 'turn_start', run_id: 'r1', turn: 1, payload: { turn: 1 } },
    {
      type: 'tool_start',
      run_id: 'r1',
      turn: 1,
      payload: { name: 'knowledge_search', args: { query: 'x' } },
    },
    {
      type: 'tool_end',
      run_id: 'r1',
      turn: 1,
      payload: { name: 'knowledge_search', is_error: false, duration_ms: 6969, result: '{"items":[],"total":0}' },
    },
    {
      type: 'note',
      run_id: 'r1',
      turn: 1,
      payload: { detail: '边界规则：未检索到有效证据，拒绝给出最终结论' },
    },
    {
      type: 'answer',
      run_id: 'r1',
      turn: 1,
      payload: { content: '没有检索到足够证据支持最终结论。' },
    },
    {
      type: 'run_end',
      run_id: 'r1',
      turn: 1,
      payload: {
        reason: 'completed',
        turns: 1,
        notes: [{ detail: '边界规则：未检索到有效证据，拒绝给出最终结论' }],
        messages: [
          { role: 'user', content: 'x' },
          {
            role: 'assistant',
            content: '```tool_calls\n[{"name":"knowledge_search","arguments":{"query":"x"}}]\n```',
            tool_calls: [{ name: 'knowledge_search', arguments: { query: 'x' } }],
          },
          { role: 'tool', name: 'knowledge_search', content: '{"items":[],"total":0}' },
          { role: 'assistant', content: '没有检索到足够证据支持最终结论。' },
        ],
      },
    },
  ]
  const originalFetch = globalThis.fetch
  globalThis.fetch = (async () => sseResponse(events)) as typeof fetch
  const thinking: ThinkingTraceStep[][] = []
  const replaced: string[] = []
  try {
    const result = await defaultAIChatTransport.query(
      { query: 'x', scene: 'qa', session_id: 's1', library_id: 'default', doc_ids: [] },
      { onThinking: steps => thinking.push(steps), onAnswerReplace: full => replaced.push(full) }
    )
    assert.equal(result.answer, '没有检索到足够证据支持最终结论。')
    assert.ok(replaced.length >= 1)
    const finalSteps = thinking[thinking.length - 1]
    assert.ok(finalSteps.some(step => step.kind === 'note' && step.detail.includes('边界规则')))
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('流式过滤：完整的纯 JSON 工具调用不进入正文', () => {
  assert.equal(
    cleanStreamText('[{"name": "knowledge_search", "arguments": {"query": "x"}}]'),
    ''
  )
})

test('流式过滤：未写完的纯 JSON 工具调用也不进入正文', () => {
  assert.equal(
    cleanStreamText('[{"name": "knowledge_search", "argu'),
    ''
  )
})

test('流式过滤：正文在前、工具调用在后时只保留正文', () => {
  assert.equal(
    cleanStreamText('先思考\n[{"name": "knowledge_search", "arguments": {"query": "x"}}]'),
    '先思考'
  )
  assert.equal(
    cleanStreamText('先思考\n[{"name": "knowledge_search", "argu'),
    '先思考'
  )
})

test('流式过滤：普通 JSON 数组和未闭合围栏不影响正文', () => {
  assert.equal(cleanStreamText('结果：[1, 2, 3]'), '结果：[1, 2, 3]')
  assert.equal(cleanStreamText('正文\n```tool_calls\n[{"name": "x"'), '正文')
})

test('agent 事件实时生成思考过程步骤', () => {
  let steps: ThinkingTraceStep[] = []

  steps = applyAgentEventToThinking(
    { type: 'turn_start', turn: 1, payload: {} },
    steps
  )
  assert.equal(steps[0].kind, 'turn')
  assert.equal(steps[0].turn, 1)

  steps = applyAgentEventToThinking(
    { type: 'tool_start', turn: 1, payload: { name: 'knowledge_search', args: { query: 'x' } } },
    steps
  )
  assert.equal(steps.length, 2)
  assert.equal(steps[1].kind, 'call')
  assert.equal(steps[1].tool, 'knowledge_search')
  assert.equal(steps[1].turn, 1)

  steps = applyAgentEventToThinking(
    {
      type: 'tool_end',
      turn: 1,
      payload: {
        name: 'knowledge_search',
        result: '{"items":[1],"total":1}',
        is_error: true,
        duration_ms: 120,
      },
    },
    steps
  )
  assert.equal(steps.length, 3)
  assert.equal(steps[2].kind, 'result')
  assert.equal(steps[2].tool, 'knowledge_search')
  assert.equal(steps[2].detail, '检索到 1 条结果')
  assert.equal(steps[2].isError, true)
  assert.equal(steps[2].durationMs, 120)

  const unchanged = applyAgentEventToThinking(
    { type: 'message_delta', payload: { delta: 'x' } },
    steps
  )
  assert.equal(unchanged.length, 3)
})
