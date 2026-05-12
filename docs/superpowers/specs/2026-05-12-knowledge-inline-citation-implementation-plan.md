# 知识库内联引用实施计划

> 日期：2026-05-12
> 来源设计：`docs/superpowers/specs/2026-05-12-knowledge-inline-citation-design.md`
> 状态：实施计划初稿

## 1. 计划目标

本计划基于已确认的《知识库内联引用设计》，把能力拆成可落地的实现阶段、文件改动边界、联调顺序与验收方法。

本次计划重点解决三个实施层面的真实问题：

- 当前 `AIChat` 输入框与文档编辑入口仍以 `textarea` 为主，无法直接在编辑态显示蓝色超链接。
- 当前文档保存链路仍是“纯字符串 Markdown”，与 `content + citations[]` 目标模型之间存在兼容改造成本。
- 当前问答链路只支持 `query` / `library_id` / `doc_ids`，尚未支持“用户显式确认的证据对象”透传。

因此，本次实施不按“所有层一起铺开”推进，而按“先打通一条最短可用链路，再扩展到完整范围”的方式推进。

## 2. 实施原则

- 先统一协议，再接交互，最后打通保存与注入。
- 先落地 `AIChat` 端到端 MVP，再扩展到文档编辑区。
- 共享渲染与编辑能力优先沉淀到 `ui-kit`，避免业务层复制。
- 文档存储优先采用兼容方案，避免一次性打断现有 Markdown 工作流。
- 首版只做“检测失配 + 提示重新确认”，不做自动修复。

## 3. 关键实现决策

### 3.1 编辑态渲染方案

实现上采用“轻量级内联 citation 编辑器”，而不是继续依赖原生 `textarea`。

原因：

- 原生 `textarea` 无法对局部文本做蓝色链接样式、hover 卡片、局部点击事件。
- 需求明确要求“插入后在正文中显示为蓝色超链接”，该能力必须发生在编辑态而不是仅发送后展示。
- 本次仍不引入完整富文本编辑器体系，只做一个基于 `contenteditable` 的轻量级文本编辑器，内部仍保存 `content + citations[] + range`。

落地方式：

- 在 `ui-kit` 新增一个通用 `InlineCitationEditor`。
- `AIChat` 输入区与文档编辑区共用同一套编辑器、候选面板和 popover。
- 编辑器负责字符串编辑、光标管理、范围更新、`@` 触发、内联渲染。

### 3.2 文档存储兼容方案

文档保存采用“Markdown 主文件 + citation sidecar JSON”的兼容方案，而不是立即把所有存储介质改成单一 JSON 文件。

建议存储形态：

- `current.md`
  - 继续保存纯文本正文，保证现有 Markdown 预览和旧接口可继续使用。
- `current.citations.json`
  - 保存与 `current.md` 对齐的 `citations[]`。
- API 返回时再组装为统一对象：

```ts
{
  content: string
  citations: CitationBinding[]
}
```

原因：

- 当前 `file_storage.read_markdown()` / `save_edited_markdown()` 都基于纯文本文件。
- 结构化预览、Markdown 预览、旧页面逻辑都仍然以字符串内容为基础。
- sidecar 方案可以最低风险地实现“结构化引用元数据独立保存”，同时避免一次性重写全部存储读写逻辑。

### 3.3 问答证据注入方案

`/api/query` 与调度链路显式扩展 `inline_citations[]` 字段，不采用“把引用对象拼回 query 纯文本”的弱实现。

落地方式：

- 前端 `QueryRequest` 增加 `inline_citations`。
- `api-server` 的 `QueryRequest` Pydantic 模型同步增加字段。
- `Dispatcher.dispatch()` 增加 `inline_citations` 参数，作为高优先级证据输入。
- 在回答生成前，把显式引用转换为证据片段，优先拼入 prompt/context。

这样可以避免后端重新猜测“用户到底引用了哪条条文”。

