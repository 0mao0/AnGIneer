<template>
  <!-- 夜间维护单日明细：总览（矩阵图+分行结论）+ 三个折叠条（回退题/修复题/评测报告），对比口径=固化基线 -->
  <div class="ndd">
    <div class="ndd-overview">
      <div class="ndd-overview__left">
        <div v-if="hasMatrix" ref="matrixChartEl" class="ndd-matrix-chart" />
      </div>
      <div class="ndd-analysis">
        <p v-for="(line, i) in analysisLines" :key="i" class="ndd-analysis__line">{{ line }}</p>
        <a-button
          v-if="cur.run_id"
          class="ndd-open-run"
          size="small"
          type="link"
          @click="$emit('open-run', { datasetId: cur.dataset_id || DEFAULT_NIGHTLY_DATASET, runId: cur.run_id })"
        >
          在日常测试中打开本次运行
        </a-button>
        <a-alert
          v-for="(reason, i) in cur.gate_reasons || []"
          :key="`r${i}`"
          type="error"
          :message="reason"
          show-icon
          class="ndd-alert"
        />
        <a-alert
          v-if="cur.note"
          type="warning"
          :message="`执行记录：${cur.note}`"
          show-icon
          class="ndd-alert"
        />
      </div>
    </div>

    <a-collapse class="ndd-collapses">
      <a-collapse-panel key="regressions" :header="`回退题目（基线答对 → 今晚答错，${regressions.length} 题）`">
        <a-empty
          v-if="!regressions.length"
          :image="Empty.PRESENTED_IMAGE_SIMPLE"
          description="没有题目从答对变成答错"
        />
        <ul v-else class="ndd-qlist">
          <li
            v-for="item in regressions"
            :key="item.qid"
            class="ndd-qitem"
            :class="{ 'ndd-qitem--expandable': !!item.evidence }"
            @click="item.evidence && toggleExpand(item.qid)"
          >
            <a-tooltip :title="`${bucketPlain(item.bucket)}${item.bucket_detail ? `（${item.bucket_detail}）` : ''}`">
              <a-tag :color="bucketColor(item.bucket)" class="ndd-qitem__tag">{{ bucketShort(item.bucket) }}</a-tag>
            </a-tooltip>
            <a-tooltip :title="item.question || undefined">
              <p class="ndd-qitem__q">{{ item.question || `题目 ${item.qid.slice(0, 8)}` }}</p>
            </a-tooltip>
            <a-tooltip title="基线答对，今晚答错">
              <span class="ndd-qitem__mark ndd-qitem__mark--down">✓→✗</span>
            </a-tooltip>
            <RightOutlined v-if="item.evidence" class="ndd-qitem__caret" :class="{ 'ndd-qitem__caret--open': !!expanded[item.qid] }" />
            <div v-if="item.evidence && expanded[item.qid]" class="ndd-ev">
              <div v-for="row in evidenceRows(item.evidence)" :key="row.label" class="ndd-ev__row">
                <span class="ndd-ev__label">{{ row.label }}</span>
                <span class="ndd-ev__from">{{ row.from }}</span>
                <span class="ndd-ev__arrow">→</span>
                <span class="ndd-ev__to">{{ row.to }}</span>
              </div>
              <p v-if="item.evidence.reason" class="ndd-ev__text">评判理由：{{ item.evidence.reason }}</p>
              <blockquote v-if="item.evidence.answer_excerpt" class="ndd-ev__answer">{{ item.evidence.answer_excerpt }}</blockquote>
              <p v-if="item.evidence.error" class="ndd-ev__error">执行错误：{{ item.evidence.error }}</p>
            </div>
          </li>
        </ul>
      </a-collapse-panel>

      <a-collapse-panel key="fixed" :header="fixedHeader">
        <ul class="ndd-qlist">
          <li v-for="item in fixed" :key="item.qid" class="ndd-qitem ndd-qitem--fixed">
            <a-tag color="success" class="ndd-qitem__tag">已修复</a-tag>
            <a-tooltip :title="item.question || undefined">
              <p class="ndd-qitem__q">{{ item.question || `题目 ${item.qid.slice(0, 8)}` }}</p>
            </a-tooltip>
            <a-tooltip title="基线答错，今晚答对">
              <span class="ndd-qitem__mark ndd-qitem__mark--up">✗→✓</span>
            </a-tooltip>
          </li>
        </ul>
      </a-collapse-panel>

      <a-collapse-panel v-if="detail?.report_md" key="report" header="评测报告（report.md）">
        <div class="ndd-md" v-html="reportHtml" />
      </a-collapse-panel>
    </a-collapse>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Empty } from 'ant-design-vue'
