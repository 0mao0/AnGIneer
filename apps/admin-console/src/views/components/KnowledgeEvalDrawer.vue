<template>
  <a-drawer
    :open="drawerVisible"
    title="知识库回归测试"
    placement="right"
    :width="560"
    @close="drawerVisible = false"
  >
    <template #extra><span /></template>

    <div class="knowledge-eval-drawer">
      <div v-if="currentDataset" class="knowledge-eval-dataset-card">
        <div class="dataset-card-top-row">
          <div class="dataset-card-left">
            <a-radio-group
              v-if="datasetButtonOptions.length"
              :value="selectedDatasetId"
              size="small"
              button-style="solid"
              class="dataset-switch-group"
              @update:value="handleDatasetChange"
            >
              <a-radio-button
                v-for="option in datasetButtonOptions"
                :key="option.value"
                :value="option.value"
                :disabled="running"
              >
                {{ option.label }}
              </a-radio-button>
            </a-radio-group>
            <div v-if="currentDataset.description" class="dataset-card-description">
              {{ currentDataset.description }}
            </div>
            <div class="dataset-card-meta">
              <span>可见题数：{{ currentDataset.visible_question_count }}</span>
              <span>SQL 题：{{ currentDataset.sql_question_count }}</span>
              <span v-if="currentDataset.version">版本：{{ currentDataset.version }}</span>
            </div>
          </div>
          <div v-if="summary || completedCount" class="dataset-card-right">
            <div class="dataset-score-value">{{ formatScore(correctRate) }}</div>
            <div class="dataset-score-hint">正确 {{ passedCount }} / {{ cases.length }}</div>
          </div>
        </div>
        <div class="dataset-card-bottom-row">
          <div />
          <div class="dataset-action-row">
            <a-button type="primary" size="small" :loading="running" @click="runSuite()">
              {{ running ? '评测执行中' : currentDatasetRunLabel }}
            </a-button>
            <a-button size="small" :disabled="running || !hasCurrentDatasetState" @click="resetCases()">
              还原题库
            </a-button>
          </div>
        </div>
      </div>

      <div class="knowledge-eval-meta">
        <span>题目数：{{ cases.length }}</span>
        <span>进度：{{ progressText }}</span>
        <a-radio-group v-model:value="resultFilter" size="small" button-style="solid">
          <a-radio-button value="all">全部（{{ cases.length }}）</a-radio-button>
          <a-radio-button value="passed">正确（{{ passedCount }}）</a-radio-button>
          <a-radio-button value="failed">错误（{{ failedCount }}）</a-radio-button>
        </a-radio-group>
      </div>

      <div class="knowledge-eval-list">
        <div
          v-for="item in filteredCases"
          :key="item.questionId"
          class="knowledge-eval-item"
          :class="`status-${item.status}`"
        >
          <div class="eval-item-header">
            <div class="eval-item-title-area">
              <div class="eval-item-first-row">
                <span class="eval-item-title-label">问题</span>
                <span v-if="item.difficulty" class="eval-meta-tag is-difficulty">{{ formatDifficulty(item.difficulty) }}</span>
                <span
                  v-for="tag in getDocTags(item)"
                  :key="`${item.questionId}-doc-${tag}`"
                  class="eval-meta-tag is-doc"
                >
                  {{ formatDocTag(tag, item) }}
                </span>
              </div>
              <div class="eval-item-second-row">
                <span class="eval-item-id">{{ item.questionId }}</span>
                <span class="eval-item-question">{{ item.question }}</span>
              </div>
            </div>
            <a-tag :color="getStatusColor(item.status)">
              {{ getStatusText(item.status) }}
            </a-tag>
          </div>

          <div v-if="item.answerText || item.goldAnswer || item.failedChecks.length" class="eval-section">
            <div v-if="item.answerText" class="eval-answer-block">
              <div class="eval-answer-label">系统回答</div>
              <div class="eval-rich-content" v-html="renderRichText(item.answerText)" />
            </div>
            <div v-if="item.failedChecks.length" class="eval-answer-block">
              <div class="eval-answer-label">正确性校验</div>
              <div class="eval-failed-checks">
                未满足标准规则：{{ item.failedChecks.map(check => (check.keywords || []).join(' / ')).join('；') }}
              </div>
            </div>
            <div v-if="item.goldAnswer" class="eval-answer-block">
              <div class="eval-answer-label">标准答案</div>
              <div class="eval-rich-content" v-html="renderRichText(item.goldAnswer)" />
            </div>
          </div>

          <div v-if="buildThinkingChain(item).length" class="eval-section">
            <div class="eval-section-header">
              <div class="eval-section-title">思考链路</div>
            </div>
            <div class="eval-thinking-chain">
              <div
                v-for="(step, idx) in buildThinkingChain(item)"
                :key="`${item.questionId}-step-${idx}`"
                class="eval-thinking-step"
              >
                <span class="eval-step-badge">{{ idx + 1 }}</span>
                <span class="eval-step-label">{{ step.label }}</span>
                <span class="eval-step-value">{{ step.value }}</span>
                <a-button
                  v-if="step.hasDetail"
                  type="link"
                  size="small"
                  @click="toggleStepDetail(item.questionId, idx)"
                >
                  {{ isStepDetailExpanded(item.questionId, idx) ? '收起' : '详情' }}
                </a-button>
                <div
                  v-if="isStepDetailExpanded(item.questionId, idx)"
                  class="eval-step-detail"
                >
                  <template v-if="step.label === '证据检索'">
                    <div
                      v-for="(c, ci) in item.citations"
                      :key="`${item.questionId}-citation-${ci}`"
                      class="eval-citation-card"
                    >
                      <div class="eval-citation-meta">
                        <span class="eval-citation-score">[{{ ci + 1 }}] 得分{{ c.score.toFixed(4) }}</span>
                      </div>
                      <div class="eval-citation-location">
                        <span>{{ c.doc_title || c.doc_id }}</span>
                        <span v-if="c.page_idx" class="eval-citation-sep">·</span>
                        <span v-if="c.page_idx">页码: P{{ c.page_idx }}</span>
                      </div>
                      <div v-if="c.section_path" class="eval-citation-section">
                        章节: {{ c.section_path }}
                      </div>
                      <div
                        v-if="c.rich_media && (c.rich_media.table_html || c.rich_media.math_content || c.rich_media.image_path || (c.rich_media.image_paths && c.rich_media.image_paths.length) || (c.rich_media.rich_media_order && c.rich_media.rich_media_order.length))"
                        class="eval-citation-rich-media"
                        v-html="renderCitationRichMedia(c)"
                      />
                      <div
                        v-if="c.content || c.snippet"
                        class="eval-citation-content eval-rich-content"
                        v-html="renderRichText(c.content || c.snippet)"
                      />
                    </div>
                  </template>
                  <pre v-else>{{ formatStepDetail(item, step.label) }}</pre>
                </div>
              </div>
            </div>
          </div>

          <div v-if="item.standardThinking" class="eval-section">
            <div class="eval-section-header">
              <div class="eval-section-title">标准思考过程</div>
            </div>
            <div class="eval-rich-content" v-html="renderRichText(item.standardThinking)" />
          </div>

          <div v-if="item.error" class="eval-item-error">{{ item.error }}</div>
        </div>
      </div>
    </div>
  </a-drawer>
