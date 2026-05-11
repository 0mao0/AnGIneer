/**
 * SOP 步骤属性面板组件，展示和编辑选中步骤的详细信息。
 */
<template>
  <div class="sop-property-panel">
    <a-form layout="vertical" size="small">
      <a-form-item label="步骤 ID">
        <a-input :value="step.id" disabled />
      </a-form-item>

      <a-form-item label="名称">
        <a-input :value="step.name || step.name_zh || ''" @change="onFieldChange('name', $event)" />
      </a-form-item>

      <a-form-item label="描述">
        <a-textarea
          :value="step.description || ''"
          :rows="3"
          @change="onFieldChange('description', $event)"
        />
      </a-form-item>

      <a-form-item label="工具">
        <a-select :value="step.tool" @change="onSelectChange('tool', $event)">
          <a-select-option value="manual">手动</a-select-option>
          <a-select-option value="calculator">计算器</a-select-option>
          <a-select-option value="table_lookup">表格查询</a-select-option>
          <a-select-option value="auto">自动</a-select-option>
          <a-select-option value="sop_run">SOP 执行</a-select-option>
          <a-select-option value="llm_call">LLM 调用</a-select-option>
        </a-select>
      </a-form-item>

      <a-form-item label="输入参数">
        <div v-for="(value, key) in step.inputs" :key="key" class="kv-row">
          <a-input :value="key" disabled class="kv-key" />
          <a-input :value="String(value)" disabled class="kv-value" />
        </div>
        <div v-if="!step.inputs || Object.keys(step.inputs).length === 0" class="kv-empty">
          暂无输入参数
        </div>
      </a-form-item>

      <a-form-item label="输出">
        <div v-for="(value, key) in step.outputs" :key="key" class="kv-row">
          <a-input :value="key" disabled class="kv-key" />
          <a-input :value="String(value)" disabled class="kv-value" />
        </div>
        <div v-if="!step.outputs || Object.keys(step.outputs).length === 0" class="kv-empty">
          暂无输出
        </div>
      </a-form-item>

      <a-form-item label="备注">
        <a-textarea
          :value="step.notes || ''"
          :rows="2"
          @change="onFieldChange('notes', $event)"
        />
      </a-form-item>
    </a-form>
  </div>
</template>

<script setup lang="ts">
import type { SopStep } from '../types/sop'

defineProps<{
  step: SopStep
}>()

const emit = defineEmits<{
  update: [updates: Partial<SopStep>]
}>()

const onFieldChange = (field: string, event: Event) => {
  const value = (event.target as HTMLInputElement).value
  emit('update', { [field]: value })
}

const onSelectChange = (field: string, value: string) => {
  emit('update', { [field]: value })
}
</script>

<style lang="less" scoped>
.sop-property-panel {
  padding: 12px;
}

.kv-row {
  display: flex;
  gap: 8px;
  margin-bottom: 4px;
}

.kv-key {
  flex: 1;
}

.kv-value {
  flex: 2;
}

.kv-empty {
  color: var(--text-secondary, #8c8c8c);
  font-size: 12px;
  padding: 4px 0;
}
</style>
