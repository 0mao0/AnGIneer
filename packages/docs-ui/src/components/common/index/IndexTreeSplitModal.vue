<template>
  <IndexTreeModalShell
    :open="open"
    :confirm-loading="loading"
    :ok-button-props="{ disabled: submitDisabled }"
    ok-text="拆分节点"
    cancel-text="取消"
    :width="1040"
    :dark-mode="darkMode"
    @update:open="emit('update:open', $event)"
    @cancel="emit('cancel')"
    @ok="submitSplit"
  >
    <template #title>
      <div class="split-modal-title">拆分节点</div>
    </template>
    <div class="split-dialog-layout">
      <div class="split-dialog-main">
        <div class="split-overview-card">
          <div class="split-overview-title-row">
            <div>
              <div class="split-overview-title">拆分预览</div>
              <div class="split-overview-hint">第一个片段保留在当前 block，其余片段会按顺序新增为后续 block。</div>
            </div>
            <div class="split-overview-stats">
              <span class="split-overview-stat">目标 1 个</span>
              <span class="split-overview-stat">有效片段 {{ nonEmptySplitSegmentCount }}</span>
              <span class="split-overview-stat">总字数 {{ splitCharacterCount }}</span>
            </div>
          </div>
        </div>
        <div v-if="node" class="split-target-card">
          <div class="split-target-title-row">
            <div class="split-target-title">当前节点</div>
            <div class="split-target-tags">
              <a-tag class="split-target-tag">{{ node.block_type || 'segment' }}</a-tag>
              <a-tag class="split-target-tag">页 {{ Number(node.page_idx || 0) + 1 }}</a-tag>
              <a-tag class="split-target-tag">块 {{ node.block_seq || 0 }}</a-tag>
            </div>
          </div>
          <div class="split-target-text">{{ nodeDisplayTitle }}</div>
        </div>
        <div class="split-source-card">
          <div class="split-source-title-row">
            <div class="split-source-title">原始文本</div>
            <span class="split-source-meta">{{ sourceText.length }} 字</span>
          </div>
          <pre class="split-source-text">{{ sourceText }}</pre>
        </div>
      </div>
      <div class="split-dialog-side">
        <div class="split-editor-card">
          <div class="split-segment-toolbar">
            <div class="split-segment-toolbar-actions">
              <a-button size="small" @click="appendSplitSegment">新增片段</a-button>
              <a-button size="small" @click="resetSplitSegmentsFromSource">重新初始化</a-button>
            </div>
            <span class="split-segment-summary">至少保留 2 个非空片段后才能提交。</span>
          </div>
          <div class="split-segment-list">
            <div v-for="(segment, index) in splitSegments" :key="segment.id" class="split-segment-card">
              <div class="split-segment-header">
                <div class="split-segment-title-row">
                  <span class="split-segment-title">片段 {{ index + 1 }}</span>
                  <span class="split-segment-badge">{{ index === 0 ? '保留当前 block' : '创建新 block' }}</span>
                  <span class="split-segment-meta">{{ getSplitSegmentCharCount(segment.plain_text) }} 字</span>
                </div>
                <div class="split-segment-actions">
                  <a-button size="small" type="text" :disabled="index === 0" @click="moveSplitSegment(segment.id, -1)">
                    上移
                  </a-button>
                  <a-button
                    size="small"
                    type="text"
                    :disabled="index === splitSegments.length - 1"
                    @click="moveSplitSegment(segment.id, 1)"
                  >
                    下移
                  </a-button>
                  <a-button
                    size="small"
                    type="text"
                    danger
                    :disabled="splitSegments.length <= 2"
                    @click="removeSplitSegment(segment.id)"
                  >
                    删除
                  </a-button>
                </div>
              </div>
              <a-textarea
                v-model:value="segment.plain_text"
                :rows="index === 0 ? 6 : 5"
                placeholder="输入该片段文本"
                class="split-segment-textarea"
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  </IndexTreeModalShell>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import type { DocBlockNode, StructuredSplitSegmentPayload } from '../../../types/knowledge'
import IndexTreeModalShell from './IndexTreeModalShell.vue'
import {
  buildInitialSplitSegments,
  createSplitSegmentDraft,
  getSplitSegmentCharCount,
  type SplitSegmentDraft
} from './indexTreeModalUtils'

