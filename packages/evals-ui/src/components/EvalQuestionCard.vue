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
      <a-tag v-if="qualityTag" :color="qualityTag.color" class="eval-question-card__quality">
        {{ qualityTag.label }}
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
          <a-tag v-if="step.timing !== undefined" color="processing" class="eval-chain__timing">
            {{ (step.timing as number).toFixed(2) }}s
          </a-tag>
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
                <span class="eval-detail-label">检索策略:</span>
                <span>{{ String(prediction.strategy) }}</span>
              </div>
              <div class="eval-detail-row">
                <span class="eval-detail-label">元 SOP:</span>
                <span>{{ metaSopPath }}</span>
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
                  <span v-if="c.fusion_sources && c.fusion_sources.length" class="eval-citation-source">
                    来源: {{ formatFusionSources(c.fusion_sources) }}
                  </span>
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
              <div v-if="retrievalScores" class="eval-retrieval-scores">
                <div class="eval-detail-row">
                  <span class="eval-detail-label">检索评测:</span>
                  <span>
                    <template v-if="retrievalScores['hit@3'] !== undefined">Hit@3: {{ ((retrievalScores['hit@3'] as number) * 100).toFixed(1) }}% </template>
                    <template v-if="retrievalScores['hit@5'] !== undefined">Hit@5: {{ ((retrievalScores['hit@5'] as number) * 100).toFixed(1) }}% </template>
                    <template v-if="retrievalScores.mrr !== undefined">MRR: {{ ((retrievalScores.mrr as number) * 100).toFixed(1) }}%</template>
                    <template v-if="retrievalScores.evaluated === false">未评测（无检索标准）</template>
                  </span>
                </div>
              </div>
            </template>

            <!-- Prompt 拼装详情 -->
            <template v-if="step.label === 'Prompt 拼装'">
              <div v-if="systemPromptText" class="eval-prompt-block">
                <div class="eval-prompt-label">System Prompt:</div>
                <div class="eval-prompt-text">{{ systemPromptText }}</div>
              </div>
              <div class="eval-prompt-block">
                <div class="eval-prompt-label">User Message - 问题:</div>
                <div class="eval-prompt-text">{{ question.question }}</div>
              </div>
              <div class="eval-prompt-block">
                <div class="eval-prompt-label">User Message - 证据片段:</div>
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

      <!-- 语义评判 -->
      <div v-if="semanticResult" class="eval-section">
        <div class="eval-semantic-header">
          <span class="eval-section__title">语义评判</span>
          <span
            class="eval-semantic-score"
            :class="{
              'eval-semantic-score--passed': semanticResult.semantic_passed === true,
              'eval-semantic-score--failed': semanticResult.semantic_passed === false,
              'eval-semantic-score--fallback': semanticResult.semantic_fallback,
            }"
          >
            {{ semanticResult.semantic_score !== null ? Math.round(semanticResult.semantic_score * 100) + '分' : '—' }}
          </span>
          <span class="eval-semantic-threshold">
            （阈值{{ Math.round(semanticResult.semantic_threshold * 100) }}分）
          </span>
        </div>
        <div v-if="semanticResult.semantic_reason" class="eval-semantic-reason">
          {{ semanticResult.semantic_reason }}
        </div>
        <div v-if="semanticResult.semantic_fallback" class="eval-semantic-fallback-hint">
          ⚠ LLM 语义评判失败，已降级为关键词匹配
        </div>
      </div>

      <!-- 错误信息 -->
      <div v-if="detail.error" class="eval-section eval-section--error">
        错误: {{ detail.error }}
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { RightOutlined } from '@ant-design/icons-vue'
import EvalLevelBadge from './EvalLevelBadge.vue'
import type { EvalQuestion, EvalRunDetail, SemanticEvalResult } from '../types/eval'

interface ThinkingStep {
  label: string
  value: string
  hasDetail: boolean
  timing?: number
}

interface CitationItem {
  score?: unknown
  fusion_sources?: string[]
  doc_title?: unknown
  doc_id?: unknown
  page_idx?: unknown
  section_path?: unknown
  text?: unknown
  content?: unknown
  snippet?: unknown
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
  completed: { color: 'success', label: '已完成' },
  running: { color: 'processing', label: '评测中' },
  error: { color: 'warning', label: '出错' },
  pending: { color: 'default', label: '待评测' },
}

const qualityTagMap: Record<string, { color: string; label: string }> = {
  correct: { color: 'success', label: '正确' },
  wrong: { color: 'error', label: '错误' },
}

const statusTag = computed(() => {
  const status = props.detail?.status || 'pending'
  return statusTagMap[status] || null
})

const qualityTag = computed(() => {
  const quality = props.detail?.quality as string | null | undefined
  if (!quality) return null
  return qualityTagMap[quality] || null
})

const prediction = computed(() => {
  const p = props.detail?.prediction as Record<string, unknown> | null
  return p
})

