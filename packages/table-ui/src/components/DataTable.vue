<template>
  <div
    ref="tableContainerRef"
    class="data-table"
    :style="tableStyle"
  >
    <div v-if="hasToolbar" class="data-table-toolbar">
      <slot v-if="$slots.toolbar" name="toolbar" />
      <div v-else class="data-table-filter-bar">
        <template v-for="f in filters" :key="f.key">
          <a-input
            v-if="f.type === 'input'"
            v-model:value="localQuery[f.key]"
            :placeholder="f.placeholder"
            allow-clear
            :style="{ width: `${f.width || 220}px` }"
            @change="emitQuery"
          />
          <a-select
            v-else-if="f.type === 'select'"
            v-model:value="localQuery[f.key]"
            :placeholder="f.placeholder"
            allow-clear
            :mode="f.multiple ? 'multiple' : undefined"
            :max-tag-count="f.multiple ? 0 : undefined"
            :max-tag-placeholder="f.multiple ? `已选 ${(localQuery[f.key] as string[] | undefined)?.length ?? 0}` : undefined"
            :style="{ width: `${f.width || (f.multiple ? 160 : 120)}px` }"
            @change="emitQuery"
          >
            <a-select-option v-for="opt in normalizedOptions(f)" :key="String(opt.value)" :value="opt.value">
              {{ opt.label }}
            </a-select-option>
          </a-select>
          <a-radio-group
            v-else-if="f.type === 'radio'"
            v-model:value="localQuery[f.key]"
            button-style="solid"
            @change="emitQuery"
          >
            <a-radio-button v-for="opt in normalizedOptions(f)" :key="String(opt.value)" :value="opt.value">
              {{ opt.label }}
            </a-radio-button>
          </a-radio-group>
          <div v-else class="data-table-filter-switch">
            <span v-if="f.label" class="data-table-filter-switch__label">{{ f.label }}</span>
            <a-switch
              v-model:checked="localQuery[f.key]"
              :checked-children="f.checkedLabel"
              :un-checked-children="f.uncheckedLabel"
              @change="emitQuery"
            />
          </div>
        </template>
        <div v-if="$slots.toolbarExtra" class="data-table-filter-bar__extra">
          <slot name="toolbarExtra" />
        </div>
      </div>
    </div>

    <SectionCard v-if="card" nopad class="data-table-card">
      <slot name="tableExtra" />
      <a-table
        class="data-table__table"
        :columns="effectiveColumns"
        :data-source="dataSource"
        :row-key="rowKey"
        :loading="loading"
        :pagination="paginationProps"
        :row-class-name="rowClassName"
        :scroll="{ x: scrollX }"
        :locale="{ emptyText }"
        :expandable="expandable"
        :row-selection="rowSelection"
        size="small"
        @resize-column="handleResizeColumn"
        @change="onTableChange"
      >
        <template #bodyCell="scope">
          <slot name="bodyCell" v-bind="scope" />
        </template>
        <template v-if="$slots.expandedRowRender" #expandedRowRender="scope">
          <slot name="expandedRowRender" v-bind="scope" />
        </template>
        <template v-if="$slots.emptyText" #emptyText>
          <slot name="emptyText" />
        </template>
      </a-table>
    </SectionCard>
    <template v-else>
      <slot name="tableExtra" />
      <a-table
        class="data-table__table"
        :columns="effectiveColumns"
        :data-source="dataSource"
        :row-key="rowKey"
        :loading="loading"
        :pagination="paginationProps"
        :row-class-name="rowClassName"
        :scroll="{ x: scrollX }"
        :locale="{ emptyText }"
        :expandable="expandable"
        :row-selection="rowSelection"
        size="small"
        @resize-column="handleResizeColumn"
        @change="onTableChange"
      >
        <template #bodyCell="scope">
          <slot name="bodyCell" v-bind="scope" />
        </template>
        <template v-if="$slots.expandedRowRender" #expandedRowRender="scope">
          <slot name="expandedRowRender" v-bind="scope" />
        </template>
        <template v-if="$slots.emptyText" #emptyText>
          <slot name="emptyText" />
        </template>
      </a-table>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, useSlots, watch } from 'vue'
