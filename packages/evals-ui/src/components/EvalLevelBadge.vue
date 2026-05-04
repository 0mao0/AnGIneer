<template>
  <a-tag :color="levelColor" class="eval-level-badge">
    {{ level }}
  </a-tag>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { EvalIntentLevel } from '../types/eval'

const props = defineProps<{
  level: EvalIntentLevel
}>()

const levelColorMap: Record<string, string> = {
  L1: 'blue',
  L2: 'green',
  L3: 'orange',
  L4: 'red',
}

const levelColor = computed(() => levelColorMap[props.level] || 'default')
</script>

<style lang="less" scoped>
.eval-level-badge {
  font-size: 12px;
  line-height: 20px;
  padding: 0 6px;
  border-radius: 4px;
}
</style>
