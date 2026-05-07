<template>
  <div
    class="eval-question-card"
    :class="{ 'eval-question-card--expanded': expanded }"
  >
    <div class="eval-question-card__header" @click="$emit('toggle', question.question_id)">
      <EvalLevelBadge :level="question.intent_level" />
      <span class="eval-question-card__id">{{ question.question_id }}</span>
      <span class="eval-question-card__text">{{ question.question }}</span>
      <a-tag v-if="statusTag" :color="statusTag.color" class="eval-question-card__status">
        {{ statusTag.label }}
      </a-tag>
      <a-button
        type="link"
        size="small"
        class="eval-question-card__eval-btn"
        :loading="evaluating"
        @click.stop="$emit('evaluate', question.question_id)"
      >
        评测
      </a-button>
      <span class="eval-question-card__arrow">
        <RightOutlined :class="{ 'eval-question-card__arrow--expanded': expanded }" />
      </span>
    </div>
    <div v-if="expanded && detail" class="eval-question-card__body">
      <!-- 思考链路 -->
      <div class="eval-chain">
        <div class="eval-chain__title">分析链路</div>
        <div
          v-for="(step, idx) in thinkingChain"
          :key="`step-${idx}`"
          class="eval-chain__step"
        >
          <span class="eval-chain__badge">{{ idx + 1 }}</span>
          <span class="eval-chain__label">{{ step.label }}</span>
          <span class="eval-chain__value">{{ step.value }}</span>
          <a-button
            v-if="step.hasDetail"
            type="link"
            size="small"
            @click.stop="toggleStep(idx)"
          >
            {{ expandedSteps.has(idx) ? '收起' : '详情' }}
          </a-button>
          <div v-if="step.hasDetail && expandedSteps.has(idx)" class="eval-chain__detail">
            <!-- 意图识别详情 -->
            <template v-if="step.label === '意图识别'">
              <div class="eval-detail-row">
                <span class="eval-detail-label">任务类型:</span>
                <span>{{ String(prediction?.task_type || question.task_type || '—') }}</span>
              </div>
              <div class="eval-detail-row">
                <span class="eval-detail-label">意图层级:</span>
                <span>{{ question.intent_level }}</span>
              </div>
              <div v-if="prediction?.strategy" class="eval-detail-row">
                <span class="eval-detail-label">策略:</span>
                <span>{{ String(prediction.strategy) }}</span>
              </div>
            </template>

            <!-- 证据检索详情 -->
            <template v-if="step.label === '证据检索'">
              <div
                v-for="(c, ci) in citations"
                :key="`citation-${ci}`"
                class="eval-citation-card"
              >
                <div class="eval-citation-meta">
                  <span class="eval-citation-index">[{{ ci + 1 }}]</span>
                  <span v-if="c.score" class="eval-citation-score">得分: {{ Number(c.score).toFixed(4) }}</span>
                </div>
                <div v-if="c.doc_title || c.doc_id" class="eval-citation-location">
                  {{ String(c.doc_title || c.doc_id) }}
                  <template v-if="c.page_idx"> · 页码: P{{ c.page_idx }}</template>
                </div>
                <div v-if="c.section_path" class="eval-citation-section">
                  章节: {{ String(c.section_path) }}
                </div>
                <div v-if="c.content || c.snippet" class="eval-citation-content">
                  {{ String(c.content || c.snippet).slice(0, 300) }}
                </div>
              </div>
              <div v-if="!citations.length" class="eval-detail-empty">无检索结果</div>
            </template>

            <!-- Prompt 拼装详情 -->
            <template v-if="step.label === 'Prompt 拼装'">
              <div class="eval-prompt-block">
                <div class="eval-prompt-label">问题:</div>
                <div class="eval-prompt-text">{{ question.question }}</div>
              </div>
              <div class="eval-prompt-block">
                <div class="eval-prompt-label">证据片段:</div>
                <div
                  v-for="(c, ci) in citations.slice(0, 5)"
                  :key="`prompt-citation-${ci}`"
                  class="eval-prompt-citation"
                >
                  <span class="eval-citation-index">[{{ ci + 1 }}]</span>
                  {{ String(c.snippet || c.content || '').slice(0, 200) || '(无片段)' }}
                </div>
              </div>
            </template>

            <!-- LLM 回答详情 -->
            <template v-if="step.label === 'LLM 回答'">
              <div v-if="prediction?.thinking" class="eval-thinking-block">
                <div class="eval-prompt-label">思考过程:</div>
                <div class="eval-thinking-text">{{ String(prediction.thinking) }}</div>
              </div>
              <div class="eval-prompt-block">
                <div class="eval-prompt-label">最终回答:</div>
                <div class="eval-prompt-text">{{ String(prediction?.answer || '—') }}</div>
              </div>
            </template>
          </div>
        </div>
      </div>

      <!-- 正确性校验 -->
      <div v-if="checkDetails.length" class="eval-section">
        <div class="eval-section__title">正确性校验</div>
        <div
          v-for="(check, ci) in checkDetails"
          :key="`check-${ci}`"
          class="eval-check-item"
          :class="{ 'eval-check-item--passed': check.passed, 'eval-check-item--failed': !check.passed }"
        >
          <span class="eval-check-icon">{{ check.passed ? '✓' : '✗' }}</span>
          <span class="eval-check-type">{{ check.type }}</span>
          <span class="eval-check-keywords">关键词: {{ (check.keywords || []).join(', ') }}</span>
        </div>
      </div>

      <!-- 检索评测结果 -->
      <div v-if="retrievalScores" class="eval-section">
        <div class="eval-section__title">检索评测</div>
        <div class="eval-score-grid">
          <div v-if="retrievalScores['hit@3'] !== undefined" class="eval-score-item">
            <span class="eval-score-label">Hit@3</span>
            <span class="eval-score-value">{{ ((retrievalScores['hit@3'] as number) * 100).toFixed(1) }}%</span>
          </div>
          <div v-if="retrievalScores['hit@5'] !== undefined" class="eval-score-item">
            <span class="eval-score-label">Hit@5</span>
            <span class="eval-score-value">{{ ((retrievalScores['hit@5'] as number) * 100).toFixed(1) }}%</span>
          </div>
          <div v-if="retrievalScores.mrr !== undefined" class="eval-score-item">
            <span class="eval-score-label">MRR</span>
            <span class="eval-score-value">{{ ((retrievalScores.mrr as number) * 100).toFixed(1) }}%</span>
          </div>
          <div v-if="retrievalScores.evaluated === false" class="eval-score-item eval-score-item--na">
            <span class="eval-score-label">状态</span>
            <span class="eval-score-value">未评测（无检索标准）</span>
          </div>
        </div>
      </div>

      <!-- 标准答案对比 -->
      <div class="eval-section">
        <div class="eval-section__title">答案对比</div>
        <div class="eval-comparison">
          <div class="eval-comparison__col">
            <div class="eval-comparison__label">系统回答</div>
            <div class="eval-comparison__content">
              {{ String(prediction?.answer || '—') }}
            </div>
          </div>
          <div class="eval-comparison__col">
            <div class="eval-comparison__label">标准答案</div>
            <div class="eval-comparison__content">
              {{ question.answer_gold?.gold_answer || '—' }}
            </div>
          </div>
        </div>
      </div>

      <!-- 标准思考过程 -->
      <div v-if="question.answer_gold?.thought_process" class="eval-section">
        <div class="eval-section__title">标准思考过程</div>
        <div class="eval-thinking-gold">
          {{ question.answer_gold.thought_process }}
        </div>
      </div>

      <!-- 错误信息 -->
      <div v-if="detail.error" class="eval-section eval-section--error">
        错误: {{ detail.error }}
      </div>

      <!-- 耗时 -->
      <div v-if="detail.latency_ms" class="eval-latency">
        耗时: {{ detail.latency_ms }}ms
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { RightOutlined } from '@ant-design/icons-vue'
import EvalLevelBadge from './EvalLevelBadge.vue'
import type { EvalQuestion, EvalRunDetail } from '../types/eval'

