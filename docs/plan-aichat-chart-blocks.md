# aichat 回答图表化（angineer 块协议 v1）

- 日期：2026-10-24
- 状态：设计已用户确认，进入实施
- 决策记录：渲染技术＝ECharts + 纯 HTML 混合（用户选定）；触发方式＝prompt 先行，S2 管道只立项不施工（用户选定）；GIS＝预留块协议、本次渲染占位卡片（用户选定）
- 与 LS 路由方案（`docs/plan-ls-routing.md`）的关系：本方案是 §4.5「渲染器按 schema 输出 markdown/表格」的生产化第一步——先让「回答里可以有图/表」这条通路存在；S2（聚合题判定）施工时复用本协议，不另起炉灶

---

## 0. 一页结论

1. 回答内容自包含「angineer 块协议」：模型在 markdown 里输出 ```angineer-chart / ```angineer-map fenced 块，前端拦截渲染成 echarts 图 / GIS 占位卡片。
2. 走 fenced 块而非新 SSE 帧：message_delta 零改动、落库/历史回灌自动重渲、评测判分前剥块即可，全链路自洽。
3. 触发靠 prompt 指令（模型自主判断何时出图）；意图分类捎带 schemas[] 判 S2 是后续独立任务。
4. 明确不做：S2 分类施工、真地图（Leaflet/底图）、bar/line/pie 之外的图型。

---

## 1. 块协议 v1

### 1.1 形态

回答 = markdown 文本（含引用标记 [K/T/E]x）+ 可选 angineer 块。块紧跟在对应 markdown 表格之后（表格是明细、图是趋势/占比的可视化），不单独成段：

````markdown
……逐年吞吐量对比 [K1]。

| 年份 | 吞吐量(万吨) |
|---|---|
| 2023 | 120 |
| 2024 | 156 |

```angineer-chart
{"chartType":"bar","title":"逐年吞吐量","categories":["2023","2024"],
 "series":[{"name":"吞吐量","data":[120,156]}],"unit":"万吨","source":"K1"}
```
````

### 1.2 块类型与 JSON schema

**angineer-chart**（v1 只 bar/line/pie）：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| chartType | string | 是 | `bar` / `line` / `pie` |
| title | string | 是 | 图标题（≤30 字） |
| categories | string[] | bar/line 必填 | x 轴类目（pie 时为扇区名，可并入 series.data） |
| series | array | 是 | `[{name, data:number[]}]`；pie 时 `[{name, value}]` |
| unit | string | 否 | 数值单位（如 万吨、%） |
| source | string | 否 | 引用标记串（如 `K1,K3`），随图显示出处 |

**angineer-map**（GIS 预留，本次只渲染占位）：

| 字段 | 类型 | 说明 |
|---|---|---|
| title | string | 卡片标题 |
| description | string | 一句话说明空间数据内容 |
| points | array | 可选 `[{name, lon, lat, props?}]` 坐标点表 |

前端对 angineer-map 渲染「占位卡片」：标题 + 描述 + 坐标/属性数据表 + 「地图视图开发中」角标。

### 1.3 命名与隔离

- `angineer-` 前缀保证与普通 ```json / ```python 代码块、与模型自拟的 ```chart 不冲突；只有精确匹配 `angineer-chart` / `angineer-map` 的 fence info-string 被拦截。
- 普通 fenced 块渲染行为完全不变。

---

## 2. 前端设计（packages/aichat-ui）

### 2.1 渲染管线

```
回答文本（流式累积 or 历史消息）
 → utils/markdown.ts 逐行扫描
    ├─ 行首 ```angineer-chart 且已闭合 → <div class="angineer-chart-block" data-chart="<URL编码JSON>">
    ├─ 行首 ```angineer-map 且已闭合   → <div class="angineer-map-block" data-map="<URL编码JSON>">
    ├─ ```angineer-* 未闭合（流式中）   → 占位 div「图表生成中…」（不渲染半截 JSON）
    ├─ 块内 JSON.parse 失败 / chartType 不支持 → 回退为该数据的 markdown 表格或 <pre> 原文
    └─ 其它内容 → 现有 markdown 渲染（表格/公式/引用/图片）不变
 → v-html（现有链路）
 → ChartBlock.vue 组件：mounted 时读 data-chart，JSON.parse，echarts 按需 init 渲染
```

要点：

