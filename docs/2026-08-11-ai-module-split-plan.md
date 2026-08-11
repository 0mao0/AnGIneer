# AI 模块解耦实施计划（aichat-ui / docs-api / aichat-api）

> **For agentic workers:** 本计划按任务逐项执行，每项完成即提交到 `main`（用户工作方式）。步骤使用 `- [ ]` 语法跟踪。

**Goal:** 把 AI 对话前端从 `ui-kit` 抽成独立的 `aichat-ui` 包，把单一 `api-server` 拆成 `docs-api` / `aichat-api` 两个独立服务目录，前端 API 客户端按服务拆分，API Key 统一申请 + scope 隔离，并让 AnGIneer 以 docker-compose 双容器 + nginx 的方式保持独立一键部署。

**Architecture:** 前端两个组件库（docs-ui 已自包含、aichat-ui 本次抽出）对应后端两个服务（docs-api 写知识库、aichat-api 读知识库），两者只通过数据契约（sqlite/jsonl/content.md）解耦，互不调用。后端仍留在 AnGIneer monorepo 内（不建独立仓库），通过独立服务目录 + 独立端口 + 路径分流实现代码级解耦；部署阶段用 docker-compose 编排两个 API 容器 + nginx 统一入口。

**Tech Stack:** Vue 3 / TypeScript / Vite / pnpm；FastAPI / uvicorn / SQLite；docker-compose / nginx。

---

## 0. 已确认的决策

1. 仓库形态：AnGIneer 主仓库 + DredgeAI 主仓库 + docs-ui + aichat-ui 共四个仓库；**后端不建独立仓库**，在 monorepo 内拆 `services/docs-api`、`services/aichat-api` 两个独立服务目录。
2. 部署：docker-compose 起两个 API 容器 + 前端静态资源 + 一个 nginx；共享 `data/` 数据卷；对外仍是一个入口、一个产品。
3. 前端 API 客户端拆成两个（docs / aichat）。
4. API Key：统一申请入口 + 一张共享 key 表 + key 带 `scope`（`doc` / `chat` / `both`），docs-api 校验 `doc` 权限、aichat-api 校验 `chat` 权限。
5. docs-ui 仓库化不在本计划范围（它已自包含，届时机械搬运即可）。

## 1. 现状事实（已核实）

### 1.1 前端

- `packages/docs-ui` 已自包含（src 内无 `@angineer/*` 依赖），被 user-web 与 admin-web 使用。
- AIChat 全家在 `packages/ui-kit`：
  - 组件：`components/common/{AIChat,BaseChat,CitationInline,CitationMentionPanel,CitationPopover,CitationRichContent,InlineCitationEditor,ThinkingSteps}.vue`
  - composable：`composables/useAIChat.ts`（依赖 `utils/tree.ts` 的 `generateMessageId` / `estimateTokens`）
  - 契约：`api/types.ts`（`AIChatTransport`）
  - 类型：`types/chat.ts`、`types/citation.ts`
  - 工具：`utils/citation.ts`、`utils/markdown.ts`（依赖 katex）、`utils/thinking.ts`、`utils/token.ts`
  - 测试：`test/useAIChat.test.ts`、`test/citation.test.ts`
- 消费者：
  - `apps/user-web/src/App.vue`：`AIChat`（其余 `AppHeader/SplitPanes/useTheme` 留在 ui-kit）
  - `apps/shared/chatTransport.ts`：`QueryRequest` 等类型 + `defaultAIChatTransport`
  - `packages/sop-ui/src/components/SOPStepNode.vue`：`CitationInline`、`CitationBinding`、`buildCitationSegments`
  - `packages/sop-ui/src/components/SOPPropertyPanel.vue`：`InlineCitationEditor`、`CitationBinding`、`InlineCitationCandidate`、`InlineCitationSearchPayload`、`mapReferenceSearchCandidate`
  - `packages/sop-ui/src/types/sop.ts`：`InlineCitationDraftValue`
- ui-kit 的 `package.json` 暴露子路径 `./utils/citation`、`./utils/markdown`、`./utils/tree`。
- chat 组件使用的 CSS 变量（17 个，均有 fallback）：`--chat-root-bg --chat-user-bubble-bg --chat-user-bubble-text --chat-assistant-bubble-bg --chat-assistant-bubble-text --chat-citation-accent --chat-citation-bg --chat-citation-border --chat-code-bg --chat-pre-bg --chat-error-color --chat-error-hover --chat-streaming-bg --chat-streaming-cursor --chat-system-bg --chat-system-border --chat-system-text`。
- `docs-ui` 的 `tsconfig.json` 可作为新包模板。

### 1.2 后端

- 单一 `services/api-server`（FastAPI，端口 8789）承载：
  - docs 系：`docs_routes.py`（`/api/knowledge/*`）、`preview_router`（`/api/*` 文件预览）、`routes/v1/documents.py`（`/api/v1/documents/*`）、`routes/v1/auth.py`（`/api/v1/auth/me`）、`graph_routes.py`（`/api/graph/*`）
  - chat 系：`main.py` 内 `/chat`、`/chat/stream`、`/api/chat`、`/api/chat/agent`、`/api/chat/agent/{run_id}/steer`、`/api/llm_configs`、`/api/query`、`/test*` 系列；`chat_agent.py`
  - 其他：`sop_routes.py`（`/api/sops/*`）、`evals_routes.py`（`/api/evals/*`）、`dream_cycle_routes.py`（`/api/dream-cycle/*`）、`api_key_routes.py`（`/api/api-keys/*`）
- 共享小件：`middleware/api_key_auth.py`、`models/api_key.py`（`data/api_keys.sqlite`，WAL 模式）、`models/parse_record.py`、`models/v1_responses.py`
- 数据：`data/knowledge_base/**/parsed/{content.md,images,doc_blocks_graph.jsonl,...}` + `data/knowledge_*.sqlite`；`engtools/config.py` 的 `KNOWLEDGE_DIR` 默认即 `data/knowledge_base`（chat 侧直接读）
- `services/docs-core`（含 MinerU/PoPo submodule 定制）、`services/angineer-core`、`services/ai-inference`、`services/engtools`、`services/sop-core`、`services/evals-core`、`services/geo-core`、`services/tree-core` 均为可 pip install -e 的包
- 部署现状：`docker/docker-compose.yml`（frontend + api-server）、`docker/Dockerfile.backend`（装全部 core 包 + libreoffice，CMD 起 api-server）、`docker/Dockerfile.frontend`、`docker/nginx/nginx.conf`（upstream api-server:8789，`/api/` 反代）
- 端口契约：`apps/shared/ports.json` 现有 `apiServerPort: 8789`、`adminConsolePort: 3002`、`webConsolePort: 3005`；引用方：`main.py`、两个 `vite.config.ts`、`apps/shared/ports.ts`、`start.ps1`

### 1.3 已知风险（执行前必读）

