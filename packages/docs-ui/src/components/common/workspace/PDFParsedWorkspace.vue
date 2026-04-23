<template>
  <div class="doc-preview" :class="{ 'dark-mode': props.darkMode }">
    <div class="preview-content">
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

        <PDFParsedViewerCombo
          v-model:activeTab="activeTab"
          :renderedMarkdown="renderedMarkdown"
          :markdownContent="markdownContent"
          :structuredItems="structuredItemsValue"
          :indexSummaryStats="indexSummaryStats"
          :hasParsedContent="hasParsedContent"
          :dark-mode="props.darkMode"
          :contentScrollPercent="rightScrollPercent"
          :activeLinkedItemId="activeLinkedItemId"
          :activeLineRange="activeLinkedLineRange"
          :sourceFilePath="filePath"
          :graphData="props.graphData"
          :onUpdateStructuredNode="props.onUpdateStructuredNode"
          :onBatchStructuredOperation="props.onBatchStructuredOperation"
          :onUndoLastOperation="props.onUndoLastOperation"
          @content-scroll="onRightPaneScrollPercent"
          @hover-item="onHoverLinkedItem"
          @select-item="onSelectItemFromRight"
          @select-line="onSelectLineFromRight"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import PDF_Viewer from '../viewers/PDF_Viewer.vue'
import PDFParsedViewerCombo from './PDFParsedViewerCombo.vue'
import { useWorkspaceLinkage } from '../../../composables/useWorkspaceLinkage'
import { useWorkspacePreview } from '../../../composables/useWorkspacePreview'
import type { PreviewMode } from '../../../composables/useParsedPdfViewer'
import type { KnowledgeTreeNode } from '../../../types/tree'
import type {
  StructuredIndexItem,
  StructuredNodeUpdatePayload,
  StructuredBatchOperationPayload,
  StructuredStats,
  PDFParsedWorkspaceEventMap
} from '../../../types/knowledge'
import { mapParseStageText, renderMarkdownToHtml } from '../../../utils/knowledge'

interface Props {
  node: KnowledgeTreeNode
  content: string
  structuredItems?: StructuredIndexItem[]
  structuredStats?: StructuredStats
  darkMode?: boolean
  graphData?: { nodes: any[]; edges: any[] } | null
  onUpdateStructuredNode?: (payload: StructuredNodeUpdatePayload) => Promise<void>
  onBatchStructuredOperation?: (payload: StructuredBatchOperationPayload) => Promise<void>
  onUndoLastOperation?: () => Promise<void>
}

const props = withDefaults(defineProps<Props>(), {
  darkMode: false
})

defineEmits<PDFParsedWorkspaceEventMap>()
/* 计算解析面板的默认展示 tab。 */
const getDefaultParsedTab = (): PreviewMode => (
  props.graphData?.nodes?.length ? 'Preview_IndexTree' : 'Preview_IndexList'
)

const filePath = computed(() => props.node.filePath || props.node.file_path || '')
const activeTab = ref<PreviewMode>(getDefaultParsedTab())
const stageText = computed(() => mapParseStageText(props.node.parseStage, props.node.parseError))
const parseButtonText = computed(() => {
  if (props.node.status === 'completed') return '重新解析'
  if (props.node.status === 'failed') return '重新解析'
  if (props.node.status === 'processing') return '解析中...'
  return '开始解析'
})
const structuredItemsValue = computed(() => props.structuredItems || [])
const hasParsedContent = computed(() => Boolean((props.content || '').trim()))
const indexSummaryStats = computed(() => {
  const strategyStats = props.structuredStats?.strategies?.doc_blocks_graph_v1 || {}
  const toCount = (value: unknown) => Number(value || 0)
  return {
    total: Object.values(strategyStats).reduce((sum, count) => sum + Number(count || 0), 0),
    formula: toCount(strategyStats.formula),
    table: toCount(strategyStats.table),
    figure: toCount(strategyStats.image) + toCount(strategyStats.figure)
  }
})

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
  graphData: computed(() => props.graphData || null),
  activeTab: computed(() => activeTab.value)
})

const markdownContent = computed(() => props.content || '')
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
    setActiveLinkedItem: setWorkspaceLinkedItem,
  toggleHighlightLink,
  resetLinkageState
} = useWorkspaceLinkage({
  graphData: computed(() => props.graphData || null),
  structuredItems: structuredItemsValue,
  markdownContent,
  activeTab: computed(() => activeTab.value),
  isPdf,
  pdfPage,
  rightScrollPercent
})

watch(() => props.content, (value) => {
  void value
}, { immediate: true })

watch(() => props.node.key, () => {
  activeTab.value = getDefaultParsedTab()
  resetPreviewState()
  resetLinkageState()
})

watch(() => props.graphData?.nodes?.length || 0, (count, previousCount) => {
  if (count > 0 && previousCount === 0 && activeTab.value === 'Preview_IndexList') {
    activeTab.value = 'Preview_IndexTree'
  }
})

const renderedMarkdown = computed(() => renderMarkdownToHtml(
  markdownContent.value,
  filePath.value
))

/**
 * 对外暴露联动定位入口，并允许调用方指定“最后一个高亮框”策略。
 */
const setActiveLinkedItem = (
  itemId: string | null,
  options: { preferredPage?: number | null; preferLastHighlight?: boolean } = {}
) => {
  setWorkspaceLinkedItem(itemId, options)
  if (itemId && props.graphData?.nodes?.length) {
    activeTab.value = 'Preview_IndexTree'
  }
}

defineExpose({
  setActiveLinkedItem,
  toggleHighlightLink,
  highlightLinkEnabled,
  showHighlightToggle,
  parseButtonText
})
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
    height: 100%;
    min-height: 0;
    overflow: hidden;
    padding: 6px;
  }

  .split-preview {
    display: flex;
    flex: 1;
    height: 100%;
    min-height: 0;
    gap: 8px;
    margin-top: 8px;
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
