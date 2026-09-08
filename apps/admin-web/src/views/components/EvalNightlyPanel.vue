<template>
  <!-- 夜间维护：nightly 门禁结果的历史与明细（数据源 data/evals/nightly/，仅管理员） -->
  <div class="eval-nightly-panel">
    <div class="nightly-content">
      <DataTable
        :columns="columns"
        :data-source="days"
        row-key="date"
        :loading="loading"
        :expand-row-by-click="true"
        :expandable="{ rowExpandable: (record: NightlyDay) => !record.running }"
        :empty-text="EMPTY_TEXT"
        storage-key="angineer-nightly-v2"
        @expand="handleExpand"
      >
        <template #headerCell="{ column }">
          <template v-if="column.key === 'delta'">
            基线
            <a-tooltip title="相对固化基线的正确率差（个百分点），+ 表示超过基线；基线为人工钉住的稳定 run">
              <QuestionCircleOutlined class="nightly-help" />
            </a-tooltip>
          </template>
        </template>

        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'subject'">
            {{ record.subject || record.dataset_id || '—' }}
          </template>
          <template v-else-if="column.key === 'time'">
            {{ fmtTime(record.started_at || record.generated_at) }}
          </template>
          <template v-else-if="column.key === 'duration'">
            {{ durationText(record) }}
          </template>
          <template v-else-if="column.key === 'state'">
            <a-tag :color="stateColor(record.state)">{{ stateLabel(record.state) }}</a-tag>
          </template>
          <template v-else-if="column.key === 'overall'">
            {{ pct(record.overall_score) }}
          </template>
          <template v-else-if="column.key === 'delta'">
            <span :class="deltaClass(record)">{{ deltaText(record) }}</span>
          </template>
          <template v-else-if="column.key === 'verdict'">
            {{ record.verdict || fallbackVerdict(record) }}
          </template>
          <template v-else-if="column.key === 'action'">
            <!-- 按钮在行内，click.stop 阻断冒泡，避免 expandRowByClick 顺带展开明细 -->
            <a-space v-if="record.running" :size="6">
              <a-popconfirm title="停止后当前题目做完即退出，不留结论、不发通知" @confirm="stopRunning">
                <a-button size="small" danger @click.stop>停止</a-button>
              </a-popconfirm>
              <a-popconfirm title="删除会同步停止正在运行的评测，确认？" @confirm="stopRunning">
                <a-button size="small" @click.stop>删除</a-button>
              </a-popconfirm>
            </a-space>
            <a-popconfirm
              v-else
              title="删除这条结论记录，并连带删除对应评测 run（逐题结果一并消失，不可恢复）"
              :width="260"
              @confirm="removeDay(record)"
            >
              <a-button size="small" danger @click.stop>删除</a-button>
            </a-popconfirm>
          </template>
        </template>

        <template #expandedRowRender="{ record }">
          <a-spin :spinning="!detailOf(record)">
            <NightlyDayDetail
              v-if="detailOf(record)"
              :day="record"
              :detail="detailOf(record)"
              @open-run="(p) => emit('open-run', p)"
            />
          </a-spin>
        </template>
      </DataTable>
    </div>

    <a-modal
      v-model:open="runModal.open"
      title="本次夜间流水线将执行"
      ok-text="开始运行"
      cancel-text="关闭"
      :confirm-loading="runModal.launching"
      @ok="confirmLaunch"
    >
      <a-spin :spinning="runModal.loading">
        <a-descriptions v-if="runModal.plan" size="small" :column="1" bordered>
          <a-descriptions-item label="测试集">
            {{ runModal.plan.dataset?.title }}（{{ runModal.plan.dataset?.question_count ?? '?' }} 题）
          </a-descriptions-item>
          <a-descriptions-item label="作答模型">{{ runModal.plan.answer_model }}</a-descriptions-item>
          <a-descriptions-item label="评判模型（候选链）">
            {{ (runModal.plan.judge_models || []).join(' → ') }}
          </a-descriptions-item>
          <a-descriptions-item label="并发 / 单次时限">
            {{ runModal.plan.concurrency }} · {{ runModal.plan.timeout_minutes }} 分钟
          </a-descriptions-item>
          <a-descriptions-item label="异常自动补判">
            最多 {{ runModal.plan.retry_rounds }} 轮（judge 抖动仅重判分，执行错误整题重跑）
          </a-descriptions-item>
          <a-descriptions-item label="结果去向">
            本页新增当日结论条目 + 企微通知（评测逐题结果进「日常测试」历史）
          </a-descriptions-item>
        </a-descriptions>
        <a-empty v-else-if="!runModal.loading" description="执行计划读取失败" />
      </a-spin>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { message } from 'ant-design-vue'
