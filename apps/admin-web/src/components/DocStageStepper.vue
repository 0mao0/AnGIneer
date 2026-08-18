<template>
  <div class="doc-stage-stepper">
    <a-collapse>
      <!-- 八个解析阶段按顺序展示 -->
      <a-collapse-panel
        v-for="stage in orderedStages"
        :key="stage.key"
        :size="'small'"
      >
        <template #header>
          <div class="stage-header">
            <component :is="statusIcon(stage.status)" :class="['stage-icon', `icon-${stage.status}`]" />
            <span class="stage-number">{{ stage.displayNum }}</span>
            <span class="stage-title-group">
              <span class="stage-title">{{ stage.title }}</span>
              <template v-if="stage.key === 'raw_parse' || stage.key === 'convert'">
                <a-tag v-if="stagePageCount(stage) > 0" size="small" class="stage-page-tag">{{ stagePageCount(stage) }}页</a-tag>
                <a-tag v-if="stageIsScanned(stage)" size="small" color="orange" class="stage-page-tag">扫描件</a-tag>
              </template>
            </span>
            <span class="stage-time">{{ formatTime(stage) }}</span>
            <span class="stage-duration">{{ formatDuration(stage) }}</span>
            <span v-if="stage.key !== 'source_prep'" class="stage-actions">
              <a-button v-if="(anyRunning || anyQueued) && (stage.status === 'running' || stage.status === 'queued')" type="link" size="small" danger class="stage-action-btn" @click.stop="emit('cancel')">
                <StopOutlined /> 取消
              </a-button>
              <a-button v-else-if="!anyRunning && !anyQueued" type="link" size="small" class="stage-action-btn" @click.stop="emit('launch', stage.key)">
                <PlayCircleOutlined /> 启动
              </a-button>
            </span>
          </div>
        </template>
        <template v-if="stage.key === 'source_prep'">
          <div class="file-summary" v-if="stageInput(stage)">
            <div v-for="(file, fi) in parseFiles(stageInput(stage))" :key="fi" class="file-row">
              <a-tag :color="'default'" style="margin: 1px 4px 1px 0;">
                <component :is="fileIcon(file)" class="tag-file-icon" :style="fileIconStyle(file)" />
                {{ file.name }}
              </a-tag>
              <span class="file-path">{{ file.path }}</span>
            </div>
          </div>
          <span v-else>—</span>
        </template>
        <template v-else-if="stage.key === 'convert'">
          <div class="convert-flow">
            <div class="convert-side convert-side-input">
              <div class="convert-side-title">输入</div>
              <div class="file-summary" v-if="convertInput(stage)">
                <div v-for="(file, fi) in parseFiles(convertInput(stage))" :key="fi" class="file-row">
                  <div class="file-name-line">
                    <CheckCircleFilled v-if="stageInputVerified(stage)" class="check-ok verify-file" title="核查通过" />
                    <CloseCircleFilled v-if="stage.status === 'failed'" class="check-no verify-file" title="核查失败" />
                    <a-tag :color="'default'" style="margin: 1px 4px 1px 0;">
                      <component :is="fileIcon(file)" class="tag-file-icon" :style="fileIconStyle(file)" />
                      {{ file.name }}
                    </a-tag>
                  </div>
                  <span class="file-path">{{ dirOf(file.path) }}</span>
                </div>
              </div>
            </div>
            <div class="convert-arrow">
              <RightOutlined class="convert-arrow-icon" />
              <div class="convert-arrow-label">
                <div class="convert-arrow-name">{{ stageRunName(stage, '格式转换') }}</div>
                <div v-if="stage.status === 'running'" class="convert-arrow-duration">{{ liveDuration(stage) }}</div>
                <div v-else-if="splitStageMessage(stage.message).duration" class="convert-arrow-duration">{{ splitStageMessage(stage.message).duration }}</div>
              </div>
            </div>
            <div class="convert-side">
              <div class="convert-side-title">输出</div>
              <div class="file-summary" v-if="stageOutput(stage)">
                <div v-for="(file, fi) in parseFiles(stageOutput(stage))" :key="fi" class="file-row">
                  <a-tag :color="'default'" style="margin: 1px 4px 1px 0;">
                    <component :is="fileIcon(file)" class="tag-file-icon" :style="fileIconStyle(file)" />
                    {{ file.name }}
                  </a-tag>
                  <span class="file-path">{{ dirOf(file.path) }}</span>
                </div>
              </div>
            </div>
          </div>
          <div v-if="stage.status === 'failed' && stage.error" class="stage-error-block">
            <pre>{{ stage.error }}</pre>
            <a-button type="link" size="small" @click.stop="copyStageError(stage)">
              <CopyOutlined /> 复制错误
            </a-button>
          </div>
        </template>
        <template v-else-if="stage.key === 'raw_parse'">
          <div class="convert-flow">
            <div class="convert-side convert-side-narrow">
              <div class="convert-side-title">输入</div>
              <div class="file-summary" v-if="stageInput(stage)">
                <div v-for="(file, fi) in parseFiles(stageInput(stage))" :key="fi" class="file-row">
                  <div class="file-name-line">
                    <CheckCircleFilled v-if="stageInputVerified(stage)" class="check-ok verify-file" title="核查通过" />
                    <CloseCircleFilled v-if="stage.status === 'failed'" class="check-no verify-file" title="核查失败" />
                    <a-tag :color="'default'" style="margin: 1px 4px 1px 0;">
                      <component :is="fileIcon(file)" class="tag-file-icon" :style="fileIconStyle(file)" />
                      {{ file.name }}
                    </a-tag>
                  </div>
                  <span class="file-path">{{ dirOf(file.path) }}</span>
                </div>
              </div>
              <span v-else>—</span>
            </div>
            <div class="convert-arrow">
              <RightOutlined class="convert-arrow-icon" />
              <div class="convert-arrow-label">
                <div class="convert-arrow-name">{{ stageRunName(stage, 'MinerU解析') }}</div>
                <div v-if="mineruBackend(stage)" class="convert-arrow-mode">解析模式: {{ mineruBackend(stage) }}</div>
                <div v-if="stage.status === 'running'" class="convert-arrow-duration">{{ liveDuration(stage) }}</div>
                <div v-else-if="splitStageMessage(stage.message).duration" class="convert-arrow-duration">{{ splitStageMessage(stage.message).duration }}</div>
              </div>
            </div>
              <div class="convert-side">
                <div class="convert-side-title">输出</div>
                <div class="checklist" v-if="mineruOutputChecklist(stage).length">
                  <div v-for="item in mineruOutputChecklist(stage)" :key="item.name" class="checklist-row" :class="{ 'checklist-raw-child': item.childOfRaw }">
                    <component :is="item.exists ? CheckCircleFilled : CloseCircleFilled" :class="item.exists ? 'check-ok' : 'check-no'" />
                    <a-tag :color="'default'" style="margin: 0 4px 0 2px;">
                      <template v-if="item.isDir">📁</template>
                      <template v-else>📄</template>
                      {{ item.name }}
                    </a-tag>
                    <a-tag v-if="item.isNew" color="blue" size="small" style="margin: 0 4px 0 0;">新增</a-tag>
                    <span class="file-path" v-if="item.path">{{ item.path }}</span>
                  </div>
                  <div v-if="mineruRawDir(stage)" class="checklist-row checklist-raw-child checklist-dir-line">
                    <span class="checklist-dir-path">{{ mineruRawDir(stage) }}</span>
                  </div>
              </div>
              <span v-else>—</span>
            </div>
          </div>
          <div v-if="stage.steps.length" class="steps-block">
            <div class="steps-title">分析步骤</div>
            <div v-for="(s, si) in stage.steps" :key="si" class="checklist-row">
              <component :is="stepIcon(s.status)" :class="stepIconClass(s.status)" />
              <span class="step-name">{{ s.step }}</span>
              <span v-if="s.detail" class="step-detail">{{ s.detail }}</span>
            </div>
          </div>
          <div v-if="stage.status === 'failed' && stage.error" class="stage-error-block">
            <pre>{{ stage.error }}</pre>
            <a-button type="link" size="small" @click.stop="copyStageError(stage)">
              <CopyOutlined /> 复制错误
            </a-button>
          </div>
        </template>
        <template v-else-if="stage.key === 'popo' || stage.key === 'structure'">
          <div class="convert-flow">
            <div class="convert-side convert-side-narrow">
              <div class="convert-side-title">输入</div>
              <div class="file-summary" v-if="stageInput(stage)">
                <div v-for="(file, fi) in parseFiles(stageInput(stage))" :key="fi" class="file-row">
                  <div class="file-name-line">
                    <CheckCircleFilled v-if="stageInputVerified(stage)" class="check-ok verify-file" title="核查通过" />
                    <CloseCircleFilled v-if="stage.status === 'failed'" class="check-no verify-file" title="核查失败" />
                    <a-tag :color="'default'" style="margin: 1px 4px 1px 0;">
                      <component :is="fileIcon(file)" class="tag-file-icon" :style="fileIconStyle(file)" />
                      {{ file.name }}
                    </a-tag>
                  </div>
                  <span class="file-path">{{ dirOf(file.path) }}</span>
                </div>
              </div>
              <span v-else>—</span>
            </div>
            <div class="convert-arrow">
              <RightOutlined class="convert-arrow-icon" />
              <div class="convert-arrow-label">
                <div class="convert-arrow-name">{{ flowStageName(stage) }}</div>
                <div v-if="flowBlocks(stage)" class="convert-arrow-mode">{{ flowBlocks(stage) }}</div>
                <div v-if="stage.status === 'running'" class="convert-arrow-duration">{{ liveDuration(stage) }}</div>
                <div v-else-if="splitStageMessage(stage.message).duration" class="convert-arrow-duration">{{ splitStageMessage(stage.message).duration }}</div>
              </div>
            </div>
            <div class="convert-side">
              <div class="convert-side-title">输出</div>
              <div class="checklist" v-if="flowOutputChecklist(stage).length">
                <div v-for="item in flowOutputChecklist(stage)" :key="item.name" class="checklist-row">
                  <component :is="item.exists ? CheckCircleFilled : CloseCircleFilled" :class="item.exists ? 'check-ok' : 'check-no'" />
                  <a-tag :color="'default'" style="margin: 0 4px 0 2px;">
                    <template v-if="item.isDir">📁</template>
                    <template v-else>📄</template>
                    {{ item.name }}
                  </a-tag>
                  <a-tag v-if="item.isNew" color="blue" size="small" style="margin: 0 4px 0 0;">新增</a-tag>
                  <span class="file-path" v-if="item.path">{{ item.path }}</span>
                </div>
                <div v-if="flowOutputDir(stage)" class="checklist-row checklist-dir-line">
                  <span class="checklist-dir-path">{{ flowOutputDir(stage) }}</span>
                </div>
              </div>
              <span v-else>—</span>
            </div>
          </div>
          <div v-if="stage.steps.length" class="steps-block">
            <div class="steps-title">分析步骤</div>
            <div v-for="(s, si) in stage.steps" :key="si" class="checklist-row">
              <component :is="stepIcon(s.status)" :class="stepIconClass(s.status)" />
              <span class="step-name">{{ s.step }}</span>
              <span v-if="s.detail" class="step-detail">{{ s.detail }}</span>
            </div>
          </div>
          <div v-if="stage.status === 'failed' && stage.error" class="stage-error-block">
            <pre>{{ stage.error }}</pre>
            <a-button type="link" size="small" @click.stop="copyStageError(stage)">
              <CopyOutlined /> 复制错误
            </a-button>
          </div>
        </template>
        <a-descriptions v-else :column="1" bordered size="small">
          <a-descriptions-item label="输入">
            <div class="file-summary" v-if="stageInput(stage)">
              <div v-for="(file, fi) in parseFiles(stageInput(stage))" :key="fi" class="file-row">
                <a-tag :color="'default'" style="margin: 1px 4px 1px 0;">
                  <component :is="fileIcon(file)" class="tag-file-icon" :style="fileIconStyle(file)" />
                  {{ file.name }}
                </a-tag>
                <span class="file-path">{{ file.path }}</span>
              </div>
            </div>
            <span v-else>—</span>
          </a-descriptions-item>
          <a-descriptions-item label="产出">
            <div class="file-summary" v-if="stageOutput(stage)">
              <div v-for="(file, fi) in parseFiles(stageOutput(stage))" :key="fi" class="file-row">
                <a-tag :color="'default'" style="margin: 1px 4px 1px 0;">
                  <component :is="fileIcon(file)" class="tag-file-icon" :style="fileIconStyle(file)" />
                  {{ file.name }}
                </a-tag>
                <span class="file-path">{{ file.path }}</span>
              </div>
            </div>
            <span v-else>—</span>
          </a-descriptions-item>
          <a-descriptions-item label="过程">
            <div v-if="stage.status === 'failed'" class="stage-error-block">
              <pre>{{ stage.error }}</pre>
              <a-button type="link" size="small" @click.stop="copyStageError(stage)">
                <CopyOutlined /> 复制错误
              </a-button>
            </div>
            <div v-else>{{ stage.message || '—' }}</div>
          </a-descriptions-item>
        </a-descriptions>
      </a-collapse-panel>
    </a-collapse>
    <div class="stage-total">
      <span class="stage-total-label">总耗时</span>
      <span class="stage-total-value">{{ totalDurationMs > 0 ? formatMs(totalDurationMs) : '—' }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, onBeforeUnmount } from 'vue'
