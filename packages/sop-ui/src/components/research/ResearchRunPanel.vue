<template>
  <a-card class="research-run-panel" :body-style="{ padding: '16px' }">
    <a-spin :spinning="loading">
      <template v-if="run">
        <div class="run-header">
          <span class="run-label">运行状态</span>
          <a-tag :color="statusColor">{{ statusText }}</a-tag>
        </div>

        <!-- 7 步进度指示器 -->
        <div class="stage-steps">
          <div
            v-for="(s, idx) in stageSteps"
            :key="s.key"
            class="step-item"
            :class="{
              done: isStepDone(idx),
              active: isStepActive(idx),
              pending: isStepPending(idx),
              failed: run.status === 'failed' && isStepActive(idx),
            }"
          >
            <div class="step-dot">
              <CheckOutlined v-if="isStepDone(idx)" />
              <LoadingOutlined v-else-if="isStepActive(idx) && isRunning" />
              <span v-else class="step-num">{{ idx + 1 }}</span>
            </div>
            <div class="step-text">{{ s.short }}</div>
          </div>
        </div>

        <div class="run-stage" v-if="run.stage">
          <div class="stage-label">
            <span>{{ stageLabel }}</span>
            <span v-if="run.stage_total > 0" class="stage-count">
              · {{ stageUnitLabel }} {{ run.stage_current }}/{{ run.stage_total }}
            </span>
          </div>
          <div class="stage-message" v-if="run.stage_message">{{ run.stage_message }}</div>
          <div class="stage-detail" v-if="run.stage_detail">
            <LoadingOutlined v-if="isRunning" class="stage-detail-icon" />
            <span>{{ run.stage_detail }}</span>
          </div>
        </div>

        <a-progress
          v-if="run.status !== 'completed' && run.status !== 'failed' && run.status !== 'cancelled'"
          :percent="Math.round(run.progress * 100)"
          :stroke-color="progressColor"
          class="run-progress"
        />

        <div v-if="run.error" class="run-error">
          <a-alert type="error" :message="run.error" banner />
        </div>

        <div class="run-actions">
          <a-button
            v-if="canStart"
            type="primary"
            size="small"
            @click="emit('start-run')"
          >
            <template #icon><PlayCircleOutlined /></template>
            {{ startButtonText }}
          </a-button>
          <a-button
            v-if="canStop"
            size="small"
            @click="emit('stop-run')"
          >
            <template #icon><StopOutlined /></template>
            停止运行
          </a-button>
        </div>
      </template>

      <div v-else class="run-empty">
        <PlayCircleOutlined class="run-empty-icon" />
        <span>暂无运行记录</span>
        <a-button type="primary" size="small" @click="emit('start-run')">
          开始新的运行
        </a-button>
      </div>
    </a-spin>
  </a-card>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ResearchRun } from '../../types/sopResearch'
import {
  PlayCircleOutlined, StopOutlined,
  LoadingOutlined, CheckOutlined,
} from '@ant-design/icons-vue'

interface Props {
  run: ResearchRun | null
  loading: boolean
}

const props = defineProps<Props>()

const emit = defineEmits<{
  'start-run': []
  'stop-run': []
  'retry-run': []
}>()

const stageSteps = [
  { key: 'evidence_prepare', short: '准备证据' },
  { key: 'candidate_extract', short: '提取候选' },
  { key: 'socratic_expand', short: '苏格拉底' },
  { key: 'sop_synthesize', short: '综合SOP' },
  { key: 'eval_generate', short: '生成评估' },
  { key: 'rule_validate', short: '规则验证' },
  { key: 'score_and_rank', short: '评分排序' },
]

const stageOrder = computed(() => stageSteps.map(s => s.key))

// 运行中（含已请求取消）的所有状态，用于判断是否显示 loading / 进度
const activeStatuses = ['running', 'queued', 'evidence_prepare', 'candidate_extract', 'socratic_expand', 'sop_synthesize', 'eval_generate', 'rule_validate', 'score_and_rank', 'cancel_requested']
// 可被用户主动停止的状态（cancel_requested 已在取消中，不可重复请求）
const stoppableStatuses = ['running', 'queued', 'evidence_prepare', 'candidate_extract', 'socratic_expand', 'sop_synthesize', 'eval_generate', 'rule_validate', 'score_and_rank']

const isRunning = computed(() => {
  if (!props.run) return false
  return activeStatuses.includes(props.run.status)
})

const currentStepIndex = computed(() => {
  if (!props.run) return -1
  return stageOrder.value.indexOf(props.run.stage)
})

function isStepDone(idx: number): boolean {
  if (!props.run) return false
  if (props.run.status === 'completed') return true
  return idx < currentStepIndex.value
}

function isStepActive(idx: number): boolean {
  if (!props.run) return false
  return idx === currentStepIndex.value
}

function isStepPending(idx: number): boolean {
  if (!props.run) return false
  return idx > currentStepIndex.value
}

