<template>
  <div
    v-for="group in groups"
    :key="group.index || `${group.kind}-${group.detail}-${group.tool}`"
    class="thinking-step"
    :class="group.kind === 'note' ? 'thinking-step-note' : ''"
  >
    <template v-if="group.kind === 'note'">
      <span class="thinking-step-note-label">
        <span v-if="group.index" class="thinking-step-index">{{ group.index }}.</span>
        <span class="thinking-step-title">{{ noteTitle(group) }}</span>
        <span v-if="noteReason(group)" class="thinking-step-detail">（{{ noteReason(group) }}）</span>
      </span>
    </template>
    <template v-else>
      <span class="thinking-step-label">
        <span v-if="group.index" class="thinking-step-index">{{ group.index }}.</span>
        <span class="thinking-step-title">{{ formatThinkingStepTitle(group) }}</span>
        <span v-if="group.callDetail" class="thinking-step-detail">
          （{{ formatThinkingArgDetail(group.callDetail) }}）
        </span>
      </span>
      <span
        v-if="group.resultDetail"
        class="thinking-step-result"
        :class="{ 'is-error': group.isError, 'has-items': isResultExpandable(group) }"
        :role="isResultExpandable(group) ? 'button' : undefined"
        :tabindex="isResultExpandable(group) ? 0 : undefined"
        :aria-expanded="isResultExpandable(group) ? isResultExpanded(group.index) : undefined"
        @click="toggleResultExpandIfAny(group.index, group)"
        @keydown.enter.prevent="toggleResultExpandIfAny(group.index, group)"
        @keydown.space.prevent="toggleResultExpandIfAny(group.index, group)"
      >
        <template v-if="isResultExpandable(group)">
          <DownOutlined
            v-if="isResultExpanded(group.index)"
            class="thinking-step-result-toggle-icon"
          />
          <RightOutlined v-else class="thinking-step-result-toggle-icon" />
        </template>
        调用结果：→ {{ group.resultDetail }}
        <template v-if="group.resultNote">；{{ group.resultNote }}</template>
        <template v-if="group.durationMs">，耗时{{ formatDuration(group.durationMs) }}</template>
      </span>

      <div
        v-if="isResultExpanded(group.index) && group.resultItems?.length"
        class="thinking-step-result-list"
      >
        <div
          v-for="(item, idx) in group.resultItems"
          :key="item.item_id || idx"
          class="thinking-result-item"
        >
          <div class="thinking-result-item-head">
            <span class="thinking-result-item-index">{{ idx + 1 }}</span>
            <button
              type="button"
              class="thinking-result-item-title"
              :title="item.text"
              @click="emit('selectCitation', toCitation(item))"
            >
              {{ getCitationTagLabel(toCitation(item)) }}
            </button>
            <span
              class="thinking-result-item-score"
              title="本组最高分显示为 100%，为组内相对值"
            >
              组内相关度 {{ formatResultScore(item.score, getResultMaxScore(group)) }}
            </span>
          </div>
          <div
            class="thinking-result-item-snippet"
            v-html="renderSearchSnippetHtml(item.text, resultQuery(group))"
          ></div>
        </div>
      </div>

      <div v-if="group.citations && group.citations.length" class="thinking-step-citations">
        <span class="thinking-step-citations-label">命中引用（用于最终回答）：</span>
        <div class="thinking-step-citations-tags">
          <button
            v-for="citation in group.citations"
            :key="`${citation.target_id}-${citation.page_idx}-${citation.section_path}`"
            type="button"
            class="thinking-step-citation"
            :title="getCitationHoverText(citation)"
            @click="emit('selectCitation', citation)"
          >
            {{ formatCitationShortLabel(citation, getCitationItemIndex(group, citation)) }}
          </button>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { DownOutlined, RightOutlined } from '@ant-design/icons-vue'
import {
  formatCitationShortLabel,
  getCitationHoverText,
  getCitationTagLabel,
} from '../utils/citation'
import {
  formatDuration,
  formatThinkingArgDetail,
  formatThinkingStepTitle,
  formatResultScore,
  getResultMaxScore,
  isResultExpandable,
  type ThinkingGroupStep,
} from '../utils/thinking'
import { renderSearchSnippetHtml } from '../utils/searchSnippet'
import type { AIChatCitation, BaseChatCitation, ThinkingTraceItem } from '../types'

defineProps<{ groups: ThinkingGroupStep[] }>()

const emit = defineEmits<{ selectCitation: [citation: BaseChatCitation] }>()

const expandedResults = ref<number[]>([])

const isResultExpanded = (index: number) => expandedResults.value.includes(index)

/** 说明类步骤：末尾括号内的理由与标题拆开，标题加粗、理由常规。 */
const splitNoteLabel = (group: ThinkingGroupStep): { title: string; reason?: string } => {
  const detail = String(group.detail || '')
  const match = detail.match(/^(.*)（([^（）]*)）$/)
  if (match && match[1]) {
    return { title: match[1], reason: match[2] || undefined }
  }
  return { title: detail }
}

const noteTitle = (group: ThinkingGroupStep): string => splitNoteLabel(group).title
const noteReason = (group: ThinkingGroupStep): string | undefined => splitNoteLabel(group).reason

const toggleResultExpand = (index: number) => {
  expandedResults.value = isResultExpanded(index)
    ? expandedResults.value.filter(item => item !== index)
    : [...expandedResults.value, index]
}

const toggleResultExpandIfAny = (index: number, group: ThinkingGroupStep) => {
  if (isResultExpandable(group)) {
    toggleResultExpand(index)
  }
}

