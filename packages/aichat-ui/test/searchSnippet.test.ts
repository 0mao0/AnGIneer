import { test } from 'node:test'
import assert from 'node:assert/strict'

import { renderSearchSnippetHtml } from '../src/utils/searchSnippet.ts'

test('行内公式用 KaTeX 渲染，不残留 $ 定界符', () => {
  const html = renderSearchSnippetHtml('设计波高 $H_{1\\%}$ 与周期 $T$ 的关系', '')
  assert.match(html, /class="katex"/)
  assert.ok(!html.includes('$H_{1\\%}$'), '行内公式不应保留原始 $ 文本')
  assert.ok(!html.includes('$T$'))
})

test('块级公式 $$...$$ 走 display 模式', () => {
  const html = renderSearchSnippetHtml('公式如下：$$E = m c^2$$ 结束', '')
  assert.match(html, /class="katex-display"/)
  assert.ok(!html.includes('$$'))
})

test('普通文本按查询词高亮并剥离 HTML 标签', () => {
  const html = renderSearchSnippetHtml('上航数联与<b>上海航道</b>的通航条件', '上航数联')
  assert.match(html, /<mark class="search-hit">上航数联<\/mark>/)
  assert.ok(!html.includes('<b>'), 'HTML 标签应被剥离')
  assert.match(html, /上海航道/)
})

test('公式命中查询词时整体高亮', () => {
  const html = renderSearchSnippetHtml('流速 $v_0$ 与 $v_1$', 'v_0')
  assert.match(html, /<mark class="search-hit"><span class="katex">/)
})

test('空文本返回空字符串', () => {
  assert.equal(renderSearchSnippetHtml('', 'x'), '')
})