</template>

<script setup lang="ts">
/**
 * 知识库评测抽屉组件。
 * 负责拉取题库、顺序触发 KnowledgeChat 问答，并展示逐题结果与汇总分数。
 */
import { computed, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { renderMarkdownToHtml, renderFormula, resolveAssetUrl } from '@angineer/docs-ui'
import {
  knowledgeApi,
  type KnowledgeEvalAnswerDetail,
  type KnowledgeEvalDataset,
  type KnowledgeEvalQuestion,
  type KnowledgeEvalSummary
} from '@/api/knowledge'

type EvalCaseStatus = 'pending' | 'running' | 'answered' | 'passed' | 'failed' | 'error'

type CitationRichMedia = {
  table_html?: string
  math_content?: string
  image_path?: string
  image_paths?: string[]
  rich_media_order?: Array<{ type: 'image' | 'table' | 'math'; path?: string }>
  source_file_name?: string
}

type EvalCitation = {
  target_id: string
  target_type?: string
  doc_id: string
  doc_title: string
  page_idx: number
  section_path: string
  snippet: string
  content?: string
  content_type?: string
  score: number
  rich_media?: CitationRichMedia
}

type EvalCaseState = {
  questionId: string
  question: string
  difficulty: string
  tags: string[]
  goldAnswer: string
  standardThinking: string
  status: EvalCaseStatus
  conclusion: string
  answerText: string
  thinking: string
  taskTypeLabel: string
  strategyLabel: string
  citations: EvalCitation[]
  error: string
  failedChecks: Array<{ type?: string; keywords?: string[] }>
  retrievalScore: number | null
  answerHealthScore: number | null
  strategy: string
  taskType: string
  confidence: number | null
  retrievedItems: Array<Record<string, any>>
  queryDebug: Record<string, any>
}

type DatasetEvalState = {
  questions: KnowledgeEvalQuestion[]
  cases: EvalCaseState[]
  summary: KnowledgeEvalSummary | null
  resultFilter: 'all' | 'passed' | 'failed'
  expandedCitationQuestionIds: string[]
}

interface Props {
  runQuestion: (question: string) => Promise<{
    answer: string
    queryChain?: string
    citations?: EvalCitation[]
    strategy?: string
    task_type?: string
    confidence?: number | null
    retrieved_items?: any[]
    debug?: Record<string, any>
  }>
}

const props = defineProps<Props>()

const drawerVisible = ref(false)
const running = ref(false)
const datasets = ref<KnowledgeEvalDataset[]>([])
const datasetStates = ref<Record<string, DatasetEvalState>>({})
const selectedDatasetId = ref('')
const loadedDatasetId = ref('')
const questions = ref<KnowledgeEvalQuestion[]>([])
const cases = ref<EvalCaseState[]>([])
const summary = ref<KnowledgeEvalSummary | null>(null)
const resultFilter = ref<'all' | 'passed' | 'failed'>('all')
const expandedCitationQuestionIds = ref<string[]>([])
const expandedStepDetails = ref<Record<string, Set<number>>>({})

const completedCount = computed(() => cases.value.filter(item => (
  item.status === 'answered' || item.status === 'passed' || item.status === 'failed' || item.status === 'error'
)).length)
const passedCount = computed(() => cases.value.filter(item => item.status === 'passed').length)
const failedCount = computed(() => cases.value.filter(item => item.status === 'failed' || item.status === 'error').length)
const currentDataset = computed(() => (
  datasets.value.find(item => item.dataset_id === selectedDatasetId.value) || null
))
const datasetButtonOptions = computed(() => datasets.value.map((item, index) => ({
  label: buildDatasetButtonLabel(item, index),
  value: item.dataset_id
})))
const hasCurrentDatasetState = computed(() => {
  const datasetId = selectedDatasetId.value
  return Boolean(datasetId && datasetStates.value[datasetId])
})
const currentDatasetRunLabel = computed(() => currentDatasetHasResult.value ? '重新评测' : '评测')
const currentDatasetHasResult = computed(() => Boolean(summary.value || completedCount.value))
const correctRate = computed(() => {
  if (!cases.value.length) {
    return null
  }
  return Number((passedCount.value / cases.value.length).toFixed(4))
})

const progressText = computed(() => `${completedCount.value}/${cases.value.length}`)
const filteredCases = computed(() => {
  if (resultFilter.value === 'passed') {
    return cases.value.filter(item => item.status === 'passed')
  }
  if (resultFilter.value === 'failed') {
    return cases.value.filter(item => item.status === 'failed' || item.status === 'error')
  }
  return cases.value
})

/**
 * 组装题库按钮文案。
 */
function buildDatasetButtonLabel(dataset: KnowledgeEvalDataset, index: number) {
  const title = String(dataset.title || '').trim()
  const compactTitle = title
    .replace(/^知识库基线评测集\s*\d*$/u, '基线')
    .replace(/^eval[_-]?\d*[\(\（]?/i, '')
    .replace(/[\)\)]\s*$/u, '')
    .trim()
  return compactTitle ? `题库${index + 1}（${compactTitle}）` : `题库${index + 1}`
}

