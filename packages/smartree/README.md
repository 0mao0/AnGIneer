# @angineer/smartree

通用树组件库（Vue 3 + ant-design-vue）：SmartTree——搜索高亮、拖拽排序、文件拖入上传、状态标签、虚拟滚动，外加一套零依赖的树工具函数。

## 特性

- **搜索过滤**：内置搜索框，关键字高亮、自动展开命中路径
- **拖拽排序**：节点拖拽移动 / 跨级放置，完整 `DropEvent` 上下文（含拖拽后整树）
- **文件拖入上传**：从操作系统拖文件到目录节点，按 `allowedFileTypes` 白名单校验
- **状态体系**：节点状态标签（pending/uploading/processing/queued/completed/failed/cancelled/partial）自动着色
- **虚拟滚动**：`virtual` + `height` 开启大数据量虚拟列表
- **暗色模式**：`dark` prop 或导入 `./style` 后跟随 `[data-theme="dark"]`
- **树工具函数**：`buildTreeFromFlat` / `sortTreeNodes` / `filterTree` / `getExpandedKeysForSearch` 等，可脱离组件单独使用（`@angineer/smartree/utils/tree`）

## 安装

未发布到 npm registry，从 GitHub 仓库钉 tag 安装：

```jsonc
// package.json
{
  "dependencies": {
    "@angineer/smartree": "github:0mao0/angineer-smartree-ui#v0.1.1"
  }
}
```

```bash
pnpm install
```

**环境要求**：`vue 3.5.41` + `ant-design-vue 4.2.6` + `@ant-design/icons-vue 7.0.1`（peerDependencies）。包为源码分发（无构建产物），宿主需用 Vite + `@vitejs/plugin-vue` 与 less 编译。

建议导入主题 token（提供 dark 模式下的专有颜色值；不导入则使用组件内 fallback 的 light 默认值）：

```ts
import '@angineer/smartree/style'
```

## 快速上手

```vue
<template>
  <SmartTree
    :tree-data="treeData"
    draggable
    multiple
    :allowed-file-types="['.pdf', '.docx']"
    @select="onSelect"
    @drop="onDrop"
    @file-drop="onFileDrop"
  />
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { SmartTree, buildTreeFromFlat } from '@angineer/smartree'
import type { SmartTreeNode, DropEvent } from '@angineer/smartree'

const treeData = ref<SmartTreeNode[]>([])

// 从扁平列表建树（按 sortOrder 排序）
treeData.value = buildTreeFromFlat<SmartTreeNode>({
  items: [
    { id: '1', parentId: null, name: '规范', sortOrder: 0 },
    { id: '2', parentId: '1', name: '第一章.pdf', sortOrder: 0 },
  ],
  toNode: (item) => ({ key: item.id, title: item.name, isFolder: !item.parentId }),
})

function onSelect(keys: string[], nodes: SmartTreeNode[]) { /* ... */ }
function onDrop(e: DropEvent) { /* e.siblings / e.targetParentKey / 拖拽后整树 */ }
function onFileDrop(files: File[], folder: SmartTreeNode | null) { /* ... */ }
</script>
```

## Props

| Prop | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `treeData` | `T[]` | 必填 | 树数据（`T extends SmartTreeNode`） |
| `showSearch` | `boolean` | `true` | 显示搜索框 |
| `searchPlaceholder` | `string` | `'搜索...'` | 搜索框占位 |
| `highlightSearch` | `boolean` | `true` | 搜索关键字高亮 |
| `showAddRootFolder` | `boolean` | `true` | 显示"新建根目录"入口 |
| `addRootFolderText` / `addRootFolderTitle` | `string` | — | 根目录入口文案/悬浮提示 |
| `showIcon` / `showStatus` / `showLine` | `boolean` | `true` / `true` / `false` | 图标 / 状态标签 / 连接线 |
| `draggable` | `boolean` | `false` | 节点可拖拽 |
| `multiple` | `boolean` | `false` | 多选 |
| `allowAddFile` | `boolean` | `true` | 允许"新建文件"操作 |
| `allowBatchDelete` | `boolean` | `true` | 允许多选批量删除 |
| `allowedFileTypes` | `string[]` | `['.pdf']` | 文件拖入类型白名单 |
| `loading` | `boolean` | `false` | 加载态 |
| `emptyText` | `string` | `'暂无数据'` | 空态文案 |
| `defaultExpandedKeys` / `defaultSelectedKeys` | `string[]` | `[]` | 初始展开/选中 |
| `defaultExpandAll` | `boolean` | `false` | 初始全部展开 |
| `dark` | `boolean` | `false` | 强制暗色（不依赖 `[data-theme]`） |
| `virtual` / `height` | `boolean` / `number` | `false` / — | 虚拟滚动与容器高度 |
| `rootDropText` / `noSearchResultText` / `fileDropHintPrefix` | `string` | — | 各类提示文案 |
| `actionLabels` | `Partial<Record<...>>` | `{}` | 节点操作文案覆盖（rename/addSubFolder/addFile/view/delete/batchDelete） |

