<template>
  <a-modal
    :open="visible"
    title="批量上传文档"
    :width="640"
    :confirm-loading="uploading"
    ok-text="上传并解析"
    :ok-button-props="{ disabled: pendingFiles.length === 0 }"
    @ok="handleConfirm"
    @cancel="handleCancel"
  >
    <a-upload-dragger
      v-model:fileList="fileList"
      multiple
      :before-upload="beforeUpload"
      :show-upload-list="false"
      accept=".pdf,.doc,.docx,.md,.txt"
      :disabled="uploading"
    >
      <p class="ant-upload-drag-icon">
        <InboxOutlined />
      </p>
      <p class="ant-upload-text">点击或拖拽文件到此处</p>
      <p class="ant-upload-hint">支持 PDF / DOC / DOCX / MD / TXT，可多选批量上传到「{{ libraryTitle }}」根目录</p>
    </a-upload-dragger>

    <div v-if="pendingFiles.length" class="batch-upload-files">
      <div
        v-for="file in pendingFiles"
        :key="file.uid"
        class="batch-upload-file"
      >
        <span class="batch-upload-file-name" :title="file.name">
          <FileOutlined /> {{ file.name }}
        </span>
        <span class="batch-upload-file-size">{{ formatSize(file.size) }}</span>
        <a-button
          type="text"
          size="small"
          danger
          title="移除"
          :disabled="uploading"
          @click="removeFile(file)"
        >
          <template #icon><close-outlined /></template>
        </a-button>
      </div>
    </div>

    <div v-if="results.length" class="batch-upload-results">
      <div class="batch-upload-results-title">本次上传结果</div>
      <div
        v-for="(item, idx) in results"
        :key="idx"
        class="batch-upload-result"
        :class="{ 'is-success': item.ok, 'is-failed': !item.ok }"
      >
        <span class="batch-upload-result-name" :title="item.name">{{ item.name }}</span>
        <span class="batch-upload-result-status">
          <check-circle-outlined v-if="item.ok" />
          <close-circle-outlined v-else />
          {{ item.ok ? '上传并解析已启动' : item.error || '失败' }}
        </span>
      </div>
    </div>
  </a-modal>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { message } from 'ant-design-vue'
import type { UploadFile } from 'ant-design-vue'
import { InboxOutlined, FileOutlined, CloseOutlined, CheckCircleOutlined, CloseCircleOutlined } from '@ant-design/icons-vue'
import type { KnowledgeParseOptions } from '@angineer/docs-ui'
import { useLibraryStore } from '@/stores/library'
import { knowledgeApi } from '@/api/knowledge'

const props = defineProps<{
  visible: boolean
  parseOptions?: KnowledgeParseOptions
}>()

const emit = defineEmits<{
  (e: 'update:visible', val: boolean): void
  (e: 'uploaded'): void
}>()

const libraryStore = useLibraryStore()
const libraryTitle = computed(() => libraryStore.currentLibraryTitle)

const fileList = ref<UploadFile[]>([])
const uploading = ref(false)
const results = ref<{ name: string; ok: boolean; error?: string }[]>([])

const pendingFiles = computed(() =>
  fileList.value.filter(f => !(f as any).canceled)
)

function beforeUpload() {
  return false
}

function formatSize(bytes?: number): string {
  if (!bytes) return '-'
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  let size = bytes
  while (size >= 1000 && i < units.length - 1) { size /= 1024; i++ }
  return `${size.toFixed(1)} ${units[i]}`
}

function removeFile(file: UploadFile) {
  fileList.value = fileList.value.filter(f => f.uid !== file.uid)
}

async function handleConfirm() {
  if (!pendingFiles.value.length) return
  uploading.value = true
  results.value = []
  const libraryId = libraryStore.libraryId || 'default'
  const parseOptions = props.parseOptions || {}
  let failed = 0
  for (const file of fileList.value) {
    if ((file as any).canceled) continue
    const name = file.name
    try {
      const rawFile = (file as any).originFileObj || file
      const up = await knowledgeApi.uploadDocument(libraryId, rawFile) as any
      const docId = up?.doc_id || up?.node?.id
      if (!docId) {
        throw new Error('上传响应缺少 doc_id')
      }
      await knowledgeApi.parseDocumentAsync(libraryId, docId, up?.file_path, parseOptions)
      results.value.push({ name, ok: true })
    } catch (e: any) {
      failed++
      results.value.push({ name, ok: false, error: e?.response?.data?.detail || e?.message || '失败' })
    }
  }
  uploading.value = false
  if (failed > 0) {
    message.error(`完成：${results.value.length} 个文件，${failed} 个失败`)
  } else {
    message.success(`全部 ${results.value.length} 个文件已上传并开始解析`)
  }
  fileList.value = []
  emit('uploaded')
  emit('update:visible', false)
}

function handleCancel() {
  if (uploading.value) return
  fileList.value = []
  results.value = []
  emit('update:visible', false)
}
</script>

<style scoped>
.batch-upload-files {
  margin-top: 12px;
  max-height: 240px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.batch-upload-file {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  border: 1px solid var(--border-color, #f0f0f0);
  border-radius: 4px;
}
.batch-upload-file-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
}
.batch-upload-file-size {
  flex-shrink: 0;
  font-size: 12px;
  color: var(--text-secondary, rgba(0, 0, 0, 0.45));
}
.batch-upload-results {
  margin-top: 12px;
  max-height: 220px;
  overflow-y: auto;
}
.batch-upload-results-title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 6px;
}
.batch-upload-result {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 3px 8px;
  font-size: 13px;
}
.batch-upload-result-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.batch-upload-result-status {
  flex-shrink: 0;
  white-space: nowrap;
}
.is-success .batch-upload-result-status {
  color: var(--success-color, #52c41a);
}
.is-failed .batch-upload-result-status {
  color: var(--error-color, #ff4d4f);
}
</style>