interface ThinkingStep {
  label: string
  value: string
  hasDetail: boolean
}

const props = defineProps<{
  question: EvalQuestion
  detail: EvalRunDetail | null
  expanded: boolean
  evaluating: boolean
}>()

defineEmits<{
  toggle: [questionId: string]
  evaluate: [questionId: string]
}>()

const expandedSteps = ref<Set<number>>(new Set())

const toggleStep = (idx: number) => {
  const next = new Set(expandedSteps.value)
  if (next.has(idx)) {
    next.delete(idx)
  } else {
    next.add(idx)
  }
  expandedSteps.value = next
}

const statusTagMap: Record<string, { color: string; label: string }> = {
  passed: { color: 'success', label: '通过' },
  failed: { color: 'error', label: '未通过' },
  running: { color: 'processing', label: '运行中' },
  error: { color: 'warning', label: '错误' },
  pending: { color: 'default', label: '待运行' },
  skipped: { color: 'default', label: '未评测' },
}

const statusTag = computed(() => {
  const status = props.detail?.status || 'pending'
  return statusTagMap[status] || null
})

const prediction = computed(() => {
  const p = props.detail?.prediction as Record<string, unknown> | null
  return p
})

const citations = computed<Array<Record<string, unknown>>>(() => {
  const c = prediction.value?.citations
  return Array.isArray(c) ? c : []
})

