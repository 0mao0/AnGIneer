<template>
  <a-tooltip placement="top" :mouse-enter-delay="0.2">
    <template #title>
      <div class="arch-tip">
        <div class="arch-tip-title">{{ data.label }}</div>
        <div class="arch-tip-summary">{{ data.summary }}</div>
        <div v-if="data.anchors?.length" class="arch-tip-anchor">{{ data.anchors[0] }}</div>
        <div class="arch-tip-hint">点击查看详情</div>
      </div>
    </template>
    <div class="arch-node" :class="[`st-${data.status}`, { dimmed, 'has-problem': !!data.problems?.length }]">
      <Handle id="t-t" type="target" :position="Position.Top" class="arch-handle" />
      <Handle id="t-b" type="target" :position="Position.Bottom" class="arch-handle" />
      <Handle id="t-l" type="target" :position="Position.Left" class="arch-handle" />
      <Handle id="t-r" type="target" :position="Position.Right" class="arch-handle" />
      <div class="arch-node-label">{{ data.label }}</div>
      <div v-if="data.sub" class="arch-node-sub">{{ data.sub }}</div>
      <div v-if="data.problems?.length" class="arch-node-badge" :title="problemTitles">
        {{ data.problems.join(' ') }}
      </div>
      <Handle id="s-b" type="source" :position="Position.Bottom" class="arch-handle" />
      <Handle id="s-t" type="source" :position="Position.Top" class="arch-handle" />
      <Handle id="s-l" type="source" :position="Position.Left" class="arch-handle" />
      <Handle id="s-r" type="source" :position="Position.Right" class="arch-handle" />
    </div>
  </a-tooltip>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import type { ArchNodeData } from './archData'
import { ARCH_PROBLEMS } from './archData'

const props = defineProps<{
  data: ArchNodeData
  dimmed?: boolean
}>()

const problemTitles = computed(() =>
  (props.data.problems ?? [])
    .map((pid) => ARCH_PROBLEMS.find((p) => p.id === pid)?.title ?? pid)
    .join('\n')
)
</script>

<style lang="less" scoped>
.arch-node {
  position: relative;
  width: 210px;
  min-height: 58px;
  padding: 8px 12px;
  border-radius: 8px;
  background: var(--bg-secondary, #fff);
  border: 2px solid var(--border-color, #d9d9d9);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
  cursor: pointer;
  transition: opacity 0.25s, box-shadow 0.2s, transform 0.15s;

  &:hover {
    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.16);
    transform: translateY(-1px);
  }

  &.dimmed {
    opacity: 0.18;
  }

  &.st-ok { border-color: #52c41a; }
  &.st-warn { border-color: #fa8c16; }
  &.st-gap { border-color: #f5222d; }
  &.st-planned {
    border-color: #722ed1;
    border-style: dashed;
    background: rgba(114, 46, 209, 0.06);
  }

  &.has-problem::before {
    content: '';
    position: absolute;
    top: -3px;
    right: -3px;
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background: #f5222d;
    animation: pulse 1.6s ease-in-out infinite;
  }
}

@keyframes pulse {
  0%, 100% { transform: scale(1); opacity: 1; }
  50% { transform: scale(1.35); opacity: 0.55; }
}

.arch-node-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary, rgba(0, 0, 0, 0.88));
  line-height: 1.3;
}

.arch-node-sub {
  margin-top: 2px;
  font-size: 11px;
  color: var(--text-secondary, rgba(0, 0, 0, 0.45));
  line-height: 1.3;
}

.arch-node-badge {
  position: absolute;
  bottom: -9px;
  right: 8px;
  padding: 0 6px;
  border-radius: 8px;
  background: #f5222d;
  color: #fff;
  font-size: 10px;
  font-weight: 700;
  line-height: 16px;
  letter-spacing: 0.5px;
}

.arch-handle {
  opacity: 0;
  pointer-events: none;
}

.arch-tip {
  max-width: 300px;

  .arch-tip-title {
    font-weight: 600;
    margin-bottom: 2px;
  }

  .arch-tip-summary {
    font-size: 12px;
    line-height: 1.5;
  }

  .arch-tip-anchor {
    margin-top: 4px;
    font-family: monospace;
    font-size: 11px;
    opacity: 0.75;
  }

  .arch-tip-hint {
    margin-top: 4px;
    font-size: 11px;
    opacity: 0.6;
  }
}
</style>
