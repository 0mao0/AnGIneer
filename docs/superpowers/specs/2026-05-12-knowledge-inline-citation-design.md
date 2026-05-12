# 知识库内联引用设计

> 日期：2026-05-12
> 状态：已确认，待实施

## 1. 目标

本次设计聚焦一个能力：在 `AIChat` 输入框与文档编辑区中，通过 `@` 从当前知识库检索并插入知识条文引用。

该能力需要同时满足以下结果：

- 用户输入如 `@表6.4.2-1` 时，可以从当前知识库全库搜索候选条文。
- 用户确认后，正文中显示为蓝色超链接样式，而不是直接铺开完整条文。
- 鼠标悬停时弹出预览卡片，能渲染正文、表格、公式、图片。
- 点击引用时，可以复用现有知识定位能力，跳转到原文对应位置。
- 后续给 `LLM` 提供上下文时，优先使用用户显式确认过的真实引用结果，降低模型自行检索带来的幻觉风险。

本次不重做整套编辑器体系，不把现有输入框整体迁移到富文本编辑器。

## 2. 已确认决策

- 生效范围仅限：
  - `AIChat` 输入框
  - 文档编辑区 / 正文编辑区
- `@` 检索范围默认是当前知识库全库检索，不采用“当前文档优先”。
- 插入后的显示形态为“正文显示蓝色链接 + JSON 独立保存 citation 元数据”。
- 不把完整引用内容直接塞进正文原文。
- `表 / 图 / 公式` 的 hover 预览与富媒体渲染应下沉到 `ui-kit`，供其他模块复用。

## 3. 方案对比

### 方案 A：纯文本增强

说明：

- `@` 仅用于帮助用户搜索条文。
- 确认后把结果写成普通文本。
- hover 或 LLM 注入时再尝试从文本反推引用。

优点：

- 改动最小。

缺点：

- 用户一旦修改文本，引用关系就容易丢失。
- `LLM` 很难稳定获得“用户明确引用的是哪条证据”。
- `表 / 图 / 公式` 不适合仅靠纯文本表达。

### 方案 B：正文显示 + 独立 citation 元数据

说明：

- 正文只显示蓝色链接文本。
- 引用对象单独保存到 `citations[]`。
- hover、点击定位、LLM 注入都基于 citation 元数据。

优点：

- 符合“用户自然阅读 + 系统稳定追踪证据”的双重目标。
- 与现有 `AIChatCitation`、`Reference`、`useKnowledgeCitation()` 的对象化方向一致。
- 适合承载 `table_html`、`math_content`、`image_paths` 等富媒体信息。

缺点：

- 需要额外维护正文锚点与 citation 元数据之间的绑定关系。

### 方案 C：富文本实体编辑器

说明：

- 将引用做成真正的内联实体或 chip。
- 编辑器内部直接保存结构化节点。

优点：

- 交互最强，引用最不容易被破坏。

缺点：

- 当前仓库主要仍是 `textarea + markdown` 路线。
- 改造范围会明显超出本次目标。

推荐采用 `方案 B`。

## 4. 现状与复用基础

当前仓库已经存在可直接复用的能力：

- `packages/ui-kit/src/types/chat.ts`
  - 已有 `AIChatCitation` 与 `BaseChatCitation`。
- `packages/docs-ui/src/composables/useKnowledgeCitation.ts`
  - 已具备基于 citation 跳转到知识文档与结构化块的能力。
- `packages/ui-kit/src/utils/markdown.ts`
  - 已具备正文、表格、公式、图片的 HTML 渲染基础。
- `packages/docs-ui/src/types/reference.ts`
  - 已有早期 `Reference` 模型，可扩展为更通用的引用基协议。
- `packages/ui-kit/src/components/common/BaseChat.vue`
  - 已能展示 AI 回答引用列表，但当前是“回答后展示”，不是“正文内联引用”。

当前缺失的核心能力有三类：

- 输入阶段的 `@` 检索与候选确认。
- 正文内联 citation 的数据模型与渲染组件。
- 保存链路与 `LLM` 注入链路中的“显式用户引用”传递。

## 5. 总体设计

### 5.1 能力分层

本次能力按三层落地：

- `ui-kit`
  - 承担通用 citation 渲染与 hover 卡片。
- `docs-ui`
  - 承担知识库引用检索、候选适配、引用插入、引用定位、失配校验。
- `apps/*`
  - 决定哪些输入框启用 `@`，以及业务对象如何保存 `{ content, citations }`。

### 5.2 主链路

用户交互主链路如下：

1. 用户在 `AIChat` 或文档编辑区输入 `@`。
2. 前端进入“知识引用模式”，采集 `@` 后的搜索关键词。
3. 前端调用专门的知识引用检索接口，在当前知识库全库搜索候选项。
4. 用户通过键盘或鼠标确认候选引用。
5. 编辑区插入蓝色链接文本，同时写入 `citations[]`。
6. hover 时弹出 citation 卡片，渲染正文或富媒体内容。
7. 点击时复用 `useKnowledgeCitation()` 跳转到原文。
8. 保存或发送给 AI 时，显式携带 `citations[]`，后端将其作为高优先级证据注入 `LLM` 上下文。

