import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  applyAgentEventToThinking,
  buildThinkingTrace,
  cleanStreamText,
  defaultAIChatTransport,
  extractSopFlowsFromToolMessages,
  extractToolResultItems,
  filterCitationsByMarkers,
  mergeThinkingTrace,
  normalizeSopFlow,
  stripToolCallArtifacts,
  summarizeToolResult,
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

test('去掉 ```json 围栏包裹的工具调用块', () => {
  const text = stripToolCallArtifacts(
    '先检索\n```json\n[{"name": "knowledge_search", "arguments": {"query": "洪家场浦"}}]\n```'
  )
  assert.equal(text, '先检索')
})

test('去掉普通 ``` 围栏包裹的工具调用块', () => {
  const text = stripToolCallArtifacts(
    '先检索\n```\n[{"name": "knowledge_search", "arguments": {"query": "洪家场浦"}}]\n```'
  )
  assert.equal(text, '先检索')
})

test('流式中未闭合的 ```json 工具调用围栏被截断', () => {
  const text = stripToolCallArtifacts(
    '您是否想知道具体技术参数？\n```json\n[{"name": "knowledge_search", "arguments": {"query": "洪家场浦"}}'
  )
  assert.equal(text, '您是否想知道具体技术参数？')
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

test('预算截断说明会出现在轨迹里（不再合成「汇总证据并生成最终回答」标记行）', () => {
  const steps = buildThinkingTrace(
    [{ role: 'assistant', content: '答案是 X' }],
    [{ detail: '轮次预算已用完（max_turns=2），进入无工具收尾回答' }]
  )
  assert.deepEqual(steps, [
    { kind: 'note', detail: '轮次预算已用完（max_turns=2），进入无工具收尾回答' },
  ])
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

test('工具返回同时带 citations 与 items 时保留全部 cite 标记', () => {
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
        total: 5,
        citations: [
          { target_id: 'a', doc_id: 'd1', doc_title: '船闸规范.pdf', marker: 'K1', page_idx: 0, section_path: '2.2', snippet: 'a', score: 0.9 },
          { target_id: 'b', doc_id: 'd1', doc_title: '船闸规范.pdf', marker: 'K2', page_idx: 0, section_path: '2.2', snippet: 'b', score: 0.8 },
        ],
        items: [
          { item_id: 'a', entity_type: 'content', doc_id: 'd1', title: 't', text: 'a', score: 0.9, metadata: { doc_title: '船闸规范.pdf', cite: 'K1' } },
          { item_id: 'b', entity_type: 'content', doc_id: 'd1', title: 't', text: 'b', score: 0.8, metadata: { doc_title: '船闸规范.pdf', cite: 'K2' } },
          { item_id: 'c', entity_type: 'content', doc_id: 'd1', title: 't', text: 'c', score: 0.7, metadata: { doc_title: '船闸规范.pdf', cite: 'K3' } },
          { item_id: 'd', entity_type: 'content', doc_id: 'd1', title: 't', text: 'd', score: 0.6, metadata: { doc_title: '船闸规范.pdf', cite: 'K4' } },
          { item_id: 'e', entity_type: 'content', doc_id: 'd1', title: 't', text: 'e', score: 0.5, metadata: { doc_title: '船闸规范.pdf', cite: 'K5' } },
        ],
      }),
    },
  ])
  const result = steps.find(step => step.kind === 'result')
  const markers = (result?.citations || []).map(citation => citation.marker).sort()
  assert.deepEqual(markers, ['K1', 'K2', 'K3', 'K4', 'K5'])
})

