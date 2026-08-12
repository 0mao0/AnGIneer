# AI 模块解耦实施计划（aichat-ui / docs-api / aichat-api）

> **v2 修订（2026-08-12）**：angineer-core 内核改造已完成并提交（agent_loop / agent_session / tool_codec / prompts），
> 旧 `/chat`、`/chat/stream`、`/api/chat`、`/api/query`、`/test*` 端点已删除，`services/api-server/main.py` 已从 803 行瘦身到 284 行。
> 本版按当前仓库基线重写：任务 0.1 由"处理 WIP"改为"确认干净基线"；任务 2.3 改为直接编写小规模 aichat-api main.py；
> 补全阶段 1 消费方与依赖声明；API Key scope 按"最小行为变化"决策实施；任务 2.7/3.1 补全引用清理清单。

> **For agentic workers:** 本计划按任务逐项执行，每项完成即提交到 `main`（用户工作方式）。步骤使用 `- [ ]` 语法跟踪。

**Goal:** 把 AI 对话前端从 `ui-kit` 抽成独立的 `aichat-ui` 包，把单一 `api-server` 拆成 `docs-api` / `aichat-api` 两个独立服务目录，前端 API 客户端按服务拆分，API Key 统一申请 + scope 落库，并让 AnGIneer 以 docker-compose 双容器 + nginx 的方式保持独立一键部署。

**Architecture:** 前端两个组件库（docs-ui 已自包含、aichat-ui 本次抽出）对应后端两个服务（docs-api 写知识库、aichat-api 读知识库），两者只通过数据契约（sqlite/jsonl/content.md）解耦，互不调用。后端仍留在 AnGIneer monorepo 内（不建独立仓库），通过独立服务目录 + 独立端口 + 路径分流实现代码级解耦；部署阶段用 docker-compose 编排两个 API 容器 + nginx 统一入口。

**Tech Stack:** Vue 3 / TypeScript / Vite / pnpm；FastAPI / uvicorn / SQLite；docker-compose / nginx。

---

## 0. 已确认的决策

1. 仓库形态：AnGIneer 主仓库 + DredgeAI 主仓库 + docs-ui + aichat-ui 共四个仓库；**后端不建独立仓库**，在 monorepo 内拆 `services/docs-api`、`services/aichat-api` 两个独立服务目录。
2. 部署：docker-compose 起两个 API 容器 + 前端静态资源 + 一个 nginx；共享 `data/` 数据卷；对外仍是一个入口、一个产品。
3. 前端 API 客户端拆成两个（docs / aichat）。
4. API Key：统一申请入口 + 一张共享 key 表 + key 带 `scope`（`doc` / `chat` / `both`）。**本次按"最小行为变化"执行：中间件仍只校验 `/api/v1/*`，docs-api 校验 `doc` 权限、aichat-api 校验 `chat` 权限；内部 `/api/*`（knowledge/graph/sops/evals/chat 等）继续免认证**，避免前端全面注入 X-API-Key 及 `/api/api-keys` 自锁问题。scope 字段完整落库并随 v1 接口生效；将来要收紧为全量校验时，只需切换中间件路径白名单并配套前端 key 注入。
5. docs-ui 仓库化不在本计划范围（它已自包含，届时机械搬运即可）。
6. 内核改造已删除的旧端点（`/chat`、`/chat/stream`、`/api/chat`、`/api/query`、`/test*`）**不再迁移**；`/knowledge`、`/knowledge/{file_name}`、`/`、`/frontend` 等 legacy 路由随 `api-server` 删除，不进入任何新服务。
7. 全局异常处理器：docs-api **不迁移**（错误响应改为 FastAPI 默认形态，冒烟时确认前端兼容）；aichat-api **保留**（保持 chat 响应形状）。

## 1. 现状事实（2026-08-12 已核验）

### 1.1 前端

- `packages/docs-ui` 已自包含（src 内无 `@angineer/*` 依赖），被 user-web 与 admin-web 使用。
- AIChat 全家在 `packages/ui-kit`：
  - 组件：`components/common/{AIChat,BaseChat,CitationInline,CitationMentionPanel,CitationPopover,CitationRichContent,InlineCitationEditor,ThinkingSteps}.vue`
  - composable：`composables/useAIChat.ts`（依赖 `utils/tree.ts` 的 `generateMessageId` / `estimateTokens`）
  - 契约：`api/types.ts`（`AIChatTransport`）
  - 类型：`types/chat.ts`、`types/citation.ts`
  - 工具：`utils/citation.ts`、`utils/markdown.ts`（依赖 katex）、`utils/thinking.ts`、`utils/token.ts`
  - 测试（均已提交）：`test/useAIChat.test.ts`、`test/citation.test.ts`、`test/thinking.test.ts`、`test/token.test.ts`
- 消费者（2026-08-12 全量 `rg` 核验）：
  - `apps/user-web/src/App.vue`：`AIChat`
  - `apps/admin-web/src/views/ExperienceManage.vue`：`AIChat`、`CitationBinding`（WIP 已提交）
  - `apps/admin-web/src/components/KnowledgeParseWorkspace.vue`：`AIChat`
  - `apps/shared/chatTransport.ts`：`QueryRequest` 等类型 + `defaultAIChatTransport`
  - `apps/shared/chatTransport.test.ts`：`ThinkingTraceItem`、`ThinkingTraceStep`
  - `packages/sop-ui/src/types/sop.ts`：`InlineCitationDraftValue`
  - `packages/sop-ui/src/composables/useSopApi.ts`：`InlineCitationSearchPayload`
  - `packages/sop-ui/src/components/SOPFlowCanvas.vue`：`CitationBinding`
  - `packages/sop-ui/src/components/SOPStepNode.vue`：`CitationInline`、`CitationBinding`、`buildCitationSegments`
  - `packages/sop-ui/src/components/SOPPropertyPanel.vue`：`InlineCitationEditor`、`CitationBinding`、`InlineCitationCandidate`、`InlineCitationSearchPayload`、`mapReferenceSearchCandidate`
  - `packages/evals-ui/src/components/EvalQuestionCard.vue`：`renderMarkdownToHtml`（来自 `@angineer/ui-kit/utils/markdown`，阶段 1 必须同步切换）
