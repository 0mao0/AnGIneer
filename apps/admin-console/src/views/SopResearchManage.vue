<template>
  <div class="sop-research-workspace" :class="appClass">
    <SplitPanes
      class="workspace-container"
      :initial-left-ratio="0.18"
      :initial-right-ratio="0.28"
    >
      <template #left>
        <Panel title="研究项目" :icon="ExperimentOutlined" contentClass="tree-panel-content">
          <template #extra>
            <a-tooltip title="刷新">
              <a-button type="text" size="small" @click="handleRefresh">
                <template #icon><ReloadOutlined /></template>
              </a-button>
            </a-tooltip>
          </template>
          <ResearchProjectList
            :projects="projects"
            :selected-project-id="selectedProjectId"
            :loading="projectsLoading"
            @select-project="handleSelectProject"
            @create-project="showCreateProjectModal"
            @refresh="handleRefresh"
          />
        </Panel>
      </template>

      <template #center>
        <Panel title="研究运行" :icon="ExperimentOutlined">
          <template #extra>
            <a-space>
              <a-button
                v-if="selectedRun"
                size="small"
                @click="handleRefreshRun"
              >
                <template #icon><ReloadOutlined /></template>
              </a-button>
            </a-space>
          </template>
          <div class="center-content">
            <ResearchRunPanel
              :run="selectedRun"
              :loading="runLoading"
              @start-run="handleStartRun"
              @stop-run="handleStopRun"
              @retry-run="handleRetryRun"
            />
            <ResearchDraftTable
              v-if="selectedRun"
              :drafts="drafts"
              :eval-drafts="evalDrafts"
              :selected-draft-id="selectedDraftId"
              :loading="draftsLoading"
              @select-draft="handleSelectDraft"
              @approve-sop="handleApproveSop"
              @approve-eval="handleApproveEval"
              @reject-draft="handleRejectDraft"
            />
          </div>
        </Panel>
      </template>

      <template #right>
        <Panel title="草稿详情" :icon="FileTextOutlined" contentClass="right-panel-content">
          <ResearchDraftDetail
            :draft="selectedDraft"
            :detail="draftDetail"
            :type="selectedDraftType"
            :loading="draftDetailLoading"
            @approve-sop="handleApproveSop"
            @approve-eval="handleApproveEval"
            @reject-draft="handleRejectDraft"
          />
        </Panel>
      </template>
    </SplitPanes>

    <a-modal
      :open="createModalVisible"
      title="新建研究项目"
      ok-text="创建"
      cancel-text="取消"
      :confirm-loading="createLoading"
      @ok="handleCreateProject"
      @update:open="handleCreateModalOpen"
    >
      <a-form layout="vertical">
        <a-form-item label="项目标题">
          <a-input v-model:value="createForm.title" placeholder="输入项目标题" />
        </a-form-item>
        <a-form-item label="知识源">
          <a-select
            v-model:value="createForm.doc_id"
            placeholder="选择文档"
            :loading="docOptionsLoading"
            :options="docOptions"
            option-filter-prop="label"
            show-search
            @change="handleDocSelect"
          />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { message } from 'ant-design-vue'
import {
  ExperimentOutlined,
  ReloadOutlined,
  FileTextOutlined,
} from '@ant-design/icons-vue'
import { SplitPanes, Panel, useTheme } from '@angineer/ui-kit'
import {
  ResearchProjectList,
  ResearchRunPanel,
  ResearchDraftTable,
  ResearchDraftDetail,
} from '@angineer/sop-ui'
import type {
  ResearchProject,
  ResearchRun,
  SopResearchDraft,
  EvalResearchDraft,
} from '@angineer/sop-ui'
import { sopResearchApi } from '@/api/sopResearch'

const { appClass } = useTheme()

