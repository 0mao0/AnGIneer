<template>
  <div class="split-pane split-pane-right">
    <div class="pane-title b2-pane-title">
      <div ref="headerTitleRowRef" class="b2-title-row">
        <div class="b2-title-main">
          <span class="pane-title-prefix pane-title-prefix-right">解析</span>
        </div>
        <div class="pane-actions-right">
          <a-radio-group
            :value="activeTab"
            size="small"
            class="b2-tab-buttons"
            option-type="button"
            button-style="solid"
            @change="onTabChange"
          >
            <a-radio-button value="Preview_HTML" title="HTML">
              <FileTextOutlined />
            </a-radio-button>
            <a-radio-button value="Preview_Markdown" title="Markdown">
              <EditOutlined />
            </a-radio-button>
            <a-radio-button value="Preview_IndexList" title="列表">
              <UnorderedListOutlined />
            </a-radio-button>
            <a-radio-button value="Preview_IndexTree" :disabled="!hasGraphData" title="树形">
              <BranchesOutlined />
            </a-radio-button>
            <a-radio-button value="Preview_IndexGraph" :disabled="!hasGraphData" title="图形">
              <DotChartOutlined />
            </a-radio-button>
          </a-radio-group>
        </div>
      </div>
    </div>

    <div ref="rightPaneRef" class="b2-content" @scroll.passive="onRightPaneScroll">
      <Preview_HTML
        v-if="activeTab === 'Preview_HTML'"
        :rendered-markdown="renderedMarkdown"
        :active-line-range="activeLineRange"
        @select-line="emit('select-line', $event)"
      />
      <Preview_Markdown
        v-else-if="activeTab === 'Preview_Markdown'"
        :content="markdownContent"
        :active-line-range="activeLineRange"
        @select-line="emit('select-line', $event)"
      />
      <div v-else class="index-layout">
        <div class="index-toolbar">
          <div class="index-summary-row">
            <span class="summary-tag">
              <span class="summary-item total">总{{ indexSummaryStats.total }}</span>
              <span class="summary-divider">|</span>
              <span class="summary-item figure">图{{ indexSummaryStats.figure }}</span>
              <span class="summary-divider">|</span>
              <span class="summary-item table">表{{ indexSummaryStats.table }}</span>
              <span class="summary-divider">|</span>
              <span class="summary-item formula">公式{{ indexSummaryStats.formula }}</span>
            </span>
            <div v-if="activeTab === 'Preview_IndexTree'" class="summary-actions">
              <span v-if="selectedBlockIds.length" class="selected-count">已选 {{ selectedBlockIds.length }} 个</span>
              <a-select
                v-model:value="batchTargetLevel"
                size="small"
                class="batch-level-select"
                :disabled="!selectedBlockIds.length || submittingBatchOperation"
                :options="batchLevelOptions"
                placeholder="设为 Lx"
                @change="submitBatchSetLevel"
              />
              <a-button
                size="small"
                :disabled="!canBatchPromote"
                @click="submitBatchRelevel(-1)"
              >
                升一级
              </a-button>
              <a-button
                size="small"
                :disabled="!canBatchDemote"
                @click="submitBatchRelevel(1)"
              >
                降一级
              </a-button>
              <a-button size="small" :disabled="selectedBlockIds.length < 2" @click="openMergeModal">
                合并
              </a-button>
              <a-button size="small" :disabled="splitTargetBlockIds.length !== 1" @click="openSplitModal">
                拆分
              </a-button>
              <a-button
                size="small"
                :loading="undoingLastOperation"
                :disabled="undoingLastOperation || submittingBatchOperation || !props.onUndoLastOperation"
                @click="submitUndoLastOperation"
              >
                {{ undoingLastOperation ? '撤回中' : '撤回' }}
              </a-button>
              <a-button
                size="small"
                :disabled="!selectedBlockIds.length"
                @click="resetSelectedBlocks"
              >
                清空
              </a-button>
            </div>
          </div>
        </div>
        <div class="index-body">
          <Preview_IndexList
            v-if="activeTab === 'Preview_IndexList'"
            ref="indexContentScrollRef"
            :items="flatIndexItems"
            :current-page="indexCurrentPage"
            :page-size="indexPageSize"
            :active-linked-item-id="activeLinkedItemId"
            :node-map="graphNodeLookup"
            :source-file-path="sourceFilePath"
            @hover-item="emit('hover-item', $event)"
            @select-item="emit('select-item', $event)"
            @page-change="onIndexPageChange"
          />
          <Preview_IndexTree
            v-else-if="activeTab === 'Preview_IndexTree'"
            :loading="!hasGraphData"
            :node-map="nodeMap"
            :children-map="childrenMap"
            :roots="roots"
            :expanded-node-ids="expandedNodeIds"
            :active-node-id="activeNodeIdForGraphTree"
            :selected-node-ids="selectedNodeIdSet"
            :source-file-path="sourceFilePath"
            @toggle="onTreeToggle"
            @select="onNodeSelect"
            @edit="openNodeEdit"
            @toggle-check="toggleNodeSelection"
            @context-action="handleTreeContextAction"
          />
          <Preview_IndexGraph
            v-else
            :loading="!hasGraphData"
            :node-map="nodeMap"
            :children-map="childrenMap"
            :roots="roots"
            :expanded-node-ids="expandedGraphNodeIds"
            :active-node-id="activeNodeIdForGraphTree"
            :viewport-state="graphViewportState"
            :source-file-path="sourceFilePath"
            @toggle="onGraphToggle"
            @select="onNodeSelect"
            @update-viewport="onViewportUpdate"
          />
        </div>
      </div>
      <a-empty
        v-if="!hasParsedContent && !isIndexMode"
        class="b2-empty"
      >
        <template #description>
          <div class="b2-empty-desc">请先解析文档<br>解析完成后将显示结果</div>
        </template>
      </a-empty>
    </div>
    <IndexTreeEditModal
      v-model:open="editModalVisible"
      :node="editingNode"
      :node-map="nodeMap"
      :dark-mode="resolvedDarkMode"
      :saving="savingNodeEdit"
      @cancel="closeNodeEdit"
      @submit="submitNodeEdit"
    />
    <IndexTreeMergeModal
      v-model:open="mergeModalVisible"
      :selected-block-ids="selectedBlockIds"
      :node-map="nodeMap"
      :dark-mode="resolvedDarkMode"
      :loading="submittingBatchOperation"
      @cancel="closeMergeModal"
      @submit="submitMergeOperation"
    />
    <IndexTreeSplitModal
      v-model:open="splitModalVisible"
      :node="splitTargetNode"
      :dark-mode="resolvedDarkMode"
      :loading="submittingBatchOperation"
      @cancel="closeSplitModal"
      @submit="submitSplitOperation"
    />
  </div>
