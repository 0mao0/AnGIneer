<template>
  <div v-if="visible" class="citation-mention-panel" :style="panelStyle">
    <button
      v-for="(candidate, index) in candidates"
      :key="`${candidate.reference.targetId}_${index}`"
      type="button"
      class="mention-item"
      :class="{ active: index === activeIndex }"
      @mousedown.prevent="emit('select', candidate)"
      @mouseenter="emit('hover', index)"
    >
      <div class="mention-main">
        <span class="mention-label">{{ candidate.label }}</span>
        <span class="mention-type">{{ candidate.reference.targetType || 'content' }}</span>
      </div>
      <div class="mention-meta">
        <span class="mention-doc">{{ formatCitationDocTitle(candidate.reference.docTitle) }}</span>
        <span v-if="candidate.reference.pageIdx">P{{ candidate.reference.pageIdx }}</span>
      </div>
      <div v-if="candidate.reference.sectionPath" class="mention-path">{{ candidate.reference.sectionPath }}</div>
      <div
        class="mention-snippet"
        :class="{
          'is-formula': isFormulaCandidate(candidate),
          'is-table': isTableCandidate(candidate),
          'is-figure': isFigureCandidate(candidate)
        }"
        v-html="renderCandidatePreview(candidate)"
      />
    </button>
  </div>
</template>

<script setup lang="ts">
import type { InlineCitationCandidate } from '../../types'
import { formatCitationDocTitle } from '../../utils/citation'
import {
  renderFormula,
  renderMarkdownInlineToHtml,
  escapeHtml,
  escapeHtmlAttribute,
  resolveAssetUrl
} from '../../utils/markdown'

interface Props {
  visible: boolean
  candidates: InlineCitationCandidate[]
  activeIndex: number
  panelStyle?: Record<string, string>
}

const props = withDefaults(defineProps<Props>(), {
  panelStyle: () => ({})
})

const emit = defineEmits<{
  select: [candidate: InlineCitationCandidate]
  hover: [index: number]
}>()

const isFormulaCandidate = (candidate: InlineCitationCandidate): boolean => (
  String(candidate.reference.targetType || '').toLowerCase() === 'formula'
)

const isFigureCandidate = (candidate: InlineCitationCandidate): boolean => (
  String(candidate.reference.targetType || '').toLowerCase() === 'figure'
)

const isTableCandidate = (candidate: InlineCitationCandidate): boolean => (
  String(candidate.reference.targetType || '').toLowerCase() === 'table'
)

const resolveFigurePreview = (candidate: InlineCitationCandidate): string => {
  const richMedia = candidate.reference.richMedia
  if (!richMedia) return ''
  const sourceFilePath = richMedia.sourceFileName || ''
  const orderedImage = richMedia.richMediaOrder?.find(item => item.type === 'image' && item.path)?.path
  const rawPath = orderedImage || richMedia.imagePath || richMedia.imagePaths?.[0] || ''
  const src = resolveAssetUrl(String(rawPath || ''), sourceFilePath)
  if (!src) return ''
  return `<img class="mention-preview-image" src="${escapeHtmlAttribute(src)}" alt="${escapeHtmlAttribute(candidate.label || 'citation image')}" />`
}

const resolveTablePreview = (candidate: InlineCitationCandidate): string => {
  const tableHtml = String(candidate.reference.richMedia?.tableHtml || '').trim()
  if (!tableHtml || typeof DOMParser === 'undefined') return ''
  try {
    const parser = new DOMParser()
    const documentFragment = parser.parseFromString(tableHtml, 'text/html')
    const table = documentFragment.querySelector('table')
    if (!table) return ''
    const clonedTable = table.cloneNode(true) as HTMLTableElement
    const rows = Array.from(clonedTable.querySelectorAll('tr'))
    rows.forEach((row, rowIndex) => {
      if (rowIndex >= 3) {
        row.remove()
        return
      }
      const cells = Array.from(row.children)
      cells.forEach((cell, cellIndex) => {
        if (cellIndex >= 4) {
          cell.remove()
        } else {
          cell.textContent = String(cell.textContent || '').trim().slice(0, 18)
        }
      })
    })
    return `<div class="mention-preview-table">${clonedTable.outerHTML}</div>`
  } catch {
    return ''
  }
}

const renderCandidatePreview = (candidate: InlineCitationCandidate): string => {
  const richFormula = String(candidate.reference.richMedia?.mathContent || '').trim()
  if (isFormulaCandidate(candidate)) {
    const formulaSource = richFormula || String(candidate.reference.content || candidate.reference.snippet || '').trim()
    return formulaSource ? renderFormula(formulaSource, true) : '<span>无公式内容</span>'
  }
  if (isTableCandidate(candidate)) {
    const tablePreview = resolveTablePreview(candidate)
    if (tablePreview) {
      return tablePreview
    }
  }
  if (isFigureCandidate(candidate)) {
    const imagePreview = resolveFigurePreview(candidate)
    if (imagePreview) {
      return imagePreview
    }
  }
  const content = String(candidate.reference.snippet || candidate.reference.content || '').trim()
  return content ? renderMarkdownInlineToHtml(content, '') : escapeHtml('无预览内容')
}
</script>

<style lang="less" scoped>
.citation-mention-panel {
  position: fixed;
  width: min(420px, calc(100vw - 24px));
  max-height: min(320px, calc(100vh - 24px));
  overflow-y: auto;
  padding: 8px;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: var(--bg-primary);
  box-shadow: 0 10px 30px rgba(15, 23, 42, 0.16);
  z-index: 4000;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.mention-item {
  width: 100%;
  text-align: left;
  padding: 8px 10px;
  border: 1px solid transparent;
  border-radius: 10px;
  background: var(--bg-secondary);
  cursor: pointer;
  color: inherit;
  font: inherit;

  &.active,
  &:hover {
    border-color: var(--primary-color);
    background: var(--bg-hover, rgba(24, 144, 255, 0.08));
  }
}

.mention-main,
.mention-meta {
  display: flex;
  justify-content: space-between;
  gap: 8px;
}

.mention-label {
  font-weight: 600;
  font-size: 13px;
  color: #fff;
}

.mention-type,
.mention-doc,
.mention-path,
.mention-snippet,
.mention-meta {
  font-size: 11px;
  line-height: 1.5;
}

.mention-type,
.mention-meta,
.mention-path {
  color: var(--text-secondary);
  font-family: 'KaiTi', 'STKaiti', 'Kaiti SC', serif;
}

.mention-snippet {
  margin-top: 4px;
  color: #fff;
  opacity: 0.9;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;

  &.is-formula {
    display: block;
    -webkit-line-clamp: initial;
  }

  &.is-table,
  &.is-figure {
    display: block;
    -webkit-line-clamp: initial;
  }

  :deep(.mention-preview-table) {
    overflow: auto hidden;
    border-radius: 6px;
  }

  :deep(.mention-preview-table table) {
    width: 100%;
    border-collapse: collapse;
    table-layout: fixed;
    font-size: 10px;
    color: #fff;
  }

  :deep(.mention-preview-table th),
  :deep(.mention-preview-table td) {
    border: 1px solid rgba(255, 255, 255, 0.12);
    padding: 3px 5px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  :deep(.mention-preview-image) {
    display: block;
    max-width: 100%;
    max-height: 84px;
    border-radius: 6px;
    object-fit: contain;
    background: rgba(255, 255, 255, 0.03);
  }

  :deep(.katex-display) {
    margin: 0;
    overflow-x: auto;
    overflow-y: hidden;
  }
}
</style>
