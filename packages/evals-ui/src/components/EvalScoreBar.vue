<template>
  <div class="eval-score-bar">
    <div v-if="label" class="eval-score-bar__label">{{ label }}</div>
    <a-progress
      :percent="displayPercentage"
      :stroke-color="strokeColor"
      :show-info="true"
      :format="() => displayText"
      size="small"
    />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  label?: string
  score: number
  maxScore?: number
}>(), {
  maxScore: 1,
})

const displayPercentage = computed(() => {
  return Math.round((props.score / props.maxScore) * 100)
})

const strokeColor = computed(() => {
  const ratio = props.score / props.maxScore
  if (ratio >= 0.8) return '#52c41a'
  if (ratio >= 0.5) return '#faad14'
  return '#f5222d'
})

const displayText = computed(() => {
  return (props.score * 100).toFixed(1) + '%'
})
</script>

<style lang="less" scoped>
.eval-score-bar {
  display: flex;
  align-items: center;
  gap: 8px;

  &__label {
    flex-shrink: 0;
    font-size: 13px;
    color: var(--text-secondary, rgba(0, 0, 0, 0.45));
    min-width: 60px;
  }

  :deep(.ant-progress) {
    flex: 1;
  }
}
</style>
