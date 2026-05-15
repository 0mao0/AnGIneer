<template>
  <div
    class="eval-question-card"
    :class="{ 'eval-question-card--expanded': expanded }"
  >
    <div class="eval-question-card__header">
      <EvalLevelBadge :level="question.intent_level" />
      <span class="eval-question-card__id">{{ question.question_id }}</span>
      <span class="eval-question-card__text">{{ localQuestionText }}</span>
      <a-tag v-if="displayStatusTag" :color="displayStatusTag.color" class="eval-question-card__status">
        {{ displayStatusTag.label }}
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
      <button
        type="button"
        class="eval-question-card__arrow-btn"
        :aria-label="expanded ? '收起题目详情' : '展开题目详情'"
        @click.stop="$emit('toggle', question.question_id)"
      >
        <RightOutlined class="eval-question-card__arrow" :class="{ 'eval-question-card__arrow--expanded': expanded }" />
      </button>
    </div>
    <div v-if="expanded" class="eval-question-card__body">
      <div class="eval-question-card__editor">
        <div class="eval-question-card__editor-header">
          <div class="eval-question-card__editor-title">题目内容</div>
          <a-space size="small">
            <a-button
              v-if="!editing"
              size="small"
              class="eval-question-card__editor-action"
              :disabled="evaluating"
              @click="startEditing"
            >
              编辑题目
            </a-button>
            <template v-else>
              <a-button
                size="small"
                type="primary"
                class="eval-question-card__editor-action"
                :loading="savingEdit"
                @click="saveEdit"
              >
                保存
              </a-button>
              <a-button
                size="small"
                class="eval-question-card__editor-action"
                :disabled="savingEdit"
                @click="cancelEdit"
              >
                取消
              </a-button>
            </template>
          </a-space>
        </div>
        <a-textarea
          v-if="editing"
          v-model:value="editText"
          class="eval-question-card__edit-input"
          :auto-size="{ minRows: 2, maxRows: 6 }"
          :disabled="savingEdit"
          @keydown.ctrl.enter.prevent="saveEdit"
        />
        <div v-else class="eval-question-card__editor-content">{{ localQuestionText }}</div>
      </div>

      <div v-if="evaluating" class="eval-question-card__loading-state">
        <a-spin size="small" />
        <span>{{ detail ? '正在更新本次评测结果...' : '正在评测，结果返回后会自动展示。' }}</span>
      </div>

      <div v-if="detail && isFlowTraceLevel" class="eval-chain">
        <div class="eval-chain__title">{{ flowTraceTitle }}</div>
        <div
          v-for="(stage, idx) in flowTraceStages"
          :key="stage.key"
          class="eval-chain__step"
        >
          <span class="eval-chain__badge">{{ idx + 1 }}</span>
          <a-tag v-if="stage.timing !== undefined" color="processing" class="eval-chain__timing">
            {{ (stage.timing as number).toFixed(2) }}s
          </a-tag>
          <span class="eval-chain__label">{{ stage.label }}</span>
          <span class="eval-chain__value">{{ stage.value }}</span>
          <a-button
            v-if="stage.hasDetail"
            type="link"
            size="small"
            @click.stop="toggleStep(stage.key)"
          >
            {{ isExpanded(stage.key) ? '收起' : '详情' }}
          </a-button>
          <div v-if="stage.hasDetail && isExpanded(stage.key)" class="eval-chain__detail">
            <template v-if="stage.detailType === 'intent'">
              <div class="eval-detail-row">
                <span class="eval-detail-label">任务类型:</span>
                <span>{{ String(prediction?.task_type || question.task_type || '—') }}</span>
              </div>
              <div class="eval-detail-row">
                <span class="eval-detail-label">意图层级:</span>
                <span>{{ intentDebug.intent_level || traceMeta.level || '—' }}</span>
              </div>
              <div class="eval-detail-row">
                <span class="eval-detail-label">意图类型:</span>
                <span>{{ intentDebug.intent_type || '—' }}</span>
              </div>
              <div class="eval-detail-row">
                <span class="eval-detail-label">服务模式:</span>
                <span>{{ intentDebug.service_mode || traceMeta.service_mode || '—' }}</span>
              </div>
              <div v-if="intentDebug.reason" class="eval-detail-block">
                <div class="eval-prompt-label">判定理由:</div>
                <div class="eval-rich-text eval-rich-text--compact" v-html="renderRichText(intentDebug.reason)" />
              </div>
            </template>

            <template v-else-if="stage.detailType === 'source'">
              <div class="eval-detail-row">
                <span class="eval-detail-label">执行类型:</span>
                <span>{{ flowTraceTitle }}</span>
              </div>
              <div class="eval-detail-row">
                <span class="eval-detail-label">SOP 名称:</span>
                <span>{{ flowDebug.sop_name || routeDebug.matched_sop_name || routeDebug.matched_sop_id || '—' }}</span>
              </div>
              <div class="eval-detail-row">
                <span class="eval-detail-label">置信度:</span>
                <span>{{ routeConfidenceText }}</span>
              </div>
              <div v-if="flowDebug.summary || routeDebug.reason" class="eval-detail-block">
                <div class="eval-prompt-label">{{ isDynamicFlowLevel ? '动态摘要:' : '执行摘要:' }}</div>
                <div
                  class="eval-rich-text eval-rich-text--compact"
                  v-html="renderRichText(flowDebug.summary || routeDebug.reason || '—')"
                />
              </div>
            </template>

            <template v-else-if="stage.detailType === 'route'">
              <div class="eval-detail-row">
                <span class="eval-detail-label">路由类型:</span>
                <span>{{ routeDebug.route_kind || '—' }}</span>
              </div>
              <div class="eval-detail-row">
                <span class="eval-detail-label">命中 SOP:</span>
                <span>{{ routeDebug.matched_sop_name || routeDebug.matched_sop_id || '—' }}</span>
              </div>
              <div v-if="routeDebug.reason" class="eval-detail-block">
                <div class="eval-prompt-label">路由说明:</div>
                <div class="eval-rich-text eval-rich-text--compact" v-html="renderRichText(routeDebug.reason)" />
              </div>
              <div v-if="routeArgsEntries.length" class="eval-detail-block">
                <div class="eval-prompt-label">参数抽取:</div>
                <div
                  v-for="([key, val]) in routeArgsEntries"
                  :key="`arg-${key}`"
                  class="eval-detail-row"
                >
                  <span class="eval-detail-label">{{ key }}:</span>
                  <span>{{ formatOutputVal(val) }}</span>
                </div>
              </div>
              <div v-if="routeMissingArgs.length" class="eval-detail-block">
                <div class="eval-prompt-label">缺失参数:</div>
                <div class="eval-detail-empty">{{ routeMissingArgs.join(', ') }}</div>
              </div>
              <div v-if="routeCandidates.length" class="eval-detail-block">
                <div class="eval-prompt-label">{{ isDynamicFlowLevel ? '动态候选' : 'SOP 候选' }}:</div>
                <div
                  v-for="candidate in routeCandidates"
                  :key="candidate.id"
                  class="eval-citation-card"
                >
                  <div class="eval-citation-meta">
                    <span class="eval-citation-index">{{ candidate.id }}</span>
                    <span v-if="candidate.recall_score !== undefined" class="eval-citation-score">
                      recall: {{ Number(candidate.recall_score).toFixed(4) }}
                    </span>
                  </div>
                  <div
                    class="eval-citation-content"
                    v-html="renderRichText(candidate.name || candidate.description || '—')"
                  />
                </div>
              </div>
            </template>

            <template v-else-if="stage.detailType === 'steps'">
              <div v-if="sopTraceSteps.length" class="eval-flow-steps">
                <div
                  v-for="step in sopTraceSteps"
                  :key="step.step_id"
                  class="eval-flow-step-card"
                  :class="{
                    'eval-flow-step-card--success': step.status === 'success',
                    'eval-flow-step-card--error': isErrorStatus(step.status),
                  }"
                >
                  <div class="eval-flow-step-card__header">
                    <span class="eval-flow-step-card__index">{{ step.step_index }}</span>
                    <span class="eval-flow-step-card__name">{{ step.step_name }}</span>
                    <span v-if="step.tool" class="eval-flow-step-card__tool">{{ step.tool }}</span>
                    <a-tag v-if="step.duration" color="processing" class="eval-flow-step-card__duration">
                      {{ step.duration.toFixed(2) }}s
                    </a-tag>
                    <a-button
                      type="link"
                      size="small"
                      @click.stop="toggleStep(`flow-step-${step.step_id}`)"
                    >
                      {{ isExpanded(`flow-step-${step.step_id}`) ? '收起' : '详情' }}
                    </a-button>
                  </div>
                  <div v-if="step.description" class="eval-flow-step-card__desc">{{ step.description }}</div>
                  <div
                    v-if="step.error"
                    class="eval-flow-step-card__error"
                  >
                    {{ step.error }}
                  </div>
                  <div
                    v-if="isExpanded(`flow-step-${step.step_id}`)"
                    class="eval-flow-step-card__detail"
                  >
                    <div class="eval-prompt-block">
                      <div class="eval-prompt-label">输入:</div>
                      <div class="eval-prompt-text">{{ formatOutputVal(step.inputs) }}</div>
                    </div>
                    <div class="eval-prompt-block">
                      <div class="eval-prompt-label">输出:</div>
                      <div class="eval-prompt-text">{{ formatOutputVal(step.outputs) }}</div>
                    </div>
                  </div>
                </div>
              </div>
              <div v-else class="eval-detail-empty">暂无 SOP 步骤追踪</div>
            </template>

            <template v-else-if="stage.detailType === 'answer'">
              <div v-if="answerHeadline" class="eval-answer-summary">
                {{ answerHeadline }}
              </div>
              <div class="eval-prompt-block">
                <div class="eval-prompt-label">最终回答:</div>
                <div class="eval-rich-text eval-rich-text--answer" v-html="renderRichText(answerText)" />
              </div>
              <div v-if="citations.length" class="eval-detail-block">
                <div class="eval-prompt-label">引用证据:</div>
                <div
                  v-for="(c, ci) in citations"
                  :key="`flow-answer-citation-${ci}`"
                  class="eval-citation-card"
                >
                  <div class="eval-citation-meta">
                    <span class="eval-citation-index">[{{ ci + 1 }}]</span>
                    <span v-if="c.doc_title || c.doc_id" class="eval-citation-source">
                      {{ String(c.doc_title || c.doc_id) }}
                    </span>
                  </div>
                  <div
                    class="eval-citation-content"
                    v-html="renderRichText(String(c.content || c.snippet || '—').slice(0, 300))"
                  />
                </div>
              </div>
            </template>

            <template v-else-if="stage.detailType === 'evaluation'">
              <div v-if="traceSummary" class="eval-detail-block">
                <div class="eval-prompt-label">诊断摘要:</div>
                <div class="eval-rich-text eval-rich-text--compact" v-html="renderRichText(traceSummary)" />
              </div>
              <div v-if="correctnessSummary" class="eval-detail-block">
                <div class="eval-prompt-label">正确性校验:</div>
                <div class="eval-check-summary" :class="correctnessSummaryClass">
                  <span class="eval-check-icon">{{ correctnessAllPassed ? '✓' : '✗' }}</span>
                  <span>{{ correctnessSummary }}</span>
                </div>
              </div>
              <div v-if="traceIssues.length" class="eval-detail-block">
                <div class="eval-prompt-label">诊断问题:</div>
                <div
                  v-for="issue in traceIssues"
                  :key="issue.code"
                  class="eval-citation-card"
                >
                  <div class="eval-citation-meta">
                    <span class="eval-citation-index">{{ issue.code }}</span>
                  </div>
                  <div class="eval-citation-content" v-html="renderRichText(issue.message)" />
                </div>
              </div>
            </template>
          </div>
        </div>
      </div>

      <div v-else-if="detail && isCasualTraceLevel" class="eval-chain">
        <div class="eval-chain__title">{{ casualTraceTitle }}</div>
        <div
          v-for="(step, idx) in casualTraceSteps"
          :key="step.key"
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
            @click.stop="toggleStep(step.key)"
          >
            {{ isExpanded(step.key) ? '收起' : '详情' }}
          </a-button>
          <div v-if="step.hasDetail && isExpanded(step.key)" class="eval-chain__detail">
            <template v-if="step.detailType === 'intent'">
              <div class="eval-detail-row">
                <span class="eval-detail-label">意图层级:</span>
                <span>{{ intentDebug.intent_level || traceMeta.level || '—' }}</span>
              </div>
              <div class="eval-detail-row">
                <span class="eval-detail-label">服务模式:</span>
                <span>{{ intentDebug.service_mode || traceMeta.service_mode || 'casual_chat' }}</span>
              </div>
              <div v-if="intentDebug.reason" class="eval-detail-block">
                <div class="eval-prompt-label">判定理由:</div>
                <div class="eval-rich-text eval-rich-text--compact" v-html="renderRichText(intentDebug.reason)" />
              </div>
            </template>
            <template v-else>
              <div v-if="answerHeadline" class="eval-answer-summary">
                {{ answerHeadline }}
              </div>
              <div class="eval-prompt-block">
                <div class="eval-prompt-label">最终回答:</div>
                <div class="eval-rich-text eval-rich-text--answer" v-html="renderRichText(answerText)" />
              </div>
            </template>
          </div>
        </div>
      </div>

      <div v-else-if="detail" class="eval-chain">
        <div class="eval-chain__title">{{ knowledgeTraceTitle }}</div>
        <div
          v-for="(step, idx) in knowledgeTraceSteps"
          :key="step.key"
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
            @click.stop="toggleStep(step.key)"
          >
            {{ isExpanded(step.key) ? '收起' : '详情' }}
          </a-button>
          <div v-if="step.hasDetail && isExpanded(step.key)" class="eval-chain__detail">
            <!-- 意图识别详情 -->
            <template v-if="step.label === '意图识别'">
              <div class="eval-detail-row">
                <span class="eval-detail-label">任务类型:</span>
                <span>{{ String(prediction?.task_type || question.task_type || '—') }}</span>
              </div>
              <div class="eval-detail-row">
                <span class="eval-detail-label">意图层级:</span>
                <span>{{ intentDebug.intent_level || traceMeta.level }}</span>
              </div>
              <div class="eval-detail-row">
                <span class="eval-detail-label">服务模式:</span>
                <span>{{ intentDebug.service_mode || traceMeta.service_mode || '—' }}</span>
              </div>
              <div v-if="intentDebug.reason" class="eval-detail-block">
                <div class="eval-prompt-label">判定理由:</div>
                <div class="eval-rich-text eval-rich-text--compact" v-html="renderRichText(intentDebug.reason)" />
              </div>
              <div class="eval-detail-row">
                <span class="eval-detail-label">元 SOP:</span>
                <span>{{ metaSopPath }}</span>
              </div>
            </template>

            <!-- 证据检索详情 -->
            <template v-if="step.label === '证据检索' || step.label === 'SQL/条款定位'">
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
                <div
                  v-if="c.content || c.snippet"
                  class="eval-citation-content"
                  v-html="renderRichText(String(c.content || c.snippet).slice(0, 300))"
                />
              </div>
              <div v-if="!citations.length" class="eval-detail-empty">无检索结果</div>
              <div v-if="step.label === 'SQL/条款定位'" class="eval-detail-row">
                <span class="eval-detail-label">查询策略:</span>
                <span>{{ String(prediction?.strategy || routeDebug.route_kind || '—') }}</span>
              </div>
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
                <div class="eval-rich-text eval-rich-text--compact" v-html="renderRichText(systemPromptText)" />
              </div>
              <div class="eval-prompt-block">
                <div class="eval-prompt-label">User Message - 问题:</div>
                <div class="eval-rich-text eval-rich-text--compact" v-html="renderRichText(question.question)" />
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
                <div class="eval-rich-text eval-rich-text--compact" v-html="renderRichText(prediction.thinking)" />
              </div>
              <div v-if="answerHeadline" class="eval-answer-summary">
                {{ answerHeadline }}
              </div>
              <div class="eval-prompt-block">
                <div class="eval-prompt-label">最终回答:</div>
                <div class="eval-rich-text eval-rich-text--answer" v-html="renderRichText(answerText)" />
              </div>
            </template>
          </div>
        </div>
      </div>

      <!-- 正确性校验 -->
      <div v-if="correctnessSummary" class="eval-section">
        <div class="eval-section__header">
          <div class="eval-section__title">正确性校验</div>
          <a-button
            v-if="checkDetails.length"
            type="link"
            size="small"
            @click.stop="toggleStep('correctness-rules')"
          >
            {{ isExpanded('correctness-rules') ? '收起规则' : '查看规则' }}
          </a-button>
        </div>
        <div class="eval-check-summary" :class="correctnessSummaryClass">
          <span class="eval-check-icon">{{ correctnessAllPassed ? '✓' : '✗' }}</span>
          <span>{{ correctnessSummary }}</span>
        </div>
        <div v-if="checkDetails.length && isExpanded('correctness-rules')" class="eval-check-rules">
          <div
            v-for="(check, ci) in checkDetails"
            :key="`check-${ci}`"
            class="eval-check-rule"
          >
            <span class="eval-check-type">{{ check.type }}</span>
            <span class="eval-check-keywords">{{ formatCheckRule(check) }}</span>
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
              <div v-if="answerHeadline" class="eval-answer-summary">
                {{ answerHeadline }}
              </div>
              <div class="eval-rich-text eval-rich-text--answer" v-html="renderRichText(answerText)" />
            </div>
          </div>
          <div class="eval-comparison__col">
            <div class="eval-comparison__label">标准答案</div>
            <div class="eval-comparison__content">
              <div class="eval-rich-text eval-rich-text--compact" v-html="renderRichText(question.answer_gold?.gold_answer || '—')" />
            </div>
          </div>
        </div>
      </div>

      <!-- 标准思考过程 -->
      <div v-if="question.answer_gold?.thought_process" class="eval-section">
        <div class="eval-section__title">标准思考过程</div>
        <div class="eval-rich-text eval-rich-text--answer" v-html="renderRichText(question.answer_gold.thought_process)" />
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
        <div
          v-if="semanticResult.semantic_reason"
          class="eval-semantic-reason eval-rich-text eval-rich-text--compact"
          v-html="renderRichText(semanticResult.semantic_reason)"
        />
        <div v-if="semanticResult.semantic_fallback" class="eval-semantic-fallback-hint">
          ⚠ LLM 语义评判失败，已降级为关键词匹配
        </div>
      </div>

      <!-- 错误信息 -->
      <div v-if="detail?.error" class="eval-section eval-section--error">
        错误: {{ detail.error }}
      </div>
      <div v-else-if="!detail && !evaluating" class="eval-question-card__empty">
        点击“评测”后可在此查看链路详情和结果。
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { RightOutlined } from '@ant-design/icons-vue'
import { renderMarkdownToHtml } from '@angineer/ui-kit/utils/markdown'
import EvalLevelBadge from './EvalLevelBadge.vue'
import type { EvalQuestion, EvalRunDetail, SemanticEvalResult } from '../types/eval'

