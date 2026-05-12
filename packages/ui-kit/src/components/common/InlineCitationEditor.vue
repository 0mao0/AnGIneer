<template>
  <div class="inline-citation-editor">
    <Teleport to="body">
      <CitationMentionPanel
        :visible="mentionVisible"
        :candidates="mentionCandidates"
        :active-index="activeMentionIndex"
        :panel-style="mentionPanelStyle"
        @select="applyMentionCandidate"
        @hover="activeMentionIndex = $event"
      />
    </Teleport>
    <Teleport to="body">
      <div
        v-if="hoveredCitation"
        class="editor-citation-popover"
        :style="citationPopoverStyle"
        @mouseenter="clearCitationPopoverHideTimer"
        @mouseleave="scheduleHideCitationPopover"
      >
        <div class="editor-citation-popover__header">
          <div class="editor-citation-popover__title">{{ hoveredCitation.label }}</div>
          <div class="editor-citation-popover__meta">
            <span>{{ formatCitationDocTitle(hoveredCitation.reference.docTitle) }}</span>
            <span v-if="hoveredCitation.reference.pageIdx">P{{ hoveredCitation.reference.pageIdx }}</span>
            <span v-if="hoveredCitation.reference.sectionPath">{{ hoveredCitation.reference.sectionPath }}</span>
          </div>
        </div>
        <CitationRichContent :reference="hoveredCitation.reference" />
      </div>
    </Teleport>
    <div
      ref="editorRef"
      class="editor-surface"
      :class="{ 'is-empty': !draftValue.content, disabled }"
      :contenteditable="disabled ? 'false' : 'true'"
      :data-placeholder="placeholder"
      @input="handleInput"
      @keydown="handleKeydown"
      @keyup="handleSelectionChanged"
      @mouseup="handleSelectionChanged"
      @click="handleEditorClick"
      @mousemove="handleEditorMouseMove"
      @mouseleave="scheduleHideCitationPopover"
      @compositionstart="isComposing = true"
      @compositionend="handleCompositionEnd"
    ></div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import CitationMentionPanel from './CitationMentionPanel.vue'
import CitationRichContent from './CitationRichContent.vue'
import type { CitationBinding, InlineCitationCandidate, InlineCitationDraftValue } from '../../types'
import {
  buildCitationSegments,
  cloneInlineCitationDraft,
  formatCitationDocTitle,
  findMentionAtCaret,
  insertCitationBinding,
  shiftCitationRanges,
  normalizeInlineCitationDraft
} from '../../utils/citation'
import { escapeHtml, escapeHtmlAttribute } from '../../utils/markdown'

interface Props {
  modelValue?: InlineCitationDraftValue
  placeholder?: string
  disabled?: boolean
  searchCitations?: (query: string) => Promise<InlineCitationCandidate[]>
}

const props = withDefaults(defineProps<Props>(), {
  modelValue: () => ({ content: '', citations: [] }),
  placeholder: '输入消息，Enter 发送...',
  disabled: false,
  searchCitations: undefined
})

const emit = defineEmits<{
  'update:modelValue': [value: InlineCitationDraftValue]
  submit: []
  selectCitation: [binding: CitationBinding]
}>()

const editorRef = ref<HTMLElement | null>(null)
const isComposing = ref(false)
const mentionVisible = ref(false)
const mentionCandidates = ref<InlineCitationCandidate[]>([])
const activeMentionIndex = ref(0)
const mentionRange = ref<{ start: number; end: number } | null>(null)
const pendingCaretOffset = ref<number | null>(null)
const searchToken = ref(0)
const isRenderingDom = ref(false)
const mentionPanelStyle = ref<Record<string, string>>({})
const hoveredCitation = ref<CitationBinding | null>(null)
const citationPopoverStyle = ref<Record<string, string>>({})
let searchTimer: number | null = null
let hideCitationPopoverTimer: number | null = null

const draftValue = computed(() => normalizeInlineCitationDraft(props.modelValue))

const emitValue = (value: InlineCitationDraftValue) => {
  emit('update:modelValue', cloneInlineCitationDraft(normalizeInlineCitationDraft(value)))
}

