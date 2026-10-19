<template>
  <div class="eval-trace">
    <div class="eval-trace__title">
      {{ title || '知识问答' }}
      <a-spin v-if="evaluating" size="small" class="eval-trace__spinner" />
    </div>

    <div v-if="!rows.length" class="eval-trace__empty">无事件 trace（该 run 没有落事件流）</div>

    <div
      v-for="row in rows"
      :key="row.key"
      class="eval-trace__row"
      :class="`eval-trace__row--${row.kind}`"
    >
      <template v-if="row.kind === 'intent'">
        <span class="eval-trace__badge">意</span>
        <div class="eval-trace__body">
          <div class="eval-trace__head">
            <a-tag v-if="row.timing !== undefined" color="processing" class="eval-trace__timing">
              {{ row.timing.toFixed(2) }}s
            </a-tag>
            <span class="eval-trace__label">意图识别</span>
            <span class="eval-trace__value">
              {{ row.level }}<template v-if="row.serviceMode"> · {{ row.serviceMode }}</template>
            </span>
          </div>
          <div v-if="row.reason" class="eval-trace__note">{{ row.reason }}</div>
        </div>
      </template>

      <template v-else-if="row.kind === 'turn'">
        <div class="eval-trace__turn">
          <span class="eval-trace__turn-line" />
          <span class="eval-trace__turn-label">{{ row.label }}</span>
          <span class="eval-trace__turn-line" />
        </div>
      </template>

      <template v-else-if="row.kind === 'tool'">
        <span class="eval-trace__badge eval-trace__badge--tool">工具</span>
        <div class="eval-trace__body">
          <div class="eval-trace__head">
            <span class="eval-trace__label">{{ row.name }}</span>
            <a-tag v-if="row.injected" color="blue" class="eval-trace__tag">预检注入</a-tag>
            <a-tag v-if="row.pending" color="warning" class="eval-trace__tag">未完成</a-tag>
            <a-tag v-if="row.isError" color="error" class="eval-trace__tag">失败</a-tag>
            <a-tag v-if="row.durationMs !== undefined" color="processing" class="eval-trace__timing">
              {{ (row.durationMs / 1000).toFixed(2) }}s
            </a-tag>
          </div>
          <details v-if="row.args || row.result" class="eval-trace__details">
            <summary>参数与结果</summary>
            <template v-if="row.args">
              <div class="eval-trace__code-label">参数</div>
              <pre class="eval-trace__code">{{ pretty(row.args) }}</pre>
            </template>
            <template v-if="row.result">
              <div class="eval-trace__code-label">结果预览</div>
              <pre class="eval-trace__code">{{ row.result }}</pre>
            </template>
          </details>
        </div>
      </template>

      <template v-else-if="row.kind === 'note'">
        <span class="eval-trace__badge eval-trace__badge--note">注</span>
        <div class="eval-trace__body">
          <div
            v-if="row.durationMs !== undefined || row.promptTokens !== undefined || row.ttftMs !== undefined"
            class="eval-trace__head"
          >
            <span v-if="row.durationMs !== undefined" class="eval-trace__meta">
              耗时 {{ (row.durationMs / 1000).toFixed(2) }}s
            </span>
            <span v-if="row.promptTokens !== undefined" class="eval-trace__meta">
              prompt {{ row.promptTokens }} tokens
            </span>
            <span v-if="row.ttftMs !== undefined" class="eval-trace__meta">
              TTFT {{ (row.ttftMs / 1000).toFixed(1) }}s
            </span>
          </div>
          <div class="eval-trace__note eval-trace__note--prewrap">{{ row.detail }}</div>
        </div>
      </template>

      <template v-else-if="row.kind === 'error'">
        <span class="eval-trace__badge eval-trace__badge--error">错误</span>
        <div class="eval-trace__body">
          <div class="eval-trace__note">{{ row.message }}</div>
        </div>
      </template>

      <template v-else-if="row.kind === 'run_end'">
        <span class="eval-trace__badge eval-trace__badge--end">终态</span>
        <div class="eval-trace__body">
          <div class="eval-trace__head">
            <span class="eval-trace__label">{{ row.summary.final_outcome || row.summary.reason || '完成' }}</span>
            <span class="eval-trace__value">
              {{ row.summary.turns || 0 }} 轮 · {{ row.summary.tool_calls || 0 }} 次工具<template
                v-if="row.summary.duration_ms"
              > · {{ (row.summary.duration_ms / 1000).toFixed(1) }}s</template>
            </span>
          </div>
          <div v-if="row.summary.path_trace?.length" class="eval-trace__paths">
            <a-tag v-for="path in row.summary.path_trace" :key="path" class="eval-trace__tag">
              {{ path }}
            </a-tag>
          </div>
        </div>
      </template>

      <template v-else>
        <span class="eval-trace__badge eval-trace__badge--unknown">?</span>
        <div class="eval-trace__body">
          <div class="eval-trace__head">
            <span class="eval-trace__label">{{ row.type }}</span>
            <span class="eval-trace__value">未识别事件</span>
          </div>
          <pre class="eval-trace__code">{{ pretty(row.payload) }}</pre>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { EvalTrace } from '../types/eval'
