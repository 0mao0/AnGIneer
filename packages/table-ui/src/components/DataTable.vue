<template>
  <div
    ref="tableContainerRef"
    class="data-table"
    :class="{ 'data-table--row-click-expand': expandRowByClick && hasExpandSlot }"
    :style="tableStyle"
  >
    <!-- 槽位存在性不具响应性：数据异步加载后才出现的 toolbar 插槽若走 computed 会被永久缓存为 false，必须模板内直接判 -->
    <div v-if="filters.length > 0 || $slots.toolbar || $slots.toolbarExtra" class="data-table-toolbar">
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
        :expand-row-by-click="expandRowByClick"
        :expand-column-width="hasExpandSlot ? EXPAND_COL_W : undefined"
        size="small"
        @resize-column="handleResizeColumn"
        @change="onTableChange"
        @expand="handleTableExpand"
      >
        <template #bodyCell="scope">
          <slot name="bodyCell" v-bind="scope" />
        </template>
        <template v-if="$slots.headerCell" #headerCell="scope">
          <slot name="headerCell" v-bind="scope" />
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
        :expand-row-by-click="expandRowByClick"
        :expand-column-width="hasExpandSlot ? EXPAND_COL_W : undefined"
        size="small"
        @resize-column="handleResizeColumn"
        @change="onTableChange"
        @expand="handleTableExpand"
      >
        <template #bodyCell="scope">
          <slot name="bodyCell" v-bind="scope" />
        </template>
        <template v-if="$slots.headerCell" #headerCell="scope">
          <slot name="headerCell" v-bind="scope" />
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
  /** 整行点击展开（配合 #expandedRowRender 使用，透传 antd expandRowByClick） */
  expandRowByClick?: boolean
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
  expandRowByClick: false,
})

const emit = defineEmits<{
  'update:query': [q: Record<string, any>]
  'change': [pagination: unknown, filters: unknown, sorter: unknown]
  'expand': [expanded: boolean, record: Record<string, any>]
}>()

/** 展开图标列宽度：a-table 注入列无宽度，与强制表宽机制（--dt-col-sum）配合需显式定宽 */
const EXPAND_COL_W = 40
/** 勾选列（rowSelection）默认宽度，同展开列：注入列不在 columns 里，必须计入强制表宽 */
const SELECTION_COL_W = 32

const hasExpandSlot = computed(() => !!useSlots().expandedRowRender)
const selectionColW = computed(() => {
  const rs = props.rowSelection as Record<string, unknown> | undefined
  if (!rs) return 0
  return typeof rs.columnWidth === 'number' ? rs.columnWidth : SELECTION_COL_W
})

function handleTableExpand(expanded: boolean, record: Record<string, any>): void {
  emit('expand', expanded, record)
}

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
    // resizable 默认 true（未显式设为 false 即启用）
    const resizable = col.resizable === false ? false : true
    if (!col.key) {
      // 无 key 列按配置宽度渲染，缺省给默认宽度兜底（避免 table-layout: fixed 下塌缩为 0）
      return typeof col.width === 'number' ? { ...col, resizable } : { ...col, width: 120, resizable }
    }
    const virtual = internalWidths[col.key] ?? (typeof col.width === 'number' ? col.width : 120)
    const min = typeof col.minWidth === 'number' ? col.minWidth : 50
    return { ...col, width: Math.max(virtual, min), minWidth: col.minWidth, resizable }
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
  effectiveColumns.value.reduce((sum, col) => sum + (typeof col.width === 'number' ? col.width : 0), 0)
  // 展开图标列/勾选列由 a-table 注入、不在 columns 内，强制表宽必须把它们算进来，
  // 否则会被 fixed 布局挤到 0（展开列）或表宽恒定超出容器一个勾选列宽（实踩 32px 横向滚动）
  + (hasExpandSlot.value ? EXPAND_COL_W : 0) + selectionColW.value,
)
/** 表宽精确等于列宽总和：窄表不被浏览器等比拉伸、宽表保持溢出滚动，同时列宽严格遵循配置/拖拽结果 */
const tableStyle = computed(() => ({ '--dt-col-sum': `${contentWidth.value}px` }))
const scrollX = computed(() => Math.max(containerWidth.value, contentWidth.value))

/** 取整后把 ±1px 舍入误差从最宽的列起逐列修正，保证参与列总宽精确等于预算（防多列取整累积出横向滚动条） */
function applyScaledWidths(keys: string[], computed: Record<string, number>, budget: number): void {
  let sum = 0
  for (const k of keys) {
    internalWidths[k] = Math.round(computed[k])
    sum += internalWidths[k]
  }
  let diff = Math.round(budget) - sum
  if (!Number.isFinite(diff) || diff === 0) return
  const order = keys.slice().sort((a, b) => internalWidths[b] - internalWidths[a])
  for (const k of order) {
    if (diff === 0) return
    const min = columnMinWidths[k] ?? 50
    if (diff > 0) {
      internalWidths[k] += 1
      diff -= 1
    } else if (internalWidths[k] - 1 >= min) {
      internalWidths[k] -= 1
      diff += 1
    }
  }
}

