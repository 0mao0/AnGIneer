<template>
  <div class="knowledge-stats" :class="appClass">
    <div class="stats-content">
    <div class="page-header">
      <div class="page-header-left">
        <LibrarySelect class="library-select-inline" mode="title" @review="onEntityReview" />
      </div>
      <div class="page-header-right">
        <a-switch
          :checked="showDeletedOnly"
          size="small"
          @change="toggleDeletedFilter"
        />
        <span class="page-header-label">用户已删</span>
      </div>
    </div>

    <div class="stats-filter-bar">
      <a-input
        v-model:value="keywordFilter"
        placeholder="按文件名搜索"
        allow-clear
        class="stats-filter-item"
        style="width: 240px"
      />
      <a-select
        v-model:value="statusFilter"
        placeholder="全部状态"
        allow-clear
        class="stats-filter-item"
        style="width: 140px"
      >
        <a-select-option v-for="opt in statusFilterOptions" :key="opt.value" :value="opt.value">
          {{ opt.label }}
        </a-select-option>
      </a-select>
      <a-select
        v-model:value="formatFilter"
        placeholder="全部格式"
        allow-clear
        class="stats-filter-item"
        style="width: 120px"
      >
        <a-select-option v-for="opt in formatFilterOptions" :key="opt.value" :value="opt.value">
          {{ opt.label }}
        </a-select-option>
      </a-select>
      <a-button type="primary" class="stats-filter-upload" @click="openUploadModal">
        <template #icon><upload-outlined /></template>
        上传
      </a-button>
      <a-button
        v-show="selectedRowKeys.length > 0"
        type="primary"
        class="stats-filter-batch-parse"
        :loading="batchParsing"
        @click="onBatchParseClick"
      >
        批量解析 ({{ selectedRowKeys.length }})
      </a-button>
      <a-button
        v-show="selectedRowKeys.length > 0"
        type="primary"
        danger
        class="stats-filter-batch-delete"
        @click="onBatchDeleteClick"
      >
        批量删除 ({{ selectedRowKeys.length }})
      </a-button>
    </div>

    <div ref="tableWrapRef" class="stats-table-wrap">
    <DataTable
      :columns="columns"
      :data-source="filteredRecords"
      :loading="loading"
      :row-selection="rowSelection"
      row-key="id"
      :card="false"
      :pagination="{ pageSize: 20, showSizeChanger: true, pageSizeOptions: ['10', '20', '50', '100'], showTotal: (total: number) => `共 ${total} 条` }"
      storage-key="angineer-admin-knowledge-v4"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'file_size'">
          {{ formatFileSize(record.file_size) }}
        </template>
        <template v-if="column.key === 'folder'">
          <a-tree-select
            size="small"
            style="width: 100%"
            :value="folderCellSelectValue(record.doc_id)"
            :tree-data="folderTreeSelectData"
            :disabled="!docIdsInNodes.has(record.doc_id)"
            :loading="movingDocIds.has(record.doc_id)"
            :dropdown-match-select-width="false"
            :dropdown-style="{ minWidth: '360px' }"
            tree-default-expand-all
            show-search
            tree-node-filter-prop="name"
            tree-node-label-prop="displayLabel"
            @change="(val: any) => folderCellChange(record, val)"
          />
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
    </DataTable>
    </div>
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
      <DocViewerPane
        v-if="viewerNode"
        ref="docParsedWorkspaceRef"
        :node="viewerNode"
        :content="viewerContent"
        :structured-items="viewerStructuredItems"
        :graph-data="viewerGraphData"
        :render-pdf-path="viewerRenderPdfPath"
        :dark="isDark"
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

    <BatchUploadModal
      v-model:visible="uploadModalOpen"
      :parse-options="parseOptions"
      @uploaded="loadRecords"
    />

    <FolderModal
      v-model:visible="folderModal.visible"
      :title="folderModal.isNew ? '新建文件夹' : '重命名文件夹'"
      :loading="folderModal.saving"
      :folder-tree-data="folderParentTree"
      :root-value="ROOT_FOLDER_VALUE"
      v-model:name="folderModal.name"
      v-model:parent-id="folderModal.parentId"
      :is-new="folderModal.isNew"
      :parent-editable="!folderModal.isNew"
      @confirm="submitFolderModal"
    />

    <a-modal
      v-model:open="folderDelete.open"
      title="删除文件夹"
      ok-text="永久删除"
      ok-danger
      :ok-button-props="{ disabled: folderDelete.input.trim() !== folderDelete.title.trim() || folderDelete.deleting }"
      @ok="confirmFolderDelete"
      @cancel="folderDelete.input = ''"
    >
      <p class="folder-delete-warning">
        将彻底删除「{{ folderDelete.label }}」及其内部全部内容（节点、解析产物与索引一并清除，不可恢复）：
        子文件夹 {{ Math.max(folderDelete.folderCount - 1, 0) }} 个、文档 {{ folderDelete.docCount }} 篇。
      </p>
      <p v-if="folderDelete.sample.length" class="folder-delete-sample">
        其中文档如：{{ folderDelete.sample.join('、') }}
      </p>
      <p>请输入完整文件夹名确认：</p>
      <p class="folder-delete-name">{{ folderDelete.title }}</p>
      <a-input-group compact class="folder-delete-fill-group">
        <a-input
          v-model:value="folderDelete.input"
          :placeholder="folderDelete.title"
          class="folder-delete-fill-input"
          @pressEnter="confirmFolderDelete"
        />
        <a-button
          class="folder-delete-fill-btn"
          title="点击自动填入完整文件夹名，再次确认后即可删除"
          @click="folderDelete.input = folderDelete.title"
        >
          一键填入
        </a-button>
      </a-input-group>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { defineAsyncComponent, ref, nextTick, onMounted, onBeforeUnmount, onActivated, onDeactivated, computed, watch, h } from 'vue'
