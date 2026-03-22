<template>
  <div class="markdown-edit-wrap">
    <a-textarea
      ref="markdownTextareaRef"
      :value="editableContent"
      class="markdown-editor"
      @update:value="emit('update:editableContent', $event)"
      @click="onMarkdownCursorChange"
      @keyup="onMarkdownCursorChange"
      @mouseup="onMarkdownCursorChange"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { toValidLine, getOffsetByLine } from '../../../utils/common'

const props = defineProps<{
  editableContent: string
  activeLineRange: { start: number; end: number } | null
}>()

const emit = defineEmits<{
  'update:editableContent': [value: string]
  'select-line': [line: number]
}>()

const markdownTextareaRef = ref()

const getCursorLineFromTextarea = (): number | null => {
  const textarea = markdownTextareaRef.value?.resizableTextArea?.textArea as HTMLTextAreaElement | undefined
  if (!textarea) return null
  const value = textarea.value || ''
  const cursor = Math.max(0, textarea.selectionStart || 0)
  const line = value.slice(0, cursor).split('\n').length
  return toValidLine(line)
}

const onMarkdownCursorChange = () => {
  const line = getCursorLineFromTextarea()
  if (line !== null) {
    emit('select-line', line)
  }
}

const scrollMarkdownEditorToLine = (line: number) => {
  const textarea = markdownTextareaRef.value?.resizableTextArea?.textArea as HTMLTextAreaElement | undefined
  if (!textarea) return
  const parsedLineHeight = Number.parseFloat(getComputedStyle(textarea).lineHeight)
  const lineHeight = Number.isFinite(parsedLineHeight) ? parsedLineHeight : 22
  const targetTop = Math.max(0, (line - 1) * lineHeight - textarea.clientHeight * 0.35)
  textarea.scrollTop = targetTop
}

watch(() => props.activeLineRange, (range) => {
  if (!range) return
  const textarea = markdownTextareaRef.value?.resizableTextArea?.textArea as HTMLTextAreaElement | undefined
  if (!textarea) return
  const text = props.editableContent || ''
  const start = getOffsetByLine(text, range.start)
  const end = getOffsetByLine(text, range.end + 1)
  textarea.focus()
  textarea.setSelectionRange(start, Math.max(start, end))
  scrollMarkdownEditorToLine(range.start)
}, { immediate: true })
</script>

<style lang="less" scoped>
.markdown-edit-wrap {
  min-height: 100%;
  padding: 12px;
}

.markdown-editor {
  width: 100%;
  min-height: calc(100vh - 340px);
  border-radius: 8px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  font-size: 13px;
}
</style>