import { QuestionCircleOutlined } from '@ant-design/icons-vue'
import { DataTable } from '@angineer/table-ui'
import type { DataTableColumn } from '@angineer/table-ui'
import evalsApi from '../../api/evals'
import NightlyDayDetail from './NightlyDayDetail.vue'

interface NightlyDay {
  date: string
  state: string
  /** 后端注入的虚拟运行行（date 固定 "running"，不落归档） */
  running?: boolean
  subject?: string
  /** 开跑时间（v0.2.42 起 nightly.json 携带；历史条目无此字段，时间列回退 generated_at、时长显示“—”） */
  started_at?: string
  generated_at?: string
  overall_score?: number
  correct?: number
  total?: number
  errored?: number
  delta?: number
  delta_ci95?: [number, number]
  base_label?: string
  judge_failed_count?: number
  verdict?: string
  run_id?: string
  dataset_id?: string
  gate_reasons?: string[]
  note?: string
}

interface NightlyDayDetailData {
  nightly?: NightlyDay
  report_md?: string
}

const emit = defineEmits<{
  (e: 'open-run', payload: { datasetId: string; runId: string }): void
}>()

const loading = ref(false)
const days = ref<NightlyDay[]>([])
const details = ref<Record<string, NightlyDayDetailData>>({})

const EMPTY_TEXT = '暂无夜间维护记录 —— nightly 评测流程每晚运行后自动在此发布门禁结论'

// 全列居中（antd align 经 DataTableColumn 索引签名透传到 a-table，表头与单元格同时生效）
const columns: DataTableColumn[] = [
  { title: '序号', key: 'seq', width: 60, minWidth: 50, align: 'center', customRender: ({ index }: { index: number }) => index + 1 },
  { title: '维护内容', key: 'subject', width: 240, minWidth: 150, ellipsis: true, align: 'center' },
  { title: '时间', key: 'time', width: 150, minWidth: 120, align: 'center' },
  { title: '时长', key: 'duration', width: 88, minWidth: 76, align: 'center' },
  { title: '结论', key: 'state', width: 80, minWidth: 64, align: 'center' },
  { title: '平均分', key: 'overall', width: 92, minWidth: 80, align: 'center' },
  { title: '题量', key: 'correct', width: 104, minWidth: 88, align: 'center',
    customRender: ({ record }: { record: NightlyDay }) =>
      record.correct != null && record.total != null ? `${record.correct}/${record.total}` : '—' },
  { title: '基线', key: 'delta', width: 90, minWidth: 72, align: 'center' },
  { title: '评价', key: 'verdict', width: 220, minWidth: 160, flex: true, resizable: true, align: 'center' },
  { title: '操作', key: 'action', width: 140, minWidth: 120, align: 'center', fixed: 'right' },
]

const stateColor = (state: string) =>
  ({ running: 'processing', green: 'success', red: 'error', error: 'warning', corrupt: 'default' }[state] || 'default')
const stateLabel = (state: string) =>
  ({ running: '运行中', green: '通过', red: '回归', error: '失败', corrupt: '损坏' }[state] || state || '—')