test('多库溯源（B1）：citations 帧不带 library_id 时按同消息 items 对账回填，items 分支直读 metadata', () => {
  const steps = buildThinkingTrace([
    {
      role: 'assistant',
      content: '',
      tool_calls: [{ name: 'knowledge_search', arguments: { query: 'x' } }],
    },
    {
      role: 'tool',
      name: 'knowledge_search',
      // citations 帧（docs-core relevant_citations 形态）无 library_id；items 带标源 metadata
      content: JSON.stringify({
        total: 2,
        citations: [
          { target_id: 't1', doc_id: 'dB', doc_title: 'B规范.pdf', marker: 'K1', page_idx: 0, section_path: '3.1', snippet: 'a', score: 0.9 },
        ],
        items: [
          { item_id: 't1', entity_type: 'content', doc_id: 'dB', title: 'B规范', text: 'a', score: 0.9, metadata: { doc_title: 'B规范.pdf', cite: 'K1', library_id: 'libB' } },
          { item_id: 't2', entity_type: 'content', doc_id: 'dC', title: 'C手册', text: 'b', score: 0.8, metadata: { doc_title: 'C手册.pdf', cite: 'K2', library_id: 'libC' } },
        ],
      }),
    },
    {
      role: 'tool',
      name: 'table_search',
      // 无 items 可对账 → library_id 留缺省（宿主按首库回退），不得瞎猜
      content: JSON.stringify({
        total: 1,
        citations: [
          { target_id: 't9', doc_id: 'dZ', doc_title: '孤儿表.xlsx', marker: 'T1', page_idx: 0, section_path: '', snippet: 'c', score: 0.7 },
        ],
      }),
    },
  ])
  const kb = steps.find(step => step.kind === 'result' && step.tool === 'knowledge_search')
  const byMarker = new Map((kb?.citations || []).map(c => [c.marker, c]))
  // citations 分支的 K1：按 marker 对账 items 回填 libB（去重保留先入的 citations 条目）
  assert.equal(byMarker.get('K1')?.library_id, 'libB')
  // items 分支的 K2：直读 metadata.library_id
  assert.equal(byMarker.get('K2')?.library_id, 'libC')
  assert.equal((kb?.citations || []).length, 2)
  const orphan = steps.find(step => step.kind === 'result' && step.tool === 'table_search')
  assert.equal(orphan?.citations?.[0]?.library_id, undefined)
})