import dayjs from 'dayjs'
import { message, Modal, Button } from 'ant-design-vue'
import {
  CopyOutlined,
  ExclamationCircleOutlined,
  UploadOutlined,
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  UpOutlined,
  DownOutlined,
} from '@ant-design/icons-vue'
import { useTheme } from '@angineer/ui-kit'
import { DataTable } from '@angineer/table-ui'
import type { DataTableColumn } from '@angineer/ui-kit'
import { knowledgeApi, type ParseRecordItem } from '@/api/knowledge'
import { useKnowledgeParse } from '@angineer/docs-ui/composables/useKnowledgeParse'
import type { KnowledgeTreeNode, KnowledgeParseOptions } from '@angineer/docs-ui'
import DocStageStepper from '@/components/DocStageStepper.vue'
import EntityReviewDrawer from '@/components/EntityReviewDrawer.vue'
import LibrarySelect from '@/components/LibrarySelect.vue'
import BatchUploadModal from '@/components/BatchUploadModal.vue'
import FolderModal from '@/views/components/FolderModal.vue'
import { useLibraryStore } from '@/stores/library'
import type { KnowledgeLibraryItem } from '@/stores/library'

/**
 * 预览工作区只在「查看」抽屉里用：经 DocViewerPane 薄包装动态引入，把 pdf.js /
 * docx-preview / katex 整个预览栈从落地路由块拆出去（此前静态 import 让它成为落地页必下内容）。
 * 同理 useKnowledgeParse 走子路径导入而非 barrel：只取一个 composable 时 barrel 会连带
 * re-export 的 PDF_Viewer / OfficePreview（katex、pdf.js、xlsx）一起进落地路由块，
 * 实测该路由块 725KB→86KB、静态下载 2015KB→1120KB。
 * loader 与异步组件共用，空闲预热过则打开抽屉时秒开。
 */
const docViewerLoader = () => import('./DocViewerPane.vue')
const DocViewerPane = defineAsyncComponent(docViewerLoader)

