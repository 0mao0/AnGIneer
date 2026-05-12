# SOP Step 描述内联引用实施计划

> 日期：2026-05-12
> 依据设计：`docs/superpowers/specs/2026-05-12-sop-step-inline-citation-design.md`
> 目标：让 SOP Step 的描述字段具备完整 `@` 内联引用能力（编辑态 + 展示态 + 持久化）。

## Phase 0：对齐协议与依赖

- 复用 `ui-kit` 的引用协议与编辑器：
  - `InlineCitationDraftValue`（`{ content, citations[] }`）
  - `CitationBinding` / `CitationReference`
  - `InlineCitationEditor`（编辑态）
  - `CitationInline` / `CitationPopover` / `CitationRichContent`（展示与 hover）
- `sop-ui` 新增引用检索 API 方法：
  - `POST /api/knowledge/references/search`

## Phase 1：前端类型与序列化切换（sop-ui）

### 1.1 类型切换

- 修改 `packages/sop-ui/src/types/sop.ts`
  - `RawSopStep.description` 从 `string` 改为 `InlineCitationDraftValue`
  - `SopStep.description` 从 `string` 改为 `InlineCitationDraftValue`（必填）
  - 移除 `mergeDescription()` 及 `notes` 拼接逻辑
  - `normalizeSopStep()` / `serializeSopStep()` 全面改为结构化 description
  - 新建 step 默认值改为 `{ content: '', citations: [] }`

### 1.2 API 层新增引用检索

- 修改 `packages/sop-ui/src/composables/useSopApi.ts`
  - 新增 `searchKnowledgeReferences(payload)` → 调用 `/api/knowledge/references/search`

验收：

- `sop-ui` 内部所有 `step.description` 相关类型编译通过，不再出现 string 的赋值点。

## Phase 2：编辑态接入（SOPPropertyPanel）

- 修改 `packages/sop-ui/src/components/SOPPropertyPanel.vue`
  - 用 `InlineCitationEditor` 替换描述区 `a-textarea`
  - `v-model` 绑定到 `draft.description`
  - 传入 `searchCitations` → 调用 `sopApi.searchKnowledgeReferences(...)` 并映射成候选
  - 监听 `selectCitation` → 向上透传事件，供宿主处理定位
  - AI 解析：改为只取 `draft.description.content` 传给 `/api/sops/steps/parse`
  - `hasChanges` 比较逻辑改为结构化 signature（基于 `content` 与 `citations[]`）

验收：

- 在步骤描述中输入 `@` 可检索、插入蓝链，hover 显示富媒体卡片。
- 保存后 `draft.description` 完整保留 `citations[]`。

## Phase 3：展示态接入（SOPStepNode）

- 修改 `packages/sop-ui/src/components/SOPStepNode.vue`
  - 从 `description.content + citations[]` 构建 segment（复用 `ui-kit` 的 `buildCitationSegments`）
  - 采用 segment-aware 截断（默认 60 字符）
  - 使用 `CitationInline` 渲染引用段，支持 hover / click
  - click 时向上 emit `selectCitation(binding.reference)`

验收：

- 流程图节点卡片描述里能看到蓝链，hover 出富媒体卡片，点击触发定位事件。

## Phase 4：宿主页接线（ExperienceManage）

- 修改 `apps/admin-console/src/views/ExperienceManage.vue`
  - 监听 `SOPPropertyPanel` / `SOPFlowCanvas` 中透出的 citation 选择事件
  - 采用 `router.resolve` + `window.open` 打开 `/knowledge` 页面，并通过 query 传递：
    - `doc_id` / `target_id` / `page_idx` / `target_type`

验收：

- 在经验页点击蓝链后，会打开知识库页面并尝试聚焦到对应条目。

## Phase 5：知识库页支持 query 聚焦（KnowledgeManage）

- 修改 `apps/admin-console/src/views/KnowledgeManage.vue`
  - 读取 route query（如 `doc_id`, `target_id`, `page_idx`）
  - `loadNodes(doc_id)` 后自动选中目标文档
  - 加载完成后调用 `docParsedWorkspaceRef.setActiveLinkedItem(target_id, { preferredPage })`

验收：

- 从经验页打开知识库页后，自动选中对应文档并高亮定位到目标引用条目。

## Phase 6：后端 SOP 结构切换（服务端）

- 修改 `services/angineer-core/src/angineer_core/base_contracts.py`
  - 引入 `StepDescription` 模型（`content + citations[]`）
  - `Step.description` 改为 `StepDescription | None`
  - 调整相关字符串使用点改为读取 `description.content`
- 修改 `services/angineer-core/src/angineer_core/dispatcher.py`
  - SOP trace 构建、prompt 拼接等位置改用 `description.content`
- 修改 `services/sop-core/src/sop_core/sop_parser.py`
  - LLM 解析生成 Step 时将 description 包装为 `{"content": "...", "citations": []}`
- `services/api-server/sop_routes.py`
  - 保持 steps 透传写入（前端已写入新结构）
  - `steps/parse` 继续仅接受字符串（由前端传 `content`）

验收：

- SOP 从 json 读取后可以正常加载为 `StepDescription`。
- SOP 执行链路不因 description 为对象而报错。

## Phase 7：验证

- 前端：类型诊断、手工验证 SOPPropertyPanel 与 SOPStepNode 的编辑/展示
- 联调：
  - 保存 SOP 后 JSON 中 step.description 为结构化对象
  - 点击 SOP 蓝链 → 打开 knowledge 页面 → 自动定位
- 回归：AI 解析仍可用（取 `description.content`）