## 6. 数据模型设计

### 6.1 设计原则

- `content` 负责用户可读文本。
- `citations[]` 负责结构化证据对象。
- citation 不能只存一个 `id`，必须同时保留：
  - 定位信息
  - 展示信息
  - 证据快照
- 这样即使知识库重解析或块 ID 漂移，历史正文仍可继续展示并提示重新确认。

### 6.2 推荐保存结构

```ts
interface InlineCitationDocumentPayload {
  content: string
  citations: CitationBinding[]
}
```

```ts
interface CitationBinding {
  id: string
  label: string
  triggerText: string
  range: {
    start: number
    end: number
  }
  reference: CitationReference
}

interface CitationReference {
  targetId: string
  targetType: 'content' | 'table' | 'formula' | 'figure'
  libraryId: string
  docId: string
  docTitle: string
  pageIdx?: number
  sectionPath?: string
  snippet?: string
  content?: string
  richMedia?: {
    tableHtml?: string
    mathContent?: string
    imagePath?: string
    imagePaths?: string[]
  }
  score?: number
  sourceVersion?: string
}
```

### 6.3 关键字段说明

- `label`
  - 正文中显示给用户看的蓝链文本，例如 `表6.4.2-1`。
- `triggerText`
  - 用户原始输入的搜索关键字，用于排查引用来源与后续推荐优化。
- `range.start/end`
  - 绑定 `content` 中的可见锚点文本范围，用于渲染、hover、点击与失配检测。
- `reference.content`
  - 保存正文证据快照。
- `reference.richMedia`
  - 保存表格、公式、图片等富媒体快照。
- `sourceVersion`
  - 预留给后续知识库重解析后的版本校验能力。

### 6.4 为什么不用“把引用塞进原文”

- 正文会被持续编辑，不适合作为可靠证据载体。
- 完整条文写入正文会破坏阅读体验。
- `表 / 图 / 公式` 不是天然的纯文本对象。
- 后续 `LLM` 需要的不是“看起来像引用的一段文字”，而是“用户明确确认过的证据对象”。

## 7. 前端交互设计

### 7.1 触发与检索

- 在 `AIChat` 输入框和文档编辑区监听 `@`。
- 当检测到光标前出现 `@关键词` 时，打开知识引用候选面板。
- 默认在当前知识库全库检索，不因当前文档上下文缩小范围。

### 7.2 候选面板

候选项至少展示以下信息：

- 引用名
- 类型：`正文 / 表格 / 公式 / 图片`
- 文档名
- 页码
- 层级路径
- 片段预览

交互要求：

- 支持 `上下方向键` 选择。
- 支持 `Enter` 确认。
- 支持 `Esc` 关闭。
- 支持鼠标点击确认。

### 7.3 插入行为

- 确认后，正文中仅插入蓝色链接文本。
- 不直接插入完整条文全文。
- 同步写入一条 `CitationBinding`。
- 插入后，光标继续停留在可编辑位置，保证写作流畅。

### 7.4 Hover 与点击

- hover：打开 citation 预览卡片。
- 点击：触发已有知识定位链路，跳转到原文对应位置。
- 预览卡片底部保留“打开原文”或等效动作入口。

### 7.5 编辑失配规则

- 如果用户删除了完整锚点文本，对应 citation 自动移除。
- 如果用户仅修改了锚点文本的一部分，citation 进入“失配”状态。
- 失配态可以继续显示快照，但要提示用户重新确认。
- 首版不做静默自动修复，避免误绑定。

## 8. 共享组件设计

### 8.1 下沉到 `ui-kit` 的组件

建议新增以下通用组件：

- `packages/ui-kit/src/components/common/CitationInline.vue`
  - 负责蓝色链接、失配态样式、hover/click 事件。
- `packages/ui-kit/src/components/common/CitationPopover.vue`
  - 负责弹层壳子、定位、宽度、加载态、操作按钮。
- `packages/ui-kit/src/components/common/CitationRichContent.vue`
  - 负责正文、表格、公式、图片的统一渲染。

### 8.2 为什么要下沉

- `AIChat`、文档编辑区、未来其他模块都会展示 citation。
- 现有表格、公式、图片渲染逻辑已散落在 `BaseChat.vue` 与 `markdown.ts`，继续堆在业务层会放大重复实现。
- `ui-kit` 只消费通用 citation 数据结构，不感知知识库业务细节。

## 9. `docs-ui` 适配层设计

建议新增或扩展以下能力：

- `packages/docs-ui/src/composables/useKnowledgeReferenceSearch.ts`
  - 负责 `@` 检索、候选列表转换、插入后生成 `CitationBinding`。
- `packages/docs-ui/src/utils/reference.ts`
  - 负责 range 维护、文本替换、序列化、反序列化、失配检测。
- 扩展 `packages/docs-ui/src/types/reference.ts`
  - 将早期 `Reference` 收敛成可服务 `AIChat`、文档编辑区、hover 卡片的统一协议。

同时保留并复用：