const statusColor = computed(() => {
  if (!props.run) return 'default'
  const s = props.run.status
  if (s === 'completed') return 'success'
  if (s === 'failed') return 'error'
  if (s === 'cancelled') return 'default'
  return 'processing'
})

const statusText = computed(() => {
  if (!props.run) return ''
  const s = props.run.status
  if (s === 'completed') return '已完成'
  if (s === 'failed') return '失败'
  if (s === 'cancelled') return '已取消'
  if (s === 'cancel_requested') return '取消中'
  return '运行中'
})

const stageLabel = computed(() => {
  if (!props.run) return ''
  const map: Record<string, string> = {
    queued: '排队中',
    evidence_prepare: '阶段 1/7 · 准备证据',
    candidate_extract: '阶段 2/7 · 提取候选',
    socratic_expand: '阶段 3/7 · 苏格拉底扩展',
    sop_synthesize: '阶段 4/7 · 综合 SOP',
    eval_generate: '阶段 5/7 · 生成评估',
    rule_validate: '阶段 6/7 · 规则验证',
    score_and_rank: '阶段 7/7 · 评分排序',
    completed: '已完成',
    failed: '失败',
    cancel_requested: '正在取消',
    cancelled: '已取消',
  }
  return map[props.run.stage] || props.run.stage
})

// 根据 stage 显示对应的单位标签，让 (3/15) 这样的数字有意义
const stageUnitLabel = computed(() => {
  if (!props.run) return ''
  const map: Record<string, string> = {
    evidence_prepare: '',
    candidate_extract: '证据包',
    socratic_expand: '候选',
    sop_synthesize: '候选',
    eval_generate: 'SOP草稿',
    rule_validate: 'SOP草稿',
    score_and_rank: 'SOP草稿',
  }
  return map[props.run.stage] || ''
})

const progressColor = computed(() => {
  if (!props.run) return '#1890ff'
  if (props.run.status === 'failed') return '#ff4d4f'
  return '#52c41a'
})

const canStart = computed(() => {
  if (!props.run) return true
  // 任何时候都可以重新运行（包括僵尸 run）
  return !isRunning.value
})

const startButtonText = computed(() => {
  if (!props.run) return '开始新的运行'
  if (props.run.status === 'failed') return '重新运行'
  if (props.run.status === 'completed') return '重新运行'
  if (props.run.status === 'cancelled') return '重新运行'
  return '开始运行'
})

const canStop = computed(() => {
  if (!props.run) return false
  return stoppableStatuses.includes(props.run.status)
})
</script>

<style lang="less" scoped>
.research-run-panel {
  .run-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 12px;

    .run-label {
      font-weight: 500;
      font-size: 13px;
    }
  }

  .stage-steps {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    margin-bottom: 14px;
    gap: 2px;

    .step-item {
      flex: 1;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 3px;
      min-width: 0;

      .step-dot {
        width: 18px;
        height: 18px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 10px;
        font-weight: 500;
        background: var(--bg-tertiary);
        color: var(--text-tertiary, #999);

        .step-num {
          font-size: 10px;
        }
      }

      .step-text {
        font-size: 10px;
        color: var(--text-tertiary, #999);
        text-align: center;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        max-width: 100%;
      }

      &.done {
        .step-dot {
          background: #52c41a;
          color: #fff;
        }
        .step-text {
          color: var(--text-secondary);
        }
      }

      &.active {
        .step-dot {
          background: #1890ff;
          color: #fff;
        }
        .step-text {
          color: #1890ff;
          font-weight: 500;
        }

        &.failed .step-dot {
          background: #ff4d4f;
        }
      }

      &.pending {
        opacity: 0.5;
      }
    }
  }

  .run-stage {
    margin-bottom: 12px;

    .stage-label {
      font-weight: 500;
      font-size: 13px;
      margin-bottom: 4px;

      .stage-count {
        font-weight: 400;
        color: var(--text-secondary);
      }
    }

    .stage-message {
      font-size: 12px;
      color: var(--text-secondary);
      margin-bottom: 2px;
    }

    .stage-detail {
      font-size: 12px;
      color: var(--text-tertiary);
      display: flex;
      align-items: flex-start;
      gap: 4px;
      line-height: 1.4;
      margin-top: 4px;
      padding: 6px 8px;
      background: var(--bg-secondary);
      border-radius: 4px;

      .stage-detail-icon {
        font-size: 11px;
        margin-top: 2px;
        animation: spin 1s linear infinite;
        flex-shrink: 0;
      }
    }
  }

  .run-progress {
    margin-bottom: 12px;
  }

  .run-error {
    margin-bottom: 12px;
  }

  .run-actions {
    display: flex;
    gap: 8px;
  }

  .run-empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 12px;
    padding: 24px 0;
    color: var(--text-secondary);

    .run-empty-icon {
      font-size: 36px;
      opacity: 0.3;
    }
  }
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