const projects = ref<ResearchProject[]>([])
const projectsLoading = ref(false)
const selectedProjectId = ref('')
const runs = ref<ResearchRun[]>([])
const selectedRunId = ref('')
const runLoading = ref(false)
const drafts = ref<SopResearchDraft[]>([])
const evalDrafts = ref<EvalResearchDraft[]>([])
const draftsLoading = ref(false)
const selectedDraftId = ref('')
const draftDetail = ref<any>(null)
const draftDetailLoading = ref(false)
const pollingTimer = ref<number | null>(null)

const selectedRun = computed(() => {
  if (!selectedRunId.value) return null
  return runs.value.find(r => r.run_id === selectedRunId.value) || null
})

const selectedDraftType = ref<'sop' | 'eval'>('sop')
const selectedDraft = computed(() => {
  if (!selectedDraftId.value) return null
  if (selectedDraftType.value === 'eval') {
    return evalDrafts.value.find(d => d.draft_id === selectedDraftId.value) || null
  }
  return drafts.value.find(d => d.draft_id === selectedDraftId.value) || null
})

const createModalVisible = ref(false)
const createLoading = ref(false)
const createForm = ref({
  title: '',
  library_id: '',
  doc_id: '',
})

const docOptions = ref<Array<{ label: string; value: string; library_id: string; doc_title: string }>>([])
const docOptionsLoading = ref(false)

interface KnowledgeNodeLike {
  id: string
  title: string
  type: string
  library_id?: string
  visible?: boolean | number
  status?: string
}

async function loadDocOptions() {
  docOptionsLoading.value = true
  try {
    const resp = await fetch('/api/knowledge/nodes?library_id=default&visible=true')
    if (!resp.ok) {
      throw new Error(`GET /knowledge/nodes failed: ${resp.status}`)
    }
    const res = await resp.json()
    let nodes: KnowledgeNodeLike[]
    if (Array.isArray(res)) {
      nodes = res
    } else if (res && Array.isArray(res.data)) {
      nodes = res.data
    } else if (res && Array.isArray(res.nodes)) {
      nodes = res.nodes
    } else {
      console.warn('[loadDocOptions] unexpected response shape:', res)
      nodes = []
    }
    docOptions.value = nodes
      .filter(n => n.type === 'document' && n.status !== 'failed')
      .map(n => ({
        label: `${n.title} (${n.id})`,
        value: n.id,
        library_id: n.library_id || 'default',
        doc_title: n.title,
      }))
  } catch (e) {
    console.error('[loadDocOptions] failed:', e)
    message.error('加载文档列表失败')
  } finally {
    docOptionsLoading.value = false
  }
}

function handleDocSelect(value: string) {
  const opt = docOptions.value.find(o => o.value === value)
  if (opt) {
    createForm.value.library_id = opt.library_id
    createForm.value.doc_id = opt.value
    if (!createForm.value.title.trim()) {
      createForm.value.title = opt.doc_title
    }
  }
}

function handleCreateModalOpen(open: boolean) {
  createModalVisible.value = open
  if (open) {
    loadDocOptions()
  }
}

const activeRunStatuses = ['running', 'queued', 'evidence_prepare', 'candidate_extract', 'socratic_expand', 'sop_synthesize', 'eval_generate', 'rule_validate', 'score_and_rank', 'cancel_requested']

async function loadProjects() {
  projectsLoading.value = true
  try {
    const res = await sopResearchApi.listProjects()
    projects.value = res.projects
  } catch (e) {
    console.error('[loadProjects] failed:', e)
    message.error('加载项目列表失败')
  } finally {
    projectsLoading.value = false
  }
}

async function handleSelectProject(projectId: string) {
  selectedProjectId.value = projectId
  selectedRunId.value = ''
  drafts.value = []
  evalDrafts.value = []
  selectedDraftId.value = ''
  draftDetail.value = null
  await loadRuns(projectId)
}

