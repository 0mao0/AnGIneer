<template>
  <div class="eval-run-panel">
    <div class="eval-run-panel__actions">
      <a-button
        v-if="isRunning"
        type="primary"
        danger
        :loading="stopping"
        :disabled="stopping"
        block
        @click="handleClick"
      >
        {{ stopping ? '正在停止...' : '停止评测' }}
      </a-button>
      <div v-else-if="canResume" class="eval-run-panel__action-row">
        <a-button
          type="primary"
          :loading="loading"
          :disabled="!datasetId || loading"
          @click="handleClick"
        >
          整体评测
        </a-button>
        <a-button
          class="eval-run-panel__resume-btn"
          :loading="loading"
          :disabled="!datasetId || loading"
          @click="onResumeClick"
        >
          <template #icon><PlayCircleOutlined /></template>
          继续评测
        </a-button>
      </div>
      <a-button
        v-else
        type="primary"
        :loading="loading"
        :disabled="!datasetId || loading"
        block
        @click="handleClick"
      >
        整体评测
      </a-button>
    </div>

    <div class="eval-run-panel__body">
      <!-- A：运行进度（不含实时准确率） -->
      <div v-if="isRunning && currentRun" class="eval-run-panel__progress">
        <a-progress
          :percent="runPercent"
          status="active"
          :stroke-color="{ from: '#108ee9', to: '#52c41a' }"
        />
        <div class="eval-run-panel__progress-meta">
          已完成 {{ currentRun.completed_questions }}/{{ currentRun.total_questions }}
        </div>
      </div>

      <!-- B：准确率（运行中显示实时值） -->
      <div v-if="summary" class="eval-run-panel__accuracy">
        <div class="eval-run-panel__accuracy-head">
          <span class="eval-run-panel__accuracy-label">
            {{ isRunning ? '实时正确率' : '整体正确率' }}
          </span>
          <a-tag v-if="scoreStatusLabel" :color="scoreTagColor" class="eval-run-panel__accuracy-tag">
            {{ scoreStatusLabel }}
          </a-tag>
        </div>
        <a-progress
          type="dashboard"
          :percent="accuracyPercent"
          :stroke-color="accuracyColor"
          :width="116"
          :format="() => `${scoreNumber}%`"
          class="eval-run-panel__accuracy-ring"
        />
        <div class="eval-run-panel__accuracy-meta">
          <span class="eval-run-panel__accuracy-item eval-run-panel__accuracy-item--ok">
            正确 {{ summary.correct ?? 0 }}
          </span>
          <span class="eval-run-panel__accuracy-item eval-run-panel__accuracy-item--bad">
            错误 {{ summary.wrong ?? 0 }}
          </span>
          <span class="eval-run-panel__accuracy-item">
            跳过 {{ summary.skipped ?? 0 }}
          </span>
        </div>
        <div v-if="lastRunTime" class="eval-run-panel__accuracy-time">{{ lastRunTime }}</div>
      </div>

      <!-- C：历史记录（列表 + 勾选对比） -->
      <div v-if="historyRuns.length" class="eval-run-panel__history">
        <div class="eval-run-panel__section-head">
          <span class="eval-run-panel__section-title">历史记录</span>
          <span v-if="compareIds.length >= 2" class="eval-run-panel__compare-badge">
            对比 {{ compareIds.length }}/3
          </span>
        </div>
        <div class="eval-run-panel__history-list">
          <div
            v-for="run in historyRuns"
            :key="run.run_id"
            class="eval-run-panel__history-row"
            :class="{
              'eval-run-panel__history-row--active': run.run_id === selectedRunId,
              'eval-run-panel__history-row--compared': compareIds.includes(run.run_id),
            }"
            @click="onSelectRun(run.run_id)"
          >
            <a-checkbox
              :checked="compareIds.includes(run.run_id)"
              :disabled="!compareIds.includes(run.run_id) && compareIds.length >= 3"
              class="eval-run-panel__history-check"
              @click.stop
              @change="onToggleCompare(run.run_id, $event.target.checked)"
            />
            <span class="eval-run-panel__history-dot" :class="`eval-run-panel__history-dot--${run.status}`" />
            <div class="eval-run-panel__history-main">
              <div class="eval-run-panel__history-name">
                {{ run.run_name || run.run_id.slice(0, 12) }}
              </div>
              <div class="eval-run-panel__history-sub">
                {{ runStatusLabel(run.status) }} · {{ run.completed_questions }}/{{ run.total_questions }}
                <template v-if="run.completed_at || run.started_at">
                  · {{ formatTime(run.completed_at || run.started_at) }}
                </template>
              </div>
            </div>
            <span class="eval-run-panel__history-score">{{ formatScore(run.summary_scores) }}</span>
            <a-button
              type="text"
              size="small"
              danger
              class="eval-run-panel__history-delete"
              @click.stop="onDeleteClick(run.run_id)"
            >
              删除
            </a-button>
          </div>
        </div>
      </div>

      <!-- D：题目明细 / 逐题对比 -->
      <div v-if="historyRuns.length" class="eval-run-panel__detail">
        <div class="eval-run-panel__section-head">
          <span class="eval-run-panel__section-title">
            {{ isCompareMode ? '逐题对比' : '题目明细' }}
          </span>
          <div v-if="isCompareMode" class="eval-run-panel__diff-toggle">
            仅看差异
            <a-switch v-model:checked="showDiffOnly" size="small" />
          </div>
        </div>

        <template v-if="isCompareMode">
          <div class="eval-run-panel__compare-wrap">
            <table class="eval-run-panel__compare-table">
              <thead>
                <tr>
                  <th class="eval-run-panel__compare-seq">#</th>
                  <th>题目</th>
                  <th v-for="run in compareRuns" :key="run.run_id" class="eval-run-panel__compare-run">
                    {{ shortName(run) }}
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="row in compareRows"
                  :key="row.seq"
                  :class="{ 'eval-run-panel__compare-row--diff': row.hasDiff }"
                >
                  <td class="eval-run-panel__compare-seq">{{ row.seq }}</td>
                  <td class="eval-run-panel__compare-question" :title="row.question">
                    {{ row.question || '—' }}
                  </td>
                  <td
                    v-for="cell in row.cells"
                    :key="cell.runId"
                    class="eval-run-panel__compare-cell"
                    :class="cell.className"
                  >
                    {{ cell.mark }}
                  </td>
                </tr>
                <tr v-if="!compareRows.length">
                  <td :colspan="compareRuns.length + 2" class="eval-run-panel__compare-empty">
                    {{ showDiffOnly ? '所选记录逐题结果一致，无差异' : '所选记录暂无题目结果' }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="eval-run-panel__compare-legend">
            <span><i class="eval-run-panel__legend-dot eval-run-panel__legend-dot--ok" />正确</span>
            <span><i class="eval-run-panel__legend-dot eval-run-panel__legend-dot--bad" />错误</span>
            <span><i class="eval-run-panel__legend-dot eval-run-panel__legend-dot--na" />未测</span>
            <span class="eval-run-panel__compare-total">差异 {{ diffCount }} 题</span>
          </div>
        </template>

        <template v-else>
          <div v-if="questionRows.length" class="eval-run-panel__chips">
            <div
              v-for="row in questionRows"
              :key="row.seq"
              class="eval-run-panel__chip"
              :class="`eval-run-panel__chip--${row.kind}`"
              :title="`${row.seq}. ${row.question || ''}`"
            >
              {{ row.seq }}
            </div>
          </div>
          <div v-else class="eval-run-panel__detail-empty">该记录暂无题目结果</div>
          <div class="eval-run-panel__chips-legend">
            <span><i class="eval-run-panel__legend-dot eval-run-panel__legend-dot--ok" />正确</span>
            <span><i class="eval-run-panel__legend-dot eval-run-panel__legend-dot--bad" />错误</span>
            <span><i class="eval-run-panel__legend-dot eval-run-panel__legend-dot--na" />未测</span>
            <span v-if="questionRows.length" class="eval-run-panel__chips-count">
              共 {{ questionRows.length }} 题
            </span>
          </div>
        </template>
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
import { ref, computed, watchEffect, watch } from 'vue'
import { PlayCircleOutlined } from '@ant-design/icons-vue'
import type { EvalRun, EvalRunDetail, EvalSummaryScores } from '../types/eval'

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
  /** 按需加载某次 run 的轻量题目详情 */
  loadRunDetails?: (runId: string) => Promise<EvalRunDetail[]>
}>()

