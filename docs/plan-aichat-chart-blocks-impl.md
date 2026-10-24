# aichat 回答图表化实施计划（angineer 块协议 v1）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** AI 回答里的数据类内容以图表呈现——模型按协议输出 ```angineer-chart / ```angineer-map fenced 块，前端拦截渲染成 ECharts 图 / GIS 占位卡片；评测判分剥块不受噪声。

**Architecture:** 块随 answer 文本走全链路（SSE/落库/回灌零改动）；前端在现有自研 markdown 状态机的 fence 分派点拦截 angineer 前缀块；渲染用 v-html 后处理挂载 echarts；评测在 suite_runner 判分派发前对判分副本剥块。

**Tech Stack:** TypeScript + node:test/tsx（aichat-ui）、echarts ^6.1.0（admin-web 已有同版）、Python pytest（angineer-core/evals-core）。

**设计真相源:** `docs/plan-aichat-chart-blocks.md`。本计划落地时的一处形态修正：设计 §2.2 的 `ChartBlock.vue` 改为 **`utils/chartBlock.ts`**（v-html 输出不经 Vue 编译，纯 TS 后处理挂载更贴合现有管线，且少一层动态组件复杂度）。

**探索期已确认的关键事实（执行者不必重查）：**

| 事实 | 位置 |
|---|---|
| markdown 状态机 fence 开/闭行 | `packages/aichat-ui/src/utils/markdown.ts:240-255`（闭块）、`:354-357`（EOF 未闭合） |
| 现状开块**不保存** info-string，闭块一律出 `<pre>` | 同上，需本次加 `codeBlockLang` |
| 测试框架 node:test + tsx，脚本清单在 package.json test | `packages/aichat-ui/package.json` scripts.test |
| BaseChat 滚动容器 ref = `messagesRef`（line 20 `.chat-messages`） | `packages/aichat-ui/src/components/BaseChat.vue` |
| BaseChat markdown 渲染 = 宿主注入 `props.renderMessage`（AIChat.vue:274 调 `renderMarkdownToHtml(content,'')`） | 两处 v-html：BaseChat.vue:161（历史）、:212（流式） |
| QA prompt 版本机制：新版本常量 + `register("agent_configs.qa_system_prompt","v20",…)` 即生效（load 走 latest） | `services/angineer-core/src/angineer_core/prompts/agent_configs.py:382-393` |
| 规则编号已用到 **17**，新规则编 **18** | agent_configs.py（"17. 检索工具为每条证据开头标注了【相关性…"） |
| 判分统一派发点 | `services/evals-core/src/evals_core/runner/suite_runner.py:309`（`evaluator.evaluate(question, gold_data, prediction)`） |
| 剥函数先例（同区放、同测试形态） | `answer_eval.py:28 strip_harness_instruction`；测试先例 `services/evals-core/tests/test_answer_harness_strip.py` |
| echarts 既有版本 ^6.1.0 | `apps/admin-web/package.json:29` |

---

## Task 1: markdown.ts 块扫描（TDD）

**Files:**
- Modify: `packages/aichat-ui/src/utils/markdown.ts`
- Create: `packages/aichat-ui/test/markdown.chart.test.ts`
- Modify: `packages/aichat-ui/package.json`（test 脚本追加该文件）

- [ ] **Step 1: 写失败测试**

创建 `packages/aichat-ui/test/markdown.chart.test.ts`：

```ts
/** angineer 块协议 v1：markdown 渲染器对 ```angineer-chart / ```angineer-map 的拦截。 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { renderMarkdownToHtml } from '../src/utils/markdown'

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
  assert.ok(html.includes('&quot;chartType&quot;'), html)
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
```

- [ ] **Step 2: 把测试文件加进 package.json test 脚本**

`packages/aichat-ui/package.json` 的 `scripts.test` 在清单末尾追加 ` test/markdown.chart.test.ts`：

