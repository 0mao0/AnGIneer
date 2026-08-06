<template>
  <div class="knowledge-stats" :class="appClass">
    <div class="stats-header">
      <div class="stats-title">历史记录<span class="stats-title-count">（{{ records.length }}条）</span></div>
      <div class="stats-actions">
        <a-popconfirm
          title="确定永久删除选中的记录？此操作不可恢复"
          @confirm="batchHardDelete"
        >
          <a-button
            v-show="selectedDeletedIds.length > 0"
            type="primary"
            danger
            size="small"
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
            <a-button
              v-if="record.status === 'failed' && record.error"
              type="text"
              size="small"
              class="error-detail-trigger"
              title="查看错误详情"
              @click="openErrorDetail(record)"
            >
              <template #icon><ExclamationCircleOutlined /></template>
            </a-button>
          </span>
        </template>
        <template v-if="column.key === 'action'">
          <span class="action-btns">
            <a-button type="link" size="small" @click="viewParseSteps(record)">过程</a-button>
            <a-divider type="vertical" />
            <a-button type="link" size="small" @click="viewDetail(record)">结果</a-button>
            <template v-if="record.status !== 'deleted'">
              <a-divider type="vertical" />
              <a-button
                v-if="RUNNING_STATUSES.has(record.status)"
                type="link"
                size="small"
                danger
                @click="stopTask(record)"
              >取消</a-button>
              <a-button v-else type="link" size="small" @click="restartTask(record)">解析</a-button>
            </template>
            <a-divider type="vertical" />
            <a-button type="link" size="small" danger @click="deleteRecord(record)">删除</a-button>
          </span>
        </template>
      </template>
    </a-table>

    <a-drawer
      v-model:open="stepsModalOpen"
      title="解析阶段"
      placement="right"
      :width="640"
      :footer="null"
    >
      <DocStageStepper
        v-if="currentStepDocId"
        :stages="currentStages"
        @retry="onRetryStage"
        @launch="onLaunchStage"
        @cancel="onCancelRunning"
      />
      <a-empty v-else description="暂无解析阶段记录" />
    </a-drawer>

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

    <a-modal
      v-model:open="errorDetailOpen"
      :title="errorDetailTitle"
      :width="720"
      :footer="null"
      destroy-on-close
    >
      <div class="error-detail-body">
        <pre>{{ errorDetailText }}</pre>
        <a-button type="link" size="small" @click="copyErrorDetail">
          <CopyOutlined /> 复制错误
        </a-button>
      </div>
    </a-modal>

    <a-modal
      v-model:open="adminDeleteModalOpen"
      :title="`再次确认删除「${adminDeleteFileName}」`"
      :width="520"
      ok-text="永久删除"
      ok-danger
      :ok-button-props="{ disabled: adminDeleteInput.trim() !== adminDeleteFileName.trim() }"
      @ok="confirmAdminDelete"
      @cancel="adminDeleteInput = ''"
    >
      <p class="admin-delete-warning">
        该文件用户尚未删除，本次为管理员强制删除，将同时移除知识库节点、文件内容与解析记录，此操作不可恢复。
      </p>
      <p>请输入完整文件名以确认：</p>
      <p class="admin-delete-filename">{{ adminDeleteFileName }}</p>
      <a-input
        v-model:value="adminDeleteInput"
        :placeholder="adminDeleteFileName"
        @pressEnter="confirmAdminDelete"
      />
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, computed, watch } from 'vue'
import dayjs from 'dayjs'
import { message, Modal } from 'ant-design-vue'
import { CopyOutlined, ExclamationCircleOutlined } from '@ant-design/icons-vue'
import { useTheme } from '@angineer/ui-kit'
import { knowledgeApi, type ParseRecordItem } from '@/api/knowledge'
import { PDFParsedWorkspace } from '@angineer/docs-ui'
import type { KnowledgeTreeNode } from '@angineer/docs-ui'
import DocStageStepper from '@/components/DocStageStepper.vue'

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
const stepsModalOpen = ref(false)
const currentStepDocId = ref('')
const currentStepTaskId = ref('')
const currentStages = ref<any[]>([])
const errorDetailOpen = ref(false)
const errorDetailTitle = ref('')
const errorDetailText = ref('')
const adminDeleteModalOpen = ref(false)
const adminDeleteDocId = ref('')
const adminDeleteRecordId = ref(0)
const adminDeleteFileName = ref('')
const adminDeleteInput = ref('')

// 列表轮询：存在进行中记录时持续静默刷新，全部终态后停止
let recordsPollTimer: number | null = null
const RUNNING_STATUSES = new Set(['queued', 'pending', 'processing'])

function hasRunningRecords(): boolean {
  return records.value.some(r => RUNNING_STATUSES.has(r.status))
}

function stopRecordsPolling() {
  if (recordsPollTimer !== null) {
    window.clearInterval(recordsPollTimer)
    recordsPollTimer = null
  }
}

