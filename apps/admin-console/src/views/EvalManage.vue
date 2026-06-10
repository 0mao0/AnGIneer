<template>
  <div ref="workspaceRef" class="eval-workspace" :class="appClass">
    <SplitPanes
      class="workspace-container"
      :initial-left-ratio="0.18"
      :initial-right-ratio="0.22"
    >
      <template #left>
        <Panel title="测试集" :icon="DatabaseOutlined" contentClass="tree-panel-content">
          <template #extra>
            <a-button type="text" size="small" title="手动创建空测试集" @click="openCreateModal">
              <template #icon><PlusOutlined /></template>
            </a-button>
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
                  <EditOutlined class="action-icon" title="重命名" @click.stop="onDatasetRename(node as EvalTreeNode)" />
                  <UploadOutlined class="action-icon" title="导入测试集" @click.stop="onAddFile(node as EvalTreeNode)" />
                  <FolderAddOutlined class="action-icon" title="添加子文件夹" @click.stop="onAddFolder(node as EvalTreeNode)" />
                  <DeleteOutlined class="action-icon delete" title="删除" @click.stop="onDatasetDelete(node as EvalTreeNode)" />
                </template>
                <template v-else>
                  <EditOutlined class="action-icon" title="重命名" @click.stop="onDatasetRename(node as EvalTreeNode)" />
                  <EyeOutlined class="action-icon" title="查看详情" @click.stop="onDatasetView(node as EvalTreeNode)" />
                  <ExportOutlined class="action-icon" title="导出" @click.stop="onDatasetExport(node as EvalTreeNode)" />
                  <DeleteOutlined class="action-icon delete" title="删除" @click.stop="onDatasetDelete(node as EvalTreeNode)" />
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
          </template>
          <EvalRunPanel
            :dataset-id="selectedDatasetId"
            :current-run="currentRun"
            :last-run="lastRun"
            :is-full-run="isFullRun"
            :last-run-time="lastRunTime"
            :loading="evalLoading"
            :runs="runs"
            @run="onStartRun"
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
      :title="folderForm.isNew ? '新建文件夹' : '重命名文件夹'"
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
</template>

<script setup lang="ts">
/** 评测管理页面 - 三栏布局 */
import { ref, computed, h, onMounted, onBeforeUnmount } from 'vue'
import { App, Input, message, Modal } from 'ant-design-vue'
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
} from '@ant-design/icons-vue'
import { SplitPanes, Panel, useTheme, type DropEvent } from '@angineer/ui-kit'
import {
  EvalDatasetTree,
  EvalQuestionList,
  EvalRunPanel,
  EvalImportModal,
} from '@angineer/evals-ui'
import { useEvalDataset, useEvalRun, useEvalDatasetTree } from '@angineer/evals-ui'
import type { EvalTreeNode } from '@angineer/evals-ui'
import type { EvalDataset, EvalQuestion } from '@angineer/evals-ui'
import FolderModal from './components/FolderModal.vue'
import EvalCompareModal from './components/EvalCompareModal.vue'
import { knowledgeApi } from '../api/knowledge'
import { evalsApi } from '../api/evals'

