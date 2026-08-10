# PDF_Viewer 可折叠解析面板设计

日期：2026-08-10

状态：待用户审阅

## 1. 背景与目标

当前文档预览存在两个入口：

- 管理后台 `KnowledgeParseWorkspace.vue` / `KnowledgeStats.vue` 使用 `PDFParsedWorkspace`，左侧 PDF 与右侧解析面板常驻并排显示；
- 用户端 `DocumentView.vue` 只使用单独的 `PDF_Viewer`，没有解析面板。

目标是把两者合并成一个可复用组件：在 `PDF_Viewer` 右上角增加一个图标按钮，点击展开右侧解析面板（对比框），再次点击收起；合并后的组件像 `PDF_Viewer` 一样保持高度可移植性，两个入口都切换过去。

`PDF_Viewer` 代码已经很大，因此它只获得一个通用的“右侧面板”能力，不吸收任何解析相关代码。

## 2. 已确认的需求决策

| 决策点 | 结论 |
| --- | --- |
| 使用场景 | 管理后台 + 用户端共用同一个可复用组件 |
| 实现方案 | 方案一：PDF_Viewer 增加通用侧栏插槽，升级 PDFParsedWorkspace 作为合并组件入口 |
| 展开布局 | 并排挤占：面板展开时与 PDF 共用下方内容区，PDF 区域自适应剩余空间 |
| 收起行为 | 面板不占布局空间，PDF 独占内容区；内部组件保持挂载以保留状态 |
| 默认状态 | 可配置 prop；管理后台与用户端均默认展开 |
| 用户端默认 Tab | 树形索引；无图数据时自动退回 Markdown，图数据就绪后自动切回树形 |
| 面板宽度 | 固定默认 400px，通过 prop 可调；不做拖拽调宽 |
| 组件命名 | 复用并升级现有 `PDFParsedWorkspace`，不另建重复组件 |

## 3. 组件边界与架构

### 3.1 PDF_Viewer：只加通用侧栏能力

新增 props：

| prop | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `sidePanelOpen` | `boolean` | 内部默认 false | 是否展开右侧面板，支持受控 / 非受控 |
| `showSidePanelToggle` | `boolean` | `false` | 是否显示展开/收起按钮；老调用方不传则完全不显示 |
| `sidePanelWidth` | `number` | `400` | 右侧面板宽度（px） |

新增事件：

- `update:sidePanelOpen: [value: boolean]`

新增插槽：

- `side-panel`：右侧面板内容，由外部注入。PDF_Viewer 不感知内容是什么。

模板结构：

- 根节点改为一个横向 flex 外壳，内部是原有的 `.split-pane` 主查看器 + 可选的右侧面板；
- 右侧面板始终挂载（用于保留内部状态），展开/收起通过宽度 `0 ↔ sidePanelWidth` 过渡实现，收起时 `pointer-events: none`；
- 展开/收起按钮放在头部右侧（`.pane-title-right`），与搜索、定位框按钮同一排；图标使用 `MenuUnfoldOutlined`（收起状态）/ `MenuFoldOutlined`（展开状态），激活时高亮，带中文 tooltip；
- 按钮不依赖 `isPdf`：PDF、Office、图片、文本预览都可使用，只要宿主传了 `showSidePanelToggle` 且提供了 `side-panel` 插槽；
- 新增一个针对内容区宽度的 `ResizeObserver`：宽度变化且处于“适应宽度”模式时自动重新计算缩放，收起/展开不会导致 PDF 停留在旧宽度。

明确不做：

- PDF_Viewer 不 import `PDFParsedViewerCombo`、不依赖知识库类型与 API；
- 不改变任何现有 props / 事件的语义。

### 3.2 PDFParsedViewerCombo：只读模式与 Tab 收敛

新增只读判定：

```ts
const readonly = computed(() =>
  !props.onUpdateStructuredNode
  && !props.onBatchStructuredOperation
  && !props.onUndoLastOperation
)
```

只读模式下：

- 隐藏树形工具栏中的“层级调整 / 合并 / 拆分 / 撤销 / 清空”操作区（`.summary-actions`）；
- `Preview_IndexTree` 新增 `readonly` prop：隐藏节点勾选框、编辑按钮和右键“调整层级”菜单；
- “显示页眉”等纯视图开关保留。

图谱 Tab 收敛：

- 当 `onLoadGraphSnapshot` 或 `onBuildGraph` 缺失时，隐藏“知识图谱”Tab（现有组件缺少回调时只会显示“未配置图谱数据源”的错误，用户端不应出现该状态）；
- 若当前 Tab 恰为知识图谱且回调变为缺失，回退到 Markdown 或树形（按现有数据情况）。

### 3.3 PDFParsedWorkspace：可复用合并组件

新增 props：

| prop | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `sidePanelOpen` | `boolean` | 非受控 | 支持 `v-model:sidePanelOpen` |
| `sidePanelDefaultOpen` | `boolean` | `true` | 首次打开 / 切换文档后的默认状态 |
| `sidePanelWidth` | `number` | `400` | 透传给 PDF_Viewer |
| `defaultParsedTab` | `PreviewMode` | 现有自动逻辑 | 指定默认 Tab（用户端传 `Preview_IndexTree`） |

新增事件：

- `update:sidePanelOpen: [value: boolean]`

结构变化：

