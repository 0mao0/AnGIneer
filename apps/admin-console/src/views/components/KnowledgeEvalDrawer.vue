<template>
  <a-drawer
    :open="drawerVisible"
    title="知识库回归测试"
    placement="right"
    :width="560"
    @close="drawerVisible = false"
  >
    <template #extra>
      <a-space size="small">
        <a-button type="primary" :loading="running" @click="runSuite()">
          {{ running ? '评测执行中' : '重新运行' }}
        </a-button>
        <a-button :disabled="running" @click="resetCases()">
          还原题库
        </a-button>
      </a-space>
    </template>

    <div class="knowledge-eval-drawer">
      <div v-if="summary" class="knowledge-eval-summary">
        <a-tooltip title="总分 = 检索分、回答健康度、回答正确率的简单平均值。若没有可计算的回答正确率，则只平均已有分项。">
          <div class="summary-card">
            <div class="summary-label">总分</div>
            <div class="summary-value">{{ formatScore(summary.overall_score) }}</div>
          </div>
        </a-tooltip>
        <a-tooltip title="检索分对应 retrieval_score，目前使用 Recall@5，表示标准证据是否进入前 5 个检索结果。">
          <div class="summary-card">
            <div class="summary-label">检索分</div>
            <div class="summary-value">{{ formatScore(summary.retrieval_score) }}</div>
          </div>
        </a-tooltip>
        <a-tooltip title="回答健康度 = 是否有回答、是否命中必须引用、拒答是否正确，三个指标的简单平均值。">
          <div class="summary-card">
            <div class="summary-label">回答健康度</div>
            <div class="summary-value">{{ formatScore(summary.answer_health_score) }}</div>
          </div>
        </a-tooltip>
        <a-tooltip title="正确率按检索结果计算：标准片段进入前 5 个结果记为正确；无需检索的题目在返回空结果时也记为正确。正确率 = 正确数量 / 总题数。">
          <div class="summary-card">
            <div class="summary-label">正确率</div>
            <div class="summary-value">
              {{ formatScore(correctRate) }}
            </div>
            <div class="summary-hint">
              正确 {{ passedCount }} / 总数 {{ cases.length }}
            </div>
          </div>
        </a-tooltip>
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
            <div class="eval-item-title">
              <div class="eval-item-title-label">问题</div>
              <div class="eval-item-question-row">
                <span class="eval-item-id">{{ item.questionId }}</span>
                <span class="eval-item-question">{{ item.question }}</span>
              </div>
            </div>
            <a-tag :color="getStatusColor(item.status)">
              {{ getStatusText(item.status) }}
            </a-tag>
          </div>

          <div class="eval-tag-groups">
            <div v-if="item.difficulty" class="eval-tag-group">
              <span class="eval-group-label">难度</span>
              <span class="eval-meta-tag is-difficulty">{{ item.difficulty }}</span>
            </div>
            <div v-if="getDocTags(item).length" class="eval-tag-group">
              <span class="eval-group-label">文档</span>
              <span
                v-for="tag in getDocTags(item)"
                :key="`${item.questionId}-doc-${tag}`"
                class="eval-meta-tag is-doc"
              >
                {{ tag }}
              </span>
            </div>
            <div v-if="getAbilityTags(item).length" class="eval-tag-group">
              <span class="eval-group-label">能力</span>
              <span
                v-for="tag in getAbilityTags(item)"
                :key="`${item.questionId}-ability-${tag}`"
                class="eval-meta-tag is-ability"
              >
                {{ tag }}
              </span>
            </div>
          </div>

          <div v-if="item.answerText || item.taskTypeLabel || item.strategyLabel" class="eval-section">
            <div class="eval-section-header">
              <div class="eval-section-title">回答</div>
              <div class="eval-chain-tags">
                <span v-if="item.taskTypeLabel" class="eval-inline-tag is-chain-label">意图</span>
                <span v-if="item.taskTypeLabel" class="eval-inline-tag is-chain-value">{{ item.taskTypeLabel }}</span>
                <span v-if="item.strategyLabel" class="eval-inline-arrow">-></span>
                <span v-if="item.strategyLabel" class="eval-inline-tag is-chain-label">策略</span>
                <span v-if="item.strategyLabel" class="eval-inline-tag is-chain-value">{{ item.strategyLabel }}</span>
              </div>
            </div>
            <div class="eval-rich-content" v-html="renderRichText(item.answerText)" />
          </div>

          <div v-if="item.conclusion || item.retrievalScore != null || item.answerHealthScore != null" class="eval-section">
            <div class="eval-section-header">
              <div class="eval-section-title">检索结论</div>
              <div class="eval-score-row">
                <a-tooltip title="单题检索分：当前以 hit@5 展示，命中标准证据记 100%，否则 0%。">
                  <div class="eval-score-chip">
                    <span class="eval-score-label">检索分</span>
                    <span class="eval-score-value">{{ formatScore(item.retrievalScore) }}</span>
                  </div>
                </a-tooltip>
                <a-tooltip title="单题回答健康度：是否有回答、是否命中必须引用、拒答是否正确的平均值。">
                  <div class="eval-score-chip">
                    <span class="eval-score-label">回答健康度</span>
                    <span class="eval-score-value">{{ formatScore(item.answerHealthScore) }}</span>
                  </div>
                </a-tooltip>
              </div>
            </div>
            <div v-if="item.conclusion" class="eval-rich-content" v-html="renderRichText(item.conclusion)" />
          </div>

          <div v-if="item.citations.length" class="eval-section">
            <div class="eval-section-header">
              <div class="eval-section-title">检索片段 (Top 5)</div>
            </div>
            <button
              type="button"
              class="eval-section-toggle"
              @click="toggleCitations(item.questionId)"
            >
              <span class="eval-toggle-text">
                {{ isCitationExpanded(item.questionId) ? '收起' : `展开 (${item.citations.length})` }}
              </span>
            </button>
            <div v-if="isCitationExpanded(item.questionId)" class="eval-citation-list">
              <div
                v-for="citation in item.citations"
                :key="`${item.questionId}-${citation.target_id}-${citation.page_idx}`"
                class="eval-citation-item"
              >
                <div class="eval-citation-meta">
                  <span class="eval-citation-doc">{{ citation.doc_title }}</span>
                  <span v-if="citation.page_idx" class="eval-citation-page">P{{ citation.page_idx }}</span>
                  <span v-if="citation.section_path" class="eval-citation-section">{{ citation.section_path }}</span>
                </div>
                <div class="eval-rich-content" v-html="renderRichText(citation.snippet || '')" />
              </div>
            </div>
          </div>

          <div v-if="item.error" class="eval-item-error">{{ item.error }}</div>
          <div v-if="item.failedChecks.length" class="eval-item-error">
            未满足标准规则：{{ item.failedChecks.map(check => (check.keywords || []).join(' / ')).join('；') }}
          </div>
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
import { computed, ref } from 'vue'
import { message } from 'ant-design-vue'
import { renderMarkdownToHtml } from '@angineer/docs-ui'
import {
  knowledgeApi,
  type KnowledgeEvalAnswerDetail,
  type KnowledgeEvalQuestion,
  type KnowledgeEvalSummary
} from '@/api/knowledge'

