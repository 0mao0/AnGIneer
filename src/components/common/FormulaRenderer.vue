<template>
  <div class="formula-renderer">
    <div class="formula-box" @click="handleClick">
      <div class="formula-content" v-html="renderedExpression" />
      <div v-if="showCopy" class="formula-actions">
        <a-button size="small" type="text" @click.stop="copyFormula">
          <CopyOutlined />
        </a-button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { message } from 'ant-design-vue'
import { CopyOutlined } from '@ant-design/icons-vue'

const props = withDefaults(defineProps<{
  expression: string
  showCopy?: boolean
}>(), {
  showCopy: true
})

const emit = defineEmits<{
  click: []
}>()

const renderedExpression = computed(() => {
  return props.expression
    .replace(/D₀/g, 'D<sub>0</sub>')
    .replace(/Z₀/g, 'Z<sub>0</sub>')
    .replace(/Z₁/g, 'Z<sub>1</sub>')
    .replace(/Z₂/g, 'Z<sub>2</sub>')
    .replace(/Z₃/g, 'Z<sub>3</sub>')
    .replace(/\+/g, ' + ')
    .replace(/=/g, ' = ')
})

const handleClick = () => {
  emit('click')
}

const copyFormula = async () => {
  try {
    await navigator.clipboard.writeText(props.expression)
    message.success('已复制公式')
  } catch {
    message.error('复制失败')
  }
}
</script>

<style lang="less" scoped>
.formula-renderer {
  display: inline-block;
}

.formula-box {
  display: inline-flex;
  align-items: center;
  background: #f5f5f5;
  padding: 8px 16px;
  border-radius: 4px;
  cursor: pointer;
  transition: background 0.2s;

  &:hover {
    background: #e6f7ff;
  }
}

.formula-content {
  font-family: 'Times New Roman', serif;
  font-size: 16px;
  line-height: 1.6;
  color: #1890ff;

  :deep(sub) {
    font-size: 12px;
  }
}

.formula-actions {
  margin-left: 8px;
}
</style>