- **用户 WIP**：`apps/shared/chatTransport.ts`、`packages/ui-kit/src/components/common/AIChat.vue`、`BaseChat.vue`、`composables/useAIChat.ts`、`types/chat.ts`、`types/index.ts`、`utils/citation.ts`、`ThinkingSteps.vue`、`utils/thinking.ts`、`utils/token.ts`、`packages/ui-kit/test/` 均未提交，且正是阶段 1 要移动的文件。**必须先按任务 0.1 处理。**
- `sop-ui` 依赖 chat 组件，阶段 1 必须同步改其 import。
- 两个服务共享 `data/` 数据卷：SQLite 已启用 WAL，docs 写 / chat 读并发可接受；api_keys.sqlite 由 docs-api 写、两个服务读，同样 WAL 兼容。
- `services/docs-core/src/popo` 是 submodule 且有本地定制（`post_processing/model_utils.py`），本计划不移动它，仅提醒未来仓库化时保留。

## 2. 目标结构

```
AnGIneer/
├─ packages/
│  ├─ docs-ui/                    # 已有，不动
│  ├─ aichat-ui/                  # 新增：AI 对话组件库（本次抽出）
│  └─ ui-kit/                     # 保留布局/主题/通用组件，移除 chat 全家
├─ services/
│  ├─ docs-api/                   # 新增：文档解析/知识库/图谱/v1/Key 管理（8790）
│  ├─ aichat-api/                 # 新增：对话/SOP/Evals/DreamCycle/测试（8791）
│  └─ api-server/                 # 删除（拆分完成并验证后）
├─ apps/shared/                   # ports、docsApiClient、aichatApiClient、chatTransport
└─ docker/                        # compose 双 API 容器 + nginx
```

路由归属：

| 路径 | 服务 |
|---|---|
| `/api/knowledge/*`、`/api/graph/*`、`/api/*`（preview）、`/api/v1/documents/*`、`/api/v1/auth/*`、`/api/api-keys/*` | docs-api |
| `/chat*`、`/api/chat*`、`/api/llm_configs`、`/api/query`、`/test*`、`/api/sops/*`、`/api/evals/*`、`/api/dream-cycle/*` | aichat-api |

## 3. 实施任务

### 阶段 0：准备

#### 任务 0.1：处理用户未提交 WIP【阻塞项，需用户确认】

**Files:** 不修改文件；只做 git 状态确认。

- [ ] **Step 1: 展示 WIP 清单并请用户选择处理方式**

运行：

```powershell
git -C D:\AI\AnGIneer status --short
```

需要用户二选一：

1. 用户先自行提交全部 WIP，我们随后在干净基线上开始；
2. 授权我们把 WIP 中与 aichat 相关的改动随阶段 1 一起搬入 `packages/aichat-ui` 并提交（chatTransport.ts 的改动留在 apps/shared，随阶段 2 提交）。

**本任务完成后才能进入阶段 1。**

#### 任务 0.2：基线验证

**Files:** 无。

- [ ] **Step 1: 记录当前 git 基线**

```powershell
git -C D:\AI\AnGIneer log -1 --oneline
```

- [ ] **Step 2: 确认依赖与构建基线**

```powershell
pnpm --filter @angineer/admin-web build
pnpm --filter @angineer/user-web build
```

预期：两个 build 均成功（与上一轮 pdfjs 升级后一致）。

- [ ] **Step 3: 确认后端可导入**

```powershell
cd D:\AI\AnGIneer\services\api-server; python -c "import main; print('ok')"
```

预期输出：`ok`。

### 阶段 1：aichat-ui 独立包

#### 任务 1.1：创建 `packages/aichat-ui` 骨架

**Files:**
- Create: `packages/aichat-ui/package.json`
- Create: `packages/aichat-ui/tsconfig.json`
- Create: `packages/aichat-ui/src/index.ts`
- Create: `packages/aichat-ui/src/components/index.ts`
- Create: `packages/aichat-ui/src/composables/index.ts`
- Create: `packages/aichat-ui/src/types/index.ts`
- Create: `packages/aichat-ui/src/utils/index.ts`
- Create: `packages/aichat-ui/src/styles/index.less`

- [ ] **Step 1: 创建 `package.json`**

```json
{
  "name": "@angineer/aichat-ui",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "main": "./src/index.ts",
  "types": "./src/index.ts",
  "exports": {
    ".": {
      "import": "./src/index.ts",
      "types": "./src/index.ts"
    },
    "./style": "./src/styles/index.less",
    "./utils/citation": {
      "import": "./src/utils/citation.ts",
      "types": "./src/utils/citation.ts"
    },
    "./utils/markdown": {
      "import": "./src/utils/markdown.ts",
      "types": "./src/utils/markdown.ts"
    }
  },
  "peerDependencies": {
    "vue": "3.5.41",
    "ant-design-vue": "4.2.6",
    "@ant-design/icons-vue": "7.0.1"
  },
  "devDependencies": {
    "vue": "3.5.41",
    "ant-design-vue": "4.2.6",
    "@ant-design/icons-vue": "7.0.1",
    "katex": "0.18.4",
    "typescript": "~5.4.0",
    "less": "^4.2.0"
  },
  "dependencies": {
    "katex": "0.18.4"
  }
}
```

- [ ] **Step 2: 创建 `tsconfig.json`**

复制 `packages/docs-ui/tsconfig.json` 内容（见现状 1.1），include 不变。

- [ ] **Step 3: 创建入口文件**

`src/index.ts`：

```ts
export * from './components'
export * from './composables'
export type * from './types'
```

`src/components/index.ts`：

```ts
export { default as AIChat } from './AIChat.vue'
export { default as BaseChat } from './BaseChat.vue'
export { default as CitationInline } from './CitationInline.vue'
export { default as CitationMentionPanel } from './CitationMentionPanel.vue'
export { default as CitationPopover } from './CitationPopover.vue'
export { default as CitationRichContent } from './CitationRichContent.vue'
export { default as InlineCitationEditor } from './InlineCitationEditor.vue'
```

`src/composables/index.ts`：

```ts
export { useAIChat, buildSessionKey, getSessionSnapshot, getActiveSessionKeys, removeSession, clearSessionPool } from './useAIChat'
```

`src/types/index.ts`：

```ts
export type {
  CitationRichMediaOrderItem,
  CitationRichMediaValue,
  CitationReference,
  CitationRange,
  CitationBinding,
  InlineCitationDraftValue,
  InlineCitationCandidate,
  InlineCitationSearchPayload
} from './citation'
export type {
  BaseChatMessageRole,
  BaseChatMessage,
  BaseChatSendPayload,
  BaseChatCitation,
  CitationRichMedia,
  BaseChatContextItem,
  BaseChatModelOption,
  AIChatCitation,
  AIChatMessage,
  ThinkingTraceItem,
  ThinkingTraceStep,
  QueryRequest,
  QueryResponse,
  SessionKey,
  SessionSnapshot,
  AIChatContextConfig
} from './chat'
```

`src/utils/index.ts`：

```ts
export * from './citation'
export * from './markdown'
export * from './thinking'
export * from './token'
```

- [ ] **Step 4: 创建 `src/styles/index.less`（chat 变量默认值，宿主可覆盖）**

