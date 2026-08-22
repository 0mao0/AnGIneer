<template>
  <div class="base-chat-component">
    <div v-if="title" class="chat-header">
      <span v-if="icon" class="header-icon">
        <component :is="icon" />
      </span>
      <span class="header-title">{{ title }}</span>
      <div class="header-actions">
        <a-tag v-if="showContextInfo" class="context-info" size="small">
          {{ contextRounds }}轮 / {{ formatTokenCount(contextTokens) }}tokens
        </a-tag>
        <a-button type="text" size="small" @click="handleClear">
          <template #icon><ClearOutlined /></template>
          清空
        </a-button>
      </div>
    </div>

    <div class="chat-messages-wrap">
      <div ref="messagesRef" class="chat-messages" @click="handleMessageClick">
      <div
        v-for="(msg, index) in displayMessages"
        :key="msg.id || index"
        :class="['message', msg.role]"
      >
        <div class="message-content">
          <div
            v-if="shouldShowTimestamp(msg)"
            class="message-time"
          >
            {{ formatMessageTimestamp(msg.timestamp) }}
          </div>
          <template v-if="msg.role === 'user'">
            <div class="user-content">
              <div v-if="msg.images?.length" class="user-images">
                <img
                  v-for="(img, idx) in msg.images"
                  :key="idx"
                  :src="img"
                  class="uploaded-image"
                  alt="上传的图片"
                />
              </div>
              <div class="user-text">
                <template v-for="segment in getInlineSegments(msg)" :key="segment.key">
                  <span v-if="segment.type === 'text'">{{ segment.text }}</span>
                  <CitationInline
                    v-else
                    :label="segment.binding.label"
                    :reference="segment.binding.reference"
                    :mismatch="segment.binding.status === 'mismatch'"
                    @select="handleInlineCitationSelect(segment.binding)"
                    @open="handleInlineCitationSelect(segment.binding)"
                  />
                </template>
              </div>
            </div>
          </template>

          <template v-else-if="msg.role === 'assistant'">
            <div class="assistant-content">
              <div
                v-if="getThinkingGroups(msg).length || ((msg as any).gap_analysis && (msg as any).gap_analysis.length > 0) || getConfidenceKeys(msg).length > 0"
                class="thinking-card"
              >
                <button
                  type="button"
                  class="thinking-card-header"
                  @click="toggleThinkingExpanded(msg)"
                >
                  <BulbOutlined class="thinking-card-icon" />
                  <span class="thinking-card-label">
                    思考过程
                    <template v-if="getThinkingStepCount(msg)">（{{ getThinkingStepCount(msg) }} 步<template v-if="getThinkingDuration(msg)"> · 工具耗时合计 {{ formatDuration(getThinkingDuration(msg)) }}</template>）</template>
                  </span>
                  <span class="thinking-card-arrow">
                    <DownOutlined v-if="isThinkingExpanded(msg)" />
                    <RightOutlined v-else />
                  </span>
                </button>
                <div v-if="isThinkingExpanded(msg)" class="thinking-card-body">
                  <div v-if="getThinkingGroups(msg).length" class="analysis-section">
                    <ThinkingSteps
                      :groups="getThinkingGroups(msg)"
                      @select-citation="handleCitationClick"
                    />
                  </div>

                  <div
                    v-if="(msg as any).gap_analysis && (msg as any).gap_analysis.length > 0"
                    class="analysis-section"
                  >
                    <div class="analysis-title">知识盲区</div>
                    <div
                      v-for="(gap, idx) in (msg as any).gap_analysis"
                      :key="idx"
                      class="gap-item"
                    >
                      <div class="gap-description">
                        <span class="gap-index">{{ idx + 1 }}.</span>
                        {{ gap.gap_description }}
                      </div>
                      <div
                        v-if="gap.suggested_sources && gap.suggested_sources.length > 0"
                        class="gap-suggestions"
                      >
                        <span class="gap-suggestion-label">建议补充：</span>
                        <a-tag
                          v-for="(src, sIdx) in gap.suggested_sources"
                          :key="sIdx"
                          color="orange"
                          class="gap-tag"
                        >
                          {{ src }}
                        </a-tag>
                      </div>
                    </div>
                  </div>

                  <div v-if="getConfidenceKeys(msg).length > 0" class="analysis-section">
                    <div class="analysis-title">置信度说明</div>
                    <div
                      v-for="level in getConfidenceKeys(msg)"
                      :key="level"
                      class="confidence-level"
                    >
                      <div class="confidence-label">
                        <span
                          class="confidence-dot"
                          :class="`confidence-dot-${level}`"
                        />
                        {{ getConfidenceLabel(level) }}
                      </div>
                      <div
                        v-for="(item, cIdx) in (msg as any).confidence_breakdown[level]"
                        :key="cIdx"
                        class="confidence-item"
                      >
                        {{ item }}
                      </div>
                    </div>
                  </div>

                </div>
              </div>

              <div class="answer-text" v-html="renderAssistantContent(msg)" />
            </div>
          </template>

          <template v-else-if="msg.role === 'system' && showSystemMessages">
            <div class="system-content">
              <InfoCircleOutlined />
              <span>系统：{{ msg.content }}</span>
            </div>
          </template>
        </div>
      </div>

      <div v-if="loading" class="message assistant streaming">
        <div class="message-content">
          <div class="assistant-content">
            <div v-if="streamingThinkingGroups.length" class="thinking-card">
              <div class="thinking-card-header static">
                <BulbOutlined class="thinking-card-icon" />
                <span class="thinking-card-label">
                  思考过程（{{ getStreamingStepCount }} 步<template v-if="getStreamingDuration"> · 工具耗时合计 {{ formatDuration(getStreamingDuration) }}</template>）
                </span>
              </div>
              <div class="thinking-card-body">
                <div class="analysis-section">
                  <ThinkingSteps
                    :groups="streamingThinkingGroups"
                    @select-citation="handleCitationClick"
                  />
                </div>
              </div>
            </div>
            <template v-if="currentStreamContent">
              <div class="answer-text" v-html="renderContent(currentStreamContent, streamingCitations)" />
              <span class="streaming-cursor">|</span>
            </template>
            <div v-else class="streaming-loading">
              <a-spin size="small" />
              <span class="loading-text">思考中...</span>
            </div>
          </div>
        </div>
      </div>
      </div>

      <div v-if="showContextInfo && !title" class="context-info-float">
        {{ contextRounds }}轮 / {{ formatTokenCount(contextTokens) }}tokens
      </div>
    </div>

    <div
      class="resize-handle"
      title="拖动调整输入区域高度"
      @mousedown="startResize"
    >
      <div class="resize-indicator"></div>
    </div>

    <div ref="chatInputRef" class="chat-input" :style="{ height: `${inputHeight}px` }">
      <div v-if="contextItems.length" class="context-hint">
        <a-tag
          v-for="item in contextItems"
          :key="item.id"
          closable
          @close="handleRemoveContext(item.id)"
        >
          {{ item.title }}
        </a-tag>
      </div>

      <div v-if="pendingImages.length" class="image-preview">
        <div
          v-for="(img, idx) in pendingImages"
          :key="idx"
          class="preview-item"
        >
          <img :src="img" alt="预览" />
          <CloseCircleOutlined class="remove-btn" @click="removeImage(idx)" />
        </div>
      </div>

      <div class="input-wrapper">
        <InlineCitationEditor
          ref="inlineCitationEditorRef"
          v-model="composerValue"
          :placeholder="placeholder"
          :disabled="loading"
          :search-citations="searchCitations"
          @submit="handleSend"
          @select-citation="handleInlineCitationSelect"
        />

        <div class="input-actions">
          <div class="left-actions">
            <a-button
              type="text"
              size="small"
              class="mention-trigger-btn"
              :disabled="loading"
              title="插入引用 @"
              @click="handleInsertMentionTrigger"
            >
              @
            </a-button>
            <a-button
              type="text"
              size="small"
              :disabled="loading || !allowImageUpload"
              :title="allowImageUpload ? '上传图片（开发中）' : '图片上传不可用'"
              @click="handleImageUpload"
            >
              <template #icon><PictureOutlined /></template>
            </a-button>
            <input
              ref="imageInputRef"
              type="file"
              accept="image/*"
              multiple
              style="display: none"
              @change="onImageSelected"
            />
          </div>

          <div class="center-actions">
            <a-select
              v-model:value="selectedModel"
              class="model-select"
              size="small"
              :loading="loadingModels"
              :disabled="loading"
              :title="selectedModel"
              @change="onModelChange"
            >
              <a-select-option
                v-for="model in models"
                :key="model.value"
                :value="model.value"
                :label="model.label"
                :title="model.label"
              >
                <span class="model-option-label">{{ model.label.replace('(付费)', '') }}</span>
                <a-tag v-if="model.label.includes('(付费)')" class="paid-tag" color="warning" size="small">付费</a-tag>
              </a-select-option>
            </a-select>
          </div>

          <div class="right-actions">
            <a-button
              v-if="loading"
              type="primary"
              danger
              size="small"
              class="icon-btn"
              title="停止生成"
              @click="handleStop"
            >
              <PauseCircleOutlined />
            </a-button>
            <a-button
              v-else
              type="primary"
              size="small"
              class="icon-btn"
              :disabled="!composerValue.content.trim() && !pendingImages.length"
              title="发送消息 (Enter)"
              @click="handleSend"
            >
              <SendOutlined />
            </a-button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 基础聊天组件。
 * 负责通用聊天 UI、输入区交互与消息展示，不直接耦合具体知识域接口。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  ClearOutlined,
  SendOutlined,
  PauseCircleOutlined,
  PictureOutlined,
  CloseCircleOutlined,
  InfoCircleOutlined,
  BulbOutlined,
  DownOutlined,
  RightOutlined
} from '@ant-design/icons-vue'
import CitationInline from './CitationInline.vue'
import InlineCitationEditor from './InlineCitationEditor.vue'
import ThinkingSteps from './ThinkingSteps.vue'
import type {
  BaseChatCitation,
  BaseChatContextItem,
  BaseChatMessage,
  BaseChatModelOption,
  BaseChatSendPayload,
  CitationBinding,
  InlineCitationCandidate,
  ThinkingTraceStep
} from '../types'
import {
  buildInlineCitationTagHtml,
  buildCitationSegments,
  getCitationLastSegment,
  mapReferenceToBaseChatCitation,
  parseMarkerNumber,
} from '../utils/citation'
import {
  countThinkingSteps,
  formatDuration,
  groupThinkingSteps,
  sumThinkingDuration,
} from '../utils/thinking'
import { formatTokenCount } from '../utils/token'

