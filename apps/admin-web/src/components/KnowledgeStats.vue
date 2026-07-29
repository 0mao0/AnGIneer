<template>
  <div class="knowledge-stats" :class="appClass">
    <div class="stats-header">
      <h2>解析记录统计</h2>
      <div class="stats-actions">
        <a-popconfirm
          title="将知识库中已删除的文档对应的解析记录标记为可删除状态"
          @confirm="cleanOrphaned"
        >
          <a-button type="default" size="small">清理孤立记录</a-button>
        </a-popconfirm>
        <a-popconfirm
          title="确定永久删除选中的记录？此操作不可恢复"
          @confirm="batchHardDelete"
        >
          <a-button
            type="primary"
            danger
            size="small"
            :disabled="selectedDeletedIds.length === 0"
          >
            批量删除 ({{ selectedDeletedIds.length }})
          </a-button>
        </a-popconfirm>
        <a-switch
          :checked="showDeletedOnly"
          size="small"
          @change="toggleDeletedFilter"
        />
        <span style="margin-left: 4px; font-size: 13px; color: var(--text-secondary);">仅显示已删除</span>
      </div>
    </div>

    <a-table
      :columns="columns"
      :data-source="records"
      :loading="loading"
      :row-selection="rowSelection"
      row-key="id"
      size="middle"
      :pagination="{ pageSize: 20, showSizeChanger: true, showTotal: (total: number) => `共 ${total} 条` }"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'api_key_name'">
          {{ record.api_key_name || '内部' }}
        </template>
        <template v-if="column.key === 'file_size'">
          {{ formatFileSize(record.file_size) }}
        </template>
        <template v-if="column.key === 'created_at'">
          {{ formatTime(record.created_at) }}
        </template>
        <template v-if="column.key === 'status'">
          <span style="display: inline-flex; align-items: center;">
            <a-tag :color="statusColor(record.status)">
              {{ statusLabel(record.status) }}
            </a-tag>
            <a-tooltip v-if="record.status === 'failed' && record.error" :title="record.error">
              <ExclamationCircleOutlined style="color: #ff4d4f; cursor: help; font-size: 14px;" />
            </a-tooltip>
          </span>
        </template>
        <template v-if="column.key === 'action'">
          <!-- 待解析/排队中：查看 + 解析 -->
          <template v-if="record.status === 'pending' || record.status === 'queued'">
            <a-button type="link" size="small" @click="viewDetail(record)">查看</a-button>
            <a-divider type="vertical" />
            <a-button type="link" size="small" @click="parseTask(record)">解析</a-button>
          </template>
          <!-- 进行中：查看 + 停止 -->
          <template v-else-if="record.status === 'processing'">
            <a-button type="link" size="small" @click="viewDetail(record)">查看</a-button>
            <a-divider type="vertical" />
            <a-popconfirm title="确定停止当前解析任务？" @confirm="stopTask(record)">
              <a-button type="link" size="small">停止</a-button>
            </a-popconfirm>
          </template>
          <!-- 完成：查看 -->
          <template v-else-if="record.status === 'completed'">
            <a-button type="link" size="small" @click="viewDetail(record)">查看</a-button>
          </template>
          <!-- 失败/已取消：查看 + 重启 -->
          <template v-else-if="record.status === 'failed' || record.status === 'cancelled'">
            <a-button type="link" size="small" @click="viewDetail(record)">查看</a-button>
            <a-divider type="vertical" />
            <a-button type="link" size="small" @click="restartTask(record)">重启</a-button>
          </template>
          <!-- 已删除：查看 + 退回 + 删除 -->
          <template v-else-if="record.status === 'deleted'">
            <a-button type="link" size="small" @click="viewDetail(record)">查看</a-button>
            <a-divider type="vertical" />
            <a-button type="link" size="small" @click="restoreRecord(record.id)">退回</a-button>
            <a-divider type="vertical" />
            <a-popconfirm title="确定永久删除此记录？" @confirm="hardDelete(record.id)">
              <a-button type="link" danger size="small">删除</a-button>
            </a-popconfirm>
          </template>
        </template>
      </template>
    </a-table>

    <a-drawer
      v-model:open="viewerOpen"
      placement="right"
      :width="'85vw'"
      :footer="null"
      @close="onViewerClose"
    >
      <template #title>
        <span>{{ viewerTitle }}</span>
        <template v-if="viewerNode?.status === 'processing'">
          <a-popconfirm title="确定停止解析？" @confirm="onViewerStop">
            <a-button size="small" danger style="margin-left: 12px;">
              <template #icon><ExclamationCircleOutlined /></template>
              停止
            </a-button>
          </a-popconfirm>
        </template>
        <a-button
          v-else
          size="small"
          type="primary"
          @click="onViewerParse"
          style="margin-left: 12px;"
        >
          {{ viewerParseButtonText }}
        </a-button>
      </template>
      <PDFParsedWorkspace
        v-if="viewerNode"
        :node="viewerNode"
        :content="viewerContent"
        :structured-items="viewerStructuredItems"
        :graph-data="viewerGraphData"
        :render-pdf-path="viewerRenderPdfPath"
      />
    </a-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import dayjs from 'dayjs'
