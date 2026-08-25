<template>
  <div class="doc-preview" :class="{ 'dark-mode': dark, 'light-mode': !dark }">
    <div class="preview-content">
      <div class="split-preview">
        <PDF_Viewer
          ref="pdfViewerRef"
          :theme="dark ? 'dark' : 'light'"
          :node="node"
          :isPdf="isPdf"
          :isOffice="isOffice"
          :isImage="isImage"
          :isText="isText"
          :pdfViewerUrl="pdfViewerUrl"
          :fileUrl="fileUrl"
          :textContent="textContent"
          :currentPdfPage="pdfPage"
          :pdfPageCount="inferredPdfPageCount"
          :highlights="linkedHighlights"
          :activeHighlightId="activeLeftHighlightId"
          :active-highlight-ids="activeLinkedHighlightIds"
          :activeClickItemId="pdfClickActiveItemId"
          :searchText="markdownContent"
          :pageLabels="printedPageLabels"
          :textScrollPercent="leftScrollPercent"
          :show-side-panel-toggle="showSidePanelToggle"
          :side-panel-open="sidePanelOpen"
          :side-panel-width="sidePanelWidth"
          :pdf-asset-base-url="pdfAssetBaseUrl"
          @download="downloadFile"
          @text-scroll="onLeftTextScrollPercent"
          @pdf-active-page="onPdfPageChanged"
          @hover-highlight="onHoverLinkedItem"
          @select-highlight="onSelectPdfHighlight"
          @search-jump="onSearchJump"
          @update:side-panel-open="sidePanelOpen = $event"
        >
          <template #side-panel>
            <PDFParsedViewerCombo
              v-model:activeTab="activeTab"
              :markdownContent="markdownContent"
              :structuredItems="structuredItemsValue"
              :indexSummaryStats="indexSummaryStats"
              :hasParsedContent="hasParsedContent"
              :contentScrollPercent="rightScrollPercent"
              :activeLinkedItemId="activeLinkedItemId"
              :activeLineRange="activeLinkedLineRange"
              :sourceFilePath="filePath"
              :graphData="props.graphData"
              :libraryId="props.libraryId || 'default'"
              :docId="props.node.key"
              :onUpdateStructuredNode="props.onUpdateStructuredNode"
              :onBatchStructuredOperation="props.onBatchStructuredOperation"
              :onUndoLastOperation="props.onUndoLastOperation"
              :onLoadGraphSnapshot="props.onLoadGraphSnapshot"
              :onBuildGraph="props.onBuildGraph"
              :dark="dark"
              :show-furniture="showFurniture"
              @update:show-furniture="showFurniture = $event"
              @content-scroll="onRightPaneScrollPercent"
              @select-item="onSelectItemFromRight"
              @select-line="onSelectLineFromRight"
            />
          </template>
        </PDF_Viewer>
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
import { extractPrintedPageLabel } from '../../../utils/knowledge'
import { buildPrintedPageLabels } from '../../../utils/pdfSearch'

interface Props {
  node: KnowledgeTreeNode
  content: string
  structuredItems?: StructuredIndexItem[]
  structuredStats?: StructuredStats
  graphData?: { nodes: any[]; edges: any[] } | null
  graphDataFullLoaded?: boolean
  renderPdfPath?: string  // LO 生成的 PDF 底图路径（对非 PDF 输入）
  fileUrlResolver?: (path: string) => string
  libraryId?: string
  onUpdateStructuredNode?: (payload: StructuredNodeUpdatePayload) => Promise<void>
  onBatchStructuredOperation?: (payload: StructuredBatchOperationPayload) => Promise<void>
  onUndoLastOperation?: () => Promise<void>
  onLoadFullGraphData?: () => Promise<void>
  onLoadGraphSnapshot?: (params: {
    libraryId?: string
    docId?: string
    viewMode?: 'doc' | 'global'
  }) => Promise<{ stats: any; entities: any[]; relations: any[] }>
  onBuildGraph?: (
    params: { libraryId?: string; docId?: string },
    enableLlm: boolean
  ) => Promise<{
    packets_processed: number
    total_entities_found: number
    total_relations_added: number
    snapshot: { stats: any; entities: any[]; relations: any[] }
  }>
  dark?: boolean
  sidePanelOpen?: boolean
  sidePanelDefaultOpen?: boolean
  sidePanelWidth?: number
  pdfAssetBaseUrl?: string
  defaultParsedTab?: PreviewMode
}

