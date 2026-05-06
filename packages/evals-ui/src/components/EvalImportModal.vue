<template>
  <a-modal
    :open="visible"
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
import { message } from 'ant-design-vue'
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
    const file = fileList.value[0] as any
    const formData = new FormData()
    formData.append('file', file.originFileObj || file)
    const resp = await fetch('/api/evals/datasets/import', {
      method: 'POST',
      body: formData,
    })
    const result = await resp.json().catch(() => ({}))
    if (!resp.ok) {
      const errMsg = result.detail || result.message || JSON.stringify(result) || `请求失败 (${resp.status})`
      throw new Error(errMsg)
    }
    fileList.value = []
    emit('update:visible', false)
    emit('uploaded')
    message.success('导入成功')
  } catch (e: any) {
    const errMsg = e?.message || '导入失败，请检查文件格式'
    message.error(errMsg)
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
