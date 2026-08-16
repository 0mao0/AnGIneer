import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  formatThinkingArgDetail,
  formatThinkingStepLabel,
  groupThinkingSteps,
  isResultExpandable,
} from '../src/utils/thinking.ts'
import type { ThinkingGroupStep } from '../src/utils/thinking'
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

test('每个步骤都有序号前缀，说明类步骤也一样', () => {
  const note: ThinkingGroupStep = {
    index: 3,
    kind: 'note',
    detail: '未调用检索工具，已要求重新检索后回答',
  }
  assert.equal(
    formatThinkingStepLabel(note),
    '3. 未调用检索工具，已要求重新检索后回答'
  )

  const pair: ThinkingGroupStep = {
    index: 1,
    kind: 'pair',
    tool: 'knowledge_search',
    callDetail: '{"query":"上航数联"}',
  }
  assert.equal(formatThinkingStepLabel(pair), '1. 调用工具：knowledge_search')

  const resultOnly: ThinkingGroupStep = {
    index: 2,
    kind: 'pair',
    tool: 'calculator',
    callDetail: '',
    resultDetail: '结果 = 42',
  }
  assert.equal(formatThinkingStepLabel(resultOnly), '2. 工具返回：calculator')
})

test('只有带候选条目的结果步骤可以展开', () => {
  const expandable: ThinkingGroupStep = {
    index: 1,
    kind: 'pair',
    tool: 'knowledge_search',
    callDetail: '{}',
    resultDetail: '检索到 20 条结果',
    resultItems: Array.from({ length: 20 }, (_, i) => ({
      item_id: `item-${i + 1}`,
      entity_type: 'content',
      doc_id: 'doc-1',
      doc_title: '推广产品.docx',
      title: `候选 ${i + 1}`,
      text: `第 ${i + 1} 条内容`,
      score: 0.9 - i * 0.01,
      metadata: { cite: `K${i + 1}` },
    })),
  }
  assert.equal(isResultExpandable(expandable), true)

  const plain: ThinkingGroupStep = {
    index: 2,
    kind: 'pair',
    tool: 'knowledge_search',
    callDetail: '{}',
    resultDetail: '检索到 0 条结果',
  }
  assert.equal(isResultExpandable(plain), false)
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
