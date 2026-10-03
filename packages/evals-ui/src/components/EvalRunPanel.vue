<template>
  <div class="eval-run-panel">
    <!-- A：新增评测（唯一发起入口，模型/题集在弹框里选） -->
    <a-button type="primary" block class="eval-run-panel__create" @click="emit('create-run')">
      <template #icon><PlusOutlined /></template>
      新增评测
    </a-button>

    <!-- B：进行中的评测 item（运行中 + 最近一次中断未完成；未完成的进历史记录，置顶展示） -->
    <div
      v-for="run in activeRuns"
      :key="run.run_id"
      class="eval-run-panel__item eval-run-panel__item--active"
      :class="{ 'eval-run-panel__item--selected': run.run_id === selectedRunId }"
      @click="onSelectRun(run.run_id)"
    >
      <div class="eval-run-panel__item-main">
        <div class="eval-run-panel__item-line1">
          <span class="eval-run-panel__item-model">{{ runModel(run) }}</span>
          <span class="eval-run-panel__item-status" :class="`eval-run-panel__item-status--${run.status}`">
            {{ statusLabel(run) }} {{ run.completed_questions }}/{{ run.total_questions }}
          </span>
        </div>
        <div class="eval-run-panel__item-line2">
          {{ formatTime(run.started_at) }} · 正确 {{ correctCount(run) }} 题
        </div>
      </div>
      <div class="eval-run-panel__item-side" @click.stop>
        <span class="eval-run-panel__item-score">{{ runScoreText(run) }}</span>
        <div class="eval-run-panel__item-actions">
          <a-tooltip title="重来：清空进度原地重跑全部题目">
            <a-button type="text" class="eval-run-panel__item-icon-btn" @click="emit('rerun', run)">
              <template #icon><RedoOutlined /></template>
            </a-button>
          </a-tooltip>
          <a-tooltip v-if="run.status === 'running'" title="暂停：完成当前题目后中断，保留已完成结果">
            <a-button type="text" class="eval-run-panel__item-icon-btn" @click="emit('stop')">
              <template #icon><PauseCircleOutlined /></template>
            </a-button>
          </a-tooltip>
          <a-tooltip v-else title="继续：断点续跑，只跑剩余题目">
            <a-button type="text" class="eval-run-panel__item-icon-btn" @click="emit('resume', run)">
              <template #icon><PlayCircleOutlined /></template>
            </a-button>
          </a-tooltip>
          <a-tooltip title="删除">
            <a-button type="text" danger class="eval-run-panel__item-icon-btn" @click="emit('delete-run', run.run_id)">
              <template #icon><DeleteOutlined /></template>
            </a-button>
          </a-tooltip>
        </div>
      </div>
    </div>

    <!-- C：运行中 item 的实时统计 -->
    <div v-if="runningRun" class="eval-run-panel__accuracy">
      <div class="eval-run-panel__accuracy-head">
        <span class="eval-run-panel__accuracy-label">实时正确率</span>
        <span class="eval-run-panel__accuracy-progress">
          {{ runningRun.completed_questions }}/{{ runningRun.total_questions }} 题
        </span>
      </div>
      <div class="eval-run-panel__accuracy-body">
        <div class="eval-run-panel__accuracy-left">
          <a-progress
            type="dashboard"
            :percent="accuracyPercent"
            stroke-color="#1677ff"
            :width="104"
            :format="() => `${scoreNumber}%`"
          />
        </div>
        <div class="eval-run-panel__accuracy-right">
          <div class="eval-run-panel__stat">
            <span class="eval-run-panel__stat-label">正确</span>
            <span class="eval-run-panel__stat-value eval-run-panel__stat-value--ok">{{ liveSummary.correct }}</span>
          </div>
          <div class="eval-run-panel__stat">
            <span class="eval-run-panel__stat-label">错误</span>
            <span class="eval-run-panel__stat-value eval-run-panel__stat-value--bad">{{ liveSummary.wrong }}</span>
          </div>
          <div class="eval-run-panel__stat">
            <span class="eval-run-panel__stat-label">异常</span>
            <span class="eval-run-panel__stat-value">{{ liveSummary.errored }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- D：历史记录（仅已完成的评测） -->
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
          class="eval-run-panel__item"
          :class="{
            'eval-run-panel__item--selected': run.run_id === selectedRunId,
            'eval-run-panel__item--compared': compareIds.includes(run.run_id),
          }"
          @click="onSelectRun(run.run_id)"
        >
          <a-checkbox
            :checked="compareIds.includes(run.run_id)"
            :disabled="!compareIds.includes(run.run_id) && compareIds.length >= 3"
            class="eval-run-panel__item-check"
            @click.stop
            @change="onToggleCompare(run.run_id, ($event.target as HTMLInputElement).checked)"
          />
          <div class="eval-run-panel__item-main">
            <div class="eval-run-panel__item-line1">
              <span class="eval-run-panel__item-model">{{ runModel(run) }}</span>
              <span class="eval-run-panel__item-status eval-run-panel__item-status--completed">已完成</span>
            </div>
            <div class="eval-run-panel__item-line2">
              {{ formatTime(run.completed_at || run.started_at) }} · 正确
              {{ run.summary_scores?.correct ?? '—' }}/{{ run.summary_scores?.total ?? run.total_questions }} 题
            </div>
          </div>
          <div class="eval-run-panel__item-side" @click.stop>
            <span class="eval-run-panel__item-score">{{ formatScore(run.summary_scores) }}</span>
            <a-tooltip title="删除">
              <a-button
                type="text"
                danger
                class="eval-run-panel__item-icon-btn"
                @click="onDeleteClick(run.run_id)"
              >
                <template #icon><DeleteOutlined /></template>
              </a-button>
            </a-tooltip>
          </div>
        </div>
      </div>
    </div>

    <a-empty
      v-if="!activeRuns.length && !historyRuns.length"
      description="暂无评测记录，点击上方新增评测"
      :image="false"
      class="eval-run-panel__empty"
    />

    <!-- E：题目明细 / 逐题对比 -->
    <div v-if="historyRuns.length || activeRuns.length" class="eval-run-panel__detail">
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
                  {{ shortSeq(run) }}
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
  </div>
