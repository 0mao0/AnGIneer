import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  formatThinkingArgDetail,
  groupThinkingSteps,
} from '../src/utils/thinking.ts'
import type { ThinkingTraceStep } from '../src/types/chat'

test('调用和返回配对成一步', () => {
  const steps: ThinkingTraceStep[] = [
    { kind: 'call', tool: 'knowledge_search', detail: '{"query":"上航数联"}' },
    { kind: 'result', tool: 'knowledge_search', detail: '检索到 3 条结果' },
  ]
  const groups = groupThinkingSteps(steps)
  assert.equal(groups.length, 1)
  assert.equal(groups[0].index, 1)
  assert.equal(groups[0].tool, 'knowledge_search')
  assert.equal(groups[0].callDetail, '{"query":"上航数联"}')
  assert.equal(groups[0].resultDetail, '检索到 3 条结果')
})

test('多轮工具调用各自成步', () => {
  const steps: ThinkingTraceStep[] = [
    { kind: 'call', tool: 'knowledge_search', detail: '{"query":"A"}' },
    { kind: 'result', tool: 'knowledge_search', detail: '检索到 2 条结果' },
    { kind: 'call', tool: 'table_search', detail: '{"query":"B"}' },
    { kind: 'result', tool: 'table_search', detail: '检索到 1 条结果' },
  ]
  const groups = groupThinkingSteps(steps)
  assert.equal(groups.length, 2)
  assert.equal(groups[0].index, 1)
  assert.equal(groups[1].index, 2)
  assert.equal(groups[1].tool, 'table_search')
})

test('没有调用记录的返回也单独成步', () => {
  const groups = groupThinkingSteps([
    { kind: 'result', tool: 'calculator', detail: '结果 = 42' },
  ])
  assert.equal(groups.length, 1)
  assert.equal(groups[0].callDetail, '')
  assert.equal(groups[0].resultDetail, '结果 = 42')
})

test('工具参数转成可读文本', () => {
  assert.equal(
    formatThinkingArgDetail('{"query":"上航数联","limit":10}'),
    'query = 上航数联，limit = 10'
  )
  assert.equal(formatThinkingArgDetail('不是 JSON'), '不是 JSON')
})

test('轮次和说明以独立步骤展示', () => {
  const groups = groupThinkingSteps([
    { kind: 'turn', turn: 1, detail: '' },
    { kind: 'call', tool: 'knowledge_search', detail: '{"query":"x"}' },
    { kind: 'result', tool: 'knowledge_search', detail: '检索到 1 条结果' },
    { kind: 'note', detail: '轮次预算已用完，进入收尾回答' },
  ])
  assert.equal(groups.length, 3)
  assert.equal(groups[0].kind, 'note')
  assert.equal(groups[0].label, '第 1 轮')
  assert.equal(groups[1].kind, 'pair')
  assert.equal(groups[1].callDetail, '{"query":"x"}')
  assert.equal(groups[2].kind, 'note')
  assert.equal(groups[2].detail, '轮次预算已用完，进入收尾回答')
})

test('工具返回的证据挂在对应步骤上', () => {
  const groups = groupThinkingSteps([
    { kind: 'call', tool: 'knowledge_search', detail: '{}' },
    {
      kind: 'result',
      tool: 'knowledge_search',
      detail: '检索到 1 条结果',
      citations: [{
        target_id: 't1',
        doc_id: 'doc-1',
        doc_title: '推广产品.docx',
        page_idx: 0,
        section_path: '产品一',
        snippet: 'xxx',
        score: 1,
      }],
    },
  ])
  assert.equal(groups.length, 1)
  assert.equal(groups[0].citations?.length, 1)
  assert.equal(groups[0].citations?.[0].doc_title, '推广产品.docx')
})