const citations = computed<CitationItem[]>(() => {
  const c = prediction.value?.citations
  return Array.isArray(c) ? (c as CitationItem[]) : []
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

const semanticResult = computed<SemanticEvalResult | null>(() => {
  const allScores = props.detail?.all_scores as Record<string, Record<string, unknown>> | null
  const answerScores = allScores?.answer || props.detail?.scores
  if (!answerScores) return null
  const evaluated = answerScores.semantic_evaluated as boolean | undefined
  if (evaluated === undefined) return null
  return {
    semantic_score: (answerScores.semantic_score as number | null) ?? null,
    semantic_reason: String(answerScores.semantic_reason || ''),
    semantic_evaluated: evaluated,
    semantic_fallback: Boolean(answerScores.semantic_fallback),
    semantic_passed: answerScores.semantic_passed as boolean | null ?? null,
    semantic_threshold: Number(answerScores.semantic_threshold || 0.7),
  }
})

const stageTimings = computed<Record<string, number>>(() => {
  return (prediction.value?.stage_timings as Record<string, number>) || {}
})

const thinkingChain = computed<ThinkingStep[]>(() => {
  const steps: ThinkingStep[] = []
  const timings = stageTimings.value
  steps.push({
    label: '意图识别',
    value: `${enrichedQuestion.value.task_typeLabel || enrichedQuestion.value.task_type} · ${enrichedQuestion.value.intent_level}`,
    hasDetail: true,
    timing: timings['intent'],
  })
  if (citations.value.length) {
    const rd = (prediction.value?.retrieval_debug as Record<string, unknown>) || {}
    const sources = (rd.sources as Record<string, Record<string, unknown>>) || {}
    const denseCount = ((sources.canonical_dense?.input_hits as number) || 0)
    const sparseCount = ((sources.canonical_sparse?.input_hits as number) || 0)
    let tableCount = 0
    for (const key of Object.keys(sources)) {
      if (key.startsWith('table_') || key.startsWith('table')) {
        tableCount += (sources[key]?.input_hits as number) || 0
      }
    }
    const deduped = (rd.deduped_hits as number) || citations.value.length
    steps.push({
      label: '证据检索',
      value: `模糊语义 ${denseCount} 条 | 精确匹配 ${sparseCount} 条 | 表格 ${tableCount} 条 = 去重后 ${deduped} 条`,
      hasDetail: true,
      timing: timings['retrieval'],
    })
  }
  if (citations.value.length && prediction.value?.answer) {
    const promptTokens = (timings['prompt_tokens'] as number) || 0
    steps.push({
      label: 'Prompt 拼装',
      value: promptTokens ? `${promptTokens} tokens` : 'System Prompt + 问题 + 证据 → LLM',
      hasDetail: true,
      timing: timings['prompt'],
    })
  }
  if (prediction.value?.answer) {
    steps.push({
      label: 'LLM 回答',
      value: 'LLM 生成',
      hasDetail: true,
      timing: timings['llm'],
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

const metaSopPath = computed(() => {
  const level = props.question.intent_level || 'L1'
  const approachMap: Record<string, string> = {
    L1: '语义检索 → 直接回答（基于检索到的规范条文给出定义/组成）',
    L2: '语义检索 → 条款定位 → 回答（定位到具体条款后给出答案）',
    L3: '语义检索 → 标准计算 → 回答（检索规范参数后进行工程计算）',
    L4: '动态编排 → 多步推理 → 回答（复杂问题拆解为多步子任务）',
  }
  return approachMap[level] || '—'
})

const systemPromptText = computed(() => {
  return (prediction.value?.system_prompt as string) || ''
})

const fusionSourceLabels: Record<string, string> = {
  canonical_dense: 'Dense',
  canonical_sparse: 'Sparse',
  table_row_key: 'Table-RowKey',
  table_schema: 'Table-Schema',
  table_summary: 'Table-Summary',
  table_text_row: 'Table-TextRow',
  table_mapping: 'Table-Mapping',
  toc_dense: 'TOC-Dense',
  toc_sparse: 'TOC-Sparse',
}

const formatFusionSources = (sources: string[]): string => {
  return sources.map(s => fusionSourceLabels[s] || s).join(' + ')
}
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

  &__quality {
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
    align-items: center;
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
    color: var(--text-secondary, rgba(0, 0, 0, 0.25));
    font-size: 11px;
  }

  &__timing {
    flex-shrink: 0;
    font-size: 11px;
    line-height: 1;
    padding: 0 4px;
    border-radius: 2px;
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

.eval-retrieval-scores {
  margin-top: 8px;
  padding-top: 6px;
  border-top: 1px dashed var(--border-color);
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

.eval-citation-source {
  color: @evals-primary;
  font-size: 11px;
  margin-left: auto;
}

.eval-citation-location {
  color: var(--text-secondary, rgba(0, 0, 0, 0.45));
  font-family: 'KaiTi', 'STKaiti', serif;
  margin-top: 2px;
}

.eval-citation-section {
  color: var(--text-secondary, rgba(0, 0, 0, 0.45));
  font-family: 'KaiTi', 'STKaiti', serif;
  margin-top: 2px;
}

.eval-citation-content {
  color: var(--text-primary, rgba(0, 0, 0, 0.88));
  font-size: 13px;
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

.eval-semantic-header {
  display: flex;
  align-items: center;
}

.eval-semantic-header .eval-section__title {
  flex: 1;
}

.eval-semantic-score {
  font-weight: 600;

  &--passed {
    color: var(--chat-success-color, #52c41a);
  }

  &--failed {
    color: var(--chat-error-color);
  }

  &--fallback {
    color: @evals-warning;
  }
}

.eval-semantic-threshold {
  color: var(--text-secondary, rgba(0, 0, 0, 0.35));
  font-size: 11px;
}

.eval-semantic-reason {
  margin-top: 4px;
  color: var(--text-secondary, rgba(0, 0, 0, 0.65));
  line-height: 1.5;
}

.eval-semantic-fallback-hint {
  margin-top: 4px;
  color: @evals-warning;
  font-size: 11px;
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
</style>