type EvalCaseStatus = 'pending' | 'running' | 'passed' | 'failed' | 'error'

type EvalCitation = {
  target_id: string
  doc_id: string
  doc_title: string
  page_idx: number
  section_path: string
  snippet: string
  score: number
}

type EvalCaseState = {
  questionId: string
  question: string
  difficulty: string
  tags: string[]
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
}

interface Props {
  runQuestion: (question: string) => Promise<{
    answer: string
    queryChain?: string
    citations?: EvalCitation[]
  }>
}

const props = defineProps<Props>()

const drawerVisible = ref(false)
const running = ref(false)
const autoRunEnabled = ref(false)
const questions = ref<KnowledgeEvalQuestion[]>([])
const cases = ref<EvalCaseState[]>([])
const summary = ref<KnowledgeEvalSummary | null>(null)
const resultFilter = ref<'all' | 'passed' | 'failed'>('all')
const expandedCitationQuestionIds = ref<string[]>([])

const completedCount = computed(() => cases.value.filter(item => (
  item.status === 'passed' || item.status === 'failed' || item.status === 'error'
)).length)
const passedCount = computed(() => cases.value.filter(item => item.status === 'passed').length)
const failedCount = computed(() => cases.value.filter(item => item.status === 'failed' || item.status === 'error').length)
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
 * 拉取评测题目列表，并准备前端状态。
 */
const fetchQuestions = async () => {
  const result = await knowledgeApi.getEvalQuestions()
  questions.value = Array.isArray(result?.questions) ? result.questions : []
  resetCases()
}

/**
 * 将题库恢复为待运行状态，便于重新开始一次完整评测。
 */
const resetCases = () => {
  cases.value = questions.value.map(question => ({
    questionId: question.question_id,
    question: question.question,
    difficulty: question.difficulty || '',
    tags: Array.isArray(question.tags) ? question.tags : [],
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
    answerHealthScore: null
  }))
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
    return {
      ...item,
      answerText: detail.answer || item.answerText,
      thinking: item.thinking || buildThinkingText(detail),
      taskTypeLabel: getTaskTypeLabel(detail.task_type),
      strategyLabel: detail.strategy || '',
      citations: Array.isArray(detail.citations) ? detail.citations : item.citations,
      failedChecks: Array.isArray(detail.failed_correctness_checks) ? detail.failed_correctness_checks : [],
      answerHealthScore: computeAnswerHealthScore(detail)
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
    if (!detail) {
      return item
    }
    const passed = computeRetrievalPassed(detail)
    return {
      ...item,
      status: passed ? 'passed' : 'failed',
      conclusion: buildRetrievalConclusion(detail),
      retrievalScore: computeRetrievalScore(detail),
      error: passed ? '' : item.error
    }
  })
}

