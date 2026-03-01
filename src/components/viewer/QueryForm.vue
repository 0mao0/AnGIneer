<template>
  <div class="query-form">
    <a-form layout="vertical" :model="formState">
      <a-form-item v-for="dim in table.dimensions" :key="dim.key" :label="dim.name">
        <template v-if="dim.type === 'discrete'">
          <a-select v-model:value="formState[dim.key]" :placeholder="`选择${dim.name}`">
            <a-select-option v-for="val in dim.values" :key="String(val)" :value="val">
              {{ val }}{{ dim.unit ? ` ${dim.unit}` : '' }}
            </a-select-option>
          </a-select>
        </template>
        
        <template v-else-if="dim.type === 'range'">
          <a-select v-model:value="formState[dim.key]" :placeholder="`选择${dim.name}范围`">
            <a-select-option v-for="range in dim.ranges" :key="range.label" :value="range.label">
              {{ range.label }}
            </a-select-option>
          </a-select>
        </template>
        
        <template v-else>
          <a-input-number
            v-model:value="formState[dim.key]"
            :placeholder="`输入${dim.name}`"
            style="width: 100%"
            :addon-after="dim.unit"
          />
        </template>
      </a-form-item>

      <a-form-item>
        <a-button type="primary" block @click="handleQuery" :loading="loading">
          查询
        </a-button>
      </a-form-item>
    </a-form>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import type { TableData, TableQueryResult } from '../../types'

const props = defineProps<{
  table: TableData
}>()

const emit = defineEmits<{
  query: [result: TableQueryResult]
}>()

const loading = ref(false)
const formState = reactive<Record<string, any>>({})

const handleQuery = async () => {
  loading.value = true
  try {
    await new Promise(resolve => setTimeout(resolve, 500))
    
    const result: TableQueryResult = {
      tableId: props.table.id,
      inputs: { ...formState },
      outputs: {
        value: Math.random() * 100
      }
    }
    
    emit('query', result)
  } finally {
    loading.value = false
  }
}
</script>

<style lang="less" scoped>
.query-form {
  :deep(.ant-form-item) {
    margin-bottom: 16px;
  }
}
</style>