const retrievalScores = computed<Record<string, unknown> | null>(() => {
  const allScores = props.detail?.all_scores as Record<string, Record<string, unknown>> | null
  if (allScores?.retrieval) {
    return allScores.retrieval
  }
  const scores = props.detail?.scores as Record<string, unknown> | null
  if (scores?.['hit@5'] !== undefined) {
    return scores
  }
  return null
})

const checkDetails = computed<Array<{ type: string; keywords: string[]; passed: boolean }>>(() => {
  const allScores = props.detail?.all_scores as Record<string, Record<string, unknown>> | null
  const answerScores = allScores?.answer || props.detail?.scores
  if (!answerScores) return []
  const details = answerScores.check_details as Array<{ type: string; keywords: string[]; passed: boolean }> | undefined
  return details || []
})

const thinkingChain = computed<ThinkingStep[]>(() => {
  const steps: ThinkingStep[] = []
  steps.push({
    label: '意图识别',
    value: `${enrichedQuestion.value.task_typeLabel || enrichedQuestion.value.task_type} · ${enrichedQuestion.value.intent_level}`,
    hasDetail: true,
  })
  if (citations.value.length) {
    steps.push({
      label: '证据检索',
      value: `命中 ${citations.value.length} 条`,
      hasDetail: true,
    })
  }
  if (citations.value.length && prediction.value?.answer) {
    steps.push({
      label: 'Prompt 拼装',
      value: '问题 + 证据 → LLM',
      hasDetail: true,
    })
  }
  if (prediction.value?.answer) {
    steps.push({
      label: 'LLM 回答',
      value: 'LLM 生成',
      hasDetail: true,
    })
  }
  return steps
})

const enrichedQuestion = computed(() => {
  const q = { ...props.question } as EvalQuestion & { task_typeLabel?: string }
  const taskTypeLabels: Record<string, string> = {
    definition: '定义查询',
    content_qa: '内容问答',
    locate: '定位查询',
    locate_qa: '定位问答',
    table_explain: '表格解读',
    table_qa: '表格问答',
    table_lookup: '表格查找',
    schema_qa: 'Schema 问答',
    analytic_sql: '分析 SQL',
    sql: 'SQL 查询',
    exam_case: '案例题',
    mixed: '混合题',
  }
  q.task_typeLabel = taskTypeLabels[q.task_type] || q.task_type
  return q
})
</script>

<style lang="less" scoped>
.eval-question-card {
  border: 1px solid var(--border-color);
  border-radius: 6px;
  margin-bottom: 8px;
  cursor: pointer;
  transition: all 0.2s;
  background: var(--bg-secondary);

  &:hover {
    border-color: @evals-primary;
  }

  &--expanded {
    border-color: @evals-primary;
    cursor: default;
  }

  &__header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 12px;
    cursor: pointer;
  }

  &__id {
    font-size: 12px;
    color: var(--text-secondary, rgba(0, 0, 0, 0.45));
    flex-shrink: 0;
  }

  &__text {
    flex: 1;
    font-size: 13px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  &__status {
    flex-shrink: 0;
  }

  &__eval-btn {
    flex-shrink: 0;
    padding: 0 4px;
    font-size: 12px;
  }

  &__arrow {
    flex-shrink: 0;
    transition: transform 0.2s;

    &--expanded {
      transform: rotate(90deg);
    }
  }

  &__body {
    padding: 0 12px 12px;
    border-top: 1px solid var(--border-color);
  }
}

.eval-chain {
  margin-top: 10px;

  &__title {
    font-size: 13px;
    font-weight: 600;
    margin-bottom: 8px;
    color: var(--text-primary, rgba(0, 0, 0, 0.88));
  }

  &__step {
    display: flex;
    align-items: flex-start;
    gap: 6px;
    padding: 4px 0;
    font-size: 12px;
    line-height: 1.6;
    flex-wrap: wrap;
  }

  &__badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 18px;
    height: 18px;
    border-radius: 50%;
    background: @evals-primary;
    color: var(--bg-secondary);
    font-size: 11px;
    flex-shrink: 0;
  }

  &__label {
    font-weight: 500;
    color: var(--text-primary, rgba(0, 0, 0, 0.88));
    flex-shrink: 0;
  }

  &__value {
    color: var(--text-secondary, rgba(0, 0, 0, 0.65));
  }

  &__detail {
    width: 100%;
    margin-left: 24px;
    padding: 8px;
    background: var(--bg-tertiary);
    border-radius: 4px;
    margin-top: 4px;
  }
}