function syncRecordsPolling() {
  if (hasRunningRecords()) {
    if (recordsPollTimer === null) {
      recordsPollTimer = window.setInterval(async () => {
        await loadRecords(true)
      }, 2000)
    }
  } else {
    stopRecordsPolling()
  }
}

const viewerParseButtonText = computed(() => {
  const status = viewerNode.value?.status
  if (status === 'completed' || status === 'failed' || status === 'cancelled' || status === 'partial') return '重新解析'
  if (status === 'processing') return '解析中...'
  return '开始解析'
})

const columns = [
  { title: '上传人员', dataIndex: 'uploaded_by', key: 'uploaded_by', width: 80 },
  { title: 'API', dataIndex: 'api_key_name', key: 'api_key_name', width: 65, ellipsis: true },
  { title: '文件名称', dataIndex: 'file_name', key: 'file_name', ellipsis: true },
  { title: '格式', dataIndex: 'file_format', key: 'file_format', width: 60 },
  { title: '大小', key: 'file_size', width: 80 },
  { title: '解析状态', key: 'status', width: 80 },
  { title: '上传时间', dataIndex: 'created_at', key: 'created_at', width: 140 },
  { title: '操作', key: 'action', width: 220, fixed: 'right' as const },
]

const rowSelection = computed(() => ({
  selectedRowKeys: selectedRowKeys.value,
  onChange: (keys: number[]) => { selectedRowKeys.value = keys },
  getCheckboxProps: (record: ParseRecordItem) => ({
    disabled: record.file_status === '已入库',
  }),
}))

const selectedDeletedIds = computed(() =>
  selectedRowKeys.value.filter(id =>
    records.value.find(r => r.id === id)?.file_status !== '已入库'
  )
)

function formatTime(iso: string): string {
  if (!iso) return '-'
  return dayjs(iso).format('YYYY-MM-DD HH:mm')
}

function openErrorDetail(record: ParseRecordItem) {
  errorDetailTitle.value = record.file_name || `解析错误 (${record.id})`
  errorDetailText.value = record.error || ''
  errorDetailOpen.value = true
}

async function copyErrorDetail() {
  try {
    await navigator.clipboard.writeText(errorDetailText.value)
    message.success('已复制')
  } catch {
    message.error('复制失败')
  }
}

function formatFileSize(bytes: number): string {
  if (!bytes) return '-'
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  let size = bytes
  while (size >= 1000 && i < units.length - 1) { size /= 1024; i++ }
  return `${size.toFixed(1)} ${units[i]}`
}

function statusColor(status: string): string {
  const map: Record<string, string> = {
    completed: 'green',
    processing: 'blue',
    queued: 'orange',
    pending: 'orange',
    partial: 'orange',
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
    partial: '部分完成',
    failed: '失败',
    cancelled: '已取消',
    deleted: '用户已删',
  }
  return map[status] || status
}

async function loadRecords(silent = false) {
  if (!silent) loading.value = true
  try {
    const res = await knowledgeApi.listRecords({ show_deleted: showDeletedOnly.value })
    records.value = res.data
  } catch (e: any) {
    if (!silent) message.error('加载记录失败: ' + (e.message || e))
  } finally {
    loading.value = false
    syncRecordsPolling()
  }
}

function toggleDeletedFilter(checked: boolean) {
  showDeletedOnly.value = checked
  loadRecords()
}

async function stopTask(record: ParseRecordItem) {
  try {
    const res = await knowledgeApi.cancelParseTask(record.task_id) as any
    message.success(res?.message || '已取消')
    await loadRecords()
  } catch (e: any) {
    message.error('取消失败: ' + (e.message || e))
  }
}

async function restartTask(record: ParseRecordItem) {
  try {
    await knowledgeApi.retryParseTask(record.doc_id)
    message.success('已开始解析')
    // 清空阶段抽屉的旧状态（含子阶段/文件核查），避免展示上一次解析的残留
    currentStages.value = []
    await loadRecords()
  } catch (e: any) {
    message.error('解析失败: ' + (e.message || e))
  }
}

async function viewParseSteps(record: ParseRecordItem) {
  stepsModalOpen.value = true
  currentStepDocId.value = record.doc_id
  currentStepTaskId.value = record.task_id || ''
  await loadDocStages(record.doc_id)
}

// 抽屉打开期间持续轮询阶段状态（1s），关闭才停止
let stagesPollTimer: number | null = null

function startStagesPolling() {
  if (stagesPollTimer !== null) return
  stagesPollTimer = window.setInterval(async () => {
    if (!currentStepDocId.value) return
    await loadDocStages(currentStepDocId.value)
  }, 1000)
}

function stopStagesPolling() {
  if (stagesPollTimer !== null) {
    window.clearInterval(stagesPollTimer)
    stagesPollTimer = null
  }
}