import { message } from 'ant-design-vue'
import {
  CopyOutlined,
  CheckCircleFilled,
  CloseCircleFilled,
  ClockCircleFilled,
  MinusCircleFilled,
  SyncOutlined,
  RightOutlined,
  FileOutlined,
  FilePdfOutlined,
  FileWordOutlined,
  FolderOutlined,
  PlayCircleOutlined,
  StopOutlined,
} from '@ant-design/icons-vue'

const props = defineProps<{
  stages: {
    stage: string
    status: string
    error?: string
    message?: string
    started_at?: string
    finished_at?: string
    input_summary?: string
    output_summary?: string
    backend?: string
    page_count?: number
    is_scanned?: boolean
    outputs?: { dir?: string; raw_dir?: string; items: { name: string; exists: boolean; isNew: boolean; isDir: boolean; childOfRaw?: boolean }[] }
    steps?: { step: string; status: string; detail?: string }[]
  }[]
}>()

const emit = defineEmits<{
  retry: [stageKey: string]
  launch: [stageKey: string]
  cancel: []
}>()

const STAGE_TITLES: Record<string, string> = {
  source_prep: '源文件准备', convert: '格式转换', raw_parse: 'MinerU 解析',
  popo: 'PoPo 强化', structure: '结构化',
  fts: 'SQLite+FTS', vectors: '向量索引', graph: '知识图谱',
}
const PIPELINE_ORDER = Object.keys(STAGE_TITLES)

