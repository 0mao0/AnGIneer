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
import type { UploadChangeParam } from 'ant-design-vue'

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
  const acceptedExts = props.accept
    .split(',')
    .map(ext => ext.trim().toLowerCase())
    .filter(Boolean)
  const lowerFileName = file.name.toLowerCase()
  const isAllowed = acceptedExts.length === 0 || acceptedExts.some(ext => lowerFileName.endsWith(ext))
  if (!isAllowed) {
    message.error(`只能上传 ${props.accept} 文件`)
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
  
  const originFile = info.file.originFileObj
  if (info.file.status === 'done') {
    if (originFile instanceof File) {
      emit('success', originFile, info.file.response)
    }
  } else if (info.file.status === 'error' && originFile instanceof File) {
    emit('error', originFile, info.file.error)
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