const emit = defineEmits<{
  run: []
  resume: [runId: string]
  stop: []
  'select-run': [runId: string]
  'delete-run': [runId: string]
}>()

const stopping = ref(false)
const selectedRunId = ref<string | undefined>(undefined)
const compareIds = ref<string[]>([])
const detailsByRun = ref<Record<string, EvalRunDetail[]>>({})
const showDiffOnly = ref(true)

const isRunning = computed(() => {
  if (props.currentRun?.status === 'running') return true
  // 兜底：即使 currentRun 未同步，只要运行列表里存在 running 记录也按评测中处理
  return !!props.runs?.some(r => r.status === 'running')
})

/** 当前展示的汇总得分 */
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

const accuracyPercent = computed(() => {
  const n = parseFloat(scoreNumber.value)
  return Number.isFinite(n) ? n : 0
})

const accuracyColor = computed(() => {
  if (isRunning.value) return '#1677ff'
  const n = accuracyPercent.value
  if (n >= 80) return '#52c41a'
  if (n >= 50) return '#faad14'
  return '#f5222d'
})

/** 运行中的进度百分比 */
const runPercent = computed(() => {
  if (!props.currentRun?.total_questions) return 0
  return Math.round((props.currentRun.completed_questions / props.currentRun.total_questions) * 100)
})

