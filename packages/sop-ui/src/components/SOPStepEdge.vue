/**
 * SOP 步骤自定义边组件，贝塞尔曲线带箭头，选中时高亮。支持分支条件标签。
 */
<template>
  <BaseEdge :id="id" :style="edgeStyle" :path="path[0]" :marker-end="props.markerEnd" />
  <path
    :d="path[0]"
    fill="none"
    stroke="transparent"
    stroke-width="14"
    class="edge-hitarea"
    @mouseenter="hovered = true"
    @mouseleave="hovered = false"
  />
  <EdgeLabelRenderer v-if="label || isFailure">
    <div
      :style="labelStyle"
      class="sop-edge-label"
      :class="{ 'failure-label': isFailure }"
    >
      {{ isFailure && !label ? '失败' : label }}
    </div>
  </EdgeLabelRenderer>
  <!-- hover 时显示删除按钮 -->
  <EdgeLabelRenderer v-if="hovered || selected">
    <div
      :style="deleteBtnStyle"
      class="sop-edge-delete-btn"
      @click.stop="onDeleteEdge?.(id)"
      @mousedown.stop
    >
      <CloseOutlined />
    </div>
  </EdgeLabelRenderer>
</template>

<script setup lang="ts">
import { computed, inject, ref } from 'vue'
import { BaseEdge, getBezierPath, EdgeLabelRenderer } from '@vue-flow/core'
import type { EdgeProps } from '@vue-flow/core'
import { CloseOutlined } from '@ant-design/icons-vue'

const props = defineProps<EdgeProps>()

const onDeleteEdge = inject<(edgeId: string) => void>('onDeleteEdge', () => {})

const hovered = ref(false)

const isFailure = computed(() => {
  const d = props.data as { isFailure?: boolean } | undefined
  return !!d?.isFailure
})

const label = computed(() => {
  const d = props.data as { label?: string } | undefined
  return d?.label || ''
})

const path = computed(() =>
  getBezierPath({
    sourceX: props.sourceX,
    sourceY: props.sourceY,
    sourcePosition: props.sourcePosition,
    targetX: props.targetX,
    targetY: props.targetY,
    targetPosition: props.targetPosition,
  })
)

const midX = computed(() => (props.sourceX + props.targetX) / 2)
const midY = computed(() => (props.sourceY + props.targetY) / 2)

const labelStyle = computed(() => ({
  position: 'absolute' as const,
  left: `${midX.value}px`,
  top: `${midY.value - 16}px`,
  transform: 'translate(-50%, -50%)',
  pointerEvents: 'none' as const,
}))

const deleteBtnStyle = computed(() => ({
  position: 'absolute' as const,
  left: `${midX.value}px`,
  top: `${midY.value + 12}px`,
  transform: 'translate(-50%, -50%)',
  pointerEvents: 'auto' as const,
}))

const edgeStyle = computed(() => {
  if (isFailure.value) {
    return {
      stroke: hovered.value || props.selected ? '#ff7875' : '#ff4d4f',
      strokeWidth: hovered.value || props.selected ? 2.75 : 2,
      strokeDasharray: '6 3',
    }
  }
  return {
    stroke: hovered.value || props.selected
      ? 'var(--primary-color, #1890ff)'
      : 'var(--text-secondary, #667085)',
    strokeWidth: hovered.value || props.selected ? 2.75 : 2,
  }
})
</script>

<style lang="less" scoped>
.edge-hitarea {
  cursor: pointer;
}

.sop-edge-label {
  font-size: 12px;
  font-weight: 500;
  color: #92400e;
  background: rgba(250, 173, 20, 0.12);
  border: 1px solid rgba(250, 173, 20, 0.35);
  border-radius: 4px;
  padding: 2px 8px;
  white-space: nowrap;
  user-select: none;

  &.failure-label {
    color: #cf1322;
    background: rgba(255, 77, 79, 0.08);
    border-color: rgba(255, 77, 79, 0.35);
  }
}

.sop-edge-delete-btn {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: var(--panel-bg, #fff);
  border: 1px solid rgba(255, 77, 79, 0.45);
  color: #ff4d4f;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  font-size: 10px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.12);
  z-index: 10;

  &:hover {
    background: #ff4d4f;
    color: #fff;
  }
}
</style>
