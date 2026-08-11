# docs-ui 文件地址解析器与依赖统一 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** docs-ui 支持外部文件地址解析器，并把 AnGIneer / DredgeAI 的 vue、antd、icons、katex 统一到同一套精确版本。

**Architecture:** 在 `useWorkspacePreview` 增加可选 `fileUrlResolver`，`PDFParsedWorkspace` 透传 prop，默认逻辑不变；依赖改为精确版本并在三个仓库同步。

**Tech Stack:** Vue 3.5.41 + ant-design-vue 4.2.6 + @ant-design/icons-vue 7.0.1 + katex 0.18.4 + pdfjs-dist 4.10.38；pnpm。

---

### Task 1: docs-ui 增加 fileUrlResolver

**Files:**
- Modify: `packages/docs-ui/src/composables/useWorkspacePreview.ts`
- Modify: `packages/docs-ui/src/components/common/workspace/PDFParsedWorkspace.vue`
- Modify: `packages/docs-ui/README.md`

- [ ] **Step 1: useWorkspacePreview 增加选项**

在 `UseWorkspacePreviewOptions` 中 `renderPdfPath` 之后插入：

```ts
fileUrlResolver?: (path: string) => string
```

把 `fileUrl` computed 替换为：

```ts
const fileUrl = computed(() => {
  const effectivePath = options.renderPdfPath?.value || options.filePath.value
  if (!effectivePath) return ''
  if (options.fileUrlResolver) return options.fileUrlResolver(effectivePath)
  if (effectivePath.startsWith('http')) return effectivePath
  return `/api/files?path=${encodeURIComponent(effectivePath)}`
})
```

- [ ] **Step 2: PDFParsedWorkspace 新增 prop 并透传**

在 `Props` 中 `renderPdfPath` 之后插入：

```ts
fileUrlResolver?: (path: string) => string
```

在 `useWorkspacePreview({ ... })` 调用中 `renderPdfPath` 之后插入：

```ts
fileUrlResolver: props.fileUrlResolver
```

- [ ] **Step 3: README 补充说明**

在“`PDF_Viewer` 支持……”说明行后追加：

```markdown
- `PDFParsedWorkspace` 支持 `fileUrlResolver` prop，可自定义文件地址拼接规则；不传时默认使用 `/api/files?path=...`。
```

- [ ] **Step 4: 验证类型检查**

Run: `pnpm --filter @angineer/user-web exec vue-tsc -b --pretty false`

Expected: 退出码 0。

- [ ] **Step 5: 提交**

Run:

```bash
git add packages/docs-ui/src/composables/useWorkspacePreview.ts packages/docs-ui/src/components/common/workspace/PDFParsedWorkspace.vue packages/docs-ui/README.md
git commit -m "feat(ui): support configurable file URL resolver in PDFParsedWorkspace"
```

Expected: 提交成功。

---

### Task 2: AnGIneer 依赖统一

**Files:**
- Modify: `packages/docs-ui/package.json`
- Modify: `apps/user-web/package.json`
- Modify: `apps/admin-web/package.json`
- Modify: `pnpm-lock.yaml`（pnpm install 生成）

- [ ] **Step 1: docs-ui package.json 精确版本**

`peerDependencies` 改为：

```json
"peerDependencies": {
  "@ant-design/icons-vue": "7.0.1",
  "ant-design-vue": "4.2.6",
  "vue": "3.5.41"
}
```

`devDependencies` 中 icons/antd/vue 改为精确版本；`dependencies` 中 katex 改为 `"0.18.4"`。

- [ ] **Step 2: 两个 app package.json 精确版本**

`user-web` 与 `admin-web` 的 `dependencies` 中：

```json
"@ant-design/icons-vue": "7.0.1",
"ant-design-vue": "4.2.6",
"vue": "3.5.41"
```

- [ ] **Step 3: pnpm install 更新 lockfile**

Run: `pnpm install`

Expected: 退出码 0，lockfile 更新。

- [ ] **Step 4: 构建验证**

Run:

```bash
pnpm --filter @angineer/user-web build
pnpm --filter @angineer/admin-web build
```

Expected: 均退出码 0。

- [ ] **Step 5: 提交**

Run:

```bash
git add packages/docs-ui/package.json apps/user-web/package.json apps/admin-web/package.json pnpm-lock.yaml
git commit -m "chore: pin vue/antd/icons/katex to unified exact versions"
```

Expected: 提交成功。

---

### Task 3: DredgeAI 依赖统一

**Files:**
- Modify: `D:\AI\DredgeAI\user-web\package.json`
- Modify: `D:\AI\DredgeAI\admin-web\package.json`
- Modify: `D:\AI\DredgeAI\pnpm-lock.yaml`（pnpm install 生成）

- [ ] **Step 1: 两个 app package.json 精确版本**

`dependencies` 中：

```json
"@ant-design/icons-vue": "7.0.1",
"ant-design-vue": "4.2.6",
"katex": "0.18.4",
"vue": "3.5.41"
```

- [ ] **Step 2: pnpm install 更新 lockfile**

Run（在 D:\AI\DredgeAI 下）：`pnpm install`

Expected: 退出码 0。

- [ ] **Step 3: typecheck 验证**

Run（在 D:\AI\DredgeAI 下）：`pnpm typecheck`

Expected: 退出码 0。

- [ ] **Step 4: 提交**

Run（在 D:\AI\DredgeAI 下）：

```bash
git add user-web/package.json admin-web/package.json pnpm-lock.yaml
git commit -m "chore: pin vue/antd/icons/katex to unified exact versions"
```

Expected: 提交成功。

---

### Task 4: 全量回归

- [ ] **Step 1: AnGIneer 回归**

PDF 预览、Office/文本预览、下载、公式渲染、解析面板展开/收起均正常。

- [ ] **Step 2: 确认两套 lockfile 已提交**

AnGIneer 与 DredgeAI 的 `pnpm-lock.yaml` 均包含统一后的精确版本。
