# angineer-aichat-ui

Vue 3 AI 对话组件库（基于 ant-design-vue + KaTeX）：流式对话、引用卡片、思考步骤等组件，以及 `useAIChat` Composable。

## 安装

```bash
pnpm add github:0mao0/angineer-aichat-ui
```

宿主项目需提供 peer 依赖：`vue@3.5`、`ant-design-vue@4`、`@ant-design/icons-vue@7`。

## 使用

```ts
import { AIChat, useAIChat } from '@angineer/aichat-ui'
import '@angineer/aichat-ui/style'
```

## 测试

```bash
pnpm dlx tsx --test test/citation.test.ts test/thinking.test.ts test/token.test.ts test/useAIChat.test.ts
```

## 导出

- 组件：`AIChat`、`BaseChat`、`Citation*`、`ThinkingSteps` 等
- Composable：`useAIChat`
- 子路径：`@angineer/aichat-ui/utils/citation`、`@angineer/aichat-ui/utils/markdown`
