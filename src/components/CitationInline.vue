<template>
  <CitationPopover
    :reference="reference"
    :source-file-path="sourceFilePath"
    :show-open-action="showOpenAction"
    @open="emit('open')"
  >
    <button
      type="button"
      class="citation-inline"
      :class="{ mismatch }"
      @click.stop="emit('select')"
    >
      {{ label }}
    </button>
  </CitationPopover>
</template>

<script setup lang="ts">
import CitationPopover from './CitationPopover.vue'
import type { CitationReference } from '../../types'

interface Props {
  label: string
  reference: CitationReference
  mismatch?: boolean
  sourceFilePath?: string
  showOpenAction?: boolean
}

withDefaults(defineProps<Props>(), {
  mismatch: false,
  sourceFilePath: '',
  showOpenAction: true
})

const emit = defineEmits<{
  select: []
  open: []
}>()
</script>

<style lang="less" scoped>
.citation-inline {
  display: inline;
  padding: 0;
  margin: 0;
  border: none;
  background: transparent;
  color: var(--primary-color);
  text-decoration: underline;
  text-underline-offset: 2px;
  cursor: pointer;
  font: inherit;

  &.mismatch {
    color: var(--warning-color, #faad14);
    text-decoration-style: dashed;
  }
}
</style>