const { appClass, isDark } = useTheme()
const { fetchLlmConfigs, buildParseOptionsPayload } = useKnowledgeParse(knowledgeApi)

const libraryStore = useLibraryStore()
const entityReviewOpen = ref(false)
const uploadModalOpen = ref(false)
const parseOptions = ref<KnowledgeParseOptions>({})

async function openUploadModal() {
  uploadModalOpen.value = true
  try {
    await fetchLlmConfigs()
    parseOptions.value = buildParseOptionsPayload()
  } catch {
    parseOptions.value = {}
  }
}
const records = ref<ParseRecordItem[]>([])

// ── 文件夹列：节点树上下文（当前库的全部文件夹 + 每篇文档的所在目录）──
// label 是展示用全路径，title 是本级名（重命名预填用），parent_id 供父级树/重挂
interface FolderOption { value: string; label: string; title: string; parentId: string; sortOrder: number }
const folderOptions = ref<FolderOption[]>([])
const docParents = ref<Record<string, string>>({})
const docIdsInNodes = ref<Set<string>>(new Set())
const movingDocIds = ref<Set<string>>(new Set())

function folderPathLabel(node: any, byId: Map<string, any>): string {
  const parts: string[] = [node.title]
  let cur = node.parent_id
  let guard = 0
  while (cur && guard++ < 20) {
    const parent = byId.get(cur)
    if (!parent) break
    parts.unshift(parent.title)
    cur = parent.parent_id
  }
  return parts.join(' / ')
}

async function loadFolderContext() {
  try {
    const nodes = (await knowledgeApi.getNodes(libraryStore.libraryId || 'default', false)) as unknown as any[]
    const byId = new Map<string, any>()
    for (const n of nodes) byId.set(n.id, n)
    folderOptions.value = nodes
      .filter(n => n.type === 'folder')
      .map(n => ({
        value: n.id,
        label: folderPathLabel(n, byId),
        title: String(n.title || ''),
        parentId: String(n.parent_id || ''),
        sortOrder: Number(n.sort_order || 0),
      }))
    const parents: Record<string, string> = {}
    const ids = new Set<string>()
    for (const n of nodes) {
      if (n.type !== 'document') continue
      ids.add(n.id)
      if (n.parent_id) parents[n.id] = n.parent_id
    }
    docParents.value = parents
    docIdsInNodes.value = ids
  } catch {
    // 节点接口失败保留上一次上下文：行内下拉只是暂时不可用，不打断列表
  }
}

function parentOf(docId: string): string {
  return docParents.value[docId] || ''
}

const folderValueSet = computed(() => new Set(folderOptions.value.map(f => f.value)))
function unknownParent(docId: string): string {
  const parent = docParents.value[docId]
  return parent && !folderValueSet.value.has(parent) ? parent : ''
}

async function moveRecord(record: ParseRecordItem, value: string) {
  const docId = record.doc_id
  movingDocIds.value = new Set(movingDocIds.value).add(docId)
  try {
    await knowledgeApi.updateNode(docId, { parent_id: value || null })
    if (value) {
      docParents.value = { ...docParents.value, [docId]: value }
    } else {
      const rest = { ...docParents.value }
      delete rest[docId]
      docParents.value = rest
    }
    docIdsInNodes.value = new Set(docIdsInNodes.value).add(docId)
    const label = folderOptions.value.find(f => f.value === value)?.label || '根目录'
    message.success(`「${record.file_name}」已移动到 ${label}`)
  } catch (e: any) {
    message.error(`移动失败: ${e?.response?.data?.detail || e?.message || e}`)
  } finally {
    const next = new Set(movingDocIds.value)
    next.delete(docId)
    movingDocIds.value = next
  }
}

// ── 文件夹增删改：行内「文件夹」树下拉（a-tree-select 真树；节点行带 ✎/🗑，旁边 ＋ 新建）──
// 本版 antdv TreeSelect 受控 :open 与面板状态不同步（该开不开/该关不关），下拉不做受控；
// ✎/🗑 弹框打开前收起下拉。Escape 键实测不生效，改点 select 自身箭头 = rc-select 的 toggleOpen
function closeOpenDropdown() {
  if (!document.querySelector('.ant-select-open')) return
  document.body.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }))
}

