<template>
  <!-- 解析回归（A 层）看板：只读展示本机跑完 --publish 上来的结论（数据源 data/evals/parse_regression/） -->
  <div class="eval-parse-regression">
    <div class="epr-inner">
      <!-- 用户要求明确写清：这是本机业务，线上点不了「开始跑」 -->
      <a-alert type="info" show-icon class="epr-notice">
        <template #message>
          本机（开发机）跑出来的结果——本页只读，线上不能触发运行
        </template>
        <template #description>
          <p class="epr-notice__p">
            A① 官方口径要 18GB OmniDocBench 评测镜像，镜像<b>只装在开发机</b>（部署机磁盘装不下，见 AGENTS.md），
            所以解析回归始终在开发机执行；本页展示的是开发机跑完同步上来的结论，服务器不跑评测、也不建索引。
          </p>
          <p class="epr-notice__p">
            跑一次（约 50 分钟 / 200 页，含 predict + A② + A①）并同步到本页：
          </p>
          <code class="epr-cmd">python scripts/run_parse_regression.py --limit 200 --seed 42 --publish {{ publishDestHint }}</code>
        </template>
      </a-alert>

      <div class="epr-toolbar">
        <span class="epr-toolbar__title">解析回归记录</span>
        <span class="epr-toolbar__hint">
          口径定义见 docs/parse-struct-eval.md（A 层）；A① 官方 markdown 三方表、A② 结构层两方表、Δ 与基线对比
        </span>
        <a-button size="small" :loading="loading" @click="loadRuns">
          <template #icon><ReloadOutlined /></template>
          刷新
        </a-button>
      </div>

      <a-alert
        v-if="!loading && !rootExists"
        type="warning"
        show-icon
        message="看板目录还不存在"
        description="服务器 data/evals/parse_regression/ 还没有内容：先在开发机跑一次带 --publish 的解析回归。"
        class="epr-empty-hint"
      />

      <a-table
        v-else
        :columns="columns"
        :data-source="runs"
        row-key="run_id"
        size="small"
        :loading="loading"
        :pagination="false"
        :scroll="{ x: 1180 }"
        :custom-row="rowProps"
        :row-class-name="(r: RunPayload) => (r.run_id === activeRunId ? 'epr-row--active' : '')"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'run_date'">
            {{ runDateText(record) }}
          </template>
          <template v-else-if="column.key === 'run_id'">
            <span class="epr-mono">{{ record.run_id }}</span>
            <!-- 没同步上来的目录不等于离线重投影：分别标清（pending=本机在跑或没 --publish） -->
            <a-tooltip v-if="record.state === 'pending'" title="本机这轮还没跑完或没带 --publish：结论层文件还没同步上来">
              <a-tag class="epr-tag">未同步</a-tag>
            </a-tooltip>
            <a-tooltip v-else-if="record.state === 'corrupt'" title="publish.json 读不出来（同步中断或写坏）">
              <a-tag color="red" class="epr-tag">损坏</a-tag>
            </a-tooltip>
            <a-tag v-else-if="record.kind !== 'run'" color="orange" class="epr-tag">离线重投影</a-tag>
          </template>
          <template v-else-if="column.key === 'git'">
            <span class="epr-mono">{{ record.git || '—' }}</span>
          </template>
          <template v-else-if="column.key === 'sample'">
            {{ record.limit ?? '—' }} 页 / seed {{ record.seed ?? '—' }}
          </template>
          <template v-else-if="column.key === 'pages'">
            {{ record.pages_scored ?? '—' }}
            <span v-if="record.pages_official != null && record.pages_official !== record.pages_scored" class="epr-dim">
              （A① {{ record.pages_official }}）
            </span>
          </template>
          <template v-else-if="column.key === 'timing'">
            {{ timingText(record) }}
          </template>
          <template v-else-if="column.key === 'delta'">
            <span :class="deltaSummaryClass(record)">{{ deltaSummary(record) }}</span>
          </template>
          <template v-else-if="column.key === 'skipped'">
            <a-tooltip v-if="record.skipped?.length" :title="record.skipped.join('；')">
              <a-tag color="gold">{{ record.skipped.length }} 项</a-tag>
            </a-tooltip>
            <span v-else>—</span>
          </template>
        </template>
      </a-table>

      <a-spin :spinning="detailLoading">
        <div v-if="detail" class="epr-detail">
          <div class="epr-detail__head">
            <h3>{{ detail.run.run_id }}</h3>
            <a-tag v-if="detail.run.state === 'pending'" color="default">未同步（本机还在跑或没 --publish）</a-tag>
            <a-tag v-else-if="detail.run.state === 'corrupt'" color="red">结论文件损坏</a-tag>
            <a-tag v-else-if="detail.run.kind !== 'run'" color="orange">离线重投影（非同一次 fresh 解析）</a-tag>
            <a-tag v-else color="green">fresh 解析</a-tag>
          </div>
          <p v-if="detail.run.note" class="epr-note">{{ detail.run.note }}</p>
          <a-alert
            v-if="detail.run.state === 'pending'"
            type="info"
            show-icon
            message="本轮结论还没同步上来"
            description="本机这轮可能还在跑（predict 约 45 分钟），或跑完时没带 --publish。同步后可点「刷新」重新加载。"
            class="epr-delta-note"
          />
          <a-alert
            v-else-if="detail.run.state === 'corrupt'"
            type="error"
            show-icon
            message="结论文件损坏"
            description="publish.json 读不出来（同步中断或写坏了）：在本机对该 run 跑 --republish 重建后再同步一次。"
            class="epr-delta-note"
          />

          <a-descriptions size="small" bordered :column="3" class="epr-desc">
            <a-descriptions-item label="代码版本">{{ detail.run.git || '—' }}</a-descriptions-item>
            <a-descriptions-item label="抽样">{{ detail.run.limit ?? '—' }} 页 / seed {{ detail.run.seed ?? '—' }}</a-descriptions-item>
            <a-descriptions-item label="评分页">{{ detail.run.pages_scored ?? '—' }}</a-descriptions-item>
            <a-descriptions-item label="页集合 hash">{{ detail.run.page_ids_hash || '—' }}</a-descriptions-item>
            <a-descriptions-item label="MinerU 版本">{{ detail.run.mineru_version || '—' }}</a-descriptions-item>
            <a-descriptions-item label="耗时">{{ timingText(detail.run) }}</a-descriptions-item>
            <a-descriptions-item label="阶段" :span="2">{{ detail.run.stages || '—' }}</a-descriptions-item>
            <a-descriptions-item label="评测镜像">{{ (detail.run.eval_image || '').split('/').pop() || '—' }}</a-descriptions-item>
          </a-descriptions>

          <div v-if="detail.run.skipped?.length" class="epr-skipped">
            <b>跳过/失败项</b>
            <ul><li v-for="s in detail.run.skipped" :key="s">{{ s }}</li></ul>
          </div>

          <!-- Δ 段 -->
          <div class="epr-section">
            <h4>Δ vs 基线 {{ detail.run.delta?.baseline_id || '—' }}</h4>
            <template v-if="detail.run.delta?.gate !== 'ok'">
              <a-alert type="warning" show-icon :message="detail.run.delta?.reason || '本次不出 Δ'" />
            </template>
            <template v-else>
              <a-alert
                v-if="detail.run.delta?.note"
                type="warning"
                show-icon
                :message="detail.run.delta.note"
                class="epr-delta-note"
              />
              <table class="epr-table">
                <thead>
                  <tr><th>口径</th><th>指标</th><th>本次</th><th>基线</th><th>Δ</th></tr>
                </thead>
                <tbody>
                  <tr v-for="row in deltaRows" :key="row.group + row.metric">
                    <td>{{ row.groupLabel }}</td>
                    <td>{{ row.label }}</td>
                    <td>{{ fmt(row.cur, row.higher_is_better) }}</td>
                    <td>{{ fmt(row.base, row.higher_is_better) }}</td>
                    <td :class="row.worse ? 'epr-bad' : (row.delta ? 'epr-good' : '')">{{ row.text }}</td>
                  </tr>
                </tbody>
              </table>
            </template>
          </div>

          <!-- A① 三方表（柱状图 + 精确数值表） -->
          <div class="epr-section">
            <h4>A① 官方 markdown 口径（三方）</h4>
            <div ref="officialChartEl" class="epr-chart" style="height: 300px" />
            <p class="epr-caption">
              <b>颜色＝来源</b>（见上方图例：参考模型蓝 / MinerU 青 / 我们绿），每组自上而下顺序固定：
              参考模型 → MinerU 单独 → 我们全链；条形长度＝实际数值（横轴 0–1）。
              <b>该指标最优的那条加 ★ 并加粗</b>。指标名后的 ↑/↓ 是方向：<b>↑ 越大越好，↓ 越小越好</b>
              ——Edit_dist 类越小越好，所以条形越短越好（它们的值本就只有 0.03–0.14，条形短是正常的，看 ★ 与数值标签）。
            </p>
            <table class="epr-table">
              <thead>
                <tr><th>指标</th><th>方向</th><th>参考模型</th><th>MinerU 单独</th><th>我们全链</th></tr>
              </thead>
              <tbody>
                <tr v-for="key in OFFICIAL_ORDER" :key="key">
                  <td>{{ label(key) }}</td>
                  <td>{{ directionText(key) }}</td>
                  <td>{{ fmt(detail.run.metrics?.official_ref?.[key], higher(key)) }}</td>
                  <td>{{ fmt(detail.run.metrics?.official_mineru?.[key], higher(key)) }}</td>
                  <td class="epr-strong">{{ fmt(detail.run.metrics?.official?.[key], higher(key)) }}</td>
                </tr>
              </tbody>
            </table>
            <p class="epr-hint">
              参考模型 / MinerU 两列是固定基线（不随本次 run 变）；"表格内文字 Edit_dist" 这类差异主要来自投影方式，别当质量绝对值读。
            </p>
          </div>

          <!-- A② 两方表（柱状图 + 精确数值表） -->
          <div class="epr-section">
            <h4>A② 结构层口径（两方）</h4>
            <div ref="structChartEl" class="epr-chart" style="height: 320px" />
            <p class="epr-caption">
              <b>颜色＝来源</b>（MinerU 青 / 我们绿），每组自上而下依次：
              MinerU 原生 content_list → 我们全链；最优那条加 ★。
              本表 8 项<b>全部是 ↑ 越大越好</b>（含"预测块被解释率"：它低说明多出来的块没被 GT 覆盖）。
            </p>
            <table class="epr-table">
              <thead>
                <tr><th>指标</th><th>方向</th><th>MinerU 原生 content_list</th><th>我们全链</th></tr>
              </thead>
              <tbody>
                <tr v-for="key in STRUCT_ORDER" :key="key">
                  <td>{{ label(key) }}</td>
                  <td>{{ directionText(key) }}</td>
                  <td>{{ fmt(detail.run.metrics?.struct_mineru?.[key], true) }}</td>
                  <td class="epr-strong">{{ fmt(detail.run.metrics?.struct_chain?.[key], true) }}</td>
                </tr>
              </tbody>
            </table>
            <p class="epr-hint">
              MinerU 两列 TEDS / 公式相似度同分是已知事实：我们的 table_html 是 MinerU HTML 原文搬运，差异只在块切分。
            </p>
          </div>

          <!-- 逐类目 / 逐文档类型（柱状图：按召回率排序，一眼看出哪类没做好） -->
          <div v-if="detail.run.by_category?.length" class="epr-section">
            <h4>A② 逐类目 · 块召回率（我们全链）</h4>
            <div ref="categoryChartEl" class="epr-chart" style="height: 380px" />
            <p class="epr-caption">
              <b>越大越好</b>：条形越长越好（颜色＝我们全链，与其他图一致）；已按召回率降序，最差的在下面，
              虚线是<b>本图平均值</b>——低于虚线的就是拖后腿的类目。
            </p>
            <table class="epr-table">
              <thead>
                <tr>
                  <th>类目</th><th>GT 块</th><th>命中</th><th>召回率</th>
                  <th>文本相似度(命中)</th><th>样本 n</th><th>表格 TEDS</th><th>公式相似度</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="c in detail.run.by_category" :key="c.category">
                  <td>{{ c.category }}</td>
                  <td>{{ c.gt_blocks }}</td>
                  <td>{{ c.matched }}</td>
                  <td>{{ pct(c.recall) }}</td>
                  <td>{{ dec(c.text_similarity_matched) }}</td>
                  <td>{{ c.text_n_matched || '—' }}</td>
                  <td>{{ dec(c.teds) }}</td>
                  <td>{{ dec(c.formula_similarity) }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div v-if="detail.run.by_data_source?.length" class="epr-section">
            <h4>A② 逐文档类型 · 块召回率</h4>
            <div ref="sourceChartEl" class="epr-chart" style="height: 300px" />
            <p class="epr-caption"><b>越大越好</b>；同样按召回率降序，虚线为本图平均值。</p>
            <table class="epr-table">
              <thead>
                <tr><th>data_source</th><th>页数</th><th>召回率</th><th>文本相似度</th><th>表格 TEDS</th><th>顺序相邻对</th></tr>
              </thead>
              <tbody>
                <tr v-for="s in detail.run.by_data_source" :key="s.data_source">
                  <td>{{ s.data_source }}</td>
                  <td>{{ s.pages }}</td>
                  <td>{{ pct(s.block_recall) }}</td>
                  <td>{{ dec(s.text_similarity) }}</td>
                  <td>{{ dec(s.teds) }}</td>
                  <td>{{ pct(s.order_adjacent_accuracy) }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- 不再内嵌 summary.md / 结构层报告：两份归档文件的每一项上面都已原生渲染
               （逐类目的样本数 n 与公式相似度列已补进表格）。文件本身照旧生成并 publish，
               在服务器归档目录里可直接读——这里只是不再重复渲染一遍。 -->
          <p class="epr-hint epr-files">
            归档原文（本页即其渲染）：<code>summary.md</code> —— 环境、A① 三方表、A② 两方表、Δ 与跳过项；
            <code>struct_chain_report.md</code> —— A② 逐类目/逐文档类型明细。
            两份都在归档目录里，同步到服务器后可直接打开。
          </p>
        </div>
      </a-spin>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { App } from 'ant-design-vue'
import { ReloadOutlined } from '@ant-design/icons-vue'
import * as echarts from 'echarts'
import evalsApi from '../../api/evals'

defineOptions({ name: 'EvalParseRegressionPanel' })

interface MetricMeta { label: string; higher_is_better: boolean; ratio: boolean }
interface DeltaRow { metric: string; label: string; cur: number | null; base: number | null; delta: number | null; higher_is_better: boolean }
interface CategoryRow {
  // 字段照 evals_core 的 by_category 全量给（样本数 n 与公式相似度原先只在结构层报告里，
  // 现在表格直接展示，所以折叠报告可以去掉）
  category: string; gt_blocks: number; matched?: number
  recall: number | null; text_similarity?: number | null; text_n?: number
  text_similarity_matched: number | null; text_n_matched?: number
  teds: number | null; teds_n?: number; formula_similarity?: number | null
}
interface SourceRow {
  data_source: string; pages: number; block_recall: number | null
  text_similarity: number | null; teds: number | null; order_adjacent_accuracy: number | null
}
interface RunPayload {
  schema?: number
  run_id: string
  ts?: string
  run_date?: string
  kind?: string
  note?: string
  limit?: number | null
  seed?: number | null
  pages_scored?: number | null
  pages_official?: number | null
  page_ids_hash?: string
  git?: string
  branch?: string
  mineru_version?: string
  stages?: string
  timing?: Record<string, number>
  skipped?: string[]
  eval_image?: string
  metrics?: Record<string, Record<string, number | null>>
  metric_meta?: Record<string, MetricMeta>
  delta?: {
    gate?: string; reason?: string; note?: string; baseline_id?: string
    groups?: Record<string, DeltaRow[]>
  }
  by_category?: CategoryRow[]
  by_data_source?: SourceRow[]
  state?: string
}
interface RunDetail {
  run: RunPayload
  summary_md: string
  struct_report_md: string
}

/** 表格里的固定指标顺序（照 docs/parse-struct-eval.md 的登记顺序） */
const OFFICIAL_ORDER = ['text_edit', 'table_teds', 'table_teds_struct', 'table_edit', 'formula_edit', 'formula_cdm', 'order_edit']
const STRUCT_ORDER = ['block_recall', 'pred_used_ratio', 'text_similarity_matched', 'text_similarity',
  'teds', 'formula_similarity', 'order_adjacent_accuracy', 'order_kendall_tau']
const GROUP_LABELS: Record<string, string> = { official: 'A①', struct_chain: 'A②' }

const { message } = App.useApp()
const runs = ref<RunPayload[]>([])
const rootExists = ref(true)
const loading = ref(false)
const detailLoading = ref(false)
const detail = ref<RunDetail | null>(null)
const activeRunId = ref('')

const publishDestHint = 'root@<部署机>:/home/runner/AnGIneer/data/evals/parse_regression'

const columns = [
  { title: '日期', key: 'run_date', width: 110 },
  { title: 'run', key: 'run_id', width: 230 },
  { title: '代码版本', key: 'git', width: 190 },
  { title: '抽样', key: 'sample', width: 140 },
  { title: '评分页', key: 'pages', width: 120 },
  { title: '耗时', key: 'timing', width: 190 },
  { title: 'Δ / 首次', key: 'delta', width: 190 },
  { title: '跳过', key: 'skipped', width: 80 }
]


const deltaRows = computed(() => {
  const groups = detail.value?.run?.delta?.groups || {}
  const out: Array<DeltaRow & { group: string; groupLabel: string; text: string; worse: boolean }> = []
  for (const group of ['official', 'struct_chain']) {
    for (const row of groups[group] || []) {
      out.push({ ...row, group, groupLabel: GROUP_LABELS[group] || group, ...deltaCell(row) })
    }
  }
  return out
})

function meta(key: string): MetricMeta {
  return detail.value?.run?.metric_meta?.[key] || { label: key, higher_is_better: true, ratio: true }
}
function label(key: string): string {
  return meta(key).label
}
function higher(key: string): boolean {
  return meta(key).higher_is_better
}
/** 0–1 的指标按百分比显示（表格里 0.0724 → 7.24%，与 summary.md 的表格口径一致） */
function fmt(value: number | null | undefined, asPct?: boolean): string {
  if (value == null) return '—'
  return asPct === false ? value.toFixed(4) : `${(value * 100).toFixed(2)}%`
}
function pct(value: number | null | undefined): string {
  return value == null ? '—' : `${(value * 100).toFixed(1)}%`
}
function dec(value: number | null | undefined): string {
  return value == null ? '—' : value.toFixed(4)
}

/** Δ 单元格：带符号数值 + 数值方向箭头；方向变差标红（判定按指标语义，不按箭头猜） */
function deltaCell(row: DeltaRow): { text: string; worse: boolean } {
  if (row.delta == null) return { text: '—', worse: false }
  if (row.delta === 0) return { text: '0', worse: false }
  const body = row.cur != null && Math.abs(row.cur) <= 1
    ? `${row.delta > 0 ? '+' : ''}${(row.delta * 100).toFixed(2)}pp`
    : `${row.delta > 0 ? '+' : ''}${row.delta.toFixed(4)}`
  const arrow = row.delta > 0 ? '↑' : '↓'
  const worse = (row.delta > 0) !== row.higher_is_better
  return { text: `${body} ${arrow}${worse ? ' ⚠' : ''}`, worse }
}

/** 日期列：run_date → ts → run_id 里的 YYYYMMDD（未同步的目录只有目录名，别显示成"—"） */
function runDateText(run: RunPayload): string {
  for (const raw of [run.run_date, run.ts, run.run_id]) {
    const m = /(\d{4})-?(\d{2})-?(\d{2})/.exec(String(raw || ''))
    if (m) return `${m[1]}-${m[2]}-${m[3]}`
  }
  return '—'
}

function timingText(run: RunPayload): string {
  const t = run.timing || {}
  const parts = Object.entries(t).map(([k, v]) => `${k} ${Math.round(Number(v))}s`)
  return parts.length ? parts.join(' / ') : '—'
}
function deltaSummary(run: RunPayload): string {
  const d = run.delta
  if (!d) return '—'
  if (d.gate !== 'ok') return '首次跑（本次即基线）'
  const rows = (d.groups?.official || []).filter((r) => r.delta != null)
  if (!rows.length) return `vs ${d.baseline_id || '基线'}`
  const worst = rows.reduce((a, b) => (Math.abs(b.delta || 0) > Math.abs(a.delta || 0) ? b : a), rows[0])
  const d0 = worst.delta as number
  return `vs ${d.baseline_id}: ${worst.label} ${d0 > 0 ? '+' : ''}${(d0 * 100).toFixed(2)}pp`
}
function deltaSummaryClass(run: RunPayload): string {
  const d = run.delta
  if (!d || d.gate !== 'ok') return 'epr-dim'
  // 离线重投影产物（入档模式）不标红：那行的 Δ 是换量尺的差，不是回归（行上已有橙色标记）
  if (run.kind !== 'run') return 'epr-dim'
  const bad = (d.groups?.official || []).some((r) => r.delta != null && r.delta !== 0 && (r.delta > 0) !== r.higher_is_better)
  return bad ? 'epr-bad' : 'epr-good'
}

function rowProps(record: RunPayload) {
  return {
    onClick: () => loadDetail(record.run_id),
    style: { cursor: 'pointer' }
  }
}

async function loadRuns() {
  loading.value = true
  try {
    const res: any = await evalsApi.getParseRegressionRuns()
    const data = res?.data ?? res
    runs.value = data?.runs || []
    rootExists.value = data?.root_exists !== false
  } catch (e: any) {
    message.error(`加载解析回归记录失败：${e?.message || e}`)
  } finally {
    loading.value = false
  }
}

async function loadDetail(runId: string) {
  activeRunId.value = runId
  detailLoading.value = true
  try {
    const res: any = await evalsApi.getParseRegressionRun(runId)
    detail.value = (res?.data ?? res) as RunDetail
    await nextTick()
    renderCharts()
  } catch (e: any) {
    message.error(`加载 ${runId} 详情失败：${e?.message || e}`)
  } finally {
    detailLoading.value = false
  }
}

// ── 柱状图（echarts，沿用 NightlyDayDetail 的 init/setOption/resize/dispose 惯例）──
// ── 配色按"来源（系列）"分，不按好坏分：颜色只回答"这是谁"，好坏靠 ★ + ↑/↓ + 数值 ──
// （第一版按好坏着色导致图例自相矛盾：绿既是最优又是某个系列；用户要求按来源分色）
const SERIES_COLORS: Record<string, string> = {
  参考模型: '#1677ff',
  'MinerU 单独': '#13c2c2',
  'MinerU 原生': '#13c2c2',
  我们全链: '#52c41a',
}
const OURS_COLOR = '#52c41a'
const seriesColor = (name: string) => SERIES_COLORS[name] || '#8c8c8c'

const officialChartEl = ref<HTMLElement | null>(null)
const structChartEl = ref<HTMLElement | null>(null)
const categoryChartEl = ref<HTMLElement | null>(null)
const sourceChartEl = ref<HTMLElement | null>(null)
const charts: echarts.ECharts[] = []

function chartAt(el: HTMLElement | null, index: number): echarts.ECharts | null {
  if (!el) return null
  if (!charts[index]) charts[index] = echarts.init(el)
  return charts[index]
}

/** 方向文案：所有指标都必须标清"越大/越小越好"，避免 Edit_dist 类被读反 */
function directionText(key: string): string {
  return higher(key) ? '↑ 越大越好' : '↓ 越小越好'
}

/** 该组里最优的那个值（按方向判定），用于给最优条加 ★ */
function bestIndexOfRow(values: Array<number | null | undefined>, higherIsBetter: boolean): number {
  let best = -1
  values.forEach((v, i) => {
    if (typeof v !== 'number') return
    if (best === -1) { best = i; return }
    const cur = values[best] as number
    if (higherIsBetter ? v > cur : v < cur) best = i
  })
  return best
}

/** 单指标横排分组柱：颜色=来源（配图例），最优条加 ★，方向在指标名后缀 ↑/↓ */
function groupedBarOption(
  keys: string[],
  seriesList: Array<{ name: string; values: Array<number | null> }>,
  valueText: (key: string, value: number | null) => string,
): echarts.EChartsOption {
  const labelOf = (k: string, v: number | null): string => {
    const text = valueText(k, v)
    return text
  }
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: any) => {
        const list = Array.isArray(params) ? params : [params]
        return [list[0]?.name, ...list.map((p: any) => `${p.marker}${p.seriesName}：${p.value == null ? '—' : p.value}`)].join('<br/>')
      },
    },
    legend: { top: 0, itemWidth: 12, itemHeight: 8, textStyle: { fontSize: 11, color: '#999' } },
    grid: { left: 8, right: 84, top: 26, bottom: 4, containLabel: true },
    xAxis: { type: 'value', max: 1, axisLabel: { show: false }, splitLine: { show: false }, axisLine: { show: false }, axisTick: { show: false } },
    yAxis: {
      type: 'category',
      inverse: true,
      data: keys.map((k) => `${label(k)} ${higher(k) ? '↑' : '↓'}`),
      axisLabel: { fontSize: 11, color: '#999' },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    series: seriesList.map((s) => ({
      name: s.name,
      type: 'bar' as const,
      barWidth: 11,
      itemStyle: { color: seriesColor(s.name), borderRadius: [0, 5, 5, 0] },
      data: s.values.map((v, i) => {
        const bestIndex = bestIndexOfRow(seriesList.map((x) => x.values[i]), higher(keys[i]))
        const isBest = seriesList.indexOf(s) === bestIndex
        return {
          value: v,
          label: {
            show: true,
            position: 'right' as const,
            fontSize: 10,
            color: isBest ? '#52c41a' : '#999',
            fontWeight: isBest ? ('bold' as const) : ('normal' as const),
            formatter: () => (isBest ? `${labelOf(keys[i], v)} ★` : labelOf(keys[i], v)),
          },
        }
      }),
    })),
  }
}

