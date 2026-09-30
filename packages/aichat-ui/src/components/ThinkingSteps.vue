<template>
  <div
    v-for="group in groups"
    :key="group.index || `${group.kind}-${group.detail}-${group.tool}`"
    class="thinking-step"
    :class="group.kind === 'note' ? 'thinking-step-note' : ''"
  >
    <template v-if="group.kind === 'note'">
      <span class="thinking-step-marker">
        <span v-if="group.index" class="thinking-step-index">{{ group.index }}.</span>
        <span v-if="stepTimeText(group)" class="thinking-step-cost">{{ stepTimeText(group) }}</span>
      </span>
      <span class="thinking-step-note-label">
        <span class="thinking-step-title">{{ noteTitle(group) }}</span>
        <span v-if="noteReason(group)" class="thinking-step-detail">（{{ noteReason(group) }}）</span>
      </span>
      <!-- 多行便签的正文行（如「模型调用」的 等待/输出 分段）：各占一行、与子行同缩进档 -->
      <span
        v-for="(line, lineIdx) in noteBodyLines(group)"
        :key="lineIdx"
        class="thinking-step-note-line"
      >{{ line }}</span>
    </template>
    <template v-else>
      <span class="thinking-step-marker">
        <span v-if="group.index" class="thinking-step-index">{{ group.index }}.</span>
        <span v-if="stepTimeText(group)" class="thinking-step-cost">{{ stepTimeText(group) }}</span>
        <!-- 并行预检两行 tag：放在序号列，与上下步骤的时间 tag 同一条竖线（2026-09-30 用户指定）；
             第一行「并行预检」、第二行预检实际用时。
             条件要求 resultDetail 已到（调用-返回配对完成）：否则流式期间 tool_start 刚到达时
             会先闪一下本 tag、tool_end 到达又被时间 tag 顶掉（用户实拍 09-30） -->
        <span
          v-else-if="group.injected && group.resultDetail"
          class="thinking-step-parallel"
          title="该检索与意图分类并行执行；此处为直接复用（无重复检索），耗时为预检实际用时"
        >
          <span class="thinking-step-parallel-label">并行预检</span>
          <span v-if="group.reusedMs" class="thinking-step-parallel-ms">{{ (group.reusedMs / 1000).toFixed(1) }}s</span>
        </span>
      </span>
      <span class="thinking-step-label">
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
      </span>

      <div
        v-if="isResultExpanded(group.index) && group.resultItems?.length"
        class="thinking-step-result-list"
      >
        <div
          v-for="(item, idx) in group.resultItems"
          :key="item.item_id || idx"
          class="thinking-result-item"
          role="button"
          tabindex="0"
          @click="emit('selectCitation', toCitation(item))"
          @keydown.enter.prevent="emit('selectCitation', toCitation(item))"
        >
          <div class="thinking-result-item-head">
            <span class="thinking-result-item-index">{{ idx + 1 }}</span>
            <span class="thinking-result-item-title">
              {{ getCitationTagLabel(toCitation(item)) }}
            </span>
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
            v-for="doc in visibleCitationDocs(group)"
            :key="doc.docId"
            type="button"
            class="thinking-step-citation"
            :title="doc.tooltip"
            @click="emit('selectCitation', doc.citation)"
          >
            {{ doc.label }}
            <span v-if="doc.count > 1" class="thinking-step-citation-count">×{{ doc.count }}</span>
          </button>
          <button
            v-if="citationDocs(group).length > CITATION_DOC_LIMIT"
            type="button"
            class="thinking-step-citation thinking-step-citation-more"
            @click="toggleCitationsExpanded(group.index)"
          >
            {{ isCitationsExpanded(group.index) ? '收起' : `+${citationDocs(group).length - CITATION_DOC_LIMIT}` }}
          </button>
        </div>
      </div>

      <!-- 附注行：并入本对工具步的说明（如预检索完成说明），不单独成步（2026-09-30） -->
      <span v-if="group.attachNote" class="thinking-step-attach">{{ group.attachNote }}</span>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { DownOutlined, RightOutlined } from '@ant-design/icons-vue'