const props = withDefaults(defineProps<Props>(), {
  sidePanelOpen: undefined,
  graphDataFullLoaded: false,
  dark: false,
  sidePanelDefaultOpen: false,
  sidePanelWidth: 400
})

const emit = defineEmits<PDFParsedWorkspaceEventMap>()

const internalSidePanelOpen = ref(props.sidePanelDefaultOpen)
const sidePanelOpen = computed({
  get: () => props.sidePanelOpen ?? internalSidePanelOpen.value,
  set: (value: boolean) => {
    internalSidePanelOpen.value = value
    emit('update:sidePanelOpen', value)
  }
})

/* 计算解析面板的默认展示 tab。 */
const getDefaultParsedTab = (): PreviewMode => {
  if (props.defaultParsedTab) return props.defaultParsedTab
  return props.graphData?.nodes?.length ? 'Preview_IndexTree' : 'Preview_Markdown'
}

const filePath = computed(() => props.node.filePath || props.node.file_path || '')
const activeTab = ref<PreviewMode>(getDefaultParsedTab())
const showFurniture = ref(localStorage.getItem('docs-ui.show-furniture') === '1')
const parseButtonText = computed(() => {
  if (props.node.status === 'completed') return '重新解析'
  if (props.node.status === 'failed') return '重新解析'
  if (props.node.status === 'cancelled') return '重新解析'
  if (props.node.status === 'partial') return '重新解析'
  if (props.node.status === 'processing') return '解析中...'
  return '开始解析'
})
const structuredItemsValue = computed(() => props.structuredItems || [])
const hasParsedContent = computed(() => Boolean((props.content || '').trim()))
const showSidePanelToggle = computed(() => (
  hasParsedContent.value || Boolean(props.graphData?.nodes?.length)
))
const indexSummaryStats = computed(() => {
  const strategyStats = props.structuredStats?.strategies?.doc_blocks_graph_v1 || {}
  const toCount = (value: unknown) => Number(value || 0)
  const paragraph = toCount(strategyStats.paragraph)
  const title = toCount(strategyStats.title)
  const table = toCount(strategyStats.table)
  const formula = toCount(strategyStats.formula)
  const figure = toCount(strategyStats.figure) + toCount(strategyStats.image)
  const headerFooter = toCount(strategyStats.header_footer)
  const total = Object.values(strategyStats).reduce((sum, count) => sum + Number(count || 0), 0)
  const other = Math.max(0, total - paragraph - title - table - formula - figure - headerFooter)
  let maxLevel = 0
  for (const node of props.graphData?.nodes || []) {
    const level = Number(node.derived_level)
    if (Number.isFinite(level) && level > maxLevel) {
      maxLevel = level
    }
  }
  return {
    total,
    paragraph,
    title,
    table,
    formula,
    figure,
    headerFooter,
    other,
    maxLevel,
  }
})

const {
  isPdf,
  isOffice,
  isImage,
  isText,
  fileUrl,
  pdfViewerUrl,
  textContent,
  inferredPdfPageCount,
  pdfPage,
  leftScrollPercent,
  rightScrollPercent,
  onRightPaneScrollPercent,
  onLeftTextScrollPercent,
  onPdfPageChanged,
  downloadFile,
  resetPreviewState
} = useWorkspacePreview({
  node: computed(() => props.node),
  filePath,
  graphData: computed(() => props.graphData || null),
  activeTab: computed(() => activeTab.value),
  renderPdfPath: computed(() => props.renderPdfPath),
  fileUrlResolver: props.fileUrlResolver
})