// 活文件夹按 parent_id 组嵌套：FolderModal 的父级选择 + 单元格树下拉共用
const folderSelectTree = computed(() => {
  const byParent = new Map<string, FolderOption[]>()
  for (const f of folderOptions.value) {
    const list = byParent.get(f.parentId) || []
    list.push(f)
    byParent.set(f.parentId, list)
  }
  const build = (parentId: string): any[] =>
    (byParent.get(parentId) || []).map(f => ({ value: f.value, title: f.title, children: build(f.value) }))
  // 挂到不在本列表里的父级（如展平的历史根目录）也当根级展示，避免整支消失
  const known = new Set(folderOptions.value.map(f => f.value))
  const roots = build('')
  for (const f of folderOptions.value) {
    if (f.parentId && !known.has(f.parentId)) roots.push({ value: f.value, title: f.title, children: build(f.value) })
  }
  return roots
})

// FolderModal 父级选择树：加「根目录」哨兵根，根层级可选且显示为根目录（选根回写 ''）
const folderParentTree = computed(() => [
  { value: ROOT_FOLDER_VALUE, title: '根目录', children: folderSelectTree.value },
])

// 单元格树下拉数据：「根目录」根（value 哨兵，选中即移出到库根）+ 文件夹树 + 未知父级兜底节点
// 本版 antdv TreeSelect 不支持 titleRender 槽（源码 TreeNode/OptionList 未消费），
// 节点行内 ✎/🗑 只能走 treeData.title = vnode；收起态显示走 displayLabel（tree-node-label-prop），
// 搜索走 name 本级名（tree-node-filter-prop）。vnode 不带 scoped data-v，样式用内联 style。
const ROOT_FOLDER_VALUE = '__root__'
function cellIconButton(icon: any, title: string, onClick: () => void, disabled = false) {
  return h(Button, { type: 'text', size: 'small', title, disabled, onClick }, { icon: () => h(icon) })
}
function cellNodeTitleRow(label: string, tooltip: string, actions: any[]) {
  return h('div', { style: 'display:flex;align-items:center;gap:8px;width:100%' }, [
    h('span', { style: 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap', title: tooltip }, label),
    actions.length
      ? h(
          'span',
          {
            style: 'display:inline-flex;gap:2px;margin-left:auto;flex-shrink:0',
            onMousedown: (e: MouseEvent) => e.stopPropagation(),
            onClick: (e: MouseEvent) => e.stopPropagation(),
          },
          actions,
        )
      : null,
  ])
}
function cellFolderNode(f: FolderOption): any {
  const sibs = siblingsOf(f)
  const idx = sibs.findIndex(x => x.value === f.value)
  const children = cellChildrenOf(f.value)
  return {
    value: f.value,
    name: f.title,
    displayLabel: f.label,
    title: cellNodeTitleRow(f.title, f.label, [
      cellIconButton(PlusOutlined, '新建子文件夹', () => openFolderCreate(f.value)),
      cellIconButton(EditOutlined, '重命名', () => openFolderRenameById(f.value)),
      cellIconButton(DeleteOutlined, '删除', () => openFolderDeleteById(f.value)),
      cellIconButton(UpOutlined, '上移', () => moveFolderSibling(f.value, -1), idx <= 0),
      cellIconButton(DownOutlined, '下移', () => moveFolderSibling(f.value, 1), idx >= sibs.length - 1),
    ]),
    children,
  }
}
// 上移/下移＝同级内交换位置：按新下标整段重排、只 PATCH 值有变的节点（list_nodes 按 sort_order 排）
function siblingsOf(f: FolderOption): FolderOption[] {
  return folderOptions.value.filter(x => x.parentId === f.parentId)
}
async function moveFolderSibling(folderId: string, dir: -1 | 1) {
  const f = folderOptions.value.find(x => x.value === folderId)
  if (!f) return
  const sibs = siblingsOf(f)
  const idx = sibs.findIndex(x => x.value === folderId)
  const target = idx + dir
  if (idx < 0 || target < 0 || target >= sibs.length) return
  closeOpenDropdown()
  const ordered = sibs.slice()
  const [moved] = ordered.splice(idx, 1)
  ordered.splice(target, 0, moved)
  try {
    await Promise.all(
      ordered.map((n, i) => (n.sortOrder === i ? null : knowledgeApi.updateNode(n.value, { sort_order: i }))),
    )
    await loadFolderContext()
  } catch (e: any) {
    message.error(`排序失败: ${e?.response?.data?.detail || e?.message || e}`)
  }
}
function cellChildrenOf(parentId: string): any[] {
  const list = folderOptions.value.filter(f => f.parentId === parentId).map(cellFolderNode)
  return list.length ? list : (undefined as any)
}
const unknownParentNodes = computed(() => {
  const ids: string[] = []
  const seen = new Set<string>()
  for (const r of records.value) {
    const u = unknownParent(r.doc_id)
    if (u && !seen.has(u)) {
      seen.add(u)
      ids.push(u)
    }
  }
  return ids.map(id => ({ value: id, name: '（未知目录）', displayLabel: '（未知目录）', title: '（未知目录）' }))
})
const folderTreeSelectData = computed(() => {
  const roots = folderOptions.value.filter(f => !f.parentId || !folderValueSet.value.has(f.parentId)).map(cellFolderNode)
  return [
    {
      value: ROOT_FOLDER_VALUE,
      name: '根目录',
      displayLabel: '根目录',
      title: cellNodeTitleRow('根目录', '库根（移动到此处 = 移出所有文件夹）', [
        cellIconButton(PlusOutlined, '在根目录新建文件夹', () => openFolderCreate('')),
      ]),
      children: roots,
    },
    ...unknownParentNodes.value,
  ]
})
function folderCellSelectValue(docId: string): string {
  return parentOf(docId) || ROOT_FOLDER_VALUE
}
function folderCellChange(record: ParseRecordItem, val: any) {
  const v = String(val ?? '')
  moveRecord(record, v === ROOT_FOLDER_VALUE ? '' : v)
}

const folderModal = ref({
  visible: false,
  saving: false,
  isNew: true,
  name: '',
  parentId: undefined as string | undefined,
  editId: '',
})

// 弹框关闭（确定/取消）时收起其中可能开着的父级面板——面板挂在 body，modal 隐藏不会带走它
watch(
  () => folderModal.value.visible,
  (v, old) => {
    if (!v && old) closeOpenDropdown()
  },
)

function openFolderCreate(parentId: string) {
  closeOpenDropdown()
  folderModal.value = {
    visible: true,
    saving: false,
    isNew: true,
    name: '',
    parentId: parentId || undefined,
    editId: '',
  }
}

function openFolderRenameById(folderId: string) {
  const f = folderOptions.value.find(x => x.value === folderId)
  if (!f) {
    message.warning('该文件夹已不在当前库，请刷新后重试')
    return
  }
  closeOpenDropdown()
  // 预填当前父级：弹框里改父级＝换层级（防成环由后端 PATCH 守卫，报错原样弹出）
  folderModal.value = {
    visible: true,
    saving: false,
    isNew: false,
    name: f.title,
    parentId: f.parentId || undefined,
    editId: f.value,
  }
}

async function submitFolderModal() {
  const name = folderModal.value.name.trim()
  if (!name) {
    message.warning('请输入文件夹名称')
    return
  }
  const m = folderModal.value
  m.saving = true
  try {
    if (m.isNew) {
      await knowledgeApi.createNode({
        title: name,
        node_type: 'folder',
        library_id: libraryStore.libraryId || 'default',
        parent_id: m.parentId || undefined,
      })
      message.success(`文件夹「${name}」已创建`)
    } else {
      const cur = folderOptions.value.find(x => x.value === m.editId)
      const newParent = m.parentId || ''
      const curParent = cur?.parentId || ''
      const patch: any = { title: name }
      if (newParent !== curParent) patch.parent_id = newParent || null
      await knowledgeApi.updateNode(m.editId, patch)
      message.success(newParent !== curParent ? '已重命名并移动' : '已重命名')
    }
    m.visible = false
    await loadFolderContext()
  } catch (e: any) {
    message.error(`保存失败: ${e?.response?.data?.detail || e?.message || e}`)
  } finally {
    m.saving = false
  }
}

// 删除：先取影响范围预览，再二次确认（需输入完整文件夹名）
const folderDelete = ref({
  open: false,
  deleting: false,
  id: '',
  title: '',
  label: '',
  folderCount: 0,
  docCount: 0,
  sample: [] as string[],
  input: '',
})

async function openFolderDeleteById(folderId: string) {
  const f = folderOptions.value.find(x => x.value === folderId)
  if (!f) {
    message.warning('该文件夹已不在当前库，请刷新后重试')
    return
  }
  let preview: any = null
  try {
    preview = await knowledgeApi.getDeleteNodePreview(f.value)
  } catch {
    // 预览失败不拦删除：影响范围按未知呈现，仍要求输入名字确认
  }
  closeOpenDropdown()
  folderDelete.value = {
    open: true,
    deleting: false,
    id: f.value,
    title: f.title,
    label: f.label,
    folderCount: Number(preview?.folder_count || 0),
    docCount: Number(preview?.document_count || 0),
    sample: Array.isArray(preview?.sample_doc_titles) ? preview.sample_doc_titles.slice(0, 3) : [],
    input: '',
  }
}

async function confirmFolderDelete() {
  const d = folderDelete.value
  if (d.input.trim() !== d.title.trim()) return
  d.deleting = true
  try {
    await knowledgeApi.deleteNode(d.id)
    message.success(`文件夹「${d.title}」已删除`)
    d.open = false
    d.input = ''
    await loadFolderContext()
    // 其下文档随文件夹一起没了，列表同步刷新
    await loadRecords()
  } catch (e: any) {
    message.error(`删除失败: ${e?.response?.data?.detail || e?.message || e}`)
  } finally {
    d.deleting = false
  }
}

// ── 历史记录筛选（文件名 / 状态 / 格式，客户端过滤）──────────────────
const keywordFilter = ref('')
const statusFilter = ref<string | undefined>(undefined)
const formatFilter = ref<string | undefined>(undefined)

const STATUS_FILTER_OPTIONS = [
  { value: 'completed', label: '完成' },
  { value: 'processing', label: '进行中' },
  { value: 'queued', label: '排队中' },
  { value: 'pending', label: '待解析' },
  { value: 'partial', label: '部分完成' },
  { value: 'failed', label: '失败' },
  { value: 'cancelled', label: '已取消' },
  { value: 'deleted', label: '用户已删' },
]
const statusFilterOptions = STATUS_FILTER_OPTIONS
const formatFilterOptions = ['pdf', 'doc', 'docx', 'md', 'txt'].map((f) => ({
  value: f,
  label: f.toUpperCase(),
}))

const filteredRecords = computed(() => {
  const kw = keywordFilter.value.trim().toLowerCase()
  return records.value.filter((r) => {
    if (statusFilter.value && r.status !== statusFilter.value) return false
    if (formatFilter.value && String(r.file_format || '').toLowerCase() !== formatFilter.value) return false
    if (kw && !String(r.file_name || '').toLowerCase().includes(kw)) return false
    return true
  })
})
const loading = ref(false)
const showDeletedOnly = ref(false)
const selectedRowKeys = ref<number[]>([])

/** 异步组件取不到内层实例类型；抽屉里只用到这一个方法 */
type ParsedWorkspaceHandle = { setActiveLinkedItem: (id: string) => void }
const docParsedWorkspaceRef = ref<ParsedWorkspaceHandle | null>(null)
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
const batchParsing = ref(false)

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

const columns = ref<DataTableColumn[]>([
  { title: '上传人员', dataIndex: 'uploaded_by', key: 'uploaded_by', width: 96 },
  { title: '文件名称', dataIndex: 'file_name', key: 'file_name', ellipsis: true, flex: true },
  { title: '格式', dataIndex: 'file_format', key: 'file_format', width: 60 },
  { title: '文件夹', key: 'folder', width: 170 },
  { title: '大小', key: 'file_size', width: 80 },
  { title: '页数', dataIndex: 'page_count', key: 'page_count', width: 60 },
  { title: '解析状态', key: 'status', width: 80 },
  { title: '上传时间', dataIndex: 'created_at', key: 'created_at', width: 140 },
  { title: '操作', key: 'action', width: 260, fixed: 'right' },
])

// 表格容器宽度：内容总宽超出容器时横向滚动（操作列 fixed:right 保持可见），否则自适应铺满
const tableWrapRef = ref<HTMLElement | null>(null)

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
  if (!silent) {
    loading.value = true
    // 手动刷新/切库/上传后顺带取文件夹上下文（轮询静默刷新不带，省一半请求）
    void loadFolderContext()
  }
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

// 下拉 item 内的实体审核入口：切换库并打开审核抽屉
function onEntityReview(lib: KnowledgeLibraryItem) {
  libraryStore.setLibrary(lib.id)
  entityReviewOpen.value = true
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

/** 被 keep-alive 缓存后 onMounted 只跑一次：每次回到本视图静默补刷列表，
 *  否则解析状态会停在离开时的快照上（列表里还有「解析中」的任务时必须新鲜）。
 *  注意 activated 在首次挂载时也会触发，跳过第一次以免与 onMounted 重复取数。 */
let activationSkipped = false
onActivated(() => {
  if (!activationSkipped) {
    activationSkipped = true
    return
  }
  loadRecords(true)
  // 阶段抽屉可能在离开时还开着，缓存后 watch(stepsModalOpen) 不会再触发，这里补启
  if (stepsModalOpen.value) startStagesPolling()
})

/** deactivate 不触发 onBeforeUnmount：两个轮询表必须在这里收口，否则在后台一直跑。 */
onDeactivated(() => {
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
  // 先只取 storage 拿 render_pdf，让 PDF 立刻开始下载；content.md 大文档可达 MB 级，不参与首屏时序
  try {
    const light = await knowledgeApi.getDocument(lib, docId, { includeContent: false }) as any
    viewerRenderPdfPath.value = light?.storage?.render_pdf || ''
  } catch {
    viewerRenderPdfPath.value = ''
  }
  try {
    const res = await knowledgeApi.getDocument(lib, docId) as any
    viewerContent.value = res?.content || ''
    // 轻量接口失败时用完整响应兜底，避免有内容却没渲染出 PDF
    viewerRenderPdfPath.value = viewerRenderPdfPath.value || res?.storage?.render_pdf || ''
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
  const ids = [...selectedRowKeys.value]
  if (!ids.length) return
  const deletingKey = `batch-deleting-${Date.now()}`
  message.loading({ content: `正在删除 ${ids.length} 条记录…`, key: deletingKey, duration: 0 })
  try {
    const res = await knowledgeApi.batchHardDeleteRecords(ids)
    const failed = res?.failed ?? []
    message.destroy(deletingKey)
    if (failed.length) {
      message.warning(`已删除 ${res?.deleted ?? ids.length - failed.length} 条，失败 ${failed.length} 条`)
      console.warn('批量硬删失败明细:', failed)
    } else {
      message.success(`已删除 ${ids.length} 条记录`)
    }
    selectedRowKeys.value = []
    batchAdminModalOpen.value = false
    batchAdminInput.value = ''
    await loadRecords()
  } catch (e: any) {
    message.destroy(deletingKey)
    message.error('批量删除失败: ' + (e?.response?.data?.detail || e?.message || e))
  }
}

// 批量解析：对选中的记录发起解析任务
async function onBatchParseClick() {
  if (!selectedRowKeys.value.length) return
  // 获取选中记录的 doc_id（过滤掉已在进行中的记录）
  const selectedDocs = records.value.filter(r =>
    selectedRowKeys.value.includes(r.id) && !RUNNING_STATUSES.has(r.status)
  )
  if (!selectedDocs.length) {
    message.warning('选中的记录中没有可解析的文件（均已在进行中或无需解析）')
    return
  }
  const docIds = selectedDocs.map(r => r.doc_id)
  batchParsing.value = true
  const loadingKey = `batch-parsing-${Date.now()}`
  message.loading({ content: `正在发起 ${docIds.length} 个解析任务…`, key: loadingKey, duration: 0 })
  try {
    const res = await knowledgeApi.batchRetryParseTasks(docIds)
    message.destroy(loadingKey)
    if (res.errors.length && !res.started) {
      message.error(`批量解析失败：${res.errors[0].reason}`)
    } else if (res.errors.length) {
      message.warning(`已启动 ${res.started} 个解析，${res.errors.length} 个失败`)
    } else {
      message.success(`已启动 ${res.started} 个解析任务`)
    }
    selectedRowKeys.value = []
    await loadRecords()
  } catch (e: any) {
    message.destroy(loadingKey)
    message.error('批量解析失败: ' + (e?.response?.data?.detail || e?.message || e))
  } finally {
    batchParsing.value = false
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
  loadRecords()
  // 空闲预热预览栈：落地页不再为 pdf.js / docx-preview / xlsx 买单，
  // 用户点「查看」时组件已在内存里（预热失败不影响功能，异步组件会自行重试加载）
  const prime = () => { void docViewerLoader().catch(() => {}) }
  if (typeof requestIdleCallback === 'function') requestIdleCallback(prime, { timeout: 5000 })
  else setTimeout(prime, 2000)
})
</script>

<style lang="less" scoped>
.knowledge-stats {
  height: 100%;
  padding: 24px;
  background: var(--bg-primary);
  overflow-y: auto;
}
.stats-content {
  max-width: 1100px;
  width: 100%;
  margin: 0 auto;
}
.page-header {
  margin-bottom: 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.page-header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}
.page-header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}
.page-header-label {
  color: var(--text-tertiary);
  font-size: 14px;
}
.stats-table-wrap {
  min-width: 0;
  width: 100%;
}
.stats-filter-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}
.stats-filter-item {
  min-width: 0;
}
.folder-delete-warning {
  color: var(--error-color, #ff4d4f);
  margin-bottom: 12px;
}
.folder-delete-sample {
  color: var(--text-secondary, rgba(0, 0, 0, 0.55));
  margin-bottom: 12px;
  word-break: break-all;
}
.folder-delete-name {
  font-weight: 600;
  word-break: break-all;
  margin-bottom: 8px;
}
.folder-delete-fill-group {
  display: flex;
  width: 100%;
}
.folder-delete-fill-input {
  flex: 1;
  min-width: 0;
}
.folder-delete-fill-btn {
  color: var(--text-secondary, rgba(0, 0, 0, 0.45));
  background: var(--bg-secondary, #fafafa);
  border-color: var(--border-color, #d9d9d9);
}
.stats-filter-upload,
.stats-filter-batch-delete,
.stats-filter-batch-parse {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 32px;
  padding: 0 15px;
  line-height: 1;
  vertical-align: middle;
}
.stats-filter-upload {
  margin-left: auto;
}
:deep(.ant-table) {
  th, td { text-align: center !important; }
}
:deep(.ant-table-thead > tr > th) {
  position: relative;
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
.library-select-inline {
  :deep(.ant-select .ant-select-selector) {
    border-top-right-radius: 6px;
    border-bottom-right-radius: 6px;
  }
}
</style>

