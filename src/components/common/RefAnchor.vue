<template>
  <span class="ref-anchor" @click="handleClick">
    <a-tooltip :title="tooltip">
      <span class="anchor-content">
        <LinkOutlined />
        <slot>{{ displayText }}</slot>
      </span>
    </a-tooltip>
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { LinkOutlined } from '@ant-design/icons-vue'

const props = defineProps<{
  referenceId: string
  referenceType: 'document' | 'table' | 'formula' | 'figure'
  displayText?: string
  tooltip?: string
}>()

const emit = defineEmits<{
  click: [referenceId: string, referenceType: string]
}>()

const tooltip = computed(() => {
  return props.tooltip || `点击跳转到${getTypeLabel(props.referenceType)}`
})

const getTypeLabel = (type: string) => {
  const labels: Record<string, string> = {
    document: '文档',
    table: '表格',
    formula: '公式',
    figure: '图片'
  }
  return labels[type] || type
}

const handleClick = () => {
  emit('click', props.referenceId, props.referenceType)
}
</script>

<style lang="less" scoped>
.ref-anchor {
  display: inline;
}

.anchor-content {
  color: #1890ff;
  cursor: pointer;
  font-size: inherit;
  transition: color 0.2s;

  &:hover {
    color: #40a9ff;
    text-decoration: underline;
  }

  :deep(.anticon) {
    margin-right: 2px;
    font-size: 12px;
  }
}
</style>