interface Props {
  messages: BaseChatMessage[]
  loading: boolean
  currentStreamContent?: string
  models?: BaseChatModelOption[]
  loadingModels?: boolean
  defaultModel?: string
  placeholder?: string
  contextItems?: BaseChatContextItem[]
  title?: string
  icon?: any
  showContextInfo?: boolean
  showSystemMessages?: boolean
  contextTokens?: number
  contextRounds?: number
  streamingThinkingSteps?: ThinkingTraceStep[]
  renderMessage?: (content: string) => string
  allowImageUpload?: boolean
  searchCitations?: (query: string) => Promise<InlineCitationCandidate[]>
}

const props = withDefaults(defineProps<Props>(), {
  currentStreamContent: '',
  models: () => [],
  loadingModels: false,
  defaultModel: '',
  placeholder: '输入消息，Enter 发送...',
  contextItems: () => [],
  title: 'AI 助手',
  icon: undefined,
  showContextInfo: true,
  showSystemMessages: false,
  contextTokens: 0,
  contextRounds: 0,
  streamingThinkingSteps: () => [],
  renderMessage: undefined,
  allowImageUpload: true,
  searchCitations: undefined
})

const emit = defineEmits<{
  send: [payload: BaseChatSendPayload, model: string]
  ready: []
  clear: []
  stop: []
  removeContext: [id: string]
  modelChange: [model: string]
  selectCitation: [citation: BaseChatCitation]
}>()