/**
 * 根据题目列表生成初始用例状态。
 */
function buildCasesFromQuestions(sourceQuestions: KnowledgeEvalQuestion[]): EvalCaseState[] {
  return sourceQuestions.map(question => ({
    questionId: question.question_id,
    question: question.question,
    difficulty: question.difficulty || '',
    tags: Array.isArray(question.tags) ? question.tags : [],
    goldAnswer: question.gold_answer || '',
    standardThinking: question.thought_process || '',
    status: 'pending',
    conclusion: '',
    answerText: '',
    thinking: '',
    taskTypeLabel: '',
    strategyLabel: '',
    citations: [],
    error: '',
    failedChecks: [],
    retrievalScore: null,
    answerHealthScore: null,
    strategy: '',
    taskType: '',
    confidence: null,
    retrievedItems: [],
    queryDebug: {}
  }))
}

/**
 * 创建单个题库的默认状态。
 */
function createDatasetState(sourceQuestions: KnowledgeEvalQuestion[]): DatasetEvalState {
  return {
    questions: sourceQuestions,
    cases: buildCasesFromQuestions(sourceQuestions),
    summary: null,
    resultFilter: 'all',
    expandedCitationQuestionIds: []
  }
}

/**
 * 将当前视图状态保存回题库缓存。
 */
function persistCurrentDatasetState() {
  const datasetId = selectedDatasetId.value || loadedDatasetId.value
  if (!datasetId) {
    return
  }
  datasetStates.value[datasetId] = {
    questions: questions.value,
    cases: cases.value,
    summary: summary.value,
    resultFilter: resultFilter.value,
    expandedCitationQuestionIds: expandedCitationQuestionIds.value
  }
}

/**
 * 从题库缓存恢复当前视图状态。
 */
function restoreDatasetState(datasetId: string) {
  const cachedState = datasetStates.value[datasetId]
  if (!cachedState) {
    return false
  }
  questions.value = cachedState.questions
  cases.value = cachedState.cases
  summary.value = cachedState.summary
  resultFilter.value = cachedState.resultFilter
  expandedCitationQuestionIds.value = cachedState.expandedCitationQuestionIds
  loadedDatasetId.value = datasetId
  return true
}

watch(
  [questions, cases, summary, resultFilter, expandedCitationQuestionIds],
  () => {
    persistCurrentDatasetState()
  },
  { deep: true }
)

/**
 * 拉取题库列表，并默认选中第一套题库。
 */
const fetchDatasets = async () => {
  const result = await knowledgeApi.getEvalDatasets()
  datasets.value = Array.isArray(result?.datasets) ? result.datasets : []
  if (!selectedDatasetId.value && datasets.value.length) {
    selectedDatasetId.value = datasets.value[0].dataset_id
  }
}

/**
 * 拉取评测题目列表，并准备前端状态。
 */
const fetchQuestions = async (datasetId?: string) => {
  const targetDatasetId = datasetId || selectedDatasetId.value
  const result = await knowledgeApi.getEvalQuestions(targetDatasetId || undefined)
  const nextDatasets = Array.isArray(result?.datasets) ? result.datasets : []
  if (nextDatasets.length) {
    datasets.value = nextDatasets
  }
  const resolvedDatasetId = String(
    result?.selected_dataset?.dataset_id || targetDatasetId || datasets.value[0]?.dataset_id || ''
  )
  selectedDatasetId.value = resolvedDatasetId
  loadedDatasetId.value = resolvedDatasetId
  const nextQuestions = Array.isArray(result?.questions) ? result.questions : []
  const nextState = createDatasetState(nextQuestions)
  datasetStates.value[resolvedDatasetId] = nextState
  restoreDatasetState(resolvedDatasetId)
}

/**
 * 将题库恢复为待运行状态，便于重新开始一次完整评测。
 */
const resetCases = () => {
  cases.value = buildCasesFromQuestions(questions.value)
  summary.value = null
  resultFilter.value = 'all'
  expandedCitationQuestionIds.value = []
}

/**
 * 将后端给出的回答明细回填到前端列表。
 */
const applyAnswerReport = (details: KnowledgeEvalAnswerDetail[]) => {
  const detailMap = new Map<string, KnowledgeEvalAnswerDetail>(
    details.map(detail => [detail.question_id, detail])
  )
  cases.value = cases.value.map(item => {
    const detail = detailMap.get(item.questionId)
    if (!detail) {
      return item
    }
    const answerPassed = computeAnswerPassed(detail)
    return {
      ...item,
      status: typeof answerPassed === 'boolean' ? (answerPassed ? 'passed' : 'failed') : item.status,
      goldAnswer: detail.gold_answer || item.goldAnswer,
      standardThinking: detail.thought_process || item.standardThinking,
      failedChecks: Array.isArray(detail.failed_correctness_checks) ? detail.failed_correctness_checks : [],
      answerHealthScore: computeAnswerHealthScore(detail),
      error: answerPassed === false ? '答案未通过标准规则校验。' : item.error
    }
  })
}