```less
// aichat-ui 主题变量默认值（宿主可通过覆盖同名变量定制）
:root {
  --chat-root-bg: var(--bg-primary, #ffffff);
  --chat-user-bubble-bg: var(--chat-user-bubble-bg, #e6f4ff);
  --chat-user-bubble-text: var(--chat-user-bubble-text, #000000);
  --chat-assistant-bubble-bg: var(--chat-assistant-bubble-bg, #f5f5f5);
  --chat-assistant-bubble-text: var(--chat-assistant-bubble-text, #000000);
  --chat-citation-accent: var(--chat-citation-accent, #1677ff);
  --chat-citation-bg: var(--chat-citation-bg, #e6f4ff);
  --chat-citation-border: var(--chat-citation-border, #91caff);
  --chat-code-bg: var(--chat-code-bg, #f6f8fa);
  --chat-pre-bg: var(--chat-pre-bg, #f6f8fa);
  --chat-error-color: var(--chat-error-color, #ff4d4f);
  --chat-error-hover: var(--chat-error-hover, #ff7875);
  --chat-streaming-bg: var(--chat-streaming-bg, #fffbe6);
  --chat-streaming-cursor: var(--chat-streaming-cursor, #1677ff);
  --chat-system-bg: var(--chat-system-bg, #fafafa);
  --chat-system-border: var(--chat-system-border, #d9d9d9);
  --chat-system-text: var(--chat-system-text, #8c8c8c);
}
```

- [ ] **Step 5: 提交**

```powershell
git -C D:\AI\AnGIneer add packages/aichat-ui
git -C D:\AI\AnGIneer commit -m "feat(aichat-ui): scaffold standalone aichat-ui package"
```

#### 任务 1.2：移动 chat 源码到 aichat-ui

**Files:**（git mv，全部保留文件历史）

- [ ] **Step 1: 移动组件**

```powershell
$src = "D:\AI\AnGIneer\packages\ui-kit\src"
$dst = "D:\AI\AnGIneer\packages\aichat-ui\src"
git -C D:\AI\AnGIneer mv "$src\components\common\AIChat.vue" "$dst\components\AIChat.vue"
git -C D:\AI\AnGIneer mv "$src\components\common\BaseChat.vue" "$dst\components\BaseChat.vue"
git -C D:\AI\AnGIneer mv "$src\components\common\CitationInline.vue" "$dst\components\CitationInline.vue"
git -C D:\AI\AnGIneer mv "$src\components\common\CitationMentionPanel.vue" "$dst\components\CitationMentionPanel.vue"
git -C D:\AI\AnGIneer mv "$src\components\common\CitationPopover.vue" "$dst\components\CitationPopover.vue"
git -C D:\AI\AnGIneer mv "$src\components\common\CitationRichContent.vue" "$dst\components\CitationRichContent.vue"
git -C D:\AI\AnGIneer mv "$src\components\common\InlineCitationEditor.vue" "$dst\components\InlineCitationEditor.vue"
git -C D:\AI\AnGIneer mv "$src\components\common\ThinkingSteps.vue" "$dst\components\ThinkingSteps.vue"
```

- [ ] **Step 2: 移动 composable / 契约 / 类型 / 工具**

```powershell
git -C D:\AI\AnGIneer mv "$src\composables\useAIChat.ts" "$dst\composables\useAIChat.ts"
git -C D:\AI\AnGIneer mv "$src\api\types.ts" "$dst\api\types.ts"
git -C D:\AI\AnGIneer mv "$src\types\chat.ts" "$dst\types\chat.ts"
git -C D:\AI\AnGIneer mv "$src\types\citation.ts" "$dst\types\citation.ts"
git -C D:\AI\AnGIneer mv "$src\utils\citation.ts" "$dst\utils\citation.ts"
git -C D:\AI\AnGIneer mv "$src\utils\markdown.ts" "$dst\utils\markdown.ts"
git -C D:\AI\AnGIneer mv "$src\utils\thinking.ts" "$dst\utils\thinking.ts"
git -C D:\AI\AnGIneer mv "$src\utils\token.ts" "$dst\utils\token.ts"
```

组件内部相对 import（`./BaseChat.vue`、`../utils/citation` 等）因目录层级一致而无需改动；`composables/useAIChat.ts` 的 `../utils/tree` 与 `api/types.ts` 的 `../types` 引用在任务 1.3 处理。

- [ ] **Step 3: 确认 ui-kit 内不再有 chat 引用**

```powershell
rg -n "BaseChat|AIChat|Citation|ThinkingSteps|useAIChat" D:\AI\AnGIneer\packages\ui-kit\src
```

预期：除 `components/index.ts`、`composables/index.ts`、`types/index.ts`、`package.json` 中的导出声明外无其他引用。

- [ ] **Step 4: 提交（如任务 0.1 选择方案 2，WIP 随本提交进入 aichat-ui）**

```powershell
git -C D:\AI\AnGIneer add -A packages/ui-kit packages/aichat-ui
git -C D:\AI\AnGIneer commit -m "refactor(aichat-ui): move AI chat module from ui-kit to aichat-ui"
```

#### 任务 1.3：本地化 `generateMessageId` / `estimateTokens`

**Files:**
- Create: `packages/aichat-ui/src/utils/tree.ts`
- Modify: `packages/aichat-ui/src/composables/useAIChat.ts`（第 17 行 import）

- [ ] **Step 1: 创建 `src/utils/tree.ts`**

内容取自 `packages/ui-kit/src/utils/tree.ts` 的 `generateMessageId` 与 `estimateTokens` 两个函数（原样复制，ui-kit 的 tree.ts 保留不动）。执行时以 ui-kit 现有实现为准：

```ts
export function generateMessageId(): string {
  return `msg-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

