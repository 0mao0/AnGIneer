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
        :custom-row="rowProps"
        :row-class-name="(r: RunPayload) => (r.run_id === activeRunId ? 'epr-row--active' : '')"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'run_date'">
            {{ record.run_date || record.ts || '—' }}
          </template>
          <template v-else-if="column.key === 'run_id'">
            <span class="epr-mono">{{ record.run_id }}</span>
            <a-tag v-if="record.kind !== 'run'" color="orange" class="epr-tag">离线重投影</a-tag>
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
            <a-tag v-if="detail.run.kind !== 'run'" color="orange">离线重投影（非同一次 fresh 解析）</a-tag>
            <a-tag v-else color="green">fresh 解析</a-tag>
          </div>
          <p v-if="detail.run.note" class="epr-note">{{ detail.run.note }}</p>

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

          <!-- A① 三方表 -->
          <div class="epr-section">
            <h4>A① 官方 markdown 口径（三方）</h4>
            <table class="epr-table">
              <thead>
                <tr><th>指标</th><th>参考模型</th><th>MinerU 单独</th><th>我们全链</th></tr>
              </thead>
              <tbody>
                <tr v-for="key in OFFICIAL_ORDER" :key="key">
                  <td>{{ label(key) }}</td>
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

          <!-- A② 两方表 -->
          <div class="epr-section">
            <h4>A② 结构层口径（两方）</h4>
            <table class="epr-table">
              <thead>
                <tr><th>指标</th><th>MinerU 原生 content_list</th><th>我们全链</th></tr>
              </thead>
              <tbody>
                <tr v-for="key in STRUCT_ORDER" :key="key">
                  <td>{{ label(key) }}</td>
                  <td>{{ fmt(detail.run.metrics?.struct_mineru?.[key], true) }}</td>
                  <td class="epr-strong">{{ fmt(detail.run.metrics?.struct_chain?.[key], true) }}</td>
                </tr>
              </tbody>
            </table>
            <p class="epr-hint">
              MinerU 两列 TEDS / 公式相似度同分是已知事实：我们的 table_html 是 MinerU HTML 原文搬运，差异只在块切分。
            </p>
          </div>

          <!-- 逐类目 / 逐文档类型 -->
          <div v-if="detail.run.by_category?.length" class="epr-section">
            <h4>A② 逐类目（我们全链）</h4>
            <table class="epr-table">
              <thead>
                <tr><th>类目</th><th>GT 块</th><th>召回率</th><th>文本相似度(命中)</th><th>表格 TEDS</th></tr>
              </thead>
              <tbody>
                <tr v-for="c in detail.run.by_category" :key="c.category">
                  <td>{{ c.category }}</td>
                  <td>{{ c.gt_blocks }}</td>
                  <td>{{ pct(c.recall) }}</td>
                  <td>{{ dec(c.text_similarity_matched) }}</td>
                  <td>{{ dec(c.teds) }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div v-if="detail.run.by_data_source?.length" class="epr-section">
            <h4>A② 逐文档类型</h4>
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

          <a-collapse class="epr-collapse">
            <a-collapse-panel v-if="detail.summary_md" key="summary" header="summary.md（本机生成的完整留档）">
              <div class="epr-md" v-html="summaryHtml" />
            </a-collapse-panel>
            <a-collapse-panel v-if="detail.struct_report_md" key="report" header="A② 结构层报告（逐类目明细）">
              <div class="epr-md" v-html="structReportHtml" />
            </a-collapse-panel>
          </a-collapse>
        </div>
      </a-spin>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { App } from 'ant-design-vue'
import { ReloadOutlined } from '@ant-design/icons-vue'
import { renderMarkdownToHtml } from '@angineer/aichat-ui/utils/markdown'
import evalsApi from '../../api/evals'

defineOptions({ name: 'EvalParseRegressionPanel' })

interface MetricMeta { label: string; higher_is_better: boolean; ratio: boolean }
interface DeltaRow { metric: string; label: string; cur: number | null; base: number | null; delta: number | null; higher_is_better: boolean }
interface CategoryRow {
  category: string; gt_blocks: number; recall: number | null
  text_similarity_matched: number | null; teds: number | null
}
interface SourceRow {
  data_source: string; pages: number; block_recall: number | null
  text_similarity: number | null; teds: number | null; order_adjacent_accuracy: number | null
}
interface RunPayload {
  schema?: number
  run_id: string
  ts?: string
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

// 第二参为源文件路径（用于解析相对图片链接）：归档里的报告没有本地相对资源，给空串
const summaryHtml = computed(() => renderMarkdownToHtml(detail.value?.summary_md || '', ''))
const structReportHtml = computed(() => renderMarkdownToHtml(detail.value?.struct_report_md || '', ''))

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
  } catch (e: any) {
    message.error(`加载 ${runId} 详情失败：${e?.message || e}`)
  } finally {
    detailLoading.value = false
  }
}

onMounted(loadRuns)
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
.epr-collapse {
  margin-top: 16px;
}
.epr-md {
  font-size: 12px;
  line-height: 1.7;
  overflow-x: auto;
}
.epr-md :deep(table) {
  width: 100%;
  border-collapse: collapse;
}
.epr-md :deep(th),
.epr-md :deep(td) {
  padding: 4px 8px;
  border: 1px solid var(--border-color, #f0f0f0);
}
.epr-row--active {
  background: var(--table-row-active-bg, rgba(22, 119, 255, 0.06));
}
</style>