async function loadRuns(projectId: string) {
  runLoading.value = true
  try {
    const res = await sopResearchApi.listRuns(projectId)
    runs.value = res.runs
    if (runs.value.length > 0) {
      selectedRunId.value = runs.value[0].run_id
      await loadDrafts(selectedRunId.value)
      startPollingIfActive()
    }
  } catch (e) {
    console.error('[loadRuns] failed:', e)
    message.error('加载运行记录失败')
  } finally {
    runLoading.value = false
  }
}

async function loadDrafts(runId: string) {
  draftsLoading.value = true
  try {
    const res = await sopResearchApi.listDrafts(runId)
    drafts.value = res.sop_drafts
    evalDrafts.value = res.eval_drafts
  } catch (e) {
    console.error('[loadDrafts] failed:', e)
    message.error('加载草稿列表失败')
  } finally {
    draftsLoading.value = false
  }
}

// 加载草稿详情，按类型分流到 SOP / Eval 接口
async function loadDraftDetail(draftId: string, type: 'sop' | 'eval') {
  draftDetailLoading.value = true
  try {
    const res = type === 'eval'
      ? await sopResearchApi.getEvalDraft(draftId)
      : await sopResearchApi.getDraft(draftId)
    draftDetail.value = res.detail
  } catch (e) {
    console.error('[loadDraftDetail] failed:', e)
    message.error('加载草稿详情失败')
    draftDetail.value = null
  } finally {
    draftDetailLoading.value = false
  }
}

async function handleRefreshRun() {
  if (!selectedProjectId.value) return
  await loadRuns(selectedProjectId.value)
}

function startPollingIfActive() {
  const run = selectedRun.value
  if (run && activeRunStatuses.includes(run.status)) {
    startPolling()
  }
}

let pollTick = 0
function startPolling() {
  stopPolling()
  pollTick = 0
  pollingTimer.value = window.setInterval(async () => {
    if (!selectedRunId.value) {
      stopPolling()
      return
    }
    // 页面隐藏时跳过本次轮询，避免后台无效请求堆积
    if (document.hidden) return
    try {
      const res = await sopResearchApi.getRun(selectedRunId.value)
      const updated = res.run
      runs.value = runs.value.map(r => r.run_id === updated.run_id ? updated : r)
      pollTick++
      // 运行中每 ~9s 刷新一次草稿列表，让用户看到中途产出的草稿
      if (pollTick % 3 === 0) {
        await loadDrafts(selectedRunId.value)
      }
      if (!activeRunStatuses.includes(updated.status)) {
        await loadDrafts(selectedRunId.value)
        stopPolling()
      }
    } catch (e) {
      console.error('[polling] failed:', e)
      stopPolling()
    }
  }, 3000)
}

function stopPolling() {
  if (pollingTimer.value !== null) {
    clearInterval(pollingTimer.value)
    pollingTimer.value = null
  }
}

async function handleStartRun() {
  if (!selectedProjectId.value) {
    message.warning('请先选择项目')
    return
  }
  try {
    const project = projects.value.find(p => p.project_id === selectedProjectId.value)
    const res = await sopResearchApi.createRun({
      project_id: selectedProjectId.value,
      library_id: project?.library_id,
      doc_id: project?.doc_id,
    })
    runs.value.unshift(res.run)
    selectedRunId.value = res.run.run_id
    startPolling()
    message.success('已开始运行')
  } catch (e: any) {
    console.error('[handleStartRun] failed:', e)
    // 409 冲突等场景后端会返回 detail，优先展示给用户
    const detail = e?.response?.data?.detail || e?.message
    message.error(detail || '开始运行失败')
  }
}

async function handleStopRun() {
  if (!selectedRunId.value) return
  try {
    await sopResearchApi.stopRun(selectedRunId.value)
    message.success('已发送停止请求')
    // 若未在轮询则启动，持续轮询直到状态变为 cancelled
    if (pollingTimer.value === null) {
      startPolling()
    }
  } catch (e) {
    console.error('[handleStopRun] failed:', e)
    message.error('停止运行失败')
  }
}