- ui-kit 的 `package.json` 暴露子路径 `./utils/citation`、`./utils/markdown`、`./utils/tree`。
- chat 组件使用的 CSS 变量（17 个，均有 fallback）：`--chat-root-bg --chat-user-bubble-bg --chat-user-bubble-text --chat-assistant-bubble-bg --chat-assistant-bubble-text --chat-citation-accent --chat-citation-bg --chat-citation-border --chat-code-bg --chat-pre-bg --chat-error-color --chat-error-hover --chat-streaming-bg --chat-streaming-cursor --chat-system-bg --chat-system-border --chat-system-text`。
- `docs-ui` 的 `tsconfig.json` 可作为新包模板。
- 两个 app 的 build 均为 `vue-tsc -b && vite build`，tsconfig `paths` 与 package.json 依赖都要同步补 `@angineer/aichat-ui`（仅加 vite alias 不够）。

### 1.2 后端

- `services/api-server`（FastAPI，端口 8789，main.py 284 行）承载：
  - docs 系：`docs_routes.py`（`/api/knowledge/*` + preview `/api/*`）、`graph_routes.py`（`/api/graph/*`）、`routes/v1/`（`/api/v1/*`）、`api_key_routes.py`（`/api/api-keys/*`）
  - chat 系（全部在 main.py）：`GET /api/llm_configs`、`POST /api/chat/agent`、`POST /api/chat/agent/{run_id}/steer`；`chat_agent.py` 提供 `find_session_by_run_id` / `get_agent_session` / `make_policy_config_factory` / `map_event_to_agent_frame`
  - 其他：`sop_routes.py`（`/api/sops/*`）、`evals_routes.py`（`/api/evals/*`）、`dream_cycle_routes.py`（`/api/dream-cycle/*`）
  - legacy（不迁移）：`/`、`/frontend`、`/knowledge`、`/knowledge/{file_name}`
- 共享小件：`middleware/api_key_auth.py`（仅校验 `/api/v1/*`）、`models/api_key.py`（`data/api_keys.sqlite`，WAL 模式）、`models/parse_record.py`、`models/v1_responses.py`（`CreateKeyRequest` 在此文件，不在 api_key_routes.py）
- 数据：`data/knowledge_base/**/parsed/{content.md,images,doc_blocks_graph.jsonl,...}` + `data/knowledge_*.sqlite`；`data/sops`（SOP_BASE_DIR）；`data/evals/evals.sqlite`（evals_core 默认路径）；`data/reports/*.json`（dream-cycle）
- `services/docs-core`（含 MinerU/PoPo submodule 定制）、`services/angineer-core`（已内核改造）、`services/ai-inference`、`services/engtools`、`services/sop-core`、`services/evals-core`、`services/geo-core`、`services/tree-core` 均为可 pip install -e 的包
- 部署现状：`docker/docker-compose.yml`（frontend + api-server）、`docker/Dockerfile.backend`（装全部 core 包 + libreoffice，CMD 起 api-server）、`docker/Dockerfile.frontend`、`docker/nginx/nginx.conf`（upstream api-server:8789，`/api/` 反代）
- 端口契约：`apps/shared/ports.json` 现有 `apiServerPort: 8789`、`adminConsolePort: 3002`、`webConsolePort: 3005`；引用方：`main.py`、两个 `vite.config.ts`、`apps/shared/ports.ts`、`start.ps1`

### 1.3 已知风险（执行前必读）

- **基线已干净**：内核改造相关 WIP 已全部提交（`git status --short` 为空）。执行期间不要再引入未提交的混合改动；若出现计划之外的 WIP，先与用户确认。
- **阶段 1 消费方多且分散**：admin-web 两个页面、sop-ui 五个文件、evals-ui 一个文件、apps/shared 两个文件都要同步改；漏一个就 `vue-tsc` 失败。
- **依赖声明是硬前提**：`@angineer/aichat-ui` 必须写入 admin-web / user-web / sop-ui / evals-ui 的 package.json `dependencies`，并补两个 app 的 tsconfig `paths`；只加 vite alias 无法通过 `vue-tsc -b`。
- **鉴权采用最小变化**：中间件仍只校验 `/api/v1/*`；`scope` 落库并生效于 v1 接口。不要在本次把校验扩展到全部 `/api/*`（前端无 key 注入、`/api/api-keys` 会自锁）。
- **docs-api 错误响应形态变化**：原全局异常处理器（返回 200 + query 形状 JSON）不迁入 docs-api，错误将变为 FastAPI 默认 4xx/5xx；冒烟时确认 admin 解析面板对错误提示的兼容性。
- **admin `knowledge.ts` 混合调用**：`getLlmConfigs` 是 aichat 端点（`/llm_configs`），与 docs 调用在同一文件；切换 client 时必须拆开，不能整文件切 docsApiClient。
- 两个服务共享 `data/` 数据卷：SQLite 已启用 WAL，docs 写 / chat 读并发可接受；api_keys.sqlite 由 docs-api 写、两个服务读，同样 WAL 兼容。禁止两个服务同时写同一 sqlite 文件。
- `services/docs-core/src/popo` 是 submodule 且有本地定制（`post_processing/model_utils.py`），本计划不移动它，仅提醒未来仓库化时保留。
- 阶段 2 的 2.2 与 2.3 之间，`api-server` 处于不可启动的中间态（docs 文件已迁走、chat 尚未迁走），建议连续执行 2.2 → 2.3 后再做冒烟。