import {
  getCitationTagLabel,
  getCitationTagTooltip,
  stripCitationDocExtension,
} from '../utils/citation'
import {
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

/** 说明类步骤：末尾括号内的理由与标题拆开，标题加粗、理由常规。
 *  多行便签（2026-09-30「模型调用」分段版式）：首行为标题（拆末尾括号理由），其余行原样作正文行。 */
const splitNoteLabel = (group: ThinkingGroupStep): { title: string; reason?: string; body: string[] } => {
  const detail = String(group.detail || '')
  const lines = detail.split(String.fromCharCode(10))
  const head = lines[0] || ''
  const body = lines.slice(1)
  const match = head.match(/^(.*)（([^（）]*)）$/)
  if (match && match[1]) {
    return { title: match[1], reason: match[2] || undefined, body }
  }
  return { title: head, body }
}

const noteTitle = (group: ThinkingGroupStep): string => splitNoteLabel(group).title
const noteReason = (group: ThinkingGroupStep): string | undefined => splitNoteLabel(group).reason
/** 多行便签的正文行（首行标题之外），每行独立成行、与子行同缩进档 */
const noteBodyLines = (group: ThinkingGroupStep): string[] => splitNoteLabel(group).body

/** 步骤时间 tag：首步 0.3s（无前缀），其余 +1.5s（值＝本步自身耗时）；
 *  不足 50ms 返回空串（四舍五入后是 +0.0s 的噪声，不显示） */
const stepTimeText = (group: ThinkingGroupStep): string => {
  const ms = group.durationMs || 0
  if (ms < 50) return ''
  const seconds = `${(ms / 1000).toFixed(1)}s`
  return (group.index || 1) > 1 ? `+${seconds}` : seconds
}

interface CitationDocGroup {
  docId: string
  label: string
  count: number
  citation: AIChatCitation
  tooltip: string
}

/** 命中引用折叠阈值：超过则先显示前 N 篇，其余走「+N」展开 */
const CITATION_DOC_LIMIT = 8
const expandedCitationGroups = ref<number[]>([])

const isCitationsExpanded = (index?: number) => expandedCitationGroups.value.includes(index || 0)

const toggleCitationsExpanded = (index?: number) => {
  const key = index || 0
  expandedCitationGroups.value = isCitationsExpanded(key)
    ? expandedCitationGroups.value.filter(item => item !== key)
    : [...expandedCitationGroups.value, key]
}

/**
 * 命中引用按文档归并：同一文档的多处引用合成一枚 chip（带 ×N）。
 * 原实现按引用条目逐枚渲染（编号+规范名前几字的短码），十几枚截断短码铺成一片、
 * 既看不出是哪几篇、又把卡片撑得很高（用户 2026-09-30 反馈）。
 */
const citationDocs = (group: ThinkingGroupStep): CitationDocGroup[] => {
  const map = new Map<string, CitationDocGroup>()
  for (const citation of group.citations || []) {
    const key = String(citation.doc_id || citation.doc_title || 'unknown')
    const hit = map.get(key)
    if (hit) {
      hit.count += 1
      continue
    }
    const name = stripCitationDocExtension(citation.doc_title) || '未命名'
    map.set(key, {
      docId: key,
      label: name.length > 14 ? `${name.slice(0, 13)}…` : name,
      count: 1,
      citation,
      tooltip: '',
    })
  }
  const docs = [...map.values()]
  for (const doc of docs) {
    doc.tooltip = `${getCitationTagTooltip(doc.citation)}（引用 ${doc.count} 处）`
  }
  // 引用处数多的文档排前，便于一眼看出证据主体
  return docs.sort((a, b) => b.count - a.count)
}

const visibleCitationDocs = (group: ThinkingGroupStep): CitationDocGroup[] => {
  const docs = citationDocs(group)
  if (docs.length <= CITATION_DOC_LIMIT || isCitationsExpanded(group.index)) return docs
  return docs.slice(0, CITATION_DOC_LIMIT)
}

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

/** 归一化检索条目 id：优先 citation_target_id，其次 item_id 剥掉 target:/table:/formula:/figure: 等前缀 */
const normalizeItemTargetId = (item: ThinkingTraceItem): string => {
  const preferred = String((item as any).citation_target_id || '').trim()
  if (preferred) return preferred
  let id = String(item.item_id || '').trim()
  id = id.replace(/^(?:target|table|formula|figure|chunk):/, '')
  id = id.replace(/-(?:row|summary|schema|text-row)(?:-\d+)?$/, '')
  return id
}

/** 把工具返回条目转成可点击跳 PDF 的引用对象 */
const toCitation = (item: ThinkingTraceItem): BaseChatCitation => ({
  target_id: normalizeItemTargetId(item),
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
  flex-direction: row;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 2px 6px;
  font-size: 12px;
  line-height: 1.6;
  padding: 2px 8px;
  border-radius: 6px;

  /* 左栏（序号+耗时标签/并行预检两行 tag）固定宽度：各步无论有无标签，右侧文字列都对齐同一条线；
     80px 是容纳「序号 + 并行预检两行 tag」的宽度（2026-09-30 从 66 加宽） */
  .thinking-step-marker {
    flex: 0 0 auto;
    width: 80px;
    white-space: nowrap;
  }

  .thinking-step-label,
  .thinking-step-note-label {
    flex: 1 1 0;
    min-width: 0;
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

  /* 每步耗时标签（2026-09-27）：统一「耗时x.x秒」，紧跟序号、位于文字前 */
  .thinking-step-cost {
    display: inline-block;
    margin-right: 6px;
    padding: 0 6px;
    border-radius: 8px;
    background: var(--aichat-step-time-bg, rgba(24, 144, 255, 0.16));
    color: var(--aichat-step-time-color, #1677ff);
    border: 1px solid var(--aichat-step-time-border, rgba(24, 144, 255, 0.45));
    font-size: 12px;
    font-weight: 400;
    line-height: 16px;
    vertical-align: 1px;
  }

  .thinking-step-detail {
    color: var(--text-secondary);
    font-weight: 400;
    word-break: break-all;
    opacity: 0.9;
  }

  /* 「并行预检」两行 tag：与时间 tag 同款胶囊（同一组钩子变量，明暗两档一致），
     仅版式不同——第一行「并行预检」、第二行预检实际用时（2026-09-30 用户指定：和时间一样做成 tag） */
  .thinking-step-parallel {
    display: inline-flex;
    flex-direction: column;
    align-items: center;
    margin-right: 6px;
    padding: 1px 6px;
    border-radius: 8px;
    background: var(--aichat-step-time-bg, rgba(24, 144, 255, 0.16));
    color: var(--aichat-step-time-color, #1677ff);
    border: 1px solid var(--aichat-step-time-border, rgba(24, 144, 255, 0.45));
    font-size: 12px;
    font-weight: 400;
    line-height: 15px;
    vertical-align: 1px;
  }

  .thinking-step-parallel-ms {
    font-size: 11px;
    opacity: 0.85;
  }

  /* 步骤下的子行（调用结果/命中引用/展开列表/附注/多行便签正文）与右栏文字列对齐（marker 80px + gap 6px） */
  .thinking-step-result,
  .thinking-step-citations,
  .thinking-step-result-list,
  .thinking-step-attach,
  .thinking-step-note-line {
    margin-left: 86px;
  }

  /* 多行便签正文行：`行 → 每段独立成行、常规字重、次级色（首行标题仍加粗） */
  .thinking-step-note-line {
    flex-basis: 100%;
    color: var(--text-secondary);
    font-weight: 400;
    word-break: break-all;
    opacity: 0.9;
  }

  .thinking-step-attach {
    flex-basis: 100%;
    color: var(--text-secondary);
    font-size: 12px;
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
    cursor: pointer;

    &:hover {
      border-color: var(--primary-color, #1677ff);
    }

    &:focus-visible {
      outline: 1px solid var(--primary-color, #1677ff);
      outline-offset: 1px;
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
    color: var(--primary-color, #1677ff);
    font-size: 12px;
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

    :deep(.bare-latex-inline) {
      display: inline-block;
      vertical-align: middle;
      margin: 0 2px;
      max-width: 100%;
      overflow-x: auto;

      .katex-display {
        display: inline-block;
        margin: 0;
      }

      .katex {
        font-size: 1.05em;
      }
    }
  }

  .thinking-step-citations {
    flex-basis: 100%;
    /* 标签上置、chip 区吃满整行：左标签右 chip 的网格会把 chip 区压到 ~270px，一枚一行很松散 */
    display: flex;
    flex-direction: column;
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

  /* 文档归并后的引用计数（×N）与「+N」展开按钮 */
  .thinking-step-citation-count {
    margin-left: 2px;
    color: var(--text-tertiary, #999);
    font-size: 11px;
  }

  .thinking-step-citation-more {
    color: var(--text-secondary);
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
