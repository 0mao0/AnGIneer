<template>
  <div class="eval-run-panel">
    <div class="eval-run-panel__actions">
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
      <a-button
        v-if="canResume"
        class="eval-run-panel__resume-btn"
        block
        :disabled="loading"
        @click="onResumeClick"
      >
        断点续跑（已测 {{ resumableRun?.completed_questions }}/{{ resumableRun?.total_questions }}）
      </a-button>
    </div>

    <div class="eval-run-panel__body">
      <div v-if="isRunning && currentRun" class="eval-run-panel__progress">
        <a-progress
          :percent="runPercent"
          status="active"
          :stroke-color="{ from: '#108ee9', to: '#52c41a' }"
        />
        <div class="eval-run-panel__progress-meta">
          <span>已完成 {{ currentRun.completed_questions }}/{{ currentRun.total_questions }}</span>
          <span v-if="livePercent !== null" class="eval-run-panel__progress-score">
            实时正确率 {{ livePercent }}%
          </span>
        </div>
      </div>

      <template v-if="summary">
        <div class="eval-run-panel__score-card">
          <div class="eval-run-panel__score-card-main">
            <span class="eval-run-panel__score-card-number">{{ scoreNumber }}</span>
            <span class="eval-run-panel__score-card-percent">%</span>
          </div>
          <div class="eval-run-panel__score-card-meta">
            <a-tag :color="scoreTagColor" class="eval-run-panel__score-card-tag">{{ scoreStatusLabel }}</a-tag>
            <span v-if="summary.total != null" class="eval-run-panel__score-card-count">
              {{ summary.correct ?? 0 }}/{{ summary.total }} 正确
            </span>
            <span v-if="lastRunTime" class="eval-run-panel__score-card-time">{{ lastRunTime }}</span>
          </div>
        </div>

        <div v-if="metrics.length" class="eval-run-panel__metrics">
          <EvalScoreBar
            v-for="m in metrics"
            :key="m.label"
            :label="m.label"
            :score="m.score"
          />
        </div>
      </template>

      <div v-if="historyRuns.length" class="eval-run-panel__history">
        <div class="eval-run-panel__section-title">历史记录</div>
        <a-select
          v-model:value="selectedRunId"
          size="small"
          class="eval-run-panel__history-select"
          :options="historyOptions"
          @change="onHistorySelect"
        />
        <div class="eval-run-panel__history-meta">
          <span class="eval-run-panel__history-name">{{ displayRunName || '—' }}</span>
          <a-tag v-if="selectedRunStatus" :color="selectedRunStatus.color">{{ selectedRunStatus.label }}</a-tag>
          <a-button
            type="link"
            danger
            size="small"
            class="eval-run-panel__history-delete"
            @click="onDeleteClick"
          >
            删除
          </a-button>
        </div>
      </div>

      <div v-if="levelRows.length" class="eval-run-panel__levels">
        <div class="eval-run-panel__section-title">按意图层级</div>
        <div v-for="row in levelRows" :key="row.level" class="eval-run-panel__level-row">
          <EvalLevelBadge :level="row.level" />
          <a-progress
            class="eval-run-panel__level-bar"
            :percent="row.percent"
            :show-info="false"
            size="small"
            :stroke-color="row.strokeColor"
          />
          <span class="eval-run-panel__level-text">{{ row.correct }}/{{ row.total }}</span>
        </div>
      </div>

      <a-empty
        v-if="!summary && !historyRuns.length && !isRunning"
        description="暂无评测记录"
        :image="false"
        class="eval-run-panel__empty"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watchEffect } from 'vue'
import EvalLevelBadge from './EvalLevelBadge.vue'
import EvalScoreBar from './EvalScoreBar.vue'
import type { EvalIntentLevel, EvalRun, EvalSummaryScores } from '../types/eval'

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
  resume: [runId: string]
  stop: []
  'select-run': [runId: string]
  'delete-run': [runId: string]
}>()

const stopping = ref(false)

const isRunning = computed(() => props.currentRun?.status === 'running')

