# 用户端 AI 对话停靠列 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把用户端 AI 对话从整页高度的抽屉浮层改为停靠在内容区右侧、与 PDF/当前页签内容同高的固定列。

**Architecture:** Workbench 新增可选 `#right` 插槽与 `showRightPanel` prop，内容区变为“主视图 + 右侧列”的横向布局；App.vue 删除抽屉，把 AIChat 放入插槽，保留所有会话逻辑，并用右下角按钮控制右侧列显隐。

**Tech Stack:** Vue 3.4 + TypeScript + Less + ant-design-vue 4；pnpm workspace。

---

## 文件总览

| 文件 | 职责 | 动作 |
| --- | --- | --- |
| `apps/user-web/src/layouts/Workbench.vue` | 内容区横向布局、右侧列插槽 | 修改 |
| `apps/user-web/src/App.vue` | 移除抽屉，接入停靠列 | 修改 |

所有提交直接落在 `main`。工作区有用户未提交的改动，提交时只 `git add` 本任务涉及的文件。

---

### Task 1: Workbench 支持右侧停靠列

**Files:**
- Modify: `apps/user-web/src/layouts/Workbench.vue`

- [ ] **Step 1: 模板增加主视图容器与右侧插槽**

把：

```html
    <div class="content-area">
      <EmptyState
        v-if="tabs.length === 0"
        title="开始工作"
        description="从左侧选择文档或 SOP，或点击下方按钮快速导航"
      >
        <template #action>
          <a-space>
            <a-button type="primary" @click="$emit('navigate-section', 'knowledge')">打开知识库</a-button>
            <a-button @click="$emit('navigate-section', 'sop')">查看 SOP</a-button>
          </a-space>
        </template>
      </EmptyState>
      <TabErrorBoundary
        v-else
        :tab-key="currentTab?.key"
        @close="closeTabFromError"
      >
        <component :is="currentViewer" v-bind="currentTab?.props" />
      </TabErrorBoundary>
    </div>
```

替换为：

```html
    <div class="content-area">
      <div class="content-main">
        <EmptyState
          v-if="tabs.length === 0"
          title="开始工作"
          description="从左侧选择文档或 SOP，或点击下方按钮快速导航"
        >
          <template #action>
            <a-space>
              <a-button type="primary" @click="$emit('navigate-section', 'knowledge')">打开知识库</a-button>
              <a-button @click="$emit('navigate-section', 'sop')">查看 SOP</a-button>
            </a-space>
          </template>
        </EmptyState>
        <TabErrorBoundary
          v-else
          :tab-key="currentTab?.key"
          @close="closeTabFromError"
        >
          <component :is="currentViewer" v-bind="currentTab?.props" />
        </TabErrorBoundary>
      </div>
      <div v-show="showRightPanel && $slots.right" class="content-right">
        <slot name="right" />
      </div>
    </div>
```

- [ ] **Step 2: 新增 showRightPanel prop**

在 `<script setup lang="ts">` 的 import 块之后插入：

```ts
const props = withDefaults(defineProps<{
  showRightPanel?: boolean
}>(), {
  showRightPanel: false
})
```

- [ ] **Step 3: 更新内容区样式**

把：

```less
.content-area {
  flex: 1;
  overflow: hidden;
  background: var(--bg-primary);
  transition: background-color 0.3s;
}
```

替换为：

```less
.content-area {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: row;
  align-items: stretch;
  background: var(--bg-primary);
  transition: background-color 0.3s;
}

.content-main {
  flex: 1;
  min-width: 0;
  overflow: hidden;
}

.content-right {
  flex: 0 0 auto;
  width: 440px;
  border-left: 1px solid var(--border-color);
  background: var(--panel-bg);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
```

- [ ] **Step 4: 验证类型检查**

Run: `pnpm --filter @angineer/user-web exec vue-tsc -b --pretty false`

Expected: 退出码 0。

- [ ] **Step 5: 提交**

Run:

```bash
git add apps/user-web/src/layouts/Workbench.vue
git commit -m "feat(user-web): support docked right column in workbench"
```

Expected: 提交成功。

---

### Task 2: App.vue 用停靠列替换抽屉

**Files:**
- Modify: `apps/user-web/src/App.vue`