## 2. 目标结构

```
AnGIneer/
├─ packages/
│  ├─ docs-ui/                    # 已有，不动
│  ├─ aichat-ui/                  # 新增：AI 对话组件库（本次抽出）
│  └─ ui-kit/                     # 保留布局/主题/通用组件，移除 chat 全家
├─ services/
│  ├─ docs-api/                   # 新增：文档解析/知识库/图谱/v1/Key 管理（8790）
│  ├─ aichat-api/                 # 新增：对话/模型配置/SOP/Evals/DreamCycle（8791）
│  └─ api-server/                 # 删除（拆分完成并验证后）
├─ apps/shared/                   # ports、docsApiClient、aichatApiClient、chatTransport
└─ docker/                        # compose 双 API 容器 + nginx
```

路由归属：

| 路径 | 服务 |
|---|---|
| `/api/knowledge/*`、`/api/graph/*`、`/api/*`（preview）、`/api/v1/*`、`/api/api-keys/*` | docs-api |
| `/api/llm_configs`、`/api/chat/agent*`、`/api/sops/*`、`/api/evals/*`、`/api/dream-cycle/*` | aichat-api |
| `/`、`/frontend`、`/knowledge`、`/knowledge/{file_name}`、`/chat*`、`/api/query`、`/test*` | 已删除，不迁移 |

## 3. 实施任务

### 阶段 0：准备

#### 任务 0.1：确认干净基线【前置项】

**Files:** 不修改文件；只做 git 状态确认。

- [ ] **Step 1: 确认工作区干净**

运行：

```powershell
git -C D:\AI\AnGIneer status --short
git -C D:\AI\AnGIneer log -1 --oneline
```

预期：无输出（或仅用户明确告知的计划外改动）；HEAD 为内核改造后的提交（当前应为 `1254d66` 或其后继提交）。

- [ ] **Step 2: 若出现计划外 WIP，停下与用户确认**，不要带着混合改动开始阶段 1。

**本任务完成后才能进入阶段 1。**

#### 任务 0.2：基线验证

**Files:** 无。

- [ ] **Step 1: 确认依赖与构建基线**

```powershell
pnpm install
pnpm --filter @angineer/admin-web build
pnpm --filter @angineer/user-web build
```

预期：两个 build 均成功。

- [ ] **Step 2: 确认后端可导入**

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

复制 `packages/docs-ui/tsconfig.json` 内容，include 不变。

- [ ] **Step 3: 创建入口文件**

`src/index.ts`：

```ts
export * from './components'
export * from './composables'
export type * from './types'
```

`src/components/index.ts`（ThinkingSteps 仅 BaseChat 内部使用，与 ui-kit 现状一致，不公开导出）：

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

组件内部相对 import（`./BaseChat.vue`、`../utils/citation`、`../../utils/thinking` 等）因目录层级一致而无需改动；`composables/useAIChat.ts` 的 `../utils/tree` 与 `api/types.ts` 的 `../types` 引用在任务 1.3 处理。

- [ ] **Step 3: 确认 ui-kit 内不再有 chat 源码引用（除待清理的导出文件）**

```powershell
rg -n "BaseChat|AIChat|Citation|ThinkingSteps|useAIChat" D:\AI\AnGIneer\packages\ui-kit\src
```

预期：除 `components/index.ts`、`composables/index.ts`、`types/index.ts`、`package.json` 中的导出声明外无其他引用。

- [ ] **Step 4: 提交**

```powershell
git -C D:\AI\AnGIneer add -A packages/ui-kit packages/aichat-ui
git -C D:\AI\AnGIneer commit -m "refactor(aichat-ui): move AI chat module from ui-kit to aichat-ui"
```

#### 任务 1.3：本地化 `generateMessageId` / `estimateTokens`

**Files:**
- Create: `packages/aichat-ui/src/utils/tree.ts`
- Modify: `packages/aichat-ui/src/composables/useAIChat.ts`（import 不动，随文件移动自动解析到本地）

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

- [ ] **Step 2: 确认 `useAIChat.ts` 的 `../utils/tree` import 解析到本地文件**（移动后目录结构不变，无需改代码）。

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

`packages/ui-kit/package.json` 删除 `./utils/citation`、`./utils/markdown` 两个 exports 条目（`./utils/tree` 保留，admin 的 `KnowledgeParseWorkspace.vue` 仍使用）。

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

#### 任务 1.5：更新消费者、依赖声明与构建接入

**Files:**
- Modify: `apps/user-web/package.json`、`apps/admin-web/package.json`（新增依赖）
- Modify: `packages/sop-ui/package.json`、`packages/evals-ui/package.json`（新增依赖）
- Modify: `apps/user-web/tsconfig.json`、`apps/admin-web/tsconfig.json`（新增 paths）
- Modify: `apps/user-web/vite.config.ts`、`apps/admin-web/vite.config.ts`（新增 alias）
- Modify: `apps/user-web/src/App.vue`
- Modify: `apps/admin-web/src/views/ExperienceManage.vue`
- Modify: `apps/admin-web/src/components/KnowledgeParseWorkspace.vue`
- Modify: `apps/shared/chatTransport.ts`
- Modify: `apps/shared/chatTransport.test.ts`
- Modify: `packages/sop-ui/src/types/sop.ts`
- Modify: `packages/sop-ui/src/composables/useSopApi.ts`
- Modify: `packages/sop-ui/src/components/SOPFlowCanvas.vue`
- Modify: `packages/sop-ui/src/components/SOPStepNode.vue`
- Modify: `packages/sop-ui/src/components/SOPPropertyPanel.vue`
- Modify: `packages/evals-ui/src/components/EvalQuestionCard.vue`