const pct = (value?: number) => (value == null ? '—' : `${(value * 100).toFixed(2)}%`)
const deltaText = (day: NightlyDay) =>
  day.delta == null ? '—' : `${day.delta > 0 ? '+' : ''}${(day.delta * 100).toFixed(2)}`
const deltaClass = (day: NightlyDay) =>
  day.delta == null ? 'nightly-delta--flat' : day.delta > 0 ? 'nightly-delta--up' : day.delta < 0 ? 'nightly-delta--down' : 'nightly-delta--flat'

/** 北京时间、精确到分（generated_at 为 UTC ISO 串） */
const fmtTime = (iso?: string) => {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('zh-CN', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false,
  })
}

/** 时长（分钟）：开跑→收口（generated_at）；运行中行用当前时刻实时计算，随 15s 轮询走；
 *  历史条目缺 started_at 显示“—” */
const durationText = (day: NightlyDay) => {
  const startIso = day.started_at || (day.running ? day.generated_at : '')
  const endIso = day.running ? new Date().toISOString() : day.generated_at
  if (!startIso || !endIso) return '—'
  const start = new Date(startIso).getTime()
  const end = new Date(endIso).getTime()
  if (Number.isNaN(start) || Number.isNaN(end) || end < start) return '—'
  return `${Math.max(0, Math.round((end - start) / 60_000))} 分钟`
}

/** 老数据没有 verdict 字段时按状态兜底生成一句话（措辞与发布端 _verdict 同风格，面向普通读者） */
const fallbackVerdict = (day: NightlyDay) => {
  if (day.state === 'error' || day.state === 'corrupt') return '评测中断，未出结果'
  if (day.state === 'red') return '整体变差，需排查'
  if (day.delta != null && day.delta > 0.005) return '较基线提升，没有题目变差'
  if (day.delta != null && day.delta < -0.005) return '小幅回落，正常波动'
  return '与基线持平，没有变差'
}

const detailOf = (record: NightlyDay): NightlyDayDetailData | undefined => details.value[record.date]

const handleExpand = (expanded: boolean, record: Record<string, any>) => {
  if (expanded) loadDetail((record as NightlyDay).date)
}

const loadDetail = async (date: string) => {
  if (details.value[date]) return
  try {
    details.value[date] = await evalsApi.getNightlyDay(date)
  } catch (e) {
    details.value[date] = { nightly: { date, state: 'corrupt', note: String((e as Error).message || '读取失败') } }
  }
}

const fetchList = async () => {
  loading.value = true
  try {
    const res = await evalsApi.getNightlyList()
    days.value = (res as { days: NightlyDay[] }).days || []
  } catch (e) {
    console.error('[nightly] 列表加载失败', e)
    message.error('夜间维护记录加载失败')
  } finally {
    loading.value = false
  }
}

/** 停止运行中流水线；运行中行的「删除」同为此语义——不留痕、干净消失 */
const stopRunning = async () => {
  try {
    const r = await evalsApi.stopNightly() as { detail?: string }
    message.success(r?.detail || '已请求停止：当前题目完成后退出')
  } catch (e) {
    message.error(String((e as Error)?.message || '停止失败'))
  } finally {
    fetchList()
    loadRunState()
  }
}

/** 删除历史结论：后端连带删除对应评测 run（run 在跑会先停） */
const removeDay = async (record: NightlyDay) => {
  try {
    const r = await evalsApi.deleteNightlyDay(record.date) as { stopped_run?: boolean }
    message.success(r?.stopped_run ? '已停止运行中的评测，并删除该记录与对应 run' : '已删除该记录与对应评测 run')
  } catch (e) {
    message.error(String((e as Error)?.message || '删除失败'))
  } finally {
    fetchList()
    loadRunState()
  }
}

// ── 运行状态与手动触发（定时开关/时间编辑在 EvalManage 头部；配置存服务器 data/evals/nightly_settings.json）──
interface NightlySettingsRsp {
  enabled: boolean
  hour: number
  minute: number
  running?: boolean
  next_fire_at?: string | null
}
interface NightlyRunPlan {
  dataset?: { id: string; title: string; question_count?: number }
  answer_model?: string
  judge_models?: string[]
  concurrency?: number
  timeout_minutes?: number
  retry_rounds?: number
}

