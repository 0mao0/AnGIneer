<template>
  <div
    v-for="flow in flows"
    :key="flow.sop_id"
    class="sop-flow-card"
  >
    <div class="sop-flow-head">
      <button
        type="button"
        class="sop-flow-header"
        @click="toggleFlow(flow.sop_id)"
      >
        <PartitionOutlined class="sop-flow-icon" />
        <span class="sop-flow-label">
          SOP 流程
          <template v-if="flow.sop_name">· {{ flow.sop_name }}</template>
          <span class="sop-flow-count">
            （{{ flow.done }}/{{ flow.total }} 步<template v-if="totalDurationText(flow)"> · {{ totalDurationText(flow) }}</template>）
          </span>
        </span>
        <span v-if="flow.running" class="sop-flow-running">
          <LoadingOutlined spin />
          执行中
        </span>
        <span class="sop-flow-arrow">
          <DownOutlined v-if="isExpanded(flow.sop_id)" />
          <RightOutlined v-else />
        </span>
      </button>
      <!-- 扩展位：宿主可放「查看流程图」等入口（未提供插槽时零渲染，独立包消费方不受影响） -->
      <span class="sop-flow-action">
        <slot name="flow-action" :flow="flow" />
      </span>
    </div>
    <div v-if="isExpanded(flow.sop_id)" class="sop-flow-body">
      <div
        v-for="(step, idx) in flow.steps"
        :key="step.step_id"
        class="sop-flow-step"
        :class="`is-${step.status}`"
      >
        <span class="sop-flow-step-rail">
          <CheckCircleFilled v-if="step.status === 'success'" class="sop-flow-dot dot-success" />
          <CloseCircleFilled v-else-if="step.status === 'failed'" class="sop-flow-dot dot-failed" />
          <LoadingOutlined v-else-if="flow.running" class="sop-flow-dot dot-running" spin />
          <span v-else class="sop-flow-dot dot-pending"></span>
          <span v-if="idx < flow.steps.length - 1" class="sop-flow-step-line"></span>
        </span>
        <span class="sop-flow-step-content">
          <span class="sop-flow-step-index">{{ idx + 1 }}.</span>
          <span class="sop-flow-step-name">{{ step.step_name }}</span>
          <span v-if="step.tool && step.tool !== 'auto'" class="sop-flow-step-tool">{{ step.tool }}</span>
          <span v-if="step.duration_ms" class="sop-flow-step-duration">{{ formatStepDuration(step.duration_ms) }}</span>
          <span v-if="step.error" class="sop-flow-step-error" :title="step.error">{{ step.error }}</span>
          <!-- 参数与结果（2026-10-16）：绿步也带出代入的参数值和算出的结果 -->
          <span
            v-if="stepParamsText(step)"
            class="sop-flow-step-params"
            :title="stepParamsText(step)"
          >{{ stepParamsText(step) }}</span>
        </span>
      </div>
      <div v-if="flow.missing_report?.length" class="sop-flow-missing">
        缺参：{{ missingText(flow.missing_report) }}——请补充后重问（系统不臆造数值，推荐值仅供参考）
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * SOP 流程卡片（2026-10-14 业主需求：L3/L4 聊天里可见 SOP 步骤流、可折叠）。
 * 数据源两类、shape 一致：live 期 sop_flow 事件快照、回放/历史从工具消息重建。
 * 折叠行为对齐思考过程卡片：默认状态由 defaultExpanded 决定，用户点按优先。
 */
import { ref } from 'vue'
import {
  PartitionOutlined,
  DownOutlined,
  RightOutlined,
  CheckCircleFilled,
  CloseCircleFilled,
  LoadingOutlined
} from '@ant-design/icons-vue'
import type { SopFlowState } from '../types'

const props = withDefaults(defineProps<{
  flows: SopFlowState[]
  /** 新出现的流程默认展开与否（流式期传 true，历史消息传 false） */
  defaultExpanded?: boolean
}>(), {
  defaultExpanded: false
})

/** 用户显式点按过的折叠状态（按 sop_id 记忆，未点按回落 defaultExpanded） */
const userToggled = ref<Map<string, boolean>>(new Map())

const isExpanded = (sopId: string) =>
  userToggled.value.get(sopId) ?? props.defaultExpanded

const toggleFlow = (sopId: string) => {
  const next = new Map(userToggled.value)
  next.set(sopId, !isExpanded(sopId))
  userToggled.value = next
}

