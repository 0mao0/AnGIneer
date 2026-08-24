import { test } from 'node:test'
import assert from 'node:assert/strict'
import { highlightText, escapeHtml } from '../src/utils/tree.ts'

test('高亮：转义标题中的 HTML，避免 XSS', () => {
  const out = highlightText('<img src=x onerror=alert(1)>', 'img')
  assert.equal(out.includes('<mark>'), true)
  assert.equal(out.includes('<img'), false)
  assert.equal(out.includes('<mark>img</mark>'), true)
})

test('高亮：无关键词时仅转义文本', () => {
  assert.equal(highlightText('<script>alert(1)</script>', ''), '&lt;script&gt;alert(1)&lt;/script&gt;')
})

test('高亮：正则特殊字符按字面匹配', () => {
  assert.equal(highlightText('a+b (c)', 'a+b'), '<mark>a+b</mark> (c)')
})

test('高亮：大小写不敏感', () => {
  assert.equal(highlightText('Hello World', 'hello'), '<mark>Hello</mark> World')
})

test('escapeHtml：转义全部特殊字符', () => {
  assert.equal(escapeHtml(`&<>"'`), '&amp;&lt;&gt;&quot;&#39;')
})
