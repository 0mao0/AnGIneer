<template>
  <a-modal
    :open="visible"
    title="批量上传文档"
    :width="640"
    :confirm-loading="parsingCount > 0"
    ok-text="开始解析"
    :ok-button-props="{ disabled: !canConfirm }"
    :cancel-button-props="{ disabled: busy }"
    @ok="handleConfirm"
    @cancel="handleCancel"
  >
    <a-upload-dragger
      v-model:fileList="fileList"
      multiple
      :before-upload="beforeUpload"
      :show-upload-list="false"
      accept=".pdf,.doc,.docx,.md,.txt"
      :disabled="parsingCount > 0"
    >
      <p class="ant-upload-drag-icon">
        <InboxOutlined />
      </p>
      <p class="ant-upload-text">点击或拖拽文件到此处</p>
      <p class="ant-upload-hint">支持 PDF / DOC / DOCX / MD / TXT，选择后立即上传到「{{ libraryTitle }}」，上传完成后点击「开始解析」</p>
    </a-upload-dragger>

    <div v-if="items.length" class="batch-upload-files">
      <div
        v-for="item in items"
        :key="item.uid"
        class="batch-upload-file"
        :class="`status-${item.status}`"
      >
        <span class="batch-upload-file-name" :title="item.name">
          <FileOutlined /> {{ item.name }}
        </span>
        <span class="batch-upload-file-size">{{ formatSize(item.size) }}</span>
        <span class="batch-upload-file-status">
          <template v-if="item.status === 'uploading'">
            <a-progress :percent="item.progress" size="small" :show-info="false" class="inline-progress" />
            <span class="status-text">{{ item.progress }}%</span>
          </template>
          <template v-else-if="item.status === 'uploaded'">
            <CheckCircleOutlined class="ok-icon" /> 已上传，待解析
          </template>
          <template v-else-if="item.status === 'parsing' || item.status === 'parsed'">
            <LoadingOutlined v-if="item.status === 'parsing'" spin class="parsing-icon" />
            <CheckCircleOutlined v-else class="ok-icon" />
            {{ item.status === 'parsing' ? '解析中…' : '解析已启动' }}
          </template>
          <template v-else>
            <CloseCircleOutlined class="err-icon" /> {{ item.error || '上传失败' }}
          </template>
        </span>
        <a-button
          v-if="item.status === 'error'"
          type="text"
          size="small"
          danger
          title="移除"
          @click="removeItem(item)"
        >
          <template #icon><CloseOutlined /></template>
        </a-button>
      </div>
    </div>
  </a-modal>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { message } from 'ant-design-vue'
import type { UploadFile } from 'ant-design-vue'
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  CloseOutlined,
  FileOutlined,
  InboxOutlined,
  LoadingOutlined,
} from '@ant-design/icons-vue'
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

interface UploadItem {
  uid: string
  name: string
  size: number
  status: 'uploading' | 'uploaded' | 'error' | 'parsing' | 'parsed'
  progress: number
  error?: string
  docId?: string
  filePath?: string
}

const libraryStore = useLibraryStore()
const libraryTitle = computed(() => libraryStore.currentLibraryTitle)

const fileList = ref<UploadFile[]>([])
const items = ref<UploadItem[]>([])

const busy = computed(() =>
  items.value.some((i) => i.status === 'uploading' || i.status === 'parsing')
)
const parsingCount = computed(() =>
  items.value.filter((i) => i.status === 'parsing').length
)
const canConfirm = computed(() =>
  items.value.some((i) => i.status === 'uploaded') && !busy.value
)

function beforeUpload(file: File) {
  // 选择即上传：不等待确认，行内显示进度
  const item: UploadItem = {
    uid: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    name: file.name,
    size: file.size,
    status: 'uploading',
    progress: 0,
  }
  items.value.push(item)
  void uploadFile(file, item)
  return false
}

async function uploadFile(file: File, item: UploadItem) {
  const libraryId = libraryStore.libraryId || 'default'
  try {
    const up = await knowledgeApi.uploadDocument(
      libraryId,
      file,
      undefined,
      (percent) => {
        item.progress = percent
      }
    ) as any
    const docId = up?.doc_id || up?.node?.id
    if (!docId) {
      throw new Error('上传响应缺少 doc_id')
    }
    item.docId = docId
    item.filePath = up?.file_path
    item.progress = 100
    item.status = 'uploaded'
    emit('uploaded')
  } catch (e: any) {
    item.status = 'error'
    item.error = e?.response?.data?.detail || e?.message || '上传失败'
  }
}

function removeItem(item: UploadItem) {
  items.value = items.value.filter((i) => i.uid !== item.uid)
}

async function handleConfirm() {
  const ready = items.value.filter((i) => i.status === 'uploaded')
  if (!ready.length || busy.value) return
  const libraryId = libraryStore.libraryId || 'default'
  const parseOptions = props.parseOptions || {}
  let failed = 0
  for (const item of ready) {
    item.status = 'parsing'
    try {
      await knowledgeApi.parseDocumentAsync(libraryId, item.docId!, item.filePath, parseOptions)
      item.status = 'parsed'
    } catch (e: any) {
      failed += 1
      item.status = 'error'
      item.error = e?.response?.data?.detail || e?.message || '解析启动失败'
    }
  }
  emit('uploaded')
  if (failed > 0) {
    message.error(`解析已启动 ${ready.length - failed} 个，${failed} 个失败`)
  } else {
    message.success(`已开始解析 ${ready.length} 个文件`)
  }
  fileList.value = []
  items.value = []
  emit('update:visible', false)
}

function handleCancel() {
  if (busy.value) return
  fileList.value = []
  items.value = []
  emit('update:visible', false)
}

function formatSize(bytes?: number): string {
  if (!bytes) return '-'
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  let size = bytes
  while (size >= 1000 && i < units.length - 1) { size /= 1024; i += 1 }
  return `${size.toFixed(1)} ${units[i]}`
}
</script>

<style scoped>
.batch-upload-files {
  margin-top: 12px;
  max-height: 260px;
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
.batch-upload-file-status {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  white-space: nowrap;
}
.inline-progress {
  width: 72px;
  margin: 0;
}
.status-text {
  min-width: 32px;
  color: var(--text-secondary, rgba(0, 0, 0, 0.45));
}
.ok-icon {
  color: var(--success-color, #52c41a);
}
.err-icon {
  color: var(--error-color, #ff4d4f);
}
.parsing-icon {
  color: var(--primary-color, #1677ff);
}
</style>