interface Props {
  open: boolean
  node: DocBlockNode | null
  darkMode?: boolean
  loading?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  darkMode: false,
  loading: false
})

const emit = defineEmits<{
  'update:open': [value: boolean]
  cancel: []
  submit: [splitSegments: StructuredSplitSegmentPayload[]]
}>()

const splitSegments = ref<SplitSegmentDraft[]>([createSplitSegmentDraft(''), createSplitSegmentDraft('')])

const sourceText = computed(() => String(props.node?.plain_text || '').trim())
const nodeDisplayTitle = computed(() => (
  String(props.node?.plain_text || props.node?.title_path || '').trim().slice(0, 120) || '未命名节点'
))
const nonEmptySplitSegments = computed(() => splitSegments.value.filter(segment => getSplitSegmentCharCount(segment.plain_text) > 0))
const nonEmptySplitSegmentCount = computed(() => nonEmptySplitSegments.value.length)
const splitCharacterCount = computed(() => (
  splitSegments.value.reduce((total, segment) => total + getSplitSegmentCharCount(segment.plain_text), 0)
))
const submitDisabled = computed(() => !props.node || nonEmptySplitSegmentCount.value < 2)

/* 根据原始文本重建默认拆分片段。 */
const resetSplitSegmentsFromSource = () => {
  splitSegments.value = buildInitialSplitSegments(sourceText.value)
}

watch(() => [props.open, props.node?.id, sourceText.value], () => {
  if (props.open) {
    resetSplitSegmentsFromSource()
  }
}, { immediate: true })

/* 在末尾追加一个空白片段。 */
const appendSplitSegment = () => {
  splitSegments.value = [...splitSegments.value, createSplitSegmentDraft('')]
}

/* 删除指定拆分片段。 */
const removeSplitSegment = (segmentId: string) => {
  if (splitSegments.value.length <= 2) return
  splitSegments.value = splitSegments.value.filter(segment => segment.id !== segmentId)
}

/* 调整拆分片段的展示和提交顺序。 */
const moveSplitSegment = (segmentId: string, delta: -1 | 1) => {
  const currentIndex = splitSegments.value.findIndex(segment => segment.id === segmentId)
  if (currentIndex < 0) return
  const targetIndex = currentIndex + delta
  if (targetIndex < 0 || targetIndex >= splitSegments.value.length) return
  const nextSegments = [...splitSegments.value]
  const [moved] = nextSegments.splice(currentIndex, 1)
  nextSegments.splice(targetIndex, 0, moved)
  splitSegments.value = nextSegments
}

/* 整理拆分结果并交给外层批处理逻辑。 */
const submitSplit = () => {
  if (!props.node) return
  const splitSegmentsPayload = nonEmptySplitSegments.value.map(segment => ({
    plain_text: segment.plain_text.trim()
  }))
  if (splitSegmentsPayload.length < 2) {
    message.warning('请至少保留 2 个非空片段')
    return
  }
  emit('submit', splitSegmentsPayload)
}
</script>

<style lang="less">
.split-modal-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--dp-title-strong, #0f172a);
}

.split-dialog-layout {
  display: grid;
  grid-template-columns: minmax(0, 0.95fr) minmax(0, 1.05fr);
  gap: 12px;
}

.split-dialog-main,
.split-dialog-side {
  min-width: 0;
}

.split-dialog-side {
  display: flex;
  flex-direction: column;
}