</template>

<script setup lang="ts">
/**
 * 评测运行面板（重排后的信息层级）：
 * 新增评测按钮 → 进行中 item（含中断未完成，重来/暂停-继续/删除）→ 运行中实时统计
 * → 历史记录 item-list（仅已完成）→ 题目明细/逐题对比。
 * 发起评测的模型与题集选择全部收敛进「新增评测」弹框（EvalRunCreateModal）。
 */
import { computed, ref, watch, watchEffect } from 'vue'
import {
  DeleteOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
  PlusOutlined,
  RedoOutlined,
} from '@ant-design/icons-vue'
import type { EvalRun, EvalRunDetail, EvalSummaryScores } from '../types/eval'

const props = defineProps<{
  currentRun: EvalRun | null
  /** 当前测试集的全部整体/单题运行（面板自行按整体评测过滤） */
  runs?: EvalRun[]
  /** 按需加载某次 run 的题目详情；{ enrich: true } 时额外带题干（逐题对比表要用），
   *  默认精简版够右栏格子染色（不回 1000+ 份题干） */
  loadRunDetails?: (runId: string, opts?: { enrich?: boolean }) => Promise<EvalRunDetail[]>
}>()

const emit = defineEmits<{
  'create-run': []
  /** 以该 item 的题集+模型重新发起全量评测 */
  rerun: [run: EvalRun]
  /** 断点续跑该 item */
  resume: [run: EvalRun]
  stop: []
  'select-run': [runId: string]
  'delete-run': [runId: string]
}>()

const compareIds = ref<string[]>([])
const detailsByRun = ref<Record<string, EvalRunDetail[]>>({})
const showDiffOnly = ref(true)
const selectedRunId = ref<string | undefined>(undefined)

const fullRuns = computed(() => (props.runs || []).filter(r => r.is_full_run !== false))

const runningRun = computed(() => {
  if (props.currentRun?.status === 'running' && props.currentRun.is_full_run !== false) {
    return props.currentRun
  }
  return fullRuns.value.find(r => r.status === 'running') || null
})

/** 置顶的未完成 item = 运行中 + 最近一次中断且有可续跑进度的 run（更早的中断记录不刷屏） */
const activeRuns = computed(() => {
  const out: EvalRun[] = []
  if (runningRun.value) out.push(runningRun.value)
  const resumable = fullRuns.value.find(r =>
    (r.status === 'cancelled' || r.status === 'failed') &&
    r.completed_questions > 0 &&
    r.completed_questions < r.total_questions &&
    r.run_id !== runningRun.value?.run_id
  )
  if (resumable) out.push(resumable)
  return out
})

const activeRunIds = computed(() => new Set(activeRuns.value.map(r => r.run_id)))

/** 历史 = 已完成（含跑完全部题但状态记失败的）；未完成的置顶展示不进历史 */
const historyRuns = computed(() =>
  fullRuns.value.filter(r =>
    !activeRunIds.value.has(r.run_id) &&
    (r.status === 'completed' || r.completed_questions >= r.total_questions)
  )
)

/** 运行中 run 的实况明细：跟随父级轮询拉取；实时统计必须由本次 run 真实进度派生，
 * 不回退上一轮 summary（幽灵数据教训 2026-09-06）。 */