import SectionCard from './SectionCard.vue'

export interface DataTableColumn {
  key?: string
  width?: number
  minWidth?: number
  resizable?: boolean
  fixed?: 'left' | 'right' | boolean
  /** 弹性列：自动填满容器时优先吸收剩余宽度（其余列保持默认宽） */
  flex?: boolean
  [key: string]: unknown
}

export interface DataTableFilter {
  key: string
  type: 'input' | 'select' | 'switch' | 'radio'
  placeholder?: string
  width?: number
  options?: Array<string | number | { value: string | number, label: string }>
  /** select 多选模式 */
  multiple?: boolean
  /** switch 类型显示的标签 */
  label?: string
  /** switch 选中/未选中文案 */
  checkedLabel?: string
  uncheckedLabel?: string
}

const props = withDefaults(defineProps<{
  columns: DataTableColumn[]
  dataSource: Record<string, any>[]
  rowKey: string | ((record: Record<string, any>) => string)
  /** 行级自定义 class（用于移动/选中等高亮） */
  rowClassName?: string | ((record: Record<string, any>) => string)
  loading?: boolean
  pagination?: Record<string, any> | boolean
  expandable?: Record<string, any>
  rowSelection?: Record<string, any>
  filters?: DataTableFilter[]
  query?: Record<string, any>
  card?: boolean
  fillWidth?: boolean
  emptyText?: string
  /** 列宽持久化 key（localStorage），传入后拖拽列宽刷新不丢 */
  storageKey?: string
}>(), {
  loading: false,
  pagination: false,
  filters: () => [],
  rowClassName: '',
  card: true,
  fillWidth: true,
  emptyText: '暂无数据',
  storageKey: '',
})

const emit = defineEmits<{
  'update:query': [q: Record<string, any>]
  'change': [pagination: unknown, filters: unknown, sorter: unknown]
}>()

// ── 列宽拖拽（localStorage 持久化）────────────────────────────
const STORAGE_PREFIX = 'angineer-datatable-cols:'
const internalWidths = reactive<Record<string, number>>({})
const columnMinWidths: Record<string, number> = {}
const hasStoredLayout = ref(false)
const userAdjusted = ref(false)
/** 是否已通过自动填满拉伸过列宽：为 true 后跟随容器宽窄双向伸缩 */
const filledToContainer = ref(false)
let persistTimer: ReturnType<typeof setTimeout> | undefined

function readStoredWidths(): Record<string, number> {
  if (!props.storageKey) return {}
  try {
    const raw = localStorage.getItem(STORAGE_PREFIX + props.storageKey)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as Record<string, unknown>
    const out: Record<string, number> = {}
    for (const [k, v] of Object.entries(parsed)) {
      if (typeof v === 'number' && Number.isFinite(v) && v > 0) out[k] = v
    }
    return out
  } catch {
    return {}
  }
}

function persistWidths(): void {
  if (!props.storageKey) return
  try {
    localStorage.setItem(STORAGE_PREFIX + props.storageKey, JSON.stringify(internalWidths))
  } catch {
    // localStorage 不可用时忽略
  }
}

watch(() => props.columns, (cols) => {
  const stored = readStoredWidths()
  for (const col of cols) {
    if (!col.key) continue
    if (!(col.key in internalWidths)) {
      const saved = stored[col.key]
      if (col.resizable && typeof saved === 'number') {
        internalWidths[col.key] = saved
        hasStoredLayout.value = true
      } else {
        internalWidths[col.key] = typeof col.width === 'number' ? col.width : 120
      }
    }
    columnMinWidths[col.key] = typeof col.minWidth === 'number' ? col.minWidth : 50
  }
}, { immediate: true, deep: true })