</template>

<script setup lang="ts">
/**
 * 文档解析视图空间组件
 * 提供 HTML、Markdown、列表、树形、图形多种视图切换
 */
import {
  FileTextOutlined,
  EditOutlined,
  UnorderedListOutlined,
  BranchesOutlined,
  DotChartOutlined
} from '@ant-design/icons-vue'
import { computed, ref } from 'vue'
import { message } from 'ant-design-vue'
import { useTheme } from '@angineer/ui-kit'
import type {
  StructuredIndexItem,
  StructuredNodeUpdatePayload,
  StructuredBatchOperationPayload,
  StructuredSplitSegmentPayload,
  DocBlocksGraph as DocBlocksGraphType,
  DocBlockNode
} from '../../../types/knowledge'
import {
  useParsedPdfViewer,
  type PreviewMode,
  type ParsedPdfViewerBridgeEventMap
} from '../../../composables/useParsedPdfViewer'
import Preview_HTML from '../viewers/Preview_HTML.vue'
import Preview_Markdown from '../viewers/Preview_Markdown.vue'
import Preview_IndexList from '../index/Preview_IndexList.vue'
import Preview_IndexTree from '../index/Preview_IndexTree.vue'
import Preview_IndexGraph from '../index/Preview_IndexGraph.vue'
import IndexTreeEditModal from '../index/IndexTreeEditModal.vue'
import IndexTreeMergeModal from '../index/IndexTreeMergeModal.vue'
import IndexTreeSplitModal from '../index/IndexTreeSplitModal.vue'

const props = defineProps<{
  activeTab: PreviewMode
  renderedMarkdown: string
  markdownContent: string
  structuredItems: StructuredIndexItem[]
  indexSummaryStats: {
    total: number
    formula: number
    table: number
    figure: number
  }
  hasParsedContent: boolean
  darkMode?: boolean
  contentScrollPercent: number
  activeLinkedItemId: string | null
  activeLineRange: { start: number; end: number } | null
  sourceFilePath?: string
  graphData?: DocBlocksGraphType | null
  onUpdateStructuredNode?: (payload: StructuredNodeUpdatePayload) => Promise<void>
  onBatchStructuredOperation?: (payload: StructuredBatchOperationPayload) => Promise<void>
  onUndoLastOperation?: () => Promise<void>
}>()

