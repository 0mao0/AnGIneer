<template>
  <div class="eval-run-panel">
    <div class="eval-run-panel__run-btn">
      <a-button
        type="primary"
        :loading="isRunning"
        :disabled="!datasetId || isRunning"
        block
        @click="$emit('run')"
      >
        {{ isRunning ? `运行中 ${progressText}` : '整体评测' }}
      </a-button>
    </div>

    <div class="eval-run-panel__content">
      <div class="eval-run-panel__overall">
        <div v-if="lastRunTime" class="eval-run-panel__overall-time">
          {{ lastRunTime }}
        </div>
        <div class="eval-run-panel__overall-score">
          {{ overallScoreDisplay }}
        </div>
        <div class="eval-run-panel__overall-label">综合得分</div>
      </div>

      <div v-if="summary" class="eval-run-panel__metrics">
        <EvalScoreBar
          v-if="summary.retrieval_score != null"
          label="检索"
          :score="summary.retrieval_score"
        />
        <EvalScoreBar
          v-if="summary.answer_score != null"
          label="回答"
          :score="summary.answer_score"
        />
        <EvalScoreBar
          v-if="summary.sql_score != null"
          label="SQL"
          :score="summary.sql_score"
        />
      </div>

      <div v-if="summary?.by_level" class="eval-run-panel__levels">
        <div class="eval-run-panel__section-title">按意图层级</div>
        <div
          v-for="(data, level) in summary.by_level"
          :key="level"
          class="eval-run-panel__level-row"
        >
          <EvalLevelBadge :level="(level as any)" />
          <span class="eval-run-panel__level-text">
            {{ data.correct }}/{{ data.total }} 正确
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import EvalLevelBadge from './EvalLevelBadge.vue'
import EvalScoreBar from './EvalScoreBar.vue'
import type { EvalRun, EvalSummaryScores } from '../types/eval'

const props = defineProps<{
  datasetId: string
  currentRun: EvalRun | null
  lastRun: EvalRun | null
  /** 当前运行是否为整体评测（非单题评测） */
  isFullRun: boolean
  /** 上次整体测试时间，格式如 "04-09 18:42" */
  lastRunTime?: string
}>()

defineEmits<{
  run: []
}>()

const isRunning = computed(() => props.currentRun?.status === 'running')

const progressText = computed(() => {
  if (!props.currentRun) return ''
  return `${props.currentRun.completed_questions}/${props.currentRun.total_questions}`
})

/** 整体评测时优先取 currentRun，单题评测时只取 lastRun */
const summary = computed((): EvalSummaryScores | null => {
  if (props.isFullRun) {
    return props.currentRun?.summary_scores || props.lastRun?.summary_scores || null
  }
  return props.lastRun?.summary_scores || null
})

const overallScoreDisplay = computed(() => {
  if (!summary.value?.overall_score) return '—'
  return (summary.value.overall_score * 100).toFixed(1) + '%'
})
</script>

<style lang="less" scoped>
.eval-run-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 16px;

  &__run-btn {
    margin-bottom: 16px;
  }

  &__content {
    flex: 1;
    overflow-y: auto;
  }

  &__overall {
    text-align: center;
    padding: 16px 0;
    border-bottom: 1px solid var(--border-color);
    margin-bottom: 16px;

    &-time {
      font-size: 12px;
      color: var(--text-secondary, rgba(0, 0, 0, 0.45));
      margin-bottom: 4px;
    }

    &-score {
      font-size: 36px;
      font-weight: 700;
      color: @evals-primary;
    }

    &-label {
      font-size: 13px;
      color: var(--text-secondary, rgba(0, 0, 0, 0.45));
      margin-top: 4px;
    }
  }

  &__metrics {
    display: flex;
    flex-direction: column;
    gap: 8px;
    margin-bottom: 16px;
  }

  &__section-title {
    font-size: 13px;
    font-weight: 600;
    margin-bottom: 8px;
    color: var(--text-secondary, rgba(0, 0, 0, 0.45));
  }

  &__levels {
    margin-bottom: 16px;
  }

  &__level-row {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 6px;
  }

  &__level-text {
    font-size: 13px;
  }
}
</style>