/**
 * 根据评测明细生成易读的推理链提示。
 */
const buildThinkingText = (detail: KnowledgeEvalAnswerDetail) => {
  const segments = []
  if (detail.strategy) {
    segments.push(`检索策略：${detail.strategy}`)
  }
  return segments.join(' -> ')
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
 * 返回能力类标签。
 */
const getAbilityTags = (item: EvalCaseState) => item.tags.filter(tag => !/^doc-/i.test(tag))

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
 * 生成更符合检索评测场景的单题结论。
 */
const buildRetrievalConclusion = (detail: Record<string, any>) => {
  const predictedIds = Array.isArray(detail.predicted_ids) ? detail.predicted_ids : []
  const goldChunkIds = Array.isArray(detail.gold_chunk_ids) ? detail.gold_chunk_ids : []
  const hitCount = goldChunkIds.filter((item: string) => predictedIds.includes(item)).length
  if (detail.retrieval_expected === false) {
    return computeRetrievalPassed(detail)
      ? '该题不要求召回标准片段，当前结果满足预期。'
      : '该题本应不返回相关片段，但当前检索结果返回了额外内容。'
  }
  if (computeRetrievalPassed(detail)) {
    return `已命中标准片段。前 5 个检索结果已覆盖目标内容，命中 ${hitCount} 个目标片段。`
  }
  return '未命中标准片段。前 5 个检索结果没有覆盖这道题要求的目标内容。'
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
  if (!questions.value.length) {
    await fetchQuestions()
  }
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
    for (const item of cases.value) {
      item.status = 'running'
      const response = await props.runQuestion(item.question)
      item.conclusion = response.answer || ''
      item.thinking = response.queryChain || ''
      item.citations = Array.isArray(response.citations) ? response.citations : []
      if (item.status === 'running') {
        item.status = 'passed'
      }
    }
    const report = await knowledgeApi.runEvalSuite()
    summary.value = report.report?.summary || null
    applyAnswerReport(report.report?.answer?.details || [])
    applyRetrievalReport(Array.isArray(report.report?.retrieval?.details) ? report.report.retrieval.details : [])
    message.success(options?.triggeredBy ? `${options.triggeredBy}后已完成知识库评测` : '知识库评测已完成')
  } catch (error) {
    const detail = (error as any)?.response?.data?.detail || (error as any)?.message || '未知错误'
    const runningItem = cases.value.find(item => item.status === 'running')
    if (runningItem) {
      runningItem.status = 'error'
      runningItem.error = detail
    }
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
 * 判断某道题的相关片段是否处于展开状态。
 */
const isCitationExpanded = (questionId: string) => expandedCitationQuestionIds.value.includes(questionId)

/**
 * 切换单题相关片段的折叠状态。
 */
const toggleCitations = (questionId: string) => {
  if (isCitationExpanded(questionId)) {
    expandedCitationQuestionIds.value = expandedCitationQuestionIds.value.filter(item => item !== questionId)
    return
  }
  expandedCitationQuestionIds.value = [...expandedCitationQuestionIds.value, questionId]
}

/**
 * 返回状态标签颜色。
 */
const getStatusColor = (status: EvalCaseStatus) => {
  if (status === 'passed') return 'green'
  if (status === 'failed') return 'red'
  if (status === 'running') return 'blue'
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
  if (status === 'error') return '异常'
  return '待运行'
}

/**
 * 对外暴露打开抽屉并立即执行的方法。
 */
const openAndRun = async () => {
  await runSuite()
}

/**
 * 在启用自动评测时，由页面层调用此方法执行一次回归。
 */
const maybeAutoRun = async (triggeredBy: string) => {
  if (!autoRunEnabled.value || running.value) {
    return
  }
  await runSuite({ triggeredBy })
}

defineExpose({
  running,
  autoRunEnabled,
  openAndRun,
  maybeAutoRun
})
</script>

<style lang="less" scoped>
.knowledge-eval-drawer {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.knowledge-eval-summary {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.summary-card {
  padding: 12px;
  border-radius: 10px;
  background: var(--bg-secondary, #fafafa);
  border: 1px solid var(--border-color, #e8e8e8);
}

.summary-label {
  font-size: 12px;
  color: var(--text-secondary, rgba(0, 0, 0, 0.45));
}

.summary-value {
  margin-top: 6px;
  font-size: 20px;
  font-weight: 600;
  color: var(--text-primary, rgba(0, 0, 0, 0.88));
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

.eval-item-title {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

.eval-item-title-label {
  font-size: 12px;
  line-height: 1;
  color: var(--text-secondary, rgba(0, 0, 0, 0.45));
}

.eval-item-question-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
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

.eval-tag-groups {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 12px;
}

.eval-tag-group {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
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

.knowledge-eval-item.status-passed {
  border-color: rgba(82, 196, 26, 0.35);
}

.knowledge-eval-item.status-failed,
.knowledge-eval-item.status-error {
  border-color: rgba(245, 34, 45, 0.28);
}
</style>