const messagesRef = ref<HTMLElement | null>(null)
const chatInputRef = ref<HTMLElement | null>(null)
const imageInputRef = ref<HTMLInputElement | null>(null)
const inlineCitationEditorRef = ref<InstanceType<typeof InlineCitationEditor> | null>(null)
const composerValue = ref<BaseChatSendPayload>({ content: '', citations: [] })
const pendingImages = ref<string[]>([])
const selectedModel = ref(props.defaultModel)
const inputHeight = ref(150)
const isResizing = ref(false)
const startY = ref(0)
const startHeight = ref(0)
const expandedCitationKeys = ref<string[]>([])
const minInputHeight = 100
const maxInputHeightRatio = 0.5

const displayMessages = computed(() => {
  if (props.showSystemMessages) {
    return props.messages
  }

  return props.messages.filter(message => message.role !== 'system')
})

const streamingThinkingGroups = computed(() => (
  groupThinkingSteps(props.streamingThinkingSteps || [])
))
// 流式期间实时提取的引用（随 thinking steps 增量更新，供正文标记实时渲染成引用 tag）
const streamingCitations = computed(() => buildStreamingCitations())

const getStreamingStepCount = computed(() => countThinkingSteps(streamingThinkingGroups.value))
const getStreamingDuration = computed(() => sumThinkingDuration(streamingThinkingGroups.value))

/**
 * 去重引用，避免同页同段重复展示。
 */
const getUniqueCitations = (message: BaseChatMessage) => {
  const citations = Array.isArray(message.citations) ? message.citations : []
  const seen = new Set<string>()
  return citations.filter(citation => {
    const key = [
      citation.target_id,
      citation.doc_id,
      citation.page_idx,
      citation.section_path,
      citation.marker || ''
    ].join('::')
    if (seen.has(key)) {
      return false
    }
    seen.add(key)
    return true
  })
}

/**
 * 返回去重后的可见引用列表。
 */
const getVisibleCitations = (message: BaseChatMessage) => {
  return getUniqueCitations(message)
}

/**
 * 流式期间从 thinking steps 的 resultItems 提取带 cite 标记的引用，
 * 让正文里的 [K1]/[T1] 标记在流式输出时就能渲染成引用 tag（与完成态样式一致）。
 */
const buildStreamingCitations = (): BaseChatCitation[] => {
  const steps = props.streamingThinkingSteps || []
  const result: BaseChatCitation[] = []
  const seen = new Set<string>()
  for (const step of steps) {
    for (const item of step.resultItems || []) {
      const marker = String((item as any).cite || '')
      if (!marker) continue
      const key = `${marker}::${item.item_id}`
      if (seen.has(key)) continue
      seen.add(key)
      const meta = item.metadata || {}
      result.push({
        target_id: String((item as any).citation_target_id || item.item_id || ''),
        target_type: item.entity_type || 'content',
        doc_id: item.doc_id || '',
        doc_title: item.doc_title || item.title || '未命名文档',
        page_idx: Number(meta.page_idx || 0),
        page_label: meta.page_label,
        section_path: String(meta.section_path || ''),
        snippet: item.text,
        content: item.text,
        content_type: 'text',
        score: item.score || 0,
        marker,
      } as BaseChatCitation)
    }
  }
  return result
}

/**
 * 为引用项生成稳定 key，便于维护折叠状态。
 */
const getCitationKey = (citation: BaseChatCitation) => [
  citation.target_id,
  citation.doc_id,
  citation.page_idx,
  citation.section_path
].join('::')

/**
 * 判断某条引用当前是否处于展开状态。
 */
const isCitationExpanded = (key: string) => expandedCitationKeys.value.includes(key)

/**
 * 切换引用项的展开状态。
 */
const toggleCitationExpanded = (key: string) => {
  if (isCitationExpanded(key)) {
    expandedCitationKeys.value = expandedCitationKeys.value.filter(item => item !== key)
    return
  }
  expandedCitationKeys.value = [...expandedCitationKeys.value, key]
}

/** 思考过程区域的展开状态（按消息 ID 跟踪，默认折叠） */
const expandedThinkingKeys = ref<string[]>([])

const getThinkingGroups = (message: BaseChatMessage) => (
  groupThinkingSteps(message.thinking_trace || [])
)

const getThinkingStepCount = (message: BaseChatMessage) => (
  countThinkingSteps(getThinkingGroups(message))
)

const getThinkingDuration = (message: BaseChatMessage) => (
  sumThinkingDuration(getThinkingGroups(message))
)

const isThinkingExpanded = (message: BaseChatMessage) => (
  expandedThinkingKeys.value.includes(message.id || '')
)

const toggleThinkingExpanded = (message: BaseChatMessage) => {
  const key = message.id || ''
  if (isThinkingExpanded(message)) {
    expandedThinkingKeys.value = expandedThinkingKeys.value.filter(item => item !== key)
  } else {
    expandedThinkingKeys.value = [...expandedThinkingKeys.value, key]
  }
}

/**
 * 点击引用时同步触发展开和外部定位。
 */
const handleCitationClick = (citation: BaseChatCitation) => {
  toggleCitationExpanded(getCitationKey(citation))
  emit('selectCitation', citation)
}

const getConfidenceKeys = (msg: BaseChatMessage): string[] => {
  const cb = (msg as any).confidence_breakdown
  if (!cb) return []
  return (['high', 'medium', 'low'] as const).filter(k => cb[k] && cb[k].length > 0)
}

const getConfidenceLabel = (level: string): string => {
  const labels: Record<string, string> = {
    high: '高置信度（证据充分）',
    medium: '中置信度（部分证据）',
    low: '推测（模型常识，非知识库）'
  }
  return labels[level] || level
}

/**
 * 判断当前消息是否需要显示 hover 时间。
 */
const shouldShowTimestamp = (message: BaseChatMessage) => (
  ['user', 'assistant'].includes(message.role) && typeof message.timestamp === 'number'
)

/**
 * 将消息时间格式化为 yyyy-MM-dd HH:mm:ss。
 */
