<template>
  <div class="document-uploader">
    <a-upload-dragger
      v-model:fileList="fileList"
      name="file"
      :multiple="multiple"
      :accept="accept"
      :before-upload="handleBeforeUpload"
      @change="handleChange"
    >
      <p class="ant-upload-drag-icon">
        <InboxOutlined />
      </p>
      <p class="ant-upload-text">{{ text || '点击或拖拽文件到此区域' }}</p>
      <p class="ant-upload-hint">{{ hint || '支持 PDF 文件上传' }}</p>
    </a-upload-dragger>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { message } from 'ant-design-vue'
import { InboxOutlined } from '@ant-design/icons-vue'
import type { UploadChangeParam, UploadProps } from 'ant-design-vue'

interface Props {
  multiple?: boolean
  accept?: string
  maxSize?: number
  text?: string
  hint?: string
}

const props = withDefaults(defineProps<Props>(), {
  multiple: true,
  accept: '.pdf',
  maxSize: 50,
  text: '',
  hint: ''
})

const emit = defineEmits<{
  change: [files: File[]]
  success: [file: File, response: any]
  error: [file: File, error: any]
}>()

const fileList = ref<any[]>([])

const handleBeforeUpload = (file: File) => {
  const isPdf = file.type === 'application/pdf' || file.name.endsWith('.pdf')
  if (!isPdf) {
    message.error('只能上传 PDF 文件')
    return false
  }
  
  const isLtMaxSize = file.size / 1024 / 1024 < props.maxSize
  if (!isLtMaxSize) {
    message.error(`文件大小不能超过 ${props.maxSize}MB`)
    return false
  }
  
  return false
}

const handleChange = (info: UploadChangeParam) => {
  const files = info.fileList
    .filter(f => f.status !== 'removed')
    .map(f => f.originFileObj || f)
    .filter(f => f instanceof File) as File[]
  
  emit('change', files)
  
  if (info.file.status === 'done') {
    emit('success', info.file.originFileObj, info.file.response)
  } else if (info.file.status === 'error') {
    emit('error', info.file.originFileObj, info.file.error)
  }
}
</script>

<style lang="less" scoped>
.document-uploader {
  :deep(.ant-upload-drag) {
    padding: 20px;
  }
}
</style>
