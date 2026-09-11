<template>
  <div v-show="evalView === 'workbench'" ref="workspaceRef" class="eval-workspace" :class="appClass">
    <SplitPanes
      ref="splitPanesRef"
      class="workspace-container"
      :initial-left-ratio="panelRatios.left"
      :initial-right-ratio="panelRatios.right"
      :left-collapsible="true"
      :left-collapsed="leftPanelCollapsed"
      @update:left-collapsed="onLeftCollapsedChange"
      :right-collapsible="true"
      :right-collapsed="rightPanelCollapsed"
      @update:right-collapsed="onRightCollapsedChange"
      @resize="onPanelResize"
    >
      <template #left>
        <Panel title="测试集" :icon="DatabaseOutlined" contentClass="tree-panel-content">
          <template #extra>
            <a-button type="text" size="small" title="手动创建空测试集" @click="openCreateModal">
              <template #icon><PlusOutlined /></template>
            </a-button>
            <a-tooltip title="收起侧边栏">
              <a-button size="small" class="header-icon-btn" @click="splitPanesRef?.toggleLeft()">
                <template #icon><MenuFoldOutlined /></template>
              </a-button>
            </a-tooltip>
          </template>
          <div class="tree-container">
            <EvalDatasetTree
              ref="evalTreeRef"
              :tree-data="evalTreeData"
              :show-search="true"
              search-placeholder="搜索测试集..."
              :show-add-root-folder="true"
              add-root-folder-title="新建文件夹"
              :show-icon="true"
              :show-status="false"
              :draggable="true"
              :default-expanded-keys="evalDefaultExpandedKeys"
              :default-selected-keys="selectedDatasetId ? [selectedDatasetId] : []"
              :dark="isDark"
              empty-text="暂无测试集"
              @select="onDatasetSelect"
              @rename="onDatasetRename"
              @add-folder="onAddFolder"
              @add-file="onAddFile"
              @delete="onDatasetDelete"
              @view="onDatasetView"
              @drop="onTreeDrop"
              @drop-root="onTreeDropRoot"
              @drop-invalid="onInvalidDrop"
            >
              <template #actions="{ node }">
                <template v-if="node.isFolder">
                  <button
                    type="button"
                    class="action-btn"
                    aria-label="重命名"
                    title="重命名"
                    @click.stop="onDatasetRename(node as EvalTreeNode)"
                  >
                    <EditOutlined />
                  </button>
                  <button
                    type="button"
                    class="action-btn"
                    aria-label="导入测试集"
                    title="导入测试集"
                    @click.stop="onAddFile(node as EvalTreeNode)"
                  >
                    <UploadOutlined />
                  </button>
                  <button
                    type="button"
                    class="action-btn"
                    aria-label="添加子文件夹"
                    title="添加子文件夹"
                    @click.stop="onAddFolder(node as EvalTreeNode)"
                  >
                    <FolderAddOutlined />
                  </button>
                  <button
                    type="button"
                    class="action-btn delete"
                    aria-label="删除"
                    title="删除"
                    @click.stop="onDatasetDelete(node as EvalTreeNode)"
                  >
                    <DeleteOutlined />
                  </button>
                </template>
                <template v-else>
                  <button
                    type="button"
                    class="action-btn"
                    aria-label="重命名"
                    title="重命名"
                    @click.stop="onDatasetRename(node as EvalTreeNode)"
                  >
                    <EditOutlined />
                  </button>
                  <button
                    type="button"
                    class="action-btn"
                    aria-label="查看详情"
                    title="查看详情"
                    @click.stop="onDatasetView(node as EvalTreeNode)"
                  >
                    <EyeOutlined />
                  </button>
                  <button
                    type="button"
                    class="action-btn"
                    aria-label="导出"
                    title="导出"
                    @click.stop="onDatasetExport(node as EvalTreeNode)"
                  >
                    <ExportOutlined />
                  </button>
                  <button
                    type="button"
                    class="action-btn delete"
                    aria-label="删除"
                    title="删除"
                    @click.stop="onDatasetDelete(node as EvalTreeNode)"
                  >
                    <DeleteOutlined />
                  </button>
                </template>
              </template>
            </EvalDatasetTree>
          </div>
        </Panel>
      </template>

      <template #center>
        <Panel title="题目列表" :icon="UnorderedListOutlined">
          <template #extra>
            <a-space v-if="currentDataset">
              <a-tag>{{ currentDataset.category }}</a-tag>
              <span class="question-count">{{ questions.length }} 题</span>
            </a-space>
          </template>
          <EvalQuestionList
            v-if="currentDataset"
            :questions="questions"
            :run-details="runDetails"
            :loading="questionsLoading"
            :evaluating-question-ids="evaluatingQuestionIds"
            :doc-tree-data="docTreeData"
            :doc-flat-list="docFlatList"
            :on-expand-detail="onQuestionExpandDetail"
            @evaluate="onEvaluateQuestion"
            @update:selected-doc-ids="onSelectedDocIdsChange"
            @question-updated="onQuestionUpdated"
          />
          <a-empty v-else description="请从左侧选择测试集" class="center-empty" />
        </Panel>
      </template>

      <template #right>
        <Panel title="评测运行" :icon="ThunderboltOutlined">
          <template #extra>
            <a-button
              type="text"
              size="small"
              :disabled="!selectedDatasetId || historyFullRuns.length < 2"
              title="对比两次评测结果"
              @click="compareVisible = true"
            >
              <template #icon><SwapOutlined /></template>
            </a-button>
            <a-tooltip title="收起侧边栏">
              <a-button size="small" class="header-icon-btn" @click="splitPanesRef?.toggleRight()">
                <template #icon><MenuUnfoldOutlined /></template>
              </a-button>
            </a-tooltip>
          </template>
          <EvalRunPanel
            :current-run="currentRun"
            :runs="runs"
            :load-run-details="fetchRunDetails"
            @create-run="runCreateVisible = true"
            @rerun="onRerunRun"
            @resume="onResumeRun"
            @stop="onStopRun"
            @select-run="onSelectHistoricalRun"
            @delete-run="onDeleteRun"
          />
        </Panel>
      </template>
    </SplitPanes>

    <EvalImportModal
      :visible="importModalVisible"
      @update:visible="importModalVisible = $event"
      @uploaded="onImported"
    />

    <EvalCompareModal
      v-model:open="compareVisible"
      :runs="historyFullRuns"
      :dataset-id="selectedDatasetId"
    />

    <EvalRunCreateModal
      v-model:open="runCreateVisible"
      :dataset-id="selectedDatasetId"
      :dataset-options="datasetOptions"
      :submitting="evalLoading"
      @confirm="onRunCreateConfirm"
    />

    <a-modal
      v-model:open="createModalVisible"
      title="新建测试集"
      @ok="handleCreateDataset"
    >
      <a-form layout="vertical">
        <a-form-item label="名称" required>
          <a-input v-model:value="createForm.title" placeholder="输入测试集名称" />
        </a-form-item>
        <a-form-item label="类别">
          <a-select v-model:value="createForm.category" placeholder="选择类别">
            <a-select-option value="knowledge">知识库评测</a-select-option>
            <a-select-option value="sop">SOP 评测</a-select-option>
            <a-select-option value="full_chain">全链路评测</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="描述">
          <a-textarea v-model:value="createForm.description" :rows="3" placeholder="可选描述" />
        </a-form-item>
      </a-form>
    </a-modal>

    <FolderModal
      :visible="folderModalVisible"
      :title="folderModalTitle"
      :loading="folderModalLoading"
      :name="folderForm.name"
      :parent-id="folderForm.parentId"
      :is-new="folderForm.isNew"
      :folder-tree-data="folderTreeData"
      @update:visible="folderModalVisible = $event"
      @update:name="folderForm.name = $event"
      @update:parent-id="folderForm.parentId = $event"
      @confirm="handleFolderModalOk"
    />

    <a-modal
      v-model:open="detailVisible"
      :title="detailDataset?.title || '测试集详情'"
      width="520px"
      :footer="null"
    >
      <template v-if="detailDataset">
        <a-descriptions :column="2" bordered size="small">
          <a-descriptions-item label="类别">{{ detailDataset.category }}</a-descriptions-item>
          <a-descriptions-item label="题目总数">{{ detailDataset.question_count }}</a-descriptions-item>
          <a-descriptions-item label="版本">{{ detailDataset.version }}</a-descriptions-item>
          <a-descriptions-item label="创建时间">{{ formatDate(detailDataset.created_at) }}</a-descriptions-item>
          <a-descriptions-item label="描述" :span="2">{{ detailDataset.description || '无' }}</a-descriptions-item>
        </a-descriptions>

        <div v-if="levelStats.length" class="level-distribution">
          <div class="level-title">题目等级分布</div>
          <div class="level-bars">
            <div v-for="s in levelStats" :key="s.level" class="level-bar-row">
              <span class="level-label">{{ s.level }}</span>
              <div class="level-bar-track">
                <div class="level-bar-fill" :style="{ width: s.percent + '%' }" />
              </div>
              <span class="level-count">{{ s.count }} 题</span>
            </div>
          </div>
        </div>
      </template>
    </a-modal>

  </div>

  <!-- 夜间测试视图：门禁结论历史（与日常测试共享页面，头部切换） -->
  <div v-if="evalView === 'nightly'" class="eval-nightly-wrap" :class="appClass">
    <div class="eval-nightly-content">
      <div class="page-header">
        <div class="page-header-left">
          <h2>夜间测试</h2>
        </div>
        <div class="page-header-right">
          <a-switch :checked="nightlyEnabled" size="small" @change="onNightlyEnabledChange" />
          <span class="page-header-label">每晚定时执行（北京时间）</span>
          <a-time-picker
            v-model:value="nightlyTime"
            format="HH:mm"
            value-format="HH:mm"
            :allow-clear="false"
            size="small"
            width="88px"
            @change="onNightlyTimeChange"
          />
          <a-button type="primary" size="small" @click="openNightlyRunModal">
            立即运行
          </a-button>
        </div>
      </div>
      <EvalNightlyPanel ref="nightlyPanelRef" @open-run="onNightlyOpenRun" />
    </div>
  </div>