## 4. 实施阶段

## 4.1 Phase A：协议与共享组件骨架

目标：先把通用类型、共享渲染组件、轻量编辑器骨架建立起来，为后续两条业务链路复用。

主要产出：

- 统一 citation 协议
- 通用 citation 渲染组件
- 轻量级 `InlineCitationEditor` 骨架
- `@` 候选面板骨架

涉及文件：

- 修改 `packages/ui-kit/src/types/chat.ts`
- 修改 `packages/docs-ui/src/types/reference.ts`
- 修改 `packages/docs-ui/src/types/index.ts`
- 新增 `packages/ui-kit/src/types/citation.ts`
- 新增 `packages/ui-kit/src/components/common/CitationInline.vue`
- 新增 `packages/ui-kit/src/components/common/CitationPopover.vue`
- 新增 `packages/ui-kit/src/components/common/CitationRichContent.vue`
- 新增 `packages/ui-kit/src/components/common/InlineCitationEditor.vue`
- 新增 `packages/ui-kit/src/components/common/CitationMentionPanel.vue`
- 视情况新增 `packages/ui-kit/src/composables/useInlineCitationEditor.ts`

实施要点：

- 抽出 `CitationReference`、`CitationBinding`、`InlineCitationDraftValue` 等通用类型。
- 保留 `BaseChatCitation` / `AIChatCitation` 兼容类型，但通过转换函数向新协议收敛。
- 把 `BaseChat.vue` 中现有 `renderCitationRichMedia()` 的富媒体渲染逻辑迁移到 `CitationRichContent.vue`。
- `InlineCitationEditor` 首版只支持：
  - 文本输入
  - `@` 检测
  - 插入引用
  - range 更新
  - hover / click
  - 失配态渲染
- 首版不做复杂撤销栈，优先复用浏览器默认编辑行为。

完成标志：

- `ui-kit` 层可以独立渲染一段带 citation 的文本。
- 图、表、公式、图片可以在通用 popover 中正常显示。
- 输入组件可在本地 mock 数据下完成 `@` 插入流程。

## 4.2 Phase B：知识引用检索与前端状态管理

目标：补齐 `docs-ui` 侧的知识检索、候选适配、文本 range 维护和失配检测。

主要产出：

- 知识引用搜索 composable
- citation 文本工具函数
- 候选 DTO 到通用 citation 协议的转换器

涉及文件：

- 新增 `packages/docs-ui/src/composables/useKnowledgeReferenceSearch.ts`
- 新增 `packages/docs-ui/src/utils/reference.ts`
- 修改 `packages/docs-ui/src/composables/useKnowledgeCitation.ts`
- 修改 `packages/docs-ui/src/types/reference.ts`
- 视情况新增 `packages/docs-ui/src/api/reference.ts` 或复用应用层 API

实施要点：

- `useKnowledgeReferenceSearch.ts` 负责：
  - 接口请求
  - 搜索关键词节流
  - 候选列表格式化
  - 把候选项转换成 `CitationBinding`
- `reference.ts` 负责：
  - 从编辑值中查找光标前的 `@关键词`
  - 插入引用后的文本替换
  - 维护所有 citation 的 `range`
  - 检测完整删除与部分失配
  - 序列化 / 反序列化
- `useKnowledgeCitation.ts` 保持“点击定位”职责，同时补一个适配层，把 `CitationReference` 转回当前知识定位所需的 citation 结构。

完成标志：

- 在不接 UI 的情况下，工具函数可以完成：
  - `@关键词` 识别
  - 插入后范围重算
  - 删除后 citation 移除
  - 文本部分变更后标记失配

## 4.3 Phase C：后端专用检索接口

目标：先把 `@` 检索接口单独打通，为前端候选面板提供稳定数据源。

主要产出：

- `POST /api/knowledge/references/search`
- docs-core 引用候选检索能力
- 候选 DTO 标准化与排序