/**
 * 将检索评测结果回填到逐题列表，便于展示单题检索得分。
 */
const applyRetrievalReport = (details: Array<Record<string, any>>) => {
  const detailMap = new Map<string, Record<string, any>>(
    details.map(detail => [String(detail.question_id || ''), detail])
  )
  cases.value = cases.value.map(item => {
    const detail = detailMap.get(item.questionId)
    if (!detail || detail.retrieval_evaluated === false) {
      return item
    }
    const passed = computeRetrievalPassed(detail)
    const shouldOverrideStatus = item.status !== 'failed'
    return {
      ...item,
      status: shouldOverrideStatus ? (passed ? 'passed' : 'failed') : item.status,
      conclusion: buildRetrievalConclusion(detail),
      retrievalScore: computeRetrievalScore(detail),
      error: passed ? '' : item.error
    }
  })
}

/**
 * 将任务类型转换为更易读的中文标签。
 */
const getTaskTypeLabel = (taskType?: string) => {
  const taskTypeLabelMap: Record<string, string> = {
    content_qa: '正文问答',
    definition_qa: '定义问答',
    locate_qa: '定位问答',
    table_qa: '表格问答',
    analytic_sql: 'SQL 分析'
  }
  return taskType ? (taskTypeLabelMap[taskType] || taskType) : ''
}

/**
 * 返回文档类标签。
 */
const getDocTags = (item: EvalCaseState) => item.tags.filter(tag => /^doc-/i.test(tag))

/**
 * 将文档 ID 标签格式化为带 PDF 名称的显示。
 */
const formatDocTag = (tag: string, item?: EvalCaseState) => {
  if (item && item.citations && item.citations.length) {
    const matched = item.citations.find((c: EvalCitation) => c.doc_id === tag || c.target_id?.startsWith(tag))
    if (matched && matched.doc_title) {
      return `${tag}《${matched.doc_title}》`
    }
  }
  return tag
}

/**
 * 将难度代码转换为中文标签。
 */
const formatDifficulty = (difficulty: string) => {
  const difficultyMap: Record<string, string> = {
    easy: '难度：简单',
    medium: '难度：中等',
    hard: '难度：困难'
  }
  return difficultyMap[difficulty] || `难度：${difficulty}`
}

type ThinkingStep = {
  label: string
  value: string
  hasDetail: boolean
}

/**
 * 根据用例状态构建思考链路步骤列表。
 */
const buildThinkingChain = (item: EvalCaseState): ThinkingStep[] => {
  const steps: ThinkingStep[] = []
  if (item.taskTypeLabel) {
    steps.push({ label: '意图识别', value: item.taskTypeLabel, hasDetail: false })
  }
  if (item.strategyLabel) {
    steps.push({ label: '检索策略', value: item.strategyLabel, hasDetail: true })
  }
  if (item.citations.length) {
    steps.push({ label: '证据检索', value: `命中 ${item.citations.length} 条`, hasDetail: true })
  }
  if (item.citations.length && item.answerText) {
    steps.push({ label: 'Prompt 拼装', value: '问题 + 证据 → LLM', hasDetail: true })
  }
  if (item.answerText) {
    steps.push({ label: '生成回答', value: 'LLM 生成', hasDetail: true })
  }
  return steps
}

/**
 * 切换思考链路步骤详情的展开/收起状态。
 */
const toggleStepDetail = (questionId: string, stepIdx: number) => {
  const key = `${questionId}`
  if (!expandedStepDetails.value[key]) {
    expandedStepDetails.value[key] = new Set()
  }
  const current = expandedStepDetails.value[key]
  if (current.has(stepIdx)) {
    current.delete(stepIdx)
  } else {
    current.add(stepIdx)
  }
  expandedStepDetails.value = { ...expandedStepDetails.value }
}

/**
 * 判断思考链路步骤详情是否已展开。
 */
const isStepDetailExpanded = (questionId: string, stepIdx: number) => {
  return expandedStepDetails.value[questionId]?.has(stepIdx) || false
}

/**
 * 格式化思考链路步骤详情内容。
 */
const formatStepDetail = (item: EvalCaseState, label: string) => {
  if (label === '证据检索' && item.citations.length) {
    return item.citations.map((c, i) => {
      const parts = [`[${i + 1}] ${c.doc_title || c.doc_id}`]
      if (c.page_idx) parts.push(`  页码: P${c.page_idx}`)
      if (c.section_path) parts.push(`  章节: ${c.section_path}`)
      if (c.score) parts.push(`  得分: ${c.score.toFixed(4)}`)
      if (c.snippet) parts.push(`  片段: ${c.snippet.slice(0, 200)}`)
      return parts.join('\n')
    }).join('\n\n')
  }
  if (label === '检索策略') {
    return `策略: ${item.strategyLabel}\n意图: ${item.taskTypeLabel || '未知'}`
  }
  if (label === 'Prompt 拼装') {
    const evidencePreview = item.citations.slice(0, 3).map((c, i) =>
      `[${i + 1}] ${c.snippet ? c.snippet.slice(0, 150) : '(无片段)'}`
    ).join('\n')
    return `问题: ${item.question}\n\n证据:\n${evidencePreview}`
  }
  if (label === '生成回答') {
    return item.answerText ? item.answerText.slice(0, 500) : '无回答内容'
  }
  return ''
}

/**
 * 判断单题检索是否命中标准结果。
 */
