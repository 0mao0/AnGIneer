/**
 * SOP 步骤自定义边组件，贝塞尔曲线带箭头，选中时高亮。
 */
<template>
  <BaseEdge :id="id" :style="edgeStyle" :path="path[0]" :marker-end="markerEnd" :label="data?.label" />
  <path
    :d="path[0]"
    fill="none"
    stroke="transparent"
    stroke-width="12"
    @mouseenter="hovered = true"
    @mouseleave="hovered = false"
  />
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { BaseEdge, getBezierPath } from '@vue-flow/core'
import type { EdgeProps } from '@vue-flow/core'

const props = defineProps<EdgeProps>()

const hovered = ref(false)

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

const edgeStyle = computed(() => ({
  stroke: hovered.value || props.selected
    ? 'var(--primary-color, #1890ff)'
    : 'var(--border-color, #b8b8b8)',
  strokeWidth: hovered.value || props.selected ? 2.5 : 1.5,
}))

const markerEnd = computed(() => hovered.value || props.selected
  ? 'url(#arrowhead-selected)'
  : 'url(#arrowhead)')
</script>
