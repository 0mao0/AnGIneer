# AIChat 统一到 ui-kit 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 KnowledgeChatPanel 和 SOPChatPanel 合并为统一的 AIChat 组件，迁移到 ui-kit，消除 docs-ui 中的冗余 Chat 组件。

**Architecture:** 在 ui-kit 中新建 AIChat.vue（封装 BaseChat + useAIChat），useAIChat composable 从 useKnowledgeChat 通用化迁移而来。Markdown 渲染作为 AIChat 内置能力。docs-ui 中删除 KnowledgeChatPanel/SOPChatPanel/useSopChat，useKnowledgeChat 标记 deprecated。消费方（web-console、admin-console）改用 AIChat。

**Tech Stack:** Vue 3, TypeScript, katex（需添加到 ui-kit 依赖）

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `packages/ui-kit/src/composables/useAIChat.ts` | 统一 AI 对话 composable，会话池+消息管理+/api/query 调用 |
| Create | `packages/ui-kit/src/components/common/AIChat.vue` | 统一 AI 对话组件，封装 BaseChat + useAIChat + Markdown 渲染 |
| Create | `packages/ui-kit/src/utils/markdown.ts` | Markdown 渲染工具（从 docs-ui 迁移 renderMarkdownToHtml） |
| Modify | `packages/ui-kit/package.json` | 添加 katex 依赖 |
| Modify | `packages/ui-kit/src/composables/index.ts` | 导出 useAIChat |
| Modify | `packages/ui-kit/src/components/index.ts` | 导出 AIChat |
| Modify | `packages/ui-kit/src/types/chat.ts` | 添加 AIChat 相关类型 |
| Modify | `apps/web-console/src/App.vue` | 改用 AIChat 替代 KnowledgeChatPanel/SOPChatPanel |
| Modify | `apps/admin-console/src/views/KnowledgeManage.vue` | 改用 AIChat 替代 KnowledgeChatPanel |
| Modify | `packages/docs-ui/src/components/index.ts` | 移除 KnowledgeChatPanel/SOPChatPanel 导出 |
| Modify | `packages/docs-ui/src/composables/useKnowledgeChat.ts` | 添加 deprecated 注释，指向 useAIChat |
| Delete | `packages/docs-ui/src/components/common/widgets/KnowledgeChatPanel.vue` | 冗余，由 AIChat 替代 |
| Delete | `packages/docs-ui/src/components/common/widgets/SOPChatPanel.vue` | 冗余，由 AIChat 替代 |
| Delete | `packages/docs-ui/src/composables/useSopChat.ts` | 冗余，由 useAIChat 替代 |
| Modify | `services/docs-core/src/docs_core/evals/eval_retrieval.py` | 迁移到 /api/query |
| Modify | `services/docs-core/src/docs_core/evals/eval_answer.py` | 迁移到 /api/query |
| Modify | `services/docs-core/src/docs_core/evals/eval_text2sql.py` | 迁移到 /api/query |
| Modify | `apps/api-server/knowledge_routes.py` | 标记旧 /query 路由 deprecated |

---

### Task 1: 添加 katex 依赖到 ui-kit

**Files:**
- Modify: `packages/ui-kit/package.json`

- [ ] **Step 1: 在 ui-kit 的 dependencies 中添加 katex**

在 `packages/ui-kit/package.json` 中，将 katex 从 devDependencies 移到 dependencies（或添加）：

```json
"dependencies": {
  "katex": "^0.16.37"
}
```

- [ ] **Step 2: 运行 pnpm install**

Run: `pnpm install`
Expected: 安装成功，无错误

- [ ] **Step 3: Commit**

```bash
git add packages/ui-kit/package.json pnpm-lock.yaml
git commit -m "chore: add katex dependency to ui-kit"
```

---

### Task 2: 迁移 Markdown 渲染到 ui-kit

**Files:**
- Create: `packages/ui-kit/src/utils/markdown.ts`

从 `packages/docs-ui/src/utils/knowledge.ts` 中提取 `renderMarkdownToHtml` 和 `renderMarkdownInlineToHtml` 函数及其依赖的内部函数（`renderInline`, 表格/代码/数学块解析等）。

- [ ] **Step 1: 创建 markdown.ts**

将 `docs-ui/utils/knowledge.ts` 中第 138-524 行的 Markdown 渲染逻辑复制到 `packages/ui-kit/src/utils/markdown.ts`，移除对 `SmartTreeNode`、`StructuredIndexItem`、`DocBlockNode` 类型的依赖，只保留纯 Markdown → HTML 转换函数。

