# AnGIneer 技术实现细节

本文档包含项目的详细技术实现、API 规范、组件使用示例。

- 运行端口契约：`apps/web-console` 使用 `3005`，`apps/admin-console` 使用 `3002`，`apps/api-server` 使用 `8789`，前端开发代理 `/api` 必须指向 `http://localhost:8789`。

---

## 目录

- [前端常用命令（自动同步）](#前端常用命令自动同步)
- [前端权威架构图（简版）](#前端权威架构图简版)
- [前端架构图（重绘）](#前端架构图重绘)
- [PDF 对比高亮逻辑架构（前端）](#pdf-对比高亮逻辑架构前端)
- [文档解析与对比查改改造清单（可直接开工）](#文档解析与对比查改改造清单可直接开工)
- [统一资源架构（已落地）](#统一资源架构已落地)
- [统一资源执行清单（按文件级）](#统一资源执行清单按文件级)
- [KnowledgeChatPanel 对话系统](#knowledgechatpanel-对话系统)
- [SmartTree 知识树系统](#smarttree-知识树系统)
- [API 端点速查](#api-端点速查)
- [数据模型](#数据模型)

---

## 数据模型与版本控制

### SCHEMA_VERSION (Docs 模块)

`SCHEMA_VERSION` 定义在 `services/docs-core/src/docs_core/knowledge_service.py` 中，用于追踪 **文档解析产物（Parsing Artifacts）的结构版本**。

- **作用范围**：
  - 影响 `KnowledgeNode` 和 `ParseTask` 数据库表。
  - 标识解析产物（Markdown, JSON 索引, 图片等）的存储结构是否与当前代码逻辑兼容。
- **版本提升准则**：
  - 当修改了解析产物的目录结构时。
  - 当修改了 `doc_blocks_graph_v1` 生成的索引 JSON 格式时。
  - 当需要强制所有存量文档重新解析以适配新功能时。
- **当前版本**：`1.0.0`

---

## 核心交互组件与逻辑优化

### PDF 渲染优化 (PDF_Viewer.vue)

为了解决“海港2.pdf”等复杂文档的渲染问题，我们实施了以下优化：

- **自适应缩放 (Adaptive Scaling)**：
  - 使用 `ResizeObserver` 实时监听容器尺寸变化。
  - 引入 `intrinsicPdfPageWidth` 状态，在 PDF 加载后预先获取第一页原始宽度，实现瞬间响应的自适应缩放。
  - 提供 `isFitToWindowMode` 开关，支持在固定比例与自动适配间平滑切换。
- **视觉一致性与防闪烁**：
  - **背景预填充**：在 `pdf.js` 渲染前，始终使用 `fillStyle = '#ffffff'` 填充 Canvas，解决深色模式或透明 PDF 下的“颜色惨白”问题。
  - **尺寸校验**：仅在 Canvas 实际目标尺寸发生变化时更新 `canvas.width/height`，避免不必要的重绘导致的闪烁。
  - **Vue 3 兼容性**：使用 `shallowRef` 存储 `pdf.js` 内部对象（包含原生私有字段），防止 Vue Proxy 代理导致的私有字段访问错误。

### 共享逻辑抽离 (common.ts & knowledge.ts)

为了降低组件耦合并消除冗余代码，我们将核心逻辑下沉至 `packages/docs-ui/src/utils/`：

- **common.ts**：存放通用文本处理（Markdown 过滤、Token 估算、行号校验等）和 UI 辅助函数。
- **knowledge.ts**：存放业务强相关的节点解析、渲染逻辑、图标映射及富媒体处理函数。
- **受益组件**：`Preview_IndexList`, `Preview_IndexTree`, `Preview_IndexGraph`, `DocBlocksTreeNode` 等 11 个核心组件已完成重构，实现了 100% 的逻辑复用。

---

## 前端常用命令（自动同步）

<!-- AUTO_SYNC:APPS_TECH_COMMANDS:START -->
```bash
pnpm install
pnpm dev:frontend
pnpm dev:admin
pnpm build:frontend
pnpm build:admin
pnpm lint
```
<!-- AUTO_SYNC:APPS_TECH_COMMANDS:END -->

---

## 前端权威架构图（简版）

这部分作为前端侧的权威简图，优先回答两个问题：

- 资源是如何被统一打开的
- 两个前端应用与共享包之间的边界是什么

```mermaid
flowchart LR
  Web["web-console"]
  Admin["admin-console"]
  DocsUI["docs-ui"]
  UIKit["ui-kit"]
  Adapter["ResourceAdapter"]
  Open["useResourceOpen"]
  Workbench["workbenchStore + Workbench"]
  Api["api-server"]

  Web --> DocsUI
  Admin --> DocsUI
  Web --> UIKit
  Admin --> UIKit
  DocsUI --> Adapter
  Adapter --> Open
  Open --> Workbench
  Web --> Api
  Admin --> Api
```

### 前端不变量

- `web-console` 与 `admin-console` 默认共享 `docs-ui` 协议层
- 资源打开主链固定为 `ResourceNode -> OpenResourcePayload -> openResource -> workbenchStore.openResource`
- 前端不直接绕过 `api-server` 访问知识后端

### 前端代码锚点

- `packages/docs-ui/src/composables/useResourceAdapter.ts`
- `apps/web-console/src/composables/useResourceOpen.ts`
- `apps/web-console/src/stores/workbench.ts`
- `packages/ui-kit/src/components/common/SmartTree.vue`
- `packages/docs-ui/src/components/common/widgets/KnowledgeTree.vue`

---

## 前端架构图（重绘）

### 分层架构（文档解析改造版）

```mermaid
flowchart TB
  subgraph Apps["前端应用层"]
    Web["apps/web-console\n工作台壳：三栏 + Tab 工作区"]
    Admin["apps/admin-console\n管理壳：路由页 + 三栏管理页(B区核心)"]
  end

  subgraph SharedUI["共享 UI / 交互层"]
    DocsUI["packages/docs-ui\nKnowledgeTree / KnowledgeChatPanel / SOPTree / SOPChatPanel"]
    UIKit["packages/ui-kit\nSmartTree / BaseChat / SplitPanes / Panel / Theme"]
  end

  subgraph AdminB["admin B区（文档生命周期）"]
    BState["B区状态机\n未解析/解析中/已解析"]
    BSplit["B1/B2双区\nB1原文+B2 Markdown预览编辑"]
    Strategy["解析/检索策略切换\nA结构化/B MinerU-RAG/C PageIndex"]
    Prog["解析进度可视化\nstage+percent+error"]
  end

  subgraph ResourceCore["资源协议层"]
    Types["types/resource.ts\nResourceNode / OpenResourcePayload"]
    Adapter["useResourceAdapter.ts\nproject|knowledge|sop -> payload"]
    OpenFlow["useResourceOpen + workbenchStore.openResource"]
  end

  subgraph State["状态层"]
    WB["workbench store\nTab 生命周期与激活态"]
  end

  subgraph API["服务访问层"]
    KApi["knowledgeApi"]
    CApi["/api/chat"]
  end

  Web --> DocsUI
  Web --> UIKit
  Admin --> DocsUI
  Admin --> UIKit
  Admin --> BState
  BState --> BSplit
  BState --> Prog
  BSplit --> Strategy

  DocsUI --> Types
  DocsUI --> Adapter
  Adapter --> OpenFlow
  OpenFlow --> WB

  Web --> KApi
  Admin --> KApi
  DocsUI --> CApi
  Strategy --> KApi
  Prog --> KApi
```

### 资源打开链路（前端统一）

```mermaid
sequenceDiagram
  participant User as 用户点击节点
  participant Side as 侧栏(项目/知识/SOP)
  participant Adapt as createResourceNode + createOpenResourcePayload
  participant Open as useResourceOpen
  participant Store as workbenchStore
  participant View as Workbench视图映射

  User->>Side: 点击资源
  Side->>Adapt: 资源实体 -> ResourceNode
  Adapt->>Open: 输出 OpenResourcePayload
  Open->>Store: openResource(payload)
  Store->>View: 激活/创建对应Tab
  View-->>User: 渲染 DocumentView / SOPView / ProjectView
```

### 应用壳体职责

```text
web-console（工作台型）
└─ App.vue
   ├─ LeftPanel（项目/知识/SOP 入口）
   ├─ Workbench（统一资源标签页渲染）
   └─ 右侧聊天区（KnowledgeChatPanel / SOPChatPanel 按左侧 Tab 切换）

admin-console（管理路由型）
└─ App.vue
   └─ router-view
      └─ /knowledge -> KnowledgeManage
         ├─ 左：KnowledgeTree（管理态）
         ├─ 中：B区（状态机 + B1/B2 + 策略切换）
         └─ 右：KnowledgeChatPanel（知识域对话封装）
```

---

## Docs 前后端架构与注意事项 (2026-03)

### 1. 整体架构概览

Docs 模块（文档解析与知识管理）当前采用 **“异步任务化解析 + 一文档一目录存储 + 单策略结构化主链”** 的核心架构，并为后续多策略检索预留扩展位。

```mermaid
flowchart TD
    subgraph Frontend["前端 (apps/admin-console)"]
        KM["KnowledgeManage.vue\n状态机驱动 B 区渲染"]
        DPW["PDFParsedWorkspace.vue\nB1/B2 联动工作区"]
        PV["PDF_Viewer.vue\n高保真 PDF 渲染器"]
    end

    subgraph Backend["后端 (apps/api-server & docs-core)"]
        API["FastAPI 异步接口\n/parse, /tasks, /document"]
        Task["ParseOrchestrator\n后台线程异步处理"]
        Parser["MinerU Parser\n云端解析 + 本地后处理"]
        Storage["FileStorage\n一文档一目录规范"]
        Query["Query Service\nintent + planner"]
        Executors["Executors\ncontent/table/formula"]
        Answering["Answering\ncitation + answer"]
    end

    subgraph Strategy["检索策略层"]
        SA["A: 结构化索引\n(当前唯一生产主链)"]
        SB["B: MinerU-RAG\n(规划中，未接入运行时)"]
        SC["C: PageIndex\n(规划中，未接入运行时)"]
    end

    KM -- 提交解析 --> API
    API -- 返回 task_id --> KM
    KM -- 轮询进度 --> API
    Task -- 调用 --> Parser
    Parser -- 产物落盘 --> Storage
    Storage -- 构建索引 --> Strategy
    API -- 发起问答 --> Query
    Query -- 规划并分发 --> Executors
    Executors -- 召回证据 --> Strategy
    Executors -- 组织作答 --> Answering
    KM -- 获取结果 --> API
```

### 2. 前端核心注意事项

#### PDF 渲染与联动
- **渲染性能**：`PDF_Viewer.vue` 必须使用 `shallowRef` 存储 pdf.js 对象，严禁使用 `ref` 进行深度代理，否则会导致私有字段访问错误。
- **防闪烁**：仅在容器尺寸变化时更新 Canvas 宽高。
- **高亮联动**：前端通过 `linkedHighlights` 统一管理来自 `mineru_blocks.json` 和 `structured_index.json` 的坐标数据。坐标必须根据 PDF 页面原始尺寸进行归一化处理。

#### 状态机管理
- 文档状态流转：`idle (未解析)` -> `processing (解析中)` -> `completed (已解析)` / `failed (失败)`。
- 解析中状态必须展示实时的 `stage` 和 `percent`。

### 3. 后端核心注意事项

#### 存储规范（一文档一目录）
所有文档产物必须存放在：`data/knowledge_base/libraries/{lib_id}/documents/{doc_id}/`
- `source/`: 原始文件。
- `parsed/`: `content.md`, `mineru_blocks.json`, `assets/` (图片/表格截图)。
- `structured/`: 经过 A/B/C 策略处理后的结构化索引。

#### 解析健壮性
- **异步化**：解析是耗时操作，必须通过 `task_id` 异步返回。
- **数据对齐**：后端返回的 `mineru_blocks` 必须包含 `page_idx` 和 `bbox`。`bbox` 统一采用 `[x0, y0, x1, y1]` 格式。
- **错误恢复**：如果云端解析返回的 `mineru_blocks.json` 为空，后端应尝试从压缩包中的 `model.json` 恢复基础块信息。

#### 策略分发现状
- 当前运行时仅支持 `doc_blocks_graph_v1` 一个结构化策略。
- `strategy` 字段与 `/api/knowledge/strategies/*` 接口已落地，但仍属于“单策略配置位”，尚未接入 `MinerURagStrategy` 或 `PageIndexStrategy` 的真实执行链。

---

## PDF 对比高亮逻辑架构（前端）

```mermaid
flowchart TB
  subgraph DataIn["数据输入层"]
    Storage["/api/knowledge/document/{library_id}/{doc_id}\nstorage + content + mineru_blocks"]
    StructApi["/api/knowledge/document/{library_id}/{doc_id}/structured\nstructured_index.items"]
    NodeState["KnowledgeManage 当前文档状态\nselectedNode + selectedDocumentContent"]
  end

  subgraph Assemble["前端组装层 KnowledgeManage.vue"]
    ParseBlocks["parseMineruBlocks\n过滤无效块/标准化字段"]
    BuildIndex["buildStructuredItems\n结构化索引兜底组装"]
    BuildFallback["buildMiddleFallbackItems\n仅基于 content 生成标题锚点"]
    PassProps["向 PDFParsedWorkspace 透传\nmineruBlocks/structuredItems/docContent"]
  end

  subgraph LinkCore["联动核心 PDFParsedWorkspace.vue"]
    ResolvePage["resolvePageNumber\npage/page_idx 统一解析"]
    RectNorm["normalizeRect\n按页尺寸动态归一化"]
    ToLinked["toLinkedHighlight\n标准化高亮实体"]
    MergePool["linkedHighlights\nstructured 优先 + mineru 兜底"]
    ActiveWatch["watch(linkedHighlights,pdfPage)\n自动维护 activeLinkedItemId"]
  end

  subgraph Render["渲染层 PDF_Viewer.vue"]
    PageFilter["visibleHighlights\n按当前页过滤"]
    ActiveOnly["activeHighlightId 命中时\n仅渲染 active 框"]
    DrawBox["PDF 覆盖层绘制蓝框"]
  end

  Storage --> ParseBlocks
  StructApi --> BuildIndex
  NodeState --> BuildFallback
  ParseBlocks --> PassProps
  BuildIndex --> PassProps
  BuildFallback --> PassProps

  PassProps --> ResolvePage
  ResolvePage --> RectNorm
  RectNorm --> ToLinked
  ToLinked --> MergePool
  MergePool --> ActiveWatch

  MergePool --> PageFilter
  ActiveWatch --> ActiveOnly
  PageFilter --> ActiveOnly
  ActiveOnly --> DrawBox
```

### PDF 渲染最佳实践 (Vue 3)

在 `PDF_Viewer.vue` 中集成 `pdfjs-dist` 时，必须遵循以下规则：

1. **避免深度代理**: `pdf.js` 的 `LoadingTask` 和 `PDFDocumentProxy` 对象内部使用了 JavaScript 原生私有字段（`#` 语法）。Vue 3 的 `ref` 会尝试对对象进行深度递归代理，导致在调用 `destroy()` 等方法时因私有字段访问冲突报错 `TypeError: Cannot read from private field`。
2. **使用 shallowRef**: 必须使用 `shallowRef` 来存储这些第三方库对象（如 PDF 加载任务、文档对象、ResizeObserver 等），只追踪引用变化，不进行递归代理。
3. **安全销毁**: 在组件卸载或 PDF 切换时，务必显式调用 `loadingTask.destroy()` 和 `pdfDoc.destroy()`。同时断开所有 `ResizeObserver` 监听。
4. **防闪烁策略**: 在 `renderPageToCanvas` 时，仅当 Canvas 目标尺寸（`targetWidth/targetHeight`）确实发生变化时才更新 `canvas.width/height`。设置 Canvas 尺寸会自动清除内容，频繁设置是产生闪烁的主要原因。
5. **色彩还原与一致性**: 渲染 PDF 页面前，必须显式在 Canvas 上填充白色背景（`canvasContext.fillStyle = '#ffffff'; canvasContext.fillRect(0, 0, targetWidth, targetHeight);`），并使用 `{ alpha: false }` 获取 2D 上下文，以防止 PDF 颜色因透明度问题显得“惨白”或受容器背景色影响。
6. **自适应缩放响应**: 为 PDF 滚动容器（`pdfScrollRef`）添加 `ResizeObserver`。当容器尺寸变化且处于“适应窗口”模式时，自动重新计算并应用缩放比例，确保在窗口缩放或布局调整时 PDF 始终保持最佳显示。
7. **渲染任务幂等性**: 维护 `pageLastRenderedScale` 映射。如果页面已在当前缩放比例下完成渲染，则跳过重复渲染请求，进一步减少性能损耗和潜在闪烁。

---

## 文档解析与对比查改改造清单（可直接开工）

### 1）前端页面（按文件级）

- `apps/admin-console/src/views/KnowledgeManage.vue`
  - 拆分 B 区状态机渲染：未解析、解析中、已解析。
  - 保持单一结构化策略：`doc_blocks_graph_v1`。
  - 新增解析进度轮询（按 `task_id` 获取进度）。
  - 已解析态改为 B1/B2 双区：左原文，右 Markdown 预览/编辑。
- `apps/admin-console/src/views/components/DocumentPreview.vue`
  - 下沉为“未解析 + 解析中”视图组件。
  - 增加进度条、阶段文案、错误态重试按钮。
- `packages/docs-ui/src/components/common/workspace/PDFParsedWorkspace.vue` (已下沉至 docs-ui)
  - 负责 B1/B2 布局、同步滚动、编辑开关、保存/放弃修改。
  - 预留“差异对比模式”入口（首版可只做按钮占位与接口联动）。
- `apps/admin-console/src/api/knowledge.ts`
  - 已接入任务接口：`parseDocumentAsync`、`getParseTask`。
  - 已接入策略接口：`setDocStrategy`、`getDocStrategy`，但当前仅支持 `doc_blocks_graph_v1`。
  - 已接入文档与结构操作接口：`getDocument`、`updateDocumentBlock`、`batchOperateDocumentBlocks`、`undoLastDocumentBlockOperation`。
  - `queryByStrategy`、文档版本列表等接口仍未落地，不应视为当前已完成能力。
- `packages/docs-ui/src/composables/useKnowledgeTree.ts`
  - 扩展节点字段：`parse_progress`、`parse_stage`、`parse_error`、`strategy`。
  - 保持 tree 构建兼容旧字段，避免前后台选择树断裂。

### 2）后端接口（按文件级）

- `apps/api-server/main.py`
  - 已将 `/api/knowledge/parse` 改为异步任务提交（返回 `task_id`）。
  - 已提供 `/api/knowledge/parse/tasks/{task_id}` 查询进度。
  - 已提供 `/api/knowledge/strategies/*`，但当前仅用于读取/写入单一策略配置。
  - 已提供 `/api/knowledge/structured/*`、`/api/knowledge/document/*`、结构块编辑与撤回接口。
  - `/api/knowledge/document/{library_id}/{doc_id}/revisions`、按策略查询与三策略构建分发仍未落地。
- `apps/api-server/knowledge_routes.py`
  - 统一承载知识库路由、文件预览路由与解析主链编排：任务创建、阶段推进、MinerU 调用、产物落盘、A 主链索引构建。
- `services/docs-core/src/docs_core/projection/*.py`
  - 当前仓库中尚未形成 A/B/C 三类独立 projection 模块，仍以 `ingest/canonical`、`ingest/structured`、`ingest/storage/file_store.py` 为主链实现。
- `services/docs-core/src/docs_core/index/doc_block_store.py`
  - 抽离 `doc_blocks` 索引写入、查询、统计，避免与文件存储职责混放。
- `services/docs-core/src/docs_core/ingest/extract/mineru_parser.py`
  - 保留 MinerU 解析能力，补充任务阶段回调（若 SDK 无实时进度则用阶段进度）。
  - 增加解析产物清单返回（md、assets、metadata）。
- `services/docs-core/src/docs_core/storage/document_storage.py`
  - 改造为“一文档一目录”结构。
  - 新增路径方法：`get_doc_root`、`get_graph_path`、`get_mineru_raw_dir`、`resolve_canonical_raw_dir`、`save_revision`。
  - 提供旧路径兼容读取逻辑（迁移期间双读）。
- `services/engtools/src/engtools/config.py`
  - 增加目录解析策略：优先新目录结构，回退旧 `knowledge_base/markdown`。
- `services/engtools/src/engtools/KnowledgeTool.py`
  - 允许 `doc_id` 或逻辑文件名检索，不再仅依赖单 md 文件路径。
- `services/engtools/src/engtools/TableTool.py`
  - 改为优先读取结构化表格索引，回退 Markdown 表格抽取。

### 3）数据表（按文件级）

- `services/docs-core/src/docs_core/knowledge_service.py`
  - 作为服务门面，内部拆分为 `KnowledgeMetaStore` 与 `KnowledgeIndexStore`。
  - 现有 `nodes` 表增加字段：
    - `parse_progress INTEGER`
    - `parse_stage TEXT`
    - `parse_error TEXT`
    - `strategy TEXT`
    - `parsed_at TEXT`
    - `edited_at TEXT`
  - 新增 `parse_tasks` 表：任务状态、阶段、进度、错误、起止时间。
  - 新增 `document_artifacts` 表：source/parsed/assets/edited 路径与 hash。
  - 新增 `document_segments` 表：条文/段落/附注等结构化片段。
  - 新增 `document_tables`、`document_images` 表：表格与图片结构化索引。
  - 新增 `document_revisions` 表：编辑版本与 diff 摘要。
  - `strategy_eval_logs` 等多策略评测持久化表仍未形成当前运行时真相源。
  - `document_segments` 与 `doc_blocks` 统一收口到 `knowledge_index.sqlite`。

### 4）迁移脚本（按文件级）

- `services/docs-core/src/docs_core/migrations/migrate_doc_layout.py`（新增）
  - 将旧 `source/{library}/{doc_id}.pdf`、`markdown/{library}/{doc_id}/full.md` 迁移到新目录。
  - 迁移后回写 `document_artifacts`。
  - 支持 dry-run 与回滚快照。
- `services/docs-core/src/docs_core/migrations/migrate_engtools_refs.py`（新增）
  - 扫描 engtools 配置与引用，建立旧文件名到 `doc_id` 的映射表。
  - 输出校验报告：可解析/缺失/冲突条目。
- `apps/api-server/main.py`
  - 新增管理端迁移触发接口（仅开发环境启用）。
- `tests/`（补充）
  - 新增迁移脚本单元测试与回归测试：确保旧路径仍可读、新路径优先。

### 5）分阶段交付建议

- P0：B 区状态机 + 异步解析进度 + B1/B2 + Markdown 可编辑，已基本落地。
- P1：A/B/C 策略切换与统一响应结构，仍未落地。
- P2：结构化索引深挖（表格跨页纠偏、图片语义增强、版本化 diff 可视化），仍在后续计划中。

---

## 统一资源架构（已落地）

### 组件-文件映射图（新增）

```mermaid
flowchart LR
  subgraph Web["apps/web-console"]
    LP["LeftPanel.vue"]
    PS["sidebar/ProjectSidebar.vue"]
    SS["sidebar/SOPSidebar.vue"]
    RO["composables/useResourceOpen.ts"]
    WB["stores/workbench.ts"]
    WV["layouts/Workbench.vue"]
    DV["views/DocumentView.vue"]
    SV["views/SOPView.vue"]
    PV["views/ProjectView.vue"]
  end

  subgraph Shared["packages/docs-ui"]
    RT["types/resource.ts"]
    RA["composables/useResourceAdapter.ts"]
    KT["components/common/widgets/KnowledgeTree.vue"]
  end

  subgraph Admin["apps/admin-console"]
    KM["views/KnowledgeManage.vue"]
  end

  LP --> RA
  PS --> RA
  SS --> RA
  KM --> RA

  RA --> RT
  LP --> RO
  PS --> RO
  SS --> RO
  RO --> WB
  WB --> WV
  WV --> DV
  WV --> SV
  WV --> PV
  LP --> KT
  KM --> KT
```

### 当前架构原则

- 共享能力层（组件、协议、适配器），不强制共享页面骨架
- 保持 web-console 工作台模式，保持 admin-console 路由页面模式
- 资源打开统一走 `ResourceNode -> OpenResourcePayload -> workbenchStore.openResource`

## 统一资源执行清单（按文件级）

- `packages/docs-ui/src/types/resource.ts`：定义 `ResourceNode`、`OpenResourcePayload`、`WorkbenchTabType`
- `packages/docs-ui/src/composables/useResourceAdapter.ts`：实现 project/knowledge/sop 到 payload 的统一转换
- `packages/docs-ui/src/types/index.ts`：导出 resource 类型
- `packages/docs-ui/src/composables/index.ts`：导出 resource adapter 能力
- `apps/web-console/src/stores/workbench.ts`：提供 `openResource(payload)` 并统一 Tab 生命周期
- `apps/web-console/src/composables/useResourceOpen.ts`：封装资源打开入口
- `apps/web-console/src/layouts/LeftPanel.vue`：知识节点点击接入统一资源链路
- `apps/web-console/src/layouts/sidebar/ProjectSidebar.vue`：项目入口接入统一资源链路
- `apps/web-console/src/layouts/sidebar/SOPSidebar.vue`：SOPTree 入口接入统一资源链路
- `apps/web-console/src/layouts/Workbench.vue`：按 `WorkbenchTabType` 统一视图映射
- `apps/web-console/src/views/ProjectView.vue`：project Tab 视图
- `apps/web-console/src/views/DocumentView.vue`：document Tab 视图（props/route 双入口）
- `apps/web-console/src/views/SOPView.vue`：sop Tab 视图（props/route 双入口）
- `apps/admin-console/src/views/KnowledgeManage.vue`：后台复用 adapter 并支持打开前台文档页

---

## KnowledgeChatPanel 对话系统

### 组件架构

```
┌─────────────────────────────────────────────────────────────┐
│      KnowledgeChatPanel.vue (docs-ui 知识域封装组件)         │
├─────────────────────────────────────────────────────────────┤
│            BaseChat.vue (ui-kit 基础聊天组件)                │
├─────────────────────────────────────────────────────────────┤
│  消息列表区 (MessageList)                                    │
│  输入框区 (InputArea)                                        │
│    ├── 图片上传按钮                                          │
│    ├── 模型选择下拉框 (自适应宽度)                           │
│    └── 发送/停止按钮                                         │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│               useKnowledgeChat.ts (业务逻辑)                 │
├─────────────────────────────────────────────────────────────┤
│  - 消息状态管理                                              │
│  - 流式请求处理                                              │
│  - 上下文压缩                                                │
│  - Token 估算                                                │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│             App Page / Domain Orchestration（可选）          │
├─────────────────────────────────────────────────────────────┤
│  - 挂载 KnowledgeChatPanel                                   │
│  - 补充领域上下文标签或页面级联动                            │
└─────────────────────────────────────────────────────────────┘
```

## SOP 经验库交互

### 前台拼装方式

- 前台左侧经验库入口由 [SOPSidebar.vue](file:///d:/AI/AnGIneer/apps/web-console/src/layouts/sidebar/SOPSidebar.vue) 承接，内部挂载 [SOPTree.vue](file:///d:/AI/AnGIneer/packages/docs-ui/src/components/common/widgets/SOPTree.vue)。
- 经验库树状态由 [useSopTree.ts](file:///d:/AI/AnGIneer/packages/docs-ui/src/composables/useSopTree.ts) 提供，当前以内置示例树组织设计流程与能力测算节点。
- 右侧聊天区在 [App.vue](file:///d:/AI/AnGIneer/apps/web-console/src/App.vue) 中按左侧 Tab 在 [KnowledgeChatPanel.vue](file:///d:/AI/AnGIneer/packages/docs-ui/src/components/common/widgets/KnowledgeChatPanel.vue) 和 [SOPChatPanel.vue](file:///d:/AI/AnGIneer/packages/docs-ui/src/components/common/widgets/SOPChatPanel.vue) 间切换。
- `SOPChatPanel` 复用 `BaseChat`，领域逻辑通过 `useSopChat` 收口，并在默认系统提示词中强调流程、步骤和约束回答。

### 前后台拼装方式

- 前台入口 [App.vue](file:///d:/AI/AnGIneer/apps/web-console/src/App.vue) 通过 [LeftPanel.vue](file:///d:/AI/AnGIneer/apps/web-console/src/layouts/LeftPanel.vue) 在「知识」Tab 挂载 `KnowledgeTree`，使用只读参数集。
- 后台入口 [KnowledgeManage.vue](file:///d:/AI/AnGIneer/apps/admin-console/src/views/KnowledgeManage.vue) 使用 TriplePane 三栏编排，左侧 `KnowledgeTree`、中心预览、右侧 `KnowledgeChatPanel`。
- 基础树能力由 [SmartTree.vue](file:///d:/AI/AnGIneer/packages/ui-kit/src/components/common/SmartTree.vue) 提供，知识域树封装由 [KnowledgeTree.vue](file:///d:/AI/AnGIneer/packages/docs-ui/src/components/common/widgets/KnowledgeTree.vue) 承接。
- 基础聊天能力由 [BaseChat.vue](file:///d:/AI/AnGIneer/packages/ui-kit/src/components/common/BaseChat.vue) 提供，知识域聊天封装由 [KnowledgeChatPanel.vue](file:///d:/AI/AnGIneer/packages/docs-ui/src/components/common/widgets/KnowledgeChatPanel.vue) 承接。
- 后台外层“包一层”是业务编排容器，负责文件上传、解析链路、树操作、拖拽重排等流程聚合，属于合理分层。

### KnowledgeChatPanel Props

| Prop | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `defaultModel` | `string` | - | 默认模型 |
| `placeholder` | `string` | `'输入消息...'` | 输入框占位符 |
| `contextItems` | `ContextItem[]` | `[]` | 上下文引用项 |
| `title` | `string` | `'AI 助手'` | 标题 |
| `icon` | `string` | - | 图标 |
| `systemPrompt` | `string` | - | 系统提示词 |
| `showContextInfo` | `boolean` | `false` | 是否显示上下文信息 |
| `showSystemMessages` | `boolean` | `false` | 是否显示系统消息 |

### KnowledgeChatPanel Events

| Event | 参数 | 说明 |
|-------|------|------|
| `send` | `(message: string, model: string)` | 发送消息时触发 |
| `ready` | `()` | 组件就绪时触发 |

### KnowledgeChatPanel Slots

| Slot | 参数 | 说明 |
|------|------|------|
| `header` | - | 自定义头部 |
| `empty` | - | 空状态自定义内容 |

### 使用示例

```vue
<template>
  <KnowledgeChatPanel
    title="AI 助手"
    placeholder="输入消息..."
    :show-context-info="true"
    @error="handleChatError"
  />
</template>

<script setup lang="ts">
import { KnowledgeChatPanel } from '@angineer/docs-ui'

/**
 * 处理聊天错误提示。
 */
const handleChatError = (error: Error) => {
  console.error('KnowledgeChatPanel error:', error)
}
</script>
```

### 输入框底部布局说明

底部操作栏采用三栏布局：

```css
.input-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.left-actions {   /* 上传按钮 - 固定 */
  flex-shrink: 0;
}

.center-actions { /* 模型选择 - 自适应 */
  flex: 1;
  max-width: 180px;
}

.right-actions {  /* 发送按钮 - 固定 */
  flex-shrink: 0;
}
```

---

## SmartTree 知识树系统

### 组件架构

```
┌─────────────────────────────────────────────────────────────┐
│                   SmartTree.vue (通用组件)                   │
├─────────────────────────────────────────────────────────────┤
│  搜索栏 (可选)                                               │
│    └── 输入框 + 新增文件夹按钮                               │
│  树内容区                                                    │
│    ├── 树节点                                                │
│    │   ├── 展开/收起图标                                     │
│    │   ├── 节点图标 (slot: icon)                             │
│    │   ├── 节点标题 (slot: title)                            │
│    │   ├── 状态标签 (slot: status)                           │
│    │   └── 操作按钮 (slot: actions)                          │
│    └── 空状态                                                │
│        └── 新增文件夹按钮                                    │
└─────────────────────────────────────────────────────────────┘
```

### 前后台拼装方式

- 前台入口 [App.vue](file:///d:/AI/AnGIneer/apps/web-console/src/App.vue) 通过 [LeftPanel.vue](file:///d:/AI/AnGIneer/apps/web-console/src/layouts/LeftPanel.vue) 在「知识」Tab 挂载 `KnowledgeTree`，使用只读参数集。
- 后台入口 [KnowledgeManage.vue](file:///d:/AI/AnGIneer/apps/admin-console/src/views/KnowledgeManage.vue) 使用 TriplePane 三栏编排，左侧 `KnowledgeTree`、中心预览、右侧 `KnowledgeChatPanel`。
- 基础树能力由 [SmartTree.vue](file:///d:/AI/AnGIneer/packages/ui-kit/src/components/common/SmartTree.vue) 提供，知识域封装由 [KnowledgeTree.vue](file:///d:/AI/AnGIneer/packages/docs-ui/src/components/common/widgets/KnowledgeTree.vue) 承接。
- 后台外层“包一层”是业务编排容器，负责文件上传、解析链路、树操作、拖拽重排等流程聚合，属于合理分层。

### Props

| Prop | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `treeData` | `SmartTreeNode[]` | `[]` | 树数据 |
| `showSearch` | `boolean` | `true` | 是否显示搜索框 |
| `searchPlaceholder` | `string` | `'搜索...'` | 搜索框占位符 |
| `showAddRootFolder` | `boolean` | `true` | 是否显示“新增一级目录”按钮 |
| `addRootFolderText` | `string` | `'新增文件夹'` | 空状态按钮文本 |
| `addRootFolderTitle` | `string` | `'新增一级目录'` | 搜索区按钮提示 |
| `showStatus` | `boolean` | `true` | 是否显示状态标签 |
| `draggable` | `boolean` | `false` | 是否可拖拽 |
| `allowAddFile` | `boolean` | `true` | 是否允许添加文件 |
| `allowedFileTypes` | `string[]` | `['.pdf']` | 允许上传文件类型 |
| `showIcon` | `boolean` | `true` | 是否显示图标 |
| `emptyText` | `string` | `'暂无数据'` | 空状态文本 |
| `loading` | `boolean` | `false` | 加载状态 |

### Events

| Event | 参数 | 说明 |
|-------|------|------|
| `select` | `(keys: string[], nodes: SmartTreeNode[])` | 选中节点 |
| `add-folder` | `(node: SmartTreeNode \| null)` | 添加文件夹，null 表示根目录 |
| `add-file` | `(node: SmartTreeNode)` | 添加文件 |
| `delete` | `(node: SmartTreeNode)` | 删除节点 |
| `rename` | `(node: SmartTreeNode)` | 重命名节点 |
| `view` | `(node: SmartTreeNode)` | 查看节点 |
| `drop` | `(info: DropInfo)` | 拖拽完成 |
| `search` | `(value: string)` | 搜索 |
| `file-drop` | `(files: File[], targetFolder: SmartTreeNode \| null)` | 文件拖拽上传 |
| `drop-invalid` | `(reason: string)` | 非法拖拽回调 |
| `drop-root` | `(dragNodeKey: string)` | 拖拽到根目录回调 |

### Slots

| Slot | 参数 | 说明 |
|------|------|------|
| `icon` | `{ node: SmartTreeNode }` | 自定义图标 |
| `title` | `{ node: SmartTreeNode, title: string }` | 自定义标题 |
| `status` | `{ node: SmartTreeNode }` | 自定义状态标签 |
| `actions` | `{ node: SmartTreeNode }` | 自定义操作按钮 |
| `empty` | - | 自定义空状态 |

### 使用示例

#### 前台只读模式

```vue
<template>
  <SmartTree
    :tree-data="treeData"
    :show-search="true"
    :show-add-root-folder="false"
    :show-status="false"
    :draggable="false"
    :allow-add-file="false"
    @select="onSelect"
  >
    <template #icon="{ node }">
      <FolderOutlined v-if="node.isFolder" style="color: #faad14" />
      <FileTextOutlined v-else style="color: #1890ff" />
    </template>
  </SmartTree>
</template>

<script setup>
import { SmartTree } from '@angineer/docs-ui'
import { FolderOutlined, FileTextOutlined } from '@ant-design/icons-vue'
</script>
```

#### 后台管理模式

```vue
<template>
  <SmartTree
    :tree-data="treeData"
    :show-search="true"
    :show-add-root-folder="true"
    :show-status="true"
    :draggable="true"
    :allow-add-file="true"
    :allowed-file-types="['.pdf', '.doc', '.docx', '.md']"
    @select="onSelect"
    @add-folder="onAddFolder"
    @add-file="onAddFile"
    @delete="onDelete"
    @drop="onDrop"
    @drop-root="onDropRoot"
  >
    <template #icon="{ node }">
      <FolderOutlined v-if="node.isFolder" style="color: #faad14" />
      <FilePdfOutlined v-else-if="getFileType(node?.title) === 'pdf'" style="color: #ff4d4f" />
      <FileWordOutlined v-else-if="getFileType(node?.title) === 'word'" style="color: #1890ff" />
      <FileMarkdownOutlined v-else-if="getFileType(node?.title) === 'markdown'" style="color: #13c2c2" />
      <FileTextOutlined v-else style="color: #8c8c8c" />
    </template>
    <template #status="{ node }">
      <a-tag :color="node.visible ? 'green' : 'default'">
        {{ node.visible ? '共享' : '本地' }}
      </a-tag>
    </template>
  </SmartTree>
</template>
```

### 拖拽处理

```typescript
const onTreeDrop = async (info: any) => {
  const { dragNode, node: dropNode } = info
  if (!dragNode || !dropNode) return

  if (!info.dropToGap && !dropNode.dataRef?.isFolder) return

  const newParentId = !info.dropToGap
    ? dropNode.key
    : (dropNode.dataRef?.parentId || null)

  const siblings = calcSiblingsAfterDrop()
  await Promise.all(
    siblings.map((item, index) =>
      knowledgeApi.updateNode(item.key, { parent_id: newParentId, sort_order: index })
    )
  )
  await loadNodes(dragNode.key)
}

const onDropRoot = async (dragNodeKey: string) => {
  await knowledgeApi.updateNode(dragNodeKey, { parent_id: null, sort_order: rootLastIndex })
  await loadNodes(dragNodeKey)
}
```

### 可验收能力清单（当前实现）

- 目录：支持根目录/任意父级创建、重命名、递归删除。
- 文件：支持上传、删除、重命名、查看、解析状态展示。
- 类型：后台上传策略统一为 `.pdf/.doc/.docx/.md`，前后端双重校验。
- 搜索：按标题过滤节点并自动展开命中路径。
- 拖拽：支持拖入目录、同级前后重排、拖到根目录，阻止拖入文件和拖入自身后代。
- 交互：上传后自动刷新并定位选中新文件；树有数据时不再错误显示空状态。

### 持久化与数据库

- 知识树服务已使用 SQLite 持久化，见 [knowledge_service.py](file:///d:/AI/AnGIneer/services/docs-core/src/docs_core/knowledge_service.py)。
- 默认数据库文件已拆分为：`data/knowledge_base/knowledge_meta.sqlite` 与 `data/knowledge_base/knowledge_index.sqlite`。
- `nodes` 表含 `sort_order` 字段，支持同级顺序持久化与重排。
- 建议使用“整体后端统一数据库”，不建议为 SmartTree 单独建独立数据库。

---

## API 端点速查

### AI 对话

| 端点 | 方法 | 功能 | 位置 |
|------|------|------|------|
| `/api/chat` | POST | AI 流式对话（SSE） | [main.py](file:///d:/AI/AnGIneer/apps/api-server/main.py#L325) |
| `/api/llm_configs` | GET | 获取模型列表 | [main.py](file:///d:/AI/AnGIneer/apps/api-server/main.py#L310) |

**KnowledgeChatRequest:**
```typescript
{
  message: string                 // 当前用户输入
  history: KnowledgeChatMessage[] // 历史消息
  model?: string                  // 模型名称
  mode?: 'chat' | 'reasoning' | 'vision'
  context?: { references?: string[] }
}
```

**SSE 事件类型:**
- `start`: 开始事件，含 messageId
- `chunk`: 增量内容
- `end`: 结束事件，含 usage 统计
- `error`: 错误事件

### 知识树管理

| 端点 | 方法 | 功能 | 位置 |
|------|------|------|------|
| `/api/knowledge/libraries` | GET | 获取知识库列表 | [main.py](file:///d:/AI/AnGIneer/apps/api-server/main.py#L1010) |
| `/api/knowledge/libraries` | POST | 创建知识库 | [main.py](file:///d:/AI/AnGIneer/apps/api-server/main.py#L1016) |
| `/api/knowledge/nodes` | GET | 获取节点列表 | [main.py](file:///d:/AI/AnGIneer/apps/api-server/main.py#L1032) |
| `/api/knowledge/nodes` | POST | 创建节点 | [main.py](file:///d:/AI/AnGIneer/apps/api-server/main.py#L1038) |
| `/api/knowledge/nodes/{id}` | PATCH | 更新节点 | [main.py](file:///d:/AI/AnGIneer/apps/api-server/main.py#L1058) |
| `/api/knowledge/nodes/{id}` | DELETE | 删除节点 | [main.py](file:///d:/AI/AnGIneer/apps/api-server/main.py#L1067) |
| `/api/knowledge/upload` | POST | 上传文档 | [main.py](file:///d:/AI/AnGIneer/apps/api-server/main.py#L1077) |
| `/api/knowledge/parse` | POST | 解析文档 | [main.py](file:///d:/AI/AnGIneer/apps/api-server/main.py#L1113) |
| `/api/knowledge/document/{library_id}/{doc_id}` | GET | 获取文档内容 | [main.py](file:///d:/AI/AnGIneer/apps/api-server/main.py#L1169) |

---

## 数据模型

### SCHEMA_VERSION (文档解析架构版本)

为了确保文档解析产物在不同迭代版本间的结构一致性，项目引入了 `SCHEMA_VERSION`。

- **定义**: `SCHEMA_VERSION` 代表 Docs 模块解析产物的结构版本（而非特定的 PDF 或 Markdown 文件版本）。
- **作用范围**:
  - **数据库层**: 存储在 `libraries`, `nodes`, `parse_tasks` 表中。
  - **解析引擎**: 当 MinerU 解析逻辑、产物文件夹结构或元数据字段发生重大变更时，需提升此版本号。
  - **兼容性检查**: 系统可通过对比数据库中的版本号，判断历史解析产物是否需要重新解析或执行迁移。
- **当前版本**: `1.0.0`

### 数据库表结构 (Docs 模块)

### SmartTreeNode (前端)

```typescript
interface SmartTreeNode {
  key: string           // 唯一标识
  title: string         // 显示名称
  isFolder?: boolean    // 是否为文件夹
  isLeaf?: boolean      // 是否为叶子节点
  parentId?: string     // 父节点 ID
  filePath?: string     // 源文件路径
  status?: 'pending' | 'processing' | 'completed' | 'failed'
  visible?: boolean     // 是否可见（共享/本地）
  sortOrder?: number    // 同级排序
  children?: SmartTreeNode[]
}
```

### KnowledgeNode (后端)

```python
class KnowledgeNode(BaseModel):
    id: str
    title: str
    type: str              # 'folder' | 'document'
    status: str = 'pending' # pending | processing | completed | failed
    visible: bool = False
    parent_id: Optional[str] = None
    library_id: str
    file_path: Optional[str] = None
    sort_order: int = 0
```

### ChatMessage

```typescript
interface ChatMessage {
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp?: number
}
```

---

## 状态说明

| 状态 | 说明 | 适用对象 |
|------|------|----------|
| `pending` | 待处理（已上传未解析） | 文件 |
| `processing` | 解析中 | 文件 |
| `completed` | 已完成 | 文件 |
| `failed` | 解析失败 | 文件 |
| `visible` | 共享/本地标识 | 文件 |

**注意**: 文件夹不显示状态标签，仅文件显示。

---

## 开发提示

### 前端

1. **组件导入优先使用 packages**
   ```typescript
   import { KnowledgeTree, KnowledgeChatPanel } from '@angineer/docs-ui'
   import { AppHeader, Panel, SmartTree } from '@angineer/ui-kit'
   ```

2. **树数据处理使用 useKnowledgeTree**
   ```typescript
   import { useKnowledgeTree } from '@angineer/docs-ui'
   const { buildTree, findNode } = useKnowledgeTree()
   ```

3. **主题统一使用 useTheme**
   ```typescript
   import { useTheme } from '@angineer/ui-kit'
   const { isDark } = useTheme()
   ```

### Python

1. **函数外增加一句话注释**
   ```python
   # 更新知识库节点
   def update_node(self, node_id: str, **kwargs) -> Optional[KnowledgeNode]:
       """更新节点"""
       ...
   ```

2. **使用 Type Hints**
   ```python
   def create_node(self, node: KnowledgeNode) -> KnowledgeNode:
       ...
   ```