const renderEditorHtml = (value: InlineCitationDraftValue): string => {
  const segments = buildCitationSegments(value)
  return segments.map((segment) => {
    if (segment.type === 'text') {
      return escapeHtml(segment.text).replace(/\n/g, '<br>')
    }
    return `<span class="editor-citation${segment.binding.status === 'mismatch' ? ' mismatch' : ''}" data-inline-citation-id="${escapeHtmlAttribute(segment.binding.id)}" contenteditable="false">${escapeHtml(segment.binding.label)}</span>`
  }).join('')
}

const syncEditorDom = async () => {
  const root = editorRef.value
  if (!root) return
  const nextHtml = renderEditorHtml(draftValue.value)
  if (root.innerHTML === nextHtml) return
  isRenderingDom.value = true
  root.innerHTML = nextHtml
  await nextTick()
  isRenderingDom.value = false
}

const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max)

const updateMentionPanelPosition = () => {
  const root = editorRef.value
  if (!root || !mentionVisible.value) return
  const rect = root.getBoundingClientRect()
  const viewportWidth = window.innerWidth
  const viewportHeight = window.innerHeight
  const panelWidth = Math.min(420, Math.max(320, rect.width))
  const horizontalMargin = 12
  const verticalGap = 8
  const availableBelow = viewportHeight - rect.bottom - horizontalMargin
  const availableAbove = rect.top - horizontalMargin
  const placeBelow = availableBelow >= 220 || availableBelow >= availableAbove
  const maxHeight = Math.max(
    160,
    Math.min(320, placeBelow ? availableBelow - verticalGap : availableAbove - verticalGap)
  )
  const left = clamp(rect.left, horizontalMargin, viewportWidth - panelWidth - horizontalMargin)
  const top = placeBelow
    ? clamp(rect.bottom + verticalGap, horizontalMargin, viewportHeight - maxHeight - horizontalMargin)
    : clamp(rect.top - maxHeight - verticalGap, horizontalMargin, viewportHeight - maxHeight - horizontalMargin)
  mentionPanelStyle.value = {
    left: `${left}px`,
    top: `${top}px`,
    width: `${panelWidth}px`,
    maxHeight: `${maxHeight}px`
  }
}

const clearCitationPopoverHideTimer = () => {
  if (hideCitationPopoverTimer) {
    window.clearTimeout(hideCitationPopoverTimer)
    hideCitationPopoverTimer = null
  }
}

const hideCitationPopover = () => {
  hoveredCitation.value = null
  citationPopoverStyle.value = {}
  clearCitationPopoverHideTimer()
}

const scheduleHideCitationPopover = () => {
  clearCitationPopoverHideTimer()
  hideCitationPopoverTimer = window.setTimeout(() => {
    hideCitationPopover()
  }, 120)
}

const updateCitationPopoverPosition = (anchor: HTMLElement) => {
  const rect = anchor.getBoundingClientRect()
  const viewportWidth = window.innerWidth
  const viewportHeight = window.innerHeight
  const panelWidth = Math.min(360, viewportWidth - 20)
  const panelMaxHeight = Math.min(240, viewportHeight - 20)
  const horizontalMargin = 12
  const verticalGap = 2
  const availableBelow = viewportHeight - rect.bottom - horizontalMargin
  const availableAbove = rect.top - horizontalMargin
  const placeBelow = availableBelow >= 220 || availableBelow >= availableAbove
  const maxHeight = Math.max(
    140,
    Math.min(panelMaxHeight, placeBelow ? availableBelow - verticalGap : availableAbove - verticalGap)
  )
  const preferRightAlignedLeft = rect.right - panelWidth
  const left = clamp(
    viewportWidth - rect.left >= panelWidth ? rect.left : preferRightAlignedLeft,
    horizontalMargin,
    viewportWidth - panelWidth - horizontalMargin
  )
  const top = placeBelow
    ? clamp(rect.bottom + verticalGap, horizontalMargin, viewportHeight - maxHeight - horizontalMargin)
    : clamp(rect.top - maxHeight - verticalGap, horizontalMargin, viewportHeight - maxHeight - horizontalMargin)
  citationPopoverStyle.value = {
    left: `${left}px`,
    top: `${top}px`,
    width: `${panelWidth}px`,
    maxHeight: `${maxHeight}px`
  }
}

