<template>
  <div class="table-view">
    <div class="table-header">
      <h3>{{ table.name }}</h3>
      <a-space>
        <a-button size="small" @click="toggleQueryPanel">
          <SearchOutlined /> 查询
        </a-button>
        <a-button size="small" @click="exportTable">
          <DownloadOutlined /> 导出
        </a-button>
      </a-space>
    </div>

    <a-drawer v-model:open="queryPanelVisible" title="表格查询" placement="right" width="400">
      <QueryForm :table="table" @query="handleQuery" />
    </a-drawer>

    <div class="table-content">
      <TableRenderer :table="table" :highlight-result="queryResult" />
    </div>

    <div v-if="queryResult" class="query-result">
      <a-alert type="success" show-icon>
        <template #message>
          查询结果: {{ queryResult.outputs }}
        </template>
      </a-alert>
      <div v-if="queryResult.warnings?.length" class="warnings">
        <a-alert
          v-for="(warning, i) in queryResult.warnings"
          :key="i"
          type="warning"
          :message="warning"
          show-icon
          style="margin-top: 8px"
        />
      </div>
    </div>

    <div v-if="table.notes?.length" class="table-notes">
      <a-collapse ghost>
        <a-collapse-panel key="notes" header="备注说明">
          <ul>
            <li v-for="(note, i) in table.notes" :key="i">{{ note }}</li>
          </ul>
        </a-collapse-panel>
      </a-collapse>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { SearchOutlined, DownloadOutlined } from '@ant-design/icons-vue'
import TableRenderer from '../common/TableRenderer.vue'
import QueryForm from './QueryForm.vue'
import type { TableData, TableQueryResult } from '../../types'

const props = defineProps<{
  table: TableData
}>()

const emit = defineEmits<{
  query: [result: TableQueryResult]
}>()

const queryPanelVisible = ref(false)
const queryResult = ref<TableQueryResult | null>(null)

const toggleQueryPanel = () => {
  queryPanelVisible.value = !queryPanelVisible.value
}

const handleQuery = (result: TableQueryResult) => {
  queryResult.value = result
  emit('query', result)
}

const exportTable = () => {
  console.log('Export table:', props.table)
}
</script>

<style lang="less" scoped>
.table-view {
  padding: 16px;
}

.table-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;

  h3 {
    margin: 0;
  }
}

.table-content {
  margin-bottom: 16px;
}

.query-result {
  margin-bottom: 16px;
}

.warnings {
  margin-top: 8px;
}

.table-notes {
  ul {
    margin: 0;
    padding-left: 20px;
  }
}
</style>