```json
"test": "pnpm dlx tsx --test test/citation.test.ts test/searchSnippet.test.ts test/thinking.test.ts test/token.test.ts test/markdown.formula.test.ts test/markdown.chart.test.ts test/useAIChat.test.ts test/useAIChat.queue.test.ts test/useAIChat.multi.test.ts"
```

- [ ] **Step 3: 跑测试确认失败**

Run: `pnpm --filter @angineer/aichat-ui test`
Expected: 新增用例 FAIL（无 `angineer-chart-block` 输出），存量用例 PASS。

- [ ] **Step 4: 实现 markdown.ts 块扫描**

`packages/aichat-ui/src/utils/markdown.ts` 三处改动：

① 在 `buildMarkdownTable` 前新增两个渲染函数：

```ts
/** angineer 块协议 v1（docs/plan-aichat-chart-blocks.md）：
 *  ```angineer-chart → data-chart 容器（chartBlock.ts 后处理挂 echarts）
 *  ```angineer-map   → 静态占位卡片（地图渲染未落地，先呈现坐标/属性数据）
 *  只精确匹配这两个 lang，其余（含 angineer-chart2 等）走普通代码块；
 *  坏 JSON 回退 <pre> 原文，不允许渲染链路成为新的失败点。 */
const ANGINEER_BLOCK_LANGS = new Set(['angineer-chart', 'angineer-map'])

const renderAngineerFallback = (raw: string, startLine: number): string =>
  `<div class="angineer-chart-fallback" data-line-start="${startLine}"><div class="angineer-block-note">图表数据格式错误，原文如下</div><pre><code>${escapeHtml(raw)}</code></pre></div>`

const renderAngineerChartBlock = (buffer: string[], startLine: number): string => {
  const raw = buffer.join('\n').trim()
  try {
    const spec = JSON.parse(raw)
    return `<div class="angineer-chart-block" data-line-start="${startLine}" data-chart="${escapeHtmlAttribute(JSON.stringify(spec))}"></div>`
  } catch {
    return renderAngineerFallback(raw, startLine)
  }
}

const renderAngineerMapBlock = (buffer: string[], startLine: number): string => {
  const raw = buffer.join('\n').trim()
  let obj: Record<string, unknown>
  try {
    obj = JSON.parse(raw) as Record<string, unknown>
  } catch {
    return renderAngineerFallback(raw, startLine)
  }
  const title = typeof obj.title === 'string' && obj.title.trim() ? escapeHtml(obj.title.trim()) : '空间数据'
  const desc = typeof obj.description === 'string' && obj.description.trim()
    ? `<div class="angineer-map-desc">${escapeHtml(obj.description.trim())}</div>`
    : ''
  const points = Array.isArray(obj.points) ? obj.points : []
  const rows = points
    .filter((p): p is Record<string, unknown> => !!p && typeof p === 'object')
    .map(p =>
      `<tr><td>${escapeHtml(String(p.name ?? ''))}</td><td>${escapeHtml(String(p.lon ?? ''))}</td><td>${escapeHtml(String(p.lat ?? ''))}</td></tr>`
    )
    .join('')
  const table = rows
    ? `<table><thead><tr><th>名称</th><th>经度</th><th>纬度</th></tr></thead><tbody>${rows}</tbody></table>`
    : ''
  return `<div class="angineer-map-block" data-line-start="${startLine}"><div class="angineer-map-head"><span class="angineer-map-title">${title}</span><span class="angineer-map-badge">地图视图开发中</span></div>${desc}${table}</div>`
}
```

② `renderMarkdownToHtml` 状态区（`let codeBlockStartLine = -1` 之后）加一行：

```ts
let codeBlockLang = ''
```

③ fence 开/闭分派（原 `if (trimmed.startsWith('```'))` 分支）改为：