const runLiveDetails = ref<EvalRunDetail[]>([])
watch(
  () => [props.currentRun?.run_id, props.currentRun?.completed_questions] as const,
  async () => {
    const run = props.currentRun
    if (run?.status === 'running' && props.loadRunDetails) {
      runLiveDetails.value = await props.loadRunDetails(run.run_id)
    } else if (run?.status !== 'running') {
      runLiveDetails.value = []
    }
  },
  { immediate: true },
)

const liveSummary = computed(() => {
  let correct = 0, wrong = 0, errored = 0
  for (const d of runLiveDetails.value) {
    if (d.status === 'error' || d.error) { errored++; continue }
    if (d.status !== 'completed') continue
    if (d.quality === 'correct') correct++
    else if (d.quality === 'wrong') wrong++
  }
  return { correct, wrong, errored, done: correct + wrong }
})

const scoreNumber = computed(() => {
  const { correct, done } = liveSummary.value
  return done ? ((correct / done) * 100).toFixed(1) : '0'
})

const accuracyPercent = computed(() => parseFloat(scoreNumber.value) || 0)

/** 被测模型名：manifest 快照优先，run_name 前缀兜底（旧 run 无快照） */
const runModel = (run: EvalRun): string => {
  const snap = run.config_snapshot as { model?: string } | null | undefined
  return snap?.model || String(run.run_name || '').split('_')[0] || '默认模型'
}

/** 简化测试编号：run_id 十六进制前 6 位（对比表列头等场景；标题行已不展示编号） */
const shortSeq = (run: EvalRun): string =>
  String(run.run_id || '').replace(/^run[-_]?/, '').slice(0, 6)

const statusLabels: Record<string, string> = {
  running: '评测中',
  cancelled: '已中断',
  failed: '失败',
  completed: '已完成',
}
const statusLabel = (run: EvalRun): string => statusLabels[run.status] || run.status

const correctCount = (run: EvalRun): number | string => {
  if (run.run_id === runningRun.value?.run_id) return liveSummary.value.correct
  return run.summary_scores?.correct ?? '—'
}

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

const runScoreText = (run: EvalRun): string => {
  if (run.run_id === runningRun.value?.run_id) return `${scoreNumber.value}%`
  return formatScore(run.summary_scores)
}

const formatTime = (iso?: string | null): string => {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const mi = String(d.getMinutes()).padStart(2, '0')
  return `${mm}-${dd} ${hh}:${mi}`
}

/** 已按「带题干」那一档加载过的 run：精简版（默认）不回题干，逐题对比表要用时再补一次 */
const enrichedRunIds = ref<Set<string>>(new Set())

/** 按需加载并缓存某次 run 的题目详情（运行中的不缓存，跟随进度刷新） */
const ensureDetails = async (runId: string, opts?: { enrich?: boolean }) => {
  if (!props.loadRunDetails) return
  const isRunningRun = runId === runningRun.value?.run_id
  const needEnrich = Boolean(opts?.enrich) && !enrichedRunIds.value.has(runId)
  if (!needEnrich && !isRunningRun && detailsByRun.value[runId]) return
  const details = await props.loadRunDetails(runId, opts)
  detailsByRun.value = { ...detailsByRun.value, [runId]: details }
  if (opts?.enrich) {
    enrichedRunIds.value = new Set(enrichedRunIds.value).add(runId)
  }
}

/** 默认选中：运行中优先，其次最近一条历史，再次置顶的中断 item；
 * 选中项从“进行中”迁入“历史”（跑完）不打断选中与明细缓存 */
watchEffect(() => {
  const all = [...activeRuns.value, ...historyRuns.value]
  if (!all.length) {
    selectedRunId.value = undefined
    return
  }
  if (selectedRunId.value && all.some(r => r.run_id === selectedRunId.value)) return
  const def = runningRun.value || historyRuns.value[0] || activeRuns.value[0]
  selectedRunId.value = def.run_id
  emit('select-run', def.run_id)
  void ensureDetails(def.run_id)
})

const onSelectRun = (runId: string) => {
  if (selectedRunId.value === runId) return
  selectedRunId.value = runId
  emit('select-run', runId)
  void ensureDetails(runId)
}

const onToggleCompare = (runId: string, checked: boolean) => {
  if (checked) {
    if (compareIds.value.includes(runId) || compareIds.value.length >= 3) return
    compareIds.value = [...compareIds.value, runId]
    // 对比表要显示题干：这一档明细比染色用的精简版多一份题干，按需补拉
    void ensureDetails(runId, { enrich: true })
  } else {
    compareIds.value = compareIds.value.filter(id => id !== runId)
  }
}

