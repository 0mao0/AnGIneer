<template>
  <div class="doc-preview" :class="{ 'dark-mode': darkMode }">
    <div class="preview-content">
      <div class="workspace-toolbar">
        <div class="workspace-toolbar-left">
          <span class="workspace-title">文档解析工作区</span>
        </div>
        <div class="workspace-toolbar-actions">
          <a-button
            v-if="showHighlightToggle"
            size="small"
            class="workspace-action-btn"
            :type="highlightLinkEnabled ? 'primary' : 'default'"
            @click="toggleHighlightLink"
          >
            高亮联动
          </a-button>
          <a-button
            type="primary"
            size="small"
            class="workspace-action-btn"
            :loading="node.status === 'processing'"
            @click="$emit('parse', node)"
          >
            {{ parseButtonText }}
          </a-button>
        </div>
      </div>
      <div class="split-preview">
        <PDF_Viewer
          :node="node"
          :progressPercent="progressPercent"
          :stageText="stageText"
          :isPdf="isPdf"
          :isOffice="isOffice"
          :isImage="isImage"
          :isText="isText"
          :pdfViewerUrl="pdfViewerUrl"
          :officePreviewUrl="officePreviewUrl"
          :fileUrl="fileUrl"
          :textContent="textContent"
          :currentPdfPage="pdfPage"
          :pdfPageCount="inferredPdfPageCount"
          :highlights="linkedHighlights"
          :activeHighlightId="activeLeftHighlightId"
          :highlightLinkEnabled="highlightLinkEnabled"
          :textScrollPercent="leftScrollPercent"
          @download="downloadFile"
          @text-scroll="onLeftTextScrollPercent"
          @hover-highlight="onHoverLinkedItem"
          @select-highlight="onSelectHighlightFromLeft"
        />

        <ParsedPDF_Viewer
          v-model:activeTab="activeTab"
          :renderedMarkdown="renderedMarkdown"
          :editableContent="editableContent"
          :isContentDirty="isContentDirty"
          :strategyValue="strategyValue"
          :ingestStatusValue="ingestStatusValue"
          :canIngest="canIngest"
          :ingestButtonText="ingestButtonText"
          :structuredItems="structuredItemsValue"
          :indexSummaryStats="indexSummaryStats"
          :hasParsedContent="hasParsedContent"
          :contentScrollPercent="rightScrollPercent"
          :activeLinkedItemId="activeLinkedItemId"
          :activeLineRange="activeLinkedLineRange"
          :graphData="props.graphData"
          @update:editableContent="editableContent = $event"
          @save-markdown="saveMarkdown"
          @cancel-markdown="cancelMarkdownEdit"
          @strategy-change="onStrategyChange"
          @trigger-ingest="triggerIngest"
          @content-scroll="onRightPaneScrollPercent"
          @hover-item="onHoverLinkedItem"
          @select-item="onSelectItemFromRight"
          @select-line="onSelectLineFromRight"
        />
      </div>
    </div>

    <a-modal
      v-model:open="ingestModalVisible"
      :title="ingestStatusValue === 'processing' ? '入库中' : '入库结果'"
      :footer="null"
      :mask-closable="ingestStatusValue !== 'processing'"
      :closable="ingestStatusValue !== 'processing'"
    >
      <div class="ingest-modal-content">
        <a-progress
          :percent="ingestProgressPercent"
          :status="ingestProgressStatus"
          size="default"
        />
        <div class="ingest-stage">{{ ingestStageText }}</div>
        <div v-if="ingestStatusValue === 'completed'" class="ingest-result">
          总条目 {{ structuredTotal }}
        </div>
        <div v-if="ingestStatusValue === 'completed'" class="ingest-result-actions">
          <a-button size="small" @click="openIndexFromIngestModal">查看索引</a-button>
        </div>
      </div>
    </a-modal>

  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import PDF_Viewer from './PDF_Viewer.vue'
import ParsedPDF_Viewer from './ParsedPDF_Viewer.vue'
import { useWorkspaceLinkage } from '../../composables/useWorkspaceLinkage'
import { useWorkspacePreview } from '../../composables/useWorkspacePreview'
import { useWorkspaceIngest } from '../../composables/useWorkspaceIngest'
import type { PreviewMode } from '../../composables/useParsedPdfViewer'
import type { KnowledgeTreeNode } from '../../types/tree'
import type {
  IngestStatus,
  KnowledgeStrategy,
  StructuredIndexItem,
  StructuredStats,
  DocumentParsedWorkspaceEventMap
} from '../../types/knowledge'
import { mapParseStageText, renderMarkdownToHtml } from '../../utils/knowledge'