const findCitationNode = (node: Node | null): HTMLElement | null => {
  let current = node
  while (current && current !== editorRef.value) {
    if (current instanceof HTMLElement && current.dataset.inlineCitationId) {
      return current
    }
    current = current.parentNode
  }
  return null
}

const getAtomicNodeText = (node: Node): string => {
  if (node instanceof HTMLElement && node.dataset.inlineCitationId) {
    return node.innerText || node.textContent || ''
  }
  return node.textContent || ''
}

const getCaretOffset = (): number => {
  const root = editorRef.value
  const selection = window.getSelection()
  if (!root || !selection || selection.rangeCount === 0) {
    return draftValue.value.content.length
  }

  const range = selection.getRangeAt(0)
  const citationNode = findCitationNode(range.startContainer)
  if (citationNode) {
    const measurement = document.createRange()
    measurement.selectNodeContents(root)
    measurement.setEndBefore(citationNode)
    const baseLength = measurement.toString().length
    return baseLength + (range.startOffset > 0 ? getAtomicNodeText(citationNode).length : 0)
  }

  const preCaretRange = range.cloneRange()
  preCaretRange.selectNodeContents(root)
  preCaretRange.setEnd(range.startContainer, range.startOffset)
  return preCaretRange.toString().length
}

const setCaretOffset = (offset: number) => {
  const root = editorRef.value
  const selection = window.getSelection()
  if (!root || !selection) return

  let consumed = 0
  const range = document.createRange()
  range.selectNodeContents(root)
  range.collapse(true)

  const setAroundNode = (node: Node, after = false) => {
    if (!node.parentNode) return false
    if (after) {
      range.setStartAfter(node)
    } else {
      range.setStartBefore(node)
    }
    range.collapse(true)
    selection.removeAllRanges()
    selection.addRange(range)
    return true
  }

  const visit = (node: Node): boolean => {
    if (node.nodeType === Node.TEXT_NODE) {
      const text = node.textContent || ''
      const nextConsumed = consumed + text.length
      if (offset <= nextConsumed) {
        range.setStart(node, Math.max(0, offset - consumed))
        range.collapse(true)
        selection.removeAllRanges()
        selection.addRange(range)
        return true
      }
      consumed = nextConsumed
      return false
    }

    if (node instanceof HTMLElement && node.dataset.inlineCitationId) {
      const atomicText = getAtomicNodeText(node)
      const nextConsumed = consumed + atomicText.length
      if (offset <= nextConsumed) {
        return setAroundNode(node, offset > consumed)
      }
      consumed = nextConsumed
      return false
    }

    for (const child of Array.from(node.childNodes)) {
      if (visit(child)) {
        return true
      }
    }
    return false
  }

  if (!visit(root)) {
    range.selectNodeContents(root)
    range.collapse(false)
    selection.removeAllRanges()
    selection.addRange(range)
  }
}

const rebuildFromDom = (): InlineCitationDraftValue => {
  const root = editorRef.value
  if (!root) {
    return draftValue.value
  }
  const citationMap = new Map(draftValue.value.citations.map(item => [item.id, item]))
  const citations: CitationBinding[] = []
  let content = ''

  const walk = (node: Node) => {
    if (node.nodeType === Node.TEXT_NODE) {
      content += node.textContent || ''
      return
    }
    if (!(node instanceof HTMLElement)) return
    const citationId = node.dataset.inlineCitationId
    if (citationId) {
      const source = citationMap.get(citationId)
      const label = node.innerText || node.textContent || source?.label || ''
      const start = content.length
      content += label
      if (source) {
        citations.push({
          ...source,
          label,
          range: {
            start,
            end: start + label.length
          }
        })
      }
      return
    }
    Array.from(node.childNodes).forEach(walk)
  }

  Array.from(root.childNodes).forEach(walk)

  return {
    content,
    citations: citations.sort((left, right) => left.range.start - right.range.start)
  }
}

const closeMention = () => {
  mentionVisible.value = false
  mentionCandidates.value = []
  activeMentionIndex.value = 0
  mentionRange.value = null
  mentionPanelStyle.value = {}
}