const computeRetrievalPassed = (detail: Record<string, any>) => {
  if (detail.retrieval_expected === false) {
    return Number(detail.empty_retrieval_correct || 0) === 1
  }
  return Number(detail['hit@5'] || 0) === 1
}

/**
 * 读取单题检索得分。
 */
const computeRetrievalScore = (detail: Record<string, any>) => {
  if (detail.retrieval_expected === false) {
    return typeof detail.empty_retrieval_correct === 'number' ? Number(detail.empty_retrieval_correct) : null
  }
  return typeof detail['hit@5'] === 'number' ? Number(detail['hit@5']) : null
}

/**
 * 判断单题回答是否通过正确性校验。
 */
const computeAnswerPassed = (detail: KnowledgeEvalAnswerDetail) => {
  if (!detail.answer_correct_checked) {
    return null
  }
  return Number(detail.answer_correct || 0) === 1
}

/**
 * 生成更符合检索评测场景的单题结论。
 */
const buildRetrievalConclusion = (detail: Record<string, any>) => {
  const predictedIds = Array.isArray(detail.predicted_ids) ? detail.predicted_ids : []
  const goldChunkIds = Array.isArray(detail.gold_chunk_ids) ? detail.gold_chunk_ids : []
  const goldSectionPaths = Array.isArray(detail.gold_section_paths) ? detail.gold_section_paths : []
  const chunkHitCount = goldChunkIds.filter((item: string) => predictedIds.includes(item)).length
  const hasChunkGold = goldChunkIds.length > 0
  const hasSectionGold = goldSectionPaths.length > 0
  if (detail.retrieval_expected === false) {
    return computeRetrievalPassed(detail)
      ? '该题不要求召回标准片段，当前结果满足预期。'
      : '该题本应不返回相关片段，但当前检索结果返回了额外内容。'
  }
  if (computeRetrievalPassed(detail)) {
    if (hasChunkGold) {
      return `已命中标准片段。前 5 个检索结果已覆盖目标内容，命中 ${chunkHitCount}/${goldChunkIds.length} 个目标片段。`
    }
    if (hasSectionGold) {
      return '已命中标准章节。前 5 个检索结果已覆盖目标章节路径。'
    }
    return '检索结果已通过。'
  }
  if (hasChunkGold) {
    return `未命中标准片段。前 5 个检索结果未覆盖目标内容，命中 ${chunkHitCount}/${goldChunkIds.length} 个目标片段。`
  }
  if (hasSectionGold) {
    return '未命中标准章节。前 5 个检索结果未覆盖目标章节路径。'
  }
  return '未命中标准内容。'
}

/**
 * 计算单题回答健康度。
 */
const computeAnswerHealthScore = (detail: KnowledgeEvalAnswerDetail) => {
  const values = [detail.answer_non_empty, detail.citation_hit, detail.refusal_correct]
    .filter((value): value is number => typeof value === 'number')
  if (!values.length) {
    return null
  }
  return Number((values.reduce((sum, value) => sum + value, 0) / values.length).toFixed(4))
}

/**
 * 确保抽屉打开前已经拿到题库数据。
 */
const ensureQuestions = async () => {
  if (!datasets.value.length) {
    await fetchDatasets()
  }
  if (!selectedDatasetId.value && datasets.value.length) {
    selectedDatasetId.value = datasets.value[0].dataset_id
  }
  if (selectedDatasetId.value && restoreDatasetState(selectedDatasetId.value)) {
    return
  }
  if (!questions.value.length || loadedDatasetId.value !== selectedDatasetId.value) {
    await fetchQuestions(selectedDatasetId.value)
  }
}

/**
 * 切换题库后刷新题目列表。
 */
const handleDatasetChange = async (datasetId: string) => {
  if (running.value || !datasetId || datasetId === loadedDatasetId.value) {
    return
  }
  persistCurrentDatasetState()
  selectedDatasetId.value = datasetId
  if (restoreDatasetState(datasetId)) {
    return
  }
  await fetchQuestions(datasetId)
}

/**
 * 顺序调用 KnowledgeChat 发送每一道题，并在结束后刷新官方统计结果。
 */
const runSuite = async (options?: { triggeredBy?: string }) => {
  if (running.value) {
    return
  }
  await ensureQuestions()
  if (!questions.value.length) {
    message.warning('当前没有可运行的知识库评测题目')
    return
  }

  drawerVisible.value = true
  running.value = true
  summary.value = null
  resetCases()

  try {
    const cachedPredictions: Record<string, any> = {}
    for (const item of cases.value) {
      item.status = 'running'
      const response = await props.runQuestion(item.question)
      item.conclusion = response.answer || ''
      item.answerText = response.answer || ''
      item.thinking = response.queryChain || ''
      item.citations = Array.isArray(response.citations) ? response.citations : []
      item.strategy = response.strategy || ''
      item.taskType = response.task_type || ''
      item.taskTypeLabel = getTaskTypeLabel(response.task_type || '')
      item.strategyLabel = response.strategy || ''
      item.confidence = response.confidence ?? null
      item.retrievedItems = Array.isArray(response.retrieved_items) ? response.retrieved_items : []
      item.queryDebug = response.debug || {}
      if (item.status === 'running') {
        item.status = 'answered'
      }
      const retrievedItems = item.retrievedItems
      cachedPredictions[item.questionId] = {
        query_id: '',
        strategy: item.strategy,
        task_type: item.taskType,
        retrieved_ids: retrievedItems.map((ri: any) => ri.item_id || ''),
        retrieved_items: retrievedItems,
        retrieved_section_paths: retrievedItems.map((ri: any) => ri.metadata?.section_path || ''),
        retrieved_doc_ids: retrievedItems.map((ri: any) => ri.doc_id || ''),
        debug: item.queryDebug,
        answer: item.conclusion,
        confidence: item.confidence,
        citations: item.citations
      }
    }
    const report = await knowledgeApi.runEvalSuite(selectedDatasetId.value || undefined, cachedPredictions)
    if (Array.isArray(report.available_datasets) && report.available_datasets.length) {
      datasets.value = report.available_datasets
    }
    if (report.selected_dataset?.dataset_id) {
      selectedDatasetId.value = report.selected_dataset.dataset_id
      loadedDatasetId.value = report.selected_dataset.dataset_id
    }
    summary.value = report.report?.summary || null
    applyAnswerReport(report.report?.answer?.details || [])
    applyRetrievalReport(Array.isArray(report.report?.retrieval?.details) ? report.report.retrieval.details : [])
    persistCurrentDatasetState()
    message.success(options?.triggeredBy ? `${options?.triggeredBy}后已完成知识库评测` : '知识库评测已完成')
  } catch (error) {
    const detail = (error as any)?.response?.data?.detail || (error as any)?.message || '未知错误'
    const runningItem = cases.value.find(item => item.status === 'running')
    if (runningItem) {
      runningItem.status = 'error'
      runningItem.error = detail
    }
    persistCurrentDatasetState()
    message.error(`知识库评测失败: ${detail}`)
  } finally {
    running.value = false
  }
}