interface ThinkingStep {
  key: string
  label: string
  value: string
  hasDetail: boolean
  detailType?: 'intent' | 'source' | 'route' | 'steps' | 'answer' | 'evaluation'
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

interface SopTraceStep {
  step_id: string
  step_name: string
  step_index: number
  tool: string
  description: string
  inputs: Record<string, unknown>
  outputs: Record<string, unknown> | null
  duration: number
  status: string
  error: string | null
}

interface RouteCandidate {
  id: string
  name?: string
  description?: string
  recall_score?: number
}

interface TraceIssue {
  code: string
  message: string
}

interface CorrectnessDetail {
  type: string
  keywords: string[]
  passed: boolean
}

const props = defineProps<{
  question: EvalQuestion
  detail: EvalRunDetail | null
  expanded: boolean
  evaluating: boolean
}>()

const emit = defineEmits<{
  toggle: [questionId: string]
  evaluate: [questionId: string]
  updated: []
}>()

const expandedSteps = ref<Set<string>>(new Set())
const editing = ref(false)
const editText = ref('')
const localQuestionText = ref(props.question.question)
const savingEdit = ref(false)

watch(() => props.question.question, (value) => {
  localQuestionText.value = value
})

watch(() => props.expanded, (value) => {
  if (!value) {
    cancelEdit()
  }
})

/** 进入展开区题目编辑模式。 */
const startEditing = () => {
  editText.value = localQuestionText.value
  editing.value = true
}

/** 取消题目编辑并恢复到当前已知文本。 */
const cancelEdit = () => {
  editing.value = false
  editText.value = localQuestionText.value
}

/** 保存编辑后的题目文本。 */
const saveEdit = async () => {
  const trimmed = editText.value.trim()
  if (!trimmed) {
    message.warning('题目不能为空')
    return
  }
  if (trimmed === localQuestionText.value) {
    editing.value = false
    return
  }
  savingEdit.value = true
  try {
    const resp = await fetch(
      `/api/evals/datasets/${props.question.dataset_id}/questions/${props.question.question_id}`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: trimmed }),
      }
    )
    if (resp.ok) {
      localQuestionText.value = trimmed
      editing.value = false
      message.success('题目已保存')
      emit('updated')
    } else {
      const errText = await resp.text().catch(() => '')
      message.error(`保存失败: ${errText || resp.status}`)
    }
  } catch (e: any) {
    message.error(`保存失败: ${e.message || e}`)
  } finally {
    savingEdit.value = false
  }
}