const refreshMention = (value: InlineCitationDraftValue, caretOffset: number) => {
  const mention = findMentionAtCaret(value.content, caretOffset)
  if (!mention || !props.searchCitations) {
    closeMention()
    return
  }
  mentionRange.value = { start: mention.start, end: mention.end }
  if (searchTimer) {
    window.clearTimeout(searchTimer)
  }
  const token = searchToken.value + 1
  searchToken.value = token
  searchTimer = window.setTimeout(async () => {
    try {
      const candidates = await props.searchCitations!(mention.query.trim())
      if (token !== searchToken.value) return
      mentionCandidates.value = candidates
      activeMentionIndex.value = 0
      mentionVisible.value = candidates.length > 0
      if (candidates.length > 0) {
        nextTick(() => {
          updateMentionPanelPosition()
        })
      }
      if (!candidates.length) {
        mentionRange.value = null
      }
    } catch {
      if (token !== searchToken.value) return
      closeMention()
    }
  }, 180)
}

const handleSelectionChanged = () => {
  const value = rebuildFromDom()
  const caretOffset = getCaretOffset()
  refreshMention(value, caretOffset)
}

const handleInput = () => {
  if (isRenderingDom.value) {
    return
  }
  const nextValue = rebuildFromDom()
  const caretOffset = getCaretOffset()
  pendingCaretOffset.value = caretOffset
  emitValue(nextValue)
  refreshMention(nextValue, caretOffset)
}

const handleEditorClick = (event: MouseEvent) => {
  const target = event.target as HTMLElement | null
  const citationElement = target?.closest?.('[data-inline-citation-id]') as HTMLElement | null
  if (citationElement?.dataset.inlineCitationId) {
    const binding = draftValue.value.citations.find(item => item.id === citationElement.dataset.inlineCitationId)
    if (binding) {
      event.preventDefault()
      emit('selectCitation', binding)
      return
    }
  }
  handleSelectionChanged()
}

const handleEditorMouseMove = (event: MouseEvent) => {
  const target = event.target as HTMLElement | null
  const citationElement = target?.closest?.('[data-inline-citation-id]') as HTMLElement | null
  if (!citationElement?.dataset.inlineCitationId) {
    scheduleHideCitationPopover()
    return
  }
  const binding = draftValue.value.citations.find(item => item.id === citationElement.dataset.inlineCitationId)
  if (!binding) {
    scheduleHideCitationPopover()
    return
  }
  clearCitationPopoverHideTimer()
  hoveredCitation.value = binding
  updateCitationPopoverPosition(citationElement)
}

const applyMentionCandidate = (candidate: InlineCitationCandidate) => {
  const range = mentionRange.value
  if (!range) return
  const currentValue = rebuildFromDom()
  const nextValue = insertCitationBinding(currentValue, range, candidate)
  pendingCaretOffset.value = range.start + candidate.label.length
  emitValue(nextValue)
  closeMention()
}

const handleKeydown = (event: KeyboardEvent) => {
  if (mentionVisible.value && mentionCandidates.value.length) {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      activeMentionIndex.value = (activeMentionIndex.value + 1) % mentionCandidates.value.length
      return
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault()
      activeMentionIndex.value = (activeMentionIndex.value - 1 + mentionCandidates.value.length) % mentionCandidates.value.length
      return
    }
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      applyMentionCandidate(mentionCandidates.value[activeMentionIndex.value])
      return
    }
    if (event.key === 'Escape') {
      event.preventDefault()
      closeMention()
      return
    }
  }

  if (event.key === 'Enter' && !event.shiftKey && !isComposing.value) {
    event.preventDefault()
    emit('submit')
  }
}

const handleCompositionEnd = () => {
  isComposing.value = false
  nextTick(() => {
    handleInput()
  })
}

const focusEditor = async () => {
  const root = editorRef.value
  if (!root) return
  root.focus()
  await nextTick()
}