- [ ] **Step 1: 补充图标 import**

把：

```ts
import { MessageOutlined, PlusOutlined } from '@ant-design/icons-vue'
```

替换为：

```ts
import { MessageOutlined, PlusOutlined, CloseOutlined } from '@ant-design/icons-vue'
```

- [ ] **Step 2: Workbench 传入开关并放入 AI 对话插槽**

把：

```html
          <template #center>
            <Workbench @navigate-section="onNavigateSection" />
          </template>
```

替换为：

```html
          <template #center>
            <Workbench
              :show-right-panel="aiChatVisible"
              @navigate-section="onNavigateSection"
            >
              <template #right>
                <div class="ai-chat-dock">
                  <div class="ai-chat-dock-header">
                    <span class="ai-chat-dock-title">AI 对话</span>
                    <a-button
                      type="text"
                      size="small"
                      title="新建对话"
                      aria-label="新建对话"
                      @click="onNewChat"
                    >
                      <template #icon><PlusOutlined /></template>
                    </a-button>
                    <a-button
                      type="text"
                      size="small"
                      title="关闭"
                      aria-label="关闭"
                      @click="aiChatVisible = false"
                    >
                      <template #icon><CloseOutlined /></template>
                    </a-button>
                  </div>
                  <div class="ai-chat-panel-body">
                    <AIChat
                      ref="aiChatRef"
                      title=""
                      :placeholder="chatPanelPlaceholder"
                      :show-context-info="true"
                      :scene="activeSection === 'sop' ? 'sops' : 'docs'"
                      :session-id="chatSessionId"
                      :transport="defaultAIChatTransport"
                      @select-citation="handleCitationSelect"
                    />
                  </div>
                </div>
              </template>
            </Workbench>
          </template>
```

- [ ] **Step 3: 删除整页抽屉**

删除模板中整个 `<a-drawer ...> ... </a-drawer>` 块（从 `<a-drawer` 到 `</a-drawer>`，包含 `#extra` 与 `ai-chat-panel-body` 内容）。

- [ ] **Step 4: 悬浮按钮打开时隐藏**

把：

```html
        <a-button
          class="ai-chat-fab"
```

替换为：

```html
        <a-button
          v-if="!aiChatVisible"
          class="ai-chat-fab"
```

- [ ] **Step 5: 更新样式**

删除：

```less
.ai-chat-drawer .ant-drawer-content,
.ai-chat-drawer .ant-drawer-wrapper-body,
.ai-chat-drawer .ant-drawer-body {
  overflow: hidden;
}
```

在 `.ai-chat-panel-body` 规则之前插入：

```less
.ai-chat-dock {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.ai-chat-dock-header {
  display: flex;
  align-items: center;
  gap: 4px;
  height: 40px;
  min-height: 40px;
  padding: 0 8px;
  border-bottom: 1px solid var(--border-color);
}

.ai-chat-dock-title {
  flex: 1;
  min-width: 0;
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
```

- [ ] **Step 6: 验证构建**

Run: `pnpm --filter @angineer/user-web build`

Expected: 退出码 0，vue-tsc 与 vite 均通过。

- [ ] **Step 7: 提交**

Run:

```bash
git add apps/user-web/src/App.vue
git commit -m "feat(user-web): dock AI chat beside content area"
```

Expected: 提交成功。

---

### Task 3: 全量验证与手工回归

**Files:** 无

- [ ] **Step 1: 运行用户端构建**

Run: `pnpm --filter @angineer/user-web build`

Expected: 退出码 0。

- [ ] **Step 2: 手工回归**

启动 `pnpm dev:frontend`，验证：

- 文档页点击右下角悬浮按钮后，右侧出现 AI 对话列，与 PDF 同高，按钮隐藏；
- 点击对话列头部“关闭”后，列消失、按钮重新出现，再次打开对话内容不丢失；
- 切换到 SOP / GIS / 项目页签，右侧列保持显示且与内容区同高；
- 无打开页签时，右侧列仍可正常显示和使用；
- “新建对话”与引用跳转功能正常。

- [ ] **Step 3: 若发现问题，修复后按 Task 规则单独提交**

禁止 `git add -A`。