- [ ] **Step 1: 声明依赖（pnpm 严格链接必需，否则 vue-tsc 无法解析）**

在 `apps/user-web/package.json`、`apps/admin-web/package.json`、`packages/sop-ui/package.json`、`packages/evals-ui/package.json` 的 `dependencies` 中新增：

```json
"@angineer/aichat-ui": "workspace:*"
```

- [ ] **Step 2: 两个 app 的 tsconfig paths**

`apps/user-web/tsconfig.json` 与 `apps/admin-web/tsconfig.json` 的 `paths` 中，紧挨 `@angineer/ui-kit` 行后加：

```json
"@angineer/aichat-ui": ["../../packages/aichat-ui/src"]
```

- [ ] **Step 3: 两个 app 的 vite alias**

`apps/user-web/vite.config.ts` 与 `apps/admin-web/vite.config.ts` 的 `resolve.alias` 中，紧挨 `@angineer/ui-kit` 行后加：

```ts
'@angineer/aichat-ui': resolve(__dirname, '../../packages/aichat-ui/src'),
```

- [ ] **Step 4: user-web App.vue 拆分 import**

`apps/user-web/src/App.vue` 第 93 行改为：

```ts
import { AppHeader, SplitPanes, useTheme } from '@angineer/ui-kit'
import { AIChat } from '@angineer/aichat-ui'
```

- [ ] **Step 5: admin-web 两个页面迁移**

`apps/admin-web/src/views/ExperienceManage.vue`：

```ts
import { SplitPanes, Panel, useTheme, type DropEvent } from '@angineer/ui-kit'
import { AIChat } from '@angineer/aichat-ui'
import type { CitationBinding } from '@angineer/aichat-ui'
```

`apps/admin-web/src/components/KnowledgeParseWorkspace.vue`：

```ts
import { SplitPanes, Panel, type DropEvent } from '@angineer/ui-kit'
import { AIChat } from '@angineer/aichat-ui'
```

- [ ] **Step 6: chatTransport 及其测试迁移类型来源**

`apps/shared/chatTransport.ts` 顶部两处 `from '@angineer/ui-kit'` 的类型导入改为 `from '@angineer/aichat-ui'`。

`apps/shared/chatTransport.test.ts` 的 `import type { ThinkingTraceItem, ThinkingTraceStep } from '@angineer/ui-kit'` 同样改为 `from '@angineer/aichat-ui'`。

- [ ] **Step 7: sop-ui 引用迁移**

`packages/sop-ui/src/types/sop.ts`：

```ts
import type { InlineCitationDraftValue } from '@angineer/aichat-ui'
import type { SmartTreeNode } from '@angineer/ui-kit'
```

`packages/sop-ui/src/composables/useSopApi.ts`：

```ts
import type { InlineCitationSearchPayload } from '@angineer/aichat-ui'
```

`packages/sop-ui/src/components/SOPFlowCanvas.vue`：

```ts
import type { CitationBinding } from '@angineer/aichat-ui'
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

- [ ] **Step 8: evals-ui markdown 依赖迁移**

`packages/evals-ui/src/components/EvalQuestionCard.vue` 第 831 行：

```ts
import { renderMarkdownToHtml } from '@angineer/aichat-ui/utils/markdown'
```

- [ ] **Step 9: 安装链接并构建验证**

```powershell
pnpm install
pnpm --filter @angineer/admin-web build
pnpm --filter @angineer/user-web build
```

预期：两个 build 通过（admin 构建会连带编译 sop-ui/evals-ui，覆盖全部消费方；本任务已把消费方清单补全）。

- [ ] **Step 10: 提交**

```powershell
git -C D:\AI\AnGIneer add apps packages pnpm-lock.yaml
git -C D:\AI\AnGIneer commit -m "refactor(aichat-ui): switch consumers to @angineer/aichat-ui"
```

#### 任务 1.6：迁移测试并验证

**Files:**
- Move: `packages/ui-kit/test/citation.test.ts` → `packages/aichat-ui/test/citation.test.ts`
- Move: `packages/ui-kit/test/useAIChat.test.ts` → `packages/aichat-ui/test/useAIChat.test.ts`
- Move: `packages/ui-kit/test/thinking.test.ts` → `packages/aichat-ui/test/thinking.test.ts`
- Move: `packages/ui-kit/test/token.test.ts` → `packages/aichat-ui/test/token.test.ts`

- [ ] **Step 1: git mv 测试文件**

```powershell
git -C D:\AI\AnGIneer mv packages/ui-kit/test/citation.test.ts packages/aichat-ui/test/citation.test.ts
git -C D:\AI\AnGIneer mv packages/ui-kit/test/useAIChat.test.ts packages/aichat-ui/test/useAIChat.test.ts
git -C D:\AI\AnGIneer mv packages/ui-kit/test/thinking.test.ts packages/aichat-ui/test/thinking.test.ts
git -C D:\AI\AnGIneer mv packages/ui-kit/test/token.test.ts packages/aichat-ui/test/token.test.ts
```

测试文件中的相对 import（`../src/composables/useAIChat.ts`、`../src/types/chat`、`../src/utils/thinking` 等）在新目录结构下不变（`test/` 与 `src/` 平级），无需修改。

- [ ] **Step 2: 运行测试**

```powershell
node --test D:\AI\AnGIneer\packages\aichat-ui\test\useAIChat.test.ts
node --test D:\AI\AnGIneer\packages\aichat-ui\test\citation.test.ts
node --test D:\AI\AnGIneer\packages\aichat-ui\test\thinking.test.ts
node --test D:\AI\AnGIneer\packages\aichat-ui\test\token.test.ts
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
- Modify: `package.json`（root scripts）

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
  '/api': { target: DOCS_API_PROXY_TARGET, changeOrigin: true }
}
```

（Vite 按 key 长度优先匹配，长前缀先命中；`/api/chat` 等会正确分流。）

- [ ] **Step 4: root package.json scripts 与 start.ps1**

root `package.json` scripts 更新：

```json
"dev:docs-api": "python services/docs-api/main.py",
"dev:aichat-api": "python services/aichat-api/main.py",
"dev:backend": "pnpm run --parallel dev:docs-api dev:aichat-api"
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
git -C D:\AI\AnGIneer add apps/shared/ports.json apps/shared/ports.ts apps/user-web/vite.config.ts apps/admin-web/vite.config.ts start.ps1 package.json
git -C D:\AI\AnGIneer commit -m "chore(ports): split docs-api and aichat-api ports and vite proxies"
```

> 中间态提示：任务 2.1 提交后到任务 2.5 提交前，dev proxy 已按新端口分流，但前端 client 尚未切换，chat/evals 等请求会暂时失败；阶段 2 建议 2.1 → 2.5 连续执行，不要中间停顿。

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

# 任务 2.4 后中间件带 scope；按决策仅校验 /api/v1/*（详见 middleware/api_key_auth.py）
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

> 说明：原全局异常处理器不迁入（见决策 7）；`/`、`/frontend`、`/knowledge` legacy 路由不迁入。

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
- Copy: `services/api-server/middleware/api_key_auth.py` → `services/aichat-api/middleware/api_key_auth.py`（2.4 再改）
- Copy: `services/api-server/models/api_key.py` → `services/aichat-api/models/api_key.py`（2.4 再改）

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

- [ ] **Step 2: 创建 `main.py`（完整内容，基于当前 284 行 main.py 的 chat 部分）**

```python
"""aichat-api — AI 问答（AgentSession SSE）、模型配置、SOP、Evals 与 DreamCycle。"""
import os
import sys
import json
import asyncio
import uuid
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
SERVICES_DIR = ROOT_DIR / "services"