const effectiveColumns = computed<DataTableColumn[]>(() =>
  props.columns.map((col) => {
    if (!col.key) {
      // 无 key 列按配置宽度渲染，缺省给默认宽度兜底（避免 table-layout: fixed 下塌缩为 0）
      return typeof col.width === 'number' ? col : { ...col, width: 120 }
    }
    const virtual = internalWidths[col.key] ?? (typeof col.width === 'number' ? col.width : 120)
    const min = typeof col.minWidth === 'number' ? col.minWidth : 50
    return { ...col, width: Math.max(virtual, min), minWidth: col.minWidth }
  }),
)

function handleResizeColumn(width: number, column: { key?: string }): void {
  const key = column.key
  if (!key || !(key in internalWidths)) return
  // 用户手动拖拽后接管布局，自动填满不再介入，避免拖拽过程回弹
  userAdjusted.value = true
  const minW = columnMinWidths[key] ?? 50
  const prevVirtual = internalWidths[key] ?? 0
  const renderedOld = Math.max(prevVirtual, minW)
  const newWidth = Math.max(minW, Math.round(width))
  const delta = newWidth - renderedOld
  internalWidths[key] = newWidth

  // 标准列宽拖拽：只改变拖动条左右两列，右侧列反向补偿同样宽度，其余列（含固定右侧列）不动。
  // 补偿列不夹紧到 minWidth，而是记录“虚拟宽度”，渲染时再夹紧到 min：
  // 右拖超过右列 min 时表格溢出，左拖回来时右列能对称恢复，避免“越拖越宽”。
  const idx = props.columns.findIndex((c) => c.key === key)
  const next = props.columns[idx + 1]
  if (next?.key && next.key in internalWidths && !next.fixed) {
    internalWidths[next.key] = (internalWidths[next.key] ?? 0) - delta
  }
  clearTimeout(persistTimer)
  persistTimer = setTimeout(persistWidths, 300)
}

// ── 横向自适应：表格宽度跟随容器，列总宽小于容器时按比例摊开填满 ──
const tableContainerRef = ref<HTMLElement | null>(null)
const containerWidth = ref(0)
let tableResizeObserver: ResizeObserver | undefined

/** 横向滚动视口宽度：以内层 .ant-table-content 为准，避免表格两侧内边框把总宽度共超出视口 2px 引发无意义滚动条 */
function viewportWidth(): number {
  const el = tableContainerRef.value
  if (!el) return 0
  const contentEl = el.querySelector<HTMLElement>('.ant-table-content, .rc-table-content')
  return contentEl?.clientWidth || el.clientWidth
}

const contentWidth = computed(() =>
  effectiveColumns.value.reduce((sum, col) => sum + (typeof col.width === 'number' ? col.width : 0), 0),
)
/** 表宽精确等于列宽总和：窄表不被浏览器等比拉伸、宽表保持溢出滚动，同时列宽严格遵循配置/拖拽结果 */
const tableStyle = computed(() => ({ '--dt-col-sum': `${contentWidth.value}px` }))
const scrollX = computed(() => Math.max(containerWidth.value, contentWidth.value))

function fillWidthToContainer(): void {
  if (!props.fillWidth || hasStoredLayout.value || userAdjusted.value) return
  const el = tableContainerRef.value
  if (!el) return
  const width = viewportWidth()
  if (!width) return
  // 内容已宽于容器（横向滚动中）时不再缩放
  const total = contentWidth.value
  if (total === 0) return
  if (!filledToContainer.value && width <= total) return

  // 弹性列（flex: true）吸收剩余宽度；未声明弹性列时退化为所有可拖拽列均分
  const flexCols = effectiveColumns.value.filter((c) => c.flex === true && c.resizable && c.key)
  const scaleTargets = flexCols.length > 0
    ? flexCols
    : effectiveColumns.value.filter((c) => c.resizable && c.key && !c.fixed)
  const scaleKeys = scaleTargets.map((c) => c.key as string)
  const scaleBase = scaleKeys.reduce((sum, k) => sum + (internalWidths[k] ?? 0), 0)
  if (scaleBase === 0) return

  const fixedTotal = effectiveColumns.value.reduce((sum, col) => {
    const key = col.key
    if (key && scaleKeys.includes(key)) return sum
    return sum + (typeof col.width === 'number' ? col.width : 0)
  }, 0)
  const leftover = width - fixedTotal
  if (leftover <= 0) return
  const scale = leftover / scaleBase
  for (const key of scaleKeys) {
    internalWidths[key] = Math.max(columnMinWidths[key] ?? 50, Math.round((internalWidths[key] ?? 0) * scale))
  }
  filledToContainer.value = true
}