.eval-detail-row {
  display: flex;
  gap: 8px;
  font-size: 12px;
  padding: 2px 0;
}

.eval-detail-label {
  color: var(--text-secondary, rgba(0, 0, 0, 0.45));
  flex-shrink: 0;
  min-width: 60px;
}

.eval-detail-empty {
  font-size: 12px;
  color: var(--text-secondary, rgba(0, 0, 0, 0.35));
  font-style: italic;
}

.eval-citation-card {
  padding: 6px 8px;
  margin-bottom: 4px;
  background: var(--bg-tertiary);
  border-radius: 4px;
  font-size: 12px;
}

.eval-citation-meta {
  display: flex;
  gap: 8px;
  align-items: center;
}

.eval-citation-index {
  color: @evals-primary;
  font-weight: 600;
}

.eval-citation-score {
  color: var(--text-secondary, rgba(0, 0, 0, 0.45));
}

.eval-citation-location {
  color: var(--text-primary, rgba(0, 0, 0, 0.88));
  margin-top: 2px;
}

.eval-citation-section {
  color: var(--text-secondary, rgba(0, 0, 0, 0.65));
  margin-top: 2px;
}

.eval-citation-content {
  color: var(--text-secondary, rgba(0, 0, 0, 0.55));
  margin-top: 4px;
  line-height: 1.5;
  max-height: 80px;
  overflow-y: auto;
}

.eval-prompt-block {
  margin-bottom: 8px;
}

.eval-prompt-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-secondary, rgba(0, 0, 0, 0.45));
  margin-bottom: 4px;
}

.eval-prompt-text {
  font-size: 12px;
  line-height: 1.6;
  padding: 6px 8px;
  background: var(--bg-tertiary);
  border-radius: 4px;
  max-height: 150px;
  overflow-y: auto;
}

.eval-prompt-citation {
  font-size: 12px;
  padding: 4px 8px;
  margin-bottom: 2px;
  background: var(--bg-tertiary);
  border-radius: 4px;
  line-height: 1.5;
}

.eval-thinking-block {
  margin-bottom: 8px;
}

.eval-thinking-text {
  font-size: 12px;
  line-height: 1.6;
  padding: 6px 8px;
  background: var(--bg-tertiary);
  border-radius: 4px;
  max-height: 200px;
  overflow-y: auto;
  white-space: pre-wrap;
}

.eval-section {
  margin-top: 12px;

  &__title {
    font-size: 13px;
    font-weight: 600;
    margin-bottom: 6px;
    color: var(--text-primary, rgba(0, 0, 0, 0.88));
  }

  &--error {
    color: @evals-error;
    font-size: 12px;
  }
}

.eval-check-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  padding: 4px 0;

  &--passed {
    color: var(--chat-success-color, #52c41a);
  }

  &--failed {
    color: var(--chat-error-color);
  }
}

.eval-check-icon {
  font-weight: 700;
}

.eval-check-type {
  font-weight: 500;
}

.eval-check-keywords {
  color: var(--text-secondary, rgba(0, 0, 0, 0.45));
}

.eval-score-grid {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}

.eval-score-item {
  display: flex;
  gap: 6px;
  font-size: 12px;

  &--na {
    color: var(--text-secondary, rgba(0, 0, 0, 0.35));
  }
}

.eval-score-label {
  color: var(--text-secondary, rgba(0, 0, 0, 0.45));
}

.eval-score-value {
  font-weight: 500;
}

.eval-comparison {
  display: flex;
  gap: 12px;

  &__col {
    flex: 1;
  }

  &__label {
    font-size: 12px;
    font-weight: 500;
    color: var(--text-secondary, rgba(0, 0, 0, 0.45));
    margin-bottom: 4px;
  }

  &__content {
    font-size: 12px;
    line-height: 1.6;
    padding: 8px;
    background: var(--bg-tertiary);
    border-radius: 4px;
    max-height: 200px;
    overflow-y: auto;
  }
}

.eval-thinking-gold {
  font-size: 12px;
  line-height: 1.6;
  padding: 8px;
  background: var(--bg-tertiary);
  border-radius: 4px;
  max-height: 200px;
  overflow-y: auto;
  white-space: pre-wrap;
}

.eval-latency {
  margin-top: 8px;
  font-size: 11px;
  color: var(--text-secondary, rgba(0, 0, 0, 0.35));
}
</style>