import { RightOutlined } from '@ant-design/icons-vue'
import * as echarts from 'echarts'
import { renderMarkdownToHtml } from '@angineer/aichat-ui/utils/markdown'

interface EvidencePair { base?: unknown; new?: unknown }

interface QuestionEvidence {
  route?: Record<string, EvidencePair>
  retrieval?: Record<string, EvidencePair>
  semantic?: EvidencePair & { threshold?: number }
  has_answer?: EvidencePair
  reason?: string
  answer_excerpt?: string
  error?: string
}

interface QuestionItem {
  qid: string
  question?: string
  bucket?: string
  bucket_detail?: string
  evidence?: QuestionEvidence
}

interface NightlyMatrix { pp?: number; pf?: number; fp?: number; ff?: number }

interface NightlyDayLite {
  date: string
  state: string
  overall_score?: number
  correct?: number
  total?: number
  delta?: number
  delta_ci95?: [number, number]
  matrix?: NightlyMatrix
  verdict?: string
  note?: string
  run_id?: string
  dataset_id?: string
  judge_failed_count?: number
  /** 判分引擎口径标记（v0.2.51 起携带） */
  eval_engine?: string
  gate_reasons?: string[]
  regressions?: Record<string, string>
  regression_items?: QuestionItem[]
  fixed_items?: QuestionItem[]
}

const DEFAULT_NIGHTLY_DATASET = 'open-ragbench-subset-v2'

const props = defineProps<{ day: NightlyDayLite; detail?: { nightly?: NightlyDayLite; report_md?: string } }>()

defineEmits<{ (e: 'open-run', payload: { datasetId: string; runId: string }): void }>()

/** 归因机读码 → 大白话（机读码来自 compare_runs.attribute()，原始串留 tooltip） */
const BUCKET_PLAIN: Record<string, string> = {
  infra_anomaly: '评判基础设施抖动，非真回归',
  retrieval_regression: '检索变差：原来找得到的内容找不到了',
  refusal: '该答的题没给出答案',
  route_change: '作答处理路径变化',
  no_semantic_eval: '缺少语义评分',
  partial_coverage: '方向对但答得不全',
  wrong_conclusion: '内容相关但结论错了',
  severe_miss: '完全答偏',
}
/** 条目行内的短标签（完整解释放 tooltip），保证一行放得下、不出横向滚动 */
const BUCKET_SHORT: Record<string, string> = {
  infra_anomaly: '评判抖动',
  retrieval_regression: '检索变差',
  refusal: '拒答',
  route_change: '路径变化',
  no_semantic_eval: '缺评',
  partial_coverage: '答得不全',
  wrong_conclusion: '结论错',
  severe_miss: '答偏',
}
const bucketPlain = (bucket?: string) => (bucket && BUCKET_PLAIN[bucket]) || bucket || '未知原因'
const bucketShort = (bucket?: string) => (bucket && BUCKET_SHORT[bucket]) || bucket || '未知'
const bucketColor = (bucket?: string) => (bucket === 'infra_anomaly' ? 'default' : 'orange')

/** 列表页已回传整份 nightly.json，明细接口回来后用更全的那份 */
const cur = computed<NightlyDayLite>(() => props.detail?.nightly || props.day)

const pct = (value?: number) => (value == null ? '—' : `${(value * 100).toFixed(2)}%`)

const hasMatrix = computed(() => cur.value.matrix != null)
const matrixPf = computed(() => cur.value.matrix?.pf)