// 重试运行：后端会基于原 run 创建一个全新的 run（新 run_id），需将新 run 加入列表并切换选中，否则 UI 仍停留在旧 run 上
async function handleRetryRun() {
  if (!selectedRunId.value) return
  try {
    const res = await sopResearchApi.retryRun(selectedRunId.value)
    // retry 在后端会创建一个全新的 run（新 run_id），需加入列表并切换选中
    if (!runs.value.some(r => r.run_id === res.run.run_id)) {
      runs.value.unshift(res.run)
    }
    selectedRunId.value = res.run.run_id
    // 切换 run 后清空旧草稿与详情，避免显示上一个 run 的残留
    drafts.value = []
    evalDrafts.value = []
    selectedDraftId.value = ''
    draftDetail.value = null
    startPolling()
    message.success('已重试运行')
  } catch (e) {
    console.error('[handleRetryRun] failed:', e)
    message.error('重试运行失败')
  }
}

async function handleSelectDraft(draftId: string, type: 'sop' | 'eval' = 'sop') {
  selectedDraftId.value = draftId
  selectedDraftType.value = type
  await loadDraftDetail(draftId, type)
}

async function handleApproveSop(draftId: string) {
  try {
    await sopResearchApi.approveSopDraft(draftId, {})
    message.success('已批准 SOP 草稿')
    if (selectedRunId.value) {
      await loadDrafts(selectedRunId.value)
    }
    draftDetail.value = null
    selectedDraftId.value = ''
  } catch (e) {
    console.error('[handleApproveSop] failed:', e)
    message.error('批准草稿失败')
  }
}

async function handleApproveEval(draftId: string) {
  try {
    await sopResearchApi.approveEvalDraft(draftId, {})
    message.success('已批准评估草稿')
    if (selectedRunId.value) {
      await loadDrafts(selectedRunId.value)
    }
  } catch (e) {
    console.error('[handleApproveEval] failed:', e)
    message.error('批准评估草稿失败')
  }
}

async function handleRejectDraft(draftId: string, type: 'sop' | 'eval' = 'sop') {
  try {
    if (type === 'eval') {
      await sopResearchApi.rejectEvalDraft(draftId, {})
    } else {
      await sopResearchApi.rejectSopDraft(draftId, {})
    }
    message.success('已拒绝草稿')
    if (selectedRunId.value) {
      await loadDrafts(selectedRunId.value)
    }
    if (selectedDraftId.value === draftId) {
      draftDetail.value = null
      selectedDraftId.value = ''
    }
  } catch (e) {
    console.error('[handleRejectDraft] failed:', e)
    message.error('拒绝草稿失败')
  }
}

function showCreateProjectModal() {
  createForm.value = { title: '', library_id: '', doc_id: '' }
  createModalVisible.value = true
}

async function handleCreateProject() {
  const { title, library_id, doc_id } = createForm.value
  if (!title.trim() || !library_id.trim() || !doc_id.trim()) {
    message.warning('请填写完整信息')
    return
  }
  createLoading.value = true
  try {
    await sopResearchApi.createProject({ title: title.trim(), library_id: library_id.trim(), doc_id: doc_id.trim() })
    createModalVisible.value = false
    message.success('创建成功')
    await loadProjects()
  } catch (e) {
    console.error('[handleCreateProject] failed:', e)
    message.error('创建项目失败')
  } finally {
    createLoading.value = false
  }
}

async function handleRefresh() {
  await loadProjects()
  if (selectedProjectId.value) {
    await loadRuns(selectedProjectId.value)
  }
}

onMounted(() => {
  loadProjects()
})

onBeforeUnmount(() => {
  stopPolling()
})
</script>

<style lang="less" scoped>
.sop-research-workspace {
  height: 100%;
  background: var(--bg-primary);
}

.workspace-container {
  height: 100%;
}

.center-content {
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: 8px;
  overflow: auto;
}

.right-panel-content {
  background: transparent;
  overflow: hidden;
}
</style>
