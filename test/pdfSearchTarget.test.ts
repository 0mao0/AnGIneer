import { test } from 'node:test'
import assert from 'node:assert/strict'

import { pickSearchTargetHighlight } from '../src/utils/pdfSearch.ts'

// 复现「编辑版 markdown 行号 ≠ 解析版 markdown 行号」导致的定位错位：
// 图数据（解析版 content.md）里 "3.1.20" 在第 32/44/399/3806 行，对应第 2/3/14/117 页；
// 但查看器搜索的是编辑版 current.md，命中行是 32/44/362/3689。
const highlights = [
  {
    id: 'h2',
    page: 2,
    lineStart: 32,
    lineEnd: 32,
    hasRect: true,
    text: '《规范》第3.1.4条、第3.1.5条、第3.1.7条、第3.1.9条、第3.1.20条、第5.4.7条中的黑体字部分为强制性条文。',
  },
  {
    id: 'h3',
    page: 3,
    lineStart: 44,
    lineEnd: 44,
    hasRect: true,
    text: '本规范第3.1.4条、第3.1.5条、第3.1.7条、第3.1.9条、第3.1.20条和第5.4.7条中的黑体字部分为强制性条文。',
  },
  {
    id: 'h14',
    page: 14,
    lineStart: 399,
    lineEnd: 399,
    hasRect: true,
    text: '3.1.20 施工过程中未成型的防波堤与护岸,应根据实际情况采取相应的防护措施。',
  },
  {
    id: 'h117',
    page: 117,
    lineStart: 3806,
    lineEnd: 3806,
    hasRect: true,
    text: '3.1.20 防波堤和护岸在实施过程中如遇恶劣气象事件,特别是台风多发区会造成较大损失,本条做了相关规定。',
  },
]

test('行号一致时按行号就近命中（第 32/44 行 → 第 2/3 页）', () => {
  assert.equal(pickSearchTargetHighlight('3.1.20', highlights[0].text, 32, highlights as any)?.page, 2)
  assert.equal(pickSearchTargetHighlight('3.1.20', highlights[1].text, 44, highlights as any)?.page, 3)
})

test('编辑版行号漂移时按文本命中 + 行距最近定位（第 362 行 → 第 14 页）', () => {
  const target = pickSearchTargetHighlight('3.1.20', '3.1.20 施工过程中未成型的防波堤与护岸,应根据实际情况采取相应的防护措施。', 362, highlights as any)
  assert.equal(target?.page, 14)
})

test('编辑版行号漂移时按文本命中 + 行距最近定位（第 3689 行 → 第 117 页）', () => {
  const target = pickSearchTargetHighlight('3.1.20', '3.1.20 防波堤和护岸在实施过程中如遇恶劣气象事件,特别是台风多发区会造成较大损失,本条做了相关规定。', 3689, highlights as any)
  assert.equal(target?.page, 117)
})

test('无文本命中时返回 null（保留旧行号映射兜底）', () => {
  assert.equal(pickSearchTargetHighlight('不存在的词', 'xx', 5, highlights as any), null)
})