import { message } from 'ant-design-vue'
import { ExclamationCircleOutlined } from '@ant-design/icons-vue'
import { useTheme } from '@angineer/ui-kit'
import { knowledgeApi, type ParseRecordItem } from '@/api/knowledge'
import { PDFParsedWorkspace } from '@angineer/docs-ui'
import type { KnowledgeTreeNode } from '@angineer/docs-ui'

const { appClass } = useTheme()

const records = ref<ParseRecordItem[]>([])
const loading = ref(false)
const showDeletedOnly = ref(false)
const selectedRowKeys = ref<number[]>([])

const viewerOpen = ref(false)
const viewerTitle = ref('')
const viewerNode = ref<KnowledgeTreeNode | null>(null)
const viewerContent = ref('')
const viewerStructuredItems = ref([])
const viewerGraphData = ref<{ nodes: any[]; edges: any[] } | null>(null)
const viewerRenderPdfPath = ref('')
const viewerParseButtonText = computed(() => {
  const status = viewerNode.value?.status
  if (status === 'completed' || status === 'failed' || status === 'cancelled') return '重新解析'
  if (status === 'processing') return '解析中...'
  return '开始解析'
})

const columns = [
  { title: '上传人员', dataIndex: 'uploaded_by', key: 'uploaded_by', width: 110 },
  { title: 'API', dataIndex: 'api_key_name', key: 'api_key_name', width: 140, ellipsis: true },
  { title: '上传文件', dataIndex: 'file_name', key: 'file_name', ellipsis: true },
  { title: '格式', dataIndex: 'file_format', key: 'file_format', width: 70 },
  { title: '大小', key: 'file_size', width: 90 },
  { title: '状态', key: 'status', width: 90 },
  { title: '上传时间', dataIndex: 'created_at', key: 'created_at', width: 150 },
  { title: '操作', key: 'action', width: 220, fixed: 'right' as const },
]

const rowSelection = computed(() => ({
  selectedRowKeys: selectedRowKeys.value,
  onChange: (keys: number[]) => { selectedRowKeys.value = keys },
  getCheckboxProps: (record: ParseRecordItem) => ({
    disabled: record.status !== 'deleted',
  }),
}))

const selectedDeletedIds = computed(() =>
  selectedRowKeys.value.filter(id =>
    records.value.find(r => r.id === id)?.status === 'deleted'
  )
)

function formatTime(iso: string): string {
  if (!iso) return '-'
  return dayjs(iso).format('YYYY-MM-DD HH:mm')
}

function formatFileSize(bytes: number): string {
  if (!bytes) return '-'
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  let size = bytes
  while (size >= 1024 && i < units.length - 1) { size /= 1024; i++ }
  return `${size.toFixed(1)} ${units[i]}`
}

function statusColor(status: string): string {
  const map: Record<string, string> = {
    completed: 'green',
    processing: 'blue',
    queued: 'orange',
    pending: 'orange',
    failed: 'red',
    cancelled: 'default',
    deleted: '#999',
  }
  return map[status] || 'default'
}

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    completed: '完成',
    processing: '进行中',
    queued: '排队中',
    pending: '待解析',
    failed: '失败',
    cancelled: '已取消',
    deleted: '已删除',
  }
  return map[status] || status
}

async function loadRecords() {
  loading.value = true
  try {
    const res = await knowledgeApi.listRecords({ show_deleted: showDeletedOnly.value })
    records.value = res.data
  } catch (e: any) {
    message.error('加载记录失败: ' + (e.message || e))
  } finally {
    loading.value = false
  }
}

function toggleDeletedFilter(checked: boolean) {
  showDeletedOnly.value = checked
  loadRecords()
}

async function stopTask(record: ParseRecordItem) {
  try {
    const res = await knowledgeApi.cancelParseTask(record.task_id) as any
    message.success(res?.message || '已停止')
    await loadRecords()
  } catch (e: any) {
    message.error('停止失败: ' + (e.message || e))
  }
}

async function restartTask(record: ParseRecordItem) {
  try {
    await knowledgeApi.retryParseTask(record.doc_id)
    message.success('已重启')
    await loadRecords()
  } catch (e: any) {
    message.error('重启失败: ' + (e.message || e))
  }
}

