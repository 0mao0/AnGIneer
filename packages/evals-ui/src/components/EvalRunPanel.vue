<template>
  <div class="eval-run-panel">
    <div class="eval-run-panel__run-btn">
      <a-button
        type="primary"
        :danger="isRunning"
        :loading="loading && !isRunning"
        :disabled="!datasetId || (loading && !isRunning)"
        block
        @click="handleClick"
      >
        <template v-if="isRunning">
          {{ stopping ? '正在停止...' : '停止评测' }}
        </template>
        <template v-else>
          整体评测
        </template>
      </a-button>
    </div>

    <div class="eval-run-panel__content">
      <div class="eval-run-panel__overall">
        <div v-if="lastRunTime" class="eval-run-panel__overall-time">
          {{ lastRunTime }}
        </div>
        <div class="eval-run-panel__overall-score" :class="{ 'eval-run-panel__overall-score--running': isRunning }">
          <span class="eval-run-panel__overall-number">{{ scoreNumber }}</span><span class="eval-run-panel__overall-percent">%</span>
        </div>
        <div v-if="isRunning && runProgress" class="eval-run-panel__in-progress">
          测评中 ({{ runProgress }})
        </div>
        <div v-if="historyRuns.length > 0" class="eval-run-panel__overall-run">
          <a-select
            v-model:value="selectedRunId"
            size="small"
            :options="historyRuns.map(r => ({
              value: r.run_id,
              label: r.run_name || r.run_id.slice(0, 12),
            }))"
            @change="onHistorySelect"
          />
          <a-button
            v-if="selectedRunId"
            type="link"
            danger
            size="small"
            @click="onDeleteClick"
          >
            删除此记录
          </a-button>
        </div>
        <div v-else-if="displayRunName" class="eval-run-panel__overall-run">
          {{ displayRunName }}
        </div>
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
import { ref, computed, watchEffect } from 'vue'
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
  /** 是否正在加载（如启动中） */
  loading?: boolean
  /** 历史整体运行列表（用于下拉选择） */
  runs?: EvalRun[]
}>()

const emit = defineEmits<{
  run: []
  stop: []
  'select-run': [runId: string]
  'delete-run': [runId: string]
}>()

const stopping = ref(false)

const isRunning = computed(() => props.currentRun?.status === 'running')

/** 评测时不显示波动的实时分数，只显示已完成运行的得分 */
const summary = computed((): EvalSummaryScores | null => {
  if (props.isFullRun) {
    if (props.currentRun?.status === 'running') {
      return props.lastRun?.summary_scores || null
    }
    return props.currentRun?.summary_scores || props.lastRun?.summary_scores || null
  }
  return props.lastRun?.summary_scores || null
})

/** 得分数字部分：正确数/总数 的百分比，而非 overall_score */
const scoreNumber = computed(() => {
  const s = summary.value
  if (!s) return '—'
  if (s.total != null && s.total > 0 && s.correct != null) {
    return ((s.correct / s.total) * 100).toFixed(1)
  }
  if (s.overall_score != null) {
    return (s.overall_score * 100).toFixed(1)
  }
  return '—'
})

/** 运行中的进度文字，如 "6/10" */
const runProgress = computed(() => {
  if (!props.currentRun || props.currentRun.status !== 'running') return null
  return `${props.currentRun.completed_questions}/${props.currentRun.total_questions}`
})

/** 处理按钮点击：根据运行状态触发启动或停止 */
const handleClick = () => {
  if (stopping.value) return
  if (isRunning.value) {
    stopping.value = true
    emit('stop')
    setTimeout(() => { stopping.value = false }, 1000)
  } else {
    emit('run')
  }
}

const selectedRunId = ref<string | undefined>(undefined)

/** 用于下拉的历史运行列表（过滤掉单题评测） */
const historyRuns = computed(() => {
  if (!props.runs) return []
  return props.runs.filter(r => r.is_full_run !== false)
})

/** 当前得分对应的运行名称（不含评测中状态，进度已在下方单独显示） */
const displayRunName = computed(() => {
  const run = historyRuns.value.find(r => r.run_id === selectedRunId.value)
  if (run) {
    return run.run_name || run.run_id.slice(0, 12)
  }
  if (props.lastRun) {
    return props.lastRun.run_name || props.lastRun.run_id.slice(0, 12)
  }
  return null
})

/** 默认选中最近一次运行，并在 runs 变化时保持同步 */
watchEffect(() => {
  const list = historyRuns.value
  if (list.length > 0) {
    if (!selectedRunId.value || !list.find(r => r.run_id === selectedRunId.value)) {
      selectedRunId.value = list[0].run_id
      emit('select-run', list[0].run_id)
    }
  }
})

const onHistorySelect = (runId: string | undefined) => {
  if (runId) {
    emit('select-run', runId)
  }
}

const onDeleteClick = () => {
  if (selectedRunId.value) {
    emit('delete-run', selectedRunId.value)
  }
}
</script>

<style lang="less" scoped>
.eval-run-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 16px;

  &__run-btn {
    margin-bottom: 8px;
  }

  &__compare-btn {
    margin-top: 6px;
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
      color: var(--text-secondary);
      margin-bottom: 4px;
    }

    &-score {
      font-weight: 700;
      color: @evals-primary;

      &--running {
        color: #52c41a;
      }
    }

    &-number {
      font-size: 36px;
    }

    &-percent {
      font-size: 12px;
    }

    &-label {
      font-size: 13px;
      color: var(--text-secondary);
      margin-top: 4px;
    }

    &-in-progress {
      font-size: 12px;
      color: #52c41a;
      margin-top: 4px;
      font-weight: 400;
    }

    &-run {
      font-size: 11px;
      color: var(--text-secondary);
      margin-top: 2px;

      :deep(.ant-select) {
        width: 100%;
      }
    }
  }

  &__progress {
    font-size: 12px;
    color: var(--primary-color);
    margin-top: 6px;
    font-weight: 500;
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
    color: var(--text-secondary);
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