</template>

<script setup lang="ts">
/** 评测管理页面 - 三栏布局 */
import { ref, computed, inject, onMounted, onBeforeUnmount, onActivated, onDeactivated, watch, type Ref } from 'vue'
import { App, message, Modal } from 'ant-design-vue'
import {
  DatabaseOutlined,
  UnorderedListOutlined,
  ThunderboltOutlined,
  EditOutlined,
  EyeOutlined,
  FolderAddOutlined,
  DeleteOutlined,
  PlusOutlined,
  UploadOutlined,
  ExportOutlined,
  SwapOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
} from '@ant-design/icons-vue'
import { SplitPanes, Panel, useTheme, useSplitPanesLayout, type DropEvent } from '@angineer/ui-kit'
import {
  EvalDatasetTree,
  EvalQuestionList,
  EvalRunPanel,
  EvalImportModal,
  EvalRunCreateModal,
} from '@angineer/evals-ui'
import { useEvalDataset, useEvalRun, useEvalDatasetTree } from '@angineer/evals-ui'
import type { EvalTreeNode } from '@angineer/evals-ui'
import type { EvalDataset, EvalQuestion, EvalRun } from '@angineer/evals-ui'
import FolderModal from './components/FolderModal.vue'
import EvalCompareModal from './components/EvalCompareModal.vue'
import EvalNightlyPanel from './components/EvalNightlyPanel.vue'
import { knowledgeApi } from '../api/knowledge'
import { useLibraryStore } from '../stores/library'
import { evalsApi } from '../api/evals'

