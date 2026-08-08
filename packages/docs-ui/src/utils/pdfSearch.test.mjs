import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildHighlightSegments,
  buildPrintedPageLabels,
  estimateMatchRects,
  insetWordRects,
  matchTextItemRects,
} from './pdfSearch.ts'

test('buildHighlightSegments 命中词分段', () => {
  assert.deepEqual(buildHighlightSegments('第一段正文', '正文'), [
    { text: '第一段', hit: false },
    { text: '正文', hit: true },
  ])
})

test('buildHighlightSegments 大小写不敏感且多处命中', () => {
  const segments = buildHighlightSegments('Foo bar FOO', 'foo')
  assert.deepEqual(segments, [
    { text: 'Foo', hit: true },
    { text: ' bar ', hit: false },
    { text: 'FOO', hit: true },
  ])
})

test('buildHighlightSegments 无命中与空查询', () => {
  assert.deepEqual(buildHighlightSegments('正文', '不存在'), [{ text: '正文', hit: false }])
  assert.deepEqual(buildHighlightSegments('正文', '  '), [{ text: '正文', hit: false }])
  assert.deepEqual(buildHighlightSegments('', '词'), [])
})

test('estimateMatchRects CJK 等宽估算', () => {
  const rects = estimateMatchRects('正文标题内容', '标题', { left: 0.1, top: 0.2, width: 0.5, height: 0.05 })
  assert.equal(rects.length, 1)
  const r = rects[0]
  assert.ok(Math.abs(r.left - (0.1 + (2 / 6) * 0.5)) < 1e-9)
  assert.ok(Math.abs(r.width - ((2 / 6) * 0.5)) < 1e-9)
  assert.equal(r.top, 0.2)
  assert.equal(r.height, 0.05)
})

test('estimateMatchRects ASCII 与 CJK 混排', () => {
  // A=0.55, 1=0.55, 中=1, 文=1 → total=3.1
  const rects = estimateMatchRects('A1中文', '中文', { left: 0.1, top: 0.2, width: 0.5, height: 0.05 })
  assert.equal(rects.length, 1)
  const r = rects[0]
  assert.ok(Math.abs(r.left - (0.1 + (1.1 / 3.1) * 0.5)) < 1e-9)
  assert.ok(Math.abs(r.width - ((2 / 3.1) * 0.5)) < 1e-9)
})

test('matchTextItemRects 单条目命中', () => {
  const rects = matchTextItemRects([
    { text: '正文', left: 0.1, top: 0.2, width: 0.2, height: 0.05 },
    { text: '其他', left: 0.4, top: 0.2, width: 0.2, height: 0.05 },
  ], '正文')
  assert.equal(rects.length, 1)
  const r = rects[0]
  assert.ok(Math.abs(r.left - 0.1) < 1e-9)
  assert.ok(Math.abs(r.top - 0.2) < 1e-9)
  assert.ok(Math.abs(r.width - 0.2) < 1e-9)
  assert.ok(Math.abs(r.height - 0.05) < 1e-9)
})

test('matchTextItemRects 跨条目命中合并外接矩形', () => {
  const rects = matchTextItemRects([
    { text: 'foo', left: 0.1, top: 0.2, width: 0.1, height: 0.05 },
    { text: 'bar', left: 0.2, top: 0.2, width: 0.1, height: 0.05 },
    { text: 'x', left: 0.5, top: 0.2, width: 0.05, height: 0.05 },
  ], 'foobar')
  assert.equal(rects.length, 1)
  const r = rects[0]
  assert.ok(Math.abs(r.left - 0.1) < 1e-9)
  assert.ok(Math.abs(r.top - 0.2) < 1e-9)
  assert.ok(Math.abs(r.width - 0.2) < 1e-9)
  assert.ok(Math.abs(r.height - 0.05) < 1e-9)
})

test('insetWordRects 纵向内缩并上下居中', () => {
  const rects = insetWordRects([
    { left: 0.1, top: 0.2, width: 0.2, height: 0.05 },
  ])
  assert.equal(rects.length, 1)
  const r = rects[0]
  const inset = (0.05 * (1 - 0.76)) / 2
  assert.ok(Math.abs(r.left - 0.1) < 1e-9)
  assert.ok(Math.abs(r.top - (0.2 + inset)) < 1e-9)
  assert.ok(Math.abs(r.width - 0.2) < 1e-9)
  assert.ok(Math.abs(r.height - (0.05 - inset * 2)) < 1e-9)
})

test('buildPrintedPageLabels page_number 优先并回退页次', () => {
  const nodes = [
    { block_type: 'page_number', plain_text: '第 3 页', page_idx: 2 },
    { block_type: 'page_footer', plain_text: '5', page_idx: 4 },
    { block_type: 'paragraph', plain_text: '正文', page_idx: 1 },
  ]
  const extract = (text) => {
    const m = text.match(/第\s*(\d+)\s*页/)
    if (m) return m[1]
    const m2 = text.match(/^\s*(\d+)\s*$/)
    if (m2) return m2[1]
    return null
  }
  assert.deepEqual(buildPrintedPageLabels(nodes, extract), {
    0: '1', 1: '2', 2: '3', 3: '4', 4: '5',
  })
})