const running = ref(false)

const runModal = reactive({
  open: false,
  loading: false,
  launching: false,
  plan: null as NightlyRunPlan | null,
})

let runPollTimer: ReturnType<typeof setInterval> | undefined

/** 排程开关/时间编辑已上移到 EvalManage 头部，面板只关心「是否在跑」。
 *  状态翻转（调度器起跑/收口）时补刷一次列表让虚拟行及时出现/消失；轮询节奏由常驻心跳统一管理 */
const loadRunState = async () => {
  try {
    const s = await evalsApi.getNightlySettings() as NightlySettingsRsp
    const was = running.value
    running.value = !!s.running
    if (was !== running.value) fetchList()
  } catch {
    // 读取失败保持默认值展示，不打扰主列表
  }
}

/** 常驻心跳轮询（修复“页面早于调度器打开就永远看不到运行行”——旧逻辑只在加载时已
 *  running 才轮询）：固定 15s tick；运行中每 tick 全刷（虚拟行进度/时长实时），
 *  空闲每 4 tick（≈60s）刷一次状态与列表。面板随视图 v-if 挂载/卸载，定时器随组件收口 */
const IDLE_TICKS_PER_REFRESH = 4
let tickCount = 0
const tickPoll = async () => {
  tickCount += 1
  if (running.value || tickCount % IDLE_TICKS_PER_REFRESH === 0) {
    await loadRunState()
    fetchList()
  }
}
const startHeartbeat = () => {
  if (!runPollTimer) runPollTimer = setInterval(tickPoll, 15_000)
}
const stopHeartbeat = () => {
  if (runPollTimer) clearInterval(runPollTimer)
  runPollTimer = undefined
}

/** 供父组件头部「立即运行」按钮调用：打开执行计划确认框（计划/模型/并发先看清楚再起跑） */
const openRunModal = async () => {
  runModal.open = true
  runModal.loading = true
  try {
    runModal.plan = await evalsApi.getNightlyRunPlan() as NightlyRunPlan
  } catch {
    runModal.plan = null
  } finally {
    runModal.loading = false
  }
}

const confirmLaunch = async () => {
  runModal.launching = true
  try {
    const r = await evalsApi.runNightlyNow() as { ok: boolean; detail?: string }
    if (r.ok) {
      message.success('夜间流水线已启动：完成前本页将显示运行状态，结束后自动刷新结论并推企微通知')
      runModal.open = false
      running.value = true
      tickCount = 0 // 让下一个 15s tick 立即进入快轮
      // 立即拉一次出"启动中"种子行；起跑建档有几秒间隙，8s 后再补拉出真实进度
      fetchList()
      setTimeout(fetchList, 8_000)
    } else {
      message.warning(r.detail || '未能启动')
    }
  } catch (e) {
    message.error(String((e as Error)?.message || '启动失败'))
  } finally {
    runModal.launching = false
  }
}

onMounted(() => {
  fetchList()
  loadRunState()
  startHeartbeat()
})
onBeforeUnmount(stopHeartbeat)

defineExpose({ openRunModal })
</script>

<style scoped>
/* 宽度封顶/居中、外边距与滚动全部交给外层 .eval-nightly-wrap + .eval-nightly-content
   （与知识库日常维护的 .knowledge-stats/.stats-content 同构），此处再包一层会让表格比头部窄 */
.eval-nightly-panel {
  min-width: 0;
}
.nightly-help {
  margin-left: 4px;
  color: var(--text-secondary, rgba(0, 0, 0, 0.45));
}
.nightly-delta--up {
  color: #52c41a;
  font-weight: 600;
}
.nightly-delta--down {
  color: #ff4d4f;
  font-weight: 600;
}
.nightly-delta--flat {
  color: var(--text-secondary, rgba(0, 0, 0, 0.45));
}
</style>