type ParsedPdfViewerComponentEventMap = ParsedPdfViewerBridgeEventMap & {
  'hover-item': [id: string | null]
  'select-line': [line: number]
}

const emit = defineEmits<ParsedPdfViewerComponentEventMap>()
const editModalVisible = ref(false)
const savingNodeEdit = ref(false)
const editingNodeId = ref<string | null>(null)
const mergeModalVisible = ref(false)
const splitModalVisible = ref(false)
const submittingBatchOperation = ref(false)
const undoingLastOperation = ref(false)
const selectedBlockIds = ref<string[]>([])
const batchTargetLevel = ref<number | undefined>(undefined)

const {
  rightPaneRef,
  indexContentScrollRef,
  headerTitleRowRef,
  isIndexMode,
  hasGraphData,
  graphNodeLookup,
  flatIndexItems,
  indexCurrentPage,
  indexPageSize,
  nodeMap,
  childrenMap,
  roots,
  expandedNodeIds,
  expandedGraphNodeIds,
  graphViewportState,
  activeNodeIdForGraphTree,
  onRightPaneScroll,
  onTabChange,
  onIndexPageChange,
  onTreeToggle,
  onGraphToggle,
  onNodeSelect: handleViewerNodeSelect,
  onViewportUpdate,
  expandAncestors,
  setViewMode
} = useParsedPdfViewer(props, emit)

const editingNode = computed<DocBlockNode | null>(() => {
  if (!editingNodeId.value) return null
  return nodeMap.value.get(editingNodeId.value) || null
})
const selectedNodeIdSet = computed(() => new Set(selectedBlockIds.value))
const selectedNodes = computed(() => (
  selectedBlockIds.value
    .map(nodeId => nodeMap.value.get(nodeId) || null)
    .filter((node): node is DocBlockNode => Boolean(node))
))
const selectedHeadingNodes = computed(() => (
  selectedNodes.value.filter(node => typeof node.derived_level === 'number' && node.derived_level > 0)
))
const canBatchRelevel = computed(() => (
  selectedBlockIds.value.length > 0
  && selectedHeadingNodes.value.length === selectedNodes.value.length
))
const canBatchPromote = computed(() => (
  canBatchRelevel.value
  && selectedHeadingNodes.value.every(node => Number(node.derived_level || 0) > 1)
))
const canBatchDemote = computed(() => canBatchRelevel.value)
const batchLevelOptions = computed(() => Array.from({ length: 6 }, (_, index) => ({
  value: index + 1,
  label: `L${index + 1}`
})))
const splitTargetBlockIds = computed(() => {
  if (selectedBlockIds.value.length === 1) {
    return [...selectedBlockIds.value]
  }
  if (selectedBlockIds.value.length === 0 && activeNodeIdForGraphTree.value) {
    return [activeNodeIdForGraphTree.value]
  }
  return []
})
const splitTargetNode = computed<DocBlockNode | null>(() => {
  const nodeId = splitTargetBlockIds.value[0]
  return nodeId ? (nodeMap.value.get(nodeId) || null) : null
})
const { isDark } = useTheme()
const resolvedDarkMode = computed(() => props.darkMode || isDark.value)

/* 打开节点纠错弹窗并回填当前值。 */
const openNodeEdit = (nodeId: string) => {
  const node = nodeMap.value.get(nodeId)
  if (!node) return
  editingNodeId.value = nodeId
  editModalVisible.value = true
}

/* 关闭节点纠错弹窗并重置局部状态。 */
const closeNodeEdit = () => {
  editModalVisible.value = false
  editingNodeId.value = null
  savingNodeEdit.value = false
}

/* 清空树中通过勾选产生的多选状态。 */
const resetSelectedBlocks = () => {
  selectedBlockIds.value = []
  batchTargetLevel.value = undefined
}

/* 解析树节点右键动作所作用的节点集合。 */
const resolveContextTargetBlockIds = (nodeId: string): string[] => {
  const normalizedId = String(nodeId || '').trim()
  if (!normalizedId) return []
  if (selectedBlockIds.value.length > 1 && selectedBlockIds.value.includes(normalizedId)) {
    return [...selectedBlockIds.value]
  }
  return [normalizedId]
}

/* 在结构树中切换 block 的勾选状态，用于批量合并。 */
const toggleNodeSelection = (nodeId: string) => {
  const nextSelected = new Set(selectedBlockIds.value)
  if (nextSelected.has(nodeId)) {
    nextSelected.delete(nodeId)
  } else {
    nextSelected.add(nodeId)
  }
  selectedBlockIds.value = Array.from(nextSelected)
}