/** 把工具返回条目转成可点击跳 PDF 的引用对象 */
const toCitation = (item: ThinkingTraceItem): BaseChatCitation => ({
  target_id: item.item_id,
  target_type: item.entity_type || 'content',
  doc_id: item.doc_id || '',
  doc_title: item.doc_title || item.title || '未命名文档',
  page_idx: Number(item.metadata?.page_idx || 0),
  page_label: item.metadata?.page_label,
  section_path: String(item.metadata?.section_path || ''),
  snippet: item.text,
  content: item.text,
  content_type: 'text',
  score: item.score || 0,
})

/** 命中引用对应的候选序号（1 起），找不到时返回 undefined。 */
const getCitationItemIndex = (group: ThinkingGroupStep, citation: AIChatCitation): number | undefined => {
  const items = group.resultItems || []
  const found = items.findIndex(
    item =>
      (citation?.marker && item.cite === citation.marker) ||
      (citation?.target_id && item.item_id === citation.target_id)
  )
  return found >= 0 ? found + 1 : undefined
}

/** 从工具调用参数里取检索查询词（knowledge_search/table_search 的 {"query": ...}）。 */
const resultQuery = (group: ThinkingGroupStep): string => {
  const detail = String(group.callDetail || '')
  if (!detail) return ''
  try {
    const parsed = JSON.parse(detail)
    const q = parsed?.query ?? parsed?.keywords ?? parsed?.q
    if (typeof q === 'string') return q
    if (Array.isArray(q)) return q.filter(Boolean).join(' ')
  } catch {
    // 非 JSON 参数（如 "query = 上航数联"）走正则兜底
  }
  const match = detail.match(/["']?query["']?\s*[:=]\s*["']?([^"',}]+)/i)
  return match ? match[1].trim() : ''
}
</script>

<style lang="less" scoped>
.thinking-step {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 12px;
  line-height: 1.6;
  padding: 2px 8px;
  border-radius: 6px;

  &:not(.thinking-step-note) {
    display: flex;
    flex-direction: row;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 2px 6px;
  }

  .thinking-step-label {
    color: var(--text-secondary);
  }

  .thinking-step-index,
  .thinking-step-title {
    font-weight: 600;
  }

  .thinking-step-index {
    margin-right: 3px;
  }

  .thinking-step-detail {
    color: var(--text-secondary);
    font-weight: 400;
    word-break: break-all;
    opacity: 0.9;
  }

  .thinking-step-result {
    flex-basis: 100%;
    color: var(--success-color, #52c41a);
    word-break: break-all;
    white-space: pre-wrap;

    &.is-error {
      color: var(--error-color, #ff4d4f);
    }

    &.has-items {
      cursor: pointer;

      &:hover {
        opacity: 0.85;
      }
    }

    .thinking-step-result-toggle-icon {
      margin-right: 2px;
    }
  }

  .thinking-step-result-list {
    flex-basis: 100%;
    display: flex;
    flex-direction: column;
    gap: 8px;
    max-height: 260px;
    overflow-y: auto;
    padding: 8px 10px;
    border: 1px solid var(--border-color);
    border-radius: 8px;
    background: rgba(128, 128, 128, 0.04);
  }

  .thinking-result-item {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 6px 8px;
    border: 1px solid var(--border-color);
    border-radius: 8px;
    background: rgba(128, 128, 128, 0.05);
    transition: border-color 0.16s ease;

    &:hover {
      border-color: var(--primary-color, #1677ff);
    }
  }

  .thinking-result-item-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
  }

  .thinking-result-item-index {
    flex-shrink: 0;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 18px;
    height: 18px;
    border-radius: 50%;
    background: rgba(128, 128, 128, 0.16);
    color: var(--text-secondary);
    font-size: 11px;
    line-height: 1;
  }

  .thinking-result-item-title {
    min-width: 0;
    max-width: 100%;
    flex: 1 1 auto;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    padding: 0;
    border: none;
    background: transparent;
    color: var(--primary-color, #1677ff);
    font-size: 12px;
    text-align: left;
    cursor: pointer;

    &:hover {
      opacity: 0.85;
    }
  }

  .thinking-result-item-score {
    flex-shrink: 0;
    color: var(--success-color, #52c41a);
    background: rgba(82, 196, 26, 0.1);
    border-radius: 999px;
    padding: 1px 6px;
    font-size: 12px;
  }

  .thinking-result-item-snippet {
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    color: var(--text-secondary);
    font-size: 12px;
    line-height: 1.5;

    :deep(.search-hit) {
      background: rgba(250, 219, 91, 0.4);
      border-radius: 2px;
      padding: 0 1px;
    }

    :deep(.math-inline-fallback) {
      color: var(--error-color, #ff4d4f);
    }
  }

  .thinking-step-citations {
    flex-basis: 100%;
    display: grid;
    grid-template-columns: auto 1fr;
    align-items: start;
    gap: 4px;
    margin-top: 2px;
    min-width: 0;
  }

  .thinking-step-citations-label {
    white-space: nowrap;
    color: var(--text-secondary);
    font-size: 12px;
  }

  .thinking-step-citations-tags {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    min-width: 0;
  }

  .thinking-step-citation {
    flex: 0 0 auto;
    max-width: 200px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    padding: 1px 8px;
    border: 1px solid var(--border-color);
    border-radius: 999px;
    background: rgba(128, 128, 128, 0.08);
    color: var(--text-secondary);
    font-size: 12px;
    line-height: 18px;
    cursor: pointer;
    transition: color 0.16s ease, border-color 0.16s ease;

    &:hover {
      color: var(--primary-color);
      border-color: var(--primary-color);
    }
  }

  &.thinking-step-note {
    margin: 2px 0;
    background: rgba(128, 128, 128, 0.06);

    .thinking-step-note-label {
      color: var(--text-secondary);
      letter-spacing: 0.02em;
    }
  }
}
</style>