/** 分行结论：一行一件事，不写门禁等内部术语；基线参照分写进差值句，不再单独展示 */
const analysisLines = computed<string[]>(() => {
  const day = cur.value
  if (day.state === 'error') return [day.note || '评测中断，未产出结果。']
  const dir = (day.delta ?? 0) >= 0 ? '高' : '低'
  const baseRef = day.overall_score != null && day.delta != null ? `（${pct(day.overall_score - day.delta)}）` : ''
  const lines = [`今晚答对 ${pct(day.overall_score)}，比基线${baseRef}${dir} ${(Math.abs(day.delta ?? 0) * 100).toFixed(2)} 个百分点。`]
  const m = day.matrix || {}
  if (m.pf != null || m.fp != null) {
    lines.push(`相对基线：答对变答错 ${m.fp ?? '—'} 题，答错变答对 ${m.pf ?? '—'} 题。`)
  }
  lines.push(day.state === 'red'
    ? '整体明显变差，需要排查下方回退题目。'
    : '整体没有变差，正常波动。')
  if (day.judge_failed_count) {
    lines.push(`评判环节抖动 ${day.judge_failed_count} 题，已自动补判。`)
  }
  // 判分口径提示：deepeval 引擎与 legacy 判分存在系统性口径差，防分差被误读为回归
  if (day.eval_engine && day.eval_engine.includes('deepeval')) {
    lines.push('本次由 DeepEval 引擎判分（口径比早期 legacy 判分严约 8 个百分点）；与 legacy 基线的分差含口径差，不代表系统回归。')
  }
  return lines
})

const regressions = computed<QuestionItem[]>(() => {
  const day = cur.value
  if (day.regression_items?.length) return day.regression_items
  return Object.entries(day.regressions || {}).map(([qid, bucket]) => ({ qid, bucket_detail: bucket }))
})
const fixed = computed<QuestionItem[]>(() => cur.value.fixed_items || [])
// ── 回退题证据展开（问题具体在哪：检索/语义分/是否作答/路由 前后对比 + 评判理由 + 今晚答案摘录）──
const expanded = ref<Record<string, boolean>>({})
const toggleExpand = (qid: string) => { expanded.value[qid] = !expanded.value[qid] }

const ROUTE_LABEL: Record<string, string> = { intent: '路由·意图', task_type: '路由·任务类型', strategy: '路由·处理路径' }

const fmtNum = (v: unknown): string =>
  typeof v === 'number' ? (Number.isInteger(v) ? String(v) : v.toFixed(2)) : String(v ?? '—')
const fmtHit = (v: unknown): string => {
  if (v == null || v === '') return '—'
  return Number(v) >= 1 ? '命中' : '未命中'
}
const fmtYesNo = (v: unknown): string =>
  v === true || v === 1 ? '是' : v === false || v === 0 ? '否' : '—'

function evidenceRows(ev: QuestionEvidence): Array<{ label: string; from: string; to: string }> {
  const rows: Array<{ label: string; from: string; to: string }> = []
  const hit5 = ev.retrieval?.['hit@5_doc']
  if (hit5) rows.push({ label: '检索 hit@5', from: fmtHit(hit5.base), to: fmtHit(hit5.new) })
  const cit = ev.retrieval?.citation_hit
  if (cit) rows.push({ label: '引用命中', from: fmtHit(cit.base), to: fmtHit(cit.new) })
  if (ev.semantic) {
    const th = ev.semantic.threshold != null ? `（过线 ${ev.semantic.threshold}）` : ''
    rows.push({ label: '语义分', from: fmtNum(ev.semantic.base), to: `${fmtNum(ev.semantic.new)}${th}` })
  }
  if (ev.has_answer) rows.push({ label: '给出回答', from: fmtYesNo(ev.has_answer.base), to: fmtYesNo(ev.has_answer.new) })
  for (const [field, pair] of Object.entries(ev.route || {})) {
    rows.push({ label: ROUTE_LABEL[field] || `路由·${field}`, from: fmtNum(pair.base), to: fmtNum(pair.new) })
  }
  return rows
}

/** report.md 走 aichat-ui 同款渲染器（表格/标题/列表；admin-web 本就经 AIChat/evals-ui 打入了该 chunk） */
const reportHtml = computed(() => renderMarkdownToHtml(props.detail?.report_md || '', ''))

