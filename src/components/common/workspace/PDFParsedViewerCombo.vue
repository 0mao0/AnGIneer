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
<a-radio-button value="Preview_KnowledgeGraph" title="知识图谱">
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
          <div v-if="activeTab !== 'Preview_KnowledgeGraph'" class="index-summary-row">
            <div class="summary-left">
              <span class="summary-tag">
                <span class="summary-item total">总{{ indexSummaryStats.total }}</span>
                <span class="summary-divider">|</span>
                <span class="summary-item figure">图{{ indexSummaryStats.figure }}</span>
                <span class="summary-divider">|</span>
                <span class="summary-item table">表{{ indexSummaryStats.table }}</span>
                <span class="summary-divider">|</span>
                <span class="summary-item formula">公式{{ indexSummaryStats.formula }}</span>
              </span>
              <div class="index-search-wrap">
                <a-input
                  v-model:value="indexSearchKeyword"
                  placeholder="搜索解析结果..."
                  size="small"
                  allow-clear
                  class="index-search-input"
                  @press-enter="onSearchNavigate('next')"
                >
                  <template #prefix>
                    <SearchOutlined class="index-search-icon" />
                  </template>
                </a-input>
                <span v-if="searchMatchInfo" class="search-match-info">{{ searchMatchInfo }}</span>
                <template v-if="indexSearchKeyword.trim()">
                  <a-button size="small" class="search-nav-btn" @click="onSearchNavigate('prev')">
                    <UpOutlined />
                  </a-button>
                  <a-button size="small" class="search-nav-btn" @click="onSearchNavigate('next')">
                    <DownOutlined />
                  </a-button>
                </template>
              </div>
            </div>
            <div v-if="activeTab === 'Preview_IndexTree'" class="summary-actions">
              <span v-if="selectedBlockIds.length" class="selected-count">已选 {{ selectedBlockIds.length }} 个</span>
              <a-dropdown
                :disabled="!selectedBlockIds.length || !canBatchRelevel || submittingBatchOperation"
              >
                <a-button size="small">
                  层级调整
                  <DownOutlined />
                </a-button>
                <template #overlay>
                  <a-menu @click="onBatchLevelMenuClick">
                    <a-menu-item key="promote" :disabled="!canBatchPromote">升一级</a-menu-item>
                    <a-menu-item key="demote" :disabled="!canBatchDemote">降一级</a-menu-item>
                    <a-menu-divider />
                    <a-menu-item
                      v-for="level in [1, 2, 3, 4, 5, 6]"
                      :key="`set-level-${level}`"
                    >
                      设为 L{{ level }}
                    </a-menu-item>
                  </a-menu>
                </template>
              </a-dropdown>
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
            :items="filteredIndexItems"
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
          <Preview_KnowledgeGraph
    v-else-if="activeTab === 'Preview_KnowledgeGraph' || activeTab === 'Preview_IndexGraph'"
    ref="knowledgeGraphRef"
    :library-id="props.libraryId"
    :doc-id="props.docId"
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
      :saving="savingNodeEdit"
      @cancel="closeNodeEdit"
      @submit="submitNodeEdit"
    />
    <IndexTreeMergeModal
      v-model:open="mergeModalVisible"
      :selected-block-ids="selectedBlockIds"
      :node-map="nodeMap"
      :loading="submittingBatchOperation"
      @cancel="closeMergeModal"
      @submit="submitMergeOperation"
    />
    <IndexTreeSplitModal
      v-model:open="splitModalVisible"
      :node="splitTargetNode"
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
  DotChartOutlined,
  SearchOutlined,
  UpOutlined,
  DownOutlined
} from '@ant-design/icons-vue'
import { computed, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
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
import Preview_KnowledgeGraph from '../index/Preview_KnowledgeGraph.vue'
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
  contentScrollPercent: number
  activeLinkedItemId: string | null
  activeLineRange: { start: number; end: number } | null
  sourceFilePath?: string
  graphData?: DocBlocksGraphType | null
  libraryId?: string
  docId?: string
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

const indexSearchKeyword = ref('')
const searchCurrentIndex = ref(0)

/** 对搜索关键词做模糊匹配：支持空格分隔的多关键词 */
const searchMatchedIds = computed<string[]>(() => {
  const keyword = indexSearchKeyword.value.trim()
  if (!keyword) return []
  const tokens = keyword.split(/\s+/).filter(Boolean)
  if (!tokens.length) return []
  const lowerTokens = tokens.map(t => t.toLowerCase())
  const matched: string[] = []
  for (const item of flatIndexItems.value) {
    const node = graphNodeLookup.value.get(item.id)
    const texts = [
      item.title || '',
      item.content || '',
      item.item_type || '',
      node?.plain_text || '',
      node?.title_path || '',
      node?.math_content || '',
      node?.caption || '',
      node?.footnote || '',
    ]
    const haystack = texts.join(' ').toLowerCase()
    if (lowerTokens.every(token => haystack.includes(token))) {
      matched.push(item.id)
    }
  }
  return matched
})

const searchMatchInfo = computed<string | null>(() => {
  const keyword = indexSearchKeyword.value.trim()
  if (!keyword) return null
  const total = searchMatchedIds.value.length
  if (total === 0) return '0/0'
  const current = Math.min(searchCurrentIndex.value + 1, total)
  return `${current}/${total}`
})

/** 搜索过滤后的列表项 */
const filteredIndexItems = computed<StructuredIndexItem[]>(() => {
  const keyword = indexSearchKeyword.value.trim()
  if (!keyword) return flatIndexItems.value
  const matchedSet = new Set(searchMatchedIds.value)
  return flatIndexItems.value.filter(item => matchedSet.has(item.id))
})

/** 搜索导航：上/下一条匹配结果 */
const onSearchNavigate = (direction: 'prev' | 'next') => {
  const total = searchMatchedIds.value.length
  if (total === 0) return
  if (direction === 'next') {
    searchCurrentIndex.value = (searchCurrentIndex.value + 1) % total
  } else {
    searchCurrentIndex.value = (searchCurrentIndex.value - 1 + total) % total
  }
  const targetId = searchMatchedIds.value[searchCurrentIndex.value]
  if (!targetId) return
  handleViewerNodeSelect(targetId)
  expandAncestors(targetId)
}

watch(indexSearchKeyword, () => {
  searchCurrentIndex.value = 0
})

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

/* 处理顶部工具栏中的批量层级动作菜单。 */
const onBatchLevelMenuClick = async ({ key }: { key: string }) => {
  if (key === 'promote') {
    await submitBatchRelevel(-1)
    return
  }
  if (key === 'demote') {
    await submitBatchRelevel(1)
    return
  }
  if (key.startsWith('set-level-')) {
    const targetLevel = Number(key.replace('set-level-', ''))
    if (Number.isFinite(targetLevel) && targetLevel > 0) {
      await submitBatchSetLevel(targetLevel)
    }
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

.summary-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.index-search-wrap {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.index-search-input {
  width: 180px;
  font-size: 12px;

  :deep(.ant-input) {
    font-size: 12px;
    padding-left: 6px;
  }

  :deep(.ant-input-suffix) {
    font-size: 12px;
  }

  :deep(.ant-input-prefix) {
    margin-inline-end: 4px;
  }
}

.index-search-icon {
  font-size: 12px;
  color: var(--dp-sub-text);
}

.search-match-info {
  font-size: 11px;
  color: var(--dp-sub-text);
  white-space: nowrap;
  min-width: 32px;
  text-align: center;
}

.search-nav-btn {
  padding: 0 4px;
  height: 22px;
  width: 22px;
  min-width: 22px;
  font-size: 10px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.summary-tag {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  font-size: 12px;
  color: var(--dp-sub-text);
  background: var(--dp-pane-bg);
  padding: 4px 10px;
  border-radius: 6px;
  border: 1px solid var(--dp-pane-border);
}

.summary-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.selected-count {
  font-size: 12px;
  color: var(--dp-sub-text);
}

.summary-item {
  font-weight: 500;

  &.total {
    color: var(--dp-title-strong);
  }

  &.figure {
    color: var(--dp-type-figure-color, #7c3aed);
  }

  &.table {
    color: var(--dp-type-table-color, #0891b2);
  }

  &.formula {
    color: var(--dp-type-formula-color, #2563eb);
  }
}

.summary-divider {
  color: var(--dp-pane-border);
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