const formatMessageTimestamp = (timestamp?: number) => {
  if (!timestamp) return ''
  const value = new Date(timestamp)
  const pad = (input: number) => String(input).padStart(2, '0')
  return [
    value.getFullYear(),
    pad(value.getMonth() + 1),
    pad(value.getDate())
  ].join('-') + ` ${pad(value.getHours())}:${pad(value.getMinutes())}:${pad(value.getSeconds())}`
}

/**
 * 转义纯文本内容，避免在默认渲染路径中注入 HTML。
 */
const escapeHtml = (content: string): string => {
  return content
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

/**
 * 渲染消息内容。
 * 如果上层提供了领域渲染器，则优先使用；否则退回纯文本换行渲染。
 * 流式时传入 streamingCitations 可将 [K1]/[T1] 标记实时渲染成引用 tag。
 */
const renderContent = (content: string, streamingCitations?: BaseChatCitation[]): string => {
  const html = props.renderMessage
    ? props.renderMessage(content)
    : escapeHtml(content).replace(/\n/g, '<br />')
  if (streamingCitations?.length) {
    // 标记 → tag：流式期间即可显示引用框（与完成态一致，避免结束后跳变）
    const markerHtml = html.replace(/\[([KTE]\d+)\]/g, (raw, marker: string) => {
      const index = streamingCitations.findIndex(citation => citation.marker === marker)
      if (index < 0) return raw
      return buildInlineCitationTagHtml(streamingCitations[index], index, parseMarkerNumber(marker))
    })
    return markerHtml
  }
  // 流式占位：只替换已完整出现的 [K1]/[T1]/[E1]，未闭合的 [K 保持原样
  return html.replace(/\[([KTE]\d+)\]/g, (_raw, marker: string) =>
    `<span class="stream-citation-marker">${parseMarkerNumber(marker) ?? 0}</span>`)
}

/**
 * 渲染助手消息：把正文里出现的文档标题/章节名替换为可点击的引用链接，
 * 点击后与参考依据面板走同一条定位跳转链路。
 */
const renderAssistantContent = (message: BaseChatMessage): string => {
  const citations = getVisibleCitations(message)
  let content = message.content || ''
  const links: Array<{ index: number; label: string }> = []

  if (citations.length) {
    // 第一轮：优先匹配“文档 + 章节”的完整短语，避免同名文档挂错引用
    const matchedIndexes = new Set<number>()
    citations.forEach((citation, index) => {
      // 正文已经写了 [Kx] 标记时，交给“标记 → 内联 tag”替换，
      // 不再把文档名/章节名单独做成链接，避免同一处出现两个可点元素
      if (citation.marker && content.includes(`[${citation.marker}]`)) return
      const spanCandidates = buildSectionCitationCandidates(citation)
      for (const needle of spanCandidates) {
        const positions: number[] = []
        let position = content.indexOf(needle)
        while (position >= 0) {
          positions.push(position)
          position = content.indexOf(needle, position + needle.length)
        }
        if (!positions.length) continue
        const token = `__INLINE_CIT_${index}__`
        // 从后往前替换，保证前面的位置索引仍然有效
        for (let i = positions.length - 1; i >= 0; i -= 1) {
          const pos = positions[i]
          content = content.slice(0, pos) + token + content.slice(pos + needle.length)
        }
        links.push({ index, label: needle })
        matchedIndexes.add(index)
        break
      }
    })
    // 第二轮：正文只写了文档名时，兜底把文档名变成链接
    citations.forEach((citation, index) => {
      if (matchedIndexes.has(index)) return
      if (citation.marker && content.includes(`[${citation.marker}]`)) return
      const spanCandidates = buildDocOnlyCitationCandidates(citation)
      for (const needle of spanCandidates) {
        const positions: number[] = []
        let position = content.indexOf(needle)
        while (position >= 0) {
          positions.push(position)
          position = content.indexOf(needle, position + needle.length)
        }
        if (!positions.length) continue
        const token = `__INLINE_CIT_${index}__`
        for (let i = positions.length - 1; i >= 0; i -= 1) {
          const pos = positions[i]
          content = content.slice(0, pos) + token + content.slice(pos + needle.length)
        }
        links.push({ index, label: needle })
        break
      }
    })
  }

  const html = props.renderMessage
    ? props.renderMessage(content)
    : escapeHtml(content).replace(/\n/g, '<br />')

  // 标记 → tag 放在最后：tag 内包含“《文档》· 章节”文本，若先替换会被旧匹配二次命中
  const markerHtml = html.replace(/\[([KTE]\d+)\]/g, (raw, marker: string) => {
    const index = citations.findIndex(citation => citation.marker === marker)
    if (index < 0) return raw
    return buildInlineCitationTagHtml(citations[index], index, parseMarkerNumber(marker))
  })

  return markerHtml.replace(/__INLINE_CIT_(\d+)__/g, (_, rawIndex) => {
    const link = links.find(item => item.index === Number(rawIndex))
    if (!link) return ''
    const citation = citations[link.index]
    if (!citation) return ''
    return [
      '<a class="inline-citation-link"',
      ` data-citation-index="${link.index}"`,
      ` data-doc-id="${escapeHtml(citation.doc_id || '')}"`,
      ` data-target-id="${escapeHtml(citation.target_id || '')}"`,
      ` data-doc-title="${escapeHtml(citation.doc_title || '')}"`,
      ` data-page-idx="${Number(citation.page_idx || 0)}"`,
      ` data-section-path="${escapeHtml(citation.section_path || '')}"`,
      ` data-snippet="${escapeHtml(citation.snippet || '')}"`,
      `>${escapeHtml(link.label)}</a>`,
    ].join('')
  })
}

/** 文档标题的常见写法：带/不带书名号、带/不带扩展名 */
const buildDocTitleForms = (docTitle: string): string[] => {
  const base = String(docTitle || '').replace(/\.(docx?|pdf|xlsx?|pptx?|md|markdown|txt)$/i, '')
  if (!base) return []
  const extensions = ['pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'md', 'txt']
  const forms = new Set<string>([
    `《${docTitle}》`,
    `《${base}》`,
    docTitle,
    base,
  ])
  for (const ext of extensions) {
    forms.add(`《${base}.${ext}》`)
    forms.add(`${base}.${ext}`)
  }
  return [...forms].filter(Boolean)
}

/** 只含文档名的候选短语（兜底链接） */
const buildDocOnlyCitationCandidates = (citation: BaseChatCitation): string[] => {
  return buildDocTitleForms(citation.doc_title)
}

/** 含“文档 + 章节”的候选短语，优先匹配 */
const buildSectionCitationCandidates = (citation: BaseChatCitation): string[] => {
  const docTitle = String(citation.doc_title || '').trim()
  if (!docTitle) return []
  const section = String(citation.section_path || '').trim()
  const lastSegment = getCitationLastSegment(citation.section_path)
  const sections = [section, lastSegment].filter((value, index, arr) => value && arr.indexOf(value) === index)
  if (!sections.length) return []
  const candidates: string[] = []
  for (const doc of buildDocTitleForms(docTitle)) {
    for (const sec of sections) {
      candidates.push(`${doc}中“${sec}”章节`)
      candidates.push(`${doc}中“${sec}”`)
      candidates.push(`${doc}中"${sec}"章节`)
      candidates.push(`${doc}中"${sec}"`)
      candidates.push(`${doc}第“${sec}”章节`)
      candidates.push(`${doc}第“${sec}”`)
      candidates.push(`${doc}第"${sec}"章节`)
      candidates.push(`${doc}第"${sec}"`)
      candidates.push(`${doc}第${sec}章节`)
      candidates.push(`${doc}第${sec}`)
      candidates.push(`${doc}“${sec}”章节`)
      candidates.push(`${doc}“${sec}”`)
      candidates.push(`${doc}"${sec}"章节`)
      candidates.push(`${doc}"${sec}"`)
      candidates.push(`${doc}${sec}章节`)
      candidates.push(`${doc}${sec}`)
    }
  }
  // 去重，更具体的短语排前面
  return Array.from(new Set(candidates))
}

/** 点击正文内联引用链接：与参考依据面板共用 selectCitation 跳转 */
const handleMessageClick = (event: MouseEvent) => {
  const target = (event.target as HTMLElement | null)?.closest?.(
    '.inline-citation-link, .citation-circle'
  ) as HTMLElement | null
  if (!target) return
  const docId = String(target.dataset.docId || '')
  if (!docId) return
  emit('selectCitation', {
    target_id: String(target.dataset.targetId || ''),
    target_type: 'content',
    doc_id: docId,
    doc_title: String(target.dataset.docTitle || ''),
    page_idx: Number(target.dataset.pageIdx || 0),
    section_path: String(target.dataset.sectionPath || ''),
    snippet: String(target.dataset.snippet || ''),
    score: 0,
  })
}

const getInlineSegments = (message: BaseChatMessage) => buildCitationSegments({
  content: message.content,
  citations: Array.isArray(message.inlineCitations) ? message.inlineCitations : []
})

/**
 * 将消息区域滚动到底部。
 */
const scrollToBottom = () => {
  nextTick(() => {
    if (messagesRef.value) {
      messagesRef.value.scrollTop = messagesRef.value.scrollHeight
    }
  })
}

/**
 * 在模型列表变化后同步默认模型，避免空选中状态。
 */
const syncSelectedModel = () => {
  if (selectedModel.value) {
    return
  }

  if (props.defaultModel) {
    selectedModel.value = props.defaultModel
    return
  }

  if (props.models.length > 0) {
    selectedModel.value = props.models[0].value
  }
}

/**
 * 触发发送事件并在成功发起后清空输入态。
 */
const handleSend = () => {
  const payload: BaseChatSendPayload = {
    content: composerValue.value.content.trim(),
    citations: Array.isArray(composerValue.value.citations) ? composerValue.value.citations : []
  }
  const content = payload.content
  if (!content && !pendingImages.value.length) {
    return
  }

  emit('send', payload, selectedModel.value)
  resetComposer()
  scrollToBottom()
}

/**
 * 重置输入态，确保发送后不会残留旧问题。
 */
const resetComposer = () => {
  composerValue.value = { content: '', citations: [] }
  pendingImages.value = []
}

const handleInlineCitationSelect = (binding: CitationBinding) => {
  emit('selectCitation', mapReferenceToBaseChatCitation(binding.reference))
}

/**
 * 通知上层清空当前会话。
 */
const handleClear = () => {
  emit('clear')
}

/**
 * 通知上层停止当前流式生成。
 */
const handleStop = () => {
  emit('stop')
}

/**
 * 通知上层移除上下文标签。
 */
const handleRemoveContext = (id: string) => {
  emit('removeContext', id)
}

/**
 * 响应模型切换事件。
 */
const onModelChange = (model: string) => {
  selectedModel.value = model
  emit('modelChange', model)
}

/**
 * 打开隐藏的图片选择框。
 */
const handleImageUpload = () => {
  if (!props.allowImageUpload) {
    return
  }

  imageInputRef.value?.click()
}

const handleInsertMentionTrigger = async () => {
  if (props.loading) {
    return
  }
  await inlineCitationEditorRef.value?.insertMentionTrigger()
}

/**
 * 读取图片为预览数据，供后续多模态能力接入。
 */
const onImageSelected = (event: Event) => {
  const target = event.target as HTMLInputElement
  const files = target.files
  if (!files) {
    return
  }

  Array.from(files).forEach(file => {
    const reader = new FileReader()
    reader.onload = loadEvent => {
      if (loadEvent.target?.result) {
        pendingImages.value.push(loadEvent.target.result as string)
      }
    }
    reader.readAsDataURL(file)
  })

  target.value = ''
}

/**
 * 移除待发送图片预览项。
 */
const removeImage = (index: number) => {
  pendingImages.value.splice(index, 1)
}

/**
 * 开始拖动调整输入区高度。
 */
const startResize = (event: MouseEvent) => {
  isResizing.value = true
  startY.value = event.clientY
  startHeight.value = inputHeight.value

  document.addEventListener('mousemove', handleResize)
  document.addEventListener('mouseup', stopResize)
}

/**
 * 根据鼠标位移实时更新输入区高度。
 */
const handleResize = (event: MouseEvent) => {
  if (!isResizing.value) {
    return
  }

  const deltaY = startY.value - event.clientY
  const newHeight = startHeight.value + deltaY
  const parentHeight = chatInputRef.value?.parentElement?.clientHeight || window.innerHeight
  const maxHeight = parentHeight * maxInputHeightRatio

  inputHeight.value = Math.max(minInputHeight, Math.min(newHeight, maxHeight))
}

/**
 * 结束拖动调整并解绑全局事件。
 */
const stopResize = () => {
  isResizing.value = false
  document.removeEventListener('mousemove', handleResize)
  document.removeEventListener('mouseup', stopResize)
}

watch(() => props.messages.length, scrollToBottom)
watch(() => props.currentStreamContent, scrollToBottom)
watch(() => props.loading, value => {
  if (value) {
    resetComposer()
  }
})
watch(() => props.defaultModel, value => {
  selectedModel.value = value
})
watch(() => props.models, syncSelectedModel, { deep: true, immediate: true })

onMounted(() => {
  syncSelectedModel()
  emit('ready')
})

onBeforeUnmount(() => {
  stopResize()
})

defineExpose({
  composerValue,
  selectedModel,
  clearComposer: resetComposer
})
</script>

<style lang="less" scoped>
.base-chat-component {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  background: var(--chat-root-bg, var(--bg-primary));
}

.chat-header {
  display: flex;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color);
  background: var(--chat-root-bg, var(--panel-header-bg));
  font-weight: 500;
  font-size: 14px;
  color: var(--text-primary);

  .header-icon {
    margin-right: 8px;
    display: flex;
    align-items: center;
  }

  .header-title {
    flex: 1;
  }

  .header-actions {
    display: flex;
    align-items: center;
    gap: 4px;

    .context-info {
      font-size: 12px;
      color: var(--text-secondary);
      margin-right: 4px;
    }

    :deep(.ant-btn) {
      padding: 0 4px;
    }
  }
}

.chat-messages-wrap {
  position: relative;
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.context-info-float {
  position: absolute;
  top: 8px;
  right: 12px;
  z-index: 2;
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid var(--border-color);
  background: var(--bg-secondary);
  color: var(--text-secondary);
  font-size: 11px;
  line-height: 18px;
  pointer-events: none;
  opacity: 0.9;
}

.chat-messages {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 16px;
  background: var(--chat-root-bg, var(--bg-primary));

  .message {
    margin-bottom: 16px;
    display: flex;

    .message-content {
      width: 100%;
      display: flex;
      flex-direction: column;
    }

    &.user {
      justify-content: flex-end;

      .message-content {
        align-items: flex-end;
      }

      .user-content {
        display: inline-block;
        background: var(--chat-user-bubble-bg);
        color: var(--chat-user-bubble-text);
        padding: 10px 14px;
        border-radius: 12px 12px 0 12px;
        max-width: 85%;
        min-width: 32px;
        word-break: normal;
        overflow-wrap: break-word;
        white-space: pre-wrap;
        box-shadow: 0 2px 8px rgba(24, 144, 255, 0.2);

        .user-images {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
          margin-bottom: 8px;

          .uploaded-image {
            max-width: 120px;
            max-height: 120px;
            border-radius: 8px;
            object-fit: cover;
          }
        }

        .user-text {
          display: inline;
          line-height: 1.5;
          word-break: normal;
          overflow-wrap: break-word;
          white-space: pre-wrap;
        }
      }
    }

    &.assistant {
      justify-content: flex-start;

      .message-content {
        align-items: flex-start;
      }

      .assistant-content {
        display: inline-block;
        background: var(--chat-assistant-bubble-bg);
        color: var(--chat-assistant-bubble-text);
        padding: 12px 16px;
        border-radius: 12px 12px 12px 0;
        max-width: 85%;
        min-width: 60px;
        overflow-wrap: break-word;
        word-break: normal;

        .message-chain {
          font-size: 12px;
          line-height: 1.5;
          color: var(--text-secondary);
          margin-bottom: 10px;
        }

        .thinking-card {
          margin: 0 0 10px;
          border: 1px solid var(--border-color);
          border-radius: 10px;
          background: rgba(128, 128, 128, 0.05);
          overflow: hidden;

          .thinking-card-header {
            display: flex;
            align-items: center;
            gap: 6px;
            width: 100%;
            padding: 6px 10px;
            border: none;
            background: transparent;
            color: var(--text-secondary);
            font-size: 12px;
            line-height: 1.4;
            text-align: left;
            cursor: pointer;

            &:hover {
              background: rgba(128, 128, 128, 0.08);
            }

            .thinking-card-icon {
              display: inline-flex;
              align-items: center;
              font-size: 13px;
              color: var(--text-tertiary, #999);
            }

            .thinking-card-label {
              flex: 1;
              font-weight: 500;
            }

            .thinking-card-arrow {
              display: inline-flex;
              align-items: center;
              font-size: 10px;
              flex-shrink: 0;
            }
          }

          .thinking-card-header.static {
            cursor: default;

            &:hover {
              background: transparent;
            }
          }

          .thinking-card-body {
            padding: 4px 10px 10px;
            border-top: 1px solid var(--border-color);
            display: flex;
            flex-direction: column;
            gap: 10px;
            font-size: 12px;
            line-height: 1.6;
            color: var(--text-secondary);

            .analysis-section {
              display: flex;
              flex-direction: column;
              gap: 6px;

              .analysis-title {
                font-size: 12px;
                font-weight: 600;
                color: var(--text-secondary);
                letter-spacing: 0.02em;
              }
            }

            .message-chain {
              margin-bottom: 0;
            }
          }
        }

        .answer-text {
          line-height: 1.6;

          :deep(p),
          :deep(ul),
          :deep(ol),
          :deep(blockquote),
          :deep(pre),
          :deep(table),
          :deep(.math-block),
          :deep(.media-table),
          :deep(.media-formula) {
            margin: 0.6em 0;
          }

          :deep(.citation-circle) {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-width: 18px;
            height: 18px;
            margin: 0 2px;
            padding: 0 3px;
            border-radius: 50%;
            background: #3f3f46;
            color: #d4d4d8;
            font-size: 10px;
            font-weight: 600;
            line-height: 1;
            vertical-align: 0.15em;
            cursor: pointer;
            transition: background-color 0.16s ease;

            &:hover {
              background-color: var(--primary-color);
            }
          }

          :deep(.stream-citation-marker) {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-width: 18px;
            height: 18px;
            margin: 0 2px;
            padding: 0 3px;
            border-radius: 50%;
            background: #3f3f46;
            color: #d4d4d8;
            font-size: 10px;
            font-weight: 600;
            line-height: 1;
            vertical-align: 0.15em;
          }

          :deep(ul) {
            list-style: disc;
            padding-left: 1.5em;
          }

          :deep(ol) {
            list-style: decimal;
            padding-left: 1.5em;
          }

          :deep(li) {
            margin: 0.25em 0;
          }

          :deep(ul ul),
          :deep(ol ul) {
            list-style: circle;
          }

          :deep(ul ul ul),
          :deep(ol ul ul) {
            list-style: square;
          }

          :deep(code) {
            background: var(--chat-code-bg);
            padding: 2px 6px;
            border-radius: 4px;
            font-family: 'Courier New', monospace;
            font-size: 0.9em;
          }

          :deep(pre) {
            background: var(--chat-pre-bg);
            padding: 12px;
            border-radius: 8px;
            overflow-x: auto;
            margin: 8px 0;

            code {
              background: none;
              padding: 0;
            }
          }

          :deep(strong) {
            font-weight: 600;
          }

          :deep(.katex) {
            font-size: 1em;
          }

          :deep(.katex-display) {
            margin: 0;
            overflow-x: auto;
            overflow-y: hidden;
            padding: 4px 0;
          }

          :deep(.math-block),
          :deep(.media-formula) {
            overflow-x: auto;
            max-width: 100%;
          }

          :deep(.media-table) {
            overflow: auto;
            max-width: 100%;
          }

          :deep(.inline-citation-link) {
            color: var(--primary-color, #1677ff);
            text-decoration: underline;
            cursor: pointer;

            &:hover {
              opacity: 0.85;
            }
          }

          :deep(table) {
            width: 100%;
            border-collapse: collapse;
            table-layout: auto;
          }

          :deep(th),
          :deep(td) {
            border: 1px solid var(--border-color);
            padding: 6px 8px;
            background: transparent;
            vertical-align: top;
          }

          :deep(img),
          :deep(.markdown-image) {
            display: block;
            max-width: 100%;
            border-radius: 8px;
          }
        }

        .citation-panel {
          margin-top: 12px;
          padding-top: 10px;
          border-top: 1px solid var(--border-color);
          display: flex;
          flex-direction: column;
          gap: 8px;
        }

        .citation-title {
          font-size: 12px;
          font-weight: 600;
          color: var(--text-secondary);
          letter-spacing: 0.02em;
        }

        .citation-item {
          width: 100%;
          text-align: left;
          padding: 10px 12px;
          border-radius: 10px;
          background: var(--chat-citation-bg);
          border-left: 3px solid var(--chat-citation-border);
          box-shadow: inset 0 0 0 1px rgba(250, 173, 20, 0.18);
          border-top: none;
          border-right: none;
          border-bottom: none;
          cursor: pointer;
          color: inherit;
          font: inherit;
        }

        .citation-header {
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .citation-toggle {
          color: var(--chat-citation-accent);
          display: inline-flex;
          align-items: center;
          justify-content: center;
          flex: 0 0 auto;
        }

        .citation-meta {
          display: flex;
          align-items: center;
          flex-wrap: wrap;
          gap: 8px;
          font-size: 12px;
          min-width: 0;
        }

        .citation-doc {
          font-weight: 600;
          color: var(--text-primary);
          min-width: 0;
          word-break: break-word;
        }

        .citation-page {
          color: var(--chat-citation-accent);
          background: rgba(250, 173, 20, 0.14);
          border-radius: 999px;
          padding: 1px 6px;
        }

        .citation-location {
          font-size: 12px;
          color: var(--text-secondary);
        }

        .citation-score {
          font-size: 11px;
          color: var(--success-color, #52c41a);
          background: rgba(82, 196, 26, 0.1);
          border-radius: 999px;
          padding: 1px 6px;
        }

        .citation-snippet {
          font-size: 12px;
          line-height: 1.6;
          color: var(--text-primary);
          white-space: pre-wrap;
          margin-top: 8px;
        }

        .citation-rich-media {
          margin-top: 8px;
          font-size: 12px;
          line-height: 1.6;
        }

        .citation-rich-media :deep(.media-table) {
          overflow-x: auto;
          max-width: 100%;
          margin: 0.3em 0;
        }

        .citation-rich-media :deep(.media-table table) {
          width: 100%;
          border-collapse: collapse;
        }

        .citation-rich-media :deep(.media-table th),
        .citation-rich-media :deep(.media-table td) {
          border: 1px solid var(--border-color);
          padding: 3px 6px;
          font-size: 11px;
        }

        .citation-rich-media :deep(.media-formula) {
          overflow-x: auto;
          max-width: 100%;
          margin: 0.3em 0;
          font-family: 'Times New Roman', serif;
        }

        .citation-rich-media :deep(.media-image) {
          max-width: 100%;
          border-radius: 4px;
        }

        .gap-item {
          padding: 8px 10px;
          border-radius: 8px;
          background: rgba(250, 140, 22, 0.06);
          border-left: 3px solid var(--warning-color, #fa8c16);
        }

        .gap-description {
          font-size: 12px;
          line-height: 1.6;
          color: var(--text-primary);
        }

        .gap-index {
          font-weight: 700;
          color: var(--warning-color, #fa8c16);
          margin-right: 2px;
        }

        .gap-suggestions {
          margin-top: 6px;
          display: flex;
          align-items: center;
          flex-wrap: wrap;
          gap: 4px;
        }

        .gap-suggestion-label {
          font-size: 11px;
          color: var(--text-secondary);
        }

        .gap-tag {
          font-size: 11px;
          line-height: 1;
        }

        .confidence-level {
          display: flex;
          flex-direction: column;
          gap: 2px;
        }

        .confidence-label {
          font-size: 12px;
          font-weight: 600;
          color: var(--text-primary);
          display: flex;
          align-items: center;
          gap: 6px;
        }

        .confidence-dot {
          display: inline-block;
          width: 8px;
          height: 8px;
          border-radius: 50%;
          flex: 0 0 auto;
        }

        .confidence-dot-high {
          background: #52c41a;
        }

        .confidence-dot-medium {
          background: #faad14;
        }

        .confidence-dot-low {
          background: #ff4d4f;
        }

        .confidence-item {
          font-size: 12px;
          line-height: 1.5;
          color: var(--text-secondary);
          padding-left: 14px;
        }

        .streaming-cursor {
          animation: blink 1s infinite;
          color: var(--chat-streaming-cursor);
        }

        .streaming-loading {
          display: flex;
          align-items: center;
          gap: 8px;
          color: var(--text-secondary);
          font-size: 12px;

          .loading-text {
            margin-left: 0;
          }
        }

        .loading-text {
          margin-left: 8px;
          color: var(--text-secondary);
        }
      }

      &.streaming .assistant-content {
        background: var(--chat-streaming-bg);
      }
    }

    &.system {
      justify-content: center;

      .system-content {
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 6px 12px;
        background: var(--chat-system-bg);
        border: 1px solid var(--chat-system-border);
        border-radius: 16px;
        font-size: 12px;
        color: var(--chat-system-text);
      }
    }
  }

  .message-time {
    opacity: 0;
    transform: translateY(2px);
    transition: opacity 0.16s ease, transform 0.16s ease;
    font-size: 11px;
    line-height: 1.4;
    color: var(--text-secondary);
    margin-bottom: 4px;
    pointer-events: none;
  }

  .message:hover .message-time {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes blink {
  0%, 50% { opacity: 1; }
  51%, 100% { opacity: 0; }
}

.resize-handle {
  height: 8px;
  flex-shrink: 0;
  background: transparent;
  cursor: row-resize;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.2s;

  &:hover {
    background: var(--border-color);
  }

  .resize-indicator {
    width: 40px;
    height: 3px;
    background: var(--border-color);
    border-radius: 2px;
    transition: background 0.2s;
  }

  &:hover .resize-indicator {
    background: var(--primary-color);
  }
}

.chat-input {
  flex-shrink: 0;
  padding: 12px 16px;
  border-top: 1px solid var(--border-color);
  background: var(--bg-secondary);
  display: flex;
  flex-direction: column;
  overflow: visible;
  position: relative;
  z-index: 5;

  .context-hint {
    margin-bottom: 8px;
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .image-preview {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-bottom: 8px;
    padding: 8px;
    background: var(--bg-tertiary);
    border-radius: 8px;

    .preview-item {
      position: relative;
      width: 80px;
      height: 80px;

      img {
        width: 100%;
        height: 100%;
        object-fit: cover;
        border-radius: 6px;
      }

      .remove-btn {
        position: absolute;
        top: -6px;
        right: -6px;
        font-size: 16px;
        color: var(--chat-error-color);
        background: var(--bg-secondary);
        border-radius: 50%;
        cursor: pointer;

        &:hover {
          color: var(--chat-error-hover);
        }
      }
    }
  }

  .input-wrapper {
    position: relative;
    display: flex;
    flex-direction: column;
    flex: 1;
    min-height: 0;
    overflow: visible;
    z-index: 6;

    :deep(.ant-input) {
      flex: 1;
      border-radius: 12px;
      resize: none;
      background: var(--bg-secondary);
      color: var(--text-primary);
      border-color: var(--border-color);
      padding: 12px 12px 48px 12px;
      font-size: 14px;
      line-height: 1.6;
      overflow-y: auto;

      &::placeholder {
        color: var(--text-secondary);
      }

      &:focus {
        border-color: var(--primary-color);
        box-shadow: 0 0 0 2px rgba(24, 144, 255, 0.2);
      }
    }
  }

  .input-actions {
    position: absolute;
    bottom: 8px;
    left: 8px;
    right: 8px;
    display: flex;
    align-items: center;
    gap: 8px;
    pointer-events: none;

    .left-actions,
    .center-actions,
    .right-actions {
      pointer-events: auto;
    }

    .left-actions {
      display: flex;
      gap: 2px;
      flex-shrink: 0;

      .mention-trigger-btn {
        color: rgba(255, 255, 255, 0.7);

        &:hover,
        &:focus {
          color: rgba(255, 255, 255, 0.88);
        }
      }
    }

    .center-actions {
      flex: 1;
      min-width: 0;
      display: flex;
      justify-content: flex-end;

      .model-select {
        width: 100%;
        max-width: 180px;

        :deep(.ant-select-selector) {
          font-size: 12px;
          border-radius: 6px;
          background: var(--bg-secondary);
          color: var(--text-primary);
          border-color: var(--border-color);
        }

        :deep(.ant-select-selection-item) {
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
          color: var(--text-primary);
          font-size: 12px;
        }

        :deep(.ant-select-arrow) {
          color: var(--text-secondary);
        }

        :deep(.ant-select-item-option-content) {
          font-size: 12px;
        }
      }
    }

    :global(.ant-select-dropdown .ant-select-item-option-content) {
      font-size: 12px;
      display: flex;
      align-items: center;
      gap: 4px;
    }

    :global(.paid-tag) {
      font-size: 10px;
      line-height: 16px;
      height: 18px;
      padding: 0 4px;
      margin: 0;
      border-radius: 3px;
      transform: scale(0.9);
      transform-origin: center center;
    }

    .right-actions {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-shrink: 0;

      .icon-btn {
        width: 24px;
        height: 24px;
        padding: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        border-radius: 6px;

        .anticon {
          font-size: 14px;
        }
      }
    }
  }
}
</style>