const fixedHeader = computed(() => {
  const total = matrixPf.value ?? fixed.value.length
  return fixed.value.length < total
    ? `修复题目（基线答错 → 今晚答对，共 ${total} 题，展示 ${fixed.value.length} 题）`
    : `修复题目（基线答错 → 今晚答对，${total} 题）`
})

// ── 过渡矩阵横向柱状图（echarts，沿用 ApiKeyChart 的全量 import 惯例）──
const matrixChartEl = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | undefined

function renderChart(): void {
  if (!matrixChartEl.value || !hasMatrix.value) return
  if (!chart) chart = echarts.init(matrixChartEl.value)
  const m = cur.value.matrix || {}
  const rows: Array<{ name: string; value: number; color: string }> = [
    { name: '都答对', value: m.pp ?? 0, color: '#bfbfbf' },
    { name: '修复（基线错→对）', value: m.pf ?? 0, color: '#52c41a' },
    { name: '回退（基线对→错）', value: m.fp ?? 0, color: '#ff4d4f' },
    { name: '都答错', value: m.ff ?? 0, color: '#8c8c8c' },
  ]
  chart.setOption({
    tooltip: { trigger: 'item', formatter: '{b}：{c} 题' },
    grid: { left: 4, right: 44, top: 4, bottom: 4, containLabel: true },
    xAxis: {
      type: 'value',
      axisLabel: { show: false },
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'category',
      inverse: true,
      data: rows.map(r => r.name),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: '#999', fontSize: 12 },
    },
    series: [{
      type: 'bar',
      barWidth: 14,
      data: rows.map(r => ({ value: r.value, itemStyle: { color: r.color, borderRadius: [0, 7, 7, 0] } })),
      label: { show: true, position: 'right', color: '#999', fontSize: 12 },
    }],
  })
}

const handleResize = () => chart?.resize()

onMounted(async () => {
  await nextTick()
  renderChart()
  window.addEventListener('resize', handleResize)
})
watch(cur, async () => {
  await nextTick()
  renderChart()
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  chart?.dispose()
  chart = undefined
})
</script>

