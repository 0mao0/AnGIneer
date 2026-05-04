<template>
  <div
    class="eval-question-card"
    :class="{ 'eval-question-card--expanded': expanded }"
    @click="$emit('toggle', question.question_id)"
  >
    <div class="eval-question-card__header">
      <EvalLevelBadge :level="question.intent_level" />
      <span class="eval-question-card__id">{{ question.question_id }}</span>
      <span class="eval-question-card__text">{{ question.question }}</span>
      <a-tag v-if="statusTag" :color="statusTag.color" class="eval-question-card__status">
        {{ statusTag.label }}
      </a-tag>
      <span class="eval-question-card__arrow">
        <RightOutlined :class="{ 'eval-question-card__arrow--expanded': expanded }" />
      </span>
    </div>
    <div v-if="expanded && detail" class="eval-question-card__body">
      <div class="eval-question-card__comparison">
        <div class="eval-question-card__col">
          <div class="eval-question-card__col-title">系统回答</div>
          <div class="eval-question-card__col-content">
            {{ detail.prediction?.answer || '—' }}
          </div>
        </div>
        <div class="eval-question-card__col">
          <div class="eval-question-card__col-title">标准答案</div>
          <div class="eval-question-card__col-content">
            {{ question.answer_gold?.gold_answer || '—' }}
          </div>
        </div>
      </div>
      <div v-if="detail.scores" class="eval-question-card__scores">
        <span v-if="detail.scores.hit@5 !== undefined" class="eval-question-card__score-item">
          检索 Hit@5: {{ (detail.scores.hit@5 as number * 100).toFixed(1) }}%
        </span>
        <span v-if="detail.scores.correctness_score !== undefined" class="eval-question-card__score-item">
          正确性: {{ ((detail.scores.correctness_score as number) * 100).toFixed(1) }}%
        </span>
        <span v-if="detail.scores.execution_success !== undefined" class="eval-question-card__score-item">
          SQL 执行: {{ detail.scores.execution_success ? '成功' : '失败' }}
        </span>
      </div>
      <div v-if="detail.error" class="eval-question-card__error">
        错误: {{ detail.error }}
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { RightOutlined } from '@ant-design/icons-vue'
import EvalLevelBadge from './EvalLevelBadge.vue'
import type { EvalQuestion, EvalRunDetail, EvalQuestionStatus } from '../types/eval'

const props = defineProps<{
  question: EvalQuestion
  detail: EvalRunDetail | null
  expanded: boolean
}>()

defineEmits<{
  toggle: [questionId: string]
}>()

const statusTagMap: Record<string, { color: string; label: string }> = {
  passed: { color: 'success', label: '通过' },
  failed: { color: 'error', label: '未通过' },
  running: { color: 'processing', label: '运行中' },
  error: { color: 'warning', label: '错误' },
  pending: { color: 'default', label: '待运行' },
}

const statusTag = computed(() => {
  const status: EvalQuestionStatus = props.detail?.status || 'pending'
  return statusTagMap[status] || null
})
</script>

<style lang="less" scoped>
.eval-question-card {
  border: 1px solid var(--dp-border-color, rgba(255, 255, 255, 0.06));
  border-radius: 6px;
  margin-bottom: 8px;
  cursor: pointer;
  transition: all 0.2s;
  background: var(--dp-pane-bg, #1e1e1e);

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
    color: var(--dp-text-secondary, rgba(255, 255, 255, 0.45));
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

  &__arrow {
    flex-shrink: 0;
    transition: transform 0.2s;

    &--expanded {
      transform: rotate(90deg);
    }
  }

  &__body {
    padding: 0 12px 12px;
    border-top: 1px solid var(--dp-border-color, rgba(255, 255, 255, 0.06));
  }

  &__comparison {
    display: flex;
    gap: 12px;
    margin-top: 10px;
  }

  &__col {
    flex: 1;

    &-title {
      font-size: 12px;
      font-weight: 600;
      margin-bottom: 4px;
      color: var(--dp-text-secondary, rgba(255, 255, 255, 0.45));
    }

    &-content {
      font-size: 13px;
      line-height: 1.6;
      padding: 8px;
      background: rgba(0, 0, 0, 0.2);
      border-radius: 4px;
      max-height: 200px;
      overflow-y: auto;
    }
  }

  &__scores {
    display: flex;
    gap: 16px;
    margin-top: 8px;
    font-size: 12px;
    color: var(--dp-text-secondary, rgba(255, 255, 255, 0.45));
  }

  &__error {
    margin-top: 8px;
    font-size: 12px;
    color: @evals-error;
  }
}
</style>
