# SOP Step 描述内联引用设计

> 日期：2026-05-12
> 状态：已确认，待实施
> 关联设计：`docs/superpowers/specs/2026-05-12-knowledge-inline-citation-design.md`

## 1. 目标

本次设计聚焦一个扩展能力：让 `SOP Step` 的描述字段具备与 `AIChat` 输入区一致的知识库 `@` 内联引用能力。

能力目标包括：

- 在 `SOPPropertyPanel` 的步骤描述编辑区支持 `@` 检索知识条文。
- 插入后在编辑态显示为蓝色超链接，而不是纯文本。
- hover 时弹出富媒体预览卡片，支持正文、表格、公式、图片。
- 点击蓝链时复用现有知识定位能力，跳转到原文。
- `SOPStepNode` 节点卡片展示态也能回显蓝链，并支持 hover 与点击定位。
- 步骤描述保存为结构化对象，而不是再退回纯字符串。

本次不是给 SOP 再做一套平行引用系统，而是让 SOP 复用当前知识库内联引用的通用协议与组件。

## 2. 已确认决策

- 生效范围包括：
  - `packages/sop-ui/src/components/SOPPropertyPanel.vue`
  - `packages/sop-ui/src/components/SOPStepNode.vue`
- `SOP Step` 描述要具备“完整功能”，不是轻量版。
- `SopStep.description` 直接升级为新结构，不再兼容字符串。
- 后端 / 接口也同步切换为新结构，不保留旧字符串兼容分支。
- `SOPStepNode` 展示态也需要蓝链回显、hover 富媒体和点击定位。

## 3. 方案对比

### 方案 A：只替换编辑器，保存仍压平为字符串

说明：

- 编辑态使用 `InlineCitationEditor`。
- 保存时只落纯文本 `content`。

优点：

- 表面改动最小。

缺点：

- 保存后引用关系丢失。
- `SOPStepNode` 无法稳定回显蓝链。
- 与“完整功能”要求冲突。

### 方案 B：步骤描述全链路结构化

说明：

- `SOPPropertyPanel` 编辑态、`SOPStepNode` 展示态、序列化、后端接口全部使用统一结构：

```ts
{
  content: string
  citations: CitationBinding[]
}
```

优点：

- 与 `AIChat` 的引用能力保持一致。
- 展示、保存、hover、定位共用一套协议。
- 后续可以把 SOP 描述中的显式引用继续透传给 LLM 或执行链路。

缺点：

- 要同时调整 `types`、`normalize`、`serialize`、组件和接口。

### 方案 C：新增平行字段承载 citation

说明：

- 保留 `description: string`。
- 新增 `description_detail` 或等价字段。

优点：

- 迁移过程更保守。

缺点：

- 会产生双字段并存和数据同步成本。
- 与“直接升级为新结构，不兼容字符串”的已确认决策冲突。

推荐采用 `方案 B`。

## 4. 现状与复用基础

当前仓库中与本次能力最直接相关的现状如下：

- `packages/sop-ui/src/components/SOPPropertyPanel.vue`
  - 步骤描述当前是 `a-textarea`，仅支持纯文本编辑。
- `packages/sop-ui/src/components/SOPStepNode.vue`
  - 节点卡片当前只展示 `description` 的纯文本截断。
- `packages/sop-ui/src/types/sop.ts`
  - `RawSopStep.description` 与 `SopStep.description` 都仍是字符串。
- `packages/ui-kit/src/components/common/InlineCitationEditor.vue`
  - 已实现完整编辑态 `@` 引用能力。
- `packages/ui-kit/src/components/common/CitationInline.vue`
  - 已实现展示态蓝链、hover 和点击行为。
- `packages/ui-kit/src/components/common/CitationRichContent.vue`
  - 已实现表、图、公式、正文的统一渲染。
- `packages/ui-kit/src/utils/citation.ts`
  - 已具备 `CitationBinding`、segment 构建、range 维护等工具能力。

