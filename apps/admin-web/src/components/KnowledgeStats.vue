<template>
  <div class="knowledge-stats" :class="appClass">
    <div class="stats-header">
      <div class="stats-title-wrap">
        <div class="stats-title">历史记录<span class="stats-title-count">（{{ records.length }}条）</span></div>
        <a-switch
          :checked="showDeletedOnly"
          size="small"
          @change="toggleDeletedFilter"
        />
        <span class="stats-deleted-label">用户已删</span>
      </div>
      <div class="stats-actions">
        <a-input-group compact class="library-review-group">
          <LibrarySelect hide-actions style="min-width: 160px" />
          <a-button
            class="library-review-btn"
            size="small"
            title="审核当前知识库的实体抽取结果"
            @click="entityReviewOpen = true"
          >
            实体审核
          </a-button>
        </a-input-group>
        <a-button
          v-show="selectedRowKeys.length > 0"
          type="primary"
          danger
          size="small"
          @click="onBatchDeleteClick"
        >
          批量删除 ({{ selectedRowKeys.length }})
        </a-button>
      </div>
    </div>

    <div ref="tableWrapRef" class="stats-table-wrap">
    <a-table
      :columns="columns"
      :data-source="records"
      :loading="loading"
      :row-selection="rowSelection"
      :scroll="{ x: scrollX }"
      row-key="id"
      size="middle"
      :pagination="{ pageSize: 20, showSizeChanger: true, showTotal: (total: number) => `共 ${total} 条` }"
    >
      <template #headerCell="{ column, title }">
        <div class="resizable-th">
          <span class="resizable-th-title">{{ title }}</span>
          <span
            v-if="column.title"
            class="resizable-th-handle"
            title="拖动调整列宽"
            @mousedown.prevent="onResizeStart($event, column)"
          />
        </div>
      </template>
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'file_size'">
          {{ formatFileSize(record.file_size) }}
        </template>
        <template v-if="column.key === 'page_count'">
          {{ record.page_count ? `${record.page_count} 页` : '-' }}
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
            <a-button type="link" size="small" @click="viewDetail(record)">结果</a-button>
            <template v-if="record.status !== 'deleted'">
              <a-button
                v-if="RUNNING_STATUSES.has(record.status)"
                type="link"
                size="small"
                danger
                @click="stopTask(record)"
              >取消</a-button>
              <a-button v-else type="link" size="small" @click="restartTask(record)">解析</a-button>
            </template>
            <a-button type="link" size="small" danger @click="deleteRecord(record)">删除</a-button>
            <a-button type="link" size="small" :loading="downloadingId === record.id" @click="downloadRecordFiles(record)">下载</a-button>
          </span>
        </template>
      </template>
    </a-table>
    </div>

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
        ref="docParsedWorkspaceRef"
        :node="viewerNode"
        :content="viewerContent"
        :structured-items="viewerStructuredItems"
        :graph-data="viewerGraphData"
        :render-pdf-path="viewerRenderPdfPath"
        :dark="isDark"
        :side-panel-default-open="false"
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
      <a-input-group compact class="admin-delete-fill-group">
        <a-input
          v-model:value="adminDeleteInput"
          :placeholder="adminDeleteFileName"
          class="admin-delete-fill-input"
          @pressEnter="confirmAdminDelete"
        />
        <a-button
          class="admin-delete-fill-btn"
          title="点击自动填入完整文件名，再次确认后即可删除"
          @click="adminDeleteInput = adminDeleteFileName"
        >
          一键填入
        </a-button>
      </a-input-group>
    </a-modal>

    <a-modal
      v-model:open="batchAdminModalOpen"
      :title="`再次确认批量删除（${selectedRowKeys.length} 条）`"
      :width="560"
      ok-text="永久删除"
      ok-danger
      :ok-button-props="{ disabled: batchAdminInput.trim() !== BATCH_DELETE_CONFIRM_SENTENCE }"
      @ok="batchHardDelete"
      @cancel="batchAdminInput = ''"
    >
      <p class="admin-delete-warning">
        选中记录中包含用户尚未删除的文件。删除将同时移除知识库节点、文件内容与解析记录（可能包含隐私数据），此操作不可恢复。
      </p>
      <p>请输入以下确认句以继续：</p>
      <p class="admin-delete-filename">{{ BATCH_DELETE_CONFIRM_SENTENCE }}</p>
      <a-input-group compact class="admin-delete-fill-group">
        <a-input
          v-model:value="batchAdminInput"
          :placeholder="BATCH_DELETE_CONFIRM_SENTENCE"
          class="admin-delete-fill-input"
          @pressEnter="batchAdminInput.trim() === BATCH_DELETE_CONFIRM_SENTENCE && batchHardDelete()"
        />
        <a-button
          class="admin-delete-fill-btn"
          title="点击自动填入确认句，再次确认后即可删除"
          @click="batchAdminInput = BATCH_DELETE_CONFIRM_SENTENCE"
        >
          一键填入
        </a-button>
      </a-input-group>
    </a-modal>

    <EntityReviewDrawer
      v-model:open="entityReviewOpen"
      :library-id="libraryStore.libraryId || 'default'"
      @changed="loadRecords"
      @view-source="handleViewSource"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, onMounted, onBeforeUnmount, computed, watch } from 'vue'