关键导出：
```typescript
export function renderMarkdownToHtml(content: string, sourceFilePath?: string): string
export function renderMarkdownInlineToHtml(content: string, sourceFilePath?: string): string
export function renderMarkdown(content: string): string
```

- [ ] **Step 2: 验证编译通过**

Run: `pnpm run lint`
Expected: 无错误

- [ ] **Step 3: Commit**

```bash
git add packages/ui-kit/src/utils/markdown.ts
git commit -m "feat(ui-kit): add markdown rendering utilities"
```

---

### Task 3: 添加 AIChat 类型定义

**Files:**
- Modify: `packages/ui-kit/src/types/chat.ts`

- [ ] **Step 1: 在 chat.ts 中添加 AIChat 相关类型**

在现有类型之后添加：

```typescript
export interface AIChatCitation {
  target_id: string
  target_type?: string
  doc_id: string
  doc_title: string
  page_idx: number
  section_path: string
  snippet: string
  content?: string
  content_type?: string
  score: number
  rich_media?: CitationRichMedia
}

export interface AIChatMessage {
  id?: string
  role: BaseChatMessageRole
  content: string
  timestamp?: number
  queryChain?: string
  images?: string[]
  citations?: AIChatCitation[]
  strategy?: string
  task_type?: string
  confidence?: number
  debug?: Record<string, any>
}

export interface QueryRequest {
  query: string
  scene?: string
  session_id?: string
  library_id?: string
  doc_ids?: string[]
  config?: string
  mode?: string
}

export interface QueryResponse {
  query_id: string
  session_key?: string
  intent: {
    intent_level: string
    intent_type: string
    parameters: Record<string, any>
    required_capabilities: string[]
    matched_sop: string | null
    service_mode: string
    reason: string | null
  }
  answer: string
  citations?: AIChatCitation[]
  retrieved_items?: Array<{
    item_id: string
    entity_type: string
    doc_id: string
    title: string
    text: string
    score: number
    metadata?: Record<string, any>
  }>
  sql?: {
    generated_sql: string
    execution_status: string
    result_preview: any
    explanation: string
  }
  fallback_used?: boolean
  latency_ms?: number
}
```

- [ ] **Step 2: Commit**

```bash
git add packages/ui-kit/src/types/chat.ts
git commit -m "feat(ui-kit): add AIChat type definitions"
```

---

### Task 4: 创建 useAIChat composable

**Files:**
- Create: `packages/ui-kit/src/composables/useAIChat.ts`
- Modify: `packages/ui-kit/src/composables/index.ts`

从 `packages/docs-ui/src/composables/useKnowledgeChat.ts` 迁移核心逻辑，通用化命名。

- [ ] **Step 1: 创建 useAIChat.ts**

将 `useKnowledgeChat.ts` 的全部逻辑复制到 `packages/ui-kit/src/composables/useAIChat.ts`，做以下调整：

1. 类型名通用化：`KnowledgeChatMessage` → `AIChatMessage`，`KnowledgeChatCitation` → `AIChatCitation`
2. 从 `../types/chat` 导入类型，不再从 `../utils/common` 导入 `generateMessageId`/`estimateTokens`（内联这两个简单函数）
3. 保留会话池逻辑（`sessionPool`、`buildSessionKey`、`switchSession`）
4. 保留 `/api/query` 调用逻辑
5. 保留 `mapQueryResponseToChatResponse`、`buildQueryChain`、`formatTaskType` 等辅助函数
6. `scene` 和 `sessionId` 支持响应式（`Ref<string>`）

关键签名：
```typescript
export function useAIChat(options?: {
  defaultModel?: string
  contextConfig?: Partial<AIChatContextConfig>
  systemPrompt?: string
  libraryId?: string
  scene?: string
  sessionId?: string | Ref<string>
  getContextItems?: () => Array<{ id: string; title: string }>
}): {
  messages: Ref<AIChatMessage[]>
  inputText: Ref<string>
  loading: Ref<boolean>
  currentStreamContent: Ref<string>
  currentSessionKey: Ref<SessionKey>
  contextTokens: ComputedRef<number>
  contextRounds: ComputedRef<number>
  sendMessage: (content: string, model?: string, onChunk?: (chunk: string) => void, sendOptions?: { includeDebug?: boolean; includeRetrieved?: boolean }) => Promise<void>
  stopGeneration: () => void
  clearMessages: () => void
  switchSession: (newScene: string, newId: string) => void
  removeCurrentSession: () => void
}
```