const insertMentionTrigger = async () => {
  if (props.disabled) return
  const currentValue = rebuildFromDom()
  const caretOffset = getCaretOffset()
  const nextContent = `${currentValue.content.slice(0, caretOffset)}@${currentValue.content.slice(caretOffset)}`
  const nextValue: InlineCitationDraftValue = {
    content: nextContent,
    citations: shiftCitationRanges(currentValue.citations, caretOffset, 1)
  }
  pendingCaretOffset.value = caretOffset + 1
  emitValue(nextValue)
  await nextTick()
  await focusEditor()
  refreshMention(nextValue, caretOffset + 1)
}

watch(draftValue, async () => {
  await syncEditorDom()
  if (pendingCaretOffset.value === null) return
  await nextTick()
  setCaretOffset(pendingCaretOffset.value)
  pendingCaretOffset.value = null
}, { deep: true, immediate: true })

onMounted(() => {
  syncEditorDom()
  window.addEventListener('resize', updateMentionPanelPosition)
  window.addEventListener('scroll', updateMentionPanelPosition, true)
  window.addEventListener('resize', hideCitationPopover)
  window.addEventListener('scroll', hideCitationPopover, true)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', updateMentionPanelPosition)
  window.removeEventListener('scroll', updateMentionPanelPosition, true)
  window.removeEventListener('resize', hideCitationPopover)
  window.removeEventListener('scroll', hideCitationPopover, true)
  if (searchTimer) {
    window.clearTimeout(searchTimer)
  }
  clearCitationPopoverHideTimer()
})

watch(mentionVisible, (visible) => {
  if (!visible) return
  nextTick(() => {
    updateMentionPanelPosition()
  })
})

watch(() => mentionCandidates.value.length, () => {
  if (!mentionVisible.value) return
  nextTick(() => {
    updateMentionPanelPosition()
  })
})

watch(hoveredCitation, (value) => {
  if (!value) return
  nextTick(() => {
    const root = editorRef.value
    const anchor = root?.querySelector?.(`[data-inline-citation-id="${value.id}"]`) as HTMLElement | null
    if (anchor) {
      updateCitationPopoverPosition(anchor)
    }
  })
})

defineExpose({
  focusEditor,
  insertMentionTrigger
})
</script>

<style lang="less" scoped>
.inline-citation-editor {
  position: relative;
  min-height: 0;
  flex: 1;
}

.editor-surface {
  min-height: 100%;
  padding: 12px 12px 48px 12px;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: var(--bg-secondary);
  color: var(--text-primary);
  font-size: 14px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  overflow-y: auto;
  outline: none;

  &.is-empty::before {
    content: attr(data-placeholder);
    color: var(--text-secondary);
    pointer-events: none;
  }

  &:focus {
    border-color: var(--primary-color);
    box-shadow: 0 0 0 2px rgba(24, 144, 255, 0.2);
  }

  &.disabled {
    cursor: not-allowed;
    opacity: 0.7;
  }
}

.editor-surface :deep(.editor-citation) {
  display: inline;
  color: var(--primary-color);
  text-decoration: underline;
  text-underline-offset: 2px;
  cursor: pointer;
}

.editor-surface :deep(.editor-citation.mismatch) {
  color: var(--warning-color, #faad14);
  text-decoration-style: dashed;
}

.editor-citation-popover {
  position: fixed;
  z-index: 4100;
  min-width: 280px;
  padding: 10px;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: var(--bg-primary);
  box-shadow: 0 12px 32px rgba(15, 23, 42, 0.2);
  overflow: auto;
}

.editor-citation-popover__header {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 10px;
}

.editor-citation-popover__title {
  font-size: 12px;
  font-weight: 600;
  color: var(--primary-color);
}

.editor-citation-popover__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 10px;
  color: var(--text-secondary);
  font-family: 'KaiTi', 'STKaiti', 'Kaiti SC', serif;
}

.editor-citation-popover :deep(.citation-rich-content) {
  gap: 8px;
}

.editor-citation-popover :deep(.media-images) {
  gap: 6px;
}

.editor-citation-popover :deep(.media-image) {
  max-height: 120px;
  object-fit: contain;
}

.editor-citation-popover :deep(table) {
  font-size: 11px;
}

.editor-citation-popover :deep(pre),
.editor-citation-popover :deep(.katex-display),
.editor-citation-popover :deep(.media-formula),
.editor-citation-popover :deep(.media-table) {
  overflow: auto;
}
</style>