// 显示序号：后端 STAGE_REGISTRY.step 为准（3.1 MinerU + 3.2 PoPo 同属第 3 步），前端兜底
const STAGE_DISPLAY_NUM: Record<string, string> = {
  source_prep: '1',
  convert: '2',
  raw_parse: '3.1',
  popo: '3.2',
  structure: '4',
  fts: '5',
  vectors: '6',
  graph: '7',
}

const orderedStages = computed(() =>
  PIPELINE_ORDER.map(key => {
    const found: Partial<NonNullable<typeof props.stages>[number]> = props.stages.find(s => s.stage === key) || {}
    return {
      key,
      title: stageTitle(key, found),
      displayNum: (found as any)?.step || STAGE_DISPLAY_NUM[key] || '',
      status: found.status || 'pending',
      error: found.error || '',
      message: found.message || '',
      started_at: found.started_at || '',
      finished_at: found.finished_at || '',
      input_summary: found.input_summary || '',
      output_summary: found.output_summary || '',
      backend: (found as any)?.backend || '',
      page_count: (found as any)?.page_count || 0,
      is_scanned: Boolean((found as any)?.is_scanned),
      outputs: (found as any)?.outputs || null,
      steps: (found as any)?.steps || [],
    }
  })
)

const totalDurationMs = computed(() => {
  let total = 0
  let anyStarted = false
  for (const s of orderedStages.value) {
    if (s.status === 'running' && s.started_at) {
      anyStarted = true
      total += nowTick.value - new Date(s.started_at).getTime()
      continue
    }
    if ((s.status === 'completed' || s.status === 'failed') && s.started_at && s.finished_at) {
      anyStarted = true
      total += Math.max(0, new Date(s.finished_at).getTime() - new Date(s.started_at).getTime())
    }
  }
  return anyStarted ? total : 0
})