- [ ] **Step 2: 更新 composables/index.ts 导出**

```typescript
export { useTheme } from './useTheme'
export { useLayout } from './useLayout'
export { useAIChat } from './useAIChat'
export type { AIChatMessage, AIChatCitation, QueryRequest, QueryResponse } from '../types/chat'
```

- [ ] **Step 3: 验证编译通过**

Run: `pnpm run lint`
Expected: 无错误

- [ ] **Step 4: Commit**

```bash
git add packages/ui-kit/src/composables/useAIChat.ts packages/ui-kit/src/composables/index.ts
git commit -m "feat(ui-kit): add useAIChat composable"
```

---

### Task 5: 创建 AIChat.vue 组件

**Files:**
- Create: `packages/ui-kit/src/components/common/AIChat.vue`
- Modify: `packages/ui-kit/src/components/index.ts`

- [ ] **Step 1: 创建 AIChat.vue**

组件结构：封装 BaseChat + useAIChat + 模型获取 + Markdown 渲染。

```vue
<template>
  <BaseChat
    ref="baseChatRef"
    :messages="messages"
    :loading="loading"
    :current-stream-content="currentStreamContent"
    :models="models"
    :loading-models="loadingModels"
    :default-model="defaultModel"
    :placeholder="placeholder"
    :context-items="contextItems"
    :title="title"
    :icon="icon"
    :show-context-info="showContextInfo"
    :show-system-messages="showSystemMessages"
    :context-tokens="contextTokens"
    :context-rounds="contextRounds"
    :render-message="renderAIChatMessage"
    @send="handleSend"
    @clear="clearMessages"
    @stop="stopGeneration"
    @remove-context="handleRemoveContext"
    @ready="handleReady"
    @select-citation="handleSelectCitation"
  />
</template>

<script setup lang="ts">
/**
 * 统一 AI 对话组件。
 * 封装 BaseChat + useAIChat + 模型获取 + Markdown 渲染。
 * 通过 scene + sessionId 区分不同场景，后端自动路由。
 */
import { onMounted, ref, computed } from 'vue'
import { BaseChat } from './BaseChat.vue'
import { useAIChat } from '../../composables/useAIChat'
import { renderMarkdownToHtml } from '../../utils/markdown'
import type { AIChatMessage, AIChatCitation, BaseChatContextItem } from '../../types'

interface Props {
  defaultModel?: string
  placeholder?: string
  contextItems?: BaseChatContextItem[]
  title?: string
  icon?: any
  systemPrompt?: string
  showContextInfo?: boolean
  showSystemMessages?: boolean
  scene?: string
  sessionId?: string
  libraryId?: string
}

const props = withDefaults(defineProps<Props>(), {
  defaultModel: '',
  placeholder: '输入消息，Enter 发送...',
  contextItems: () => [],
  title: 'AI 助手',
  icon: undefined,
  systemPrompt: '',
  showContextInfo: true,
  showSystemMessages: false,
  scene: 'docs',
  sessionId: 'default',
  libraryId: 'default'
})

interface ModelOption { value: string; label: string }

const emit = defineEmits<{
  send: [message: string, model: string]
  ready: []
  removeContext: [id: string]
  error: [error: Error]
  answerComplete: [message: AIChatMessage]
  selectCitation: [citation: AIChatCitation]
}>()

const sessionIdRef = computed(() => props.sessionId)

const {
  messages,
  loading,
  currentStreamContent,
  contextTokens,
  contextRounds,
  sendMessage,
  stopGeneration,
  clearMessages,
} = useAIChat({
  defaultModel: props.defaultModel,
  systemPrompt: props.systemPrompt,
  libraryId: props.libraryId,
  scene: props.scene,
  sessionId: sessionIdRef,
  getContextItems: () => props.contextItems
})

const loadingModels = ref(false)
const models = ref<ModelOption[]>([])
const baseChatRef = ref<InstanceType<typeof BaseChat> | null>(null)

const renderAIChatMessage = (content: string) => renderMarkdownToHtml(content, '')

const fetchModels = async () => {
  loadingModels.value = true
  try {
    const response = await fetch('/api/llm_configs')
    if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`)
    const data = await response.json()
    models.value = data
      .filter((model: any) => model.configured)
      .map((model: any) => ({ value: model.name, label: model.name }))
  } catch (error) {
    console.error('获取模型列表失败:', error)
    models.value = [{ value: 'default', label: '默认模型' }]
  } finally {
    loadingModels.value = false
  }
}

