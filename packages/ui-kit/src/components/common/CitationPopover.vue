<template>
  <a-popover
    placement="topLeft"
    trigger="hover"
    :overlay-class-name="overlayClassName"
  >
    <template #content>
      <div class="citation-popover">
        <div class="popover-header">
          <div class="popover-title">{{ reference.docTitle || '引用预览' }}</div>
          <div class="popover-meta">
            <span v-if="reference.pageIdx">P{{ reference.pageIdx }}</span>
            <span v-if="reference.sectionPath">{{ reference.sectionPath }}</span>
          </div>
        </div>
        <CitationRichContent :reference="reference" :source-file-path="sourceFilePath" />
        <button
          v-if="showOpenAction"
          type="button"
          class="popover-action"
          @click.stop="emit('open')"
        >
          打开原文
        </button>
      </div>
    </template>
    <slot />
  </a-popover>
</template>

<script setup lang="ts">
import CitationRichContent from './CitationRichContent.vue'
import type { CitationReference } from '../../types'

interface Props {
  reference: CitationReference
  sourceFilePath?: string
  overlayClassName?: string
  showOpenAction?: boolean
}

withDefaults(defineProps<Props>(), {
  sourceFilePath: '',
  overlayClassName: 'citation-popover-overlay',
  showOpenAction: true
})

const emit = defineEmits<{
  open: []
}>()
</script>

<style lang="less" scoped>
.citation-popover {
  width: min(560px, 70vw);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.popover-header {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.popover-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.popover-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 12px;
  color: var(--text-secondary);
}

.popover-action {
  align-self: flex-start;
  padding: 0;
  border: none;
  background: transparent;
  color: var(--primary-color);
  cursor: pointer;
  font-size: 12px;
}
</style>