## 事件

| 事件 | 签名 | 说明 |
| --- | --- | --- |
| `select` | `(keys: string[], nodes: T[])` | 选中变化 |
| `rename` / `delete` / `view` | `(node: T)` | 节点操作 |
| `add-folder` | `(node: T \| null)` | 新建目录（null 表示根目录） |
| `add-file` | `(node: T)` | 新建文件 |
| `batch-delete` | `(node: T)` | 批量删除 |
| `drop` | `(event: DropEvent)` | 节点拖放完成（含 `siblings`、`targetParentKey` 与拖拽后整树） |
| `search` | `(text: string)` | 搜索输入 |
| `file-drop` | `(files: File[], targetFolder: T \| null)` | 系统文件拖入 |
| `drop-invalid` | `(reason: string)` | 文件类型校验失败 |
| `drop-root` | `(dragNodeKeys: string[])` | 拖到根级空白区 |

## 暴露方法（`defineExpose`）

`expandAll()` / `collapseAll()` / `getSelectedNodes()` / `validateFileType()` / `getAllowedFileTypesDesc()`，以及响应式状态 `searchText` / `expandedKeys` / `selectedKeys`。

## 工具函数（`@angineer/smartree/utils/tree`）

| 函数 | 说明 |
| --- | --- |
| `buildTreeFromFlat<T>({ items, toNode })` | 扁平列表建树（按 `sortOrder` 排序，`T extends SortableTreeNode`） |
| `sortTreeNodes<T>(nodes)` | 树节点按 `sortOrder` 递归排序 |
| `filterTree<T>(nodes, keyword)` | 按标题过滤（保留命中路径） |
| `getExpandedKeysForSearch<T>(nodes, keyword)` | 计算搜索命中需展开的 key 集合 |
| `cloneTree<T>(nodes)` | 深拷贝树 |
| `escapeHtml` / `highlightText` | XSS 转义 / 关键字高亮 HTML |
| `getFileIconType` / `getFileIconColor` | 按扩展名取图标类型/颜色 |
| `getStatusColor` / `getStatusText` | 状态 → 颜色/文案映射 |

## 主题定制

组件颜色经 `var(--tree-*, 默认值)` 解析，使用处自带 fallback，不导入样式文件也能正常工作（light 默认值）。导入 `./style` 后获得 dark 模式专有值，并可在 `:root` 覆盖同名变量定制：

| 变量 | light | dark |
| --- | --- | --- |
| `--tree-folder-color` | `#f0b90b` | `#f5c542` |
| `--tree-danger-color` / `--tree-danger-hover` | `#cf1322` | `#e05353` |
| `--tree-drop-zone-bg` | `rgba(24, 144, 255, 0.06)` | `rgba(24, 144, 255, 0.16)` |
| `--tree-drop-border` | `rgba(24, 144, 255, 0.5)` | `rgba(23, 125, 220, 0.6)` |

## 类型

```ts
import type { SmartTreeNode, SmartTreeNodeStatus, TreeNodeAction, DropEvent } from '@angineer/smartree'
```

`SmartTreeNode` 业务字段经索引签名自由挂载，严格类型由消费方继承后定义。

## 仓库说明

本仓库为独立发布仓，代码唯一真相源在 [AnGIneer](https://github.com/0mao0/AnGIneer) monorepo 的 `packages/smartree`，经 `scripts/sync-standalone.ps1` 同步；版本以 git tag 发布。变更历史见 [CHANGELOG.md](./CHANGELOG.md)。