test('多库溯源（投影形态）：顶层 cite/library_id 同样回填，条目不得整条丢', () => {
  const steps = buildThinkingTrace([
    {
      role: 'assistant',
      content: '',
      tool_calls: [{ name: 'knowledge_search', arguments: { query: 'x' } }],
    },
    {
      role: 'tool',
      name: 'knowledge_search',
      // 投影形态：metadata 已剥，cite/library_id 在条目顶层（生产 10-06 起实况）
      content: JSON.stringify({
        total: 2,
        citations: [
          { target_id: 't1', doc_id: 'dB', doc_title: 'B规范.pdf', marker: 'K1', page_idx: 0, section_path: '3.1', snippet: 'a', score: 0.9 },
        ],
        items: [
          { item_id: 't1', entity_type: 'content', doc_id: 'dB', title: 'B规范', text: 'a', rerank_score: 0.9, cite: 'K1', library_id: 'libB', doc_title: 'B规范.pdf' },
          { item_id: 't2', entity_type: 'content', doc_id: 'dC', title: 'C手册', text: 'b', rerank_score: 0.8, cite: 'K2', library_id: 'libC', doc_title: 'C手册.pdf' },
        ],
      }),
    },
  ])
  const kb = steps.find(step => step.kind === 'result' && step.tool === 'knowledge_search')
  const byMarker = new Map((kb?.citations || []).map(c => [c.marker, c]))
  assert.equal(byMarker.get('K1')?.library_id, 'libB')
  assert.equal(byMarker.get('K2')?.library_id, 'libC')
  assert.equal(kb?.resultItems?.length, 2)
  assert.equal(kb?.resultItems?.[0]?.cite, 'K1')
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

test('extractToolResultItems 兼容投影形态（顶层 cite/doc_id/位置键，metadata 已剥）', () => {
  // 生产形态：LLM 投影把 metadata 的引用/位置键提升到条目顶层（2026-10-16 复盘）
  const items = extractToolResultItems(JSON.stringify({
    total: 1,
    items: [{
      item_id: 'i1',
      entity_type: 'chunk',
      doc_id: 'd1',
      title: '公路水泥规范',
      text: '混凝土保护层厚度 30mm。',
      rerank_score: 0.72,
      citation_target_id: 'ct1',
      cite: 'K1',
      page_idx: 3,
      page_label: '12',
      section_path: '4 材料 / 4.1 水泥',
      library_id: 'std-highway',
      doc_title: '公路水泥规范.pdf',
    }],
  }))
  const item = items?.[0]
  assert.equal(item?.cite, 'K1')
  assert.equal(item?.doc_id, 'd1')
  assert.equal(item?.doc_title, '公路水泥规范.pdf')
  // 顶层位置键合回 metadata：思考轨迹条目点击跳页走 item.metadata.page_idx，两形态都要有
  assert.equal(item?.metadata?.page_idx, 3)
  assert.equal(item?.metadata?.page_label, '12')
  assert.equal(item?.metadata?.section_path, '4 材料 / 4.1 水泥')
  assert.equal(item?.metadata?.library_id, 'std-highway')
})

test('extractToolResultItems 对缺 item_id 的历史行按位置兜底，不再整条丢弃', () => {
  const items = extractToolResultItems(JSON.stringify({
    total: 1,
    items: [{ doc_id: 'd9', text: '无 id 的历史投影行', cite: 'K7' }],
  }))
  assert.equal(items?.length, 1)
  assert.equal(items?.[0]?.cite, 'K7')
  assert.match(String(items?.[0]?.item_id), /^item-0-d9/)
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

test('extractToolResultItems 优先使用融合重排分而非原始分', () => {
  const items = extractToolResultItems(JSON.stringify({
    total: 2,
    items: [
      {
        item_id: 'a',
        entity_type: 'content',
        doc_id: 'd1',
        title: 'A',
        text: '内容 A',
        score: 6.2,
        rerank_score: 0.18,
        metadata: { doc_title: 'a.pdf' },
      },
      {
        item_id: 'b',
        entity_type: 'content',
        doc_id: 'd2',
        title: 'B',
        text: '内容 B',
        score: 5.1,
        metadata: { doc_title: 'b.pdf', normalized_score: 0.42 },
      },
    ],
  }))
  assert.equal(items?.[0].score, 0.18)
  assert.equal(items?.[1].score, 0.42)
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
    { kind: 'note', detail: '执行计划：L1 语义检索', turn: 1 },
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
  assert.ok(merged.some(step => step.kind === 'note' && step.detail === '执行计划：L1 语义检索'))
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
    { kind: 'note', detail: '执行计划：L1 语义检索', turn: 2 },
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
  assert.ok(merged.some(step => step.kind === 'note' && step.detail === '执行计划：L1 语义检索'))
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

test('新一轮 turn 开始时清空上一轮流式正文（拒答重答不残留中间疑问句）', async () => {
  const refusal = '没有检索到足够证据支持最终结论。您是否想知道其他规范？'
  const finalAnswer = '该规范主要内容包括设计与施工要求。'
  const events = [
    { type: 'run_start', run_id: 'r1', turn: 0, payload: {} },
    { type: 'turn_start', run_id: 'r1', turn: 1, payload: { turn: 1 } },
    { type: 'message_delta', run_id: 'r1', turn: 1, payload: { delta: refusal } },
    {
      type: 'note',
      run_id: 'r1',
      turn: 1,
      payload: { detail: '有有效证据但回答为拒答，已要求基于证据重答' },
    },
    { type: 'turn_start', run_id: 'r1', turn: 2, payload: { turn: 2 } },
    { type: 'message_delta', run_id: 'r1', turn: 2, payload: { delta: finalAnswer } },
    {
      type: 'run_end',
      run_id: 'r1',
      turn: 2,
      payload: {
        reason: 'completed',
        turns: 2,
        notes: [{ detail: '有有效证据但回答为拒答，已要求基于证据重答' }],
        messages: [
          { role: 'user', content: 'x' },
          { role: 'assistant', content: refusal },
          { role: 'user', content: '已检索到有效证据，请基于证据作答' },
          { role: 'assistant', content: finalAnswer },
        ],
      },
    },
  ]
  const originalFetch = globalThis.fetch
  globalThis.fetch = (async () => sseResponse(events)) as typeof fetch
  let bubble = ''
  const snapshots: string[] = []
  try {
    const result = await defaultAIChatTransport.query(
      { query: 'x', scene: 'qa', session_id: 's1', library_id: 'default', doc_ids: [] },
      {
        onDelta: d => {
          bubble += d
          snapshots.push(bubble)
        },
        onAnswerReplace: full => {
          bubble = full
          snapshots.push(bubble)
        },
      }
    )
    assert.equal(result.answer, finalAnswer)
    assert.equal(bubble, finalAnswer)
    const clearIdx = snapshots.findIndex(s => s === '')
    assert.ok(clearIdx >= 0, 'turn 2 开始时应先清空气泡')
    for (const s of snapshots.slice(clearIdx + 1)) {
      assert.ok(!s.includes('您是否'), `重答轮之后气泡不应残留中间疑问句: ${s}`)
    }
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('多库载荷：body 带 library_ids 且 library_id=首项', async () => {
  const events = [
    { type: 'run_start', run_id: 'r1', turn: 0, payload: {} },
    {
      type: 'run_end',
      run_id: 'r1',
      turn: 0,
      payload: { reason: 'completed', turns: 0, notes: [], messages: [] },
    },
  ]
  const originalFetch = globalThis.fetch
  let capturedBody = ''
  globalThis.fetch = (async (_url: any, init?: any) => {
    capturedBody = String(init?.body ?? '')
    return sseResponse(events)
  }) as typeof fetch
  try {
    await defaultAIChatTransport.query(
      {
        query: '跨库提问',
        scene: 'qa',
        session_id: 's-multi',
        library_id: 'libA',
        library_ids: ['libA', 'libB'],
        doc_ids: [],
      },
      {}
    )
    const body = JSON.parse(capturedBody)
    assert.deepEqual(body.library_ids, ['libA', 'libB'])
    assert.equal(body.library_id, 'libA')
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('旧宿主兼容：payload 不带 library_ids 时 body 无该键', async () => {
  const events = [
    { type: 'run_start', run_id: 'r1', turn: 0, payload: {} },
    {
      type: 'run_end',
      run_id: 'r1',
      turn: 0,
      payload: { reason: 'completed', turns: 0, notes: [], messages: [] },
    },
  ]
  const originalFetch = globalThis.fetch
  let capturedBody = ''
  globalThis.fetch = (async (_url: any, init?: any) => {
    capturedBody = String(init?.body ?? '')
    return sseResponse(events)
  }) as typeof fetch
  try {
    await defaultAIChatTransport.query(
      { query: '单库提问', scene: 'qa', session_id: 's-single', library_id: 'libA', doc_ids: [] },
      {}
    )
    const body = JSON.parse(capturedBody)
    // 负断言：undefined 会被 JSON.stringify 剥掉；实现若误写空数组此断言必红
    assert.equal('library_ids' in body, false)
    assert.equal(body.library_id, 'libA')
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('流式过滤：完整的纯 JSON 工具调用不进入正文', () => {  assert.equal(
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

test('summarizeToolResult 如实显示工具错误，不吞成占位符', () => {
  // 纯文本错误（如 SQLite 打不开库）必须原样透出，否则故障被伪装成「完整内容见最终轨迹」
  assert.equal(
    summarizeToolResult('工具执行失败: unable to open database file'),
    '工具执行失败: unable to open database file'
  )
  // 流式阶段被截断的 JSON 残片仍然只给占位符，不把残片漏进界面
  assert.equal(
    summarizeToolResult('{"items": [{"item_id": "x", "text": "截断'),
    '工具已返回结果（完整内容见最终轨迹）'
  )
  // 合法 JSON 照旧走摘要
  assert.equal(summarizeToolResult('{"items": [1, 2], "total": 2}'), '检索到 2 条结果')
  assert.equal(summarizeToolResult('{"entities": [], "total": 0}'), '图谱检索到 0 个实体')
})

test('normalizeSopFlow 归一实时快照：三态状态、耗时换算、done 兜底计数', () => {
  const plan = normalizeSopFlow({
    sop_id: 'sop_tide',
    sop_name: '潮位查表计算',
    total: 2,
    done: 0,
    running: true,
    steps: [
      { step_id: 's1', step_name: '查表', tool: 'table_lookup', status: 'pending' },
      { step_id: 's2', step_name: '计算', tool: 'python_compute', status: 'pending' },
    ],
  })
  assert.equal(plan?.running, true)
  assert.equal(plan?.done, 0)
  assert.equal(plan?.steps[0].step_name, '查表')

  const step = normalizeSopFlow({
    sop_id: 'sop_tide',
    total: 2,
    running: true,
    steps: [
      { step_id: 's1', step_name: '查表', tool: 'table_lookup', status: 'success', duration_ms: 1500 },
      { step_id: 's2', step_name: '计算', tool: 'python_compute', status: 'failed', error: '缺参 W' },
    ],
  })
  assert.equal(step?.steps[0].status, 'success')
  assert.equal(step?.steps[0].duration_ms, 1500)
  assert.equal(step?.steps[1].status, 'failed')
  assert.equal(step?.steps[1].error, '缺参 W')
  // done 缺省时按非 pending 步数兜底
  assert.equal(step?.done, 2)

  // 形状不认识静默丢弃
  assert.equal(normalizeSopFlow({}), undefined)
  assert.equal(normalizeSopFlow({ sop_id: 'x', steps: 'no' }), undefined)
})

test('extractSopFlowsFromToolMessages 从 sop_trace 重建终态：失败与缺参保留', () => {
  const toolMessage = {
    role: 'tool',
    content: JSON.stringify({
      sop_id: 'sop_tide',
      sop_name: '潮位查表计算',
      steps: [
        { step_id: 's1', step_name: '查表', status: 'success' },
        { step_id: 's2', step_name: '计算', status: 'error' },
      ],
      sop_trace: [
        { step_id: 's1', status: 'success', duration: 1.5, tool: 'table_lookup' },
        { step_id: 's2', status: 'error', error: '缺少参数 W，推荐值 310.03', tool: 'python_compute' },
      ],
      missing_report: ['W'],
    }),
  }
  const flows = extractSopFlowsFromToolMessages([toolMessage])
  assert.equal(flows.length, 1)
  const flow = flows[0]
  assert.equal(flow.running, false)
  // done 口径与后端一致：非 pending 即计入（失败也算走完）
  assert.equal(flow.done, 2)
  assert.equal(flow.steps[0].duration_ms, 1500)
  assert.equal(flow.steps[1].status, 'failed')
  assert.equal(flow.steps[1].error, '缺少参数 W，推荐值 310.03')
  assert.deepEqual(flow.missing_report, ['W'])

  // 无 sop_trace 的工具消息不产流
  assert.equal(extractSopFlowsFromToolMessages([{ role: 'tool', content: '{"items":[]}' }]).length, 0)
  assert.equal(extractSopFlowsFromToolMessages([{ role: 'tool', content: 'not json' }]).length, 0)
})

test('SOP 步骤参数绑定与结果透传：live 归一 + 回放重建都要保留，脏值清洗', () => {
  // live 帧：bindings + result 原样保留（截断/标量清洗）
  const live = normalizeSopFlow({
    sop_id: 'sop_breakwater',
    total: 1,
    running: true,
    steps: [
      {
        step_id: 'step_1',
        step_name: '计算零点高度',
        tool: 'calculator',
        status: 'success',
        duration_ms: 7,
        bindings: { 设计波高H: 2.8, 长文本: 'x'.repeat(80), 结构体: { a: 1 }, 缺失名: null },
        result: 4.2,
      },
    ],
  })
  assert.deepEqual(live?.steps[0].bindings, {
    设计波高H: 2.8,
    长文本: 'x'.repeat(60) + '…',
    缺失名: null,
  })
  assert.equal(live?.steps[0].result, 4.2)

  // 回放：从 sop_trace 明细取 bindings/result；旧消息（无字段）不渲染不报错
  const toolMessage = {
    role: 'tool',
    content: JSON.stringify({
      sop_id: 'sop_breakwater',
      sop_name: '半圆型防波堤波浪力计算',
      steps: [{ step_id: 'step_1', step_name: '计算零点高度', status: 'success' }],
      sop_trace: [
        {
          step_id: 'step_1',
          status: 'success',
          duration: 0.007,
          tool: 'calculator',
          bindings: { 设计波高H: 2.8 },
          result: 4.2,
        },
      ],
    }),
  }
  const replay = extractSopFlowsFromToolMessages([toolMessage])
  assert.deepEqual(replay[0].steps[0].bindings, { 设计波高H: 2.8 })
  assert.equal(replay[0].steps[0].result, 4.2)

  const legacy = extractSopFlowsFromToolMessages([{
    role: 'tool',
    content: JSON.stringify({
      sop_id: 'sop_old',
      steps: [{ step_id: 's1', step_name: '旧步', status: 'success' }],
      sop_trace: [{ step_id: 's1', status: 'success', duration: 1 }],
    }),
  }])
  assert.equal(legacy[0].steps[0].bindings, undefined)
  assert.equal(legacy[0].steps[0].result, undefined)
})

test('SSE sop_flow 事件驱动 onSopFlow 回调，run_end 工具消息终态覆盖 live 快照', async () => {
  const sopToolContent = JSON.stringify({
    sop_id: 'sop_tide',
    sop_name: '潮位查表计算',
    steps: [{ step_id: 's1', step_name: '查表', status: 'success' }],
    sop_trace: [{ step_id: 's1', status: 'success', duration: 1.5, tool: 'table_lookup' }],
  })
  const events = [
    { type: 'run_start', run_id: 'r1', turn: 0, payload: {} },
    {
      type: 'sop_flow', run_id: 'r1', turn: 0,
      payload: { sop_id: 'sop_tide', sop_name: '潮位查表计算', total: 1, done: 0, running: true,
        steps: [{ step_id: 's1', step_name: '查表', tool: 'table_lookup', status: 'pending' }] },
    },
    {
      type: 'run_end', run_id: 'r1', turn: 1,
      payload: {
        reason: 'completed', turns: 1, notes: [],
        messages: [
          { role: 'user', content: 'x' },
          { role: 'tool', name: 'sop_execute', content: sopToolContent },
          { role: 'assistant', content: '潮位结论如下。' },
        ],
      },
    },
  ]
  const originalFetch = globalThis.fetch
  globalThis.fetch = (async () => sseResponse(events)) as typeof fetch
  const snapshots: Array<{ running: boolean; done: number }> = []
  try {
    const result = await defaultAIChatTransport.query(
      { query: 'x', scene: 'qa', session_id: 's1', library_id: 'default', doc_ids: [] },
      { onSopFlow: flows => snapshots.push(...flows.map(f => ({ running: f.running, done: f.done }))) }
    )
    assert.equal(result.answer, '潮位结论如下。')
    assert.equal(snapshots.length, 2)
    assert.equal(snapshots[0].running, true)
    assert.equal(snapshots[0].done, 0)
    // run_end 终态覆盖：running 收敛为 false
    assert.equal(snapshots[snapshots.length - 1].running, false)
    assert.equal(result.sop_flows?.length, 1)
    assert.equal(result.sop_flows?.[0].running, false)
    assert.equal(result.sop_flows?.[0].steps[0].status, 'success')
  } finally {
    globalThis.fetch = originalFetch
  }
})