- 把 `PDFParsedViewerCombo` 移入 `PDF_Viewer` 的 `#side-panel` 插槽；
- PDF_Viewer 绑定 `:show-side-panel-toggle`（有解析内容或图数据时显示按钮）、`:side-panel-open`、`:side-panel-width`，并监听 `@update:side-panel-open`；
- `getDefaultParsedTab()` 优先返回 `defaultParsedTab`，未传时维持现有逻辑（有图数据用树形，否则 Markdown）；
- 切换文档（`node.key` 变化）时，面板状态重置为 `sidePanelDefaultOpen`；
- 其余 props 与事件全部不变。

## 4. 数据流

### 4.1 管理后台

无数据流变化。`KnowledgeParseWorkspace.vue` 与 `KnowledgeStats.vue` 不传新 prop，组件默认展开，编辑、树形、知识图谱、左右联动行为与现在一致。

### 4.2 用户端 DocumentView.vue

- 把单独的 `PDF_Viewer` 换成 `PDFParsedWorkspace`；
- 传入已有的 `node`、`content`、`renderPdfPath`；
- 传 `:side-panel-default-open="true"`、`:default-parsed-tab="'Preview_IndexTree'"`；
- 移除 DocumentView 自带的文档标题栏（标题已显示在顶部页签中），让 PDF 预览从内容区顶部开始；
- 图数据优先取 `DocumentResponse.graph_data`（现有接口已返回该字段），缺失时通过用户端已有的 `getDocBlocksGraph` 懒加载，经由组件已有的 `on-load-full-graph-data` / `graph-data-full-loaded` 契约传入；
- 不传编辑类回调与图谱数据源回调，面板自动进入只读模式，且不显示“知识图谱”Tab；
- 树形节点点击、左右联动、搜索跳转复用 `PDFParsedWorkspace` 现有的 `useWorkspaceLinkage` 逻辑。

组件仍然保持“声明式、可移植”：所有数据由宿主传入或通过回调提供，组件内部不写死任何 API。

## 5. 交互细节

- 按钮：PDF_Viewer 头部右侧，展开/收起图标切换并高亮，tooltip 中文提示；
- 动画：面板宽度过渡约 200ms；
- 状态保留：面板始终挂载，收起再展开后保留当前 Tab、树节点展开状态、滚动位置；
- 空内容：既无 Markdown 也无图数据时不显示按钮，避免展开空面板；只有 Markdown 时按钮照常可用；
- 展开/收起引起的宽度变化：PDF 在“适应宽度”模式下自动重排；用户手动缩放过的比例保持不变。

## 6. 错误处理与边界情况

- 用户端图数据加载失败：不阻断 PDF 预览，`console.warn` 记录，面板退回 Markdown，树形 Tab 置灰并提示暂无数据；
- 无图数据但指定了树形默认 Tab：自动回退 Markdown，图数据就绪后自动切回树形（复用现有 watch）；
- 老调用方不传任何新 prop：按钮不显示、面板不展开、行为与现状完全一致；
- 面板隐藏时内部组件不卸载，避免重新加载 / 重置状态。

## 7. 文件改动清单

| 文件 | 改动 |
| --- | --- |
| `packages/docs-ui/src/components/common/viewers/PDF_Viewer.vue` | 新增侧栏 props / emit / slot、外壳布局、按钮、宽度监听 |
| `packages/docs-ui/src/components/common/workspace/PDFParsedWorkspace.vue` | 新增 4 个 prop + 1 个事件，把解析面板移入插槽 |
| `packages/docs-ui/src/components/common/workspace/PDFParsedViewerCombo.vue` | 只读模式、图谱 Tab 收敛 |
| `packages/docs-ui/src/components/common/index/Preview_IndexTree.vue` | 新增 `readonly` prop，隐藏勾选 / 编辑 / 右键菜单 |
| `packages/docs-ui/src/types/knowledge.ts` | `PDFParsedWorkspaceEventMap` 增加 `update:sidePanelOpen` |
| `apps/user-web/src/views/DocumentView.vue` | 换用 `PDFParsedWorkspace`，接入图数据与默认收起/树形 |
| `packages/docs-ui/README.md` | 组件说明小更新（可选） |

管理后台两个页面不改代码，仅做回归验证。

## 8. 验证与测试

仓库目前只有纯逻辑脚本测试（无组件级测试框架），因此采用“构建检查 + 回归清单”：

1. 运行现有类型检查、构建、lint，确认新 props / 类型无破坏；
2. 管理后台回归：默认展开、树形编辑、知识图谱、左右联动、搜索跳转与现状一致；
3. 用户端回归：默认收起、展开后默认树形、只读（无编辑工具栏、无知识图谱 Tab）、无图数据时退回 Markdown、PDF 翻页/缩放/搜索/高亮正常；
4. 展开/收起往返：面板内部状态保留，PDF 宽度自适应；
5. 若实施中抽出了可单测的纯函数（如默认 Tab 决策），补充 `.mjs` 脚本测试。

## 9. 明确不做

- 不实现面板宽度拖拽调节；
- 不持久化面板开关状态（每个场景使用各自默认值）；
- 不在用户端启用结构化编辑与知识图谱功能；
- 不让 PDF_Viewer 直接依赖解析组件或知识库类型；
- 不重构 PDF_Viewer 现有 PDF 渲染逻辑。