/** 运行中 run 进度变化时刷新其明细 */
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
  if (selectedRunId.value === runId) selectedRunId.value = undefined
  compareIds.value = compareIds.value.filter(id => id !== runId)
}

const primaryDetails = computed(() => {
  if (!selectedRunId.value) return []
  return detailsByRun.value[selectedRunId.value] || []
})

const questionRows = computed(() =>
  primaryDetails.value.map((d, idx) => {
    let kind = 'na'
    if (d.status === 'completed') {
      if (d.quality === 'correct') kind = 'ok'
      else if (d.quality === 'wrong') kind = 'bad'
    } else if (d.status === 'error') {
      kind = 'bad'
    } else if (d.status === 'running') {
      kind = 'running'
    }
    return { seq: idx + 1, kind, question: String(d.question || '') }
  })
)

const isCompareMode = computed(() => compareIds.value.length >= 2)

const compareRuns = computed(() =>
  compareIds.value
    .map(id => fullRuns.value.find(r => r.run_id === id))
    .filter((r): r is EvalRun => !!r)
)

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
    rows.push({
      seq: i + 1,
      question: String(runDetails.find(d => d[i])?.[i]?.question || ''),
      hasDiff: new Set(marks).size > 1,
      cells,
    })
  }
  return rows
})

const diffCount = computed(() => allCompareRows.value.filter(r => r.hasDiff).length)

const compareRows = computed(() =>
  showDiffOnly.value ? allCompareRows.value.filter(r => r.hasDiff) : allCompareRows.value
)
</script>

<style lang="less" scoped>
.eval-run-panel {
  display: flex;
  flex-direction: column;
  min-height: 100%;
  padding: 12px;
  gap: 12px;

  &__create {
    flex-shrink: 0;
  }

  /* ===== item（进行中 / 历史共用）===== */
  &__item {
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
      border-color: fade(@evals-primary, 55%);
    }

    &--selected {
      border-color: @evals-primary;
      background: fade(@evals-primary, 6%);
    }

    &--compared {
      background: fade(@evals-primary, 4%);
    }

    &-main {
      flex: 1;
      min-width: 0;
    }

    /* 第一行：模型 + 状态标签（nowrap 防窄栏把内容折成竖排） */
    &-line1 {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 12px;
      color: var(--text-primary);
      min-width: 0;
      white-space: nowrap;
    }

    /* 第二行：时间 + 正确题数（弱化色；nowrap 防时间被拆成多行竖排） */
    &-line2 {
      margin-top: 2px;
      font-size: 11px;
      color: var(--text-tertiary);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    &-model {
      flex: 1 1 auto;
      min-width: 0;
      font-weight: 600;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    /* 状态一眼可见：评测中带进度计数（此前用户误以为“没进展”的直接修复） */
    &-status {
      flex-shrink: 0;
      font-size: 11px;
      line-height: 18px;
      padding: 0 7px;
      border-radius: 9px;
      font-variant-numeric: tabular-nums;

      &--running {
        color: #1677ff;
        background: fade(#1677ff, 10%);
        animation: eval-run-panel-pulse 1.6s ease-in-out infinite;
      }

      &--completed {
        color: #389e0d;
        background: fade(#52c41a, 10%);
      }

      &--cancelled {
        color: #d48806;
        background: fade(#faad14, 12%);
      }

      &--failed {
        color: #f5222d;
        background: fade(#f5222d, 8%);
      }
    }

    &-side {
      flex-shrink: 0;
      display: flex;
      align-items: center;
      gap: 4px;
    }

    &-score {
      font-size: 13px;
      font-weight: 600;
      color: @evals-primary;
      font-variant-numeric: tabular-nums;
    }

    &-actions {
      display: flex;
      align-items: center;
      gap: 2px;
    }

    /* 纯图标操作按钮，图标放大一档更好点 */
    &-icon-btn {
      width: 30px;
      height: 30px;
      padding: 0;
      display: inline-flex;
      align-items: center;
      justify-content: center;

      :deep(.anticon) {
        font-size: 16px;
      }
    }

    &-check {
      flex-shrink: 0;
    }
  }

  &__history {
    &-list {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
  }

  &__accuracy {
    padding: 14px 12px;
    border-radius: 8px;
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);

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

    &-progress {
      font-size: 11px;
      color: var(--text-secondary);
      font-variant-numeric: tabular-nums;
    }

    &-body {
      display: flex;
      align-items: center;
      gap: 18px;
      margin-top: 8px;
    }

    &-left {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 6px;
    }

    &-right {
      flex: 1;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
  }

  &__stat {
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 13px;

    &-label {
      color: var(--text-secondary);
    }

    &-value {
      font-weight: 600;
      color: var(--text-primary);

      &--ok {
        color: #52c41a;
      }

      &--bad {
        color: #f5222d;
      }
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
