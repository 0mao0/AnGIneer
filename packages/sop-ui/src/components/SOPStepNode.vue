/**
 * SOP 步骤自定义节点组件，卡片式布局，显示步骤序号、名称、工具图标和描述。
 */
<template>
  <div class="sop-step-node" :class="{ selected: selected, hovered: hovered }">
    <Handle type="target" :position="Position.Top" />
    <div class="step-header">
      <span class="step-index">{{ stepIndex + 1 }}</span>
      <span class="step-name">{{ step.name || step.name_zh || step.id }}</span>
      <component :is="toolIcon" class="step-tool-icon" />
    </div>
    <div v-if="step.description" class="step-desc">
      {{ truncatedDesc }}
    </div>
    <Handle type="source" :position="Position.Bottom" />
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import {
  CalculatorOutlined,
  TableOutlined,
  ThunderboltOutlined,
  ToolOutlined,
} from '@ant-design/icons-vue'
import type { SopStep } from '../types/sop'

const props = defineProps<{
  id: string
  data: { step: SopStep; stepIndex: number }
  selected?: boolean
}>()

const hovered = ref(false)

const step = computed(() => props.data.step)
const stepIndex = computed(() => props.data.stepIndex)

const toolIconMap: Record<string, any> = {
  calculator: CalculatorOutlined,
  table_lookup: TableOutlined,
  auto: ThunderboltOutlined,
}

const toolIcon = computed(() => {
  return toolIconMap[step.value.tool] || ToolOutlined
})

const truncatedDesc = computed(() => {
  const desc = step.value.description || ''
  return desc.length > 60 ? desc.slice(0, 57) + '...' : desc
})
</script>

<style lang="less" scoped>
.sop-step-node {
  min-width: 180px;
  max-width: 260px;
  padding: 10px 14px;
  border-radius: 8px;
  background: var(--panel-bg, #fff);
  border: 2px solid var(--border-color, #e8e8e8);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  transition: border-color 0.2s, box-shadow 0.2s;
  cursor: pointer;

  &:hover,
  &.hovered {
    border-color: var(--primary-color, #1890ff);
    box-shadow: 0 4px 12px rgba(24, 144, 255, 0.15);
  }

  &.selected {
    border-color: var(--primary-color, #1890ff);
    box-shadow: 0 0 0 2px rgba(24, 144, 255, 0.2);
  }
}

.step-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.step-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--primary-color, #1890ff);
  color: #fff;
  font-size: 12px;
  font-weight: 600;
  flex-shrink: 0;
}

.step-name {
  flex: 1;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary, #262626);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.step-tool-icon {
  font-size: 14px;
  color: var(--primary-color, #1890ff);
  flex-shrink: 0;
}

.step-desc {
  margin-top: 6px;
  font-size: 11px;
  color: var(--text-secondary, #8c8c8c);
  line-height: 1.4;
}
</style>
