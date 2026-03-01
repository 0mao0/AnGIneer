<template>
  <div class="reference-viewer">
    <div class="reference-header">
      <h4>{{ reference.title }}</h4>
      <a-tag :color="getTypeColor(reference.type)">{{ getTypeLabel(reference.type) }}</a-tag>
    </div>

    <div class="reference-content">
      <div class="reference-text">{{ reference.content }}</div>
      
      <div v-if="reference.location" class="reference-location">
        <a-descriptions size="small" :column="1">
          <a-descriptions-item label="来源">{{ reference.source }}</a-descriptions-item>
          <a-descriptions-item v-if="reference.location.page" label="页码">
            {{ reference.location.page }}
          </a-descriptions-item>
          <a-descriptions-item v-if="reference.location.section" label="章节">
            {{ reference.location.section }}
          </a-descriptions-item>
        </a-descriptions>
      </div>
    </div>

    <div class="reference-actions">
      <a-space>
        <a-button size="small" @click="copyReference">
          <CopyOutlined /> 复制引用
        </a-button>
        <a-button size="small" @click="goToSource">
          <LinkOutlined /> 跳转原文
        </a-button>
      </a-space>
    </div>
  </div>
</template>

<script setup lang="ts">
import { message } from 'ant-design-vue'
import { CopyOutlined, LinkOutlined } from '@ant-design/icons-vue'
import type { Reference } from '../../types'

const props = defineProps<{
  reference: Reference
}>()

const emit = defineEmits<{
  goToSource: [reference: Reference]
}>()

const getTypeLabel = (type: string) => {
  const labels: Record<string, string> = {
    document: '文档',
    table: '表格',
    formula: '公式',
    figure: '图片'
  }
  return labels[type] || type
}

const getTypeColor = (type: string) => {
  const colors: Record<string, string> = {
    document: 'blue',
    table: 'green',
    formula: 'orange',
    figure: 'purple'
  }
  return colors[type] || 'default'
}

const copyReference = async () => {
  try {
    const text = `[${props.reference.title}](${props.reference.source})`
    await navigator.clipboard.writeText(text)
    message.success('已复制到剪贴板')
  } catch {
    message.error('复制失败')
  }
}

const goToSource = () => {
  emit('goToSource', props.reference)
}
</script>

<style lang="less" scoped>
.reference-viewer {
  padding: 12px;
  background: #f5f5f5;
  border-radius: 4px;
  border-left: 3px solid #1890ff;
}

.reference-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;

  h4 {
    margin: 0;
    font-size: 14px;
  }
}

.reference-content {
  margin-bottom: 12px;
}

.reference-text {
  font-size: 13px;
  line-height: 1.6;
  color: #333;
}

.reference-location {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid #e8e8e8;
}

.reference-actions {
  text-align: right;
}
</style>
