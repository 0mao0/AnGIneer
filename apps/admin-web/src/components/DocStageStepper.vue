<template>
  <div class="doc-stage-stepper">
    <a-collapse>
      <!-- 前段：源文件准备 / 格式转换 / MinerU 解析 -->
      <a-collapse-panel
        v-for="stage in headStages"
        :key="stage.key"
        :size="'small'"
      >
        <template #header>
          <div class="stage-header">
            <component :is="statusIcon(stage.status)" :class="['stage-icon', `icon-${stage.status}`]" />
            <span class="stage-number">{{ stage.displayNum }}.</span>
            <span class="stage-title">{{ stage.title }}</span>
            <span class="stage-time">{{ formatTime(stage) }}</span>
            <span class="stage-duration">{{ formatDuration(stage) }}</span>
            <span v-if="stage.key !== 'source_prep'" class="stage-actions">
              <a-button v-if="anyRunning && stage.status === 'running'" type="link" size="small" danger class="stage-action-btn" @click.stop="emit('cancel')">
                <StopOutlined /> 取消
              </a-button>
              <a-button v-else-if="!anyRunning" type="link" size="small" class="stage-action-btn" @click.stop="emit('launch', stage.key)">
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

      <!-- 4. 结构强化（4.1 PoPo / 4.2 Solo 二级） -->
      <a-collapse-panel key="structure-group" :size="'small'" class="structure-group">
        <template #header>
          <div class="stage-header">
            <ApartmentOutlined class="stage-icon icon-group" />
            <span class="stage-number">4.</span>
            <span class="stage-title">结构强化</span>
            <span class="stage-time">PoPo 优先，失败回退 Solo</span>
          </div>
        </template>
        <a-collapse class="sub-collapse">
          <a-collapse-panel
            v-for="stage in structureStages"
            :key="stage.key"
            :size="'small'"
                      >
            <template #header>
              <div class="stage-header">
                <component :is="statusIcon(stage.status)" :class="['stage-icon', `icon-${stage.status}`]" />
                <span class="stage-number">{{ stage.displayNum }}</span>
                <span class="stage-title">{{ stage.title }}</span>
                <span class="stage-time">{{ formatTime(stage) }}</span>
                <span class="stage-duration">{{ formatDuration(stage) }}</span>
                <span class="stage-actions">
                  <a-button v-if="anyRunning && stage.status === 'running'" type="link" size="small" danger class="stage-action-btn" @click.stop="emit('cancel')">
                    <StopOutlined /> 取消
                  </a-button>
                  <a-button v-else-if="!anyRunning" type="link" size="small" class="stage-action-btn" @click.stop="emit('launch', stage.key)">
                    <PlayCircleOutlined /> 启动
                  </a-button>
                </span>
              </div>
            </template>
            <a-descriptions :column="1" bordered size="small">
          <a-descriptions-item label="输入">
            <div class="file-summary" v-if="stageInput(stage)">
              <div v-for="(file, fi) in parseFiles(stageInput(stage))" :key="fi" class="file-row">
                <CheckCircleFilled v-if="stageInputVerified(stage)" class="check-ok verify-file" title="核查通过" />
                <CloseCircleFilled v-if="stage.status === 'failed'" class="check-no verify-file" title="核查失败" />
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
      </a-collapse-panel>

      <!-- 后段：全文索引 / 向量索引 / 知识图谱 -->
      <a-collapse-panel
        v-for="stage in tailStages"
        :key="stage.key"
        :size="'small'"
      >
        <template #header>
          <div class="stage-header">
            <component :is="statusIcon(stage.status)" :class="['stage-icon', `icon-${stage.status}`]" />
            <span class="stage-number">{{ stage.displayNum }}.</span>
            <span class="stage-title">{{ stage.title }}</span>
            <span class="stage-time">{{ formatTime(stage) }}</span>
            <span class="stage-duration">{{ formatDuration(stage) }}</span>
            <span class="stage-actions">
              <a-button v-if="anyRunning && stage.status === 'running'" type="link" size="small" danger class="stage-action-btn" @click.stop="emit('cancel')">
                <StopOutlined /> 取消
              </a-button>
              <a-button v-else-if="!anyRunning" type="link" size="small" class="stage-action-btn" @click.stop="emit('launch', stage.key)">
                <PlayCircleOutlined /> 启动
              </a-button>
            </span>
          </div>
        </template>
        <a-descriptions :column="1" bordered size="small">
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
  ApartmentOutlined,
  FileOutlined,
  FilePdfOutlined,
  FileWordOutlined,
  FolderOutlined,
  PlayCircleOutlined,
  StopOutlined,
} from '@ant-design/icons-vue'