/** 切换链路节点或步骤详情的展开状态。 */
const toggleStep = (key: string) => {
  const next = new Set(expandedSteps.value)
  if (next.has(key)) {
    next.delete(key)
  } else {
    next.add(key)
  }
  expandedSteps.value = next
}

/** 判断链路节点或步骤详情当前是否处于展开状态。 */
const isExpanded = (key: string) => expandedSteps.value.has(key)

const displayStatusTag = computed(() => {
  if (props.evaluating || props.detail?.status === 'running') {
    return { color: 'processing', label: '评测中' }
  }

  const status = props.detail?.status || 'pending'
  const quality = props.detail?.quality as string | null | undefined
  if (status === 'completed') {
    if (quality === 'correct') {
      return { color: 'success', label: '已完成 · 正确' }
    }
    if (quality === 'wrong') {
      return { color: 'error', label: '已完成 · 错误' }
    }
    return { color: 'success', label: '已完成' }
  }

  if (status === 'error') {
    return { color: 'error', label: '出错' }
  }

  return { color: 'default', label: '待评测' }
})

const prediction = computed(() => {
  const p = props.detail?.prediction as Record<string, unknown> | null
  return p
})

const traceMeta = computed<Record<string, unknown>>(() => {
  return (prediction.value?.trace_meta as Record<string, unknown>) || {}
})

