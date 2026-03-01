<template>
  <div class="document-card" @click="handleClick">
    <a-card hoverable>
      <template #cover>
        <div class="card-cover">
          <FileTextOutlined style="font-size: 32px; color: #1890ff" />
        </div>
      </template>
      <a-card-meta :title="document.title" :description="document.description">
        <template #avatar>
          <a-avatar :style="{ backgroundColor: '#1890ff' }">
            {{ document.title?.charAt(0) }}
          </a-avatar>
        </template>
      </a-card-meta>
      <div class="card-footer">
        <a-tag v-if="document.category" size="small">{{ document.category }}</a-tag>
        <span class="update-time">{{ formatTime(document.updatedAt) }}</span>
      </div>
    </a-card>
  </div>
</template>

<script setup lang="ts">
import { FileTextOutlined } from '@ant-design/icons-vue'

interface Document {
  id: string
  title: string
  description?: string
  category?: string
  updatedAt?: string
}

const props = defineProps<{
  document: Document
}>()

const emit = defineEmits<{
  click: [document: Document]
}>()

const handleClick = () => {
  emit('click', props.document)
}

const formatTime = (time?: string) => {
  if (!time) return ''
  const date = new Date(time)
  return `${date.getMonth() + 1}/${date.getDate()}`
}
</script>

<style lang="less" scoped>
.document-card {
  cursor: pointer;

  .card-cover {
    height: 80px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: linear-gradient(135deg, #e6f7ff 0%, #f0f5ff 100%);
  }

  .card-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: 12px;
    padding-top: 12px;
    border-top: 1px solid #f0f0f0;

    .update-time {
      font-size: 12px;
      color: #999;
    }
  }
}
</style>