const statusLabelMap: Record<string, { label: string; color: string }> = {
  running: { label: '评测中', color: 'processing' },
  completed: { label: '已完成', color: 'success' },
  cancelled: { label: '已中断', color: 'warning' },
  failed: { label: '失败', color: 'error' },
}

const runStatusLabel = (status: string) => statusLabelMap[status]?.label || status

/** 当前展示分数的运行状态 */
const scoreStatusLabel = computed(() => {
  const run = isRunning.value ? props.currentRun : (props.lastRun || props.currentRun)
  if (!run) return null
  return statusLabelMap[run.status]?.label || run.status
})

const scoreTagColor = computed(() => {
  const run = isRunning.value ? props.currentRun : (props.lastRun || props.currentRun)
  if (!run) return 'default'
  return statusLabelMap[run.status]?.color || 'default'
})

/** 可断点续跑的最近一次运行：仅当最新一条整体运行是中断/失败且未跑完 */
const resumableRun = computed(() => {
  if (!props.runs) return null
  const fullRuns = props.runs.filter(r => r.is_full_run !== false)
  if (!fullRuns.length) return null
  const latest = fullRuns[0]
  const resumable =
    (latest.status === 'cancelled' || latest.status === 'failed') &&
    latest.completed_questions > 0 &&
    latest.completed_questions < latest.total_questions
  return resumable ? latest : null
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

/** 历史整体运行列表（过滤掉单题评测） */
const historyRuns = computed(() => {
  if (!props.runs) return []
  return props.runs.filter(r => r.is_full_run !== false)
})

const formatScore = (s?: EvalSummaryScores | null): string => {
  if (!s) return '—'
  if (s.total && s.correct != null) {
    return ((s.correct / s.total) * 100).toFixed(1) + '%'
  }
  if (s.overall_score != null) {
    return (s.overall_score * 100).toFixed(1) + '%'
  }
  return '—'
}

const formatTime = (iso: string): string => {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const mi = String(d.getMinutes()).padStart(2, '0')
  return `${mm}-${dd} ${hh}:${mi}`
}

/** 按需加载并缓存某次 run 的题目详情 */
const ensureDetails = async (runId: string) => {
  if (!props.loadRunDetails) return
  const run = historyRuns.value.find(r => r.run_id === runId)
  const isRunningRun = run?.status === 'running'
  if (!isRunningRun && detailsByRun.value[runId]) return
  const details = await props.loadRunDetails(runId)
  detailsByRun.value = { ...detailsByRun.value, [runId]: details }
}

/** 默认选中最近一次运行 */
watchEffect(() => {
  const list = historyRuns.value
  if (list.length) {
    if (!selectedRunId.value || !list.find(r => r.run_id === selectedRunId.value)) {
      selectedRunId.value = list[0].run_id
      emit('select-run', list[0].run_id)
      void ensureDetails(list[0].run_id)
    }
  } else {
    selectedRunId.value = undefined
  }
})

const onSelectRun = (runId: string) => {
  if (selectedRunId.value === runId) return
  selectedRunId.value = runId
  emit('select-run', runId)
  void ensureDetails(runId)
}

/** 勾选/取消勾选用于对比的记录，最多 3 组 */
const onToggleCompare = (runId: string, checked: boolean) => {
  if (checked) {
    if (compareIds.value.includes(runId) || compareIds.value.length >= 3) return
    compareIds.value = [...compareIds.value, runId]
  } else {
    compareIds.value = compareIds.value.filter(id => id !== runId)
  }
  void ensureDetails(runId)
}

/** 运行中的 run 进度变化时刷新详情 */
watch(
  () => props.currentRun?.completed_questions,
  () => {
    if (props.currentRun && selectedRunId.value === props.currentRun.run_id) {
      void ensureDetails(props.currentRun.run_id)
    }
  }
)

const onDeleteClick = (runId: string) => {
  emit('delete-run', runId)
  if (selectedRunId.value === runId) {
    selectedRunId.value = undefined
  }
  compareIds.value = compareIds.value.filter(id => id !== runId)
}

/** 单选模式：主记录逐题结果 */
const primaryDetails = computed(() => {
  if (!selectedRunId.value) return []
  return detailsByRun.value[selectedRunId.value] || []
})

const questionRows = computed(() => {
  return primaryDetails.value.map((d, idx) => {
    let kind = 'na'
    if (d.status === 'completed') {
      if (d.quality === 'correct') kind = 'ok'
      else if (d.quality === 'wrong') kind = 'bad'
    } else if (d.status === 'error') {
      kind = 'bad'
    } else if (d.status === 'running') {
      kind = 'running'
    }
    return {
      seq: idx + 1,
      kind,
      question: String(d.question || ''),
    }
  })
})

const isCompareMode = computed(() => compareIds.value.length >= 2)

const compareRuns = computed(() => {
  return compareIds.value
    .map(id => historyRuns.value.find(r => r.run_id === id))
    .filter((r): r is EvalRun => !!r)
})

const shortName = (run: EvalRun) => {
  return run.run_name || run.run_id.slice(0, 8)
}

/** 对比模式：逐题结果矩阵 */
const allCompareRows = computed(() => {
  const runs = compareRuns.value
  if (runs.length < 2) return []
  const runDetails = runs.map(run => detailsByRun.value[run.run_id] || [])
  const maxLen = Math.max(...runDetails.map(d => d.length))
  const rows: Array<{
    seq: number
    question: string
    hasDiff: boolean
    cells: Array<{ runId: string; mark: string; className: string; quality: string | null }>
  }> = []
  for (let i = 0; i < maxLen; i++) {
    const cells = runs.map((run, idx) => {
      const d = runDetails[idx]?.[i]
      let mark = '—'
      let className = 'eval-run-panel__compare-cell--na'
      let quality: string | null = null
      if (d?.status === 'completed') {
        if (d.quality === 'correct') {
          mark = '✓'
          quality = 'correct'
          className = 'eval-run-panel__compare-cell--ok'
        } else if (d.quality === 'wrong') {
          mark = '✗'
          quality = 'wrong'
          className = 'eval-run-panel__compare-cell--bad'
        }
      } else if (d?.status === 'error') {
        mark = '!'
        quality = 'error'
        className = 'eval-run-panel__compare-cell--bad'
      }
      return { runId: run.run_id, mark, className, quality }
    })
    const marks = cells.map(c => c.quality).filter(q => q !== null)
    const hasDiff = new Set(marks).size > 1
    rows.push({
      seq: i + 1,
      question: String(runDetails.find(d => d[i])?.[i]?.question || ''),
      hasDiff,
      cells,
    })
  }
  return rows
})

const diffCount = computed(() => allCompareRows.value.filter(r => r.hasDiff).length)

const compareRows = computed(() => {
  return showDiffOnly.value
    ? allCompareRows.value.filter(r => r.hasDiff)
    : allCompareRows.value
})
</script>

<style lang="less" scoped>
.eval-run-panel {
  display: flex;
  flex-direction: column;
  min-height: 100%;
  padding: 12px;
  gap: 12px;

  &__actions {
    display: flex;
    flex-direction: column;
    gap: 8px;
    flex-shrink: 0;
  }

  &__action-row {
    display: flex;
    gap: 8px;

    > :deep(.ant-btn) {
      flex: 1;
      min-width: 0;
    }
  }

  &__resume-btn {
    border-style: dashed;
    color: @evals-primary;
  }

  &__body {
    flex: 1;
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
      margin-top: 6px;
      font-size: 12px;
      color: var(--text-secondary);
      text-align: right;
    }
  }

  &__accuracy {
    padding: 14px 12px;
    border-radius: 8px;
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    text-align: center;

    &-head {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      margin-bottom: 4px;
    }

    &-label {
      font-size: 13px;
      font-weight: 600;
      color: var(--text-primary);
    }

    &-tag {
      font-size: 11px;
      line-height: 1.4;
    }

    &-ring {
      margin: 2px auto;
    }

    &-meta {
      display: flex;
      align-items: center;
      justify-content: center;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 6px;
      font-size: 12px;
      color: var(--text-secondary);
    }

    &-item--ok {
      color: #52c41a;
    }

    &-item--bad {
      color: #f5222d;
    }

    &-time {
      margin-top: 4px;
      font-size: 11px;
      color: var(--text-secondary);
    }
  }

  &__section-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    margin-bottom: 8px;
  }

  &__section-title {
    font-size: 12px;
    font-weight: 600;
    color: var(--text-secondary);
  }

  &__compare-badge {
    font-size: 11px;
    color: @evals-primary;
    background: fade(@evals-primary, 10%);
    border-radius: 10px;
    padding: 1px 8px;
  }

  &__diff-toggle {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    color: var(--text-secondary);
  }

  &__history {
    &-list {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }

    &-row {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 8px 10px;
      border-radius: 8px;
      background: var(--bg-secondary);
      border: 1px solid var(--border-color);
      cursor: pointer;
      transition: border-color 0.2s ease, background-color 0.2s ease;

      &:hover {
        border-color: @evals-primary;
      }

      &--active {
        border-color: @evals-primary;
        background: fade(@evals-primary, 6%);
      }

      &--compared {
        background: fade(@evals-primary, 4%);
      }
    }

    &-check {
      flex-shrink: 0;
    }

    &-dot {
      flex-shrink: 0;
      width: 8px;
      height: 8px;
      border-radius: 50%;

      &--running {
        background: #1677ff;
        animation: eval-run-panel-pulse 1.2s ease-in-out infinite;
      }

      &--completed {
        background: #52c41a;
      }

      &--cancelled {
        background: #faad14;
      }

      &--failed {
        background: #f5222d;
      }
    }

    &-main {
      flex: 1;
      min-width: 0;
    }

    &-name {
      font-size: 12px;
      color: var(--text-primary);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    &-sub {
      font-size: 11px;
      color: var(--text-secondary);
      margin-top: 2px;
    }

    &-score {
      flex-shrink: 0;
      font-size: 13px;
      font-weight: 600;
      color: @evals-primary;
    }

    &-delete {
      flex-shrink: 0;
      padding: 0 4px;
      font-size: 11px;
    }
  }

  &__detail {
    &-empty {
      padding: 16px;
      text-align: center;
      color: var(--text-secondary);
      font-size: 12px;
      background: var(--bg-secondary);
      border-radius: 8px;
      border: 1px dashed var(--border-color);
    }
  }

  &__chips {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(28px, 1fr));
    gap: 4px;
  }

  &__chip {
    height: 28px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 500;
    border: 1px solid transparent;
    cursor: default;

    &--ok {
      background: fade(#52c41a, 10%);
      color: #389e0d;
      border-color: fade(#52c41a, 35%);
    }

    &--bad {
      background: fade(#f5222d, 8%);
      color: #f5222d;
      border-color: fade(#f5222d, 30%);
    }

    &--na {
      background: var(--bg-tertiary);
      color: var(--text-secondary);
      border-color: var(--border-color);
    }

    &--running {
      background: fade(#1677ff, 8%);
      color: #1677ff;
      border-color: fade(#1677ff, 30%);
      animation: eval-run-panel-pulse 1.2s ease-in-out infinite;
    }
  }

  &__chips-legend,
  &__compare-legend {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 12px;
    margin-top: 8px;
    font-size: 11px;
    color: var(--text-secondary);
  }

  &__legend-dot {
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 2px;
    margin-right: 4px;

    &--ok {
      background: #52c41a;
    }

    &--bad {
      background: #f5222d;
    }

    &--na {
      background: var(--bg-tertiary);
      border: 1px solid var(--border-color);
    }
  }

  &__chips-count,
  &__compare-total {
    margin-left: auto;
    color: var(--text-secondary);
  }

  &__compare-wrap {
    border: 1px solid var(--border-color);
    border-radius: 6px;
  }

  &__compare-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 11px;

    th,
    td {
      padding: 4px 8px;
      border-bottom: 1px solid var(--border-color);
      text-align: left;
    }

    th {
      background: var(--bg-tertiary);
      position: sticky;
      top: 0;
      z-index: 1;
      font-weight: 600;
    }

    &-seq {
      width: 36px;
      text-align: center;
      color: var(--text-secondary);
    }

    &-question {
      max-width: 200px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    &-run {
      text-align: center;
      min-width: 60px;
    }

    &-cell {
      text-align: center;
      font-weight: 600;

      &--ok {
        color: #52c41a;
      }

      &--bad {
        color: #f5222d;
      }

      &--na {
        color: var(--text-secondary);
        font-weight: 400;
      }
    }

    &-row--diff td {
      background: fade(#faad14, 8%);
    }
  }

  &__compare-empty {
    text-align: center;
    color: var(--text-secondary);
    padding: 16px;
  }

  &__empty {
    margin-top: 24px;
  }
}

@keyframes eval-run-panel-pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.45;
  }
}
</style>