涉及文件：

- 修改 `services/api-server/knowledge_routes.py`
- 新增或修改 `services/docs-core/src/docs_core/knowledge_service.py`
- 新增 `services/docs-core/src/docs_core/query_protocols/reference_contracts.py` 或扩展 `contracts.py`
- 视情况新增 `services/docs-core/src/docs_core/retrieval/reference_search.py`

实施要点：

- API 层新增请求/响应模型：
  - `library_id`
  - `query`
  - `limit`
  - `types`
  - `current_doc_id`
- docs-core 复用已有索引与图谱字段：
  - `plain_text`
  - `table_html`
  - `math_content`
  - `image_path`
  - `image_paths`
  - `title_path`
  - `page_idx`
  - `block_uid`
- 排序优先级按 spec 执行：
  - 编号精确命中
  - 层级路径 / 片段命中
  - hybrid / dense 分数
- 返回值直接满足前端插入需要，避免前端二次拼装业务字段。

完成标志：

- 输入 `表6.4.2-1`、`公式3.1.5-2` 等编号时，候选结果稳定返回。
- 返回值包含足够 hover 渲染与点击定位的全部信息。

## 4.4 Phase D：AIChat 端到端 MVP

目标：优先把 `AIChat` 做成第一条完整可用链路。

原因：

- `AIChat` 当前没有正文持久化负担，联调成本低于文档编辑区。
- 该链路最直接服务“给 LLM 注入用户显式证据”这个核心目标。

涉及文件：

- 修改 `packages/ui-kit/src/components/common/BaseChat.vue`
- 修改 `packages/ui-kit/src/components/common/AIChat.vue`
- 修改 `packages/ui-kit/src/composables/useAIChat.ts`
- 修改 `packages/ui-kit/src/api/client.ts`
- 修改 `packages/ui-kit/src/types/chat.ts`

实施要点：

- 用 `InlineCitationEditor` 替换 `BaseChat.vue` 当前的输入 `a-textarea`。
- `BaseChat` 的 `send` 事件从 `(message, model)` 扩展为 `(payload, model)`：

```ts
interface BaseChatSendPayload {
  content: string
  citations: CitationBinding[]
}
```

- `AIChat.vue` 向上游事件继续兼容透出：
  - 旧调用方若只关心字符串，内部可取 `payload.content`
  - 新链路同时获得 `payload.citations`
- `useAIChat.ts` 的 `sendMessage()` 扩展为可接收 `inline_citations`。
- `queryApi.query()` 发送到 `/api/query` 时携带 `inline_citations`。
- 用户发送后，本轮用户消息也保存 citation 元数据，便于对话记录回显与复查。

完成标志：

- 在 `AIChat` 中输入 `@表6.4.2-1` 可完成搜索、确认、蓝链插入。
- hover 能展示正文 / 图 / 表 / 公式。
- 发送时后端收到 `inline_citations[]`。
- 用户消息气泡可正确回显内联 citation。

## 4.5 Phase E：问答链路显式证据注入

目标：让 `LLM` 优先消费用户显式确认过的证据对象。

涉及文件：

- 修改 `packages/ui-kit/src/types/chat.ts`
- 修改 `services/api-server/main.py`
- 修改 `services/angineer-core/src/angineer_core/dispatcher.py`
- 视情况修改 `services/docs-core/src/docs_core/query_protocols/contracts.py`

实施要点：

- 前后端同步扩展 `QueryRequest.inline_citations`。
- `main.py` 中的 `QueryRequest` Pydantic 模型增加字段，透传给 `Dispatcher.dispatch()`。
- `Dispatcher.dispatch()` 在进入原有意图与检索流程前，先构造一份“显式证据上下文”。
- 显式证据上下文建议包含：
  - `label`
  - `doc_title`
  - `page_idx`
  - `section_path`
  - `content`
  - `rich_media_summary`
