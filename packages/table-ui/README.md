# @angineer/table-ui

通用表格组件库（Vue 3 + ant-design-vue）：配置驱动的 DataTable——筛选栏、列宽拖拽持久化、容器自适应填满，外加配套卡片容器 SectionCard。

## 特性

- **配置驱动筛选栏**：`filters` 声明式配置，支持 input / select（可多选）/ radio / switch 四种控件，`v-model:query` 输出查询条件
- **列宽拖拽 + 持久化**：列声明 `resizable` 即可拖拽调宽，传入 `storageKey` 后列宽写入 localStorage，刷新不丢
- **容器自适应填满**：`fillWidth` 开启时（默认）列总宽小于容器自动按比例摊开；`flex: true` 标记的弹性列优先吸收剩余宽度
- **卡片容器模式**：默认把表格包进圆角卡片（内置 SectionCard），`:card="false"` 即裸表格
- **主题零配置**：颜色经 `var(--table-*, var(--语义变量, 默认值))` 双回退——跟随宿主主题（含 dark/light），无宿主变量时用内置默认值，也可覆盖 `--table-*` 单独定制表格
- a-table 能力透传：展开行、行选择、行高亮、空态文案、分页约定（`showTotal` 默认"共 N 条"）

## 安装

已发布到 npm registry：

```bash
pnpm add @angineer/table-ui
```

或从 GitHub 钉 tag 安装（源码同源）：`"@angineer/table-ui": "github:0mao0/angineer-table-ui#v0.1.1"`

**环境要求**：`vue 3.5.41` + `ant-design-vue 4.2.6`（peerDependencies）。包为源码分发（无构建产物），宿主需用 Vite + `@vitejs/plugin-vue` 与 less 编译（与本组织其他 `*-ui` 包一致）。

## 快速上手

```vue
<template>
  <DataTable
    v-model:query="query"
    :columns="columns"
    :data-source="users"
    row-key="id"
    :loading="loading"
    :filters="filters"
    :pagination="{ pageSize: 15 }"
    storage-key="my-users-table"
    @change="onTableChange"
  >
    <template #bodyCell="{ column, record }">
      <template v-if="column.key === 'action'">
        <a @click="edit(record)">编辑</a>
      </template>
    </template>
  </DataTable>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { DataTable } from '@angineer/table-ui'
import type { DataTableColumn, DataTableFilter } from '@angineer/table-ui'

const columns: DataTableColumn[] = [
  { key: 'name', title: '姓名', width: 200, resizable: true, flex: true },
  { key: 'role', title: '角色', width: 120 },
  { key: 'action', title: '操作', width: 100, fixed: 'right' },
]

const filters: DataTableFilter[] = [
  { key: 'keyword', type: 'input', placeholder: '搜索姓名/账号', width: 240 },
  { key: 'role', type: 'select', placeholder: '角色', options: ['管理员', '编辑', '访客'] },
  { key: 'tags', type: 'select', placeholder: '标签', multiple: true, options: [{ value: 'vip', label: 'VIP' }] },
  { key: 'status', type: 'radio', options: [{ value: 'all', label: '全部' }, { value: 'on', label: '启用' }] },
  { key: 'enabled', type: 'switch', label: '仅启用', checkedLabel: '是', uncheckedLabel: '否' },
]

const query = ref<Record<string, any>>({})
const users = ref<Record<string, any>[]>([])
const loading = ref(false)

function onTableChange(pagination: unknown, _filters: unknown, sorter: unknown) {
  // a-table change 事件透传：分页/排序变化时重新拉数
}
function edit(record: Record<string, any>) { /* ... */ }
</script>
```

## Props

| Prop | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `columns` | `DataTableColumn[]` | 必填 | 列配置（透传 a-table 列属性，扩展见下表） |
| `dataSource` | `Record<string, any>[]` | 必填 | 数据源 |
| `rowKey` | `string \| (record) => string` | 必填 | 行主键 |
| `filters` | `DataTableFilter[]` | `[]` | 筛选栏配置，见下表 |
| `query` | `Record<string, any>` | — | 查询条件，配合 `v-model:query` 双向绑定 |
| `pagination` | `object \| false` | `false` | a-table 分页配置；对象形式时默认补 `showSizeChanger: false` 与 `showTotal: 共 N 条` |
| `loading` | `boolean` | `false` | 加载态 |
| `card` | `boolean` | `true` | 是否包进卡片容器（内置 SectionCard） |
| `fillWidth` | `boolean` | `true` | 列总宽小于容器时自动摊开填满 |
| `storageKey` | `string` | `''` | 列宽持久化 key（localStorage：`angineer-datatable-cols:<storageKey>`） |
| `emptyText` | `string` | `'暂无数据'` | 空态文案 |
| `rowClassName` | `string \| (record) => string` | `''` | 行级自定义 class（移动/选中高亮等） |
| `expandable` / `rowSelection` | `object` | — | a-table 对应配置透传 |

