<template>
  <div ref="workspaceRef" class="eval-workspace" :class="{ 'dark-mode': isDark }">
    <SplitPanes
      class="workspace-container"
      :initial-left-ratio="0.18"
      :initial-right-ratio="0.22"
    >
      <template #left>
        <Panel title="测试集" :icon="DatabaseOutlined">
          <EvalDatasetTree
            :datasets="datasets"
            :selected-id="selectedDatasetId"
            @select="onDatasetSelect"
            @import="importModalVisible = true"
            @create="showCreateModal"
          />
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
      v-model:visible="importModalVisible"
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
  </div>
</template>

<script setup lang="ts">
/** 评测管理页面 - 三栏布局 */
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { message } from 'ant-design-vue'
import {
  DatabaseOutlined,
  UnorderedListOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons-vue'
import { SplitPanes, Panel, useTheme } from '@angineer/ui-kit'
import {
  EvalDatasetTree,
  EvalQuestionList,
  EvalRunPanel,
  EvalImportModal,
  EvalCompareView,
} from '@angineer/evals-ui'
import { useEvalDataset, useEvalRun, useEvalCompare } from '@angineer/evals-ui'
import { evalsApi } from '@/api/evals'
import type { EvalDataset, EvalQuestion, EvalRun, EvalRunDetail } from '@angineer/evals-ui'

const { isDark } = useTheme()
const workspaceRef = ref<HTMLElement | null>(null)

const {
  datasets,
  currentDataset,
  questions,
  loading: datasetsLoading,
  fetchDatasets,
  fetchDataset,
  fetchQuestions,
  createDataset,
} = useEvalDataset()

const {
  currentRun,
  runs,
  loading: runLoading,
  runDetails,
  startRun,
  fetchRun,
  fetchRuns,
  stopPolling,
} = useEvalRun()

const { compareResult, compare: doCompare, clear: clearCompare } = useEvalCompare()

const selectedDatasetId = ref('')
const questionsLoading = ref(false)
const importModalVisible = ref(false)
const compareVisible = ref(false)
const createModalVisible = ref(false)
const createForm = ref({ title: '', category: 'knowledge', description: '' })

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

const showCreateModal = () => {
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
  display: flex;
  flex-direction: column;
  background: var(--bg-primary, #141414);
  transition: background-color 0.3s;

  &.dark-mode {
    background: #141414;
  }

  &:not(.dark-mode) {
    background: #f5f5f5;
  }
}

.workspace-container {
  flex: 1;
  min-height: 0;
}

.question-count {
  font-size: 12px;
  color: var(--text-secondary, rgba(255, 255, 255, 0.45));
}

.center-empty {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