.split-overview-card,
.split-target-card,
.split-source-card,
.split-editor-card,
.split-segment-card {
  border-radius: 12px;
  border: 1px solid var(--dp-pane-border, #e2e8f0);
  background: color-mix(in srgb, var(--dp-pane-bg, #ffffff) 95%, #f8fafc 5%);
}

.split-overview-card,
.split-target-card,
.split-source-card,
.split-editor-card {
  padding: 10px 12px;
}

.split-overview-card,
.split-target-card,
.split-source-card {
  margin-bottom: 10px;
}

.split-overview-title-row,
.split-target-title-row,
.split-source-title-row,
.split-segment-toolbar,
.split-segment-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.split-overview-title,
.split-target-title,
.split-source-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--dp-title-strong, #0f172a);
}

.split-overview-hint,
.split-segment-summary {
  margin-top: 2px;
  color: var(--dp-sub-text, #64748b);
  font-size: 12px;
  line-height: 1.5;
}

.split-overview-stats,
.split-target-tags,
.split-segment-toolbar-actions,
.split-segment-actions,
.split-segment-title-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.split-overview-stat,
.split-target-tag,
.split-segment-badge,
.split-segment-meta {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  padding: 0 8px;
  border-radius: 999px;
  border: 1px solid rgba(37, 99, 235, 0.16);
  background: color-mix(in srgb, #dbeafe 18%, #ffffff);
  color: #1d4ed8;
  font-size: 12px;
}

.split-target-text {
  margin-top: 8px;
  color: var(--dp-title-text, #0f172a);
  font-size: 13px;
  line-height: 1.6;
  word-break: break-word;
}

.split-source-meta {
  color: var(--dp-sub-text, #64748b);
  font-size: 12px;
}

.split-source-text {
  margin: 8px 0 0;
  padding: 10px;
  border-radius: 10px;
  border: 1px dashed var(--dp-pane-border, #d8dee9);
  background: color-mix(in srgb, var(--dp-content-bg, #ffffff) 96%, #eff6ff 4%);
  color: var(--dp-title-text, #0f172a);
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.split-segment-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 10px;
}

.split-segment-card {
  padding: 10px;
}

.split-segment-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--dp-title-strong, #0f172a);
}

.split-segment-header {
  margin-bottom: 8px;
}

.split-segment-textarea textarea {
  border-radius: 8px;
}

.index-tree-modal-dark .split-modal-title,
.index-tree-modal-dark .split-overview-title,
.index-tree-modal-dark .split-target-title,
.index-tree-modal-dark .split-source-title,
.index-tree-modal-dark .split-target-text,
.index-tree-modal-dark .split-segment-title {
  color: rgba(255, 255, 255, 0.88);
}

.index-tree-modal-dark .split-overview-card,
.index-tree-modal-dark .split-target-card,
.index-tree-modal-dark .split-source-card,
.index-tree-modal-dark .split-editor-card,
.index-tree-modal-dark .split-segment-card {
  border-color: #242c39;
  background: #171d27;
}

.index-tree-modal-dark .split-overview-hint,
.index-tree-modal-dark .split-segment-summary,
.index-tree-modal-dark .split-source-meta {
  color: rgba(255, 255, 255, 0.58);
}

.index-tree-modal-dark .split-overview-stat,
.index-tree-modal-dark .split-target-tag,
.index-tree-modal-dark .split-segment-badge,
.index-tree-modal-dark .split-segment-meta {
  border-color: rgba(96, 165, 250, 0.3);
  background: rgba(37, 99, 235, 0.18);
  color: #93c5fd;
}

.index-tree-modal-dark .split-source-text {
  border-color: #2f3948;
  background: #111722;
  color: rgba(255, 255, 255, 0.76);
}

.index-tree-modal-dark .split-segment-textarea textarea {
  background: #0f141d;
  border-color: #242c39;
  color: rgba(255, 255, 255, 0.82);
}

@media (max-width: 980px) {
  .split-dialog-layout {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .split-overview-title-row,
  .split-target-title-row,
  .split-source-title-row,
  .split-segment-toolbar,
  .split-segment-header {
    flex-direction: column;
  }
}
</style>