const formatStepDuration = (ms: number) =>
  ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`

const totalDurationText = (flow: SopFlowState) => {
  const sum = flow.steps.reduce((acc, step) => acc + (step.duration_ms || 0), 0)
  return sum > 0 ? formatStepDuration(sum) : ''
}

/** 缺参清单成句：参数名 + 推荐值（与 sop_execute 汇总话术同构） */
const missingText = (items: NonNullable<SopFlowState['missing_report']>) =>
  items.slice(0, 6).map(item => {
    const seg = String(item.param || '')
    if (item.recommend !== undefined && item.recommend !== null && item.recommend !== '') {
      return `${seg}（建议 ${item.recommend}${item.unit || ''}）`
    }
    return seg
  }).join('、')

/** 数值展示：浮点收敛到 6 位、整数不带小数、非有限值退字符串 */
const formatParamValue = (value: string | number | null): string => {
  if (value === null || value === undefined) return '缺'
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return String(value)
    return Number.isInteger(value) ? String(value) : String(Math.round(value * 1e6) / 1e6)
  }
  const text = String(value)
  return text.length > 24 ? text.slice(0, 24) + '…' : text
}

/** 单步「参数=值 → 结果」一行文本；无绑定也无结果时返回空串（不占位） */
const stepParamsText = (step: SopFlowState['steps'][number]): string => {
  const parts: string[] = []
  if (step.bindings) {
    for (const [name, value] of Object.entries(step.bindings)) {
      parts.push(`${name}=${formatParamValue(value)}`)
    }
  }
  const head = parts.join('、')
  const tail = step.result !== undefined && step.result !== null
    ? ` → ${formatParamValue(step.result)}`
    : ''
  if (!head && !tail) return ''
  return head ? `${head}${tail}` : tail.replace(/^ → /, '结果 ')
}
</script>

<style lang="less" scoped>
.sop-flow-card {
  margin: 0 0 10px;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  background: rgba(128, 128, 128, 0.05);
  overflow: hidden;

  .sop-flow-head {
    display: flex;
    align-items: center;
  }

  .sop-flow-action {
    display: inline-flex;
    align-items: center;
    flex-shrink: 0;
    padding-right: 10px;
  }

  .sop-flow-header {
    display: flex;
    align-items: center;
    gap: 6px;
    flex: 1;
    min-width: 0;
    padding: 6px 10px;
    border: none;
    background: transparent;
    color: var(--text-secondary);
    font-size: 12px;
    line-height: 1.4;
    text-align: left;
    cursor: pointer;

    &:hover {
      background: rgba(128, 128, 128, 0.08);
    }

    .sop-flow-icon {
      display: inline-flex;
      align-items: center;
      font-size: 13px;
      color: var(--text-tertiary, #999);
    }

    .sop-flow-label {
      flex: 1;
      font-weight: 500;

      .sop-flow-count {
        font-weight: 400;
        color: var(--text-secondary);
      }
    }

    .sop-flow-running {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      flex-shrink: 0;
      font-size: 11px;
      color: var(--text-tertiary, #999);
    }

    .sop-flow-arrow {
      display: inline-flex;
      align-items: center;
      font-size: 10px;
      flex-shrink: 0;
    }
  }

  .sop-flow-body {
    padding: 6px 10px 10px;
    border-top: 1px solid var(--border-color);
    display: flex;
    flex-direction: column;
    font-size: 12px;
    line-height: 1.6;
    color: var(--text-secondary);
  }

  .sop-flow-step {
    display: flex;
    align-items: stretch;
    gap: 8px;
    min-height: 22px;

    .sop-flow-step-rail {
      display: flex;
      flex-direction: column;
      align-items: center;
      flex-shrink: 0;
      padding-top: 3px;
      width: 14px;

      .sop-flow-dot {
        font-size: 12px;
        line-height: 1;
      }

      .dot-success {
        color: #52c41a;
      }

      .dot-failed {
        color: #ff4d4f;
      }

      .dot-running {
        color: var(--text-tertiary, #999);
      }

      .dot-pending {
        width: 8px;
        height: 8px;
        border: 1px solid var(--text-tertiary, #bbb);
        border-radius: 50%;
      }

      .sop-flow-step-line {
        flex: 1;
        width: 0;
        margin: 2px 0;
        border-left: 1px dashed var(--border-color);
      }
    }

    .sop-flow-step-content {
      display: flex;
      align-items: baseline;
      flex-wrap: wrap;
      gap: 6px;
      padding-bottom: 4px;

      .sop-flow-step-index {
        color: var(--text-tertiary, #999);
      }

      .sop-flow-step-name {
        font-weight: 500;
      }

      .sop-flow-step-tool,
      .sop-flow-step-duration {
        padding: 0 6px;
        border: 1px solid var(--border-color);
        border-radius: 6px;
        font-size: 11px;
        color: var(--text-tertiary, #999);
        background: rgba(128, 128, 128, 0.05);
      }

      .sop-flow-step-error {
        width: 100%;
        color: #ff4d4f;
        font-size: 11px;
      }

      .sop-flow-step-params {
        width: 100%;
        font-size: 11px;
        line-height: 1.5;
        color: var(--text-tertiary, #999);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
    }

    &.is-pending .sop-flow-step-content .sop-flow-step-name {
      font-weight: 400;
      color: var(--text-tertiary, #999);
    }
  }

  .sop-flow-missing {
    margin-top: 4px;
    padding: 4px 8px;
    border-left: 2px solid #faad14;
    background: rgba(250, 173, 20, 0.08);
    border-radius: 0 6px 6px 0;
    font-size: 11px;
    line-height: 1.5;
    color: var(--text-secondary);
  }
}
</style>