// 结构化阶段标题按实际使用的后端动态显示；未完成或未知时保持中性「结构化」
function stageTitle(key: string, found: { backend?: string }): string {
  if (key === 'structure') {
    const backend = String(found.backend || '')
    if (backend === 'popo') return '结构化（基于 PoPo）'
    if (backend === 'solo') return 'Solo结构化'
    return STAGE_TITLES.structure
  }
  return STAGE_TITLES[key]
}

// 页数/扫描件元数据由 raw_parse 阶段落库；convert 等阶段展示时回退引用同一文档的 raw_parse
function stagePageCount(stage: { key: string; status: string; page_count?: number }): number {
  if (stage.page_count > 0) return stage.page_count
  if (stage.key === 'convert' && stage.status !== 'pending' && stage.status !== 'skipped') {
    return orderedStages.value.find(s => s.key === 'raw_parse')?.page_count || 0
  }
  return 0
}

function stageIsScanned(stage: { key: string; status: string; is_scanned?: boolean }): boolean {
  if (stage.is_scanned) return true
  if (stage.key === 'convert' && stage.status !== 'pending' && stage.status !== 'skipped') {
    return Boolean(orderedStages.value.find(s => s.key === 'raw_parse')?.is_scanned)
  }
  return false
}

// 是否有阶段正在运行（决定显示启动还是取消）
const anyRunning = computed(() => orderedStages.value.some(s => s.status === 'running'))
// 是否有阶段排队等待 GPU（同样视为任务进行中，不显示启动）
const anyQueued = computed(() => orderedStages.value.some(s => s.status === 'queued'))

// 每秒 tick，驱动执行中阶段的实时耗时
const nowTick = ref(Date.now())
let tickTimer: number | null = null
onMounted(() => {
  tickTimer = window.setInterval(() => { nowTick.value = Date.now() }, 1000)
})
onBeforeUnmount(() => {
  if (tickTimer !== null) window.clearInterval(tickTimer)
})

function statusIcon(status: string) {
  const map: Record<string, any> = {
    completed: CheckCircleFilled,
    running: SyncOutlined,
    queued: ClockCircleFilled,
    failed: CloseCircleFilled,
    skipped: MinusCircleFilled,
    pending: ClockCircleFilled,
  }
  return map[status] || ClockCircleFilled
}