- 首版策略：
  - 不跳过原有检索
  - 但把显式证据放在 prompt/context 的前部
  - 让回答引用与证据优先对齐该批对象

完成标志：

- `/api/query` 能接收并消费 `inline_citations[]`。
- 相同问题在有显式引用和无显式引用两种情况下，回答内容与引用依据可观察到差异。

## 4.6 Phase F：文档编辑区接入与兼容存储

目标：把同一套能力扩展到知识文档编辑入口，并完成 `content + citations[]` 的落库。

涉及文件：

- 修改 `apps/admin-console/src/views/KnowledgeManage.vue`
- 修改 `packages/docs-ui/src/components/common/workspace/PDFParsedWorkspace.vue`
- 修改 `packages/docs-ui/src/components/common/workspace/PDFParsedViewerCombo.vue`
- 修改 `packages/docs-ui/src/components/common/index/IndexTreeEditModal.vue`
- 修改 `packages/docs-ui/src/types/knowledge.ts`
- 修改 `apps/admin-console/src/api/knowledge.ts`
- 修改 `services/api-server/knowledge_routes.py`
- 修改 `services/docs-core/src/docs_core/ingest/store/assets_file_store.py`

实施要点：

- 文档编辑区首批覆盖“结构化节点编辑弹窗”：
  - `IndexTreeEditModal.vue` 的 `plain_text` 编辑器接入 `InlineCitationEditor`
  - 后续再扩展到其他正文编辑入口
- `StructuredNodeUpdatePayload` 增加可选 `citations?: CitationBinding[]`
- 文档整体内容接口逐步扩展为：

```ts
interface DocumentContentPayload {
  content: string
  citations?: CitationBinding[]
}
```

- `knowledge.ts` 的 `updateDocument()` 从纯字符串参数升级为对象参数。
- `knowledge_routes.py` 的 `KnowledgeDocumentUpdate` 从 `content: str` 扩展为兼容模型：
  - 兼容旧请求只传字符串内容
  - 新请求可传 `content + citations`
- `assets_file_store.py` 增加 sidecar 文件读写：
  - 读取 `current.citations.json`
  - 保存 `current.citations.json`
  - 缺失时按空数组返回

完成标志：

- 结构化编辑弹窗可插入和展示内联引用。
- 保存后再次打开仍能恢复 citation。
- 老文档、老接口、无 citation 内容不受影响。

## 5. 推荐交付顺序

推荐按以下 6 个迭代批次交付，而不是一次性全做完：

1. `Phase A`
   - 协议、共享渲染、轻量编辑器骨架
2. `Phase C`
   - 先补专用检索接口，给 UI 真实数据源
3. `Phase B`
   - 完成前端工具层和搜索适配
4. `Phase D`
   - 打通 `AIChat` MVP
5. `Phase E`
   - 打通 `inline_citations[]` 到 `LLM` 注入
6. `Phase F`
   - 扩展到文档编辑区与兼容落库

顺序说明：

- `AIChat` 先上线能最快验证用户价值与检索质量。
- 文档编辑区落库链路依赖更多兼容改造，应放在后半段。
- `LLM` 注入链路应在 `AIChat` 可用后立即跟进，否则只能完成“看得见引用”，不能兑现“减少幻觉”的核心目标。

## 6. 文件级改动清单

### 6.1 前端

- `packages/ui-kit/src/types/chat.ts`
  - 扩展 `QueryRequest`
  - 兼容旧 citation 类型
- `packages/ui-kit/src/api/client.ts`
  - 增加 `referenceSearch` API
- `packages/ui-kit/src/components/common/BaseChat.vue`
  - 输入区替换为 `InlineCitationEditor`
  - 用户消息支持内联 citation 渲染
- `packages/ui-kit/src/components/common/AIChat.vue`
  - 透传带 citation 的发送 payload
