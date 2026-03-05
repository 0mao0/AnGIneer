<template>
  <div class="table-renderer">
    <div class="table-wrapper" ref="tableRef">
      <table class="data-table" :class="{ 'highlight-mode': !!highlightResult }">
        <thead>
          <tr>
            <th v-for="col in columns" :key="col.key" :style="{ width: col.width }">
              {{ col.title }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(row, rowIndex) in table.data"
            :key="rowIndex"
            :class="{ highlighted: isHighlightedRow(row) }"
          >
            <td v-for="col in columns" :key="col.key">
              {{ row[col.dataIndex] }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { TableData, TableQueryResult } from '../../types'

const props = defineProps<{
  table: TableData
  highlightResult?: TableQueryResult | null
}>()

const tableRef = ref<HTMLElement | null>(null)

const columns = computed(() => {
  const cols: Array<{ title: string; dataIndex: string; key: string; width?: string }> = [
    { title: props.table.dimensions[0]?.name || '维度', dataIndex: 'dim', key: 'dim', width: '120px' }
  ]
  
  props.table.outputs.forEach((output) => {
    cols.push({
      title: output.name,
      dataIndex: output.key,
      key: output.key
    })
  })
  
  return cols
})

const isHighlightedRow = (row: Record<string, any>) => {
  if (!props.highlightResult) return false
  return Object.entries(props.highlightResult.inputs).some(
    ([key, value]) => row[key] === value
  )
}
</script>

<style lang="less" scoped>
.table-renderer {
  overflow-x: auto;
}

.table-wrapper {
  max-width: 100%;
}

.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;

  th, td {
    border: 1px solid #e8e8e8;
    padding: 8px 12px;
    text-align: center;
  }

  th {
    background: #fafafa;
    font-weight: 600;
  }

  tbody tr:hover {
    background: #f5f5f5;
  }

  &.highlight-mode {
    .highlighted {
      background: #e6f7ff;
      font-weight: 500;
    }
  }
}
</style>