import dayjs from 'dayjs'
import { message, Modal } from 'ant-design-vue'
import type { TableColumnType } from 'ant-design-vue'
import { CopyOutlined, ExclamationCircleOutlined } from '@ant-design/icons-vue'
import { useTheme } from '@angineer/ui-kit'
import { knowledgeApi, type ParseRecordItem } from '@/api/knowledge'
import { PDFParsedWorkspace } from '@angineer/docs-ui'
import type { KnowledgeTreeNode } from '@angineer/docs-ui'
import DocStageStepper from '@/components/DocStageStepper.vue'
import EntityReviewDrawer from '@/components/EntityReviewDrawer.vue'
import LibrarySelect from '@/components/LibrarySelect.vue'
import { useLibraryStore } from '@/stores/library'

const { appClass, isDark } = useTheme()

const libraryStore = useLibraryStore()
const entityReviewOpen = ref(false)
const records = ref<ParseRecordItem[]>([])
const loading = ref(false)
const showDeletedOnly = ref(false)
const selectedRowKeys = ref<number[]>([])

const docParsedWorkspaceRef = ref<InstanceType<typeof PDFParsedWorkspace> | null>(null)
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

const COLUMN_WIDTH_STORAGE_KEY = 'angineer-admin-knowledge-column-widths-v3'
const MIN_COLUMN_WIDTH = 48
const FILE_NAME_FALLBACK_WIDTH = 240

const columns = ref<TableColumnType[]>([
  { title: '上传人员', dataIndex: 'uploaded_by', key: 'uploaded_by', width: 96 },
  { title: '文件名称', dataIndex: 'file_name', key: 'file_name', ellipsis: true },
  { title: '格式', dataIndex: 'file_format', key: 'file_format', width: 60 },
  { title: '大小', key: 'file_size', width: 80 },
  { title: '页数', dataIndex: 'page_count', key: 'page_count', width: 60 },
  { title: '解析状态', key: 'status', width: 80 },
  { title: '上传时间', dataIndex: 'created_at', key: 'created_at', width: 140 },
  { title: '操作', key: 'action', width: 260, fixed: 'right' as const },
])

// 表格容器宽度：内容总宽超出容器时横向滚动（操作列 fixed:right 保持可见），否则自适应铺满
const tableWrapRef = ref<HTMLElement | null>(null)
const containerWidth = ref(0)
let tableResizeObserver: ResizeObserver | undefined

const contentWidth = computed(() => {
  let sum = 0
  for (const col of columns.value) {
    const w = (col as { width?: number | string }).width
    sum += typeof w === 'number' ? w : FILE_NAME_FALLBACK_WIDTH
  }
  return sum
})
const scrollX = computed(() => Math.max(containerWidth.value, contentWidth.value))

function observeTableWidth() {
  if (!tableWrapRef.value) return
  tableResizeObserver = new ResizeObserver((entries) => {
    const width = entries[0]?.contentRect.width
    if (width) containerWidth.value = Math.round(width)
  })
  tableResizeObserver.observe(tableWrapRef.value)
}

let resizingColumn: TableColumnType | null = null
let resizeStartX = 0
let resizeStartWidth = 0

function onResizeStart(event: MouseEvent, column: TableColumnType) {
  resizingColumn = column
  resizeStartX = event.clientX
  // 未设宽度的自适应列（文件名称）从 DOM 读取当前实际宽度作为起点
  const th = (event.target as HTMLElement).closest('th')
  resizeStartWidth = Number(column.width) || th?.offsetWidth || MIN_COLUMN_WIDTH
  document.addEventListener('mousemove', onResizeMove)
  document.addEventListener('mouseup', onResizeEnd)
}

function onResizeMove(event: MouseEvent) {
  if (!resizingColumn) return
  const nextWidth = Math.max(MIN_COLUMN_WIDTH, Math.round(resizeStartWidth + event.clientX - resizeStartX))
  resizingColumn.width = nextWidth
}

function onResizeEnd() {
  if (resizingColumn) {
    persistColumnWidths()
  }
  resizingColumn = null
  document.removeEventListener('mousemove', onResizeMove)
  document.removeEventListener('mouseup', onResizeEnd)
}