const handleSend = async (message: string, model: string) => {
  emit('send', message, model)
  baseChatRef.value?.clearComposer?.()
  try {
    await sendMessage(message, model)
    const lastAssistantMessage = [...messages.value]
      .reverse()
      .find(item => item.role === 'assistant')
    if (lastAssistantMessage) {
      emit('answerComplete', lastAssistantMessage)
    }
  } catch (error) {
    emit('error', error instanceof Error ? error : new Error(String(error)))
  } finally {
    baseChatRef.value?.clearComposer?.()
  }
}

const handleRemoveContext = (id: string) => { emit('removeContext', id) }
const handleReady = () => { emit('ready') }
const handleSelectCitation = (citation: AIChatCitation) => { emit('selectCitation', citation) }

onMounted(() => { fetchModels() })

defineExpose({
  messages,
  clearMessages,
  sendMessage,
  handleSend,
  clearComposer: () => baseChatRef.value?.clearComposer?.()
})
</script>
```

- [ ] **Step 2: 更新 components/index.ts 导出**

在 `packages/ui-kit/src/components/index.ts` 末尾添加：

```typescript
export { default as AIChat } from './common/AIChat.vue'
```

- [ ] **Step 3: 验证编译通过**

Run: `pnpm run lint`
Expected: 无错误

- [ ] **Step 4: Commit**

```bash
git add packages/ui-kit/src/components/common/AIChat.vue packages/ui-kit/src/components/index.ts
git commit -m "feat(ui-kit): add AIChat component"
```

---

### Task 6: 更新 web-console 消费方

**Files:**
- Modify: `apps/web-console/src/App.vue`

- [ ] **Step 1: 替换导入和使用**

将 `KnowledgeChatPanel` 和 `SOPChatPanel` 替换为 `AIChat`：

```vue
<template>
  <!-- ... 其他不变 ... -->
  <template #right>
    <Panel :title="chatPanelTitle" :icon="MessageOutlined">
      <AIChat
        title=""
        :placeholder="chatPanelPlaceholder"
        :show-context-info="true"
        :scene="activeSection === 'sop' ? 'sops' : 'docs'"
        :session-id="chatSessionId"
      />
    </Panel>
  </template>
</template>

<script setup lang="ts">
// 移除: import { KnowledgeChatPanel, SOPChatPanel } from '@angineer/docs-ui'
// 添加:
import { AIChat } from '@angineer/ui-kit'
// ... 其他不变，移除 currentChatPanel computed ...
</script>
```

- [ ] **Step 2: 验证编译通过**

Run: `pnpm run lint`
Expected: 无错误

- [ ] **Step 3: Commit**

```bash
git add apps/web-console/src/App.vue
git commit -m "refactor(web-console): use AIChat instead of KnowledgeChatPanel/SOPChatPanel"
```

---

### Task 7: 更新 admin-console 消费方

**Files:**
- Modify: `apps/admin-console/src/views/KnowledgeManage.vue`

- [ ] **Step 1: 替换导入和使用**

将 `KnowledgeChatPanel` 替换为 `AIChat`：

```vue
<AIChat
  ref="knowledgeChatRef"
  title=""
  placeholder="输入消息，Ctrl+Enter 发送..."
  :show-context-info="true"
  scene="knowledge"
  :session-id="selectedNode && !selectedNode.isFolder ? selectedNode.key : 'default'"
  @answer-complete="handleKnowledgeAnswerComplete"
  @select-citation="handleKnowledgeCitationSelect"
/>
```

更新导入：
```typescript
// 移除: import { KnowledgeChatPanel } from '@angineer/docs-ui'
// 添加:
import { AIChat } from '@angineer/ui-kit'
```

更新 ref 类型：
```typescript
const knowledgeChatRef = ref<InstanceType<typeof AIChat> | null>(null)
```

- [ ] **Step 2: 验证编译通过**

Run: `pnpm run lint`
Expected: 无错误

- [ ] **Step 3: Commit**

```bash
git add apps/admin-console/src/views/KnowledgeManage.vue
git commit -m "refactor(admin-console): use AIChat instead of KnowledgeChatPanel"
```

---

### Task 8: 清理 docs-ui 冗余组件

**Files:**
- Delete: `packages/docs-ui/src/components/common/widgets/KnowledgeChatPanel.vue`
- Delete: `packages/docs-ui/src/components/common/widgets/SOPChatPanel.vue`
- Delete: `packages/docs-ui/src/composables/useSopChat.ts`
- Modify: `packages/docs-ui/src/components/index.ts` — 移除导出
- Modify: `packages/docs-ui/src/composables/useKnowledgeChat.ts` — 添加 deprecated 标记

- [ ] **Step 1: 删除冗余文件**

删除 `KnowledgeChatPanel.vue`、`SOPChatPanel.vue`、`useSopChat.ts`

- [ ] **Step 2: 更新 docs-ui/components/index.ts**

移除 KnowledgeChatPanel 和 SOPChatPanel 的导出行。

- [ ] **Step 3: 在 useKnowledgeChat.ts 顶部添加 deprecated 标记**

在文件顶部注释中添加：
```
/**
 * @deprecated 请使用 @angineer/ui-kit 的 useAIChat 替代。
 * 本模块将在后续版本中移除。
 */