export function estimateTokens(content: string): number {
  if (!content) return 0
  const cjk = (content.match(/[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]/g) || []).length
  const rest = content.replace(/[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]/g, ' ')
  return Math.ceil(cjk + rest.trim().split(/\s+/).filter(Boolean).length * 1.3)
}
```

- [ ] **Step 2: 确认 useAIChat 的 import 解析到本地文件**

`packages/aichat-ui/src/composables/useAIChat.ts` 第 17 行保持 `import { generateMessageId, estimateTokens } from '../utils/tree'` 不变（现在 `../utils/tree` 解析到 aichat-ui 本地文件）。

- [ ] **Step 3: 提交**

```powershell
git -C D:\AI\AnGIneer add packages/aichat-ui/src/utils/tree.ts
git -C D:\AI\AnGIneer commit -m "refactor(aichat-ui): localize message id and token estimate utils"
```

#### 任务 1.4：清理 ui-kit 导出

**Files:**
- Modify: `packages/ui-kit/src/components/index.ts`
- Modify: `packages/ui-kit/src/composables/index.ts`
- Modify: `packages/ui-kit/src/types/index.ts`
- Modify: `packages/ui-kit/package.json`

- [ ] **Step 1: 移除组件导出**

`packages/ui-kit/src/components/index.ts` 删除以下 7 行（BaseChat/AIChat/CitationInline/CitationPopover/CitationRichContent/CitationMentionPanel/InlineCitationEditor）。

- [ ] **Step 2: 移除 composable 导出**

`packages/ui-kit/src/composables/index.ts` 删除 `useAIChat` 一行（保留 useTheme/useLayout/useThemeStore）。

- [ ] **Step 3: 移除类型导出**

`packages/ui-kit/src/types/index.ts` 删除 `from './citation'` 与 `from './chat'` 两个 export type 块（保留 `ThemeConfig`、`LayoutConfig`、`PanelProps`、`SmartTreeNode` 等其余导出）。

- [ ] **Step 4: 移除 package.json 子路径**

`packages/ui-kit/package.json` 删除 `./utils/citation`、`./utils/markdown` 两个 exports 条目（`./utils/tree` 保留）。

- [ ] **Step 5: 验证 ui-kit 内部无残留**

```powershell
rg -n "BaseChat|AIChat|Citation|ThinkingSteps|useAIChat" D:\AI\AnGIneer\packages\ui-kit\src
```

预期：无输出。

- [ ] **Step 6: 提交**

```powershell
git -C D:\AI\AnGIneer add packages/ui-kit
git -C D:\AI\AnGIneer commit -m "refactor(ui-kit): remove AI chat exports after aichat-ui split"
```

#### 任务 1.5：更新消费者与构建接入

**Files:**
- Modify: `apps/user-web/vite.config.ts`
- Modify: `apps/admin-web/vite.config.ts`
- Modify: `apps/user-web/src/App.vue`
- Modify: `apps/shared/chatTransport.ts`
- Modify: `packages/sop-ui/src/components/SOPStepNode.vue`
- Modify: `packages/sop-ui/src/components/SOPPropertyPanel.vue`
- Modify: `packages/sop-ui/src/types/sop.ts`

- [ ] **Step 1: 两个 app 的 vite.config.ts 增加 alias**

`apps/user-web/vite.config.ts` 与 `apps/admin-web/vite.config.ts` 的 `resolve.alias` 中，紧挨 `@angineer/ui-kit` 行后加：

```ts
'@angineer/aichat-ui': resolve(__dirname, '../../packages/aichat-ui/src'),
```

- [ ] **Step 2: user-web App.vue 拆分 import**

`apps/user-web/src/App.vue` 第 93 行改为：

```ts
import { AppHeader, SplitPanes, useTheme } from '@angineer/ui-kit'
import { AIChat } from '@angineer/aichat-ui'
```

- [ ] **Step 3: chatTransport.ts 类型来源**

`apps/shared/chatTransport.ts` 顶部两处 `from '@angineer/ui-kit'` 的类型导入改为 `from '@angineer/aichat-ui'`。

- [ ] **Step 4: sop-ui 引用迁移**

`packages/sop-ui/src/types/sop.ts`：

```ts
import type { InlineCitationDraftValue } from '@angineer/aichat-ui'
import type { SmartTreeNode } from '@angineer/ui-kit'
```

`packages/sop-ui/src/components/SOPStepNode.vue`：

```ts
import { CitationInline } from '@angineer/aichat-ui'
import type { CitationBinding } from '@angineer/aichat-ui'
import { buildCitationSegments } from '@angineer/aichat-ui/utils/citation'
```

`packages/sop-ui/src/components/SOPPropertyPanel.vue`：

```ts
import { InlineCitationEditor } from '@angineer/aichat-ui'
import type { CitationBinding, InlineCitationCandidate, InlineCitationSearchPayload } from '@angineer/aichat-ui'
import { mapReferenceSearchCandidate } from '@angineer/aichat-ui/utils/citation'
```

- [ ] **Step 5: 安装链接并构建验证**

```powershell
pnpm install
pnpm --filter @angineer/admin-web build
pnpm --filter @angineer/user-web build
```

预期：两个 build 通过（admin 构建会连带编译 sop-ui/evals-ui，覆盖全部消费方）。

- [ ] **Step 6: 提交**

```powershell
git -C D:\AI\AnGIneer add apps/user-web apps/admin-web apps/shared packages/sop-ui pnpm-lock.yaml
git -C D:\AI\AnGIneer commit -m "refactor(aichat-ui): switch consumers to @angineer/aichat-ui"
```

#### 任务 1.6：迁移测试并验证

**Files:**
- Move: `packages/ui-kit/test/useAIChat.test.ts` → `packages/aichat-ui/test/useAIChat.test.ts`
- Move: `packages/ui-kit/test/citation.test.ts` → `packages/aichat-ui/test/citation.test.ts`

- [ ] **Step 1: git mv 测试文件**

```powershell
git -C D:\AI\AnGIneer mv packages/ui-kit/test/useAIChat.test.ts packages/aichat-ui/test/useAIChat.test.ts
git -C D:\AI\AnGIneer mv packages/ui-kit/test/citation.test.ts packages/aichat-ui/test/citation.test.ts
```

两个测试文件中的相对 import（`../src/composables/useAIChat.ts`、`../src/types/chat`）在新目录结构下不变（`test/` 与 `src/` 平级），无需修改；若 ui-kit/test 中还有其他 chat 相关测试，一并迁移。

- [ ] **Step 2: 运行测试**

```powershell
node --test D:\AI\AnGIneer\packages\aichat-ui\test\useAIChat.test.ts
node --test D:\AI\AnGIneer\packages\aichat-ui\test\citation.test.ts
```

预期：全部通过（与迁移前一致）。

- [ ] **Step 3: 提交**

```powershell
git -C D:\AI\AnGIneer add packages/aichat-ui/test packages/ui-kit/test
git -C D:\AI\AnGIneer commit -m "test(aichat-ui): move chat tests into aichat-ui package"
```

### 阶段 2：后端拆两个服务

#### 任务 2.1：端口契约

**Files:**
- Modify: `apps/shared/ports.json`
- Modify: `apps/shared/ports.ts`
- Modify: `apps/user-web/vite.config.ts`
- Modify: `apps/admin-web/vite.config.ts`
- Modify: `start.ps1`

- [ ] **Step 1: ports.json 增加两个端口**

```json
{
  "localHost": "localhost",
  "apiServerPort": 8789,
  "docsApiPort": 8790,
  "aichatApiPort": 8791,
  "adminConsolePort": 3002,
  "webConsolePort": 3005
}
```

（`apiServerPort` 在任务 2.7 删除前暂时保留，避免中间态脚本失效。）

- [ ] **Step 2: ports.ts 增加导出**

`apps/shared/ports.ts` 增加：

```ts
export const DOCS_API_PORT = portContract.docsApiPort
export const AICHAT_API_PORT = portContract.aichatApiPort
```

- [ ] **Step 3: 两个 vite.config.ts 拆 proxy**

`apps/user-web/vite.config.ts`（admin-web 同构）在文件头增加：

```ts
const DOCS_API_PROXY_TARGET = `http://${portContract.localHost}:${portContract.docsApiPort}`
const AICHAT_API_PROXY_TARGET = `http://${portContract.localHost}:${portContract.aichatApiPort}`
```

`server.proxy` 改为：

```ts
proxy: {
  '/api/knowledge': { target: DOCS_API_PROXY_TARGET, changeOrigin: true },
  '/api/graph': { target: DOCS_API_PROXY_TARGET, changeOrigin: true },
  '/api/v1': { target: DOCS_API_PROXY_TARGET, changeOrigin: true },
  '/api/api-keys': { target: DOCS_API_PROXY_TARGET, changeOrigin: true },
  '/api/chat': { target: AICHAT_API_PROXY_TARGET, changeOrigin: true },
  '/api/sops': { target: AICHAT_API_PROXY_TARGET, changeOrigin: true },
  '/api/evals': { target: AICHAT_API_PROXY_TARGET, changeOrigin: true },
  '/api/dream-cycle': { target: AICHAT_API_PROXY_TARGET, changeOrigin: true },
  '/api/llm_configs': { target: AICHAT_API_PROXY_TARGET, changeOrigin: true },
  '/api/query': { target: AICHAT_API_PROXY_TARGET, changeOrigin: true },
  '/api': { target: DOCS_API_PROXY_TARGET, changeOrigin: true }
}
```

- [ ] **Step 4: start.ps1 按两个端口启动**

根 `package.json` scripts 更新：

```json
"dev:docs-api": "python services/docs-api/main.py",
"dev:aichat-api": "python services/aichat-api/main.py",
"dev:backend": "pnpm run --parallel dev:docs-api dev:aichat-api",
```

`start.ps1` 修改四处：

1. 变量区新增：

```powershell
$docsPort = $portContract.docsApiPort
$aichatPort = $portContract.aichatApiPort
$docsUrl = "http://${hostName}:${docsPort}"
$aichatUrl = "http://${hostName}:${aichatPort}"
```

2. 清理旧进程处增加：

```powershell
Stop-PortProcess -Label "DocsApi" -Port $docsPort
Stop-PortProcess -Label "AichatApi" -Port $aichatPort
```

3. 健康检查改为两个服务依次检查（复用现有 `Test-BackendHealth`）：

```powershell
$docsHealthy = Test-BackendHealth -Url $docsUrl -TimeoutSeconds 30
$aichatHealthy = Test-BackendHealth -Url $aichatUrl -TimeoutSeconds 30
```

4. 启动输出增加两个后端 URL（`Backend: $docsUrl / $aichatUrl`），`$backendProcess` 仍通过 `pnpm dev:backend` 启动（内部并行两个服务）。

- [ ] **Step 5: 提交**

```powershell
git -C D:\AI\AnGIneer add apps/shared/ports.json apps/shared/ports.ts apps/user-web/vite.config.ts apps/admin-web/vite.config.ts start.ps1
git -C D:\AI\AnGIneer commit -m "chore(ports): split docs-api and aichat-api ports and vite proxies"
```

#### 任务 2.2：创建 `services/docs-api`

**Files:**
- Create: `services/docs-api/main.py`
- Move: `services/api-server/docs_routes.py` → `services/docs-api/docs_routes.py`
- Move: `services/api-server/graph_routes.py` → `services/docs-api/graph_routes.py`
- Move: `services/api-server/api_key_routes.py` → `services/docs-api/api_key_routes.py`
- Move: `services/api-server/middleware/` → `services/docs-api/middleware/`
- Move: `services/api-server/models/` → `services/docs-api/models/`
- Move: `services/api-server/routes/` → `services/docs-api/routes/`

- [ ] **Step 1: git mv 文件**

```powershell
$api = "D:\AI\AnGIneer\services\api-server"
$dst = "D:\AI\AnGIneer\services\docs-api"
New-Item -ItemType Directory -Force -Path $dst | Out-Null
git -C D:\AI\AnGIneer mv "$api\docs_routes.py" "$dst\docs_routes.py"
git -C D:\AI\AnGIneer mv "$api\graph_routes.py" "$dst\graph_routes.py"
git -C D:\AI\AnGIneer mv "$api\api_key_routes.py" "$dst\api_key_routes.py"
git -C D:\AI\AnGIneer mv "$api\middleware" "$dst\middleware"
git -C D:\AI\AnGIneer mv "$api\models" "$dst\models"
git -C D:\AI\AnGIneer mv "$api\routes" "$dst\routes"
```

- [ ] **Step 2: 创建 `main.py`（完整内容）**

```python
"""docs-api — 文档解析、知识库、图谱、产物下载与 API Key 管理。"""
import os
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
SERVICES_DIR = ROOT_DIR / "services"