因此，本次不应重新实现 SOP 专用版本，而应把 `sop-ui` 接到已有 `ui-kit` / 知识引用协议上。

## 5. 总体设计

### 5.1 分层

本次能力按三层落地：

- `ui-kit`
  - 保持通用 citation 编辑、展示与 hover 组件。
- `sop-ui`
  - 负责 SOP 领域类型、编辑器接线、节点展示与保存态组装。
- `services/*`
  - 负责 SOP 数据持久化结构切换，以及知识引用定位所需字段透传。

### 5.2 主链路

用户主链路如下：

1. 用户在 `SOPPropertyPanel` 的描述编辑区输入 `@`。
2. 编辑器进入知识引用模式，拉起候选面板。
3. 用户确认引用后，步骤描述中插入蓝色超链接，并写入 `citations[]`。
4. hover 蓝链时，弹出富媒体预览卡片。
5. 点击蓝链时，复用知识定位能力跳转原文。
6. 点击“保存”后，`SopStep.description` 按结构化对象写回 SOP 数据。
7. `SOPStepNode` 读取相同结构，在节点卡片中回显蓝链。

## 6. 数据模型设计

### 6.1 新步骤描述结构

推荐将 `SopStep.description` 固定为：

```ts
interface SopStepDescription {
  content: string
  citations: CitationBinding[]
}
```

对应 `SopStep`：

```ts
interface SopStep {
  id: string
  name?: string
  name_zh?: string
  name_en?: string
  description: SopStepDescription
  execution: SopExecution
  next_step_id?: string
  on_failure?: string
  analysis_status?: string
  ui_meta?: SopStepUiMeta
}
```

### 6.2 原始数据结构

由于已确认“不兼容字符串”，原始持久化结构也直接切到新对象：

```ts
interface RawSopStep {
  id: string
  name?: string
  name_zh?: string
  name_en?: string
  description?: SopStepDescription
  execution?: Partial<SopExecution> | null
  tool?: string
  inputs?: Record<string, any>
  outputs?: Record<string, string>
  next_step_id?: string
  on_failure?: string
  analysis_status?: string
  ui_meta?: SopStepUiMeta | null
}
```

### 6.3 关键原则

- `description.content` 负责用户可读文本。
- `description.citations[]` 负责结构化证据对象。
- 节点展示、编辑回填、保存持久化都只认这一种结构。
- 不做字符串兼容分支，避免双模型长期并存。

## 7. 前端交互设计

### 7.1 `SOPPropertyPanel` 编辑态

`SOPPropertyPanel` 中的描述区由 `a-textarea` 替换为 `InlineCitationEditor`。

要求：

- 支持输入 `@` 检索知识条文。
- 支持工具栏 `@` 按钮插入。
- 支持蓝色链接显示。
- 支持 hover 富媒体预览。
- 支持点击引用跳转原文。
- 支持失配态展示。

### 7.2 `SOPStepNode` 展示态

节点卡片中的描述区不再简单显示 `truncatedDesc` 字符串，而是基于 `description.content + citations[]` 构建 segment。

要求：

- 引用部分继续显示蓝链。
- hover 继续显示富媒体卡片。
- 点击继续触发知识定位。
- 卡片内容保持紧凑，不把整段富媒体直接铺开在节点内部。

### 7.3 展示裁切策略

节点卡片仍需控制信息密度，因此展示态采用 segment-aware 截断：

- 按可见字符数裁切整体展示长度。
- 不能把蓝链引用文本从中间裁断。
- 若末尾超长，则在完整 segment 后追加 `...`。

这样既保留蓝链完整性，也避免节点卡片高度失控。

## 8. 类型与序列化改造

### 8.1 `sop.ts`

`packages/sop-ui/src/types/sop.ts` 需要同步改造以下内容：

- `RawSopStep.description`
- `SopStep.description`
- `normalizeSopStep()`
- `serializeSopStep()`
- 任何默认值、clone 值和空步骤初始化逻辑