interface Props {
  node: KnowledgeTreeNode
  content: string
  structuredItems?: StructuredIndexItem[]
  structuredStats?: StructuredStats
  ingestStatus?: IngestStatus
  ingestProgress?: number
  ingestStage?: string
  darkMode?: boolean
  graphData?: { nodes: any[]; edges: any[] } | null
}

const props = withDefaults(defineProps<Props>(), {
  darkMode: false
})

const emit = defineEmits<DocumentParsedWorkspaceEventMap>()

const filePath = computed(() => props.node.filePath || props.node.file_path || '')
const ingestStatusValue = computed(() => props.ingestStatus || 'idle')
const ingestProgressPercent = computed(() => Number(props.ingestProgress || 0))
const activeTab = ref<PreviewMode>('Preview_HTML')
const stageText = computed(() => mapParseStageText(props.node.parseStage, props.node.parseError))
const parseButtonText = computed(() => {
  if (props.node.status === 'completed') return '重新解析'
  if (props.node.status === 'failed') return '重新解析'
  if (props.node.status === 'processing') return '解析中...'
  return '开始解析'
})
const structuredItemsValue = computed(() => props.structuredItems || [])
const editableContent = ref('')
const savedContent = ref('')
const isContentDirty = computed(() => editableContent.value !== savedContent.value)

const {
  progressPercent,
  isPdf,
  isOffice,
  isImage,
  isText,
  fileUrl,
  pdfViewerUrl,
  officePreviewUrl,
  textContent,
  inferredPdfPageCount,
  pdfPage,
  leftScrollPercent,
  rightScrollPercent,
  onRightPaneScrollPercent,
  onLeftTextScrollPercent,
  downloadFile,
  resetPreviewState
} = useWorkspacePreview({
  node: computed(() => props.node),
  filePath,
  graphData: computed(() => props.graphData || null)
})

const {
  ingestModalVisible,
  ingestProgressStatus,
  ingestStageText,
  strategyValue,
  structuredTotal,
  hasParsedContent,
  indexSummaryStats,
  ingestButtonText,
  canIngest,
  onStrategyChange: setStrategy,
  triggerIngest: requestIngest,
  closeIngestModal
} = useWorkspaceIngest({
  node: computed(() => props.node),
  content: computed(() => props.content || ''),
  isContentDirty,
  ingestStatus: ingestStatusValue,
  ingestStage: computed(() => props.ingestStage || ''),
  structuredStats: computed(() => props.structuredStats)
})

const saveMarkdown = () => {
  if (!isContentDirty.value) {
    return
  }
  emit('save-content', editableContent.value)
  savedContent.value = editableContent.value
}

const cancelMarkdownEdit = () => {
  editableContent.value = savedContent.value
}

const triggerIngest = () => {
  if (!requestIngest()) return
  emit('rebuild-structured', strategyValue.value)
}

const onStrategyChange = (value: KnowledgeStrategy) => {
  setStrategy(value)
  emit('change-strategy', value)
}

const openIndexFromIngestModal = () => {
  activeTab.value = 'Preview_IndexList'
  closeIngestModal()
}
const markdownContent = computed(() => editableContent.value || props.content || '')
const {
  linkedHighlights,
  activeLinkedItemId,
  highlightLinkEnabled,
  showHighlightToggle,
  activeLeftHighlightId,
  activeLinkedLineRange,
  onHoverLinkedItem,
  onSelectHighlightFromLeft,
  onSelectItemFromRight,
  onSelectLineFromRight,
  toggleHighlightLink,
  resetLinkageState
} = useWorkspaceLinkage({
  graphData: computed(() => props.graphData || null),
  structuredItems: structuredItemsValue,
  markdownContent,
  isPdf,
  pdfPage,
  rightScrollPercent
})

watch(() => props.content, (value) => {
  editableContent.value = value || ''
  savedContent.value = value || ''
}, { immediate: true })

watch(() => props.node.key, () => {
  activeTab.value = 'Preview_HTML'
  resetPreviewState()
  resetLinkageState()
})

const renderedMarkdown = computed(() => renderMarkdownToHtml(
  markdownContent.value,
  filePath.value
))
</script>

