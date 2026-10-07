<template>
  <a-modal
    :open="open"
    title="已有评测正在运行"
    ok-text="仍然开始"
    cancel-text="取消"
    :ok-button-props="{ loading: submitting }"
    @ok="emit('confirm')"
    @cancel="emit('cancel')"
  >
    <div class="eval-busy">
      <p class="eval-busy__lead">
        现在有 {{ running.length }} 个评测在跑。评测链路（问答生成 + 判分）共用同一套后端，
        再起一个会互相拖慢、也可能让判分更容易超时。
      </p>
      <ul class="eval-busy__list">
        <li v-for="run in running" :key="run.run_id" class="eval-busy__item">
          <div class="eval-busy__title">{{ run.dataset_title || run.dataset_id }}</div>
          <div class="eval-busy__meta">
            {{ run.model || '默认模型' }} · {{ run.completed_questions }}/{{ run.total_questions }} 题
            · {{ formatTime(run.started_at) }} 开始
          </div>
        </li>
      </ul>
      <p class="eval-busy__hint">
        点「仍然开始」= 与上述评测并发运行；点「取消」= 放弃本次发起。
      </p>
    </div>
  </a-modal>
</template>

<script setup lang="ts">
/** 「已有评测在跑」确认弹框：列出在跑评测，由用户拍板是否并发。
 * 旧行为是后端直接 400 + 一条 toast（用户只能放弃），2026-09-27 用户要求改成自己决定。 */
import type { EvalRunningRun } from '../types/eval'

defineProps<{
  open: boolean
  running: EvalRunningRun[]
  /** 点「仍然开始」后请求在跑：按钮转圈避免重复点击 */
  submitting?: boolean
}>()

const emit = defineEmits<{
  confirm: []
  cancel: []
}>()

const formatTime = (iso?: string | null): string => {
  if (!iso) return '—'
  // 与 EvalRunPanel.formatTime 同口径：历史裸串按 UTC 读（容器 UTC 写入早 8 小时）
  const hasOffset = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(iso)
  const d = new Date(hasOffset ? iso : `${iso}Z`)
  if (Number.isNaN(d.getTime())) return '—'
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const mi = String(d.getMinutes()).padStart(2, '0')
  return `${mm}-${dd} ${hh}:${mi}`
}
</script>

<style lang="less" scoped>
.eval-busy {
  &__lead {
    margin: 0 0 12px;
    color: var(--text-secondary);
    line-height: 1.6;
  }

  &__list {
    margin: 0;
    padding: 0;
    list-style: none;
    max-height: 240px;
    overflow-y: auto;
  }

  &__item {
    padding: 8px 10px;
    margin-bottom: 8px;
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    border-radius: 6px;

    &:last-child {
      margin-bottom: 0;
    }
  }

  &__title {
    color: var(--text-primary);
    font-weight: 500;
  }

  &__meta {
    margin-top: 2px;
    font-size: 12px;
    color: var(--text-tertiary);
  }

  &__hint {
    margin: 12px 0 0;
    font-size: 12px;
    color: var(--text-tertiary);
  }
}
</style>