/** 单序列横排柱（逐类目/逐文档类型，只有"我们全链"一个来源）：
 *  颜色统一用我们的系列色（与其他图一致）；好坏靠降序 + 平均值虚线读，
 *  不按数值着色（那会与"颜色=来源"的约定打架，且阈值是拍的）。 */
function singleBarOption(items: Array<{ name: string; value: number | null }>, unit: (v: number | null) => string): echarts.EChartsOption {
  const valid = items.filter((x) => typeof x.value === 'number') as Array<{ name: string; value: number }>
  const max = Math.max(...valid.map((x) => x.value), 0)
  const avg = valid.length ? valid.reduce((sum, x) => sum + x.value, 0) / valid.length : 0
  return {
    tooltip: { trigger: 'item', formatter: (p: any) => `${p.name}：${p.value == null ? '—' : p.value}` },
    grid: { left: 8, right: 96, top: 6, bottom: 4, containLabel: true },
    xAxis: { type: 'value', min: 0, max: max || 1, axisLabel: { show: false }, splitLine: { show: false }, axisLine: { show: false }, axisTick: { show: false } },
    yAxis: {
      type: 'category',
      inverse: true,
      data: items.map((x) => x.name),
      axisLabel: { fontSize: 11, color: '#999' },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    series: [{
      name: '我们全链',
      type: 'bar',
      barWidth: 12,
      itemStyle: { color: OURS_COLOR, borderRadius: [0, 6, 6, 0] },
      data: items.map((x) => ({
        value: x.value,
        label: { show: true, position: 'right' as const, fontSize: 10, color: '#999', formatter: () => unit(x.value) },
      })),
      markLine: {
        silent: true,
        symbol: 'none',
        lineStyle: { type: 'dashed' as const, color: '#8c8c8c', width: 1 },
        label: {
          position: 'end' as const,
          fontSize: 10,
          color: '#8c8c8c',
          formatter: () => `平均 ${unit(avg)}`,
        },
        data: [{ xAxis: avg }],
      },
    }],
  }
}

function renderCharts(): void {
  const run = detail.value?.run
  if (!run?.metrics) return
  const m = run.metrics

  const official = chartAt(officialChartEl.value, 0)
  official?.setOption(groupedBarOption(
    OFFICIAL_ORDER,
    [
      { name: '参考模型', values: OFFICIAL_ORDER.map((k) => m.official_ref?.[k] ?? null) },
      { name: 'MinerU 单独', values: OFFICIAL_ORDER.map((k) => m.official_mineru?.[k] ?? null) },
      { name: '我们全链', values: OFFICIAL_ORDER.map((k) => m.official?.[k] ?? null) },
    ],
    (k, v) => fmt(v, higher(k)),
  ), true)

  const struct = chartAt(structChartEl.value, 1)
  struct?.setOption(groupedBarOption(
    STRUCT_ORDER,
    [
      { name: 'MinerU 原生', values: STRUCT_ORDER.map((k) => m.struct_mineru?.[k] ?? null) },
      { name: '我们全链', values: STRUCT_ORDER.map((k) => m.struct_chain?.[k] ?? null) },
    ],
    (_k, v) => fmt(v, true),
  ), true)

  const cats = (run.by_category || [])
    .filter((c) => typeof c.recall === 'number')
    .sort((a, b) => (b.recall as number) - (a.recall as number))
  chartAt(categoryChartEl.value, 2)?.setOption(
    singleBarOption(cats.map((c) => ({ name: c.category, value: c.recall })), (v) => pct(v)), true)

  const srcs = (run.by_data_source || [])
    .filter((s) => typeof s.block_recall === 'number')
    .sort((a, b) => (b.block_recall as number) - (a.block_recall as number))
  chartAt(sourceChartEl.value, 3)?.setOption(
    singleBarOption(srcs.map((s) => ({ name: s.data_source, value: s.block_recall })), (v) => pct(v)), true)
}

const handleResize = () => charts.forEach((c) => c.resize())

onMounted(async () => {
  await loadRuns()
  window.addEventListener('resize', handleResize)
})
watch(detail, async () => {
  await nextTick()
  renderCharts()
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  charts.forEach((c) => c.dispose())
  charts.length = 0
})
</script>

<style scoped>
.eval-parse-regression {
  height: 100%;
  overflow: auto;
  background: var(--page-bg, var(--bg-color, transparent));
}
.epr-inner {
  padding: 16px 20px 32px;
}
.epr-notice {
  margin-bottom: 14px;
}
.epr-notice__p {
  margin: 0 0 6px;
  line-height: 1.6;
}
.epr-cmd {
  display: block;
  padding: 6px 10px;
  margin-top: 4px;
  border-radius: 6px;
  background: var(--code-bg, rgba(0, 0, 0, 0.04));
  font-family: Consolas, Monaco, monospace;
  font-size: 12px;
  word-break: break-all;
}
.epr-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}
.epr-toolbar__title {
  font-weight: 600;
  font-size: 14px;
}
.epr-toolbar__hint {
  flex: 1;
  color: var(--text-color-secondary, #8c8c8c);
  font-size: 12px;
}
.epr-empty-hint {
  margin-bottom: 12px;
}
.epr-mono {
  font-family: Consolas, Monaco, monospace;
  font-size: 12px;
}
.epr-tag {
  margin-left: 6px;
}
.epr-dim {
  color: var(--text-color-secondary, #8c8c8c);
}
.epr-good {
  color: #389e0d;
}
.epr-bad {
  color: #cf1322;
}
.epr-strong {
  font-weight: 600;
}
.epr-detail {
  margin-top: 16px;
  padding: 14px 16px;
  border: 1px solid var(--border-color, #f0f0f0);
  border-radius: 8px;
  background: var(--panel-bg, #fff);
  overflow-x: auto;   /* 窄窗口下宽表横向滚动，不压缩成逐字换行 */
}
.epr-table {
  min-width: 560px;
}
.epr-detail__head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.epr-detail__head h3 {
  margin: 0;
  font-size: 15px;
}
.epr-note {
  margin: 6px 0 10px;
  color: var(--text-color-secondary, #8c8c8c);
  font-size: 12px;
  line-height: 1.6;
}
.epr-desc {
  margin-bottom: 8px;
}
.epr-skipped {
  margin: 8px 0;
  padding: 8px 10px;
  border-radius: 6px;
  background: var(--warn-bg, rgba(250, 173, 20, 0.08));
  font-size: 12px;
}
.epr-skipped ul {
  margin: 4px 0 0;
  padding-left: 18px;
}
.epr-section {
  margin-top: 16px;
}
.epr-section h4 {
  margin: 0 0 8px;
  font-size: 13px;
  font-weight: 600;
}
.epr-delta-note {
  margin-bottom: 8px;
}
.epr-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.epr-table th,
.epr-table td {
  padding: 5px 8px;
  border: 1px solid var(--border-color, #f0f0f0);
  text-align: left;
}
.epr-table th {
  background: var(--table-head-bg, rgba(0, 0, 0, 0.02));
  font-weight: 600;
}
.epr-hint {
  margin: 6px 0 0;
  color: var(--text-color-secondary, #8c8c8c);
  font-size: 12px;
  line-height: 1.6;
}
.epr-chart {
  width: 100%;
  min-width: 520px;
  margin-top: 6px;
}
.epr-caption {
  margin: 6px 0 10px;
  color: var(--text-color-secondary, #8c8c8c);
  font-size: 12px;
  line-height: 1.6;
}
.epr-files {
  margin-top: 16px;
  padding-top: 10px;
  border-top: 1px dashed var(--border-color, #f0f0f0);
}
.epr-files code {
  padding: 1px 4px;
  border-radius: 4px;
  background: var(--code-bg, rgba(0, 0, 0, 0.04));
  font-size: 11px;
}
.epr-row--active {
  background: var(--table-row-active-bg, rgba(22, 119, 255, 0.06));
}
</style>