// 分析步骤状态图标：done/failed/running/skipped 对应勾/叉/旋转/减号
function stepIcon(status: string) {
  const map: Record<string, any> = {
    done: CheckCircleFilled,
    completed: CheckCircleFilled,
    failed: CloseCircleFilled,
    running: SyncOutlined,
    skipped: MinusCircleFilled,
    pending: ClockCircleFilled,
  }
  return map[status] || ClockCircleFilled
}

function stepIconClass(status: string): string {
  if (status === 'failed') return 'check-no'
  if (status === 'done' || status === 'completed') return 'check-ok'
  if (status === 'skipped') return 'check-skip'
  return 'check-run'
}

function formatTime(stage: { started_at?: string }): string {
  if (!stage.started_at) return '—'
  return stage.started_at.slice(11, 19)
}

function formatDuration(stage: { started_at?: string; finished_at?: string; status: string }): string {
  if (stage.status === 'pending') return '等待中'
  if (stage.status === 'skipped') return '已跳过'
  if (stage.status === 'queued') return '排队中'
  // 执行中：实时计时（整数秒每秒刷新）
  if (stage.status === 'running' && stage.started_at) {
    return formatMs(nowTick.value - new Date(stage.started_at).getTime())
  }
  if (stage.status === 'running') return '执行中'
  // 完成/失败：总时长 1 位小数
  if (!stage.started_at || !stage.finished_at) return '—'
  try {
    const start = new Date(stage.started_at).getTime()
    const end = new Date(stage.finished_at).getTime()
    const ms = Math.max(0, end - start)
    if (ms < 100) return `${ms}ms`
    return `${(ms / 1000).toFixed(1)}s`
  } catch {
    return '—'
  }
}

function formatMs(ms: number): string {
  const secs = Math.max(0, Math.floor(ms / 1000))
  if (secs < 1) return `${ms}ms`
  if (secs < 60) return `${secs}s`
  return `${Math.floor(secs / 60)}m${secs % 60}s`
}

// 执行中的实时耗时文案，如 "耗时 12.3s"
function liveDuration(stage: { started_at?: string; status: string }): string {
  if (stage.status !== 'running' || !stage.started_at) return ''
  return `耗时 ${formatMs(nowTick.value - new Date(stage.started_at).getTime())}`
}

function stageInput(stage: { key: string; input_summary: string }): string {
  return stage.input_summary || '—'
}

function stageOutput(stage: { key: string; output_summary: string }): string {
  return stage.output_summary || '—'
}

// 格式转换的输入：优先本阶段 input_summary；running 期间尚未写库时，回退到上一步「源文件准备」的输出
function convertInput(stage: { key: string; input_summary: string; status: string }): string {
  if (stage.input_summary) return stage.input_summary
  const prep = orderedStages.value.find(s => s.key === 'source_prep')
  if (prep && prep.output_summary) return prep.output_summary
  return ''
}

// 核查通过才显示 ✅：completed 或 running 且后端已写入「核查通过」（每个阶段启动前统一核查）
function stageInputVerified(stage: { status: string; message?: string }): boolean {
  if (stage.status === 'completed') return true
  return stage.status === 'running' && Boolean(stage.message && stage.message.includes('核查通过'))
}

async function copyStageError(stage: { error?: string; title: string }) {
  try {
    await navigator.clipboard.writeText(`[${stage.title}]\n${stage.error || ''}`)
    message.success('已复制')
  } catch {
    message.error('复制失败')
  }
}

// MinerU 解析输出检查：顶层 3 项 + mineru_raw 内部 5 文件，存在打勾缺失打叉，新增文件单独展示
const MINERU_TOP_OUTPUTS = ['content.md', 'images', 'mineru_raw']
const MINERU_RAW_FILES = ['content_list.json', 'content_list_v2.json', 'model.json', 'middle.json', 'origin.zip']

// 拆分阶段消息为「阶段名」+「耗时」两行，如 "LibreOffice转换，耗时16.3s"
function splitStageMessage(msg: string | undefined): { name: string; duration: string } {
  const text = msg || ''
  const idx = text.indexOf('，耗时')
  if (idx > 0) return { name: text.slice(0, idx), duration: text.slice(idx + 1) }
  return { name: text, duration: '' }
}

// 箭头行的阶段名：running 且刚核查通过（message="核查通过"）时，耗时实际是转换耗时，名称显示「转换中」
// message 中 ||backend|| 分隔符（如 "MinerU解析完成||pipeline||"）在显示时会剥离
function stageRunName(stage: { status: string; message?: string }, fallback: string): string {
  const name = splitStageMessage(stage.message).name || fallback
  if (stage.status === 'running' && name === '核查通过') return '转换中'
  return name.replace(/\|\|.+\|\|/, '')
}