- `useKnowledgeCitation()`
  - 继续承担点击 citation 后的文档定位职责。

## 10. 后端接口设计

### 10.1 新增专用检索接口

推荐新增：

`POST /api/knowledge/references/search`

请求体建议：

```json
{
  "library_id": "lib_xxx",
  "query": "表6.4.2-1",
  "limit": 10,
  "types": ["content", "table", "formula", "figure"],
  "current_doc_id": "optional_doc_id"
}
```

说明：

- `current_doc_id` 只用于排序加权，不用于缩小检索范围。
- `types` 可用于筛选候选类别，但首版可默认全开。

### 10.2 返回结构

接口直接返回可插入的 citation 候选 DTO，至少包含：

- `target_id`
- `target_type`
- `library_id`
- `doc_id`
- `doc_title`
- `page_idx`
- `section_path`
- `label`
- `snippet`
- `content`
- `score`
- `rich_media`
- `source_version`

### 10.3 排序策略

检索排序遵循以下优先级：

1. 编号或标题精确命中
2. `section_path / snippet` 的关键词命中
3. dense / hybrid 召回分数

这样可以保证 `表6.4.2-1`、`公式3.1.5-2` 这类工程编号的命中稳定性。

## 11. 保存与序列化链路

### 11.1 AIChat

`AIChat` 发送消息时，不仅发送纯文本 `query`，还要附带：

- `inline_citations[]`

其语义是“用户在本次输入中显式确认的证据对象”。

### 11.2 文档编辑区

文档正文保存对象从单纯字符串扩展为：

```ts
{
  content: string
  citations?: CitationBinding[]
}
```

如果当前文档块接口仅支持字符串，需扩展为兼容型 schema，而不是另起平行接口。

### 11.3 旧数据兼容

- 旧数据没有 `citations` 时，一律按空数组处理。
- 旧内容展示与编辑行为不应受到影响。

## 12. LLM 注入策略

### 12.1 核心原则

- 用户显式 `@` 的 citation 优先级高于普通检索召回。
- `LLM` 获取的是明确证据对象，而不是再去猜数据库里的候选结果。

### 12.2 注入方式

后端收到 `query + inline_citations[]` 后，应先将引用对象转换为高置信证据片段，再拼入 `prompt/context` 前部。

建议注入结构包含：

- `label`
- `doc_title`
- `page_idx`
- `section_path`
- `content`
- `rich_media_summary`

### 12.3 富媒体处理

- 表格：除 `table_html` 外，建议补一份可供模型直接消费的 `table_text`。
- 公式：保留原始 `math_content`。
- 图片：首版至少提供 `caption` 或附近正文，不依赖主链视觉理解。

## 13. 风险与边界

- 当前输入体系不是富文本编辑器，因此首版采用“文本范围绑定”而不是“不可破坏的实体编辑”。
- 用户编辑锚点后可能出现 `content` 与 `citations[]` 失配，首版只做检测与提示，不做自动修复。
- 文档重解析后块 ID 可能漂移，因此 citation 必须保存快照而不是只存 ID。
- 本次不扩展到所有输入框，只覆盖已确认的两类输入区域。
- `@` 引用检索接口与普通问答接口分离，避免语义混乱。

## 14. 预期改动边界

预计主要涉及以下区域：

- `packages/ui-kit`
  - citation 内联组件
  - citation 卡片组件
  - citation 富媒体渲染组件
  - 现有 `markdown.ts` 的渲染能力复用
- `packages/docs-ui`
  - reference 类型扩展
  - `@` 引用检索 composable
  - range 与失配工具函数
  - 与 `useKnowledgeCitation()` 的接线
- `apps/admin-console`
  - `KnowledgeManage.vue` 接入文档编辑区 citation 能力
- `packages/ui-kit/src/components/common/AIChat.vue`
  - 接入内联引用输入与发送时的 `inline_citations[]`
- `services/api-server`
  - 新增 `references/search` 路由
- `services/docs-core`
  - 提供引用候选检索与富媒体快照组装

本次设计不要求：

- 重做整套编辑器
- 重做全部知识问答接口
- 重做图片视觉理解主链

## 15. 验收标准

实施后至少满足以下结果：

- 在 `AIChat` 输入框中输入 `@表6.4.2-1` 可以检索当前知识库全库候选。
- 在文档编辑区中可以插入相同形态的蓝色引用文本。
- hover 时能稳定展示正文或 `表 / 图 / 公式` 富媒体内容。
- 点击引用时可以跳到原文对应位置。
- 保存正文时能稳定落库 `content + citations[]`。
- 发送 AI 消息时，后端能收到用户显式确认的 `inline_citations[]` 或等价字段。
- 未使用 citation 的旧数据与旧页面行为不回归。

## 16. 实施建议

建议按以下顺序实施：

1. 先统一 citation 数据协议。
2. 再下沉 `ui-kit` 渲染组件。
3. 接着完成 `@` 检索与候选确认。
4. 然后接入 `AIChat` 与文档编辑区。
5. 最后打通保存链路与 `LLM` 注入链路。

这样可以先稳定模型与组件边界，再逐步接线业务页面和后端能力。