<style scoped>
.ndd {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
}
/* 总览：图 + 分行结论，横向铺满且可换行，不出横向滚动 */
.ndd-overview {
  display: flex;
  gap: 24px;
  align-items: flex-start;
  flex-wrap: wrap;
  min-width: 0;
}
.ndd-overview__left {
  flex: 0 1 360px;
  min-width: 280px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.ndd-analysis {
  flex: 1 1 320px;
  min-width: 260px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.ndd-matrix-chart {
  width: 100%;
  max-width: 360px;
  height: 140px;
}
.ndd-analysis__line {
  margin: 0;
  font-size: 13px;
  line-height: 22px;
  color: var(--text-primary, rgba(0, 0, 0, 0.85));
}
.ndd-open-run {
  align-self: flex-start;
  padding-left: 0;
}
.ndd-alert {
  margin-top: 2px;
}
.ndd-collapses {
  background: transparent;
}
/* 渲染后的 report.md：表格/标题/列表样式（v-html 内容需 :deep） */
.ndd-md {
  font-size: 13px;
  line-height: 22px;
  color: var(--text-primary, rgba(0, 0, 0, 0.85));
  max-height: 480px;
  overflow: auto;
  overflow-wrap: anywhere;
}
.ndd-md :deep(h1) { font-size: 17px; margin: 12px 0 8px; }
.ndd-md :deep(h2) { font-size: 15px; margin: 12px 0 6px; }
.ndd-md :deep(h3) { font-size: 14px; margin: 10px 0 6px; }
.ndd-md :deep(p) { margin: 4px 0; }
.ndd-md :deep(ul), .ndd-md :deep(ol) { margin: 4px 0; padding-left: 22px; }
.ndd-md :deep(li) { margin: 2px 0; }
.ndd-md :deep(strong) { font-weight: 600; }
.ndd-md :deep(code) {
  background: rgba(128, 128, 128, 0.12);
  border-radius: 3px;
  padding: 1px 5px;
  font-size: 12px;
}
.ndd-md :deep(pre code) { background: transparent; padding: 0; }
.ndd-md :deep(pre) {
  background: rgba(128, 128, 128, 0.08);
  border-radius: 6px;
  padding: 8px 10px;
  overflow: auto;
}
.ndd-md :deep(table) {
  border-collapse: collapse;
  margin: 8px 0;
}
/* 14 列指标表按紧凑档排版：窄 padding + 小字号 + 等宽数字，避免整表过宽 */
.ndd-md :deep(th), .ndd-md :deep(td) {
  border: 1px solid var(--border-color, rgba(5, 5, 5, 0.08));
  padding: 1px 5px;
  font-size: 11.5px;
  line-height: 16px;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.ndd-md :deep(th:first-child), .ndd-md :deep(td:first-child) {
  white-space: normal;
  max-width: 120px;
}
.ndd-md :deep(th) {
  background: var(--bg-secondary, rgba(128, 128, 128, 0.06));
  font-weight: 600;
}
.ndd-md :deep(tr:nth-child(even) td) {
  background: var(--bg-secondary, rgba(128, 128, 128, 0.03));
}
.ndd-qlist {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 420px;
  overflow-y: auto;
  overflow-x: hidden;
}
/* 单行紧凑条目：标签 + 单行省略题干 + 状态符号，全部受父宽约束 */
.ndd-qitem {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  min-width: 0;
  max-width: 100%;
  border: 1px solid var(--border-color, rgba(5, 5, 5, 0.06));
  border-radius: 6px;
  padding: 3px 8px;
  background: var(--card-bg, var(--bg-primary, #fff));
}
.ndd-qitem--expandable {
  cursor: pointer;
}
.ndd-qitem__caret {
  flex-shrink: 0;
  font-size: 10px;
  color: var(--text-secondary, rgba(0, 0, 0, 0.35));
  transition: transform 0.2s;
}
.ndd-qitem__caret--open {
  transform: rotate(90deg);
}
/* 展开后的逐题前后对比证据 */
.ndd-ev {
  width: 100%;
  margin: 2px 0 4px;
  padding: 8px 10px;
  border-radius: 6px;
  background: var(--bg-secondary, rgba(128, 128, 128, 0.06));
  font-size: 12px;
  line-height: 20px;
}
.ndd-ev__row {
  display: flex;
  align-items: baseline;
  gap: 6px;
  flex-wrap: wrap;
}
.ndd-ev__label {
  color: var(--text-secondary, rgba(0, 0, 0, 0.45));
  min-width: 88px;
}
.ndd-ev__from {
  color: var(--text-secondary, rgba(0, 0, 0, 0.65));
  text-decoration: line-through;
  text-decoration-color: rgba(0, 0, 0, 0.25);
}
.ndd-ev__arrow {
  color: var(--text-secondary, rgba(0, 0, 0, 0.35));
}
.ndd-ev__to {
  color: var(--text-primary, rgba(0, 0, 0, 0.85));
  font-weight: 600;
}
.ndd-ev__text {
  margin: 4px 0 0;
  color: var(--text-primary, rgba(0, 0, 0, 0.85));
}
.ndd-ev__answer {
  margin: 6px 0 0;
  padding: 4px 10px;
  border-left: 3px solid var(--border-color, rgba(5, 5, 5, 0.12));
  color: var(--text-secondary, rgba(0, 0, 0, 0.65));
  overflow-wrap: anywhere;
  display: -webkit-box;
  -webkit-line-clamp: 4;
  line-clamp: 4;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.ndd-ev__error {
  margin: 4px 0 0;
  color: #ff4d4f;
}
.ndd-qitem__tag {
  flex-shrink: 0;
  margin-inline-end: 0;
}
.ndd-qitem__q {
  flex: 1;
  min-width: 0;
  margin: 0;
  font-size: 12px;
  line-height: 18px;
  color: var(--text-primary, rgba(0, 0, 0, 0.85));
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ndd-qitem__mark {
  flex-shrink: 0;
  font-size: 12px;
  white-space: nowrap;
}
.ndd-qitem__mark--down {
  color: #ff4d4f;
}
.ndd-qitem__mark--up {
  color: #52c41a;
}
.ndd-qitem--fixed .ndd-qitem__q {
  color: var(--text-secondary, rgba(0, 0, 0, 0.65));
}
</style>