function fillWidthToContainer(): void {
  if (!props.fillWidth || userAdjusted.value) return
  const el = tableContainerRef.value
  if (!el) return
  const width = viewportWidth()
  if (!width) return
  const total = contentWidth.value
  if (total === 0) return

  // 弹性列（flex: true）吸收宽度差；未声明弹性列时退化为所有可拖拽列按比例分摊
  const flexCols = effectiveColumns.value.filter((c) => c.flex === true && c.resizable && c.key)
  const scaleTargets = flexCols.length > 0
    ? flexCols
    : effectiveColumns.value.filter((c) => c.resizable && c.key && !c.fixed)
  const scaleKeys = scaleTargets.map((c) => c.key as string)
  if (scaleKeys.length === 0) return
  const scaleBase = scaleKeys.reduce((sum, k) => sum + (internalWidths[k] ?? 0), 0)
  if (scaleBase === 0) return

  // 展开图标列/勾选列不在 columns 里但占宽度，分摊时必须先扣掉，否则总宽超容器出横向滚动
  const auxTotal = (hasExpandSlot.value ? EXPAND_COL_W : 0) + selectionColW.value
  const fixedTotal = effectiveColumns.value.reduce((sum, col) => {
    const key = col.key
    if (key && scaleKeys.includes(key)) return sum
    return sum + (typeof col.width === 'number' ? col.width : 0)
  }, 0) + auxTotal

  // 双向自适应：宽则拉伸、窄则收缩（各列不低于 minWidth）
  const minScale = scaleKeys.reduce((sum, k) => sum + (columnMinWidths[k] ?? 50), 0)
  const leftover = width - fixedTotal

  if (width >= total || leftover >= minScale) {
    // 容器更宽，或缺口在弹性列自身余量内：维持原语义，仅缩放列参与
    const scale = leftover / scaleBase
    const computed: Record<string, number> = {}
    for (const key of scaleKeys) {
      computed[key] = Math.max(columnMinWidths[key] ?? 50, (internalWidths[key] ?? 0) * scale)
    }
    applyScaledWidths(scaleKeys, computed, leftover)
    filledToContainer.value = true
    return
  }

  // 容器放不下且弹性列兜不住：全部非 fixed 可收缩列按余量分摊收缩（原行为只缩弹性列，
  // 一列余量不足即整表放弃 → 基础列宽总和大于容器时横向滚动条永存，夜间维护表实踩）。
  // 触底 minWidth 的列退出分摊、剩余缺口重新分给未触底列；全部触底仍放不下才允许横向滚动
  const shrinkKeys = effectiveColumns.value
    .filter((c) => c.resizable && c.key && !c.fixed)
    .map((c) => c.key as string)
  if (shrinkKeys.length === 0) return
  const nonShrinkTotal = effectiveColumns.value.reduce((sum, col) => {
    const key = col.key
    if (key && shrinkKeys.includes(key)) return sum
    return sum + (typeof col.width === 'number' ? col.width : 0)
  }, 0) + auxTotal
  const budget = width - nonShrinkTotal
  const minTotal = shrinkKeys.reduce((sum, k) => sum + (columnMinWidths[k] ?? 50), 0)
  if (budget < minTotal) return
  const w: Record<string, number> = {}
  for (const k of shrinkKeys) w[k] = internalWidths[k] ?? 0
  const floored = new Set<string>()
  for (let iter = 0; iter <= shrinkKeys.length; iter++) {
    const active = shrinkKeys.filter((k) => !floored.has(k))
    if (active.length === 0) break
    const flooredSum = shrinkKeys.reduce((sum, k) => (floored.has(k) ? sum + w[k] : sum), 0)
    const activeBase = active.reduce((sum, k) => sum + w[k], 0)
    if (activeBase <= 0) break
    const scale = (budget - flooredSum) / activeBase
    let anyClamped = false
    for (const k of active) {
      const min = columnMinWidths[k] ?? 50
      if (w[k] * scale <= min) {
        w[k] = min
        floored.add(k)
        anyClamped = true
      } else {
        w[k] = w[k] * scale
      }
    }
    if (!anyClamped) break
  }
  applyScaledWidths(shrinkKeys, w, budget)
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

// ── 分页约定：受控模式，showSizeChanger 默认 true ──
const internalPagination = reactive<Record<string, any>>({})

const paginationProps = computed(() => {
  if (!props.pagination || typeof props.pagination !== 'object') return false
  return {
    showSizeChanger: true,
    ...props.pagination,
    ...internalPagination,
    showTotal: props.pagination.showTotal ?? ((t: number) => `共 ${t} 条`),
  }
})

function onTableChange(pagination: unknown, filters: unknown, sorter: unknown): void {
  // 受控分页：回写当前页码和每页条数
  if (pagination && typeof pagination === 'object') {
    const p = pagination as Record<string, any>
    if (p.current !== undefined) internalPagination.current = p.current
    if (p.pageSize !== undefined) internalPagination.pageSize = p.pageSize
  }
  emit('change', pagination, filters, sorter)
}

// ── 筛选栏：配置驱动，v-model:query ──
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

// 表头居中。必须 !important：antd cssinjs 给 th 注入 text-align:start 的特异性
// 高于 scoped 编译产物（实测 computed 为 start），常规覆盖无效——只影响表头对齐，无副作用面。
.data-table__table :deep(th) {
  text-align: center !important;
}

// 单元格内容默认居中（表头与内容一致）。用 td.ant-table-cell 提升特异性盖过 antd 默认样式；
// 不带 !important，这样列级 column.align（antd 写在 td 内联样式上）仍能覆盖成左对齐/右对齐。
.data-table__table :deep(td.ant-table-cell) {
  text-align: center;
}

// 整行热区展开：行级指针光标提示可点击
.data-table--row-click-expand :deep(.ant-table-row) {
  cursor: pointer;
}

// 分页栏无背景底色
:deep(.ant-table-pagination) {
  background: transparent !important;
}

</style>