watch(stepsModalOpen, (open) => {
  if (open) startStagesPolling()
  else stopStagesPolling()
})

onBeforeUnmount(() => {
  stopStagesPolling()
  stopRecordsPolling()
})

async function loadDocStages(docId: string) {
  try {
    const res = await knowledgeApi.getDocStages(docId) as any
    currentStages.value = (res as any).stages || []
  } catch {
    currentStages.value = []
  }
}

async function onRetryStage(stageKey: string) {
  if (!currentStepDocId.value) return
  try {
    await knowledgeApi.retryDocStage(currentStepDocId.value, stageKey)
    startStagesPolling()
    await loadDocStages(currentStepDocId.value)
  } catch (e: any) {
    message.error(`重试失败: ${e?.response?.data?.detail || e?.message}`)
  }
}

async function onLaunchStage(stageKey: string) {
  if (!currentStepDocId.value) return
  try {
    await knowledgeApi.retryDocStage(currentStepDocId.value, stageKey)
    startStagesPolling()
    await loadDocStages(currentStepDocId.value)
  } catch (e: any) {
    message.error(`启动失败: ${e?.response?.data?.detail || e?.message}`)
  }
}

async function onCancelRunning() {
  if (!currentStepTaskId.value) {
    message.warning('没有正在运行的任务')
    return
  }
  try {
    await knowledgeApi.cancelParseTask(currentStepTaskId.value)
    message.success('已取消当前任务')
    setTimeout(() => loadDocStages(currentStepDocId.value || ''), 1000)
  } catch (e: any) {
    message.error(`取消失败: ${e?.response?.data?.detail || e?.message}`)
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
    await knowledgeApi.retryParseTask(viewerNode.value.key)
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

async function deleteRecord(record: ParseRecordItem) {
  if (record.file_status === '用户已删') {
    Modal.confirm({
      title: '确认删除',
      content: `确定要彻底删除「${record.file_name}」的解析记录吗？此操作不可恢复。`,
      okText: '删除',
      okType: 'danger',
      cancelText: '取消',
      async onOk() {
        try {
          await knowledgeApi.deleteNode(record.doc_id)
          await knowledgeApi.hardDeleteRecord(record.id)
          message.success('已删除')
          await loadRecords()
        } catch (e: any) {
          message.error('删除失败: ' + (e?.response?.data?.detail || e?.message || e))
        }
      }
    })
    return
  }
  // 用户尚未删除：两次弹框，第二次需输入完整文件名才能永久删除
  Modal.confirm({
    title: '确认删除（危险操作）',
    content: `「${record.file_name}」是用户尚未删除的文件。删除将同时移除知识库节点、文件内容与解析记录（可能包含隐私数据），此操作不可恢复。`,
    okText: '继续',
    okType: 'danger',
    cancelText: '取消',
    onOk() {
      adminDeleteDocId.value = record.doc_id
      adminDeleteRecordId.value = record.id
      adminDeleteFileName.value = record.file_name
      adminDeleteInput.value = ''
      adminDeleteModalOpen.value = true
    }
  })
}

async function confirmAdminDelete() {
  if (adminDeleteInput.value.trim() !== adminDeleteFileName.value.trim()) return
  try {
    await knowledgeApi.deleteNode(adminDeleteDocId.value)
    await knowledgeApi.hardDeleteRecord(adminDeleteRecordId.value)
    message.success('已删除')
    adminDeleteModalOpen.value = false
    adminDeleteInput.value = ''
    await loadRecords()
  } catch (e: any) {
    message.error('删除失败: ' + (e?.response?.data?.detail || e?.message || e))
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

onMounted(() => {
  loadRecords()
})
</script>

<style lang="less" scoped>
.knowledge-stats {
  height: 100%;
  padding: 16px 16px 24px;
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
}
.stats-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
}
.stats-title-count {
  font-size: 12px;
  font-weight: 400;
  color: var(--text-secondary);
}
.stats-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
:deep(.ant-table) {
  th, td { text-align: center !important; }
}
.action-btns {
  white-space: nowrap;
  :deep(.ant-btn) {
    padding-inline: 0;
    margin-inline: 2px;
  }
  :deep(.ant-divider-vertical) {
    margin-inline: 2px;
  }
}
.error-detail-trigger {
  padding: 0 4px;
  height: auto;
}
.error-detail-body {
  pre {
    white-space: pre-wrap;
    word-break: break-all;
    font-size: 12px;
    line-height: 1.5;
    max-height: 60vh;
    overflow-y: auto;
    margin-bottom: 8px;
    padding: 8px 10px;
    background: #fafafa;
    border: 1px solid #f0f0f0;
    border-radius: 4px;
  }
}
.admin-delete-warning {
  color: var(--error-color, #ff4d4f);
  margin-bottom: 12px;
}
.admin-delete-filename {
  font-weight: 600;
  word-break: break-all;
  margin-bottom: 8px;
}
</style>