/* 转发节点激活事件，并让“单点选中即可拆分”成立。 */
const onNodeSelect = (nodeId: string) => {
  handleViewerNodeSelect(nodeId)
}

/* 打开批量合并弹窗。 */
const openMergeModal = () => {
  if (selectedBlockIds.value.length < 2) return
  mergeModalVisible.value = true
}

/* 关闭批量合并弹窗。 */
const closeMergeModal = () => {
  mergeModalVisible.value = false
  submittingBatchOperation.value = false
}

/* 打开拆分弹窗，默认支持“单点选中即可拆分”。 */
const openSplitModal = () => {
  if (splitTargetBlockIds.value.length !== 1) return
  splitModalVisible.value = true
}

/* 关闭拆分弹窗。 */
const closeSplitModal = () => {
  splitModalVisible.value = false
  submittingBatchOperation.value = false
}

/* 撤回当前文档最近一次结构操作。 */
const submitUndoLastOperation = async () => {
  if (!props.onUndoLastOperation) return
  try {
    undoingLastOperation.value = true
    await props.onUndoLastOperation()
  } finally {
    undoingLastOperation.value = false
  }
}

/* 提交节点纠错结果并刷新外层数据。 */
const submitNodeEdit = async (payload: StructuredNodeUpdatePayload) => {
  if (!props.onUpdateStructuredNode) {
    closeNodeEdit()
    return
  }
  try {
    savingNodeEdit.value = true
    await props.onUpdateStructuredNode(payload)
    closeNodeEdit()
  } catch (error) {
    savingNodeEdit.value = false
  }
}

/* 提交合并请求并同步清理树中的多选状态。 */
const submitMergeOperation = async (targetBlockId: string) => {
  if (!props.onBatchStructuredOperation) {
    closeMergeModal()
    return
  }
  try {
    submittingBatchOperation.value = true
    await props.onBatchStructuredOperation({
      operation: 'merge',
      blockIds: selectedBlockIds.value,
      targetBlockId
    })
    resetSelectedBlocks()
    closeMergeModal()
  } catch (error) {
    submittingBatchOperation.value = false
    const detail = error instanceof Error ? error.message : '批量结构操作失败'
    message.error(detail)
  }
}

/* 按批次统一升降选中标题节点的层级。 */
const submitBatchRelevel = async (levelDelta: number) => {
  if (!props.onBatchStructuredOperation) return
  if (!selectedBlockIds.value.length) return
  if (!canBatchRelevel.value) {
    message.warning('批量升降级仅支持已识别为标题的节点')
    return
  }
  if (levelDelta < 0 && !canBatchPromote.value) {
    message.warning('选中项中包含 L1，不能继续升一级')
    return
  }
  try {
    submittingBatchOperation.value = true
    await props.onBatchStructuredOperation({
      operation: 'relevel',
      blockIds: selectedBlockIds.value,
      levelDelta
    })
    resetSelectedBlocks()
  } catch (error) {
    submittingBatchOperation.value = false
    const detail = error instanceof Error ? error.message : '批量层级调整失败'
    message.error(detail)
  } finally {
    submittingBatchOperation.value = false
  }
}

/* 按批次把选中节点直接设置为指定层级。 */
const submitBatchSetLevel = async (targetLevel: number) => {
  if (!props.onBatchStructuredOperation) return
  if (!selectedBlockIds.value.length) return
  try {
    submittingBatchOperation.value = true
    await props.onBatchStructuredOperation({
      operation: 'relevel',
      blockIds: selectedBlockIds.value,
      targetLevel
    })
    resetSelectedBlocks()
  } catch (error) {
    submittingBatchOperation.value = false
    const detail = error instanceof Error ? error.message : '批量层级设置失败'
    message.error(detail)
  } finally {
    submittingBatchOperation.value = false
  }
}

/* 处理树节点右键菜单的快捷层级操作。 */
const handleTreeContextAction = async (payload: { nodeId: string; action: 'promote' | 'demote' | 'set-level'; targetLevel?: number }) => {
  const targetBlockIds = resolveContextTargetBlockIds(payload.nodeId)
  if (!targetBlockIds.length || !props.onBatchStructuredOperation) return
  const previousSelectedIds = [...selectedBlockIds.value]
  selectedBlockIds.value = targetBlockIds
  try {
    if (payload.action === 'set-level' && typeof payload.targetLevel === 'number') {
      await submitBatchSetLevel(payload.targetLevel)
      return
    }
    if (payload.action === 'promote') {
      await submitBatchRelevel(-1)
      return
    }
    if (payload.action === 'demote') {
      await submitBatchRelevel(1)
    }
  } finally {
    if (selectedBlockIds.value.length === 0) {
      selectedBlockIds.value = previousSelectedIds.filter(nodeId => nodeMap.value.has(nodeId))
    }
  }
}