```

- [ ] **Step 4: 验证编译通过**

Run: `pnpm run lint`
Expected: 无错误

- [ ] **Step 5: Commit**

```bash
git add -A packages/docs-ui/
git commit -m "refactor(docs-ui): remove redundant KnowledgeChatPanel/SOPChatPanel/useSopChat, deprecate useKnowledgeChat"
```

---

### Task 9: 迁移 eval 脚本到 /api/query

**Files:**
- Modify: `services/docs-core/src/docs_core/evals/eval_retrieval.py`
- Modify: `services/docs-core/src/docs_core/evals/eval_answer.py`
- Modify: `services/docs-core/src/docs_core/evals/eval_text2sql.py`

- [ ] **Step 1: 创建统一的 eval 查询辅助函数**

在 `services/docs-core/src/docs_core/evals/` 下新建 `query_helper.py`：

```python
"""评测查询辅助，统一走 /api/query 端点。"""
import json
import urllib.request
from typing import Any, Dict, Optional


def call_query_api(
    query: str,
    library_id: str = "default",
    doc_ids: Optional[list] = None,
    scene: str = "docs",
    session_id: str = "eval",
) -> Dict[str, Any]:
    """调用 /api/query 端点获取查询结果。"""
    payload = {
        "query": query,
        "scene": scene,
        "session_id": session_id,
        "library_id": library_id,
    }
    if doc_ids:
        payload["doc_ids"] = doc_ids
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        "http://localhost:8789/api/query",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))
```

- [ ] **Step 2: 更新 eval_retrieval.py**

将 `knowledge_query_service.query(request)` 替换为 `call_query_api()`，适配返回结构。

- [ ] **Step 3: 更新 eval_answer.py**

同上。

- [ ] **Step 4: 更新 eval_text2sql.py**

同上。

- [ ] **Step 5: Commit**

```bash
git add services/docs-core/src/docs_core/evals/
git commit -m "refactor(evals): migrate eval scripts from knowledge_query_service to /api/query"
```

---

### Task 10: 标记旧路由 deprecated

**Files:**
- Modify: `apps/api-server/knowledge_routes.py`

- [ ] **Step 1: 在 /query 和 /retrieve 路由上添加 deprecated 标记**

```python
@knowledge_router.post("/query", response_model=KnowledgeQueryResponse, deprecated=True)
async def query_knowledge(request: KnowledgeQueryRequest) -> KnowledgeQueryResponse:
    """已废弃：请使用 /api/query 端点。本路由将在后续版本中移除。"""
    ...

@knowledge_router.post("/retrieve", deprecated=True)
async def retrieve_knowledge(request: KnowledgeRetrieveRequest) -> Dict[str, Any]:
    """已废弃：请使用 /api/query 端点。本路由将在后续版本中移除。"""
    ...
```

- [ ] **Step 2: Commit**

```bash
git add apps/api-server/knowledge_routes.py
git commit -m "deprecate(knowledge_routes): mark /query and /retrieve as deprecated"
```

---

### Task 11: 最终验证

- [ ] **Step 1: 运行 lint**

Run: `pnpm run lint`
Expected: 全部通过

- [ ] **Step 2: 启动前端验证**

Run: `pnpm dev:frontend`
Expected: 页面正常加载，右侧 AI 对话面板正常显示

- [ ] **Step 3: 启动后端验证**

Run: `pnpm dev:backend`
Expected: 后端正常启动，/api/query 端点可用

- [ ] **Step 4: 端到端测试**

1. 在知识库页面选择文档，输入问题，验证对话正常
2. 切换文档，验证对话隔离
3. 在 web-console 切换知识/经验标签，验证 scene 切换正常
