/** angineer 块协议 v1：markdown 渲染器对 ```angineer-chart / ```angineer-map 的拦截。 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { register } from 'node:module'

// katex ESM 会 import './katex.min.css'，node 无 css 加载器（vite 构建不受影响）。
// 用 node:module register 把 .css 短路为空模块，必须在动态 import markdown.ts 之前完成
// （与 markdown.formula.test.ts 同法）。
register('./css-loader.mjs', import.meta.url)
const { renderMarkdownToHtml } = await import('../src/utils/markdown.ts')

test('闭合 angineer-chart 块输出 data-chart 容器', () => {
  const spec = { chartType: 'bar', title: '逐年吞吐量', categories: ['2023', '2024'], series: [{ name: '吞吐量', data: [120, 156] }] }
  const md = `前文 [K1]。\n\n\`\`\`angineer-chart\n${JSON.stringify(spec)}\n\`\`\`\n`
  const html = renderMarkdownToHtml(md, '')
  assert.ok(html.includes('class="angineer-chart-block"'), html)
  const attr = html.match(/data-chart="([^"]*)"/)
  assert.ok(attr, '缺 data-chart 属性')
  const parsed = JSON.parse(attr![1].replace(/&amp;/g, '&').replace(/&quot;/g, '"'))
  assert.equal(parsed.chartType, 'bar')
  assert.deepEqual(parsed.series[0].data, [120, 156])
})

test('流式未闭合块输出生成中占位', () => {
  const md = '回答中…\n\n```angineer-chart\n{"chartType":"bar"'
  const html = renderMarkdownToHtml(md, '')
  assert.ok(html.includes('angineer-chart-pending'), html)
  assert.ok(html.includes('图表生成中'), html)
})

test('坏 JSON 回退显示原文，不抛异常', () => {
  const md = '```angineer-chart\n{"chartType": broken\n```'
  const html = renderMarkdownToHtml(md, '')
  assert.ok(html.includes('angineer-chart-fallback'), html)
  assert.ok(html.includes('{"chartType": broken'), html)
})

test('普通 json 代码块不受影响', () => {
  const md = '```json\n{"a":1}\n```'
  const html = renderMarkdownToHtml(md, '')
  assert.ok(html.includes('<pre'), html)
  assert.ok(!html.includes('angineer-chart'), html)
})

test('lang 前缀相近的块不误伤（angineer-chart2 走普通代码块）', () => {
  const md = '```angineer-chart2\n{"x":1}\n```'
  const html = renderMarkdownToHtml(md, '')
  assert.ok(html.includes('<pre'), html)
  assert.ok(!html.includes('angineer-chart-block'), html)
})

test('lang 大小写不敏感', () => {
  const spec = { chartType: 'pie', title: '占比', series: [{ name: 'A', value: 60 }, { name: 'B', value: 40 }] }
  const md = '```ANGINEER-CHART\n' + JSON.stringify(spec) + '\n```'
  const html = renderMarkdownToHtml(md, '')
  assert.ok(html.includes('angineer-chart-block'), html)
})

test('angineer-map 块输出占位卡片：标题+角标+坐标表', () => {
  const md = '```angineer-map\n{"title":"疏浚区分布","description":"三个作业区","points":[{"name":"A区","lon":121.5,"lat":31.2}]}\n```'
  const html = renderMarkdownToHtml(md, '')
  assert.ok(html.includes('angineer-map-block'), html)
  assert.ok(html.includes('疏浚区分布'), html)
  assert.ok(html.includes('地图视图开发中'), html)
  assert.ok(html.includes('<td>A区</td>'), html)
  assert.ok(html.includes('<td>121.5</td>'), html)
})

test('map 块坏 JSON 同样回退原文', () => {
  const md = '```angineer-map\nnot json\n```'
  const html = renderMarkdownToHtml(md, '')
  assert.ok(html.includes('angineer-chart-fallback'), html)
})

test('混合内容：表格与 chart 块先后正确分派', () => {
  const spec = { chartType: 'line', title: '趋势', categories: ['1月', '2月'], series: [{ name: '量', data: [1, 2] }] }
  const md = `| 月 | 量 |\n|---|---|\n| 1月 | 1 |\n| 2月 | 2 |\n\n\`\`\`angineer-chart\n${JSON.stringify(spec)}\n\`\`\`\n`
  const html = renderMarkdownToHtml(md, '')
  assert.ok(html.includes('<table'), html)
  assert.ok(html.includes('angineer-chart-block'), html)
})