for pkg in ("docs-core", "angineer-core", "tree-core"):
    sys.path.insert(0, str(SERVICES_DIR / pkg / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from docs_routes import docs_router, preview_router
from graph_routes import graph_router
from api_key_routes import router as api_key_router
from routes.v1 import router as v1_router
from middleware.api_key_auth import APIKeyAuthMiddleware

app = FastAPI(
    title="AnGIneer Docs API",
    description="文档解析 API：上传 PDF/DOCX/PPTX，产出 content.md/images/jsonl/sqlite 产物。",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

_default_origins = "http://localhost:3005,http://localhost:3002,http://127.0.0.1:3005,http://127.0.0.1:3002,http://localhost,http://127.0.0.1"
_allowed_origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", _default_origins).split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)

app.add_middleware(APIKeyAuthMiddleware, scope="doc")

app.include_router(docs_router, prefix="/api/knowledge", tags=["Knowledge"])
app.include_router(preview_router, prefix="/api", tags=["Preview"])
app.include_router(graph_router, prefix="/api/graph", tags=["Knowledge Graph"])
app.include_router(api_key_router)
app.include_router(v1_router)


@app.get("/health")
def health():
    return {"service": "docs-api", "status": "ok"}


if __name__ == "__main__":
    import json
    import uvicorn

    with open(ROOT_DIR / "apps" / "shared" / "ports.json", "r", encoding="utf-8") as pf:
        API_SERVER_PORT = int(json.load(pf)["docsApiPort"])
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=API_SERVER_PORT,
        app_dir=str(Path(__file__).resolve().parent),
        reload=True,
        reload_dirs=[
            str(Path(__file__).resolve().parent),
            str(SERVICES_DIR / "docs-core" / "src"),
            str(SERVICES_DIR / "angineer-core" / "src"),
        ],
    )
```

- [ ] **Step 3: 提交**

```powershell
git -C D:\AI\AnGIneer add services/docs-api services/api-server
git -C D:\AI\AnGIneer commit -m "feat(docs-api): create standalone docs API service"
```

#### 任务 2.3：创建 `services/aichat-api`

**Files:**
- Create: `services/aichat-api/main.py`
- Move: `services/api-server/chat_agent.py` → `services/aichat-api/chat_agent.py`
- Move: `services/api-server/sop_routes.py` → `services/aichat-api/sop_routes.py`
- Move: `services/api-server/evals_routes.py` → `services/aichat-api/evals_routes.py`
- Move: `services/api-server/dream_cycle_routes.py` → `services/aichat-api/dream_cycle_routes.py`
- Copy: `services/api-server/middleware/api_key_auth.py` → `services/aichat-api/middleware/api_key_auth.py`
- Copy: `services/api-server/models/api_key.py` → `services/aichat-api/models/api_key.py`

- [ ] **Step 1: git mv / 复制文件**

```powershell
$api = "D:\AI\AnGIneer\services\api-server"
$dst = "D:\AI\AnGIneer\services\aichat-api"
New-Item -ItemType Directory -Force -Path "$dst\middleware","$dst\models" | Out-Null
git -C D:\AI\AnGIneer mv "$api\chat_agent.py" "$dst\chat_agent.py"
git -C D:\AI\AnGIneer mv "$api\sop_routes.py" "$dst\sop_routes.py"
git -C D:\AI\AnGIneer mv "$api\evals_routes.py" "$dst\evals_routes.py"
git -C D:\AI\AnGIneer mv "$api\dream_cycle_routes.py" "$dst\dream_cycle_routes.py"
Copy-Item "$api\middleware\api_key_auth.py" "$dst\middleware\api_key_auth.py"
Copy-Item "$api\models\api_key.py" "$dst\models\api_key.py"
```

- [ ] **Step 2: 创建 `main.py` 骨架**

```python
"""aichat-api — AI 问答、Agent 会话、SOP、Evals 与 DreamCycle。"""
import os
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
SERVICES_DIR = ROOT_DIR / "services"

for pkg in ("angineer-core", "ai-inference", "sop-core", "evals-core", "geo-core", "engtools", "docs-core", "tree-core"):
    sys.path.insert(0, str(SERVICES_DIR / pkg / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from middleware.api_key_auth import APIKeyAuthMiddleware
from sop_routes import sop_router
from evals_routes import evals_router
from dream_cycle_routes import dream_cycle_router

app = FastAPI(
    title="AnGIneer AIChat API",
    description="AI 问答 API：Agent 多轮会话、SSE 流式回答、引用与思考步骤。",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

_default_origins = "http://localhost:3005,http://localhost:3002,http://127.0.0.1:3005,http://127.0.0.1:3002,http://localhost,http://127.0.0.1"
_allowed_origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", _default_origins).split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)
app.add_middleware(APIKeyAuthMiddleware, scope="chat")

# ---- 以下路由从原 services/api-server/main.py 原样迁移，逻辑不变 ----
# 1) QueryRequest / SessionEntry / _SESSION_POOL / _get_or_create_session / _evict_expired_sessions
#    ChatMessage / ChatContext / ChatRequest / ChatStreamEvent / SteerRequest
#    execution_trace / _trace_json_safe / TraceDispatcher
# 2) @app.post("/chat") / @app.post("/chat/stream")
# 3) @app.get("/api/llm_configs")
# 4) @app.post("/api/chat") / @app.post("/api/chat/agent") / @app.post("/api/chat/agent/{run_id}/steer")
# 5) @app.get("/test_content/{test_id}") / @app.get("/test_cases/{test_id}")
#    @app.get("/test/stream/02") / @app.get("/test/stream/03") / @app.get("/test/stream/04")
#    @app.get("/run_test/{test_id}") / @app.post("/api/query")
# 迁移方式：用 `git show HEAD:services/api-server/main.py` 读取对应区段逐字复制，
# 原 main.py 的对应行号：173-380（模型/会话池/TraceDispatcher）、380-628（chat 路由）、
# 464-466（llm_configs）、636-915（test 路由与 /api/query）。

app.include_router(sop_router, prefix="/api/sops", tags=["SOPs"])
app.include_router(evals_router, prefix="/api/evals", tags=["Evals"])
app.include_router(dream_cycle_router, prefix="/api/dream-cycle", tags=["Dream Cycle"])


@app.get("/health")
def health():
    return {"service": "aichat-api", "status": "ok"}


if __name__ == "__main__":
    import json
    import uvicorn

    with open(ROOT_DIR / "apps" / "shared" / "ports.json", "r", encoding="utf-8") as pf:
        AICHAT_API_PORT = int(json.load(pf)["aichatApiPort"])
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=AICHAT_API_PORT,
        app_dir=str(Path(__file__).resolve().parent),
        reload=True,
        reload_dirs=[
            str(Path(__file__).resolve().parent),
            str(SERVICES_DIR / "angineer-core" / "src"),
            str(SERVICES_DIR / "ai-inference" / "src"),
            str(SERVICES_DIR / "sop-core" / "src"),
            str(SERVICES_DIR / "evals-core" / "src"),
            str(SERVICES_DIR / "engtools" / "src"),
        ],
    )
```

> 执行说明：上表列出的每个路由函数及其依赖的模型/全局状态，按原 `main.py` 的代码逐字复制（不改逻辑），只调整 import 来源。迁移完成后由任务 2.6 冒烟验证完整性。

- [ ] **Step 3: 提交**

```powershell
git -C D:\AI\AnGIneer add services/aichat-api services/api-server
git -C D:\AI\AnGIneer commit -m "feat(aichat-api): create standalone aichat API service"
```

#### 任务 2.4：API Key scope

**Files:**
- Modify: `services/docs-api/models/api_key.py`
- Modify: `services/docs-api/middleware/api_key_auth.py`
- Modify: `services/aichat-api/models/api_key.py`
- Modify: `services/aichat-api/middleware/api_key_auth.py`
- Modify: `services/docs-api/api_key_routes.py`

- [ ] **Step 1: api_key.py 增加 scope（两个服务各改一份，内容一致）**

`models/api_key.py` 修改三处：

1. `APIKey` dataclass 末尾增加 `scope: str = "both"`；
2. `init_db()` 的 CREATE TABLE 增加 `scope TEXT NOT NULL DEFAULT 'both'` 列，并在建表后执行迁移：

```python
cols = [row[1] for row in conn.execute("PRAGMA table_info(api_keys)").fetchall()]
if "scope" not in cols:
    conn.execute("ALTER TABLE api_keys ADD COLUMN scope TEXT NOT NULL DEFAULT 'both'")
```

3. `generate_key(..., scope: str = "both")` 的 INSERT 增加 scope 列与参数。

- [ ] **Step 2: middleware 参数化 scope（两个服务各改一份）**

`middleware/api_key_auth.py` 整体替换为：

```python
"""API Key 验证 FastAPI 中间件。按服务 scope 校验 X-API-Key。"""
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from models.api_key import lookup_key


class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, scope: str = "doc"):
        super().__init__(app)
        self.scope = scope

    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith(("/api/v1/", "/api/")):
            api_key = request.headers.get("X-API-Key", "").strip()
            if not api_key:
                raise HTTPException(status_code=401, detail="Missing X-API-Key header")

            key_info = lookup_key(api_key)
            if not key_info:
                raise HTTPException(status_code=403, detail="Invalid or inactive API key")
            if key_info.scope not in (self.scope, "both"):
                raise HTTPException(status_code=403, detail=f"API key has no {self.scope} scope")

            request.state.api_key_info = key_info

        return await call_next(request)
```

> 注意：docs-api 的中间件现在对 `/api/*` 全部校验（原来只校验 `/api/v1/*`）。为避免管理端无 key 请求被拦，任务 2.5 之后、冒烟之前为 admin-web 的 docs 请求补上 X-API-Key（开发环境可从现有 key 或 localStorage 读取）。**若不想引入该改动，可把中间件校验路径恢复为只校验 `/api/v1/*`，docs-api 内部接口继续免认证——执行时以"最小行为变化"为原则，优先保留现状，并在执行记录中标注。**

- [ ] **Step 3: 创建 key 时支持 scope**

`docs-api/api_key_routes.py` 的 `CreateKeyRequest` 增加：

```python
scope: str = Field(default="both", pattern="^(doc|chat|both)$")
```

`generate_key` 调用增加 `req.scope` 参数，`CreateKeyResponse` 增加 `scope: str` 字段并回填。

- [ ] **Step 4: 迁移现有 key 并验证**

```powershell
cd D:\AI\AnGIneer\services\docs-api
python -c "from models.api_key import init_db; init_db(); print('migrated')"
```

预期：输出 `migrated`，`data/api_keys.sqlite` 的 `api_keys` 表新增 `scope` 列且旧行默认 `both`。

- [ ] **Step 5: 提交**

```powershell
git -C D:\AI\AnGIneer add services/docs-api services/aichat-api
git -C D:\AI\AnGIneer commit -m "feat(auth): add scope to API keys and scope-aware middleware"
```

#### 任务 2.5：前端 client 拆分

**Files:**
- Modify: `apps/shared/apiClient.ts`
- Modify: `apps/user-web/src/api/knowledge.ts`
- Modify: `apps/admin-web/src/api/knowledge.ts`
- Modify: `apps/admin-web/src/api/apiKeys.ts`
- Modify: `apps/admin-web/src/api/evals.ts`
- Modify: `apps/admin-web/src/api/dreamCycle.ts`
- Modify: `apps/admin-web/src/api/sopResearch.ts`
- Modify: `apps/shared/chatTransport.ts`

- [ ] **Step 1: apiClient.ts 增加两个共享 client**

```ts
/** 文档处理服务客户端（/api/knowledge、/api/v1、/api/graph、/api/api-keys） */
export const docsApiClient: UnwrappedAxiosInstance = createApiClient({ baseURL: '/api' }) as UnwrappedAxiosInstance

/** AI 问答服务客户端（/api/chat、/api/sops、/api/evals、/api/dream-cycle、/api/llm_configs） */
export const aichatApiClient: UnwrappedAxiosInstance = createApiClient({ baseURL: '/api', timeout: 60000 }) as UnwrappedAxiosInstance
```

- [ ] **Step 2: 各 api 文件切换 import 与 URL**

规则：docs 用途改用 `docsApiClient`，chat 用途改用 `aichatApiClient`；原来把服务前缀放进 `baseURL` 的文件改为共享 client + 显式路径。

`apps/user-web/src/api/knowledge.ts`：`sharedApiClient` → `docsApiClient`（全部调用同步替换）。

`apps/admin-web/src/api/knowledge.ts` 与 `apps/admin-web/src/api/apiKeys.ts`：

```ts
const api = docsApiClient
```

（删除 `axios.create(getApiClientConfig(...))` 写法与 `axios`、`getApiClientConfig`、`registerDataUnwrapInterceptor` 的 import；`docsApiClient` 已是解包实例，原包装不再需要。）

`apps/admin-web/src/api/evals.ts`：

```ts
const api = aichatApiClient
```

并将所有请求路径前加 `/evals`（`'/datasets'` → `'/evals/datasets'`，`'/runs'` → `'/evals/runs'`）。

`apps/admin-web/src/api/dreamCycle.ts`：

```ts
const api = aichatApiClient
```

并将所有请求路径前加 `/dream-cycle`。

`apps/admin-web/src/api/sopResearch.ts`：`RESEARCH_BASE` 改为 `'/sops/research'`，`fetch` 调用改为 `aichatApiClient` 对应方法（GET/POST/PUT/DELETE），保持函数签名与返回值不变。

`apps/shared/chatTransport.ts`：`fetchModels` 改用 `aichatApiClient.get('/llm_configs')`，`searchReferences` 改用 `docsApiClient.post('/knowledge/references/search', payload)`。

- [ ] **Step 3: 构建验证**

```powershell
pnpm --filter @angineer/admin-web build
pnpm --filter @angineer/user-web build
```

预期：通过。

- [ ] **Step 4: 提交**

```powershell
git -C D:\AI\AnGIneer add apps/shared apps/user-web/src/api apps/admin-web/src/api
git -C D:\AI\AnGIneer commit -m "refactor(frontend): split api clients by backend service"
```

#### 任务 2.6：双服务冒烟

**Files:** 无（仅验证）。

- [ ] **Step 1: 启动 docs-api**

```powershell
Start-Job -ScriptBlock { Set-Location D:\AI\AnGIneer\services\docs-api; python -m uvicorn main:app --host 127.0.0.1 --port 8790 }
```

验证：

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8790/health
```

预期：`{"service":"docs-api","status":"ok"}`。

- [ ] **Step 2: 启动 aichat-api 并验证**

同上启动 `services/aichat-api`（端口 8791），验证 `/health` 返回 `{"service":"aichat-api","status":"ok"}`。

- [ ] **Step 3: 关键接口冒烟**

```powershell
$headers = @{ 'X-API-Key' = '<key>' }
Invoke-WebRequest -UseBasicParsing -Headers $headers "http://127.0.0.1:8790/api/v1/documents/doc-020a5d97/artifacts"
Invoke-WebRequest -UseBasicParsing -Method Post -Body '{"query":"test"}' "http://127.0.0.1:8791/api/chat/agent"
Invoke-WebRequest -UseBasicParsing -Headers $headers "http://127.0.0.1:8791/api/llm_configs"
```

预期：artifacts 200、chat 无 key 401、llm_configs 200（key 从现有 `data/api_keys.sqlite` 或任务 2.4 生成）。

- [ ] **Step 4: 前端联调**

启动两个 app dev server，验证：用户端文档页 PDF 渲染与解析面板（docs proxy）；AI 对话 SSE 流（aichat proxy）。

- [ ] **Step 5: 停止冒烟进程**

```powershell
Get-Job | Stop-Job; Get-Job | Remove-Job -Force
```

#### 任务 2.7：移除 `services/api-server`

**Files:**
- Delete: `services/api-server/`（git rm）
- Modify: `apps/shared/ports.json`、`apps/shared/ports.ts`（删除 apiServerPort）
- Modify: `start.ps1`（若仍有 apiServerPort 引用）

- [ ] **Step 1: 确认 api-server 已无引用**

```powershell
rg -n "api-server|apiServerPort" D:\AI\AnGIneer -g "!node_modules" -g "!**/dist/**" -g "!docs/**"
```

剩余引用仅允许出现在本任务要改的文件中。

- [ ] **Step 2: 删除目录与字段**

```powershell
git -C D:\AI\AnGIneer rm -r services/api-server
```

`ports.json` 删除 `apiServerPort`；`ports.ts` 删除 `API_SERVER_PORT`；`start.ps1` 删除相关行。

- [ ] **Step 3: 重新跑任务 2.6 冒烟（回归）**

预期：docs-api / aichat-api 仍正常。

- [ ] **Step 4: 提交**

```powershell
git -C D:\AI\AnGIneer add services apps/shared start.ps1
git -C D:\AI\AnGIneer commit -m "refactor(api): remove monolithic api-server after service split"
```

### 阶段 3：部署编排

#### 任务 3.1：Dockerfile / compose / nginx 双服务

**Files:**
- Modify: `docker/Dockerfile.backend`
- Modify: `docker/docker-compose.yml`
- Modify: `docker/nginx/nginx.conf`
- Modify: `docker/deploy-local.ps1`、`docker/deploy-local.sh`、`docker/deploy.sh`（若引用 api-server）

- [ ] **Step 1: Dockerfile.backend 尾部改为双服务入口**

将原尾部：

```dockerfile
WORKDIR /app/services/api-server

EXPOSE 8789

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8789"]
```

替换为：

```dockerfile
EXPOSE 8790 8791

# compose 中通过 command 覆盖入口：
# docs-api:  uvicorn main:app --host 0.0.0.0 --port 8790（workdir /app/services/docs-api）
# aichat-api: uvicorn main:app --host 0.0.0.0 --port 8791（workdir /app/services/aichat-api）
CMD ["python", "-c", "print('backend image: start via docker-compose command')"]
```

（`COPY services/ services/` 已覆盖新目录，无需新增 COPY。）

- [ ] **Step 2: docker-compose.yml 双服务**

将 `api-server` 服务整体替换为 `docs-api` 与 `aichat-api` 两个服务（均使用同一 `Dockerfile.backend` 镜像，通过 `command` 与 `working_dir` 区分）：

```yaml
  docs-api:
    build:
      context: ..
      dockerfile: docker/Dockerfile.backend
    image: angineer-docs-api:latest
    container_name: angineer-docs-api
    ports:
      - "8790:8790"
    command: ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8790"]
    working_dir: /app/services/docs-api
    env_file:
      - ../.env
    volumes:
      - ../data:/app/data
      - ../logs:/app/logs
    restart: unless-stopped
    networks:
      - angineer-net
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8790/health')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s

  aichat-api:
    build:
      context: ..
      dockerfile: docker/Dockerfile.backend
    image: angineer-aichat-api:latest
    container_name: angineer-aichat-api
    ports:
      - "8791:8791"
    command: ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8791"]
    working_dir: /app/services/aichat-api
    env_file:
      - ../.env
    volumes:
      - ../data:/app/data
      - ../logs:/app/logs
    restart: unless-stopped
    networks:
      - angineer-net
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8791/health')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s
```

`frontend` 服务的 `depends_on` 改为 `docs-api` 与 `aichat-api`。

- [ ] **Step 3: nginx.conf 双 upstream**

```nginx
    upstream api_server {
        server docs-api:8790;
    }

    upstream aichat_api {
        server aichat-api:8791;
    }
```

`location /api/` 块改为：

```nginx
        location /api/chat {
            proxy_pass http://aichat_api;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_buffering off;
            proxy_cache off;
            proxy_read_timeout 600s;
            chunked_transfer_encoding on;
        }

        location ~ ^/api/(sops|evals|dream-cycle|llm_configs|query) {
            proxy_pass http://aichat_api;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_read_timeout 300s;
            proxy_send_timeout 300s;
        }

        location /api/ {
            proxy_pass http://api_server;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_read_timeout 300s;
            proxy_send_timeout 300s;
        }
```

> nginx 的 `location /api/chat` 最长前缀优先于正则与 `location /api/`，SSE 不会被 buffering 干扰。`/docs`、`/redoc`、`/openapi.json` 保持指向 `api_server`（即 docs-api）。

- [ ] **Step 4: 更新部署脚本端口**

`docker/deploy-local.ps1`、`docker/deploy-local.sh`、`docker/deploy.sh` 中若硬编码 `8789` 或 `api-server`，同步替换为两个新服务（8790/8791），未引用则跳过。

- [ ] **Step 5: 提交**

```powershell
git -C D:\AI\AnGIneer add docker
git -C D:\AI\AnGIneer commit -m "feat(deploy): run docs-api and aichat-api as separate containers"
```

#### 任务 3.2：部署验证

**Files:** 无。

- [ ] **Step 1: compose 语法校验**

```powershell
docker compose -f D:\AI\AnGIneer\docker\docker-compose.yml config --quiet
```

预期：退出码 0，无错误输出。

- [ ] **Step 2: 本地镜像构建冒烟（可选，耗时）**

```powershell
docker compose -f D:\AI\AnGIneer\docker\docker-compose.yml build docs-api aichat-api
```

若服务器资源有限，跳过 build，仅保留 config 校验 + 任务 2.6 的本地双服务验证。

- [ ] **Step 3: 提交（如无文件改动则跳过）**

### 阶段 4：回归与文档

#### 任务 4.1：服务 README 与文档

**Files:**
- Create: `services/docs-api/README.md`
- Create: `services/aichat-api/README.md`
- Modify: `README.md`（根，服务说明区段）
- Modify: `docs/2026-08-11-ai-module-split-plan.md`（完成标记）

- [ ] **Step 1: 写 docs-api README**

内容必须包含：

1. 启动命令（`uvicorn main:app --host 0.0.0.0 --port 8790`，工作目录 `services/docs-api`）；
2. 数据依赖（`data/knowledge_base`、`data/api_keys.sqlite`）；
3. 认证说明（X-API-Key + scope=doc/both）；
4. 对外产物契约（content.md / images.zip / doc_blocks_graph.jsonl / meta.json / index.sqlite / graph.sqlite）；
5. 迁移说明（`api_keys` 表 scope 列由 `init_db()` 自动补齐）。

- [ ] **Step 2: 写 aichat-api README**

内容必须包含：

1. 启动命令（`uvicorn main:app --host 0.0.0.0 --port 8791`，工作目录 `services/aichat-api`）；
2. 数据依赖（只读 `data/knowledge_base` 与 `data/knowledge_*.sqlite`）；
3. 认证说明（X-API-Key + scope=chat/both）；
4. SSE 事件契约（run_start / tool_start / note / answer / message_delta / run_end）；
5. 会话说明（AgentSession 当前为内存态，单实例）。

- [ ] **Step 3: 更新根 README 服务说明**

把原来的 api-server 说明替换为 docs-api / aichat-api 双服务说明与端口表。

- [ ] **Step 4: 提交**

```powershell
git -C D:\AI\AnGIneer add services/docs-api/README.md services/aichat-api/README.md README.md docs
git -C D:\AI\AnGIneer commit -m "docs: document docs-api and aichat-api services"
```

#### 任务 4.2：全量回归

**Files:** 无。

- [ ] **Step 1: 前端全量构建**

```powershell
pnpm --filter @angineer/admin-web build
pnpm --filter @angineer/user-web build
```

- [ ] **Step 2: 后端双服务回归**

重复任务 2.6 冒烟四步（health、artifacts、chat 401、llm_configs）。

- [ ] **Step 3: 功能回归（关键用户路径）**

1. 上传一份 PDF → 解析完成 → 下载 content.md / images.zip / jsonl / sqlite（docs-api）；
2. 在用户端对解析后的文档发起 AI 问答，验证 SSE 回答与引用（aichat-api）；
3. 明暗主题切换下检查 AI 对话面板样式（CSS 变量由宿主提供）。

- [ ] **Step 4: 检查工作区**

```powershell
git -C D:\AI\AnGIneer status --short
```

只允许出现本计划之外的既有用户 WIP；本次改动应全部已提交。

## 4. 风险与注意

1. **任务 0.1 是硬阻塞**：chatTransport.ts 与 ui-kit chat 文件是未提交 WIP，阶段 1 直接触碰，必须先由用户决策。
2. docs-api 中间件改为对 `/api/*` 全量校验后，管理端（admin-web）调 `/api/knowledge`、`/api/graph` 等必须携带 X-API-Key；若不想引入该改动，执行时以"最小行为变化"为原则，把中间件校验路径恢复为只校验 `/api/v1/*`，docs-api 内部接口继续免认证，并在执行记录中标注。
3. aichat-api 的 evals/sop/dream_cycle 从原进程迁出后，其依赖的 `angineer_core.prompts.*`、`sop_core`、`evals_core` 均已纳入 sys.path；迁移时以 import 报错为线索补齐。
4. SQLite 共享：两个容器挂同一 `../data`，WAL 已启用；禁止两个服务同时写同一 sqlite 文件（api_keys 仅 docs-api 写；knowledge 仅 docs-api 写）。
5. 部署脚本（deploy-local.sh/ps1/deploy.sh）如硬编码 8789，需同步更新（任务 3.1 Step 4）。
6. 本计划完成后，`packages/aichat-ui` 即为可整体抽成 GitHub 仓库的形态（与 docs-ui 相同），届时做 subtree split 即可，不在本计划内。