function persistColumnWidths() {
  const widths: Record<string, number> = {}
  for (const column of columns.value) {
    if (typeof column.width === 'number') {
      widths[String(column.key)] = column.width
    }
  }
  localStorage.setItem(COLUMN_WIDTH_STORAGE_KEY, JSON.stringify(widths))
}

function restoreColumnWidths() {
  try {
    const saved = JSON.parse(localStorage.getItem(COLUMN_WIDTH_STORAGE_KEY) || '{}') as Record<string, number>
    for (const column of columns.value) {
      const width = saved[String(column.key)]
      if (typeof width === 'number' && width >= MIN_COLUMN_WIDTH) {
        column.width = width
      }
    }
  } catch {
    // 本地存储内容损坏时忽略，使用默认列宽
  }
}

const rowSelection = computed(() => ({
  selectedRowKeys: selectedRowKeys.value,
  onChange: (keys: number[]) => { selectedRowKeys.value = keys },
}))

// 选中记录中是否包含用户尚未删除的文件（此类批量删除需额外强确认）
const selectedHasActiveFiles = computed(() =>
  selectedRowKeys.value.some(id =>
    records.value.find(r => r.id === id)?.file_status !== '用户已删'
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
    const res = await knowledgeApi.listRecords({
      show_deleted: showDeletedOnly.value,
      library_id: libraryStore.libraryId || 'default',
    })
    records.value = res.data
  } catch (e: any) {
    if (!silent) message.error('加载记录失败: ' + (e.message || e))
  } finally {
    loading.value = false
    syncRecordsPolling()
  }
}

watch(() => libraryStore.libraryId, () => {
  loadRecords()
})

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
  tableResizeObserver?.disconnect()
  document.removeEventListener('mousemove', onResizeMove)
  document.removeEventListener('mouseup', onResizeEnd)
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

async function handleViewSource(payload: { docId: string; sectionPath: string; libraryId: string }) {
  const { docId, sectionPath, libraryId } = payload
  viewerTitle.value = docId
  viewerNode.value = {
    key: docId,
    title: docId,
    status: 'completed',
    filePath: '',
    isFolder: false,
    parseProgress: 100,
    parseStage: 'completed',
    parseError: '',
    parseTaskId: '',
    visible: true,
  } as unknown as KnowledgeTreeNode
  viewerOpen.value = true
  await loadViewerData(docId, libraryId)
  await nextTick()
  const item = (viewerStructuredItems.value as any[]).find((s: any) => {
    const path = s?.meta?.section_path || s?.title || ''
    return path === sectionPath || path.includes(sectionPath) || sectionPath.includes(path)
  })
  if (item?.id) {
    docParsedWorkspaceRef.value?.setActiveLinkedItem(item.id)
  }
}

function onViewerClose() {
  viewerNode.value = null
  viewerContent.value = ''
  viewerStructuredItems.value = []
  viewerGraphData.value = null
  viewerRenderPdfPath.value = ''
}

