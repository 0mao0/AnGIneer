<template>
  <a-modal
    v-model:open="visible"
    title="导入测试集"
    :confirm-loading="uploading"
    @ok="handleUpload"
    @cancel="handleCancel"
  >
    <a-upload-dragger
      v-model:fileList="fileList"
      :before-upload="beforeUpload"
      :max-count="1"
      accept=".json"
    >
      <p class="ant-upload-drag-icon">
        <InboxOutlined />
      </p>
      <p class="ant-upload-text">点击或拖拽 JSON 文件到此处</p>
      <p class="ant-upload-hint">仅支持 .json 格式的评测题集文件</p>
    </a-upload-dragger>
  </a-modal>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { InboxOutlined } from '@ant-design/icons-vue'
import type { UploadFile } from 'ant-design-vue'

defineProps<{
  visible: boolean
}>()

const emit = defineEmits<{
  'update:visible': [val: boolean]
  uploaded: []
}>()

const fileList = ref<UploadFile[]>([])
const uploading = ref(false)

const beforeUpload = () => false

const handleUpload = async () => {
  if (!fileList.value.length) return
  uploading.value = true
  try {
    const formData = new FormData()
    formData.append('file', fileList.value[0] as any)
    const resp = await fetch('/api/evals/datasets/import', {
      method: 'POST',
      body: formData,
    })
    if (!resp.ok) {
      const err = await resp.json()
      throw new Error(err.detail || '导入失败')
    }
    fileList.value = []
    emit('update:visible', false)
    emit('uploaded')
  } catch (e: any) {
    console.error('导入失败:', e)
  } finally {
    uploading.value = false
  }
}

const handleCancel = () => {
  fileList.value = []
  emit('update:visible', false)
}
</script>