const { appClass } = useTheme()
const { modal } = App.useApp()

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
const fetchDocOptions = async () => {
  try {
    const resp = await knowledgeApi.getNodes('default', true)
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
  selectHistoricalRun,
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
const folderForm = ref({ name: '', parentId: undefined as string | undefined, isNew: true, nodeId: '', category: 'knowledge' as string })

/** 格式化日期 */
const formatDate = (iso: string) => {
  if (!iso) return '-'
  return new Date(iso).toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

/** 历史整体运行列表（过滤掉单题评测，用于对比弹窗） */
const historyFullRuns = computed(() => {
  if (!runs.value) return []
  return runs.value.filter(r => r.is_full_run !== false && r.is_full_run !== 0)
})

/** 格式化上次整体测试时间，格式如 "04-09 18:42" */
const lastRunTime = computed(() => {
  const iso = lastRun.value?.completed_at || lastRun.value?.started_at
  if (!iso) return undefined
  const d = new Date(iso)
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const mi = String(d.getMinutes()).padStart(2, '0')
  return `${mm}-${dd} ${hh}:${mi}`
})

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
  stopPolling()
  isFullRun.value = false
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

const onStartRun = async () => {
  if (!selectedDatasetId.value) return
  evalLoading.value = true
  try {
    await startRun(selectedDatasetId.value, selectedDocIds.value)
    message.success('评测已启动')
  } catch (e: any) {
    message.error(e.message || '启动评测失败')
  } finally {
    evalLoading.value = false
  }
}

/** 停止当前评测任务 */
const onStopRun = async () => {
  if (!currentRun.value?.run_id) return
  try {
    await stopRun(currentRun.value.run_id)
    message.info('评测已停止')
  } catch (e: any) {
    message.error(e.message || '停止评测失败')
  }
}

/** 选择历史运行记录查看 */
const onSelectHistoricalRun = async (runId: string) => {
  await selectHistoricalRun(runId)
}

const onDeleteRun = (runId: string) => {
  Modal.confirm({
    title: '确认删除',
    content: '删除后该次评测记录及所有题目详情将永久移除，不可恢复。',
    okText: '删除',
    okType: 'danger',
    cancelText: '取消',
    onOk: async () => {
      try {
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

/** 处理重命名 */
const onDatasetRename = (node: EvalTreeNode) => {
  const key = String(node.key)
  if (isCategoryFolderFn(node)) {
    message.info('分类目录不支持重命名')
    return
  }
  if (isPersistedFolderFn(node)) {
    folderForm.value = {
      name: node.title,
      parentId: undefined,
      isNew: false,
      nodeId: key,
      category: getCategoryFromNode(node),
    }
    folderModalVisible.value = true
    return
  }
  const renameValue = ref(node.title)
  modal.confirm({
    title: '重命名测试集',
    content: () =>
      h(Input, {
        value: renameValue.value,
        'onUpdate:value': (val: string) => { renameValue.value = val },
        placeholder: '输入新名称',
        style: { marginTop: '8px' },
      }),
    okText: '确认',
    cancelText: '取消',
    async onOk() {
      const trimmed = renameValue.value?.trim()
      if (!trimmed) throw new Error('名称不能为空')
      if (trimmed === node.title) return
      try {
        await renameDataset(key, trimmed)
        message.success('重命名成功')
      } catch (e: any) {
        throw new Error(e.message || '重命名失败')
      }
    },
  })
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
  }
  folderModalVisible.value = true
}

/** 处理添加测试集（上传 JSON 文件导入） */
const onAddFile = (_node: EvalTreeNode) => {
  importModalVisible.value = true
}

/** 处理树节点拖放 */
const onTreeDrop = async (event: DropEvent) => {
  const { dragKey, targetParentKey } = event

  if (isCategoryFolderFn({ key: dragKey } as EvalTreeNode)) return

  try {
    if (isPersistedFolderFn({ key: dragKey } as EvalTreeNode)) {
      await updateFolder(dragKey, { parent_folder_id: targetParentKey || '' })
    } else {
      await moveDataset(dragKey, targetParentKey || '')
    }
    message.success('移动成功')
  } catch (e: any) {
    message.error(e.message || '移动失败')
    await fetchDatasets()
    await fetchFolders()
  }
}

/** 处理拖到根目录 */
const onTreeDropRoot = async (dragNodeKey: string) => {
  if (isCategoryFolderFn({ key: dragNodeKey } as EvalTreeNode)) return
  try {
    if (isPersistedFolderFn({ key: dragNodeKey } as EvalTreeNode)) {
      const category = getCategoryFromNode({ key: dragNodeKey } as EvalTreeNode)
      await updateFolder(dragNodeKey, { parent_folder_id: '', category })
      message.success('已移动到根目录')
    } else {
      await moveDataset(dragNodeKey, '')
      message.success('已移动到根目录')
    }
  } catch (e: any) {
    message.error(e.message || '移动失败')
    await fetchDatasets()
  }
}

/** 处理无效拖放 */
const onInvalidDrop = (reason: string) => {
  const messages: Record<string, string> = {
    'same-node': '不能拖到自身',
    'drop-to-descendant': '不能拖到子节点中',
    'drop-into-file': '不能拖入文件节点',
  }
  message.warning(messages[reason] || '无效的拖放操作')
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
</script>

<style lang="less" scoped>
.eval-workspace {
  height: 100%;
  background: var(--bg-primary);
  transition: background-color 0.3s;
}

.workspace-container {
  height: 100%;
}

.tree-container {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 5px;
  min-height: 0;

  :deep(.smart-tree) {
    background: transparent;
    flex: 1;
  }
}

.tree-panel-content {
  background: transparent;
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