const props = defineProps<{
  stages: { stage: string; status: string; error?: string; message?: string; started_at?: string; finished_at?: string; input_summary?: string; output_summary?: string }[]
}>()

const emit = defineEmits<{
  retry: [stageKey: string]
  launch: [stageKey: string]
  cancel: []
}>()

const STAGE_TITLES: Record<string, string> = {
  source_prep: '源文件准备', convert: '格式转换', raw_parse: 'MinerU 解析',
  popo: 'PoPo 强化', structure: 'Solo 强化',
  fts: '全文索引', vectors: '向量索引', graph: '知识图谱',
}
const PIPELINE_ORDER = Object.keys(STAGE_TITLES)

// 显示序号：PoPo 与 Solo 为并行分支（4.1 / 4.2）
const STAGE_DISPLAY_NUM: Record<string, string> = {
  source_prep: '1',
  convert: '2',
  raw_parse: '3',
  popo: '4.1',
  structure: '4.2',
  fts: '5',
  vectors: '6',
  graph: '7',
}

const orderedStages = computed(() =>
  PIPELINE_ORDER.map(key => {
    const found: Partial<NonNullable<typeof props.stages>[number]> = props.stages.find(s => s.stage === key) || {}
    return {
      key,
      title: STAGE_TITLES[key],
      displayNum: STAGE_DISPLAY_NUM[key] || '',
      status: found.status || 'pending',
      error: found.error || '',
      message: found.message || '',
      started_at: found.started_at || '',
      finished_at: found.finished_at || '',
      input_summary: found.input_summary || '',
      output_summary: found.output_summary || '',
    }
  })
)

// 分段：前段（1-3）｜结构强化组（4.1/4.2）｜后段（5-7）
const HEAD_KEYS = ['source_prep', 'convert', 'raw_parse']
const STRUCTURE_KEYS = ['popo', 'structure']
const TAIL_KEYS = ['fts', 'vectors', 'graph']

const headStages = computed(() => orderedStages.value.filter(s => HEAD_KEYS.includes(s.key)))
const structureStages = computed(() => orderedStages.value.filter(s => STRUCTURE_KEYS.includes(s.key)))
const tailStages = computed(() => orderedStages.value.filter(s => TAIL_KEYS.includes(s.key)))

// 是否有阶段正在运行（决定显示启动还是取消）
const anyRunning = computed(() => orderedStages.value.some(s => s.status === 'running'))

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
    failed: CloseCircleFilled,
    skipped: MinusCircleFilled,
    pending: ClockCircleFilled,
  }
  return map[status] || ClockCircleFilled
}

function formatTime(stage: { started_at?: string }): string {
  if (!stage.started_at) return '—'
  return stage.started_at.slice(11, 19)
}

function formatDuration(stage: { started_at?: string; finished_at?: string; status: string }): string {
  if (stage.status === 'pending') return '等待中'
  if (stage.status === 'skipped') return '已跳过'
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

function mineruOutputChecklist(stage: { output_summary: string }): { name: string; path: string; exists: boolean; isNew: boolean; isDir: boolean; childOfRaw?: boolean }[] {
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
function mineruRawDir(stage: { output_summary: string }): string {
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

function parseFiles(text: string): { name: string; path: string; isDir: boolean }[] {
  return text.split(/\s*\+\s*/).filter(Boolean).map(part => {
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
  &.icon-failed { color: var(--error-color, #ff4d4f); }
  &.icon-skipped { color: var(--text-tertiary, #999); }
  &.icon-pending { color: var(--text-tertiary, #bbb); }
}

.stage-number {
  font-weight: 600;
  font-size: 13px;
  min-width: 20px;
}

.stage-title {
  font-size: 13px;
  font-weight: 500;
  flex: 1;
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
.stage-action-btn {
  font-size: 12px;
  padding-inline: 0;
}

/* 结构强化分组 */
.structure-group {
  :deep(.ant-collapse-header) {
    background: var(--bg-tertiary, #fafafa);
    border-bottom: 1px solid var(--border-color, #f0f0f0);
  }
}
.icon-group {
  color: var(--primary-color, #1890ff);
}
.sub-collapse {
  :deep(.ant-collapse) {
    border: none !important;
    background: transparent !important;
  }
  :deep(.ant-collapse-content) {
    background: transparent !important;
  }
  :deep(.ant-collapse-item) {
    border-bottom: none !important;
  }
  :deep(.ant-collapse-header) {
    padding-left: 24px !important;
  }
}

.stage-error-block {
  pre {
    white-space: pre-wrap;
    word-break: break-all;
    font-size: 12px;
    margin-bottom: 4px;
    max-height: 200px;
    overflow-y: auto;
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
.convert-side .file-path {
  font-size: 10px;
  max-width: 100%;
  text-align: center;
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
</style>