/* 提交拆分请求并保持“单点选中即可拆分”的工作流。 */
const submitSplitOperation = async (splitSegments: StructuredSplitSegmentPayload[]) => {
  if (!props.onBatchStructuredOperation) {
    closeSplitModal()
    return
  }
  try {
    submittingBatchOperation.value = true
    await props.onBatchStructuredOperation({
      operation: 'split',
      blockIds: splitTargetBlockIds.value,
      splitSegments
    })
    resetSelectedBlocks()
    closeSplitModal()
  } catch (error) {
    submittingBatchOperation.value = false
    const detail = error instanceof Error ? error.message : '批量结构操作失败'
    message.error(detail)
  }
}

// 模板引用占位，防止 Linter 报错
void [rightPaneRef, indexContentScrollRef, headerTitleRowRef]

defineExpose({
  expandAncestors,
  setViewMode: (mode: PreviewMode) => {
    setViewMode(mode)
  }
})
</script>

<style lang="less" scoped>
.split-pane {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
  border: 1px solid var(--dp-pane-border);
  border-radius: 8px;
  background: var(--dp-pane-bg);
  overflow: hidden;
}

.pane-title {
  font-size: 13px;
  color: var(--dp-title-text);
  padding: 0 12px;
  border-bottom: 1px solid var(--dp-title-border);
  background: var(--dp-title-bg);
  height: 40px;
  min-height: 40px;
  box-sizing: border-box;
  display: flex;
  align-items: center;
}

.pane-title-prefix {
  font-size: 13px;
  font-weight: 500;
  color: var(--dp-title-strong);
}

.b2-pane-title {
  padding: 0 8px;
}

.b2-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  height: 100%;
  width: 100%;
  flex-wrap: nowrap;
}

.b2-title-main {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  flex: 1;
  flex-wrap: nowrap;
}

.pane-actions-right {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 4px;
  margin-left: auto;
}

.floating-controls {
  position: absolute;
  top: 8px;
  right: 8px;
  z-index: 10;
  display: flex;
  flex-direction: column;
  gap: 8px;
  pointer-events: none;
}

.floating-group {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px;
  background: var(--dp-pane-bg);
  border: 1px solid var(--dp-pane-border);
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
  pointer-events: auto;
}

.action-btn {
  height: 24px;
  border-radius: 4px;
  font-size: 12px;
  padding-inline: 8px;
}

.b2-tab-buttons {
  flex: 0 0 auto;
}

.b2-tab-buttons :deep(.ant-radio-button-wrapper) {
  height: 24px;
  line-height: 22px;
  padding-inline: 8px;
  font-size: 12px;
}

.tab-label {
  margin-left: 4px;
}

.b2-content {
  position: relative;
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  overflow-y: overlay;
  background: var(--dp-content-bg);
}

.b2-content > :not(.floating-controls):not(.b2-empty) {
  flex: 1;
  min-height: 100%;
}

.index-layout {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 100%;
  padding: 10px;
  box-sizing: border-box;
  overflow: hidden;
}

.index-toolbar {
  flex-shrink: 0;
}

.index-body {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.index-body > * {
  height: 100%;
}

.index-summary-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}

.summary-tag {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  font-size: 12px;
  color: var(--dp-sub-text, #64748b);
  background: var(--dp-pane-bg, #f8fafc);
  padding: 4px 10px;
  border-radius: 6px;
  border: 1px solid var(--dp-pane-border, #e2e8f0);
}

.summary-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.batch-level-select {
  min-width: 96px;
}

.selected-count {
  font-size: 12px;
  color: var(--dp-sub-text, #64748b);
}

.summary-item {
  font-weight: 500;

  &.total {
    color: var(--dp-title-strong, #0f172a);
  }

  &.figure {
    color: #7c3aed;
  }

  &.table {
    color: #0891b2;
  }

  &.formula {
    color: #2563eb;
  }
}

.summary-divider {
  color: var(--dp-pane-border, #cbd5e1);
  margin: 0 2px;
}

.b2-empty {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
  background: var(--dp-empty-overlay);
}

.b2-empty-desc {
  line-height: 1.6;
  color: var(--dp-empty-text);
  text-align: center;
}
</style>
