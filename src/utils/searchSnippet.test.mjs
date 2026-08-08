import assert from 'node:assert/strict'
import test from 'node:test'

import { renderSearchSnippetHtml } from './searchSnippet.ts'

test('剥离 HTML 标签并保留文本', () => {
  const html = renderSearchSnippetHtml('地址<sub>：</sub>100736', '地址')
  assert.ok(html.includes('<mark class="search-hit">地址</mark>'))
  assert.ok(html.includes('：100736'))
  assert.ok(!html.includes('<sub>'))
})

test('数学段渲染为 Katex 并高亮命中公式', () => {
  const html = renderSearchSnippetHtml('$F = ma$', 'F')
  assert.ok(html.includes('katex'))
  assert.ok(html.includes('<mark class="search-hit">'))
  assert.ok(!html.includes('$F = ma$'))
})

test('命中词在公式内时整段公式高亮', () => {
  const html = renderSearchSnippetHtml('$140 < A \\leqslant 400$', 'leqslant')
  assert.ok(html.includes('<mark class="search-hit">'))
  assert.ok(html.includes('katex'))
})

test('文本转义防注入', () => {
  const html = renderSearchSnippetHtml('<script>alert(1)</script>', 'x')
  assert.ok(!html.includes('<script>'))
  assert.ok(html.includes('alert(1)'))
})

test('带 <sub> 的公式不被标签剥离破坏', () => {
  const html = renderSearchSnippetHtml('A<sub>1</sub> = $x^2$', 'x')
  assert.ok(!html.includes('<sub>'))
  assert.ok(html.includes('katex'))
  assert.ok(html.includes('A1 ='))
})