/**
 * 格式化汇总分数为百分比。
 */
const formatScore = (value?: number | null) => {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    return '--'
  }
  return `${Math.round(value * 100)}%`
}

/**
 * 统一渲染题目结论与检索片段中的 Markdown、公式和表格。
 */
const renderRichText = (content: string) => renderMarkdownToHtml(content || '', '')

/**
 * 将 citation 的 rich_media 渲染为富媒体 HTML（图片、表格、公式）。
 */
const renderCitationRichMedia = (citation: EvalCitation): string => {
  const rm = citation.rich_media
  if (!rm) return ''
  const sections: string[] = []
  const sourceFilePath = rm.source_file_name || ''
  const renderedImages = new Set<string>()

  if (Array.isArray(rm.rich_media_order) && rm.rich_media_order.length > 0) {
    let tableRendered = false
    let mathRendered = false
    rm.rich_media_order.forEach((item) => {
      if (item.type === 'image' && item.path) {
        const src = resolveAssetUrl(item.path, sourceFilePath)
        if (src && !renderedImages.has(src)) {
          renderedImages.add(src)
          sections.push(`<img class="media-image" src="${src}" alt="image" style="max-width:100%;border-radius:4px;" />`)
        }
      } else if (item.type === 'table' && !tableRendered && rm.table_html) {
        tableRendered = true
        sections.push(`<div class="media-table">${rm.table_html}</div>`)
      } else if (item.type === 'math' && !mathRendered && rm.math_content) {
        mathRendered = true
        sections.push(`<div class="media-formula">${renderFormula(rm.math_content, true)}</div>`)
      }
    })
    if (!tableRendered && rm.table_html) {
      sections.push(`<div class="media-table">${rm.table_html}</div>`)
    }
    if (!mathRendered && rm.math_content) {
      sections.push(`<div class="media-formula">${renderFormula(rm.math_content, true)}</div>`)
    }
  } else {
    const allImagePaths = [
      ...(rm.image_path ? [rm.image_path] : []),
      ...(Array.isArray(rm.image_paths) ? rm.image_paths : [])
    ]
    allImagePaths.forEach((imagePath) => {
      const src = resolveAssetUrl(imagePath, sourceFilePath)
      if (src && !renderedImages.has(src)) {
        renderedImages.add(src)
        sections.push(`<img class="media-image" src="${src}" alt="image" style="max-width:100%;border-radius:4px;" />`)
      }
    })
    if (rm.table_html) {
      sections.push(`<div class="media-table">${rm.table_html}</div>`)
    }
    if (rm.math_content) {
      sections.push(`<div class="media-formula">${renderFormula(rm.math_content, true)}</div>`)
    }
  }

  return sections.join('')
}

/**
 * 返回状态标签颜色。
 */
const getStatusColor = (status: EvalCaseStatus) => {
  if (status === 'passed') return 'green'
  if (status === 'failed') return 'red'
  if (status === 'running') return 'blue'
  if (status === 'answered') return 'gold'
  if (status === 'error') return 'orange'
  return 'default'
}

/**
 * 返回状态标签文案。
 */
const getStatusText = (status: EvalCaseStatus) => {
  if (status === 'passed') return '通过'
  if (status === 'failed') return '未通过'
  if (status === 'running') return '执行中'
  if (status === 'answered') return '待判定'
  if (status === 'error') return '异常'
  return '待运行'
}

/**
 * 对外暴露打开抽屉的方法（不自动运行评测）。
 */
const open = async () => {
  await ensureQuestions()
  drawerVisible.value = true
}

/**
 * 对外暴露打开抽屉并立即执行的方法。
 */
const openAndRun = async () => {
  await runSuite()
}

defineExpose({
  running,
  open,
  openAndRun,
})
</script>

<style lang="less" scoped>
.knowledge-eval-drawer {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.knowledge-eval-dataset-card {
  padding: 12px 14px;
  border-radius: 12px;
  border: 1px solid var(--border-color, #e8e8e8);
  background: var(--bg-secondary, #fff);
}

.dataset-card-top-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}

.dataset-card-left {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

.dataset-card-right {
  flex-shrink: 0;
  text-align: right;
}

.dataset-score-value {
  font-size: 28px;
  font-weight: 700;
  color: #faad14;
  line-height: 1.2;
}

.dataset-score-hint {
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-secondary, rgba(0, 0, 0, 0.45));
}

.dataset-card-description {
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-secondary, rgba(0, 0, 0, 0.55));
}

.dataset-switch-group {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.dataset-card-bottom-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  margin-top: 12px;
}

.dataset-action-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.dataset-card-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  font-size: 12px;
  color: var(--text-secondary, rgba(0, 0, 0, 0.45));
}