### 8.2 旧逻辑移除

以下逻辑需要删除或改写：

- `mergeDescription()` 返回字符串的旧逻辑
- 任何 `description || ''` 的字符串回退
- 任何直接对 `step.description.length` 做判断的代码

## 9. 组件改动边界

### 9.1 `SOPPropertyPanel.vue`

预计改动：

- 描述区从 `a-textarea` 替换为 `InlineCitationEditor`
- `draft.description` 默认值改成结构化对象
- `hasChanges` 签名比较改成结构化 description 比较
- `handleSave()` 输出新结构
- `handleAiParse()` 传给 `parseStepDescription()` 时只取 `draft.description.content`

### 9.2 `SOPStepNode.vue`

预计改动：

- 移除 `truncatedDesc` 的纯字符串计算
- 使用 segment-aware 展示逻辑
- 引入 `CitationInline` 渲染蓝链
- 节点描述 hover / click 接到现有 citation 选择事件

### 9.3 事件传递

由于节点点击引用需要定位知识原文，需保证 `SOPStepNode` 上层链路能接收 citation 选择事件，并最终交给知识定位处理逻辑。

如果当前 `SOPFlowCanvas` 尚未承接这类事件，需要补一层事件透传。

## 10. 后端与接口设计

### 10.1 SOP 主数据接口

既然已确认“后端只支持新结构”，则：

- 创建 / 更新 SOP 的接口直接接收结构化 `description`
- 查询 SOP 的接口直接返回结构化 `description`
- 不提供字符串兼容回退

### 10.2 AI 解析接口

`parseStepDescription(description: string)` 仍保持只接受纯文本。

原因：

- AI 解析的目标是提取工具、输入、输出。
- 引用对象不应直接参与解析字段识别。

调用方式：

- 前端从 `draft.description.content` 取纯文本传入

### 10.3 数据迁移要求

由于不兼容字符串，必须同步处理历史 SOP 数据：

- 可通过离线迁移脚本将旧 `description: string` 转成：

```json
{
  "content": "旧描述文本",
  "citations": []
}
```

- 未迁移旧数据时，新前端 / 新后端不保证正常读取。

## 11. 风险与边界

- `SOPStepNode` 属于流程图节点，hover 交互需要避免影响拖拽和选中。
- 节点描述区空间有限，必须用 segment-aware 截断，不能直接复用完整编辑态。
- 后端已选择不兼容字符串，因此部署顺序要保证前后端与数据迁移同步完成。
- 本次只覆盖 `SOP Step.description`，不扩展到 SOP 顶层 `description` 或其他字段。

## 12. 验收标准

实施后至少满足以下结果：

- 在 `SOPPropertyPanel` 描述区输入 `@` 可检索当前知识库候选。
- 选择引用后，编辑态显示为蓝色超链接。
- hover 时能稳定显示正文 / 表格 / 公式 / 图片预览。
- 点击蓝链时能跳转到知识原文。
- 保存后，`SopStep.description` 落库为 `{ content, citations[] }`。
- 重新加载 SOP 后，`SOPPropertyPanel` 仍能正确回显蓝链。
- `SOPStepNode` 节点卡片中也能回显蓝链、hover 预览、点击定位。
- AI 解析功能继续可用，并以 `description.content` 为输入。

## 13. 实施建议

建议按以下顺序实施：

1. 先修改 `packages/sop-ui/src/types/sop.ts` 的数据模型与序列化协议。
2. 再接 `SOPPropertyPanel.vue` 的结构化编辑器。
3. 接着改 `SOPStepNode.vue` 的展示态蓝链回显与截断。
4. 然后打通节点点击引用的事件透传与知识定位。
5. 最后同步调整后端 SOP 读写结构与历史数据迁移。

这样可以先稳定前端单一数据模型，再扩展到展示、交互和持久化链路。
