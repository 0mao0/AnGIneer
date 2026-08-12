<template>
  <div
    v-for="group in groups"
    :key="group.index || `${group.kind}-${group.detail}-${group.tool}`"
    class="thinking-step"
    :class="group.kind === 'note' ? 'thinking-step-note' : ''"
  >
    <template v-if="group.kind === 'note'">
      <span class="thinking-step-note-label">{{ group.label || group.detail }}</span>
    </template>
    <template v-else>
      <span v-if="group.index" class="thinking-step-index">{{ group.index }}.</span>
      <span class="thinking-step-label">
        {{ group.callDetail ? '调用工具：' : '工具返回：' }}{{ group.tool }}
        <span v-if="group.callDetail" class="thinking-step-detail">
          （{{ formatThinkingArgDetail(group.callDetail) }}）
        </span>
      </span>
      <span
        v-if="group.resultDetail"
        class="thinking-step-result"
        :class="{ 'is-error': group.isError }"
      >
        调用结果：→ {{ group.resultDetail }}
        <template v-if="group.resultItems?.length">
          （全部 {{ group.resultItems.length }} 条作为候选交给模型）
        </template>
        <template v-if="group.resultNote">；{{ group.resultNote }}</template>
        <template v-if="group.durationMs"> · 耗时 {{ formatDuration(group.durationMs) }}</template>
      </span>

      <div v-if="group.resultItems?.length" class="thinking-step-result-toggle">
        <button
          type="button"
          class="thinking-step-result-toggle-btn"
          @click="toggleResultExpand(group.index)"
        >
          <DownOutlined v-if="isResultExpanded(group.index)" />
          <RightOutlined v-else />
          {{ isResultExpanded(group.index) ? '收起' : '查看' }} {{ group.resultItems.length }} 条结果
        </button>
      </div>

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
            <button
              type="button"
              class="thinking-result-item-title"
              :title="item.text"
              @click="emit('selectCitation', toCitation(item))"
            >
              {{ getCitationTagLabel(toCitation(item)) }}
            </button>
            <span v-if="item.score" class="thinking-result-item-score">
              {{ item.score.toFixed(2) }}
            </span>
          </div>
          <div class="thinking-result-item-snippet">{{ truncate(item.text, 140) }}</div>
        </div>
      </div>

      <div v-if="group.citations && group.citations.length" class="thinking-step-citations">
        <span class="thinking-step-citations-label">命中引用（用于最终回答）：</span>
        <button
          v-for="citation in group.citations"
          :key="`${citation.target_id}-${citation.page_idx}-${citation.section_path}`"
          type="button"
          class="thinking-step-citation"
          :title="getCitationTagTooltip(citation)"
          @click="emit('selectCitation', citation)"
        >
          {{ getCitationTagLabel(citation) }}
        </button>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { DownOutlined, RightOutlined } from '@ant-design/icons-vue'
import { getCitationTagLabel, getCitationTagTooltip } from '../utils/citation'
import {
  formatDuration,
  formatThinkingArgDetail,
  type ThinkingGroupStep,
} from '../utils/thinking'
import type { BaseChatCitation, ThinkingTraceItem } from '../types'

defineProps<{ groups: ThinkingGroupStep[] }>()

const emit = defineEmits<{ selectCitation: [citation: BaseChatCitation] }>()

const expandedResults = ref<number[]>([])

const isResultExpanded = (index: number) => expandedResults.value.includes(index)

const toggleResultExpand = (index: number) => {
  expandedResults.value = isResultExpanded(index)
    ? expandedResults.value.filter(item => item !== index)
    : [...expandedResults.value, index]
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

const truncate = (text: string, max: number) => {
  const normalized = String(text || '')
  return normalized.length > max ? `${normalized.slice(0, max)}…` : normalized
}
</script>

<style lang="less" scoped>
.thinking-step {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 12px;
  line-height: 1.6;

  &:not(.thinking-step-note) {
    display: flex;
    flex-direction: row;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 2px 6px;
  }

  .thinking-step-index {
    font-weight: 700;
    color: var(--text-tertiary, #999);
  }

  .thinking-step-label {
    font-weight: 600;
    color: var(--text-secondary);
  }

  .thinking-step-detail {
    color: var(--text-secondary);
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
  }

  .thinking-step-result-toggle {
    flex-basis: 100%;
  }

  .thinking-step-result-toggle-btn {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 1px 8px;
    border: 1px solid var(--border-color);
    border-radius: 6px;
    background: transparent;
    color: var(--text-secondary);
    font-size: 11px;
    line-height: 20px;
    cursor: pointer;
    transition: color 0.16s ease, border-color 0.16s ease;

    &:hover {
      color: var(--primary-color);
      border-color: var(--primary-color);
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
    gap: 2px;
  }

  .thinking-result-item-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
  }

  .thinking-result-item-title {
    min-width: 0;
    max-width: 100%;
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
    color: var(--text-tertiary, #999);
    font-size: 11px;
  }

  .thinking-result-item-snippet {
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    color: var(--text-secondary);
    font-size: 11px;
    line-height: 1.5;
  }

  .thinking-step-citations {
    flex-basis: 100%;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 4px;
    margin-top: 2px;
  }

  .thinking-step-citations-label {
    color: var(--text-tertiary, #999);
    font-size: 11px;
  }

  .thinking-step-citation {
    max-width: 180px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    padding: 1px 8px;
    border: 1px solid var(--border-color);
    border-radius: 999px;
    background: rgba(128, 128, 128, 0.08);
    color: var(--text-secondary);
    font-size: 11px;
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
    padding: 4px 8px;
    border-radius: 6px;
    background: rgba(128, 128, 128, 0.06);

    .thinking-step-note-label {
      font-weight: 600;
      color: var(--text-tertiary, #999);
      font-size: 11px;
      letter-spacing: 0.02em;
    }
  }
}
</style>
