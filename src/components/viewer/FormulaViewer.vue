<template>
  <div class="formula-viewer">
    <div class="formula-header">
      <h4>{{ formula.name }}</h4>
      <a-tag v-if="formula.source" color="blue">{{ formula.source }}</a-tag>
    </div>
    
    <div class="formula-display">
      <div class="formula-expression" v-html="renderedFormula" />
      <div v-if="formula.description" class="formula-description">
        {{ formula.description }}
      </div>
    </div>

    <div v-if="formula.variables?.length" class="formula-variables">
      <h5>变量说明:</h5>
      <a-table
        :columns="variableColumns"
        :data-source="formula.variables"
        :pagination="false"
        size="small"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'symbol'">
            <code>{{ record.symbol }}</code>
          </template>
        </template>
      </a-table>
    </div>

    <div v-if="showCalculator" class="formula-calculator">
      <a-divider>计算器</a-divider>
      <Calculator :formula="formula" @calculate="handleCalculate" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import Calculator from './Calculator.vue'

interface FormulaVariable {
  symbol: string
  name: string
  unit?: string
  description?: string
}

interface Formula {
  id: string
  name: string
  expression: string
  description?: string
  source?: string
  variables?: FormulaVariable[]
}

const props = withDefaults(defineProps<{
  formula: Formula
  showCalculator?: boolean
}>(), {
  showCalculator: true
})

const emit = defineEmits<{
  calculate: [result: number]
}>()

const variableColumns = [
  { title: '符号', key: 'symbol', width: 80 },
  { title: '名称', dataIndex: 'name', key: 'name' },
  { title: '单位', dataIndex: 'unit', key: 'unit', width: 80 },
  { title: '说明', dataIndex: 'description', key: 'description' }
]

const renderedFormula = computed(() => {
  return props.formula.expression
    .replace(/D₀/g, 'D<sub>0</sub>')
    .replace(/Z₀/g, 'Z<sub>0</sub>')
    .replace(/Z₁/g, 'Z<sub>1</sub>')
    .replace(/Z₂/g, 'Z<sub>2</sub>')
    .replace(/Z₃/g, 'Z<sub>3</sub>')
})

const handleCalculate = (result: number) => {
  emit('calculate', result)
}
</script>

<style lang="less" scoped>
.formula-viewer {
  padding: 16px;
  background: #f9f9f9;
  border-radius: 4px;
}

.formula-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;

  h4 {
    margin: 0;
  }
}

.formula-display {
  background: #fff;
  padding: 16px;
  border-radius: 4px;
  margin-bottom: 16px;
  text-align: center;
}

.formula-expression {
  font-family: 'Times New Roman', serif;
  font-size: 18px;
  line-height: 2;
  color: #1890ff;
}

.formula-description {
  margin-top: 8px;
  color: #666;
  font-size: 13px;
}

.formula-variables {
  margin-bottom: 16px;

  h5 {
    margin: 0 0 8px;
    font-size: 14px;
  }

  code {
    background: #f5f5f5;
    padding: 2px 6px;
    border-radius: 3px;
    font-family: 'Courier New', monospace;
  }
}

.formula-calculator {
  margin-top: 16px;
}
</style>
