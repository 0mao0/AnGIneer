<template>
  <div class="doc-stage-stepper">
    <a-steps size="small" :current="-1" direction="vertical">
      <a-step
        v-for="stage in orderedStages"
        :key="stage.key"
        :title="stage.title"
        :description="stageDescription(stage)"
        :status="stepStatus(stage.status)"
      />
    </a-steps>
    <div v-if="hasFailedStage" class="stage-error-copy">
      <a-typography-text type="danger" :content="failedStageMessage" />
      <a-button type="link" size="small" @click="copyError">
        <CopyOutlined /> 复制错误信息
      </a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { message } from 'ant-design-vue'
import { CopyOutlined } from '@ant-design/icons-vue'

const props = defineProps<{
  stages: { stage: string; status: string; error?: string; message?: string }[]
}>()

defineEmits<{
  retry: [stageKey: string]
}>()

const STAGE_TITLES: Record<string, string> = {
  source_prep: '源文件准备', convert: '格式转换', raw_parse: 'MinerU 解析',
  popo: 'PoPo 增强', structure: '结构化入库', fts: '全文索引',
  vectors: '向量索引', graph: '知识图谱', sop: 'SOP 生成',
}
const PIPELINE_ORDER = Object.keys(STAGE_TITLES)

const orderedStages = computed(() =>
  PIPELINE_ORDER.map(key => {
    const found = props.stages.find(s => s.stage === key) || {}
    return { key, title: STAGE_TITLES[key], status: found.status || 'pending', error: found.error || '', message: found.message || '' }
  })
)

const failedStages = computed(() => orderedStages.value.filter(s => s.status === 'failed'))
const hasFailedStage = computed(() => failedStages.value.length > 0)
const failedStageMessage = computed(() =>
  failedStages.value.map(s => `[${s.title}] ${s.error}`).join('\n')
)

function stepStatus(status: string): string {
  const map: Record<string, string> = {
    completed: 'finish', running: 'process', failed: 'error',
    skipped: 'wait', pending: 'wait',
  }
  return map[status] || 'wait'
}

function stageDescription(stage: { status: string; error: string; message: string }): string {
  if (stage.status === 'running') return '进行中...'
  if (stage.status === 'failed') return stage.error?.split('\n')[0] || '失败'
  if (stage.status === 'completed' && stage.message) return stage.message
  if (stage.status === 'skipped') return '已跳过'
  return '等待中'
}

async function copyError() {
  try {
    await navigator.clipboard.writeText(failedStageMessage.value)
    message.success('错误信息已复制')
  } catch {
    message.error('复制失败')
  }
}
</script>

<style lang="less" scoped>
.doc-stage-stepper {
  :deep(.ant-steps-item-description) {
    font-size: 12px;
    max-width: 360px;
  }
  .stage-error-copy {
    margin-top: 12px;
    padding: 8px 12px;
    background: var(--bg-tertiary, #f5f5f5);
    border-radius: 6px;
  }
}
</style>