function viewDetail(record: ParseRecordItem) {
  viewerTitle.value = record.file_name || record.doc_id
  viewerNode.value = {
    key: record.doc_id,
    title: record.file_name || record.doc_id,
    status: record.status,
    filePath: '',
    isFolder: false,
    parseProgress: record.status === 'processing' ? 50 : 0,
    parseStage: record.status === 'processing' ? 'processing' : '',
    parseError: record.error || '',
    parseTaskId: record.task_id || '',
    visible: true,
  } as unknown as KnowledgeTreeNode
  viewerOpen.value = true
  loadViewerData(record.doc_id)
}

function onViewerClose() {
  viewerNode.value = null
  viewerContent.value = ''
  viewerStructuredItems.value = []
  viewerGraphData.value = null
  viewerRenderPdfPath.value = ''
}

async function loadViewerData(docId: string) {
  try {
    const res = await knowledgeApi.getDocument('default', docId) as any
    viewerContent.value = res?.content || ''
    viewerRenderPdfPath.value = res?.storage?.render_pdf || ''
  } catch {
    viewerContent.value = '暂无内容'
  }
  try {
    const stats = await knowledgeApi.getStructuredIndex(docId, 'doc_blocks_graph_v1') as any
    viewerStructuredItems.value = stats?.items || []
  } catch {
    viewerStructuredItems.value = []
  }
  try {
    const graph = await knowledgeApi.getDocBlocksGraph('default', docId) as any
    viewerGraphData.value = graph?.data || null
  } catch {
    viewerGraphData.value = null
  }
}

async function onViewerParse() {
  if (!viewerNode.value) return
  try {
    const result = await knowledgeApi.retryParseTask(viewerNode.value.key) as any
    viewerNode.value.status = 'processing'
    viewerNode.value.parseError = ''
    viewerNode.value.parseStage = 'queued'
    message.success('已开始解析')
  } catch (e: any) {
    message.error('解析失败: ' + (e.message || e))
  }
}

async function onViewerStop() {
  if (!viewerNode.value || !viewerNode.value.parseTaskId) return
  try {
    const res = await knowledgeApi.cancelParseTask(viewerNode.value.parseTaskId) as any
    viewerNode.value.status = 'cancelled'
    viewerNode.value.parseStage = 'cancelled'
    message.success(res?.message || '已停止')
    await loadRecords()
  } catch (e: any) {
    message.error('停止失败: ' + (e.message || e))
  }
}

async function hardDelete(recordId: number) {
  try {
    await knowledgeApi.hardDeleteRecord(recordId)
    message.success('已永久删除')
    await loadRecords()
  } catch (e: any) {
    message.error('删除失败: ' + (e.message || e))
  }
}

async function cleanOrphaned() {
  try {
    const res = await knowledgeApi.cleanOrphanedRecords()
    message.success(res.message)
    await loadRecords()
  } catch (e: any) {
    message.error('清理失败: ' + (e.message || e))
  }
}

async function parseTask(record: ParseRecordItem) {
  try {
    const result = await knowledgeApi.retryParseTask(record.doc_id) as any
    message.success('已开始解析')
    await loadRecords()
  } catch (e: any) {
    message.error('解析失败: ' + (e.message || e))
  }
}

async function restoreRecord(recordId: number) {
  try {
    const res = await knowledgeApi.restoreRecord(recordId)
    message.success(res.message)
    await loadRecords()
  } catch (e: any) {
    message.error('退回失败: ' + (e.message || e))
  }
}

async function batchHardDelete() {
  try {
    for (const id of selectedDeletedIds.value) {
      await knowledgeApi.hardDeleteRecord(id)
    }
    message.success(`已删除 ${selectedDeletedIds.value.length} 条记录`)
    selectedRowKeys.value = []
    await loadRecords()
  } catch (e: any) {
    message.error('批量删除失败: ' + (e.message || e))
  }
}

async function purgeAllDeleted() {
  try {
    const res = await knowledgeApi.purgeAllDeleted()
    message.success(res.message)
    await loadRecords()
  } catch (e: any) {
    message.error('清除失败: ' + (e.message || e))
  }
}

onMounted(() => {
  loadRecords()
})
</script>

<style lang="less" scoped>
.knowledge-stats {
  height: 100%;
  padding: 24px;
  background: var(--bg-primary);
  overflow-y: auto;
}
.stats-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  flex-wrap: wrap;
  gap: 8px;
  h2 {
    margin: 0;
    font-size: 18px;
    color: var(--text-primary);
  }
}
.stats-actions {
  display: flex;
  gap: 8px;
}
:deep(.ant-table) {
  th, td { text-align: center !important; }
}
</style>