/** 评测时不显示波动的实时分数，只显示已完成运行的得分 */
const summary = computed((): EvalSummaryScores | null => {
  if (props.isFullRun) {
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

/** 运行中的进度百分比 */
const runPercent = computed(() => {
  if (!props.currentRun?.total_questions) return 0
  return Math.round((props.currentRun.completed_questions / props.currentRun.total_questions) * 100)
})

/** 运行中的实时正确率（百分比数字） */
const livePercent = computed(() => {
  const s = props.currentRun?.summary_scores
  if (!s || !s.total || s.correct == null) return null
  return ((s.correct / s.total) * 100).toFixed(1)
})

const statusLabelMap: Record<string, { label: string; color: string }> = {
  running: { label: '评测中', color: 'processing' },
  completed: { label: '已完成', color: 'success' },
  cancelled: { label: '已中断', color: 'warning' },
  failed: { label: '失败', color: 'error' },
}

/** 当前展示分数的运行状态 */
const scoreStatusLabel = computed(() => {
  const run = isRunning.value ? props.currentRun : (props.lastRun || props.currentRun)
  if (!run) return '—'
  return statusLabelMap[run.status]?.label || run.status
})

const scoreTagColor = computed(() => {
  const run = isRunning.value ? props.currentRun : (props.lastRun || props.currentRun)
  if (!run) return 'default'
  return statusLabelMap[run.status]?.color || 'default'
})

/** 可断点续跑的最近一次运行（已中断/失败且完成了一部分） */
const resumableRun = computed(() => {
  if (!props.runs) return null
  const candidates = props.runs.filter(r =>
    (r.status === 'cancelled' || r.status === 'failed') &&
    r.completed_questions > 0 &&
    r.completed_questions < r.total_questions
  )
  if (!candidates.length) return null
  return candidates.sort((a, b) =>
    new Date(b.completed_at || b.started_at).getTime() - new Date(a.completed_at || a.started_at).getTime()
  )[0]
})

const canResume = computed(() => !isRunning.value && !!resumableRun.value && !!props.datasetId)

const onResumeClick = () => {
  if (resumableRun.value) {
    emit('resume', resumableRun.value.run_id)
  }
}

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

const historyOptions = computed(() => {
  return historyRuns.value.map(r => {
    const statusText = statusLabelMap[r.status]?.label
    const suffix = statusText && r.status !== 'completed'
      ? `（${statusText} ${r.completed_questions}/${r.total_questions}）`
      : ''
    return {
      value: r.run_id,
      label: `${r.run_name || r.run_id.slice(0, 12)}${suffix}`,
    }
  })
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

const selectedRunStatus = computed(() => {
  const run = historyRuns.value.find(r => r.run_id === selectedRunId.value)
  if (!run) return null
  return statusLabelMap[run.status] || null
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

/** 检索/回答/SQL 指标行 */
const metrics = computed(() => {
  const s = summary.value
  if (!s) return []
  const rows: Array<{ label: string; score: number }> = []
  if (s.retrieval_score != null) rows.push({ label: '检索', score: s.retrieval_score })
  if (s.answer_score != null) rows.push({ label: '回答', score: s.answer_score })
  if (s.sql_score != null) rows.push({ label: 'SQL', score: s.sql_score })
  return rows
})

/** 意图层级统计行 */
const levelRows = computed(() => {
  const byLevel = summary.value?.by_level
  if (!byLevel) return []
  const order = ['L1', 'L2', 'L3', 'L4']
  return order
    .filter(level => byLevel[level])
    .map(level => {
      const data = byLevel[level]
      const percent = data.total ? Math.round((data.correct / data.total) * 100) : 0
      return {
        level: level as EvalIntentLevel,
        correct: data.correct,
        total: data.total,
        percent,
        strokeColor: percent >= 80 ? '#52c41a' : percent >= 50 ? '#faad14' : '#f5222d',
      }
    })
})
</script>

<style lang="less" scoped>
.eval-run-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 12px;
  gap: 12px;

  &__actions {
    display: flex;
    flex-direction: column;
    gap: 8px;
    flex-shrink: 0;
  }

  &__resume-btn {
    border-style: dashed;
    color: @evals-primary;
  }

  &__body {
    flex: 1;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 16px;
  }

  &__progress {
    padding: 12px;
    border-radius: 8px;
    background: fade(@evals-primary, 6%);
    border: 1px solid fade(@evals-primary, 18%);

    &-meta {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-top: 6px;
      font-size: 12px;
      color: var(--text-secondary);
    }

    &-score {
      color: #52c41a;
      font-weight: 500;
    }
  }

  &__score-card {
    text-align: center;
    padding: 14px 12px;
    border-radius: 8px;
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);

    &-main {
      display: flex;
      align-items: baseline;
      justify-content: center;
    }

    &-number {
      font-size: 38px;
      font-weight: 700;
      color: @evals-primary;
      line-height: 1;
    }

    &-percent {
      font-size: 13px;
      color: @evals-primary;
      margin-left: 2px;
    }

    &-meta {
      display: flex;
      align-items: center;
      justify-content: center;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 8px;
      font-size: 12px;
      color: var(--text-secondary);
    }
  }

  &__metrics {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  &__section-title {
    font-size: 12px;
    font-weight: 600;
    color: var(--text-secondary);
    margin-bottom: 8px;
  }

  &__history {
    &-select {
      width: 100%;
    }

    &-meta {
      display: flex;
      align-items: center;
      gap: 6px;
      margin-top: 6px;
      font-size: 12px;
    }

    &-name {
      flex: 1;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      color: var(--text-primary);
    }

    &-delete {
      flex-shrink: 0;
      padding: 0 4px;
      font-size: 12px;
    }
  }

  &__levels {
    &-row {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 6px;
    }

    &-bar {
      flex: 1;
      min-width: 0;
      margin: 0;
    }

    &-text {
      font-size: 12px;
      color: var(--text-secondary);
      min-width: 40px;
      text-align: right;
    }
  }

  &__empty {
    margin-top: 24px;
  }
}
</style>