/** keep-alive 的 include 按组件名匹配（见 App.vue 的 cachedViews），少这行会静默不缓存 */
defineOptions({ name: 'EvalManage' })

const { appClass, isDark } = useTheme()
const { modal } = App.useApp()

/** 三栏比例 / 收起状态持久化：与知识库三栏共用 ui-kit useSplitPanesLayout（独立 storageKey，互不影响） */
const workspaceRef = ref<HTMLElement | null>(null)
const splitPanesRef = ref<InstanceType<typeof SplitPanes> | null>(null)
const {
  panelRatios,
  leftCollapsed: leftPanelCollapsed,
  rightCollapsed: rightPanelCollapsed,
  setLeftCollapsed: onLeftCollapsedChange,
  setRightCollapsed: onRightCollapsedChange,
  onPanelResize,
} = useSplitPanesLayout({
  storageKey: 'angineer-admin-eval-layout-v1',
  defaultLeftRatio: 0.18,
  defaultRightRatio: 0.22,
  collapsedStorageKeys: {
    left: 'angineer-eval-left-collapsed',
    right: 'angineer-eval-right-collapsed',
  },
  getContainerWidth: () => workspaceRef.value?.clientWidth || window.innerWidth,
})

/** 视图模式（日常测试|夜间维护）：App.vue 头部统一控制，?view=nightly 深链进入 */
const evalView = inject<Ref<'workbench' | 'nightly'>>('evalView', ref<'workbench' | 'nightly'>('workbench'))

/** 夜间测试头部：定时开关+时间（改哪项存哪项，开关状态以服务端为准；改时间不再隐式开启定时）；
 *  立即运行打开面板内的执行计划确认框（计划/模型/并发先看清楚再起跑），running 态与轮询由面板负责 */
const nightlyPanelRef = ref<{ openRunModal: () => void } | null>(null)
const nightlyEnabled = ref(false)
const nightlyTime = ref<string>('01:00')

async function loadNightlySchedule() {
  try {
    const s = await evalsApi.getNightlySettings() as { enabled?: boolean; hour?: number; minute?: number }
    nightlyEnabled.value = !!s.enabled
    nightlyTime.value = `${String(s.hour ?? 1).padStart(2, '0')}:${String(s.minute ?? 0).padStart(2, '0')}`
  } catch { /* ignore */ }
}

async function saveNightlySchedule(enabled: boolean, time: string) {
  const [hour, minute] = time.split(':').map(Number)
  try {
    const s = await evalsApi.saveNightlySettings({ enabled, hour, minute }) as { enabled?: boolean; hour?: number; minute?: number }
    nightlyEnabled.value = !!s.enabled
    nightlyTime.value = `${String(s.hour ?? 1).padStart(2, '0')}:${String(s.minute ?? 0).padStart(2, '0')}`
    message.success(nightlyEnabled.value ? `已保存：每晚 ${nightlyTime.value} 执行` : '已保存：定时执行关闭')
  } catch (e: any) {
    message.error('保存失败: ' + (e?.response?.data?.detail || e.message || e))
    await loadNightlySchedule() // 保存失败回滚到服务端真值，避免 UI 与调度脱节
  }
}

function onNightlyEnabledChange(checked: unknown) {
  saveNightlySchedule(!!checked, nightlyTime.value)
}

function onNightlyTimeChange(time: string) {
  saveNightlySchedule(nightlyEnabled.value, time)
}