- `packages/ui-kit/src/composables/useAIChat.ts`
  - 发送 `inline_citations`
- `packages/docs-ui/src/types/reference.ts`
  - 定义统一引用协议
- `packages/docs-ui/src/composables/useKnowledgeCitation.ts`
  - 衔接点击定位
- `packages/docs-ui/src/components/common/index/IndexTreeEditModal.vue`
  - 结构化编辑弹窗接入内联引用编辑器
- `apps/admin-console/src/views/KnowledgeManage.vue`
  - 接线 `AIChat` 与文档编辑区引用行为
- `apps/admin-console/src/api/knowledge.ts`
  - 扩展文档更新与引用搜索接口

### 6.2 后端

- `services/api-server/knowledge_routes.py`
  - 新增 `references/search`
  - 扩展文档保存接口
- `services/api-server/main.py`
  - 扩展 `/api/query` 请求模型
- `services/angineer-core/src/angineer_core/dispatcher.py`
  - 接收显式证据并注入上下文
- `services/docs-core/src/docs_core/knowledge_service.py`
  - 提供引用搜索与候选组装
- `services/docs-core/src/docs_core/ingest/store/assets_file_store.py`
  - 读写 citation sidecar

## 7. 测试与验证

### 7.1 前端验证

- 组件级验证：
  - `CitationRichContent` 对正文、表格、公式、图片渲染正确
  - `InlineCitationEditor` 对 `@` 触发、插入、删除、失配处理正确
- 交互级验证：
  - 键盘上下选择候选
  - `Enter` 确认
  - `Esc` 关闭
  - hover 打开 popover
  - 点击跳原文

### 7.2 后端验证

- `references/search` 能正确处理：
  - 全库检索
  - 编号检索
  - 类型筛选
  - 空结果
- `/api/query` 能接受 `inline_citations[]`
- `Dispatcher` 能把显式证据拼入上下文，不破坏既有查询路径

### 7.3 兼容验证

- 旧聊天不传 `inline_citations` 仍可正常问答
- 旧文档不带 `citations` 仍可正常读取与编辑
- 旧 Markdown 预览不因新增 sidecar 文件而失效

## 8. 风险与应对

- 编辑器复杂度风险
  - 应对：首版仅支持单段纯文本编辑，不做块级富文本能力，不做复杂撤销系统
- range 漂移风险
  - 应对：统一通过 `reference.ts` 做文本替换与重算，避免每个页面自行维护
- 富媒体渲染重复风险
  - 应对：禁止继续在 `BaseChat.vue` 内拼装 HTML，统一走 `CitationRichContent.vue`
- 文档存储回归风险
  - 应对：采用 sidecar 兼容方案，保留 `current.md` 主文件
- 调度链路扩展风险
  - 应对：`Dispatcher.dispatch()` 新增参数使用可选字段，不影响旧调用

## 9. 阶段验收口径

### 9.1 第一阶段验收

- 共享 citation 组件可用
- 专用搜索接口可用
- `AIChat` 中可完成 `@` 引用插入与 hover 预览

### 9.2 第二阶段验收

- `/api/query` 可稳定消费 `inline_citations[]`
- 回答优先参考显式证据

### 9.3 第三阶段验收

- 文档编辑区可编辑、保存、恢复 citation
- 旧数据无回归

## 10. 建议下一步

如果按本计划进入编码，建议第一轮实现只覆盖以下最小闭环：

1. 统一 citation 类型与 `ui-kit` 共享渲染组件
2. `references/search` 后端接口
3. `AIChat` 输入区 `@` 检索与插入
4. `/api/query` 的 `inline_citations[]` 透传

这样可以先验证：

- 用户是否能顺畅完成“搜索 -> 确认 -> 插入 -> 发送”
- 检索候选质量是否满足工程编号场景
- 显式证据注入后，回答质量是否有实际提升

文档编辑区与兼容落库存储建议放在第二轮实现。
