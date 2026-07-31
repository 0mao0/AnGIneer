<template>
  <div class="doc-stage-stepper">
    <a-collapse>
      <a-collapse-panel
        v-for="(stage, idx) in orderedStages"
        :key="stage.key"
        :size="'small'"
        :disabled="stage.status === 'skipped'"
      >
        <template #header>
          <div class="stage-header">
            <component :is="statusIcon(stage.status)" :class="['stage-icon', `icon-${stage.status}`]" />
            <span class="stage-number">{{ idx + 1 }}.</span>
            <span class="stage-title">{{ stage.title }}</span>
            <span class="stage-time">{{ formatTime(stage) }}</span>
            <span class="stage-duration">{{ formatDuration(stage) }}</span>
          </div>
        </template>
        <template v-if="stage.key === 'source_prep'">
          <div class="file-summary" v-if="stageInput(stage)">
            <div v-for="(file, fi) in parseFiles(stageInput(stage))" :key="fi" class="file-row">
              <a-tag :color="'default'" style="margin: 1px 4px 1px 0;">
                <component :is="fileIcon(file)" class="tag-file-icon" />
                {{ file.name }}
              </a-tag>
              <span class="file-path">{{ file.path }}</span>
            </div>
          </div>
          <span v-else>—</span>
        </template>
        <template v-else-if="stage.key === 'convert'">
          <div class="convert-flow">
            <div class="convert-side">
              <div class="convert-side-title">输入</div>
              <div class="file-summary" v-if="stageInput(stage)">
                <div v-for="(file, fi) in parseFiles(stageInput(stage))" :key="fi" class="file-row">
                  <a-tag :color="'default'" style="margin: 1px 4px 1px 0;">
                    <component :is="fileIcon(file)" class="tag-file-icon" />
                    {{ file.name }}
                  </a-tag>
                  <span class="file-path">{{ dirOf(file.path) }}</span>
                </div>
              </div>
            </div>
            <div class="convert-arrow">
              <RightOutlined class="convert-arrow-icon" />
              <div class="convert-arrow-label">{{ stage.message || '格式转换' }}</div>
            </div>
            <div class="convert-side">
              <div class="convert-side-title">输出</div>
              <div class="file-summary" v-if="stageOutput(stage)">
                <div v-for="(file, fi) in parseFiles(stageOutput(stage))" :key="fi" class="file-row">
                  <a-tag :color="'default'" style="margin: 1px 4px 1px 0;">
                    <component :is="fileIcon(file)" class="tag-file-icon" />
                    {{ file.name }}
                  </a-tag>
                  <span class="file-path">{{ dirOf(file.path) }}</span>
                </div>
              </div>
            </div>
          </div>
        </template>
        <a-descriptions v-else :column="1" bordered size="small">
          <a-descriptions-item label="输入">
            <div class="file-summary" v-if="stageInput(stage)">
              <div v-for="(file, fi) in parseFiles(stageInput(stage))" :key="fi" class="file-row">
                <a-tag :color="'default'" style="margin: 1px 4px 1px 0;">
                  <component :is="fileIcon(file)" class="tag-file-icon" />
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
                  <component :is="fileIcon(file)" class="tag-file-icon" />
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
import { computed } from 'vue'
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
} from '@ant-design/icons-vue'

const props = defineProps<{
  stages: { stage: string; status: string; error?: string; message?: string; started_at?: string; finished_at?: string; input_summary?: string; output_summary?: string }[]
}>()

defineEmits<{
  retry: [stageKey: string]
}>()

const STAGE_TITLES: Record<string, string> = {
  source_prep: '源文件准备', convert: '格式转换', raw_parse: 'MinerU 解析',
  build_blocks: '区块提取', popo: 'PoPo 增强', structure: 'Solo 结构化入库',
  fts: '全文索引', vectors: '向量索引', graph: '知识图谱',
}
const PIPELINE_ORDER = Object.keys(STAGE_TITLES)

const orderedStages = computed(() =>
  PIPELINE_ORDER.map(key => {
    const found: Partial<NonNullable<typeof props.stages>[number]> = props.stages.find(s => s.stage === key) || {}
    return {
      key,
      title: STAGE_TITLES[key],
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
  if (stage.status === 'running') return '执行中'
  if (stage.status === 'skipped') return '已跳过'
  if (!stage.started_at || !stage.finished_at) return '—'
  try {
    const start = new Date(stage.started_at).getTime()
    const end = new Date(stage.finished_at).getTime()
    const ms = end - start
    if (ms < 1000) return `${ms}ms`
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
    return `${Math.floor(ms / 60000)}m${Math.round((ms % 60000) / 1000)}s`
  } catch {
    return '—'
  }
}

function stageInput(stage: { key: string; input_summary: string }): string {
  return stage.input_summary || '—'
}

function stageOutput(stage: { key: string; output_summary: string }): string {
  return stage.output_summary || '—'
}

async function copyStageError(stage: { error?: string; title: string }) {
  try {
    await navigator.clipboard.writeText(`[${stage.title}]\n${stage.error || ''}`)
    message.success('已复制')
  } catch {
    message.error('复制失败')
  }
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
  flex-shrink: 0;
  min-width: 64px;
}
.convert-arrow-icon {
  font-size: 16px;
  color: var(--primary-color, #1890ff);
}
.convert-arrow-label {
  font-size: 11px;
  color: var(--text-secondary, #666);
  text-align: center;
  line-height: 1.3;
}
</style>