```ts
    if (trimmed.startsWith('```')) {
      if (inCodeBlock) {
        inCodeBlock = false
        const code = codeBlockBuffer.join('\n')
        if (codeBlockLang === 'angineer-chart') {
          htmlBlocks.push(renderAngineerChartBlock(codeBlockBuffer, codeBlockStartLine))
        } else if (codeBlockLang === 'angineer-map') {
          htmlBlocks.push(renderAngineerMapBlock(codeBlockBuffer, codeBlockStartLine))
        } else {
          htmlBlocks.push(`<pre data-line-start="${codeBlockStartLine}"><code>${escapeHtml(code)}</code></pre>`)
        }
        codeBlockBuffer = []
        codeBlockStartLine = -1
        codeBlockLang = ''
      } else {
        closeLists()
        flushParagraph()
        flushTable()
        inCodeBlock = true
        codeBlockStartLine = currentLineNumber
        codeBlockLang = trimmed.slice(3).trim().toLowerCase()
      }
      continue
    }
```

④ EOF 未闭合分支（原 `if (inCodeBlock) {` 尾部，line 354 附近）改为：

```ts
  if (inCodeBlock) {
    if (codeBlockLang === 'angineer-chart' || codeBlockLang === 'angineer-map') {
      htmlBlocks.push(`<div class="angineer-chart-pending" data-line-start="${codeBlockStartLine}">图表生成中…</div>`)
    } else {
      const code = codeBlockBuffer.join('\n')
      htmlBlocks.push(`<pre data-line-start="${codeBlockStartLine}"><code>${escapeHtml(code)}</code></pre>`)
    }
  }
```

- [ ] **Step 5: 跑测试确认全绿**

Run: `pnpm --filter @angineer/aichat-ui test`
Expected: 全部 PASS（含 8 个存量文件）。

- [ ] **Step 6: Commit**

```bash
git add packages/aichat-ui/src/utils/markdown.ts packages/aichat-ui/test/markdown.chart.test.ts packages/aichat-ui/package.json
git commit -m "feat(aichat-ui): markdown 渲染拦截 angineer-chart/map 块——占位/回退/普通代码块隔离（图表化 T1）"
```

---

## Task 2: chartBlock.ts（echarts 按需渲染 + 暗色）

**Files:**
- Create: `packages/aichat-ui/src/utils/chartBlock.ts`
- Modify: `packages/aichat-ui/package.json`（dependencies 加 echarts）

- [ ] **Step 1: 加依赖**

`packages/aichat-ui/package.json` 的 `dependencies` 加（与 admin-web 同版，echarts 无宿主框架耦合，同 katex 放 dependencies 先例）：

```json
"echarts": "^6.1.0"
```

Run: `pnpm install`
Expected: lockfile 更新，安装成功。

- [ ] **Step 2: 实现 chartBlock.ts**

创建 `packages/aichat-ui/src/utils/chartBlock.ts`：

```ts
/** angineer 图表块渲染器（v1）：v-html 后处理挂载 echarts。
 *  为什么不是 Vue 组件：markdown 输出走 v-html（不经 Vue 编译），
 *  在容器上后处理 querySelector 挂载是最贴合现有管线的方式。
 *  流式期间块未闭合时 markdown 层只出 pending 占位；闭合后 v-html 重建 DOM，
 *  本模块每次调用只挂「未挂载」的块，并 dispose 已脱离文档的旧实例（防泄漏）。 */
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { EChartsType } from 'echarts/core'

echarts.use([BarChart, LineChart, PieChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

export interface AngineerChartSpec {
  chartType: 'bar' | 'line' | 'pie'
  title: string
  categories?: string[]
  series?: Array<{ name?: string; data?: number[]; value?: number }>
  unit?: string
  source?: string
}

const LIGHT_PALETTE = ['#5b8ff9', '#61ddaa', '#f6bd16', '#7262fd', '#78d3f8', '#9661bc']
const DARK_PALETTE = ['#5b8ff9', '#61ddaa', '#f6bd16', '#7262fd', '#78d3f8', '#9661bc']

const isDark = (): boolean =>
  typeof document !== 'undefined' &&
  (document.documentElement.classList.contains('dark') || document.documentElement.dataset.theme === 'dark')

const activeInstances = new Set<{ chart: EChartsType; dom: HTMLElement }>()

const buildOption = (spec: AngineerChartSpec, dark: boolean): echarts.EChartsCoreOption => {
  const axisColor = dark ? 'rgba(255,255,255,0.65)' : 'rgba(0,0,0,0.65)'
  const splitColor = dark ? 'rgba(255,255,255,0.12)' : 'rgba(0,0,0,0.08)'
  const textStyle = { color: dark ? 'rgba(255,255,255,0.85)' : 'rgba(0,0,0,0.88)' }
  const legend = spec.series && spec.series.length > 1
    ? { bottom: 0, textStyle: { color: axisColor } }
    : undefined
  if (spec.chartType === 'pie') {
    const data = (spec.series || []).map(s => ({ name: String(s.name ?? ''), value: Number(s.value ?? 0) }))
    return {
      backgroundColor: 'transparent',
      color: dark ? DARK_PALETTE : LIGHT_PALETTE,
      textStyle,
      title: { text: spec.title, left: 'center', textStyle: { color: textStyle.color, fontSize: 14 } },
      tooltip: { trigger: 'item' },
      legend,
      series: [{ type: 'pie', radius: ['38%', '66%'], center: ['50%', '54%'], data }],
    }
  }
  return {
    backgroundColor: 'transparent',
    color: dark ? DARK_PALETTE : LIGHT_PALETTE,
    textStyle,
    title: { text: spec.title, left: 'center', textStyle: { color: textStyle.color, fontSize: 14 } },
    tooltip: { trigger: 'axis' },
    legend,
    grid: { left: 48, right: 24, top: 40, bottom: legend ? 48 : 28, containLabel: false },
    xAxis: { type: 'category', data: spec.categories || [], axisLabel: { color: axisColor }, axisLine: { lineStyle: { color: splitColor } } },
    yAxis: {
      type: 'value',
      name: spec.unit || '',
      nameTextStyle: { color: axisColor },
      axisLabel: { color: axisColor },
      splitLine: { lineStyle: { color: splitColor } },
    },
    series: (spec.series || []).map(s => ({
      type: spec.chartType === 'line' ? 'line' : 'bar',
      name: String(s.name ?? ''),
      data: Array.isArray(s.data) ? s.data : [],
      smooth: spec.chartType === 'line',
    })),
  }
}

const mountOne = (el: HTMLElement): void => {
  const attr = el.getAttribute('data-chart')
  if (!attr) return
  let spec: AngineerChartSpec
  try {
    spec = JSON.parse(attr) as AngineerChartSpec
  } catch {
    el.textContent = '图表数据格式错误'
    return
  }
  if (!spec || typeof spec.chartType !== 'string') {
    el.textContent = '图表数据不完整'
    return
  }
  const chart = echarts.init(el)
  chart.setOption(buildOption(spec, isDark()))
  activeInstances.add({ chart, dom: el })
  el.setAttribute('data-mounted', '1')
}

/** 扫描 root 内未挂载的 angineer 图表块并挂载；先回收已脱离文档的旧实例。 */
export const mountChartBlocks = (root: HTMLElement): void => {
  for (const item of [...activeInstances]) {
    if (!document.contains(item.dom)) {
      item.chart.dispose()
      activeInstances.delete(item)
    }
  }
  if (!root.querySelector('.angineer-chart-block')) return
  root.querySelectorAll<HTMLElement>('.angineer-chart-block[data-chart]').forEach(el => {
    if (el.getAttribute('data-mounted')) return
    mountOne(el)
  })
}

let themeObserverStarted = false

/** 主题切换重上色：宿主暗色双形态（html.dark 类 / data-theme 属性，见 styles/index.less 注释）。 */
export const startChartThemeObserver = (): void => {
  if (themeObserverStarted || typeof document === 'undefined') return
  themeObserverStarted = true
  const observer = new MutationObserver(() => {
    const dark = isDark()
    for (const item of activeInstances) {
      const attr = item.dom.getAttribute('data-chart')
      if (!attr) continue
      try {
        item.chart.setOption(buildOption(JSON.parse(attr) as AngineerChartSpec, dark))
      } catch {
        /* spec 已在挂载时校验过，防御性忽略 */
      }
    }
  })
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class', 'data-theme'] })
}
```

- [ ] **Step 3: typecheck**

Run: `pnpm --filter @angineer/aichat-ui typecheck`
Expected: 通过。

- [ ] **Step 4: Commit**

```bash
git add packages/aichat-ui/src/utils/chartBlock.ts packages/aichat-ui/package.json pnpm-lock.yaml
git commit -m "feat(aichat-ui): chartBlock 渲染器——echarts 按需引入 bar/line/pie、暗色双选择器、脱离文档实例回收（图表化 T2）"
```

---

## Task 3: BaseChat.vue 接线 + 样式

**Files:**
- Modify: `packages/aichat-ui/src/components/BaseChat.vue`
- Modify: `packages/aichat-ui/src/styles/index.less`

- [ ] **Step 1: BaseChat.vue 接线**

① script 里 import（与现有 import 区并列）：

```ts
import { mountChartBlocks, startChartThemeObserver } from '../utils/chartBlock'
```

② 滚动容器（line 20 `<div ref="messagesRef" class="chat-messages" ...>`）挂载后处理。在现有 `messagesRef` 声明附近加：

```ts
let chartRemountTimer: ReturnType<typeof setTimeout> | undefined
const scheduleChartMount = () => {
  if (chartRemountTimer) clearTimeout(chartRemountTimer)
  // 流式 delta 高频重建 v-html，debounce 后只挂一次；echarts init ~几十 ms，150ms 足够收敛
  chartRemountTimer = setTimeout(() => {
    nextTick(() => {
      const root = messagesRef.value
      if (root) mountChartBlocks(root)
    })
  }, 150)
}
```

③ 生命周期接线（与现有 onMounted/watch 区并列；`messages`、`currentStreamContent` 是已有 props 名——若实际 props 名不同以文件内现有 watch 为准，见 line 1344 `watch(() => props.currentStreamContent, ...)`）：

```ts
onMounted(() => {
  startChartThemeObserver()
  scheduleChartMount()
})
onBeforeUnmount(() => {
  if (chartRemountTimer) clearTimeout(chartRemountTimer)
})
watch(
  () => [props.currentStreamContent, props.messages?.length],
  () => scheduleChartMount()
)
```

若 `props.messages` 名不同（以 `displayMessages` 计算属性源为准），用同一来源。历史消息分支（line 161）在 `messages` 变化时同样触发。

- [ ] **Step 2: 样式**

`packages/aichat-ui/src/styles/index.less` 末尾追加：

```less
/* angineer 图表块（协议 v1，docs/plan-aichat-chart-blocks.md）：echarts 容器与 GIS 占位卡片 */
.angineer-chart-block {
  width: 100%;
  height: 280px;
  margin: 8px 0;
}

.angineer-chart-pending {
  margin: 8px 0;
  padding: 40px 0;
  text-align: center;
  color: var(--chat-system-text, #8c8c8c);
  background: var(--chat-pre-bg, rgba(0, 0, 0, 0.03));
  border-radius: 8px;
  font-size: 13px;
}

.angineer-chart-fallback {
  margin: 8px 0;
  .angineer-block-note {
    font-size: 12px;
    color: var(--chat-system-text, #8c8c8c);
    margin-bottom: 4px;
  }
}

.angineer-map-block {
  margin: 8px 0;
  padding: 12px;
  border: 1px solid var(--chat-system-border, #d9d9d9);
  border-radius: 8px;
  font-size: 13px;
  .angineer-map-head {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .angineer-map-title {
    font-weight: 600;
  }
  .angineer-map-badge {
    font-size: 12px;
    padding: 0 6px;
    border-radius: 4px;
    color: var(--chat-citation-accent, #177ddc);
    background: var(--chat-citation-bg, #f0f5ff);
  }
  .angineer-map-desc {
    color: var(--chat-system-text, #8c8c8c);
    margin: 4px 0 8px;
  }
  table {
    width: 100%;
  }
}
```

- [ ] **Step 3: typecheck + 全量测试**

Run: `pnpm --filter @angineer/aichat-ui typecheck && pnpm --filter @angineer/aichat-ui test`
Expected: 全绿。

- [ ] **Step 4: 手测（本地 dev）**

Run: `pnpm --filter @angineer/user-web dev`（配好后端见记忆 local-chat-e2e-recipe-1014：login admin/admin1）
手测清单：
1. 往对话发一条含完整 angineer-chart 块的文本（可用测试消息直接粘贴 markdown）→ 柱状图渲染、悬停 tooltip 正常
2. 同法测 pie/line
3. 切暗色主题 → 图表配色随动、文字可读
4. 发一条普通 ```json 块 → 照旧 `<pre>` 展示
5. 粘贴坏 JSON 块 → 回退原文展示

- [ ] **Step 5: Commit**

```bash
git add packages/aichat-ui/src/components/BaseChat.vue packages/aichat-ui/src/styles/index.less
git commit -m "feat(aichat-ui): BaseChat 接线图表块挂载（debounce+脱离文档回收）+ 块容器样式双主题（图表化 T3）"
```

---

## Task 4: QA prompt v20（规则 18 图表化交付）

**Files:**
- Modify: `services/angineer-core/src/angineer_core/prompts/agent_configs.py`
- Create: `services/angineer-core/tests/test_qa_prompt_chart_rule.py`

- [ ] **Step 1: 写失败测试**

创建 `services/angineer-core/tests/test_qa_prompt_chart_rule.py`：

```python
"""QA prompt v20：规则 18 图表化交付（docs/plan-aichat-chart-blocks.md）。"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "services" / "angineer-core" / "src"))

from angineer_core.prompts import load  # noqa: E402


def test_latest_is_v20_and_contains_chart_rule():
    text = load("agent_configs.qa_system_prompt")
    assert "angineer-chart" in text
    assert "angineer-map" in text
    assert "18." in text


def test_v20_starts_with_v19_and_rule18_is_last():
    from angineer_core.prompts.agent_configs import QA_AGENT_SYSTEM_PROMPT_V19, QA_AGENT_SYSTEM_PROMPT_V20

    assert QA_AGENT_SYSTEM_PROMPT_V20.startswith(QA_AGENT_SYSTEM_PROMPT_V19)
    assert "18." not in QA_AGENT_SYSTEM_PROMPT_V19
```

Run: `python -m pytest services/angineer-core/tests/test_qa_prompt_chart_rule.py -v`
Expected: FAIL（latest 仍是 v19、无 v20 常量）。

- [ ] **Step 2: 实现 v20**

`services/angineer-core/src/angineer_core/prompts/agent_configs.py`：在 V19 定义块之后（`assert QA_AGENT_SYSTEM_PROMPT_V19 != ...` 之后、「当前版本别名」注释之前）插入：

```python
# v20（2026-10-24）：新增规则 18 图表化交付——数据类回答（多行对比/聚合/趋势/占比）在
# markdown 表格后附 ```angineer-chart 块，前端拦截渲染成 ECharts 图；空间数据用
# angineer-map 块（前端占位卡片，地图渲染未落地）。设计：docs/plan-aichat-chart-blocks.md。
# 边界：只允许证据中的具体数值（同规则 8 引用契约，source 逐字照抄 cite 值）；
# 纯概念/条文类回答不得出块。模型遵从度风险见 2026-09-21 失败留档——上线后按
# 本地 E2E + 生产观察迭代措辞，括号令牌教训勿复犯（本规则给的是完整 JSON 样例非抽象令牌）。
_QA_RULE18_CHART = (
    "18. 图表化交付：回答涉及多行数据对比/聚合/趋势/占比，且证据中存在具体数值时，"
    "先用 Markdown 表格列出明细；若数据适合图形表达（趋势/占比/对比），在表格后紧跟一个代码块，"
    "语言标记为 angineer-chart，块内是一个合法 JSON 对象，格式示例：\n"
    '{"chartType":"bar","title":"逐年吞吐量","categories":["2023","2024"],'
    '"series":[{"name":"吞吐量","data":[120,156]}],"unit":"万吨","source":"K1"}\n'
    "字段约定：chartType 取 bar/line/pie；bar/line 必填 categories 与 series[].data；"
    "pie 时 series 用 {\"name\",\"value\"} 形式；source 填对应证据的 cite 标记值（逐字照抄，同规则 8）。"
    "禁止编造证据中不存在的数值；图表数值必须与表格和正文一致；每次回答最多 2 个图表块。"
    "证据含坐标/空间分布数据时，可另用语言标记 angineer-map 的代码块输出 "
    "{\"title\":\"...\",\"description\":\"...\",\"points\":[{\"name\":\"...\",\"lon\":121.5,\"lat\":31.2}]}。"
    "没有具体数值、纯概念/条文/拒答类回答，不要输出任何图表块。\n"
)
QA_AGENT_SYSTEM_PROMPT_V20 = QA_AGENT_SYSTEM_PROMPT_V19 + _QA_RULE18_CHART
assert QA_AGENT_SYSTEM_PROMPT_V20.startswith(QA_AGENT_SYSTEM_PROMPT_V19), "v20 追加未命中（v19 内容漂移）"
```

`register` 清单（line 393 后）追加一行：

```python
register("agent_configs.qa_system_prompt", "v20", QA_AGENT_SYSTEM_PROMPT_V20)
```

文件头 docstring 的版本行同步：`版本 QA v17 / COMPLEX v5 / followup v3` 改为 `版本 QA v20 / COMPLEX v5 / followup v3`，并补一行最后变更说明（2026-10-24 v20 规则 18 图表化交付）。

- [ ] **Step 3: 跑测试确认全绿 + 存量回归**

Run: `python -m pytest services/angineer-core/tests/test_qa_prompt_chart_rule.py services/angineer-core/tests -v -k "prompt"`
Expected: PASS。再跑全量 `python -m pytest services/angineer-core/tests -q`（生产行为改动面＝prompt 追加一条规则，存量用例不应受影响）。

- [ ] **Step 4: 本地 E2E 验证模型遵从度（必做，2026-09-21 教训）**

后端起本地 dev 后，发数据类问题（选知识库里确有数值表格的库，如财务/水文库）：
1. 数据题（「近三年营收对比」类）→ 回答应含 markdown 表格 + angineer-chart 块，前端出图
2. 纯条文题（「XX 规范第几条」类）→ 回答不含任何 angineer 块（负向验证）
3. 块内 source 标记与回答引用标记一致、能在证据里找到

- [ ] **Step 5: Commit**

```bash
git add services/angineer-core/src/angineer_core/prompts/agent_configs.py services/angineer-core/tests/test_qa_prompt_chart_rule.py
git commit -m "feat(angineer-core): QA prompt v20 规则 18 图表化交付——数据题表格后附 angineer-chart/map 块，数值必须来自证据（图表化 T4）"
```

---

## Task 5: 评测判分剥块

**Files:**
- Modify: `services/evals-core/src/evals_core/runner/answer_eval.py`
- Modify: `services/evals-core/src/evals_core/runner/suite_runner.py`
- Create: `services/evals-core/tests/test_answer_angineer_strip.py`

- [ ] **Step 1: 写失败测试**

创建 `services/evals-core/tests/test_answer_angineer_strip.py`（照 test_answer_harness_strip.py 先例）：

```python
"""answer_eval：angineer 图表块剥离——判分只消费语义内容，JSON 块是噪声。"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "services" / "evals-core" / "src"))

from evals_core.runner.answer_eval import strip_angineer_blocks  # noqa: E402


def test_strip_closed_chart_block():
    text = "对比结论如下 [K1]。\n\n```angineer-chart\n{\"chartType\":\"bar\",\"series\":[]}\n```\n\n补充说明 [K2]。"
    assert strip_angineer_blocks(text) == "对比结论如下 [K1]。\n\n\n\n补充说明 [K2]。"


def test_strip_unclosed_chart_block_tail():
    text = "结论 [K1]。\n\n```angineer-chart\n{\"chartType\":\"bar\""
    assert strip_angineer_blocks(text) == "结论 [K1]。"


def test_keep_normal_answer_and_tables():
    text = "| 年 | 值 |\n|---|---|\n| 2023 | 120 |\n\n普通 ```json {\"a\":1}``` 保留。"
    assert strip_angineer_blocks(text) == text
```

Run: `python -m pytest services/evals-core/tests/test_answer_angineer_strip.py -v`
Expected: FAIL（函数不存在）。

- [ ] **Step 2: 实现 strip_angineer_blocks**

`services/evals-core/src/evals_core/runner/answer_eval.py` 在 `strip_harness_instruction` 定义之后加：

```python
# angineer 图表块（回答交付物 v1，docs/plan-aichat-chart-blocks.md）：判分只消费语义内容，
# 块内 JSON 对 LLM 判官是噪声；markdown 表格文本保留。第二分支兜底剥「开了未闭合」的尾巴
# （流式中断的 answer 也可能进判分）。与 strip_harness_instruction 同区维护。
_ANGINEER_BLOCK_RE = re.compile(r"```angineer-(?:chart|map)\b[\s\S]*?```|```angineer-(?:chart|map)\b[\s\S]*$", re.I)


def strip_angineer_blocks(text: str) -> str:
    return _ANGINEER_BLOCK_RE.sub("", str(text or "")).strip()
```

- [ ] **Step 3: suite_runner 判分派发点接入（判分副本，原文留痕不动）**

`services/evals-core/src/evals_core/runner/suite_runner.py` line 309 附近改为：

```python
        prediction = last_prediction
        # 判分输入剥 angineer 图表块（v1）：JSON 块对判官是噪声；落库留痕的 prediction 原文不动。
        judge_prediction = dict(prediction)
        if isinstance(judge_prediction.get("answer"), str):
            judge_prediction["answer"] = strip_angineer_blocks(judge_prediction["answer"])
        scores = evaluator.evaluate(question, gold_data, judge_prediction)
```

文件头 import 区（已有 `from evals_core.runner.answer_eval import AnswerEvaluator`）加：

```python
from evals_core.runner.answer_eval import strip_angineer_blocks
```

Run: `python -m pytest services/evals-core/tests/test_answer_angineer_strip.py services/evals-core/tests -q`
Expected: 全绿（含 harness_strip 存量）。

- [ ] **Step 4: Commit**

```bash
git add services/evals-core/src/evals_core/runner/answer_eval.py services/evals-core/src/evals_core/runner/suite_runner.py services/evals-core/tests/test_answer_angineer_strip.py
git commit -m "feat(evals-core): 判分输入剥 angineer 图表块——判分副本处理、prediction 原文留痕不动（图表化 T5）"
```

---

## Task 6: 全量验证

- [ ] **Step 1: 前端全量**

Run: `pnpm -r typecheck && pnpm -r test`
Expected: 全绿（aichat-ui 新测试 + 双端 typecheck）。

- [ ] **Step 2: 双端 build**

Run: `pnpm --filter @angineer/user-web build && pnpm --filter @angineer/admin-web build`
Expected: 成功；对比 build 前 `dist/assets` 体积，echarts 按需引入后增量应 <400KB（gzip 前手动核一眼，超了查是否误引全量 `import * as echarts from 'echarts'`）。

- [ ] **Step 3: Python 全量**

Run: `python -m pytest services/angineer-core/tests services/evals-core/tests -q`
Expected: 全绿。

- [ ] **Step 4: 端到端冒烟（Task 4 Step 4 已做的三条若已过，此步合并记账即可）**

- 数据题出图（bar）✓ / 纯文本题无块 ✓ / source 标记与证据一致 ✓

- [ ] **Step 5: 汇总报告（不自动 push，push 须用户明令）**

报告内容：各 Task commit 清单、echarts 体积增量、E2E 三条结果、遗留（S2 立项、地图渲染待立项）。
