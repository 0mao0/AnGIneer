# docs-ui 文件地址解析器与依赖统一 设计

日期：2026-08-11

状态：已确认（用户批准）

## 1. 背景

- docs-ui 目前把文件地址硬编码为 `/api/files?path=...`（AnGIneer 后端约定）；
- DredgeAI 的文件服务约定是 `/storage/{key}`，接入 docs-ui 时无法直接复用；
- AnGIneer 与 DredgeAI 的 vue / antd / katex 版本不一致。

## 2. 决策

### 2.1 文件地址解析器

- `PDFParsedWorkspace` 新增可选 prop：`fileUrlResolver?: (path: string) => string`；
- 不传时保持现有默认行为：`http(s)` 开头直通，否则拼 `/api/files?path=...`；
- 传入时由该函数决定最终 URL，PDF 地址、Office 预览、下载、文本加载统一生效；
- 该能力只影响 `useWorkspacePreview` 的 `fileUrl` 计算，不改变组件其他行为。

### 2.2 依赖统一（精确一套，不写范围）

| 依赖 | 统一版本 |
| --- | --- |
| vue | `3.5.41` |
| ant-design-vue | `4.2.6` |
| @ant-design/icons-vue | `7.0.1` |
| katex | `0.18.4` |
| pdfjs-dist | `4.10.38`（保持 4.x，不跨大版本） |

同步范围：

- docs-ui 的 `peerDependencies` 与 `devDependencies`；
- AnGIneer 的 `user-web` / `admin-web`；
- DredgeAI 的 `user-web` / `admin-web`。

升级方式：三处手动同步修改 + 回归验证 + 提交 lockfile，禁止依赖范围自动漂移。

## 3. 文件改动清单

| 文件 | 改动 |
| --- | --- |
| `packages/docs-ui/src/composables/useWorkspacePreview.ts` | 新增 `fileUrlResolver` 选项 |
| `packages/docs-ui/src/components/common/workspace/PDFParsedWorkspace.vue` | 新增 prop 并传入 composable |
| `packages/docs-ui/package.json` | peer/dev 依赖精确版本，katex 升 0.18.4 |
| `packages/docs-ui/README.md` | 补充 `fileUrlResolver` 说明 |
| `apps/user-web/package.json`、`apps/admin-web/package.json` | vue/antd/icons 精确版本 |
| `pnpm-lock.yaml` | pnpm install 后更新 |
| DredgeAI `user-web/package.json`、`admin-web/package.json` | vue/antd/icons/katex 精确版本 |
| DredgeAI `pnpm-lock.yaml` | pnpm install 后更新 |

## 4. 使用方式

- AnGIneer：不传 `fileUrlResolver`，默认行为不变；
- DredgeAI：传

```ts
:file-url-resolver="(path) => path.startsWith('http') ? path : `${API_BASE_URL}/storage/${encodeURIComponent(path)}`"
```

## 5. 验证

1. docs-ui 类型检查通过；
2. AnGIneer user-web / admin-web 构建通过；
3. DredgeAI `pnpm install` 后 typecheck 通过；
4. 回归：AnGIneer PDF/Office/文本预览、下载、公式渲染正常。
