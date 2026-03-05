# AnGIneer 技术实现细节

本文档包含项目的详细技术实现、API 规范、组件使用示例。

---

## 目录

- [AIChat 对话系统](#aichat-对话系统)
- [SmartTree 知识树系统](#smarttree-知识树系统)
- [API 端点速查](#api-端点速查)
- [数据模型](#数据模型)

---

## AIChat 对话系统

### 组件架构

```
┌─────────────────────────────────────────────────────────────┐
│                    AIChat.vue (UI 组件)                      │
├─────────────────────────────────────────────────────────────┤
│  消息列表区 (MessageList)                                    │
│  输入框区 (InputArea)                                        │
│    ├── 图片上传按钮                                          │
│    ├── 模型选择下拉框 (自适应宽度)                           │
│    └── 发送/停止按钮                                         │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                  useAIChat.ts (业务逻辑)                     │
├─────────────────────────────────────────────────────────────┤
│  - 消息状态管理                                              │
│  - 流式请求处理                                              │
│  - 上下文压缩                                                │
│  - Token 估算                                                │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    chat.ts (Pinia Store)                     │
├─────────────────────────────────────────────────────────────┤
│  - 全局对话状态                                              │
│  - 跨组件消息共享                                            │
└─────────────────────────────────────────────────────────────┘
```

### AIChat.vue Props

| Prop | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `defaultModel` | `string` | - | 默认模型 |
| `placeholder` | `string` | `'输入消息...'` | 输入框占位符 |
| `contextItems` | `ContextItem[]` | `[]` | 上下文引用项 |
| `title` | `string` | `'AI 助手'` | 标题 |
| `icon` | `string` | - | 图标 |
| `systemPrompt` | `string` | - | 系统提示词 |
| `showContextInfo` | `boolean` | `false` | 是否显示上下文信息 |
| `showSystemMessages` | `boolean` | `false` | 是否显示系统消息 |

### AIChat.vue Events

| Event | 参数 | 说明 |
|-------|------|------|
| `send` | `(message: string, model: string)` | 发送消息时触发 |
| `ready` | `()` | 组件就绪时触发 |

### AIChat.vue Slots

| Slot | 参数 | 说明 |
|------|------|------|
| `header` | - | 自定义头部 |
| `empty` | - | 空状态自定义内容 |

### 使用示例

```vue
<template>
  <AIChat
    ref="aiChatRef"
    title="AI 助手"
    placeholder="输入消息..."
    :show-context-info="true"
    @send="handleSend"
    @ready="handleReady"
  />
</template>

<script setup>
import { AIChat } from '@angineer/docs-ui'
import { useChatStore } from '@/stores/chat'

const chatStore = useChatStore()

const handleSend = async (message, model) => {
  await chatStore.sendMessage(message)
}
</script>
```

### 输入框底部布局说明

底部操作栏采用三栏布局：

```css
.input-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.left-actions {   /* 上传按钮 - 固定 */
  flex-shrink: 0;
}

.center-actions { /* 模型选择 - 自适应 */
  flex: 1;
  max-width: 180px;
}

.right-actions {  /* 发送按钮 - 固定 */
  flex-shrink: 0;
}
```

---

## SmartTree 知识树系统

### 组件架构

```
┌─────────────────────────────────────────────────────────────┐
│                   SmartTree.vue (通用组件)                   │
├─────────────────────────────────────────────────────────────┤
│  搜索栏 (可选)                                               │
│    └── 输入框 + 新增文件夹按钮                               │
│  树内容区                                                    │
│    ├── 树节点                                                │
│    │   ├── 展开/收起图标                                     │
│    │   ├── 节点图标 (slot: icon)                             │
│    │   ├── 节点标题 (slot: title)                            │
│    │   ├── 状态标签 (slot: status)                           │
│    │   └── 操作按钮 (slot: actions)                          │
│    └── 空状态                                                │
│        └── 新增文件夹按钮                                    │
└─────────────────────────────────────────────────────────────┘
```

### Props

| Prop | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `treeData` | `SmartTreeNode[]` | `[]` | 树数据 |
| `showSearch` | `boolean` | `true` | 是否显示搜索框 |
| `searchPlaceholder` | `string` | `'搜索...'` | 搜索框占位符 |
| `showStatus` | `boolean` | `false` | 是否显示状态标签 |
| `draggable` | `boolean` | `false` | 是否可拖拽 |
| `allowAddFile` | `boolean` | `false` | 是否允许添加文件 |
| `showIcon` | `boolean` | `true` | 是否显示图标 |
| `emptyText` | `string` | `'暂无数据'` | 空状态文本 |
| `loading` | `boolean` | `false` | 加载状态 |

### Events

| Event | 参数 | 说明 |
|-------|------|------|
| `select` | `(keys: string[], nodes: SmartTreeNode[])` | 选中节点 |
| `add-folder` | `(node: SmartTreeNode \| null)` | 添加文件夹，null 表示根目录 |
| `add-file` | `(node: SmartTreeNode)` | 添加文件 |
| `delete` | `(node: SmartTreeNode)` | 删除节点 |
| `rename` | `(node: SmartTreeNode)` | 重命名节点 |
| `view` | `(node: SmartTreeNode)` | 查看节点 |
| `drop` | `(info: DropInfo)` | 拖拽完成 |
| `search` | `(value: string)` | 搜索 |

### Slots

| Slot | 参数 | 说明 |
|------|------|------|
| `icon` | `{ node: SmartTreeNode }` | 自定义图标 |
| `title` | `{ node: SmartTreeNode, title: string }` | 自定义标题 |
| `status` | `{ node: SmartTreeNode }` | 自定义状态标签 |
| `actions` | `{ node: SmartTreeNode }` | 自定义操作按钮 |
| `empty` | - | 自定义空状态 |

### 使用示例

#### 前台只读模式

```vue
<template>
  <SmartTree
    :tree-data="treeData"
    :show-search="false"
    :show-status="false"
    :draggable="false"
    :allow-add-file="false"
    @select="onSelect"
  >
    <template #icon="{ node }">
      <FolderOutlined v-if="node.isFolder" style="color: #faad14" />
      <FileTextOutlined v-else style="color: #1890ff" />
    </template>
  </SmartTree>
</template>

<script setup>
import { SmartTree } from '@angineer/docs-ui'
import { FolderOutlined, FileTextOutlined } from '@ant-design/icons-vue'
</script>
```

#### 后台管理模式

```vue
<template>
  <SmartTree
    :tree-data="treeData"
    :show-search="true"
    :show-status="true"
    :draggable="true"
    :allow-add-file="true"
    @select="onSelect"
    @add-folder="onAddFolder"
    @add-file="onAddFile"
    @delete="onDelete"
    @drop="onDrop"
  >
    <template #icon="{ node }">
      <FolderOutlined v-if="node.isFolder" style="color: #faad14" />
      <FilePdfOutlined v-else style="color: #ff4d4f" />
    </template>
    <template #status="{ node }">
      <a-tag :color="node.visible ? 'green' : 'default'">
        {{ node.visible ? '共享' : '本地' }}
      </a-tag>
    </template>
  </SmartTree>
</template>
```

### 拖拽处理

```typescript
const onTreeDrop = async (info: any) => {
  const { dragNode, dropNode, dropPosition } = info
  
  if (!dragNode || !dropNode) return
  
  const nodeId = dragNode.key
  let newParentId: string | undefined
  
  if (dropPosition === 0) {
    newParentId = dropNode.key  // 成为子节点
  } else {
    newParentId = dropNode.parentId  // 成为同级节点
  }
  
  await knowledgeApi.updateNode(nodeId, { parent_id: newParentId })
  await loadNodes()  // 刷新树
}
```

---

## API 端点速查

### AI 对话

| 端点 | 方法 | 功能 | 位置 |
|------|------|------|------|
| `/api/chat` | POST | AI 流式对话（SSE） | [main.py](file:///d:/AI/AnGIneer/apps/api-server/main.py#L325) |
| `/api/llm_configs` | GET | 获取模型列表 | [main.py](file:///d:/AI/AnGIneer/apps/api-server/main.py#L310) |

**ChatRequest:**
```typescript
{
  message: string        // 当前用户输入
  history: ChatMessage[] // 历史消息
  model?: string         // 模型名称
  mode?: 'chat' | 'reasoning' | 'vision'
  context?: { references?: string[] }
}
```

**SSE 事件类型:**
- `start`: 开始事件，含 messageId
- `chunk`: 增量内容
- `end`: 结束事件，含 usage 统计
- `error`: 错误事件

### 知识树管理

| 端点 | 方法 | 功能 | 位置 |
|------|------|------|------|
| `/api/knowledge/libraries` | GET | 获取知识库列表 | [main.py](file:///d:/AI/AnGIneer/apps/api-server/main.py#L1010) |
| `/api/knowledge/libraries` | POST | 创建知识库 | [main.py](file:///d:/AI/AnGIneer/apps/api-server/main.py#L1016) |
| `/api/knowledge/nodes` | GET | 获取节点列表 | [main.py](file:///d:/AI/AnGIneer/apps/api-server/main.py#L1032) |
| `/api/knowledge/nodes` | POST | 创建节点 | [main.py](file:///d:/AI/AnGIneer/apps/api-server/main.py#L1038) |
| `/api/knowledge/nodes/{id}` | PATCH | 更新节点 | [main.py](file:///d:/AI/AnGIneer/apps/api-server/main.py#L1058) |
| `/api/knowledge/nodes/{id}` | DELETE | 删除节点 | [main.py](file:///d:/AI/AnGIneer/apps/api-server/main.py#L1067) |
| `/api/knowledge/upload` | POST | 上传文档 | [main.py](file:///d:/AI/AnGIneer/apps/api-server/main.py#L1077) |
| `/api/knowledge/parse` | POST | 解析文档 | [main.py](file:///d:/AI/AnGIneer/apps/api-server/main.py#L1113) |
| `/api/knowledge/document/{library_id}/{doc_id}` | GET | 获取文档内容 | [main.py](file:///d:/AI/AnGIneer/apps/api-server/main.py#L1169) |

---

## 数据模型

### SmartTreeNode (前端)

```typescript
interface SmartTreeNode {
  key: string           // 唯一标识
  title: string         // 显示名称
  isFolder?: boolean    // 是否为文件夹
  isLeaf?: boolean      // 是否为叶子节点
  status?: 'pending' | 'processing' | 'completed' | 'failed'
  visible?: boolean     // 是否可见（共享/本地）
  children?: SmartTreeNode[]
}
```

### KnowledgeNode (后端)

```python
class KnowledgeNode(BaseModel):
    id: str
    title: str
    type: str              # 'folder' | 'document'
    status: str = 'pending' # pending | processing | completed | failed
    visible: bool = False
    parent_id: Optional[str] = None
    library_id: str
    file_path: Optional[str] = None
```

### ChatMessage

```typescript
interface ChatMessage {
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp?: number
}
```

---

## 状态说明

| 状态 | 说明 | 适用对象 |
|------|------|----------|
| `pending` | 待处理（已上传未解析） | 文件 |
| `processing` | 解析中 | 文件 |
| `completed` | 已完成 | 文件 |
| `failed` | 解析失败 | 文件 |
| `visible` | 共享/本地标识 | 文件 |

**注意**: 文件夹不显示状态标签，仅文件显示。

---

## 开发提示

### 前端

1. **组件导入优先使用 packages**
   ```typescript
   import { SmartTree, AIChat } from '@angineer/docs-ui'
   import { AppHeader, Panel } from '@angineer/ui-kit'
   ```

2. **树数据处理使用 useKnowledgeTree**
   ```typescript
   import { useKnowledgeTree } from '@angineer/docs-ui'
   const { buildTree, findNode } = useKnowledgeTree()
   ```

3. **主题统一使用 useTheme**
   ```typescript
   import { useTheme } from '@angineer/ui-kit'
   const { isDark } = useTheme()
   ```

### Python

1. **函数外增加一句话注释**
   ```python
   # 更新知识库节点
   def update_node(self, node_id: str, **kwargs) -> Optional[KnowledgeNode]:
       """更新节点"""
       ...
   ```

2. **使用 Type Hints**
   ```python
   def create_node(self, node: KnowledgeNode) -> KnowledgeNode:
       ...
   ```