function openNightlyRunModal() {
  nightlyPanelRef.value?.openRunModal()
}

onMounted(() => {
  if (evalView.value === 'nightly') loadNightlySchedule()
})
watch(evalView, (v) => { if (v === 'nightly') loadNightlySchedule() })

/** 知识库树节点（用于规范筛选） */
interface DocTreeNode {
  key: string
  title: string
  type: 'folder' | 'document'
  parentId: string | null
  children?: DocTreeNode[]
}
const docTreeData = ref<DocTreeNode[]>([])
const docFlatList = ref<DocTreeNode[]>([])

/** 从扁平节点列表构建树 */
const buildDocTree = (nodes: any[]): { tree: DocTreeNode[]; flat: DocTreeNode[] } => {
  const flat: DocTreeNode[] = nodes.map(n => ({
    key: n.id,
    title: n.title,
    type: n.type,
    parentId: n.parent_id || null,
  }))
  const map = new Map<string, DocTreeNode>()
  for (const item of flat) map.set(item.key, item)
  const tree: DocTreeNode[] = []
  for (const item of flat) {
    if (!item.parentId || !map.has(item.parentId)) {
      tree.push(item)
    } else {
      const parent = map.get(item.parentId)!
      if (!parent.children) parent.children = []
      parent.children.push(item)
    }
  }
  return { tree, flat }
}

/** 加载知识库节点树 */
const fetchDocOptions = async (libraryId?: string) => {
  try {
    const lib = libraryId || useLibraryStore().libraryId || 'default'
    const resp = await knowledgeApi.getNodes(lib, true)
    const nodes = (resp as any)?.data || resp || []
    const list = Array.isArray(nodes) ? nodes : []
    const { tree, flat } = buildDocTree(list)
    docTreeData.value = tree
    docFlatList.value = flat
  } catch {
    docTreeData.value = []
    docFlatList.value = []
  }
}

const {
  datasets,
  currentDataset,
  questions,
  folders,
  fetchDatasets,
  fetchDataset,
  fetchQuestions,
  createDataset,
  deleteDataset,
  renameDataset,
  fetchFolders,
  createFolder,
  renameFolder,
  deleteFolder,
  updateFolder,
  moveDataset,
} = useEvalDataset()

const {
  treeData: evalTreeData,
  defaultExpandedKeys: evalDefaultExpandedKeys,
  isCategoryFolder: isCategoryFolderFn,
  isPersistedFolder: isPersistedFolderFn,
  getCategoryFromNode,
} = useEvalDatasetTree(datasets, folders)

const {
  currentRun,
  lastRun,
  runs,
  runDetails,
  evaluatingQuestionIds,
  isFullRun,
  startRun,
  fetchLastRun,
  evaluateQuestion,
  fetchQuestionDetail,
  fetchRunDetails,
  clearDetailsCache,
  selectHistoricalRun,
  startPolling,
  stopPolling,
  stopRun,
  deleteRun,
} = useEvalRun()

const selectedDatasetId = ref('')
const questionsLoading = ref(false)
const evalLoading = ref(false)
const importModalVisible = ref(false)
const compareVisible = ref(false)
const createModalVisible = ref(false)
const createForm = ref({ title: '', category: 'knowledge', description: '' })
const detailVisible = ref(false)
const detailDataset = ref<EvalDataset | null>(null)
const detailQuestions = ref<EvalQuestion[]>([])

const folderModalVisible = ref(false)
const folderModalLoading = ref(false)
const folderForm = ref({ name: '', parentId: undefined as string | undefined, isNew: true, nodeId: '', category: 'knowledge' as string, nodeType: 'folder' as 'folder' | 'dataset' })

/** 弹窗标题（重命名走同一 FolderModal：文件夹/测试集共用名称弹窗，不再手搓输入框 modal） */
const folderModalTitle = computed(() =>
  folderForm.value.isNew ? '新建文件夹' : (folderForm.value.nodeType === 'dataset' ? '重命名测试集' : '重命名文件夹')
)