const markdownContent = computed(() => props.content || '')
const printedPageLabels = computed(() => buildPrintedPageLabels(
  props.graphData?.nodes || [],
  extractPrintedPageLabel,
))
const {
  linkedHighlights,
  activeLinkedItemId,
  activeLinkedHighlightIds,
  activeLeftHighlightId,
  pdfClickActiveItemId,
  activeLinkedLineRange,
  onHoverLinkedItem,
  onSelectHighlightFromLeft,
  onSelectItemFromRight: onSelectItemFromRightLinked,
  onSelectLineFromRight,
    setActiveLinkedItem: setWorkspaceLinkedItem,
  resetLinkageState
} = useWorkspaceLinkage({
  graphData: computed(() => props.graphData || null),
  structuredItems: structuredItemsValue,
  markdownContent,
  activeTab: computed(() => activeTab.value),
  isPdf,
  pdfPage,
  rightScrollPercent,
  showFurniture: computed(() => showFurniture.value),
  onPdfHighlightResolved: (target) => pdfViewerRef.value?.scrollToHighlight(target, 'center'),
})

const pdfViewerRef = ref<InstanceType<typeof PDF_Viewer> | null>(null)
/* 右侧树点击：跳页并把命中 bbox 纵向居中（含同页页饰） */
const onSelectItemFromRight = (itemId: string) => {
  onSelectItemFromRightLinked(itemId, (target) => {
    pdfPage.value = target.page
    pdfViewerRef.value?.scrollToHighlight(target, 'center')
  })
}
const onSelectPdfHighlight = (item: Parameters<typeof onSelectHighlightFromLeft>[0]) => {
  onSelectHighlightFromLeft(item, (highlight) => pdfViewerRef.value?.scrollToHighlight(highlight, 'center'))
}

watch(() => props.content, (value) => {
  void value
}, { immediate: true })

watch(showFurniture, (value) => {
  localStorage.setItem('docs-ui.show-furniture', value ? '1' : '0')
})

watch(() => props.node.key, () => {
  internalSidePanelOpen.value = props.sidePanelDefaultOpen
  activeTab.value = getDefaultParsedTab()
  resetPreviewState()
  resetLinkageState()
})

watch(() => props.graphData?.nodes?.length || 0, (count, previousCount) => {
  if (count > 0 && previousCount === 0 && activeTab.value === 'Preview_Markdown') {
    activeTab.value = 'Preview_IndexTree'
  }
})

watch(
  [isPdf, () => props.graphData?.nodes?.length || 0, () => props.graphDataFullLoaded],
  ([pdfMode, _graphNodeCount, fullLoaded]) => {
    if (!pdfMode || fullLoaded || !props.onLoadFullGraphData) return
    props.onLoadFullGraphData()
  },
  { immediate: true }
)

watch(activeTab, (tab) => {
  if ((tab === 'Preview_IndexTree' || tab === 'Preview_IndexGraph' || tab === 'Preview_KnowledgeGraph') && !props.graphDataFullLoaded && props.onLoadFullGraphData) {
    props.onLoadFullGraphData()
  }
})

// 搜索跳转后，右侧面板同步滚动到命中行
const onSearchJump = (_page: number, lineNumber: number) => {
  const totalLines = Math.max(1, markdownContent.value.split('\n').length)
  const ratio = Math.max(0, Math.min(1, (lineNumber - 1) / totalLines))
  rightScrollPercent.value = ratio
}

/**
 * 对外暴露联动定位入口，并允许调用方指定“最后一个高亮框”策略。
 */
const setActiveLinkedItem = (
  itemId: string | null,
  options: { preferredPage?: number | null; preferLastHighlight?: boolean; groupHighlight?: boolean } = {}
) => {
  setWorkspaceLinkedItem(itemId, options)
  if (itemId && props.graphData?.nodes?.length) {
    activeTab.value = 'Preview_IndexTree'
  }
}

defineExpose({
  setActiveLinkedItem,
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
  --dp-progress-bg: var(--docs-progress-bg, #fcfdff);
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

  .split-preview :deep(.pdf-viewer-side-panel .split-pane) {
    border: none;
    border-radius: 0;
  }

  .ingest-modal-content {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding-top: 6px;
  }

  .ingest-stage {
    font-size: 13px;
    color: var(--text-secondary);
  }

  .ingest-result {
    font-size: 14px;
    color: var(--primary-color);
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