import { buildTraceRows } from '../utils/trace'

const props = defineProps<{
  title?: string
  trace?: EvalTrace | null
  intent?: Record<string, unknown> | null
  stageTimings?: Record<string, number> | null
  evaluating?: boolean
}>()

const rows = computed(() =>
  buildTraceRows({
    trace: props.trace,
    intent: props.intent,
    stageTimings: props.stageTimings,
  })
)

function pretty(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}
</script>

<style lang="less" scoped>
.eval-trace {
  font-size: 12px;

  &__title {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 8px;
    font-size: 13px;
    font-weight: 600;
  }

  &__empty {
    padding: 8px 0;
    color: @evals-text-secondary;
  }

  &__row {
    display: flex;
    gap: 10px;
    padding: 6px 0;

    &--turn {
      padding: 2px 0;
    }
  }

  &__badge {
    flex: none;
    width: 24px;
    height: 24px;
    border-radius: 50%;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 11px;
    color: @evals-primary;
    background: fade(@evals-primary, 14%);

    &--tool {
      color: @evals-success;
      background: fade(@evals-success, 14%);
    }

    &--note {
      color: @evals-warning;
      background: fade(@evals-warning, 14%);
    }

    &--error {
      color: @evals-error;
      background: fade(@evals-error, 14%);
    }

    &--end {
      color: @evals-primary;
      background: fade(@evals-primary, 14%);
    }

    &--unknown {
      color: @evals-text-secondary;
      background: @evals-border-color;
    }
  }

  &__body {
    flex: 1;
    min-width: 0;
  }

  &__head {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 6px;
    min-height: 24px;
  }

  &__label {
    font-weight: 600;
    color: @evals-text-primary;
  }

  &__value,
  &__meta {
    color: @evals-text-secondary;
  }

  &__timing {
    margin-inline-end: 0;
  }

  &__tag {
    margin-inline-end: 0;
  }

  &__note {
    margin-top: 2px;
    color: @evals-text-secondary;
    line-height: 1.6;
    white-space: pre-wrap;
  }

  &__turn {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
    padding: 8px 0 2px;
  }

  &__turn-line {
    flex: 1;
    height: 1px;
    background: @evals-border-color;
  }

  &__turn-label {
    color: @evals-text-secondary;
    font-size: 11px;
  }

  &__details {
    margin-top: 4px;

    summary {
      cursor: pointer;
      color: @evals-primary;
      width: fit-content;
    }
  }

  &__code-label {
    margin-top: 6px;
    color: @evals-text-secondary;
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
    max-height: 240px;
    overflow: auto;
  }

  &__paths {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin-top: 4px;
  }
}
</style>
