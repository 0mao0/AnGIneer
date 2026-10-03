import { test } from 'node:test'
import assert from 'node:assert/strict'
import { register } from 'node:module'

// katex ESM 会 import './katex.min.css'，node 无 css 加载器（vite 构建不受影响）。
// 用 node:module register 把 .css 短路为空模块，必须在动态 import markdown.ts 之前完成。
register('./css-loader.mjs', import.meta.url)
const { renderFormula, renderMarkdownInlineToHtml } = await import('../src/utils/markdown.ts')

// 2026-10-04 occamy 实测（生产会话 chat-musnnodn-qc733j）：模型照抄规范原文
// `Z_c = EHWL + R_{1%} + Δ`（JTS 165-2013 记法），裸文本自动公式化后 `%` 被 KaTeX
// 当注释符 → 解析报错、整条公式渲染成红字（throwOnError:false 的错误态）。
// renderFormula 归一化把未转义 % 统一转 \%（KaTeX 渲染为字面 %），转义后实证干净。

test('规范原文 R_{1%} 不再触发 KaTeX 错误态', () => {
  const html = renderFormula('R_{1%}', false)
  assert.ok(html.includes('katex'), '应走 KaTeX 渲染路径')
  assert.ok(!html.includes('katex-error'), '不应出现 KaTeX 错误红字')
})

test('真实公式行 Z_c = EHWL + R_{1%} + \\Delta 渲染干净', () => {
  const html = renderFormula('Z_c = EHWL + R_{1%} + \\Delta', false)
  assert.ok(!html.includes('katex-error'))
})

test('模型已写对的 \\% 不重复转义', () => {
  const html = renderFormula('Z_c = EHWL + R_{1\\%} + \\Delta', false)
  assert.ok(!html.includes('katex-error'))
  // 双转义会渲染出字面反斜杠（KaTeX 里 \\ 是换行命令，会报错或出残留）
  assert.ok(!/\\\\/.test(html), 'HTML 中不应出现双反斜杠残留')
})

test('端到端：回答行经内联渲染后无红字兜底', () => {
  const html = renderMarkdownInlineToHtml('Z_c = EHWL + R_{1%} + Δ', '')
  assert.ok(!html.includes('katex-error'), '不应出现 KaTeX 错误红字')
  assert.ok(!html.includes('math-inline-fallback'), '不应落到裸文本兜底')
})
