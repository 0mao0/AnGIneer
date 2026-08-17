import { test } from 'node:test'
import assert from 'node:assert/strict'

import { buildMatchSegments, textItemsInRect } from '../src/utils/pdfSearch.ts'
import type { PageTextItem } from '../src/utils/pdfSearch'

const item = (text: string, left: number, top: number, width = 0.1, height = 0.02): PageTextItem => ({
  text,
  left,
  top,
  width,
  height,
})

test('textItemsInRect 只取与矩形相交的文本项并按行拼接', () => {
  const items = [
    item('第一行', 0.1, 0.1),
    item('第二行A', 0.1, 0.2),
    item('第二行B', 0.3, 0.2),
    item('框外', 0.8, 0.8),
  ]
  const text = textItemsInRect(items, { left: 0.05, top: 0.05, width: 0.6, height: 0.3 })
  assert.equal(text, '第一行\n第二行A第二行B')
})

test('textItemsInRect 空输入返回空串', () => {
  assert.equal(textItemsInRect([], { left: 0, top: 0, width: 1, height: 1 }), '')
})

test('buildMatchSegments 精确匹配加粗命中段', () => {
  const segs = buildMatchSegments('甲乙丙丁', '乙丙')
  assert.deepEqual(segs, [
    { text: '甲', hit: false },
    { text: '乙丙', hit: true },
    { text: '丁', hit: false },
  ])
})

test('buildMatchSegments 空白差异容错匹配', () => {
  const segs = buildMatchSegments('第一条 规定', '第一条规定')
  assert.ok(segs.some((s) => s.hit && s.text.includes('第一条')))
})

test('buildMatchSegments 无 matchText 时整段不加粗', () => {
  const segs = buildMatchSegments('全文', '')
  assert.deepEqual(segs, [{ text: '全文', hit: false }])
})
