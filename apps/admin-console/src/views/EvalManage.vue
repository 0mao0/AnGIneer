<template>
  <div ref="workspaceRef" class="eval-workspace" :class="appClass">
    <SplitPanes
      class="workspace-container"
      :initial-left-ratio="0.18"
      :initial-right-ratio="0.22"
    >
      <template #left>
        <Panel title="测试集" :icon="DatabaseOutlined" contentClass="tree-panel-content">
          <div class="tree-container">
            <EvalDatasetTree
              ref="evalTreeRef"
              :tree-data="evalTreeData"
              :default-expanded-keys="evalDefaultExpandedKeys"
              :default-selected-keys="selectedDatasetId ? [selectedDatasetId] : []"
              @select="onDatasetSelect"
              @rename="onDatasetRename"
              @delete="onDatasetDelete"
              @view="onDatasetView"
              @add-folder="onAddFolder"
              @add-file="onAddFile"
            />
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
          />
          <a-empty v-else description="请从左侧选择测试集" class="center-empty" />
        </Panel>
      </template>

      <template #right>
        <Panel title="评测运行" :icon="ThunderboltOutlined">
          <EvalRunPanel
            :dataset-id="selectedDatasetId"
            :current-run="currentRun"
            @run="onStartRun"
            @compare="compareVisible = true"
          />
        </Panel>
      </template>
    </SplitPanes>

    <EvalImportModal
      :visible="importModalVisible"
      @update:visible="importModalVisible = $event"
      @uploaded="onImported"
    />

    <a-modal
      v-model:open="compareVisible"
      title="历史对比"
      width="800px"
      :footer="null"
    >
      <EvalCompareView :runs="runs" />
    </a-modal>

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
import { App, Input, message } from 'ant-design-vue'
import {
  DatabaseOutlined,
  UnorderedListOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons-vue'
import { SplitPanes, Panel, useTheme } from '@angineer/ui-kit'
import type { SmartTreeNode } from '@angineer/ui-kit'
import {
  EvalDatasetTree,
  EvalQuestionList,
  EvalRunPanel,
  EvalImportModal,
  EvalCompareView,
} from '@angineer/evals-ui'
import { useEvalDataset, useEvalRun, useEvalDatasetTree } from '@angineer/evals-ui'
import type { EvalTreeNode } from '@angineer/evals-ui'
import type { EvalDataset, EvalQuestion } from '@angineer/evals-ui'

const { appClass } = useTheme()
const { modal } = App.useApp()
const workspaceRef = ref<HTMLElement | null>(null)
const evalTreeRef = ref<InstanceType<typeof EvalDatasetTree> | null>(null)

const {
  datasets,
  currentDataset,
  questions,
  fetchDatasets,
  fetchDataset,
  fetchQuestions,
  createDataset,
  deleteDataset,
  renameDataset,
} = useEvalDataset()

const {
  treeData: evalTreeData,
  defaultExpandedKeys: evalDefaultExpandedKeys,
  isGroupNode: isGroupNodeFn,
  getCategoryFromGroupKey,
} = useEvalDatasetTree(datasets)

const {
  currentRun,
  runs,
  runDetails,
  startRun,
  fetchRuns,
  stopPolling,
} = useEvalRun()

const selectedDatasetId = ref('')
const questionsLoading = ref(false)
const importModalVisible = ref(false)
const compareVisible = ref(false)
const createModalVisible = ref(false)
const createForm = ref({ title: '', category: 'knowledge', description: '' })
const detailVisible = ref(false)
const detailDataset = ref<EvalDataset | null>(null)
const detailQuestions = ref<EvalQuestion[]>([])

/** 格式化日期 */
const formatDate = (iso: string) => {
  if (!iso) return '-'
  return new Date(iso).toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

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

const onDatasetSelect = async (datasetId: string) => {
  selectedDatasetId.value = datasetId
  questionsLoading.value = true
  try {
    await fetchDataset(datasetId)
    await fetchQuestions(datasetId)
    await fetchRuns(datasetId)
  } finally {
    questionsLoading.value = false
  }
}

const onStartRun = async () => {
  if (!selectedDatasetId.value) return
  try {
    await startRun(selectedDatasetId.value)
    message.success('评测已启动')
  } catch (e: any) {
    message.error(e.message || '启动评测失败')
  }
}

const onImported = async () => {
  importModalVisible.value = false
  await fetchDatasets()
  message.success('导入成功')
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

/** 从节点提取 category */
const getCategoryFromNode = (node: SmartTreeNode): string => {
  if (isGroupNodeFn(node)) {
    return getCategoryFromGroupKey(String(node.key))
  }
  return (node as EvalTreeNode).category || 'knowledge'
}

/** 处理重命名 */
const onDatasetRename = (node: EvalTreeNode) => {
  const key = String(node.key)
  if (key.startsWith('group-')) {
    message.info('分类目录不支持重命名')
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
  if (key.startsWith('group-')) {
    message.info('分类目录不支持删除')
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
  if (key.startsWith('group-')) return

  const ds = datasets.value.find(d => d.dataset_id === key)
  if (!ds) return

  detailDataset.value = ds
  detailVisible.value = true

  try {
    const resp = await fetch(`/api/evals/datasets/${key}/questions`)
    if (resp.ok) {
      const data = await resp.json()
      detailQuestions.value = data.questions || []
    }
  } catch {
    detailQuestions.value = []
  }
}

/** 处理新建文件夹/测试集 */
const onAddFolder = (parentNode: EvalTreeNode | null) => {
  const category = parentNode ? getCategoryFromNode(parentNode) : 'knowledge'
  createForm.value = { title: '', category, description: '' }
  createModalVisible.value = true
}

/** 处理添加测试集（在分类目录下新建） */
const onAddFile = (node: EvalTreeNode) => {
  const category = getCategoryFromNode(node)
  createForm.value = { title: '', category, description: '' }
  createModalVisible.value = true
}

onMounted(() => {
  fetchDatasets()
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