function mineruOutputChecklist(stage: { status: string; output_summary: string; outputs?: { items: { name: string; exists: boolean; isNew: boolean; isDir: boolean; childOfRaw?: boolean }[] } }): { name: string; path: string; exists: boolean; isNew: boolean; isDir: boolean; childOfRaw?: boolean }[] {
  // 未启动/排队/已跳过的阶段不渲染产物核查，避免把“尚未运行”显示成红叉
  if (['pending', 'queued', 'skipped'].includes(stage.status)) {
    return []
  }
  // 后端真实文件系统核查结果优先；仅在旧接口/未返回时回退到 output_summary 字符串比对
  if (stage.outputs?.items?.length) {
    return stage.outputs.items.map(item => ({ ...item, path: '' }))
  }
  const files = parseFiles(stage.output_summary || '')
  const presentNames = new Set(files.map(f => f.name))

  const top = MINERU_TOP_OUTPUTS.map(name => ({
    name,
    exists: presentNames.has(name),
    isNew: false,
    isDir: !name.includes('.'),
    path: '', // 所有输出在同一目录，路径统一在列表最下方写一次
  }))

  // mineru_raw 内部子文件（路径以 mineru_raw 目录为前缀）
  const rawPath = files.find(f => f.name === 'mineru_raw')?.path || ''
  const rawPrefixes = rawPath ? [rawPath + '/', rawPath + '\\'] : []
  const rawChildren = rawPrefixes.length
    ? files.filter(f => f.name !== 'mineru_raw' && rawPrefixes.some(p => f.path.startsWith(p)))
    : []
  const rawNames = new Set(rawChildren.map(f => f.name))
  const rawList = MINERU_RAW_FILES.map(name => ({
    name,
    exists: rawNames.has(name),
    isNew: false,
    isDir: false,
    childOfRaw: true,
    path: '', // 五个文件都在同一目录，路径统一在列表下方写一次
  }))

  const rawChildPaths = new Set(rawChildren.map(f => f.path))
  // mineru_raw 内部新增文件（不在固定 5 项内）：缩进 + 新增标签
  const rawExtras = rawChildren
    .filter(f => !MINERU_RAW_FILES.includes(f.name))
    .map(f => ({ name: f.name, path: '', exists: true, isNew: true, isDir: f.isDir, childOfRaw: true }))
  // 顶层新增文件：平级 + 新增标签（路径同下，不再逐行展示）
  const topExtras = files
    .filter(f => !MINERU_TOP_OUTPUTS.includes(f.name) && !rawChildPaths.has(f.path))
    .map(f => ({ name: f.name, path: '', exists: true, isNew: true, isDir: f.isDir }))

  const rows: any[] = [...top, ...rawList, ...rawExtras, ...topExtras]
  return rows
}

// 五个文件所在目录（mineru_raw 父目录 = parsed），在检查表下方写一次
function mineruRawDir(stage: { output_summary: string; outputs?: { dir?: string } }): string {
  if (stage.outputs?.dir) return stage.outputs.dir
  const files = parseFiles(stage.output_summary || '')
  const raw = files.find(f => f.name === 'mineru_raw')
  if (raw) return dirOf(raw.path)
  const sample = files[0]
  if (!sample) return ''
  const idx = sample.path.search(/[\\/]mineru_raw[\\/]|(?:content\.md|images)$/)
  return idx > 0 ? sample.path.slice(0, idx + 1) : ''
}

// 从 message 提取解析模式（||backend|| 分隔符），非虚构文件
function mineruBackend(stage: { message?: string }): string {
  const name = splitStageMessage(stage.message).name || ''
  const m = name.match(/\|\|(.+)\|\|/)
  return m ? m[1] : ''
}

// 结构强化输出检查：PoPo / Solo 各自固定的产物清单，存在打勾缺失打叉
const POPO_OUTPUTS = ['enriched_blocks.json', 'document_tree.json']
// 结构化阶段两条后端共用同一组输出文件名，与 PoPo 阶段产物分开判断
const STRUCTURE_OUTPUTS = ['content.md', 'doc_blocks_graph.jsonl', 'doc_blocks_graph_meta.json']

function flowOutputChecklist(stage: { key: string; status: string; output_summary: string; outputs?: { items: { name: string; exists: boolean; isNew: boolean; isDir: boolean; childOfRaw?: boolean }[] } }): { name: string; path: string; exists: boolean; isNew: boolean; isDir: boolean; childOfRaw?: boolean }[] {
  // 未启动/排队/已跳过的阶段不渲染产物核查，避免把“尚未运行”显示成红叉
  if (['pending', 'queued', 'skipped'].includes(stage.status)) {
    return []
  }
  // 后端真实文件系统核查结果优先；仅在旧接口/未返回时回退到 output_summary 字符串比对
  if (stage.outputs?.items?.length) {
    return stage.outputs.items.map(item => ({ ...item, path: '' }))
  }
  const expected = stage.key === 'structure' ? STRUCTURE_OUTPUTS : POPO_OUTPUTS
  const files = parseFiles(stage.output_summary || '')
  const presentNames = new Set(files.map(f => f.name))
  const fixed = expected.map(name => ({
    name,
    exists: presentNames.has(name),
    isNew: false,
    isDir: false,
    path: '', // 所有产物都在同一目录，路径统一在列表下方写一次
  }))
  const extras = files
    .filter(f => !expected.includes(f.name))
    .map(f => ({ name: f.name, path: '', exists: true, isNew: true, isDir: f.isDir }))
  return [...fixed, ...extras]
}

