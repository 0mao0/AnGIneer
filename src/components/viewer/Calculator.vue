<template>
  <div class="calculator">
    <a-form layout="inline" :model="values">
      <a-form-item v-for="variable in formula.variables" :key="variable.symbol" :label="variable.symbol">
        <a-input-number
          v-model:value="values[variable.symbol]"
          :placeholder="variable.name"
          style="width: 120px"
          :addon-after="variable.unit"
        />
      </a-form-item>
      <a-form-item>
        <a-button type="primary" @click="calculate">计算</a-button>
      </a-form-item>
    </a-form>

    <div v-if="result !== null" class="result">
      <a-alert type="success" show-icon>
        <template #message>
          计算结果: <strong>{{ result.toFixed(2) }}</strong>
        </template>
      </a-alert>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'

interface FormulaVariable {
  symbol: string
  name: string
  unit?: string
}

interface Formula {
  id: string
  name: string
  expression: string
  variables?: FormulaVariable[]
}

defineProps<{
  formula: Formula
}>()

const emit = defineEmits<{
  calculate: [result: number]
}>()

const values = reactive<Record<string, number>>({})
const result = ref<number | null>(null)

const calculate = () => {
  const sum = Object.values(values).reduce((acc, val) => acc + (val || 0), 0)
  result.value = sum
  emit('calculate', sum)
}
</script>

<style lang="less" scoped>
.calculator {
  :deep(.ant-form-inline .ant-form-item) {
    margin-bottom: 12px;
  }
}

.result {
  margin-top: 16px;
}
</style>
