import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { buildTraceRows } from './trace.ts'

const fixture = JSON.parse(
  readFileSync(new URL('../../test/fixtures/trace-l1.json', import.meta.url), 'utf8')
)
const intent = {
  intent_level: 'L1',
  service_mode: 'semantic_retrieval',
  reason: '统计词问的是文档正文中的数值，走正文检索',
}

function rowsOf(trace = fixture) {
  return buildTraceRows({ trace, intent, stageTimings: { intent: 1.101 } })
}

test('意图节点排第一，带 intent 耗时', () => {
  const rows = rowsOf()
  assert.equal(rows[0].kind, 'intent')
  assert.equal(rows[0].level, 'L1')
  assert.equal(rows[0].serviceMode, 'semantic_retrieval')
  assert.equal(rows[0].timing, 1.101)
})

test('message_delta 不进渲染行', () => {
  const rows = rowsOf()
  assert.equal(rows.some(row => row.kind === 'unknown' && row.type === 'message_delta'), false)
  assert.equal(rows.some(row => row.kind === 'note' && row.detail.includes('delta')), false)
})

test('turn 头按事件顺序去重：预检 + 第 1 轮', () => {
  const labels = rowsOf()
    .filter(row => row.kind === 'turn')
    .map(row => row.label)
  assert.deepEqual(labels, ['预检', '第 1 轮'])
})

test('tool_start/tool_end 按 call_id 配成一张卡', () => {
  const tools = rowsOf().filter(row => row.kind === 'tool')
  assert.equal(tools.length, 1)
  assert.equal(tools[0].name, 'knowledge_search')
  assert.equal(tools[0].durationMs, 25719)
  assert.equal(tools[0].injected, true)
  assert.equal(tools[0].args.query, 'springing lien market practice')
})

test('llm_request 渲染为真实 prompt 行', () => {
  const prompt = rowsOf().find(row => row.kind === 'prompt')
  assert.ok(prompt)
  assert.equal(prompt.messageCount, 3)
  assert.equal(prompt.promptChars, 1234)
  assert.equal(prompt.truncated, false)
  assert.equal(prompt.messages[0].role, 'system')
  assert.match(prompt.messages[0].content, /问答助手/)
})

test('note 保留 tokens / TTFT / 耗时', () => {
  const note = rowsOf().find(
    row => row.kind === 'note' && row.promptTokens === 1200
  )
  assert.ok(note)
  assert.equal(note.ttftMs, 600)
  assert.equal(note.durationMs, 8600)
})

test('run_end 汇总读 summary，工具数不缺', () => {
  const end = rowsOf().find(row => row.kind === 'run_end')
  assert.ok(end)
  assert.equal(end.summary.final_outcome, 'model_answer')
  assert.equal(end.summary.turns, 1)
  assert.equal(end.summary.tool_calls, 1)
  assert.deepEqual(end.summary.path_trace, ['first_search_injected'])
})

test('未知事件类型保留为通用行，不静默丢', () => {
  const unknown = rowsOf().find(row => row.kind === 'unknown')
  assert.ok(unknown)
  assert.equal(unknown.type, 'artifact')
  assert.equal(unknown.payload.name, 'response.md')
})

test('没有 trace 时返回空，页面显示「无事件 trace」', () => {
  assert.deepEqual(buildTraceRows({ trace: null, intent }), [])
  assert.deepEqual(buildTraceRows({ trace: { events: [] }, intent }), [])
})
