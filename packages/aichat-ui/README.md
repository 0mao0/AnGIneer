# angineer-aichat-ui

Vue 3 AI 对话组件库（基于 ant-design-vue + KaTeX）：流式对话、引用卡片（Citation）、思维链展示，以及 `useAIChat` Composable。

## 安装

未发布到 npm registry，从 GitHub 仓库钉 tag 安装：

```jsonc
// package.json
{
  "dependencies": {
    "@angineer/aichat-ui": "github:0mao0/angineer-aichat-ui#v0.1.5"
  }
}
```

```bash
pnpm install
```

**环境要求**：peer 依赖 `vue@3.5.41`、`ant-design-vue@4.2.6`、`@ant-design/icons-vue@7.0.1`；KaTeX 作为包依赖随装。包为源码分发（无构建产物），宿主需用 Vite + `@vitejs/plugin-vue` 与 less 编译。

## 使用

```vue
<template>
  <AIChat
    title="规范问答"
    scene="docs"
    session-id="default"
    library-id="my-library"
    @send="onSend"
    @answer-complete="onAnswer"
    @select-citation="onSelectCitation"
  />
</template>

<script setup lang="ts">
import { AIChat } from '@angineer/aichat-ui'
import type { AIChatMessage, AIChatCitation } from '@angineer/aichat-ui'

function onSend(message: string, model: string) { /* 自行对接后端流式接口 */ }
function onAnswer(message: AIChatMessage) { /* ... */ }
function onSelectCitation(citation: AIChatCitation) { /* ... */ }
</script>
```

自定义对话逻辑可用 `useAIChat` Composable（暴露 `messages` / `loading` / `currentStreamContent` / `liveThinkingSteps` / `sendMessage` / `stopGeneration` / `clearMessages` / `startNewChat` 等）。

## 导出

- 组件：`AIChat`、`BaseChat`、`CitationInline`、`CitationMentionPanel`、`CitationPopover`、`CitationRichContent`、`InlineCitationEditor`
- Composable：`useAIChat`
- 子路径导出：`@angineer/aichat-ui/utils/citation`、`@angineer/aichat-ui/utils/markdown`

## 主题定制

**组件私有 token（`--chat-*`）**：使用处全部内置 fallback，不导入任何样式文件也能正常渲染（light 默认值）。导入 `@angineer/aichat-ui/style` 后获得完整 token 层——含 `[data-theme="dark"]` 下的暗色值（dark 模式必需），并可在 `:root` 覆盖同名变量定制：

| 变量 | light | dark（导入 style 后生效） | 用途 |
| --- | --- | --- | --- |
| `--chat-root-bg` | `var(--bg-primary, #ffffff)` | 自动跟随 `--bg-primary` | 聊天区背景 |
| `--chat-user-bubble-bg` / `--chat-user-bubble-text` | `#e6f4ff` / `#000000` | `#15325b` / `rgba(255,255,255,0.85)` | 用户气泡 |
| `--chat-assistant-bubble-bg` / `--chat-assistant-bubble-text` | `#f5f5f5` / `#000000` | `var(--bg-secondary, #1f1f1f)` / `var(--text-primary, …)` | 助手气泡 |
| `--chat-citation-accent` / `--chat-citation-bg` / `--chat-citation-border` | `#1677ff` / `#e6f4ff` / `#91caff` | `#177ddc` / `#111a2c` / `#15325b` | 引用卡片 |
| `--chat-code-bg` / `--chat-pre-bg` | `#f6f8fa` | `var(--bg-tertiary, rgba(255,255,255,0.04))` | 行内代码 / 代码块 |
| `--chat-streaming-bg` / `--chat-streaming-cursor` | `#fffbe6` / `#1677ff` | `rgba(250,173,20,0.1)` / `#177ddc` | 流式输出态 |
| `--chat-system-bg` / `--chat-system-border` / `--chat-system-text` | `#fafafa` / `#d9d9d9` / `#8c8c8c` | `var(--bg-secondary/--divider-color/--text-secondary, …)` | 系统消息 |
| `--chat-error-color` / `--chat-error-hover` | `#ff4d4f` / `#ff7875` | `var(--danger, #dc4446)` / `#e86e6b` | 错误态 |

**宿主语义变量契约**：组件同时引用通用语义变量（`--text-primary`、`--text-secondary`、`--border-color`、`--bg-primary`、`--bg-secondary`、`--bg-tertiary`、`--primary-color`、`--panel-header-bg`）以跟随宿主 dark/light 主题。宿主未定义时请在 `:root` 提供，例如 light 默认值：`--text-primary: rgba(0,0,0,0.85)`、`--text-secondary: rgba(0,0,0,0.65)`、`--border-color: rgba(0,0,0,0.06)`、`--bg-primary: #ffffff`、`--bg-secondary: #fafafa`、`--bg-tertiary: rgba(0,0,0,0.02)`、`--primary-color: #1890ff`、`--panel-header-bg: #fafafa`（dark 模式在 `[data-theme="dark"]` 下覆盖同名变量即可）。

## 测试

```bash
pnpm --filter @angineer/aichat-ui test       # 31 个单元测试（tsx + node:test）
pnpm --filter @angineer/aichat-ui typecheck  # vue-tsc
```

## 仓库说明

本仓库为独立发布仓，代码唯一真相源在 [AnGIneer](https://github.com/0mao0/AnGIneer) monorepo 的 `packages/aichat-ui`，经 `scripts/sync-standalone.ps1` 同步；版本以 git tag 发布。变更历史见 [CHANGELOG.md](./CHANGELOG.md)。