/** 格式化日期 */
const formatDate = (iso: string) => {
  if (!iso) return '-'
  return new Date(iso).toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

/** 历史整体运行列表（过滤掉单题评测，用于对比弹窗） */
const historyFullRuns = computed(() => {
  if (!runs.value) return []
  return runs.value.filter(r => r.is_full_run !== false)
})

/** 左树组件引用：新增评测弹框切换题集时同步高亮 */
const evalTreeRef = ref<InstanceType<typeof EvalDatasetTree> | null>(null)

/** 构建 FolderModal 所需的文件夹树数据，追加根目录选项 */
const folderTreeData = computed(() => {
  const convert = (nodes: EvalTreeNode[]): any[] =>
    nodes
      .filter(n => n.isFolder)
      .map(n => ({
        value: n.key,
        title: n.title,
        children: n.children ? convert(n.children as EvalTreeNode[]) : [],
      }))
  return [
    { value: '__root__', title: '根目录' },
    ...convert(evalTreeData.value as EvalTreeNode[]),
  ]
})

/** 计算 L1-L4 等级分布 */
const levelStats = computed(() => {
  const total = detailQuestions.value.length
  if (!total) return []
  const counts: Record<string, number> = {}
  for (const q of detailQuestions.value) {
    const level = q.intent_level || 'L1'
    counts[level] = (counts[level] || 0) + 1
  }
  const levels = ['L1', 'L2', 'L3', 'L4']
  return levels
    .filter(l => counts[l])
    .map(l => ({
      level: l,
      count: counts[l],
      percent: Math.round((counts[l] / total) * 100),
    }))
})

const onDatasetSelect = async (keys: string[], _nodes: EvalTreeNode[]) => {
  if (keys.length === 0) return
  const key = keys[0]
  if (key.startsWith('folder-')) return
  selectedDatasetId.value = key
  const ds = datasets.value.find(d => d.dataset_id === key)
  if (ds?.library_id) {
    await fetchDocOptions(ds.library_id)
  }
  stopPolling()
  isFullRun.value = false
  clearDetailsCache()
  questionsLoading.value = true
  try {
    await fetchDataset(key)
    await fetchQuestions(key)
    await fetchLastRun(key)
  } finally {
    questionsLoading.value = false
  }
}

/** 当前规范筛选选中的文档 ID 列表 */
const selectedDocIds = ref<string[]>([])

const onSelectedDocIdsChange = (docIds: string[]) => {
  selectedDocIds.value = docIds
}

/** 题目文本编辑后刷新列表 */
const onQuestionUpdated = async () => {
  if (selectedDatasetId.value) {
    await fetchQuestions(selectedDatasetId.value)
  }
}

/** 展开单题时按需拉取该题的完整运行详情（含 trace 与分项分数） */
const onQuestionExpandDetail = async (questionId: string) => {
  const run = currentRun.value || lastRun.value
  if (!run?.run_id) return
  await fetchQuestionDetail(run.run_id, questionId)
}

/** 新增评测弹框：模型/题集在弹框选定；切换题集时同步切左树选中态 */
const runCreateVisible = ref(false)

/** 题集下拉选项：按左树层级带出文件夹路径前缀，避免同名测试集无法区分 */
const datasetOptions = computed(() => {
  const folderTitle = new Map(folders.value.map(f => [f.folder_id, f.title]))
  const pathOf = (dataset: EvalDataset): string => {
    const parts: string[] = [dataset.title]
    let parent = folderTitle.has(dataset.folder_id) ? dataset.folder_id : ''
    const guard = new Set<string>()
    while (parent && !guard.has(parent)) {
      guard.add(parent)
      parts.unshift(folderTitle.get(parent) || '')
      parent = folders.value.find(f => f.folder_id === parent)?.parent_folder_id || ''
    }
    return parts.filter(Boolean).join(' / ')
  }
  return datasets.value.map(d => ({ value: d.dataset_id, label: pathOf(d) }))
})

const startRunGuarded = async (
  datasetId: string,
  opts: {
    resumeRunId?: string
    restartRunId?: string
    configName?: string
    judgeConfigName?: string
    successText: string
  },
) => {
  evalLoading.value = true
  try {
    await startRun(datasetId, {
      docIds: datasetId === selectedDatasetId.value ? selectedDocIds.value : undefined,
      resumeRunId: opts.resumeRunId,
      restartRunId: opts.restartRunId,
      configName: opts.configName,
      judgeConfigName: opts.judgeConfigName,
    })
    message.success(opts.successText)
    return true
  } catch (e: any) {
    message.error(e.message || '启动评测失败')
    return false
  } finally {
    evalLoading.value = false
  }
}

const onRunCreateConfirm = async (payload: { datasetId: string; configName?: string; judgeConfigName?: string }) => {
  if (payload.datasetId !== selectedDatasetId.value) {
    await onDatasetSelect([payload.datasetId], [])
    const tree = evalTreeRef.value as { selectedKeys: string[] } | null
    if (tree) tree.selectedKeys = [payload.datasetId]
  }
  const ok = await startRunGuarded(payload.datasetId, {
    configName: payload.configName,
    judgeConfigName: payload.judgeConfigName,
    successText: '评测已启动',
  })
  if (ok) runCreateVisible.value = false
}

/** 置顶 item「重来」：原地重跑同一条记录（清空旧明细与进度，不新增 item）；
 * 运行中先优雅停止并等状态落定（stopRun 已保持轮询到终态），再发 restart */
const onRerunRun = async (run: EvalRun) => {
  const snap = (run.config_snapshot || {}) as { model?: string; judge_config?: string }
  if (run.status === 'running') {
    try {
      await stopRun(run.run_id)
    } catch {
      /* 已结束/已中断：直接进原地重启 */
    }
    for (let i = 0; i < 90; i++) {
      const cur = currentRun.value
      if (cur && cur.run_id === run.run_id && cur.status === 'running') {
        await new Promise((resolve) => setTimeout(resolve, 1000))
        continue
      }
      break
    }
  }
  await startRunGuarded(run.dataset_id, {
    restartRunId: run.run_id,
    configName: snap.model,
    judgeConfigName: snap.judge_config,
    successText: '评测已重新开始',
  })
}

/** 断点续跑：复用已中断 run 的已完成结果，只执行剩余题目 */
const onResumeRun = async (run: EvalRun) => {
  await startRunGuarded(run.dataset_id, {
    resumeRunId: run.run_id,
    successText: '断点续跑已启动',
  })
}

/** 停止当前评测任务 */
const onStopRun = async () => {
  const runId = currentRun.value?.run_id || runs.value.find(r => r.status === 'running')?.run_id
  if (!runId) return
  try {
    await stopRun(runId)
    message.info('评测已停止')
  } catch (e: any) {
    // 后端返回"未找到运行中的任务"= 线程已结束/后端已重启（僵尸 run），
    // 刷新状态并按已结束提示，而不是报一个让人困惑的 404 错误。
    if (String(e.message || '').includes('未找到运行中的任务')) {
      await fetchLastRun(selectedDatasetId.value)
      message.info('评测任务已结束或已中断')
    } else {
      message.error(e.message || '停止评测失败')
    }
  }
}

/** 选择历史运行记录查看 */
const onSelectHistoricalRun = async (runId: string) => {
  await selectHistoricalRun(runId)
}

/** 夜间维护面板点"在日常测试中打开"：切回工作台、选对测试集并加载该 run。
 * run 存于当前环境的评测库（本地/站点各自独立），查不到时以前会静默空态，必须言明 */
const onNightlyOpenRun = async (payload: { datasetId: string; runId: string }) => {
  evalView.value = 'workbench'
  try {
    if (selectedDatasetId.value !== payload.datasetId) {
      await onDatasetSelect([payload.datasetId], [])
    }
    await selectHistoricalRun(payload.runId)
    if (!runDetails.value.size) {
      message.warning(`当前环境评测库中未找到该 run（${payload.runId}）的逐题明细，无法展示；夜间记录与工作台共用同一环境的评测库，请确认浏览的是运行该次评测的环境`)
    }
  } catch (e) {
    message.error(String((e as Error)?.message || '打开夜间 run 失败'))
  }
}

const onDeleteRun = (runId: string) => {
  const run = runs.value.find(r => r.run_id === runId)
  const running = run?.status === 'running'
  Modal.confirm({
    title: '确认删除',
    content: running
      ? '该评测正在运行，删除将先停止它，再永久移除该次记录及题目详情，不可恢复。'
      : '删除后该次评测记录及所有题目详情将永久移除，不可恢复。',
    okText: '删除',
    okType: 'danger',
    cancelText: '取消',
    onOk: async () => {
      try {
        // 删除运行中的记录前必须先停，否则后台线程仍会往已删除的 run 写明细
        if (running) {
          try {
            await stopRun(runId)
          } catch {
            /* 已结束的 run 停不下：继续删除 */
          }
        }
        await deleteRun(runId, selectedDatasetId.value)
        message.success('评测记录已删除')
      } catch (e: any) {
        message.error(e.message || '删除失败')
      }
    },
  })
}

/** 对单道题目发起评测 */
const onEvaluateQuestion = async (questionId: string) => {
  if (!selectedDatasetId.value) return
  try {
    await evaluateQuestion(selectedDatasetId.value, questionId, selectedDocIds.value)
  } catch (e: any) {
    message.error(e.message || '评测失败')
  }
}

const onImported = async () => {
  importModalVisible.value = false
  await fetchDatasets()
  message.success('导入成功')
}

/** 打开手动创建空测试集弹窗 */
const openCreateModal = () => {
  createForm.value = { title: '', category: 'knowledge', description: '' }
  createModalVisible.value = true
}

const handleCreateDataset = async () => {
  if (!createForm.value.title) {
    message.warning('请输入名称')
    return
  }
  try {
    await createDataset(createForm.value)
    createModalVisible.value = false
    message.success('创建成功')
  } catch (e: any) {
    message.error(e.message || '创建失败')
  }
}

/** 处理重命名：文件夹与测试集统一走 FolderModal（与知识库一致） */
const onDatasetRename = (node: EvalTreeNode) => {
  const key = String(node.key)
  if (isCategoryFolderFn(node)) {
    message.info('分类目录不支持重命名')
    return
  }
  folderForm.value = {
    name: node.title,
    parentId: undefined,
    isNew: false,
    nodeId: key,
    category: getCategoryFromNode(node),
    nodeType: isPersistedFolderFn(node) ? 'folder' : 'dataset',
  }
  folderModalVisible.value = true
}

/** 处理删除 */
const onDatasetDelete = (node: EvalTreeNode) => {
  const key = String(node.key)
  if (isCategoryFolderFn(node)) {
    message.info('分类目录不支持删除')
    return
  }
  if (isPersistedFolderFn(node)) {
    modal.confirm({
      title: '确认删除',
      content: `删除后，文件夹内的数据集将移至分组根目录。确定删除文件夹「${node.title}」吗？`,
      okText: '删除',
      okType: 'danger',
      cancelText: '取消',
      async onOk() {
        try {
          await deleteFolder(key)
          message.success('删除成功')
        } catch (e: any) {
          throw new Error(e.message || '删除失败')
        }
      },
    })
    return
  }
  modal.confirm({
    title: '确认删除',
    content: `确定要删除测试集「${node.title}」吗？`,
    okText: '删除',
    okType: 'danger',
    cancelText: '取消',
    async onOk() {
      try {
        await deleteDataset(key)
        if (selectedDatasetId.value === key) {
          selectedDatasetId.value = ''
        }
        message.success('删除成功')
      } catch (e: any) {
        throw new Error(e.message || '删除失败')
      }
    },
  })
}

/** 处理查看详情 - 弹框显示题目数量与等级分布 */
const onDatasetView = async (node: EvalTreeNode) => {
  const key = String(node.key)
  if (isCategoryFolderFn(node)) return

  const ds = datasets.value.find(d => d.dataset_id === key)
  if (!ds) return

  detailDataset.value = ds
  detailVisible.value = true

  try {
    const data = await evalsApi.getQuestions(key)
    detailQuestions.value = (data as any)?.questions || []
  } catch {
    detailQuestions.value = []
  }
}

/** 处理导出测试集 - 下载 JSON 文件 */
const onDatasetExport = async (node: EvalTreeNode) => {
  const key = String(node.key)
  if (isCategoryFolderFn(node)) return
  try {
    const data = await evalsApi.exportDataset(key)
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${node.title}.json`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
    message.success('导出成功')
  } catch (e: any) {
    message.error(e.message || '导出失败')
  }
}

/** 处理新建文件夹，记录当前分组类别以便"根目录"选择时保留上下文 */
const onAddFolder = (parentNode: EvalTreeNode | null) => {
  const category = parentNode ? getCategoryFromNode(parentNode) : 'knowledge'
  folderForm.value = {
    name: '',
    parentId: parentNode?.key || '__root__',
    isNew: true,
    nodeId: '',
    category,
    nodeType: 'folder',
  }
  folderModalVisible.value = true
}

/** 处理添加测试集（上传 JSON 文件导入） */
const onAddFile = (_node: EvalTreeNode) => {
  importModalVisible.value = true
}

/**
 * 落位后按知识库同款机制把 SmartTree 的乐观移动持久化：
 * 逐个兄弟节点写回父级 + sort_order（DropEvent.siblings 已含被拖节点的新位置），空隙排序不再落空。
 * 分类目录（folder-knowledge/sop/full_chain）是后端真实 tree_node 记录，与知识库对根节点的处理一致，照常参与落库。
 */
const persistDroppedSiblings = async (siblings: DropEvent['siblings'], targetParentKey?: string | null) => {
  const parentKey = targetParentKey ?? ''
  for (let index = 0; index < siblings.length; index++) {
    const key = String(siblings[index].key)
    if (isPersistedFolderFn({ key } as EvalTreeNode)) {
      await updateFolder(key, { parent_folder_id: parentKey, sort_order: index })
    } else {
      await moveDataset(key, parentKey, index)
    }
  }
}

const refreshEvalTree = async () => {
  await Promise.all([fetchDatasets(), fetchFolders()])
}

/** 处理树节点拖放 */
const onTreeDrop = async (event: DropEvent) => {
  const { dragKey, targetParentKey, siblings } = event

  if (isCategoryFolderFn({ key: dragKey } as EvalTreeNode)) return

  try {
    await persistDroppedSiblings(siblings, targetParentKey)
    message.success('移动成功')
  } catch (e: any) {
    message.error(e.message || '移动失败')
  } finally {
    await refreshEvalTree()
  }
}

/** 处理拖到根目录（与知识库同款：其余根级节点按序落库，被拖节点排最后） */
const onTreeDropRoot = async (dragNodeKeys: string[]) => {
  const dragNodeKey = dragNodeKeys[0]
  if (!dragNodeKey) return
  if (isCategoryFolderFn({ key: dragNodeKey } as EvalTreeNode)) return
  try {
    const roots = evalTreeData.value as EvalTreeNode[]
    const rootSiblings = roots.filter(n => String(n.key) !== dragNodeKey)
    await persistDroppedSiblings(rootSiblings, null)
    if (isPersistedFolderFn({ key: dragNodeKey } as EvalTreeNode)) {
      const dragged = roots.find(n => String(n.key) === dragNodeKey)
      await updateFolder(dragNodeKey, {
        parent_folder_id: '',
        sort_order: rootSiblings.length,
        // 分类以节点真实值为准，不能按 key 猜测覆盖（拖普通子文件夹到根时 getCategoryFromNode({key}) 会误判成 knowledge）
        ...(dragged?.category ? { category: dragged.category } : {}),
      })
    } else {
      await moveDataset(dragNodeKey, '', rootSiblings.length)
    }
    message.success('已移动到根目录')
  } catch (e: any) {
    message.error(e.message || '移动失败')
  } finally {
    await refreshEvalTree()
  }
}

/** 处理无效拖放（SmartTree 拖失败仍是乐观移动，须回读还原视图，与知识库一致） */
const onInvalidDrop = async (reason: string) => {
  const messages: Record<string, string> = {
    'same-node': '不能拖到自身',
    'drop-to-descendant': '不能拖到子节点中',
    'drop-into-file': '不能拖入文件节点',
  }
  message.warning(messages[reason] || '无效的拖放操作')
  await refreshEvalTree()
}

/** 处理文件夹弹窗确认 */
const handleFolderModalOk = async () => {
  if (!folderForm.value.name.trim()) {
    message.error('请输入文件夹名称')
    return
  }

  folderModalLoading.value = true
  try {
    if (folderForm.value.isNew) {
      const parentId = folderForm.value.parentId
      const isRoot = !parentId || parentId === '__root__'
      const category = isRoot ? folderForm.value.category : getCategoryFromNode({ key: parentId } as EvalTreeNode)
      const parentFolderId = (!isRoot && parentId.startsWith('folder-')) ? parentId : ''
      await createFolder({
        title: folderForm.value.name.trim(),
        category,
        parent_folder_id: parentFolderId || undefined,
      })
      message.success('创建成功')
    } else if (folderForm.value.nodeType === 'dataset') {
      await renameDataset(folderForm.value.nodeId, folderForm.value.name.trim())
      message.success('重命名成功')
    } else {
      await renameFolder(folderForm.value.nodeId, folderForm.value.name.trim())
      message.success('重命名成功')
    }
    folderModalVisible.value = false
  } catch (e: any) {
    message.error(e.message || '操作失败')
  } finally {
    folderModalLoading.value = false
  }
}

onMounted(() => {
  fetchDatasets()
  fetchFolders()
  fetchDocOptions()
})

onBeforeUnmount(() => {
  stopPolling()
})

/**
 * 缓存后 onMounted 只跑一次：回来时刷新测试集/文件夹两个列表；左侧有选中测试集时补刷最近一次运行，
 * 否则停表期间的状态会永远停在离开时的快照（跑着的 run 在 deactivate 时被停了表）。
 * activated 首次挂载也会触发，跳过第一次以免重复取数。
 */
let activationSkipped = false
onActivated(() => {
  if (!activationSkipped) {
    activationSkipped = true
    return
  }
  fetchDatasets()
  fetchFolders()
  const run = currentRun.value
  if (run && run.status === 'running') startPolling(run.run_id)
  else if (selectedDatasetId.value) fetchLastRun(selectedDatasetId.value)
})

/** deactivate 不触发 onBeforeUnmount：评测轮询在这里收口，回到本视图时再接上 */
onDeactivated(stopPolling)
</script>

<style lang="less" scoped>
.eval-workspace {
  height: 100%;
  background: var(--bg-primary);
  transition: background-color 0.3s;

  // 三栏 Panel header：背景与内容区统一，下边线用灰色分隔（对齐知识库三栏）
  :deep(.panel-header) {
    background: var(--panel-bg);
    border-bottom: 1px solid var(--panel-header-divider, var(--border-color));
  }

  // 左侧测试集树区域：暗色下用纯黑（SmartTree 本身透明，背景由容器承载）
  :deep(.tree-panel-content) {
    background: var(--tree-bg, var(--panel-bg));
  }
}

.eval-nightly-wrap {
  height: 100%;
  background: var(--bg-primary);
  transition: background-color 0.3s;
  padding: 24px;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
}
.eval-nightly-content {
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
  h2 {
    margin: 0;
    color: var(--text-primary);
  }
}
.page-header-label {
  color: var(--text-tertiary);
  font-size: 14px;
}
.page-header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.workspace-container {
  height: 100%;
}

.tree-container {
  height: 100%;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 5px;
  width: 100%;
  min-width: 0;
  background: transparent;

  :deep(.smart-tree) {
    background: transparent;
  }

  // 删除类按钮常驻大红色（SmartTree 基础色特异性高，需 !important 覆盖）
  :deep(.action-btn.delete) {
    color: #ff4d4f !important;

    &:hover {
      color: #ff4d4f !important;
      background: rgba(255, 77, 79, 0.15);
    }
  }
}

.tree-panel-content {
  background: transparent;
}

.header-icon-btn {
  padding-inline: 8px;
}

.question-count {
  font-size: 12px;
  color: var(--text-secondary, rgba(0, 0, 0, 0.45));
}

.center-empty {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.level-distribution {
  margin-top: 16px;

  .level-title {
    font-weight: 500;
    margin-bottom: 8px;
    color: var(--text-primary, rgba(0, 0, 0, 0.85));
  }

  .level-bars {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .level-bar-row {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .level-label {
    width: 24px;
    font-size: 12px;
    color: var(--text-secondary, rgba(0, 0, 0, 0.45));
  }

  .level-bar-track {
    flex: 1;
    height: 16px;
    background: var(--bg-tertiary);
    border-radius: 4px;
    overflow: hidden;
  }

  .level-bar-fill {
    height: 100%;
    background: var(--primary-color);
    border-radius: 4px;
    transition: width 0.3s;
  }

  .level-count {
    width: 48px;
    font-size: 12px;
    text-align: right;
    color: var(--text-secondary, rgba(0, 0, 0, 0.45));
  }
}

</style>