for pkg in (
    "ai-inference", "angineer-core", "sop-core", "docs-core",
    "geo-core", "engtools", "evals-core", "tree-core",
):
    sys.path.insert(0, str(SERVICES_DIR / pkg / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ai_inference.llm_client import LLMClient
from angineer_core import IntentClassifier
from chat_agent import (
    find_session_by_run_id,
    get_agent_session,
    make_policy_config_factory,
    map_event_to_agent_frame,
)
from sop_core.sop_loader import SopLoader
from engtools import *
import geo_core.GisTool
import engtools.KnowledgeTool
from sop_routes import sop_router
from evals_routes import evals_router
from dream_cycle_routes import dream_cycle_router
from middleware.api_key_auth import APIKeyAuthMiddleware

app = FastAPI(
    title="AnGIneer AIChat API",
    description="AI 问答 API：Agent 多轮会话、SSE 流式回答、引用与思考步骤。",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """保留原 api-server 的全局异常处理，保持 chat 响应形状。"""
    from angineer_core.base_utils import is_fatal_exception
    if is_fatal_exception(exc):
        raise
    import traceback as _tb
    _tb.print_exc()
    logger.error(f"未处理异常: {exc}", exc_info=True)
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=200,
        content={
            "query_id": f"q-{uuid.uuid4().hex[:12]}",
            "session_key": "",
            "intent": {},
            "answer": f"抱歉，服务处理出现异常：{type(exc).__name__}: {exc}",
            "citations": [],
            "retrieved_items": [],
            "sql": None,
            "fallback_used": False,
            "latency_ms": 0,
        },
    )


SOP_BASE_DIR = os.path.join(str(ROOT_DIR), "data", "sops")
sop_loader = SopLoader(SOP_BASE_DIR)

_default_origins = "http://localhost:3005,http://localhost:3002,http://127.0.0.1:3005,http://127.0.0.1:3002,http://localhost,http://127.0.0.1"
_allowed_origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", _default_origins).split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)

# 任务 2.4 后中间件带 scope；按决策仅校验 /api/v1/*（aichat-api 当前无 /api/v1 路由，中间件实际不拦截）
app.add_middleware(APIKeyAuthMiddleware, scope="chat")

app.include_router(sop_router, prefix="/api/sops", tags=["SOPs"])
app.include_router(evals_router, prefix="/api/evals", tags=["Evals"])
app.include_router(dream_cycle_router, prefix="/api/dream-cycle", tags=["Dream Cycle"])


class QueryRequest(BaseModel):
    """统一查询请求，支持 scene + id 会话池路由。"""
    query: str
    scene: str = "docs"
    session_id: Optional[str] = None
    library_id: str = "default"
    doc_ids: List[str] = Field(default_factory=list)
    inline_citations: List[Dict[str, Any]] = Field(default_factory=list)
    config: Optional[str] = None
    mode: Optional[str] = None
    history: List[Dict[str, Any]] = Field(default_factory=list)


class SteerRequest(BaseModel):
    """run 中途 steer 注入请求体。"""
    text: str


@app.get("/api/llm_configs")
def list_llm_configs():
    """获取可用 LLM 模型配置列表。"""
    try:
        client = LLMClient()
        configs = [{"name": c["name"], "model": c["model"], "configured": bool(c["api_key"])} for c in client.configs]
        default_model = os.getenv("ANGINEER_DEFAULT_MODEL", "")
        if default_model:
            idx = next((i for i, c in enumerate(configs) if c["name"] == default_model), None)
            if idx is not None and idx > 0:
                configs.insert(0, configs.pop(idx))
        return configs
    except Exception as e:
        logger.error(f"获取 LLM 配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取模型配置失败: {str(e)}")


@app.post("/api/chat/agent")
async def chat_agent_stream(request: QueryRequest, raw_request: Request):
    """Agent SSE：run/turn/tool 事件按 AgentEvent 帧输出。"""
    async def event_stream():
        try:
            session = get_agent_session(
                request.scene or "qa",
                request.session_id,
                library_id=request.library_id,
                doc_ids=request.doc_ids,
            )

            queue: asyncio.Queue = asyncio.Queue()

            def emit(event):
                queue.put_nowait(event)

            loop = asyncio.get_event_loop()
            intent_result = None
            try:
                sops = sop_loader.load_all() if sop_loader is not None else []
                intent_result = IntentClassifier(sops).classify_intent(
                    request.query,
                    config_name=request.config,
                    mode=request.mode or "instruct",
                )
            except Exception as exc:
                logger.warning("Agent 意图分级失败，按 scene 默认路由: %s", exc)
            config_factory = make_policy_config_factory(
                request.scene or "qa",
                request.library_id,
                request.doc_ids,
                intent_result=intent_result,
                sop_loader=sop_loader,
            )
            run_future = loop.run_in_executor(
                None,
                session.run,
                request.query,
                emit,
                config_factory,
            )

            while True:
                if await raw_request.is_disconnected():
                    session.cancel()
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.2)
                except asyncio.TimeoutError:
                    if run_future.done():
                        break
                    continue
                yield f"data: {map_event_to_agent_frame(event)}\n\n"
                if event.type in ("run_end", "error"):
                    break
            await run_future

            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error(f"Agent 对话错误: {e}")
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/chat/agent/{run_id}/steer")
def steer_agent(run_id: str, request: SteerRequest):
    """run 中途 steer 注入，下一 turn 生效。"""
    session = find_session_by_run_id(run_id)
    if session is None:
        raise HTTPException(status_code=404, detail="run not found or already finished")
    session.steer(request.text)
    return {"status": "ok", "run_id": run_id}


@app.get("/health")
def health():
    return {"service": "aichat-api", "status": "ok"}


if __name__ == "__main__":
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

> 执行说明：以上代码从当前 `services/api-server/main.py`（284 行版）的 chat 部分原样迁移，不改逻辑；若内核后续再调整 AgentSession 接口，以当前 `chat_agent.py` 与 `angineer_core` 实际签名为准。legacy `/`、`/frontend`、`/knowledge` 路由不迁移。

- [ ] **Step 3: 提交**

```powershell
git -C D:\AI\AnGIneer add services/aichat-api services/api-server
git -C D:\AI\AnGIneer commit -m "feat(aichat-api): create standalone aichat API service"
```

#### 任务 2.4：API Key scope

**Files:**
- Modify: `services/docs-api/models/api_key.py`
- Modify: `services/docs-api/middleware/api_key_auth.py`
- Modify: `services/docs-api/models/v1_responses.py`
- Modify: `services/docs-api/api_key_routes.py`
- Modify: `services/aichat-api/models/api_key.py`
- Modify: `services/aichat-api/middleware/api_key_auth.py`
- Modify: `apps/admin-web/src/api/apiKeys.ts`（KeyItem 增加 scope，可选）

- [ ] **Step 1: api_key.py 增加 scope（两个服务各改一份，内容一致）**

`models/api_key.py` 修改四处：

1. `APIKey` dataclass 末尾增加 `scope: str = "both"`；
2. `init_db()` 的 CREATE TABLE 增加 `scope TEXT NOT NULL DEFAULT 'both'` 列，并在建表后执行迁移：

```python
cols = [row[1] for row in conn.execute("PRAGMA table_info(api_keys)").fetchall()]
if "scope" not in cols:
    conn.execute("ALTER TABLE api_keys ADD COLUMN scope TEXT NOT NULL DEFAULT 'both'")
```

3. `generate_key(..., scope: str = "both")` 的 INSERT 增加 scope 列与参数，`APIKey(...)` 回填 scope；
4. `list_keys()` 的 SELECT 增加 `scope` 列。

- [ ] **Step 2: middleware 参数化 scope，但保持只校验 `/api/v1/*`（最小行为变化）**

`middleware/api_key_auth.py` 两个服务各改一份，整体替换为：

```python
"""API Key 验证 FastAPI 中间件。仅对 /api/v1/* 路径生效，按服务 scope 校验。"""
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from models.api_key import lookup_key


class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, scope: str = "doc"):
        super().__init__(app)
        self.scope = scope

    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/api/v1/"):
            api_key = request.headers.get("X-API-Key", "").strip()
            if not api_key:
                raise HTTPException(status_code=401, detail="Missing X-API-Key header")

            key_info = lookup_key(api_key)
            if not key_info:
                raise HTTPException(status_code=403, detail="Invalid or inactive API key")
            if key_info.scope not in (self.scope, "both"):
                raise HTTPException(status_code=403, detail=f"API key has no {self.scope} scope")

            request.state.api_key_info = key_info

        response = await call_next(request)
        return response
```

> 说明：与现状完全一致地只校验 `/api/v1/*`，因此 `/api/api-keys`、`/api/knowledge` 等内部接口仍免认证，前端无需注入 X-API-Key。scope 在 v1 接口上生效：docs-api 要求 `doc/both`，aichat-api 要求 `chat/both`（aichat-api 当前无 `/api/v1` 路由，中间件暂不拦截，为后续收紧预留）。

- [ ] **Step 3: 创建 key 时支持 scope**

`services/docs-api/models/v1_responses.py` 的 `CreateKeyRequest` 增加：

```python
scope: str = Field(default="both", pattern="^(doc|chat|both)$")
```

`services/docs-api/api_key_routes.py`：

- `CreateKeyResponse` 增加 `scope: str` 字段并回填；
- `KeyItem` 增加 `scope: str = "both"`；
- `create_api_key` 改为 `generate_key(req.user_name, scope=req.scope)`。

`apps/admin-web/src/api/apiKeys.ts` 的 `KeyItem` 与 create 载荷增加 `scope`（可选，建议同步，管理界面才能显示/选择权限）。

- [ ] **Step 4: 迁移现有 key 并验证**

```powershell
cd D:\AI\AnGIneer\services\docs-api
python -c "from models.api_key import init_db; init_db(); print('migrated')"
```

预期：输出 `migrated`，`data/api_keys.sqlite` 的 `api_keys` 表新增 `scope` 列且旧行默认 `both`。

- [ ] **Step 5: 提交**

```powershell
git -C D:\AI\AnGIneer add services/docs-api services/aichat-api apps/admin-web/src/api/apiKeys.ts
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

`apps/admin-web/src/api/knowledge.ts`：删除 `axios`、`getApiClientConfig`、`registerDataUnwrapInterceptor` 的 import 与 `registerDataUnwrapInterceptor(axios.create(...))` 包装，改为：

```ts
import { docsApiClient, aichatApiClient } from '../../../shared/apiClient'
const api = docsApiClient
```

**注意：`getLlmConfigs` 是 aichat 端点，不能走 `api`（docsApiClient）**，改为：

```ts
getLlmConfigs: () =>
  aichatApiClient.get('/llm_configs') as Promise<LlmConfigOption[]>,
```

（保持方法名与返回类型不变，docs-ui 的 `KnowledgeApi` 接口无需改动。）

`apps/admin-web/src/api/apiKeys.ts`：同 knowledge.ts 处理，`const api = docsApiClient`。

`apps/admin-web/src/api/evals.ts`：

```ts
const api = aichatApiClient
```

并将所有请求路径前加 `/evals`（`'/datasets'` → `'/evals/datasets'`，`'/runs'` → `'/evals/runs'`，`'/compare'` → `'/evals/compare'`，`'/folders'` → `'/evals/folders'`）。

`apps/admin-web/src/api/dreamCycle.ts`：

```ts
const api = aichatApiClient
```

并将所有请求路径前加 `/dream-cycle`（`'/reports'` → `'/dream-cycle/reports'`，`'/run'` → `'/dream-cycle/run'`，`'/tasks/...'` → `'/dream-cycle/tasks/...'`）。

`apps/admin-web/src/api/sopResearch.ts`：`RESEARCH_BASE` 改为 `'/sops/research'`，`fetch` 调用改为 `aichatApiClient` 对应方法（GET/POST/PUT/DELETE），保持函数签名与返回值不变（注意 unwrap 后不再需要 `res.json()`）。

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
Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:8791/api/llm_configs"
```

预期：artifacts 200（key 从现有 `data/api_keys.sqlite` 或任务 2.4 生成）；chat/agent 200 SSE（内部免认证，无需 key）；llm_configs 200。

另验证 docs-api 错误响应变化：不带 key 访问 `/api/v1/documents/.../artifacts` 应返回 401（FastAPI 默认形态），前端解析面板能正常显示错误。

- [ ] **Step 4: 前端联调**

启动两个 app dev server，验证：用户端文档页 PDF 渲染与解析面板（docs proxy）；AI 对话 SSE 流（aichat proxy）；admin 的 Evals / DreamCycle / SOP 管理页（aichat proxy）。

- [ ] **Step 5: 停止冒烟进程**

```powershell
Get-Job | Stop-Job; Get-Job | Remove-Job -Force
```

#### 任务 2.7：移除 `services/api-server`

**Files:**
- Delete: `services/api-server/`（git rm）
- Modify: `apps/shared/ports.json`、`apps/shared/ports.ts`（删除 apiServerPort）
- Modify: `start.ps1`（若仍有 apiServerPort 引用）
- Modify: `package.json`（删除/重命名 `api:dev`，更新 `dev:backend` 已由 2.1 处理）
- Modify: `README.md`、`services/docs-core/README.md`、`packages/docs-ui/README.md`（docs 引用同步更新）
- Modify: `docker/webhook-server.py` 的 `'api-server'` 镜像 key（或标记由任务 3.1 处理）

- [ ] **Step 1: 确认 api-server 已无代码引用**

```powershell
rg -n "api-server|apiServerPort" D:\AI\AnGIneer -g "!node_modules" -g "!**/dist/**" -g "!services/api-server/**"
```

剩余引用仅允许出现在本任务或任务 3.1 要改的文件中（README/docs/webhook/docker 除外，允许同步更新）。

- [ ] **Step 2: 删除目录与字段**

```powershell
git -C D:\AI\AnGIneer rm -r services/api-server
```

`ports.json` 删除 `apiServerPort`；`ports.ts` 删除 `API_SERVER_PORT`；`start.ps1` 删除相关行；root `package.json` 删除 `api:dev`（`dev:backend` 已在 2.1 改为并行双服务）。

- [ ] **Step 3: 重新跑任务 2.6 冒烟（回归）**

预期：docs-api / aichat-api 仍正常。

- [ ] **Step 4: 提交**

```powershell
git -C D:\AI\AnGIneer add services apps/shared start.ps1 package.json README.md
git -C D:\AI\AnGIneer commit -m "refactor(api): remove monolithic api-server after service split"
```

### 阶段 3：部署编排

#### 任务 3.1：Dockerfile / compose / nginx / 部署脚本

**Files:**
- Modify: `docker/Dockerfile.backend`
- Modify: `docker/docker-compose.yml`
- Modify: `docker/nginx/nginx.conf`
- Modify: `docker/deploy-local.ps1`、`docker/deploy-local.sh`、`docker/deploy.sh`（若引用 api-server）
- Modify: `docker/webhook-server.py`（`'api-server'` 镜像 key 更新为两个服务）

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

        location ~ ^/api/(sops|evals|dream-cycle|llm_configs) {
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

> nginx 的 `location /api/chat` 最长前缀优先于正则与 `location /api/`，SSE 不会被 buffering 干扰；`/docs`、`/redoc`、`/openapi.json` 保持指向 `api_server`（即 docs-api）。`/chat*`、`/test*` 等旧路由已不存在，无需配置。

- [ ] **Step 4: 更新部署脚本与 webhook**

`docker/deploy-local.ps1`、`docker/deploy-local.sh`、`docker/deploy.sh` 中若硬编码 `8789` 或 `api-server`，同步替换为两个新服务（8790/8791）。

`docker/webhook-server.py` 中 `'api-server': ...` 的镜像 key 改为 docs-api / aichat-api 两个镜像（或改为列表），确保自动部署能构建/拉取正确镜像。

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
2. 数据依赖（`data/knowledge_base`、`data/api_keys.sqlite`、`data/parse_records.sqlite`）；
3. 认证说明（X-API-Key + scope=doc/both，仅 `/api/v1/*` 校验）；
4. 对外产物契约（content.md / images.zip / doc_blocks_graph.jsonl / meta.json / index.sqlite / graph.sqlite）；
5. 迁移说明（`api_keys` 表 scope 列由 `init_db()` 自动补齐）；
6. 错误响应说明（无全局异常处理器，返回 FastAPI 默认 4xx/5xx）。

- [ ] **Step 2: 写 aichat-api README**

内容必须包含：

1. 启动命令（`uvicorn main:app --host 0.0.0.0 --port 8791`，工作目录 `services/aichat-api`）；
2. 数据依赖（只读 `data/knowledge_base` 与 `data/knowledge_*.sqlite`；读写 `data/sops`、`data/evals/evals.sqlite`、`data/reports/*.json`）；
3. 认证说明（X-API-Key + scope=chat/both，当前无 `/api/v1` 路由，中间件预留）；
4. SSE 事件契约（run_start / tool_start / note / answer / message_delta / run_end，AgentEvent 帧）；
5. 会话说明（AgentSession 当前为内存态，单实例，重启丢失）。

- [ ] **Step 3: 更新根 README 服务说明**

把原来的 api-server 说明替换为 docs-api / aichat-api 双服务说明与端口表，并同步 `services/docs-core/README.md`、`packages/docs-ui/README.md` 中过时的 api-server 引用。

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

重复任务 2.6 冒烟四步（health ×2、artifacts 200、chat/agent SSE、llm_configs 200）。

- [ ] **Step 3: 功能回归（关键用户路径）**

1. 上传一份 PDF → 解析完成 → 下载 content.md / images.zip / jsonl / sqlite（docs-api）；
2. 在用户端对解析后的文档发起 AI 问答，验证 SSE 回答与引用（aichat-api）；
3. 明暗主题切换下检查 AI 对话面板样式（CSS 变量由宿主提供）；
4. admin 的 API Key 管理页创建 key 时能选择 scope，v1 请求按 scope 生效。

- [ ] **Step 4: 检查工作区**

```powershell
git -C D:\AI\AnGIneer status --short
```

只允许出现本计划之外的既有用户 WIP；本次改动应全部已提交。

## 4. 风险与注意

1. **基线已干净**：内核改造 WIP 已提交；执行期间保持干净，出现计划外改动先停下确认。
2. **鉴权采用最小行为变化**：中间件仍只校验 `/api/v1/*`；scope 落库并生效于 v1。不要在本计划内把校验扩展到全部 `/api/*`（需要前端 key 注入 + `/api/api-keys` 豁免，另行立项）。
3. **docs-api 错误响应形态变化**：原全局异常处理器不迁入 docs-api，错误返回 FastAPI 默认形态；冒烟确认前端兼容，不兼容则补一个 docs-api 自己的轻量异常处理器（不改响应为 200）。
4. **legacy 路由不迁移**：`/`、`/frontend`、`/knowledge`、`/knowledge/{file_name}` 随 api-server 删除；部署环境静态资源由 nginx 提供。
5. SQLite 共享：两个容器挂同一 `../data`，WAL 已启用；禁止两个服务同时写同一 sqlite 文件（api_keys 仅 docs-api 写；knowledge 仅 docs-api 写；evals/dream-cycle 仅 aichat-api 写）。
6. **阶段 1 消费方必须按任务 1.5 全量更新**：admin 两个页面、sop-ui 五个文件、evals-ui 一个文件、apps/shared 两个文件；漏一个 `vue-tsc` 失败。
7. **依赖声明是硬前提**：`@angineer/aichat-ui: workspace:*` 必须写入四个包，并补两个 app 的 tsconfig paths。
8. **admin knowledge.ts 的 `getLlmConfigs` 必须走 aichatApiClient**，保持方法名与 docs-ui `KnowledgeApi` 接口不变。
9. 部署脚本（deploy-local.sh/ps1/deploy.sh）与 `docker/webhook-server.py` 如硬编码 8789/api-server，需同步更新（任务 3.1 Step 4）。
10. 任务 2.2 与 2.3 之间 api-server 不可启动，建议连续执行；2.1 到 2.5 之间 dev proxy 与 client 不匹配，同样连续执行。
11. 本计划完成后，`packages/aichat-ui` 即为可整体抽成 GitHub 仓库的形态（与 docs-ui 相同），届时做 subtree split 即可，不在本计划内。
12. `services/docs-core/src/popo` 是 submodule 且有本地定制，未来仓库化时按 AGENTS.md 保留环境变量版 `post_processing/model_utils.py`。