.knowledge-eval-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  font-size: 12px;
  color: var(--text-secondary, rgba(0, 0, 0, 0.45));
  align-items: center;
}

.knowledge-eval-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.knowledge-eval-item {
  padding: 14px;
  border-radius: 14px;
  border: 1px solid var(--border-color, #e8e8e8);
  background: var(--bg-secondary, #fff);
}

.eval-item-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.eval-item-title-label {
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-secondary, rgba(0, 0, 0, 0.45));
  flex-shrink: 0;
}

.eval-item-title-area {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.eval-item-first-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.eval-item-second-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}

.eval-item-id {
  font-size: 12px;
  color: #1677ff;
  font-weight: 600;
  line-height: 1.6;
  flex-shrink: 0;
}

.eval-item-question {
  color: var(--text-primary, rgba(0, 0, 0, 0.88));
  line-height: 1.75;
  font-size: 15px;
  font-weight: 600;
  word-break: break-word;
}

.eval-group-label {
  min-width: 36px;
  font-size: 12px;
  color: var(--text-secondary, rgba(0, 0, 0, 0.45));
}

.eval-meta-tag {
  display: inline-flex;
  align-items: center;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 12px;
  line-height: 1.2;
  border: 1px solid transparent;
}

.eval-meta-tag.is-difficulty {
  background: color-mix(in srgb, #faad14 12%, var(--bg-secondary, #fff));
  border-color: color-mix(in srgb, #faad14 28%, var(--border-color, #e8e8e8));
  color: color-mix(in srgb, #faad14 80%, var(--text-primary, rgba(0, 0, 0, 0.88)));
}

.eval-meta-tag.is-doc {
  background: color-mix(in srgb, #1677ff 10%, var(--bg-secondary, #fff));
  border-color: color-mix(in srgb, #1677ff 24%, var(--border-color, #e8e8e8));
  color: var(--text-primary, rgba(0, 0, 0, 0.88));
}

.eval-meta-tag.is-ability {
  background: color-mix(in srgb, #722ed1 10%, var(--bg-secondary, #fff));
  border-color: color-mix(in srgb, #722ed1 22%, var(--border-color, #e8e8e8));
  color: var(--text-primary, rgba(0, 0, 0, 0.88));
}

.eval-section {
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid color-mix(in srgb, var(--border-color, #e8e8e8) 84%, transparent);
}

.eval-standard-block + .eval-standard-block {
  margin-top: 12px;
}

.eval-standard-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary, rgba(0, 0, 0, 0.55));
}

.eval-section-header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.eval-section-toggle {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  padding: 0;
  border: none;
  background: transparent;
  cursor: pointer;
  margin-top: 8px;
  width: 100%;
}

.eval-section-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary, rgba(0, 0, 0, 0.55));
}

.eval-chain-tags {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.eval-inline-tag {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 12px;
  line-height: 1.2;
}

.eval-inline-tag.is-chain-label {
  color: var(--text-secondary, rgba(0, 0, 0, 0.45));
  background: color-mix(in srgb, var(--border-color, #e8e8e8) 55%, transparent);
}

.eval-inline-tag.is-chain-value {
  color: var(--text-primary, rgba(0, 0, 0, 0.88));
  background: color-mix(in srgb, #1677ff 10%, var(--bg-secondary, #fff));
  border: 1px solid color-mix(in srgb, #1677ff 20%, var(--border-color, #e8e8e8));
}

.eval-inline-arrow {
  font-size: 12px;
  color: var(--text-secondary, rgba(0, 0, 0, 0.45));
}

.eval-toggle-text {
  color: #1890ff;
  font-size: 12px;
  flex-shrink: 0;
}

.eval-score-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.eval-score-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  background: color-mix(in srgb, #1890ff 12%, var(--bg-secondary, #fff));
  border: 1px solid color-mix(in srgb, #1890ff 25%, var(--border-color, #e8e8e8));
}

.eval-score-label {
  font-size: 12px;
  color: var(--text-secondary, rgba(0, 0, 0, 0.45));
}

.eval-score-value {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary, rgba(0, 0, 0, 0.88));
}

.eval-thinking,
.eval-item-error {
  white-space: pre-wrap;
  line-height: 1.7;
  word-break: break-word;
  font-size: 13px;
}

.eval-thinking {
  margin-top: 10px;
  color: var(--text-primary, rgba(0, 0, 0, 0.88));
}

.eval-item-error {
  margin-top: 10px;
  color: #cf1322;
}

.eval-failed-checks {
  margin-top: 4px;
  padding: 8px 10px;
  border-radius: 6px;
  background: color-mix(in srgb, #cf1322 8%, var(--bg-secondary, #fff));
  border: 1px solid color-mix(in srgb, #cf1322 20%, var(--border-color, #e8e8e8));
  color: #cf1322;
  font-size: 13px;
  line-height: 1.6;
}

.eval-citation-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.eval-citation-item {
  padding: 10px;
  border-radius: 8px;
  background: color-mix(in srgb, #1890ff 8%, var(--bg-secondary, #1f1f1f));
  border: 1px solid color-mix(in srgb, #1890ff 26%, var(--border-color, #303030));
}

.eval-citation-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 6px;
  font-size: 12px;
}

.eval-citation-doc {
  font-weight: 600;
  color: var(--text-primary, rgba(0, 0, 0, 0.88));
}

.eval-citation-page {
  color: #1890ff;
}

.eval-citation-section {
  color: var(--text-secondary, rgba(0, 0, 0, 0.45));
}

.eval-answer-block {
  margin-top: 10px;
}

.eval-answer-block + .eval-answer-block {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed color-mix(in srgb, var(--border-color, #e8e8e8) 70%, transparent);
}

.eval-answer-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary, rgba(0, 0, 0, 0.55));
  margin-bottom: 4px;
}

.eval-thinking-chain {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 8px;
}

.eval-thinking-step {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.eval-step-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: color-mix(in srgb, #1890ff 15%, var(--bg-secondary, #fff));
  color: #1890ff;
  font-size: 12px;
  font-weight: 600;
  flex-shrink: 0;
}

.eval-step-label {
  font-weight: 600;
  color: var(--text-secondary, rgba(0, 0, 0, 0.65));
}

.eval-step-value {
  color: var(--text-primary, rgba(0, 0, 0, 0.88));
}

.eval-step-detail {
  width: 100%;
  margin-top: 6px;
  padding: 10px;
  border-radius: 8px;
  background: color-mix(in srgb, var(--border-color, #e8e8e8) 40%, var(--bg-secondary, #fff));
  overflow-x: auto;
}

.eval-step-detail pre {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--text-primary, rgba(0, 0, 0, 0.88));
}

.eval-citation-card {
  padding: 10px 12px;
  border-radius: 8px;
  background: color-mix(in srgb, var(--bg-secondary, #fff) 92%, var(--border-color, #e8e8e8) 8%);
  border: 1px solid color-mix(in srgb, var(--border-color, #e8e8e8) 60%, transparent);
  margin-bottom: 8px;
}

.eval-citation-card:last-child {
  margin-bottom: 0;
}

.eval-citation-meta {
  display: flex;
  align-items: center;
  margin-bottom: 4px;
}

.eval-citation-score {
  font-size: 13px;
  font-weight: 600;
  color: #fa8c16;
}

.eval-citation-location {
  font-size: 12px;
  color: var(--text-secondary, rgba(0, 0, 0, 0.45));
  line-height: 1.6;
}

.eval-citation-sep {
  margin: 0 4px;
}

.eval-citation-section {
  font-size: 12px;
  color: var(--text-secondary, rgba(0, 0, 0, 0.45));
  line-height: 1.6;
}

.eval-citation-content {
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px dashed color-mix(in srgb, var(--border-color, #e8e8e8) 70%, transparent);
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-primary, rgba(0, 0, 0, 0.88));
}

.eval-citation-rich-media {
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px dashed color-mix(in srgb, var(--border-color, #e8e8e8) 70%, transparent);
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-primary, rgba(0, 0, 0, 0.88));
}

.eval-citation-rich-media :deep(.media-table) {
  overflow-x: auto;
  max-width: 100%;
  margin: 0.4em 0;
}

.eval-citation-rich-media :deep(.media-table table) {
  width: 100%;
  border-collapse: collapse;
}

.eval-citation-rich-media :deep(.media-table th),
.eval-citation-rich-media :deep(.media-table td) {
  border: 1px solid var(--border-color, #e8e8e8);
  padding: 4px 8px;
  font-size: 12px;
}

.eval-citation-rich-media :deep(.media-formula),
.eval-citation-rich-media :deep(.math-block),
.eval-citation-rich-media :deep(.katex-display) {
  overflow-x: auto;
  max-width: 100%;
  margin: 0.4em 0;
}

.eval-citation-rich-media :deep(.media-image) {
  max-width: 100%;
  border-radius: 4px;
}

.eval-citation-content :deep(p),
.eval-citation-content :deep(ul),
.eval-citation-content :deep(ol),
.eval-citation-content :deep(blockquote),
.eval-citation-content :deep(pre),
.eval-citation-content :deep(table),
.eval-citation-content :deep(.math-block),
.eval-citation-content :deep(.media-table),
.eval-citation-content :deep(.media-formula) {
  margin: 0.4em 0;
}

.eval-citation-content :deep(.media-table),
.eval-citation-content :deep(.math-block),
.eval-citation-content :deep(.media-formula),
.eval-citation-content :deep(.katex-display) {
  overflow-x: auto;
  max-width: 100%;
}

.eval-citation-content :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 0.4em 0;
}

.eval-citation-content :deep(th),
.eval-citation-content :deep(td) {
  border: 1px solid var(--border-color, #e8e8e8);
  padding: 4px 8px;
  font-size: 12px;
}

.eval-citation-content :deep(img),
.eval-citation-content :deep(.markdown-image) {
  max-width: 100%;
  border-radius: 4px;
}

.eval-rich-content {
  margin-top: 10px;
  line-height: 1.7;
  color: var(--text-primary, rgba(0, 0, 0, 0.88));

  :deep(p),
  :deep(ul),
  :deep(ol),
  :deep(blockquote),
  :deep(pre),
  :deep(table),
  :deep(.math-block),
  :deep(.media-table),
  :deep(.media-formula) {
    margin: 0.6em 0;
  }

  :deep(.media-table),
  :deep(.math-block),
  :deep(.media-formula),
  :deep(.katex-display) {
    overflow-x: auto;
    max-width: 100%;
  }
}

.knowledge-eval-item.status-running {
  border-color: rgba(22, 119, 255, 0.35);
}

.knowledge-eval-item.status-answered {
  border-color: rgba(250, 173, 20, 0.32);
}

.knowledge-eval-item.status-passed {
  border-color: rgba(82, 196, 26, 0.35);
}

.knowledge-eval-item.status-failed,
.knowledge-eval-item.status-error {
  border-color: rgba(245, 34, 45, 0.28);
}
</style>
