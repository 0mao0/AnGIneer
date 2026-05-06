# 前端架构冗余清理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消除前端代码库中的冗余代码，统一 API 层和工具函数，让 KnowledgeManage.vue 使用已有 composables。

**Architecture:** 按依赖顺序从底层到上层清理：先删除死代码(P2)，再统一共享工具函数(P0-2/P1-2)，再重构页面使用 composables(P0-1)，最后统一 API 层(P1-1)。

**Tech Stack:** Vue 3 + TypeScript + Vite + pnpm monorepo

---

### Task 1: P2 — 删除死代码

**Files:**
- Delete: `apps/admin-console/src/views/components/TreeNodeItem.vue`
- Delete: `packages/docs-ui/src/composables/useDocument.ts`
- Modify: `packages/docs-ui/src/composables/index.ts` (移除 useDocument 导出)

- [ ] **Step 1: 删除 TreeNodeItem.vue** — 无任何文件导入此组件
- [ ] **Step 2: 删除 useDocument.ts** — 无任何外部文件导入此 composable，其 API 路径 `/api/docs/` 与实际后端不匹配
- [ ] **Step 3: 从 composables/index.ts 移除 useDocument 导出**
- [ ] **Step 4: 验证构建通过** — `pnpm build`

---

### Task 2: P0-2 — 消除 Markdown 渲染函数重复

ui-kit/markdown.ts 和 docs-ui/knowledge.ts 中以下函数完全相同：
`escapeHtml`, `escapeHtmlAttribute`, `resolveAssetUrl`, `renderFormula`, `renderMarkdown`, `renderMarkdownInlineToHtml`, `renderMarkdownToHtml`

**Files:**
- Modify: `packages/ui-kit/package.json` (新增 utils/markdown 导出路径)
- Modify: `packages/docs-ui/src/utils/knowledge.ts` (删除重复实现，改为从 ui-kit 导入并 re-export)

- [ ] **Step 1: 在 ui-kit/package.json 的 exports 中添加 `./utils/markdown` 路径**
- [ ] **Step 2: 在 docs-ui/knowledge.ts 中，将重复的 markdown 函数替换为从 `@angineer/ui-kit/utils/markdown` 导入并 re-export**
- [ ] **Step 3: 验证所有消费者仍能正常导入** — 检查 PDFParsedWorkspace.vue、KnowledgeEvalDrawer.vue、AIChat.vue
- [ ] **Step 4: 验证构建通过** — `pnpm build`

---

### Task 3: P1-2 — 消除状态映射和文件类型检测重复

docs-ui/knowledge.ts 中的 `mapNodeStatusText` 与 ui-kit/tree.ts 的 `getStatusText` 逻辑相同；
`getPreviewFileType`/`getFileExtension` 与 ui-kit/tree.ts 的 `getFileIconType` 逻辑相同。

**Files:**
- Modify: `packages/docs-ui/src/utils/knowledge.ts` (替换为从 ui-kit 导入)
- Modify: `packages/docs-ui/src/utils/common.ts` (移除已从 ui-kit re-export 的 getStatusColor/getStatusText)

- [ ] **Step 1: 在 docs-ui/knowledge.ts 中，将 `mapNodeStatusText` 替换为从 ui-kit 导入的 `getStatusText` 并 re-export 别名**
- [ ] **Step 2: 在 docs-ui/knowledge.ts 中，将 `getPreviewFileType` 内部改用 ui-kit 的 `getFileIconType`，保持外部 API 不变**
- [ ] **Step 3: 验证构建通过** — `pnpm build`

---

### Task 4: P0-1 — KnowledgeManage.vue 使用已有 composables

KnowledgeManage.vue 约 1500 行，其中 ~400 行逻辑与 useKnowledgeParse、useKnowledgeStructuredIndex、useKnowledgeCitation 完全重复。

**Files:**
- Modify: `apps/admin-console/src/views/KnowledgeManage.vue`

- [ ] **Step 1: 导入三个 composable，替换内联类型定义**
- [ ] **Step 2: 用 useKnowledgeParse() 替换内联的解析设置/轮询逻辑**
- [ ] **Step 3: 用 useKnowledgeStructuredIndex() 替换内联的结构化索引逻辑**
- [ ] **Step 4: 用 useKnowledgeCitation() 替换内联的引用定位逻辑**
- [ ] **Step 5: 删除所有已替换的内联函数和类型定义**
- [ ] **Step 6: 验证构建通过** — `pnpm build`

---

### Task 5: P1-1 — 统一 API 层

web-console 使用原生 fetch + 4 个端点，admin-console 使用 axios + 25+ 个端点，共享端点重复定义。

**Files:**
- Create: `apps/shared/knowledgeApi.ts` (从 admin-console 迁移，作为唯一真相源)
- Modify: `apps/admin-console/src/api/knowledge.ts` (改为从 shared 导入并扩展)
- Modify: `apps/web-console/src/api/knowledge.ts` (改为从 shared 导入)
- Modify: `apps/web-console/src/views/DocumentView.vue` (适配新 API)

- [ ] **Step 1: 创建 apps/shared/knowledgeApi.ts，包含通用 axios 实例和所有共享端点**
- [ ] **Step 2: 更新 admin-console/knowledge.ts，从 shared 导入基础 API 并扩展 admin 专属方法**
- [ ] **Step 3: 更新 web-console/knowledge.ts，从 shared 导入**
- [ ] **Step 4: 更新 DocumentView.vue 适配新 API 签名**
- [ ] **Step 5: 验证构建通过** — `pnpm build`