// 产物所在目录（PoPo → popo 目录，Solo → parsed 目录），在检查表下方写一次
function flowOutputDir(stage: { key: string; output_summary: string; outputs?: { dir?: string } }): string {
  if (stage.outputs?.dir) return stage.outputs.dir
  const files = parseFiles(stage.output_summary || '')
  const sample = files.find(f => f.path) || files[0]
  if (!sample) return ''
  return dirOf(sample.path)
}

// 箭头阶段名：消息形如 "PoPo 强化完成，N blocks（…），耗时X.Xs"，箭头只显示动作名
function flowStageName(stage: { key: string; status: string; message?: string }): string {
  const isStructure = stage.key === 'structure'
  const runningLabel = isStructure ? '结构化进行中' : 'PoPo 强化中'
  const doneLabel = isStructure ? '结构化完成' : 'PoPo 强化完成'
  const raw = splitStageMessage(stage.message).name || ''
  if (stage.status === 'running' && (!raw || raw === '核查通过')) return runningLabel
  const clean = raw.replace(/\|\|.+\|\|/, '').split('，')[0] || ''
  return clean || (stage.status === 'running' ? runningLabel : doneLabel)
}

// 箭头模式行：blocks 数量，如 "12 blocks"
function flowBlocks(stage: { message?: string }): string {
  const m = (stage.message || '').match(/(\d+)\s*blocks?/)
  return m ? `${m[1]} blocks` : ''
}

function parseFiles(text: string): { name: string; path: string; isDir: boolean }[] {
  // 产物清单用 " + "（空格+加号+空格）连接多个文件；文件名里的 + 不能作为分隔符
  return text.split(/\s+\+\s+/).filter(Boolean).map(part => {
    part = part.trim()
    if (/[/\\]/.test(part) || part.includes(':')) {
      const name = part.split(/[/\\]/).filter(Boolean).pop() || part
      const isDir = !name.includes('.') || part.endsWith('/') || part.endsWith('\\')
      return { name, path: part, isDir }
    }
    return { name: part, path: '', isDir: false }
  })
}

function dirOf(path: string): string {
  if (!path) return path
  const idx = Math.max(path.lastIndexOf('/'), path.lastIndexOf('\\'))
  return idx > 0 ? path.slice(0, idx + 1) : path
}

function fileIcon(file: { name: string; isDir: boolean }) {
  if (file.isDir) return FolderOutlined
  const ext = file.name.split('.').pop()?.toLowerCase() || ''
  if (ext === 'pdf') return FilePdfOutlined
  if (['doc', 'docx'].includes(ext)) return FileWordOutlined
  return FileOutlined
}

function fileIconStyle(file: { name: string; isDir: boolean }): Record<string, string> | undefined {
  if (file.isDir) return undefined
  const ext = file.name.split('.').pop()?.toLowerCase() || ''
  if (ext === 'pdf') return { color: '#e74c3c' }
  if (['doc', 'docx'].includes(ext)) return { color: '#2b7cd3' }
  return undefined
}

</script>

<style lang="less" scoped>
.doc-stage-stepper {
  :deep(.ant-collapse-header) {
    padding: 8px 12px !important;
  }
  :deep(.ant-collapse-content-box) {
    padding: 8px 12px !important;
  }
}

.stage-header {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}