### DataTableColumn（在 a-table 列属性基础上扩展）

| 字段 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `key` | `string` | — | 列标识；参与列宽管理/持久化的列必须提供 |
| `width` | `number` | `120` | 初始列宽（px） |
| `minWidth` | `number` | `50` | 拖拽下限（px） |
| `resizable` | `boolean` | `false` | 可拖拽调宽 |
| `flex` | `boolean` | `false` | 弹性列：自适应填满时优先吸收剩余宽度 |
| `fixed` | `'left' \| 'right' \| boolean` | — | 固定列（固定列不参与拖拽补偿与自适应缩放） |

### DataTableFilter

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `key` | `string` | 查询条件字段名（`update:query` 输出的 key） |
| `type` | `'input' \| 'select' \| 'radio' \| 'switch'` | 控件类型 |
| `placeholder` | `string` | input/select 占位文案 |
| `width` | `number` | 控件宽度（px）；默认 input 220、select 120、多选 select 160 |
| `options` | `Array<string \| number \| { value, label }>` | select/radio 的选项 |
| `multiple` | `boolean` | select 多选模式 |
| `label` | `string` | switch 左侧标签 |
| `checkedLabel` / `uncheckedLabel` | `string` | switch 选中/未选中文案 |

## 事件

| 事件 | 签名 | 说明 |
| --- | --- | --- |
| `update:query` | `(q: Record<string, any>)` | 筛选栏任一控件变化即触发；空字符串归一为 `undefined` |
| `change` | `(pagination, filters, sorter)` | a-table change 事件透传（分页/排序/列筛选变化） |

## 插槽

| 插槽 | 说明 |
| --- | --- |
| `bodyCell` | 单元格自定义渲染（a-table 同名机制，scope：`{ column, record, text, index }`） |
| `toolbar` | 整体替换筛选栏 |
| `toolbarExtra` | 筛选栏右侧追加内容（按钮等） |
| `tableExtra` | 表格上方追加内容（卡片内侧/裸表格均生效） |
| `expandedRowRender` | 展开行渲染（配合 `expandable`） |
| `emptyText` | 空态自定义内容 |

## 主题定制

组件颜色全部经双回退解析：`var(--table-*, var(--宿主语义变量, 内置默认值))`。
即：默认跟随宿主全局主题（含 `[data-theme="dark"]` 下的暗色值），宿主无对应变量时使用内置默认值；想单独定制表格外观，在 `:root` 覆盖 `--table-*` 即可，无需导入任何样式文件。

| 变量 | 跟随的宿主变量 | 内置默认值（light） |
| --- | --- | --- |
| `--table-card-bg` | `--card-bg` | `#ffffff` |
| `--table-border-color` | `--border-color` | `rgba(0, 0, 0, 0.06)` |
| `--table-divider-color` | `--divider-color` | `rgba(0, 0, 0, 0.08)` |
| `--table-text-primary` | `--text-primary` | `rgba(0, 0, 0, 0.85)` |
| `--table-text-secondary` | `--text-secondary` | `rgba(0, 0, 0, 0.65)` |
| `--table-shadow-sm` | `--shadow-sm` | `0 1px 2px rgba(0, 0, 0, 0.06)` |
| `--table-shadow-md` | `--shadow-md` | `0 4px 12px rgba(0, 0, 0, 0.08)` |

## 导出

```ts
import { DataTable, SectionCard } from '@angineer/table-ui'
import type { DataTableColumn, DataTableFilter } from '@angineer/table-ui'
```

## 仓库说明

本仓库为独立发布仓，代码唯一真相源在 [AnGIneer](https://github.com/0mao0/AnGIneer) monorepo 的 `packages/table-ui`，经 `scripts/sync-standalone.ps1` 同步；版本以 git tag（vx.y.z）与 npm registry（`@angineer/table-ui`）同步发布。变更历史见 [CHANGELOG.md](./CHANGELOG.md)。