- **流式渐进**：BaseChat 流式期间对累积文本全量重渲（现状即如此），块闭合那一刻自动从占位换成真图，无需额外事件。
- **echarts 按需引入**：`echarts/core` + BarChart/LineChart/PieChart + Grid/Tooltip/Legend 组件 + Canvas 渲染器，控制包体（全量 echarts 约 1MB，按需后显著更小）。
- **主题**：亮暗双套色板；暗色监听宿主 `html.dark` 类与 `[data-theme=dark]` 双选择器（防暗色 token 静默失效老坑，见记忆 dark-token-marker）。切换主题时 `setOption` 重上色。
- **XSS**：块内容只经 `JSON.parse` → echarts（canvas/SVG）渲染，不拼任何 HTML 字符串；data 属性值 URL 编码转义。
- **尺寸**：块宽 100% 气泡宽，高按图型固定（bar/line 约 280px、pie 约 300px），`resize` 监听容器变化。
- **图数上限**：渲染端不设限（prompt 端限 2 张；渲染器对超量照常渲染，信任内容侧约束）。

### 2.2 新增/改动文件

| 文件 | 动作 |
|---|---|
| `packages/aichat-ui/package.json` | 加 `echarts` 依赖 |
| `packages/aichat-ui/src/utils/markdown.ts` | 加 angineer 块扫描与占位/回退输出 |
| `packages/aichat-ui/src/components/ChartBlock.vue` | 新增：echarts 渲染组件（chart+map 占位两种形态） |
| `packages/aichat-ui/src/styles/*` | 块容器样式（含暗色） |
| `packages/aichat-ui/src/components/index.ts` | 导出 ChartBlock |

宿主（user-web / admin-web）零改动——v-html 渲染管线自动生效。

---

## 3. 后端设计（services/angineer-core）

### 3.1 prompt 指令（prompts/agent_configs.py）

回答规则清单追加一条（各档共享段），要点：

1. 涉及多行数据对比/聚合/趋势/占比，且**证据中存在具体数值**时：明细用 markdown 表格呈现；
2. 数据适合图形表达（趋势/占比/对比）且 ≤2 张图时，表格后紧跟 ```angineer-chart 块，JSON 字段按协议（chartType/title/categories/series/unit/source）；source 填对应证据的引用标记值（逐字照抄，同规则 8 契约）；
3. **无证据数值不得编造图表**；数字必须与表格/正文一致；
4. 证据含坐标/空间分布数据时，可输出 ```angineer-map 块（title/description/points）；
5. 块的 JSON 必须合法完整、在闭合 fence 前不可截断；推荐紧凑单行书写，渲染器按「fence 开行至闭合行整体 parse」，不依赖单行。

### 3.2 评测判分保护

- 判官（judge）输入预剥 ```angineer-* 块正文（保留 markdown 表格文本）后再判分——JSON 噪声不影响语义判分；剥离函数放 evals 判分输入准备处。
- 表格题/自由文本题回归：块不存在时链路行为与现状逐字节一致（prompt 追加条目对不出数据的题无感）。

### 3.3 落库/回灌/SSE

零改动：块随 answer 文本走 message_delta、落 chat_messages.content、历史回灌即重渲。

---

## 4. 实施清单

| # | 任务 | 验证 |
|---|---|---|
| T1 | markdown.ts 块扫描 + 占位/回退 + 样式 | 单测：闭合/未闭合/坏 JSON/普通代码块不误伤 |
| T2 | ChartBlock.vue + echarts 按需引入 + 暗色 | 手测：bar/line/pie 渲染、主题切换 |
| T3 | prompt 指令追加（agent_configs.py） | 本地 E2E 数据题出图、纯文本题无感 |
| T4 | 评测判分剥 angineer 块 | 剥离单测 + 判分输入对照 |
| T5 | 全量 typecheck + test + 双端 build | 绿 |

## 5. 风险与对策

| 风险 | 对策 |
|---|---|
| 模型 JSON 写坏 | 渲染端回退表格/原文，不炸不丢答 |
| 模型编造数据 | prompt 禁令 + source 必填引用标记 + 数值须与表格一致；后续 S2 施工后改代码校验 |
| 出图时机不准（该出不出/不该出乱出） | prompt 迭代调优；S2 立项待施工（高置信聚合题强制图表） |
| echarts 包体 | 按需引入 bar/line/pie；build 产物体积对比验证 |
| 判分被 JSON 噪声污染 | 判分输入预剥块（T4） |
| 暗色主题失效 | 双选择器 + setOption 重上色；手测覆盖 |

## 6. 后续立项（本次不做）

- **S2 回答分型施工**：意图分类捎带 `schemas[]`+confidence（IntentResult 契约扩展、消费方随迁），高置信聚合题强制走图表管道。设计入口：`docs/plan-ls-routing.md` §4.3/§5-P1。
- **GIS 地图渲染**：Leaflet/底图选型、密钥、GCJ-02 偏移处理；协议已预留（angineer-map）。
