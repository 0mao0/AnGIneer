/**
 * SOP 分叉节点组件，紧凑型条件判断节点，支持多条出边（每边代表一个分支条件）。
 */
<template>
  <div
    class="sop-fork-node"
    :class="{ selected: selected, hovered: hovered, dirty: isDirty }"
    @mouseenter="hovered = true"
    @mouseleave="hovered = false"
  >
    <span v-if="isDirty" class="node-dirty-dot" />
    <Handle id="top" type="target" :position="Position.Top" class="handle handle-top" />
    <button
      v-if="deletable && (hovered || selected)"
      type="button"
      class="node-delete-btn"
      title="删除分叉节点"
      @click.stop="emit('delete')"
    >
      <DeleteOutlined />
    </button>
    <div class="fork-body">
      <span class="fork-icon"><BranchesOutlined /></span>
      <span class="fork-var">{{ conditionVarDisplay }}</span>
      <span class="fork-badge">{{ branchEdges.length > 0 ? branchEdges.length : '?' }}</span>
    </div>
    <Handle
      v-for="(branch, idx) in branchEdges"
      :key="branch.id"
      :id="`branch-${idx}`"
      type="source"
      :position="Position.Bottom"
      :style="branchHandleStyle(idx, branchEdges.length)"
      class="handle handle-branch"
    />
    <Handle
      v-if="branchEdges.length === 0"
      id="branch-0"
      type="source"
      :position="Position.Bottom"
      class="handle handle-branch"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, inject, ref, type Ref } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import { DeleteOutlined, BranchesOutlined } from '@ant-design/icons-vue'
import type { SopStep } from '../types/sop'

const props = defineProps<{
  id: string
  data: { step: SopStep; stepIndex: number; dirty?: boolean }
  selected?: boolean
  deletable?: boolean
}>()

const emit = defineEmits<{
  delete: []
}>()

const hovered = ref(false)

const dirtyStepIds = inject<Ref<Set<string> | undefined>>('dirtyStepIds', ref(new Set()))
const isDirty = computed(() => dirtyStepIds.value?.has(props.id) ?? false)

const branchEdges = computed(() => {
  return (props.data as any)?.branchEdges as Array<{
    id: string; label: string; target: string; isDefault?: boolean
  }> ?? []
})

const conditionVarDisplay = computed(() => {
  const raw = props.data?.step?.condition_var
    || props.data?.step?.execution?.inputs?.condition_var
    || ''
  return raw.replace(/^\$\{(.+)\}$/, '$1')
})

const branchHandleStyle = (idx: number, total: number): Record<string, string> => {
  if (total <= 1) return {}
  const pct = ((idx + 1) / (total + 1)) * 100
  return { left: `${pct}%` }
}
</script>

<style lang="less" scoped>
.sop-fork-node {
  min-width: 150px;
  max-width: 220px;
  height: 40px;
  padding: 0 12px;
  border-radius: 6px;
  background: var(--panel-bg, #fff);
  border: 2px solid rgba(250, 173, 20, 0.45);
  border-left: 4px solid rgba(250, 173, 20, 0.55);
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.06);
  transition: border-color 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease;
  cursor: pointer;
  position: relative;
  display: flex;
  align-items: center;

  &:hover,
  &.hovered {
    border-color: rgba(250, 173, 20, 0.7);
    border-left-color: rgba(250, 173, 20, 0.85);
    box-shadow: 0 6px 14px rgba(250, 173, 20, 0.14);
    transform: translateY(-1px);
  }

  &.selected {
    border-color: var(--warning-color, #faad14);
    border-left-color: var(--warning-color, #faad14);
    box-shadow:
      0 0 0 2px rgba(250, 173, 20, 0.2),
      0 8px 18px rgba(250, 173, 20, 0.16);
    transform: translateY(-1px);
  }
}

.node-dirty-dot {
  position: absolute;
  top: -6px;
  left: -6px;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: #ff4d4f;
  z-index: 4;
  box-shadow: 0 0 0 2px rgba(255, 77, 79, 0.2);
}

.node-delete-btn {
  position: absolute;
  top: -9px;
  right: -9px;
  width: 20px;
  height: 20px;
  border: 1px solid rgba(255, 77, 79, 0.35);
  border-radius: 50%;
  background: var(--panel-bg, #fff);
  color: #ff4d4f;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.12);
  transition: all 0.2s ease;
  z-index: 3;
  font-size: 10px;

  &:hover {
    background: #ff4d4f;
    color: #fff;
  }
}

.fork-body {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  overflow: hidden;
}

.fork-icon {
  font-size: 16px;
  color: var(--warning-color, #faad14);
  flex-shrink: 0;
}

.fork-var {
  flex: 1;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary, #262626);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.fork-badge {
  flex-shrink: 0;
  font-size: 10px;
  font-weight: 600;
  color: var(--warning-color, #faad14);
  background: rgba(250, 173, 20, 0.1);
  border-radius: 10px;
  padding: 0 6px;
  height: 18px;
  line-height: 18px;
}

.handle {
  width: 10px;
  height: 10px;
  border-width: 2px;
  background: rgba(250, 173, 20, 0.15);
  border-color: rgba(250, 173, 20, 0.45);
  box-shadow: none;
  transition: border-color 0.2s ease, background-color 0.2s ease;
  z-index: 5;
}

.handle-top {
  transform: translate(-50%, -7px);
}

.handle-branch {
  transform: translate(-50%, 7px);
}
</style>