<style lang="less" scoped>
.doc-preview {
  --dp-bg: var(--docs-bg, #f3f5f8);
  --dp-pane-bg: var(--docs-pane-bg, #fff);
  --dp-pane-border: var(--docs-pane-border, #e8edf4);
  --dp-title-bg: var(--docs-title-bg, #fff);
  --dp-title-border: var(--docs-title-border, #edf1f7);
  --dp-title-text: var(--docs-text, #595959);
  --dp-title-strong: var(--docs-text-strong, #4f5d7a);
  --dp-sub-text: var(--docs-text-subtle, #8c8c8c);
  --dp-progress-bg: var(--docs-progress-bg, #f7f9fc);
  --dp-content-bg: var(--docs-content-bg, #fff);
  --dp-code-bg: var(--docs-code-bg, #f6f8fa);
  --dp-inline-code-bg: var(--docs-inline-code-bg, rgba(0, 0, 0, 0.04));
  --dp-scroll-track: transparent;
  --dp-scroll-thumb: rgba(15, 23, 42, 0.22);
  --dp-index-card-bg: var(--docs-index-card-bg, #fafcff);
  --dp-empty-overlay: var(--docs-empty-overlay, rgba(255, 255, 255, 0.92));
  --dp-empty-text: var(--docs-empty-text, rgba(0, 0, 0, 0.45));
  --dp-segment-bg: var(--docs-segment-bg, #dfe5f2);
  --dp-segment-border: var(--docs-segment-border, #cdd6e7);
  --dp-segment-selected-bg: var(--docs-segment-selected-bg, #fff);
  --dp-segment-selected-text: var(--docs-segment-selected-text, #1f2937);
  --dp-segment-shared-bg: var(--docs-segment-shared-bg, linear-gradient(90deg, #52c41a 0%, #389e0d 100%));
  --dp-segment-shared-border: var(--docs-segment-shared-border, #389e0d);
  --dp-math-bg: var(--docs-math-bg, #eef3ff);
  --dp-math-color: var(--docs-math-color, #1d3a8a);
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--dp-bg);

  .preview-content {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-height: 0;
    overflow: hidden;
    padding: 6px;
  }

  .workspace-toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 6px 8px;
    border: 1px solid var(--dp-pane-border);
    border-radius: 8px;
    background: var(--dp-pane-bg);
    margin-bottom: 8px;
  }

  .workspace-toolbar-left {
    min-width: 0;
    display: flex;
    align-items: center;
  }

  .workspace-title {
    color: var(--dp-title-strong);
    font-size: 13px;
    font-weight: 600;
    white-space: nowrap;
  }

  .workspace-toolbar-actions {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 8px;
    flex-wrap: wrap;
  }

  .workspace-action-btn {
    height: 28px;
    border-radius: 6px;
    font-size: 12px;
    padding-inline: 10px;
  }

  .split-preview {
    display: flex;
    flex: 1;
    min-height: 0;
    gap: 8px;
  }

  .ingest-modal-content {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding-top: 6px;
  }

  .ingest-stage {
    font-size: 13px;
    color: #595959;
  }

  .ingest-result {
    font-size: 14px;
    color: #1677ff;
    font-weight: 600;
  }

  .ingest-result-actions {
    display: flex;
    gap: 8px;
  }

  &.dark-mode {
    --dp-bg: #101319;
    --dp-pane-bg: #171b24;
    --dp-pane-border: #2a3140;
    --dp-title-bg: #171b24;
    --dp-title-border: #2a3140;
    --dp-title-text: rgba(255, 255, 255, 0.78);
    --dp-title-strong: rgba(255, 255, 255, 0.92);
    --dp-sub-text: rgba(255, 255, 255, 0.62);
    --dp-progress-bg: #171b24;
    --dp-content-bg: #171b24;
    --dp-code-bg: #1d2330;
    --dp-inline-code-bg: rgba(255, 255, 255, 0.12);
    --dp-scroll-thumb: rgba(148, 163, 184, 0.42);
    --dp-index-card-bg: #1d2330;
    --dp-empty-overlay: rgba(16, 19, 25, 0.92);
    --dp-empty-text: rgba(255, 255, 255, 0.6);
    --dp-segment-bg: #2a3345;
    --dp-segment-border: #38445b;
    --dp-segment-selected-bg: #3a4660;
    --dp-segment-selected-text: rgba(255, 255, 255, 0.9);
    --dp-segment-shared-bg: linear-gradient(90deg, #49aa19 0%, #237804 100%);
    --dp-segment-shared-border: #237804;
    --dp-math-bg: rgba(59, 130, 246, 0.18);
    --dp-math-color: rgba(219, 234, 254, 0.95);
    background: var(--dp-bg);
  }
}
</style>
