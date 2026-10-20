<template>
  <div v-if="steps.length" class="sop-steps">
    <div class="sop-steps__title">SOP 步骤（{{ steps.length }} 步）</div>
    <details v-for="step in steps" :key="step.step_id" class="sop-step">
      <summary class="sop-step__head">
        <span class="sop-step__index">{{ step.step_index }}</span>
        <span class="sop-step__name">{{ step.step_name || step.step_id }}</span>
        <span class="sop-step__tool">{{ step.tool }}</span>
        <a-tag :color="statusColor(step.status)" class="sop-step__status">{{ step.status }}</a-tag>
        <span v-if="step.duration" class="sop-step__duration">{{ step.duration.toFixed(2) }}s</span>
      </summary>
      <div class="sop-step__body">
        <div v-if="step.description" class="sop-step__desc">{{ step.description }}</div>
        <div v-if="step.error" class="sop-step__error">错误：{{ step.error }}</div>
        <div class="sop-step__label">输入</div>
        <pre class="sop-step__code">{{ pretty(step.inputs) }}</pre>
        <div class="sop-step__label">输出</div>
        <pre class="sop-step__code">{{ pretty(step.outputs) }}</pre>
      </div>
    </details>
  </div>
</template>

<script setup lang="ts">
import type { EvalSopTraceStep } from '../types/eval'

defineProps<{
  steps: EvalSopTraceStep[]
}>()

function statusColor(status: string): string | undefined {
  if (status === 'success') return 'success'
  if (['error', 'failed', 'fail'].includes(status)) return 'error'
  return undefined
}

function pretty(value: unknown): string {
  if (value === null || value === undefined) return '—'
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}
</script>

<style lang="less" scoped>
.sop-steps {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px dashed @evals-border-color;

  &__title {
    margin-bottom: 6px;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.02em;
    color: @evals-text-secondary;
  }
}

.sop-step {
  border-bottom: 1px solid @evals-border-color;

  &__head {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 0;
    cursor: pointer;
    list-style: none;
    font-size: 12px;

    &::-webkit-details-marker {
      display: none;
    }

    &::before {
      content: '▸';
      flex: none;
      width: 12px;
      text-align: center;
      color: @evals-text-secondary;
      font-size: 10px;
    }
  }

  &[open] > .sop-step__head::before {
    content: '▾';
  }

  &__index {
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 18px;
    height: 18px;
    border-radius: 50%;
    background: fade(@evals-primary, 14%);
    color: @evals-primary;
    font-size: 10px;
  }

  &__name {
    font-weight: 600;
    color: @evals-text-primary;
  }

  &__tool {
    color: @evals-text-secondary;
    font-size: 11px;
  }

  &__status {
    margin-inline-end: 0;
  }

  &__duration {
    margin-left: auto;
    color: @evals-text-secondary;
    font-size: 11px;
  }

  &__body {
    padding: 2px 0 10px 32px;
  }

  &__desc {
    color: @evals-text-secondary;
    font-size: 12px;
    line-height: 1.6;
  }

  &__error {
    margin-top: 4px;
    color: @evals-error;
    font-size: 12px;
  }

  &__label {
    margin-top: 8px;
    color: @evals-text-secondary;
    font-size: 11px;
  }

  &__code {
    margin: 4px 0 0;
    padding: 8px;
    border-radius: 4px;
    background: var(--bg-tertiary, rgba(255, 255, 255, 0.04));
    color: @evals-text-primary;
    font-family: Consolas, 'Courier New', monospace;
    font-size: 11px;
    line-height: 1.5;
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 200px;
    overflow: auto;
  }
}
</style>