function observeTableWidth(): void {
  if (!tableContainerRef.value) return
  tableResizeObserver = new ResizeObserver((entries) => {
    const width = entries[0]?.contentRect.width
    if (!width) return
    containerWidth.value = Math.round(viewportWidth())
    fillWidthToContainer()
  })
  tableResizeObserver.observe(tableContainerRef.value)
}

onMounted(() => {
  observeTableWidth()
  fillWidthToContainer()
})

onBeforeUnmount(() => {
  tableResizeObserver?.disconnect()
})

// ── 分页约定：默认 showSizeChanger=false + showTotal ──
const paginationProps = computed(() => {
  if (!props.pagination || typeof props.pagination !== 'object') return false
  return {
    showSizeChanger: false,
    ...props.pagination,
    showTotal: props.pagination.showTotal ?? ((t: number) => `共 ${t} 条`),
  }
})

function onTableChange(pagination: unknown, filters: unknown, sorter: unknown): void {
  emit('change', pagination, filters, sorter)
}

// ── 筛选栏：配置驱动，v-model:query ──
const hasToolbar = computed(() =>
  props.filters.length > 0 || !!(useSlots().toolbar || useSlots().toolbarExtra),
)

const localQuery = reactive<Record<string, any>>({})

watch(() => props.query, (q) => {
  if (q) Object.assign(localQuery, q)
}, { deep: true, immediate: true })

function normalizedOptions(f: DataTableFilter): Array<{ value: string | number, label: string }> {
  return (f.options ?? []).map((o) => {
    if (typeof o === 'object' && o !== null) return o
    return { value: o, label: String(o) }
  })
}

function emitQuery(): void {
  const q: Record<string, any> = {}
  for (const f of props.filters) {
    const v = localQuery[f.key]
    q[f.key] = v === '' ? undefined : v
  }
  emit('update:query', q)
}
</script>

<style scoped lang="less">
.data-table-filter-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 16px;

  &__extra {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    margin-left: auto;
  }
}

.data-table-filter-switch {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 32px;

  &__label {
    font-size: 13px;
    white-space: nowrap;
    color: var(--table-text-secondary, var(--text-secondary, rgba(0, 0, 0, 0.65)));
  }

  // 开关与输入框同高对齐：antd switch 默认高度低于 32px，用行内高度撑起
  :deep(.ant-switch) {
    display: inline-flex;
    align-items: center;
  }
}

// 覆盖 rc-table 内联 min-width: 100% 与自动布局，
// 避免列总宽小于容器时被浏览器等比拉伸，保证拖拽调宽时表头线与鼠标位移一致
.data-table__table :deep(table) {
  min-width: auto !important;
  // rc-table 会按 scroll.x 内联 width: Npx，会强制表宽等于容器并把富余宽度摊给各列；
  // 改为精确等于列宽总和（--dt-col-sum），列总和小于容器时不被拉伸，大于容器时保持溢出滚动
  width: var(--dt-col-sum, max-content) !important;
  table-layout: fixed !important;
}

// 列尾 resizable 列的 resize handle 定位于 right:-8px，会伸出表格右边界造成无意义横向滚动；最后一列右侧已无内容可拖，隐藏
.data-table__table :deep(th:last-child .ant-table-resize-handle) {
  display: none;
}

// 表头居中
.data-table__table :deep(th) {
  text-align: center;
}

</style>