async function loadViewerData(docId: string, libraryId?: string) {
  const lib = libraryId || useLibraryStore().libraryId
  try {
    const res = await knowledgeApi.getDocument(lib, docId) as any
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
    const graph = await knowledgeApi.getDocBlocksGraph(lib, docId) as any
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

// 下载源文件与 PDF 转换文件到浏览器默认下载路径；源文件即 PDF 时只下一个
const downloadingId = ref<number | null>(null)

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

function baseName(p: string): string {
  return p.split(/[/\\]/).filter(Boolean).pop() || p
}

async function downloadRecordFiles(record: ParseRecordItem) {
  downloadingId.value = record.id
  try {
    const res = await knowledgeApi.getDocumentStorage(libraryStore.libraryId || 'default', record.doc_id)
    const storage = (res as any)?.storage || {}
    const sourcePath = String(storage.source_file || '')
    const pdfPath = String(storage.render_pdf || '')
    const targets: { kind: 'source' | 'pdf'; name: string }[] = []
    if (sourcePath) targets.push({ kind: 'source', name: record.file_name || baseName(sourcePath) })
    if (pdfPath && pdfPath !== sourcePath) targets.push({ kind: 'pdf', name: baseName(pdfPath) })
    if (!targets.length) {
      message.warning('没有可下载的文件')
      return
    }
    for (const t of targets) {
      const blob = await knowledgeApi.downloadDocFile(record.doc_id, t.kind)
      saveBlob(blob, t.name)
      // 浏览器对连续多文件下载有限流，间隔触发
      await new Promise(r => setTimeout(r, 400))
    }
    message.success('已开始下载')
  } catch (e: any) {
    message.error('下载失败: ' + (e?.response?.data?.detail || e?.message || e))
  } finally {
    downloadingId.value = null
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
          await purgeNodeIfExists(record.doc_id)
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
    await purgeNodeIfExists(adminDeleteDocId.value)
    await knowledgeApi.hardDeleteRecord(adminDeleteRecordId.value)
    message.success('已删除')
    adminDeleteModalOpen.value = false
    adminDeleteInput.value = ''
    await loadRecords()
  } catch (e: any) {
    message.error('删除失败: ' + (e?.response?.data?.detail || e?.message || e))
  }
}

// 批量删除入口：含用户未删除文件时走强确认（输入确认句），否则普通确认
const batchAdminModalOpen = ref(false)
const batchAdminInput = ref('')
const BATCH_DELETE_CONFIRM_SENTENCE = '我再次确认将要删除这些用户未删除的文件！'

function onBatchDeleteClick() {
  if (!selectedRowKeys.value.length) return
  if (selectedHasActiveFiles.value) {
    batchAdminInput.value = ''
    batchAdminModalOpen.value = true
    return
  }
  Modal.confirm({
    title: '确认批量删除',
    content: `确定永久删除选中的 ${selectedRowKeys.value.length} 条解析记录吗？此操作不可恢复。`,
    okText: '删除',
    okType: 'danger',
    cancelText: '取消',
    onOk: batchHardDelete,
  })
}

async function batchHardDelete() {
  try {
    const ids = [...selectedRowKeys.value]
    for (const id of ids) {
      const record = records.value.find(r => r.id === id)
      if (record) {
        await purgeNodeIfExists(record.doc_id)
      }
      await knowledgeApi.hardDeleteRecord(id)
    }
    message.success(`已删除 ${ids.length} 条记录`)
    selectedRowKeys.value = []
    batchAdminModalOpen.value = false
    batchAdminInput.value = ''
    await loadRecords()
  } catch (e: any) {
    message.error('批量删除失败: ' + (e.message || e))
  }
}

// 彻底删除前清理知识库节点；节点已彻底不存在（孤儿记录）时忽略 404，仅清理记录本身。
async function purgeNodeIfExists(docId: string) {
  try {
    await knowledgeApi.deleteNode(docId)
  } catch (e: any) {
    if (e?.response?.status !== 404) throw e
  }
}

onMounted(() => {
  restoreColumnWidths()
  observeTableWidth()
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
.stats-title-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
}
.stats-deleted-label {
  font-size: 13px;
  color: var(--text-secondary);
  white-space: nowrap;
}
.stats-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.stats-table-wrap {
  min-width: 0;
}
:deep(.ant-table) {
  th, td { text-align: center !important; }
}
:deep(.ant-table-thead > tr > th) {
  position: relative;
}
.resizable-th {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 100%;
}

.resizable-th-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.resizable-th-handle {
  position: absolute;
  top: 0;
  right: -5px;
  bottom: 0;
  width: 10px;
  cursor: col-resize;
  z-index: 1;

  &::after {
    content: '';
    position: absolute;
    top: 8px;
    bottom: 8px;
    right: 4px;
    width: 2px;
    border-radius: 1px;
    background: transparent;
    transition: background 0.2s;
  }

  &:hover::after {
    background: var(--primary-color);
  }
}
.action-btns {
  display: inline-flex;
  align-items: baseline;
  gap: 2px;
  white-space: nowrap;
  // 五个文字按钮统一字号，高度贴合文字，保证视觉对齐
  :deep(.ant-btn) {
    padding-inline: 4px;
    margin-inline: 0;
    height: auto;
    font-size: 13px;
    line-height: 1.5;
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
    background: var(--bg-secondary, #fafafa);
    border: 1px solid var(--border-color, #f0f0f0);
    color: var(--text-primary, rgba(0, 0, 0, 0.88));
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
.admin-delete-fill-group {
  display: flex;
  width: 100%;
}
.admin-delete-fill-input {
  flex: 1;
  min-width: 0;
}
.admin-delete-fill-btn {
  color: var(--text-secondary, rgba(0, 0, 0, 0.45));
  background: var(--bg-secondary, #fafafa);
  border-color: var(--border-color, #d9d9d9);
  &:hover {
    color: var(--primary-color);
    border-color: var(--primary-color);
    background: var(--bg-secondary, #fafafa);
  }
}
.library-review-group {
  display: flex;
  align-items: center;
  margin-right: 12px;
  :deep(.ant-select .ant-select-selector) {
    border-top-right-radius: 0;
    border-bottom-right-radius: 0;
  }
}
.library-review-btn {
  color: var(--text-secondary, rgba(0, 0, 0, 0.45));
  background: var(--bg-secondary, #fafafa);
  border-color: var(--border-color, #d9d9d9);
  height: 32px;
  border-radius: 0 6px 6px 0;
  border-left: none;
  &:hover {
    color: var(--primary-color);
    border-color: var(--primary-color);
    background: var(--bg-secondary, #fafafa);
  }
}
</style>