const intentDebug = computed<Record<string, unknown>>(() => {
  const fromPrediction = (prediction.value?.intent_debug as Record<string, unknown>) || {}
  const fromIntent = (prediction.value?.intent as Record<string, unknown>) || {}
  return { ...fromIntent, ...fromPrediction }
})

const routeDebug = computed<Record<string, unknown>>(() => {
  return (prediction.value?.route_debug as Record<string, unknown>) || {}
})

const flowDebug = computed<Record<string, unknown>>(() => {
  return (prediction.value?.flow_debug as Record<string, unknown>) || {}
})

const traceIssues = computed<TraceIssue[]>(() => {
  const issues = prediction.value?.issues
  return Array.isArray(issues) ? (issues as TraceIssue[]) : []
})

const traceSummary = computed(() => {
  return String(prediction.value?.trace_summary || prediction.value?.summary || '')
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

const checkDetails = computed<CorrectnessDetail[]>(() => {
  const allScores = props.detail?.all_scores as Record<string, Record<string, unknown>> | null
  const answerScores = allScores?.answer || props.detail?.scores
  if (!answerScores) return []
  const details = answerScores.check_details as CorrectnessDetail[] | undefined
  return details || []
})

const correctnessAllPassed = computed(() => {
  return checkDetails.value.length > 0 && checkDetails.value.every(check => check.passed)
})

const correctnessSummary = computed(() => {
  if (!checkDetails.value.length) return ''
  if (correctnessAllPassed.value) {
    if (explicitAnswerOption.value) {
      return `关键词校验通过，命中标准答案选项 ${explicitAnswerOption.value}`
    }
    return '关键词校验通过'
  }
  if (explicitAnswerOption.value) {
    return `关键词校验未完全通过，但当前回答显式给出了选项 ${explicitAnswerOption.value}`
  }
  const passedCount = checkDetails.value.filter(check => check.passed).length
  return `关键词校验未通过（${passedCount}/${checkDetails.value.length}）`
})

const correctnessSummaryClass = computed(() => {
  return correctnessAllPassed.value ? 'eval-check-summary--passed' : 'eval-check-summary--failed'
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

const currentIntentLevel = computed(() => {
  return String(
    intentDebug.value.intent_level || traceMeta.value.level || 'L1'
  )
})

/** 判断是否为需要展示闲聊直答链路的题目。 */
const isCasualTraceLevel = computed(() => currentIntentLevel.value === 'L0')

/** 判断是否为 L3/L4 的流程执行链路。 */
const isFlowTraceLevel = computed(() => {
  return currentIntentLevel.value === 'L3' || currentIntentLevel.value === 'L4'
})

const isDynamicFlowLevel = computed(() => currentIntentLevel.value === 'L4')

const flowTraceTitle = computed(() => {
  return String(traceMeta.value.title || (isDynamicFlowLevel.value ? '动态 SOP 执行' : '标准 SOP 执行'))
})

const knowledgeTraceTitle = computed(() => {
  return String(traceMeta.value.title || (currentIntentLevel.value === 'L2' ? '分析链路（SQL/条款定位）' : '分析链路'))
})

const casualTraceTitle = computed(() => {
  return String(traceMeta.value.title || '闲聊链路')
})

/** 获取 SOP 追踪步骤列表，并插入第0步显示题干已知条件。 */
const sopTraceSteps = computed<SopTraceStep[]>(() => {
  const trace = prediction.value?.sop_trace
  const steps: SopTraceStep[] = Array.isArray(trace) ? [...trace] : []
  const args = routeArgsEntries.value
  if (args.length) {
    const inputs: Record<string, unknown> = {}
    for (const [key, val] of args) {
      inputs[key] = val
    }
    steps.unshift({
      step_id: 'step_0',
      step_name: '已知条件',
      step_index: 0,
      tool: '',
      description: '从题干中提取的已知参数',
      inputs,
      outputs: null,
      duration: 0,
      status: 'success',
      error: null,
    })
  }
  return steps
})

const routeCandidates = computed<RouteCandidate[]>(() => {
  const candidates = routeDebug.value.candidates
  return Array.isArray(candidates) ? (candidates as RouteCandidate[]) : []
})

const routeArgsEntries = computed<Array<[string, unknown]>>(() => {
  const args = routeDebug.value.args
  if (!args || Array.isArray(args) || typeof args !== 'object') return []
  return Object.entries(args as Record<string, unknown>)
})

const routeMissingArgs = computed<string[]>(() => {
  const missing = routeDebug.value.missing_args
  return Array.isArray(missing) ? missing.map(item => String(item)) : []
})

const routeConfidenceText = computed(() => {
  const confidence = routeDebug.value.confidence
  if (typeof confidence === 'number') {
    return `${(confidence * 100).toFixed(1)}%`
  }
  return '—'
})

const answerText = computed(() => String(prediction.value?.answer || ''))

/** 格式化输出值，截断过长的内容 */
const formatOutputVal = (val: unknown): string => {
  if (val === null || val === undefined) return '—'
  const str = typeof val === 'object' ? JSON.stringify(val, null, 2) : String(val)
  return str.length > 200 ? str.slice(0, 200) + '…' : str
}

/** 将 markdown/公式文本渲染为可读 HTML。 */
const renderRichText = (content: unknown): string => {
  const text = String(content || '').trim()
  if (!text) return '<p>—</p>'
  return renderMarkdownToHtml(text, '')
}

/** 从回答中提取显式选项，便于生成最终结论摘要。 */
const extractExplicitOption = (text: string): string => {
  const normalizedText = text.replace(/\r\n/g, '\n')
  const lines = normalizedText
    .split('\n')
    .map(line => line.trim())
    .filter(Boolean)

  const strongPatterns = [
    /正确答案(?:是|为)?\s*[:：]?\s*[\*\s]*[\(\[]?\s*([A-D])\s*[\)\]]?/i,
    /对应选项(?:是|为)?\s*[:：]?\s*[\*\s]*[\(\[]?\s*([A-D])\s*[\)\]]?/i,
    /答案(?:是|为)?\s*[:：]?\s*[\*\s]*[\(\[]?\s*([A-D])\s*[\)\]]?/i,
    /故选\s*([A-D])/i,
    /因此选\s*([A-D])/i,
    /应选\s*([A-D])/i,
    /选\s*项?\s*[\(\[]?\s*([A-D])\s*[\)\]]?\s*(?:正确|即可|为答案)/i,
  ]

  // 优先从答案末尾往前找“明确结论句式”，避免误命中前面的选项列表。
  for (const line of [...lines].reverse()) {
    if (/对比选项|备选项|选项对比/i.test(line)) continue
    for (const pattern of strongPatterns) {
      const match = line.match(pattern)
      if (match?.[1]) return match[1].toUpperCase()
    }
  }

  // 兜底时只接受“看起来像结论”的单行，不接受包含多个候选项的列表行。
  const fallbackLines = [...lines].reverse().filter(line => {
    const optionTokenCount = (line.match(/[\(\[]\s*[A-D]\s*[\)\]]/gi) || []).length
    if (optionTokenCount > 1) return false
    if (/对比选项|备选项|选项对比/i.test(line)) return false
    return true
  })
  for (const line of fallbackLines) {
    const match = line.match(/\*\*[\(\[]?\s*([A-D])\s*[\)\]]\*\*|[\(\[]\s*([A-D])\s*[\)\]]/)
    const option = match?.[1] || match?.[2]
    if (option) return option.toUpperCase()
  }
  return ''
}

const explicitAnswerOption = computed(() => extractExplicitOption(answerText.value))

const answerHeadline = computed(() => {
  if (explicitAnswerOption.value) {
    return `最终结论：选项 ${explicitAnswerOption.value}`
  }
  const firstLine = answerText.value
    .split('\n')
    .map(line => line.trim())
    .find(Boolean)
  if (!firstLine) return ''
  const normalized = firstLine.replace(/^#+\s*/, '').replace(/\*\*/g, '')
  return normalized.length > 48 ? `${normalized.slice(0, 48)}...` : normalized
})

/** 判断步骤状态是否应视为错误。 */
const isErrorStatus = (status: string) => ['error', 'failed', 'fail'].includes(status)

const knowledgeTraceSteps = computed<ThinkingStep[]>(() => {
  const steps: ThinkingStep[] = []
  const timings = stageTimings.value
  steps.push({
    key: 'knowledge-intent',
    label: '意图识别',
    value: `${enrichedQuestion.value.taskTypeLabel || enrichedQuestion.value.task_type} · ${currentIntentLevel.value}`,
    hasDetail: true,
    detailType: 'intent',
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
      key: 'knowledge-evidence',
      label: currentIntentLevel.value === 'L2' ? 'SQL/条款定位' : '证据检索',
      value: `模糊语义 ${denseCount} 条 | 精确匹配 ${sparseCount} 条 | 表格 ${tableCount} 条 = 去重后 ${deduped} 条`,
      hasDetail: true,
      detailType: 'route',
      timing: timings['retrieval'],
    })
  }
  if (citations.value.length && prediction.value?.answer) {
    const promptTokens = (timings['prompt_tokens'] as number) || 0
    steps.push({
      key: 'knowledge-prompt',
      label: 'Prompt 拼装',
      value: promptTokens ? `${promptTokens} tokens` : 'System Prompt + 问题 + 证据 → LLM',
      hasDetail: true,
      timing: timings['prompt'],
    })
  }
  if (prediction.value?.answer) {
    steps.push({
      key: 'knowledge-answer',
      label: 'LLM 回答',
      value: 'LLM 生成',
      hasDetail: true,
      timing: timings['llm'],
    })
  }
  return steps
})

const casualTraceSteps = computed<ThinkingStep[]>(() => {
  const timings = stageTimings.value
  return [
    {
      key: 'casual-intent',
      label: '意图识别',
      value: `${enrichedQuestion.value.taskTypeLabel || enrichedQuestion.value.task_type} · ${currentIntentLevel.value}`,
      hasDetail: true,
      detailType: 'intent',
      timing: timings['intent'],
    },
    {
      key: 'casual-direct',
      label: '闲聊直答',
      value: String(traceMeta.value.title || 'casual_chat'),
      hasDetail: false,
      timing: timings['llm'],
    },
    {
      key: 'casual-answer',
      label: '最终回答',
      value: prediction.value?.answer ? 'LLM 生成' : '—',
      hasDetail: true,
      detailType: 'answer',
      timing: timings['llm'],
    },
  ]
})

/** 计算 SOP 步骤执行总耗时（不含虚拟的第0步）。 */
const sopExecutionTiming = computed(() => {
  const steps = sopTraceSteps.value.filter(s => s.step_index > 0)
  if (!steps.length) return undefined
  const total = steps.reduce((sum, s) => sum + (s.duration || 0), 0)
  return total || undefined
})

const flowTraceStages = computed<ThinkingStep[]>(() => {
  const timings = stageTimings.value
  return [
    {
      key: 'flow-intent',
      label: '意图识别',
      value: `${enrichedQuestion.value.taskTypeLabel || enrichedQuestion.value.task_type} · ${currentIntentLevel.value}`,
      hasDetail: true,
      detailType: 'intent',
      timing: timings['intent'],
    },
    {
      key: 'flow-route',
      label: 'SOP 路由',
      value: String(routeDebug.value.matched_sop_name || routeDebug.value.matched_sop_id || '待补充'),
      hasDetail: true,
      detailType: 'route',
      timing: timings['sop_route'],
    },
    {
      key: 'flow-steps',
      label: '步骤推进',
      value: (() => {
        const realStepCount = sopTraceSteps.value.filter(s => s.step_index > 0).length
        return realStepCount ? `${realStepCount} 步` : '暂无步骤追踪'
      })(),
      hasDetail: true,
      detailType: 'steps',
      timing: sopExecutionTiming.value,
    },
    {
      key: 'flow-answer',
      label: '最终回答',
      value: prediction.value?.answer ? 'LLM 生成' : '—',
      hasDetail: true,
      detailType: 'answer',
      timing: timings['llm'],
    },
    {
      key: 'flow-evaluation',
      label: '评测结论',
      value: traceIssues.value.length ? `${traceIssues.value.length} 个诊断问题` : '通过当前链路校验',
      hasDetail: true,
      detailType: 'evaluation',
    },
  ]
})

const enrichedQuestion = computed(() => {
  const q = { ...props.question } as EvalQuestion & { taskTypeLabel?: string }
  const taskTypeLabels: Record<string, string> = {
    casual_chat: '闲聊',
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
  q.taskTypeLabel = taskTypeLabels[q.task_type] || q.task_type
  return q
})

const metaSopPath = computed(() => {
  const level = currentIntentLevel.value || 'L1'
  const approachMap: Record<string, string> = {
    L0: '闲聊直答 → 回答（非工程规范问题，不进入检索与 SOP）',
    L1: '语义检索 → 直接回答（基于检索到的规范条文给出定义/组成）',
    L2: '语义检索 → 条款定位 → 回答（定位到具体条款后给出答案）',
    L3: '标准 SOP 执行 → 步骤推进 → 回答（命中预定义 SOP 并执行）',
    L4: '动态 SOP 执行 → 步骤推进 → 回答（通过 LLM 生成临时 SOP 并执行）',
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

/** 格式化检索来源标签 */
const formatFusionSources = (sources: string[]): string => {
  return sources.map(s => fusionSourceLabels[s] || s).join(' + ')
}

/** 将原始关键词规则整理为更适合前端展示的摘要。 */
const formatCheckRule = (check: CorrectnessDetail): string => {
  if (check.keywords?.length) {
    return `${check.passed ? '通过' : '失败'} / ${check.keywords.join('、')}`
  }
  return check.passed ? '通过' : '失败'
}
</script>

<style lang="less" scoped>
.eval-question-card {
  border: 1px solid var(--border-color);
  border-radius: 6px;
  margin-bottom: 8px;
  transition: all 0.2s;
  background: var(--bg-secondary);

  &:hover {
    border-color: @evals-primary;
  }

  &--expanded {
    border-color: @evals-primary;
  }

  &__header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 12px;
  }

  &__id {
    font-size: 12px;
    color: var(--text-secondary, rgba(0, 0, 0, 0.45));
    flex-shrink: 0;
  }

  &__text {
    flex: 1;
    min-width: 0;
    font-size: 13px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    cursor: text;
    user-select: text;
  }

  &__edit-input {
    font-size: 13px;
    width: 100%;
  }

  &__status {
    flex-shrink: 0;
    white-space: nowrap;
  }

  &__eval-btn {
    flex-shrink: 0;
    padding: 0 4px;
    font-size: 12px;
  }

  &__arrow-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    padding: 0;
    border: none;
    border-radius: 4px;
    background: transparent;
    color: var(--text-secondary, rgba(0, 0, 0, 0.45));
    cursor: pointer;
    transition: background-color 0.2s ease, color 0.2s ease;

    &:hover {
      background: var(--bg-tertiary);
      color: var(--text-primary, rgba(0, 0, 0, 0.88));
    }
  }

  &__arrow {
    transition: transform 0.2s;

    &--expanded {
      transform: rotate(90deg);
    }
  }

  &__body {
    padding: 12px;
    border-top: 1px solid var(--border-color);
  }

  &__editor {
    border: 1px solid var(--border-color);
    border-radius: 6px;
    padding: 10px 12px;
    background: var(--bg-primary);
  }

  &__editor-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 8px;
  }

  &__editor-title {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary, rgba(0, 0, 0, 0.88));
  }

  &__editor-action {
    font-size: 12px;
  }

  &__editor-content {
    font-size: 13px;
    line-height: 1.7;
    color: var(--text-primary, rgba(0, 0, 0, 0.88));
    white-space: pre-wrap;
    user-select: text;
  }

  &__loading-state {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 12px;
    padding: 10px 12px;
    border-radius: 6px;
    background: fade(@evals-primary, 8%);
    border: 1px solid fade(@evals-primary, 18%);
    color: var(--text-secondary, rgba(0, 0, 0, 0.65));
    font-size: 12px;
  }

  &__empty {
    margin-top: 12px;
    padding: 12px;
    border-radius: 6px;
    background: var(--bg-tertiary);
    color: var(--text-secondary, rgba(0, 0, 0, 0.45));
    font-size: 12px;
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

.eval-sop-trace {
  margin-top: 10px;

  &__title {
    font-size: 13px;
    font-weight: 600;
    margin-bottom: 8px;
    color: var(--text-primary, rgba(0, 0, 0, 0.88));
  }

  &__layout {
    display: flex;
    gap: 12px;
  }

  &__left,
  &__right {
    flex: 1;
    min-width: 0;
  }

  &__col-header {
    font-size: 12px;
    font-weight: 600;
    color: var(--text-secondary, rgba(0, 0, 0, 0.45));
    padding: 4px 8px;
    border-bottom: 1px solid var(--border-color);
    margin-bottom: 4px;
  }

  &__step-row {
    display: flex;
    align-items: flex-start;
    gap: 6px;
    padding: 6px 8px;
    font-size: 12px;
    border-bottom: 1px dashed var(--border-color);
  }

  &__step-index {
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

  &__step-name {
    font-weight: 500;
    color: var(--text-primary, rgba(0, 0, 0, 0.88));
  }

  &__step-desc {
    color: var(--text-secondary, rgba(0, 0, 0, 0.45));
    font-size: 11px;
    margin-left: 4px;
  }

  &__exec-row {
    padding: 6px 8px;
    font-size: 12px;
    border-bottom: 1px dashed var(--border-color);

    &--success {
      border-left: 2px solid var(--chat-success-color, #52c41a);
    }

    &--error {
      border-left: 2px solid var(--chat-error-color);
    }

    &--pending {
      border-left: 2px solid var(--text-secondary, rgba(0, 0, 0, 0.15));
    }
  }

  &__exec-status {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  &__status-icon {
    font-size: 12px;
    font-weight: 700;

    &--success {
      color: var(--chat-success-color, #52c41a);
    }

    &--error {
      color: var(--chat-error-color);
    }

    &--pending {
      color: var(--text-secondary, rgba(0, 0, 0, 0.25));
    }
  }

  &__tool-name {
    color: @evals-primary;
    font-size: 11px;
  }

  &__duration {
    font-size: 11px;
    line-height: 1;
    padding: 0 4px;
    border-radius: 2px;
    margin-left: auto;
  }

  &__outputs {
    margin-top: 4px;
    padding: 4px 8px;
    background: var(--bg-tertiary);
    border-radius: 4px;
  }

  &__output-item {
    display: flex;
    gap: 4px;
    font-size: 11px;
    padding: 2px 0;
  }

  &__output-key {
    color: var(--text-secondary, rgba(0, 0, 0, 0.45));
    flex-shrink: 0;
  }

  &__output-val {
    color: var(--text-primary, rgba(0, 0, 0, 0.88));
    word-break: break-all;
    max-height: 60px;
    overflow-y: auto;
  }

  &__error {
    margin-top: 4px;
    color: var(--chat-error-color);
    font-size: 11px;
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

.eval-detail-block {
  margin-top: 8px;
}

.eval-answer-summary {
  margin-bottom: 8px;
  padding: 8px 10px;
  border-radius: 6px;
  border: 1px solid fade(@evals-primary, 25%);
  background: fade(@evals-primary, 8%);
  color: var(--text-primary, rgba(0, 0, 0, 0.88));
  font-size: 12px;
  font-weight: 600;
}

.eval-rich-text {
  color: inherit;
  line-height: 1.7;
  word-break: break-word;

  &--compact {
    font-size: 12px;
  }

  &--answer {
    font-size: 12px;
  }

  :deep(p) {
    margin: 0 0 10px;
  }

  :deep(p:last-child) {
    margin-bottom: 0;
  }

  :deep(h1),
  :deep(h2),
  :deep(h3),
  :deep(h4) {
    margin: 12px 0 8px;
    font-size: 13px;
    line-height: 1.5;
    font-weight: 600;
  }

  :deep(ul),
  :deep(ol) {
    margin: 8px 0 8px 18px;
    padding: 0;
  }

  :deep(li) {
    margin: 4px 0;
  }

  :deep(strong) {
    font-weight: 700;
  }

  :deep(code) {
    padding: 1px 4px;
    border-radius: 4px;
    background: var(--bg-tertiary);
    font-family: Consolas, 'Courier New', monospace;
    font-size: 11px;
  }

  :deep(pre) {
    margin: 8px 0;
    padding: 10px;
    border-radius: 6px;
    background: var(--bg-tertiary);
    overflow-x: auto;
  }

  :deep(pre code) {
    padding: 0;
    background: transparent;
  }

  :deep(blockquote) {
    margin: 8px 0;
    padding-left: 10px;
    border-left: 3px solid fade(@evals-primary, 35%);
    color: var(--text-secondary, rgba(0, 0, 0, 0.65));
  }

  :deep(table) {
    width: 100%;
    border-collapse: collapse;
    margin: 8px 0;
    font-size: 12px;
  }

  :deep(th),
  :deep(td) {
    padding: 6px 8px;
    border: 1px solid var(--border-color);
    text-align: left;
    vertical-align: top;
  }

  :deep(th) {
    background: var(--bg-tertiary);
  }

  :deep(.katex-display) {
    margin: 8px 0;
    overflow-x: auto;
    overflow-y: hidden;
  }
}

.eval-flow-steps {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.eval-flow-step-card {
  padding: 8px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: var(--bg-secondary);

  &--success {
    border-color: fade(#52c41a, 35%);
  }

  &--error {
    border-color: fade(@evals-error, 40%);
  }

  &__header {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }

  &__index {
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

  &__name {
    font-weight: 600;
    color: var(--text-primary, rgba(0, 0, 0, 0.88));
  }

  &__tool {
    color: @evals-primary;
    font-size: 11px;
    padding: 0 6px;
    background: fade(@evals-primary, 10%);
    border-radius: 10px;
  }

  &__duration {
    font-size: 11px;
    line-height: 1;
    padding: 0 4px;
    border-radius: 2px;
  }

  &__desc {
    margin-top: 6px;
    color: var(--text-secondary, rgba(0, 0, 0, 0.55));
    font-size: 12px;
    line-height: 1.5;
  }

  &__error {
    margin-top: 6px;
    color: var(--chat-error-color);
    font-size: 12px;
  }

  &__detail {
    margin-top: 8px;
    padding-top: 8px;
    border-top: 1px dashed var(--border-color);
  }
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

  &__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    margin-bottom: 6px;
  }

  &--error {
    color: @evals-error;
    font-size: 12px;
  }
}

.eval-check-summary {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 12px;
  line-height: 1.6;
  padding: 8px 10px;
  border-radius: 6px;

  &--passed {
    background: fade(#52c41a, 8%);
    border: 1px solid fade(#52c41a, 20%);
    color: var(--chat-success-color, #52c41a);
  }

  &--failed {
    background: fade(@evals-error, 8%);
    border: 1px solid fade(@evals-error, 20%);
    color: var(--chat-error-color);
  }
}

.eval-check-icon {
  font-weight: 700;
}

.eval-check-rules {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.eval-check-rule {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 12px;
}

.eval-check-type {
  font-weight: 500;
  min-width: 84px;
  color: var(--text-primary, rgba(0, 0, 0, 0.88));
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