.stage-icon {
  font-size: 14px;
  flex-shrink: 0;
  &.icon-completed { color: var(--success-color, #52c41a); }
  &.icon-running { color: var(--primary-color, #1890ff); }
  &.icon-queued { color: #fa8c16; }
  &.icon-failed { color: var(--error-color, #ff4d4f); }
  &.icon-skipped { color: var(--text-tertiary, #999); }
  &.icon-pending { color: var(--text-tertiary, #bbb); }
}

.stage-number {
  font-weight: 600;
  font-size: 13px;
  min-width: 20px;
}

.stage-title-group {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
  min-width: 0;
}

.stage-title {
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.stage-time {
  font-size: 12px;
  color: var(--text-tertiary, #999);
  min-width: 60px;
  text-align: right;
}

.stage-duration {
  font-size: 12px;
  color: var(--text-secondary, #666);
  min-width: 55px;
  text-align: right;
}

.stage-actions {
  flex-shrink: 0;
  margin-left: 4px;
}
.stage-page-tag {
  margin-inline-end: 0;
}
.stage-action-btn {
  font-size: 12px;
  padding-inline: 0;
}

.stage-error-block {
  pre {
    white-space: pre-wrap;
    word-break: break-all;
    font-size: 12px;
    margin-bottom: 4px;
  }
}

.file-summary {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.file-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
}
.file-path {
  font-size: 11px;
  color: var(--text-tertiary, #999);
  word-break: break-all;
  flex: 1;
  min-width: 0;
}

.tag-file-icon {
  font-size: 12px;
  margin-right: 4px;
}

/* MinerU 输出检查表 */
.checklist {
  display: flex;
  flex-direction: column;
  gap: 4px;
  align-items: flex-start;
}
.checklist-row {
  display: flex;
  align-items: center;
  flex-wrap: nowrap;
  gap: 4px;
  font-size: 12px;
  max-width: 100%;
}
.check-ok {
  color: var(--success-color, #52c41a);
  font-size: 13px;
  flex-shrink: 0;
}
.file-name-line {
  display: flex;
  align-items: center;
  gap: 2px;
}
.verify-file {
  font-size: 12px;
  flex-shrink: 0;
}
.check-no {
  color: var(--error-color, #ff4d4f);
  font-size: 13px;
  flex-shrink: 0;
}
.check-run {
  color: var(--primary-color, #1677ff);
  font-size: 13px;
  flex-shrink: 0;
}
.check-skip {
  color: var(--text-tertiary, #999);
  font-size: 13px;
  flex-shrink: 0;
}
.steps-block {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 8px;
  padding: 8px 10px;
  border: 1px dashed var(--border-color, #e8e8e8);
  border-radius: 6px;
  background: var(--bg-tertiary, #fafafa);
}
.steps-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary, #666);
}
.step-name {
  font-size: 12px;
  color: var(--text-primary, #222);
}
.step-detail {
  font-size: 11px;
  color: var(--text-tertiary, #999);
  word-break: break-all;
  flex: 1;
  min-width: 0;
}
.checklist-raw-child {
  padding-left: 20px;
}
.checklist-dir-line {
  color: var(--text-tertiary, #999);
  font-size: 11px;
  align-items: flex-start;
  max-width: 100%;
  padding-left: 0;
}
.checklist-dir-path {
  flex: 1;
  min-width: 0;
  word-break: break-all;
  overflow-wrap: anywhere;
  text-align: left;
  line-height: 1.4;
}

.convert-flow {
  display: flex;
  align-items: stretch;
  gap: 8px;
}
.convert-side {
  flex: 1;
  min-width: 0;
  padding: 6px 10px 10px;
  border: 1px solid var(--border-color, #f0f0f0);
  border-radius: 6px;
  background: var(--bg-tertiary, #fafafa);
  display: flex;
  flex-direction: column;
  gap: 4px;
  align-items: center;
  text-align: center;
}
/* 输入框固定 170px，输出框占满剩余（输出更宽） */
.convert-side-input {
  flex: 0 0 170px;
}
.convert-side-narrow {
  flex: 0 0 170px;
}
.convert-side-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary, #666);
  margin-bottom: 2px;
}
.convert-side .file-row {
  justify-content: center;
  flex-direction: column;
  gap: 2px;
}
/* 输入/输出框内文件行：宽度锚定到所在框，避免长文件名/路径把框撑破 */
.convert-side .file-summary,
.convert-side .file-row,
.convert-side .file-name-line {
  width: 100%;
  max-width: 100%;
  min-width: 0;
}
/* 文件名（图标+文件名）保持一行，超长省略号截断；不溢出所在框 */
.convert-side .file-name-line .ant-tag,
.convert-side .file-row > .ant-tag {
  max-width: 100%;
  min-width: 0;
  height: auto;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.convert-side .file-path {
  width: 100%;
  max-width: 100%;
  font-size: 10px;
  text-align: center;
  overflow-wrap: anywhere;
}
.convert-arrow {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  flex: 0 0 90px;
}
.convert-arrow-icon {
  font-size: 16px;
  color: var(--primary-color, #1890ff);
}
.convert-arrow-label {
  font-size: 11px;
  color: var(--text-secondary, #666);
  text-align: center;
  line-height: 1.4;
}
.convert-arrow-name {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-primary, #333);
}
.convert-arrow-mode {
  font-size: 10px;
  color: var(--text-tertiary, #999);
  margin-top: -2px;
}
.convert-arrow-duration {
  font-size: 11px;
  color: var(--text-tertiary, #999);
  white-space: nowrap;
}

.stage-total {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px dashed var(--border-color, #e8e8e8);
}
.stage-total-label {
  font-size: 12px;
  color: var(--text-secondary, #666);
}
.stage-total-value {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary, #222);
}
</style>
