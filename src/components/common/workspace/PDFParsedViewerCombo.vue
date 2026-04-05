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
              <a-button size="small" :disabled="selectedBlockIds.length < 2" @click="openBatchModal('merge')">
                合并
              </a-button>
              <a-button size="small" :disabled="splitTargetBlockIds.length !== 1" @click="openBatchModal('split')">
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
          />
          <Preview_IndexGraph
            v-else
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
        v-if="!hasParsedContent"
        class="b2-empty"
      >
        <template #description>
          <div class="b2-empty-desc">请先解析文档<br>解析完成后将显示结果</div>
        </template>
      </a-empty>
    </div>
    <a-modal
      v-model:open="editModalVisible"
      title="修改节点内容"
      :confirm-loading="savingNodeEdit"
      width="760px"
      :wrap-class-name="structuredModalWrapClass"
      @ok="submitNodeEdit"
      @cancel="closeNodeEdit"
    >
      <template v-if="editingNode">
        <div class="edit-node-meta">
          <a-tag color="blue">{{ editingNode.block_type || 'segment' }}</a-tag>
          <a-tag>页 {{ Number(editingNode.page_idx || 0) + 1 }}</a-tag>
          <a-tag>块 {{ editingNode.block_seq || 0 }}</a-tag>
          <span class="edit-node-id">{{ editingNode.block_uid || editingNode.id }}</span>
        </div>
        <div class="edit-dialog-layout">
          <div class="edit-dialog-main">
            <div class="edit-surface-card">
              <div class="edit-section-title">内容编辑</div>
              <a-form layout="vertical" class="edit-form">
                <a-form-item v-if="showPlainTextEditor" label="识别文本">
                  <a-textarea v-model:value="editForm.plain_text" :rows="6" />
                </a-form-item>
                <a-form-item v-if="showMathEditor" label="公式源码">
                  <a-textarea v-model:value="editForm.math_content" :rows="4" />
                </a-form-item>
                <a-form-item v-if="showTableEditor" label="表格 HTML">
                  <a-textarea v-model:value="editForm.table_html" :rows="10" />
                </a-form-item>
                <a-form-item v-if="showCaptionEditor" label="题注">
                  <a-textarea v-model:value="editForm.caption" :rows="3" />
                </a-form-item>
                <a-form-item v-if="showFootnoteEditor" label="注释">
                  <a-textarea v-model:value="editForm.footnote" :rows="3" />
                </a-form-item>
              </a-form>
            </div>
          </div>
          <div class="edit-dialog-side">
            <div class="edit-surface-card">
              <div class="edit-section-title">结构设置</div>
              <a-form layout="vertical" class="edit-form">
                <a-form-item label="父级节点">
                  <a-select
                    v-model:value="editForm.parent_block_uid"
                    :options="parentNodeOptions"
                    allow-clear
                    show-search
                    option-filter-prop="label"
                    placeholder="选择新的父级节点"
                  />
                  <div class="edit-field-hint">可把当前 block 调整到新的标题层级之下，或改成根节点。</div>
                </a-form-item>
                <a-form-item label="标题层次">
                  <a-select
                    v-model:value="editForm.derived_title_level"
                    :options="headingLevelOptions"
                    allow-clear
                    placeholder="留空表示非标题节点"
                  />
                </a-form-item>
                <a-form-item label="合并到目标 block">
                  <a-select
                    v-model:value="editForm.merge_into_block_uid"
                    :options="mergeTargetOptions"
                    allow-clear
                    show-search
                    option-filter-prop="label"
                    placeholder="不合并，仅更新当前 block"
                  />
                  <div class="edit-field-hint">选择后会把当前 block 的内容并入目标 block，并从结构树中移除当前 block。</div>
                </a-form-item>
              </a-form>
            </div>
            <div class="edit-surface-card edit-side-summary-card">
              <div class="edit-section-title">当前状态</div>
              <div class="edit-side-summary">
                <div class="edit-side-summary-item">
                  <span class="edit-side-summary-label">当前页</span>
                  <span class="edit-side-summary-value">第 {{ Number(editingNode.page_idx || 0) + 1 }} 页</span>
                </div>
                <div class="edit-side-summary-item">
                  <span class="edit-side-summary-label">父节点</span>
                  <span class="edit-side-summary-value">{{ currentParentLabel }}</span>
                </div>
                <div class="edit-side-summary-item">
                  <span class="edit-side-summary-label">层级</span>
                  <span class="edit-side-summary-value">{{ currentHeadingLevelLabel }}</span>
                </div>
                <div class="edit-side-summary-item">
                  <span class="edit-side-summary-label">目标 block</span>
                  <span class="edit-side-summary-value">{{ currentMergeTargetLabel }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </template>
    </a-modal>
    <a-modal
      v-model:open="batchModalVisible"
      :title="batchModalTitle"
      :confirm-loading="submittingBatchOperation"
      :ok-button-props="batchModalOkButtonProps"
      :width="batchModalWidth"
      :wrap-class-name="structuredModalWrapClass"
      @ok="submitBatchOperation"
      @cancel="closeBatchModal"
    >
      <a-form layout="vertical">
        <a-form-item label="已选 block" :class="{ 'split-selection-form-item': batchOperation === 'split' }">
          <a-select
            mode="multiple"
            :value="batchSelectionIds"
            :options="batchSelectedNodeOptions"
            disabled
          />
        </a-form-item>
        <a-form-item v-if="batchOperation === 'merge'" label="合并目标">
          <a-select
            v-model:value="batchForm.targetBlockId"
            :options="selectedNodeOptions"
            show-search
            option-filter-prop="label"
            placeholder="选择保留的目标 block"
          />
          <div class="edit-field-hint">其余选中 block 会按当前文档顺序并入目标 block。</div>
        </a-form-item>
        <div v-if="batchOperation === 'split'" class="split-dialog-layout">
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
            <div class="split-source-card">
              <div class="split-source-title-row">
                <div class="split-source-title">原始文本</div>
                <span class="split-source-meta">{{ splitSourceText.length }} 字</span>
              </div>
              <pre class="split-source-text">{{ splitSourceText }}</pre>
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
                <div v-for="(segment, index) in batchForm.splitSegments" :key="segment.id" class="split-segment-card">
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
                        :disabled="index === batchForm.splitSegments.length - 1"
                        @click="moveSplitSegment(segment.id, 1)"
                      >
                        下移
                      </a-button>
                      <a-button
                        size="small"
                        type="text"
                        danger
                        :disabled="batchForm.splitSegments.length <= 2"
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
              <div class="edit-field-hint">提交后会自动定位到第一个新增片段，便于继续检查与微调。</div>
            </div>
          </div>
        </div>
      </a-form>
    </a-modal>
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
import type {
  StructuredIndexItem,
  StructuredNodeUpdatePayload,
  StructuredBatchOperationPayload,
  StructuredBatchOperationType,
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
const ROOT_PARENT_VALUE = '__root__'
const editModalVisible = ref(false)
const savingNodeEdit = ref(false)
const editingNodeId = ref<string | null>(null)
const batchModalVisible = ref(false)
const submittingBatchOperation = ref(false)
const undoingLastOperation = ref(false)
const batchOperation = ref<StructuredBatchOperationType>('merge')
const selectedBlockIds = ref<string[]>([])
type SplitSegmentDraft = {
  id: string
  plain_text: string
}
const editForm = ref({
  plain_text: '',
  math_content: '',
  table_html: '',
  caption: '',
  footnote: '',
  parent_block_uid: ROOT_PARENT_VALUE,
  derived_title_level: null as number | null,
  merge_into_block_uid: undefined as string | undefined
})
const batchForm = ref({
  targetBlockId: undefined as string | undefined,
  splitSegments: [] as SplitSegmentDraft[]
})

const {
  rightPaneRef,
  indexContentScrollRef,
  headerTitleRowRef,
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

const showPlainTextEditor = computed(() => Boolean(editingNode.value))
const showMathEditor = computed(() => {
  const blockType = String(editingNode.value?.block_type || '').toLowerCase()
  return ['formula', 'equation', 'math'].includes(blockType) || Boolean(editingNode.value?.math_content)
})
const showTableEditor = computed(() => {
  const blockType = String(editingNode.value?.block_type || '').toLowerCase()
  return blockType === 'table' || Boolean(editingNode.value?.table_html)
})
const showCaptionEditor = computed(() => {
  const blockType = String(editingNode.value?.block_type || '').toLowerCase()
  return ['table', 'image', 'figure'].includes(blockType) || Boolean(editingNode.value?.caption)
})
const showFootnoteEditor = computed(() => {
  const blockType = String(editingNode.value?.block_type || '').toLowerCase()
  return ['table', 'image', 'figure'].includes(blockType) || Boolean(editingNode.value?.footnote)
})
const orderedNodeOptions = computed(() => (
  [...nodeMap.value.values()]
    .sort((a, b) => {
      if ((a.page_idx || 0) !== (b.page_idx || 0)) return (a.page_idx || 0) - (b.page_idx || 0)
      return (a.block_seq || 0) - (b.block_seq || 0)
    })
    .map(node => ({
      value: node.block_uid || node.id,
      label: `P${Number(node.page_idx || 0) + 1} · B${node.block_seq || 0} · ${(node.plain_text || node.title_path || node.block_type || '未命名').slice(0, 80)}`
    }))
))
const parentNodeOptions = computed(() => {
  const currentId = editingNode.value?.block_uid || editingNode.value?.id || ''
  return [
    { value: ROOT_PARENT_VALUE, label: '设为根节点' },
    ...orderedNodeOptions.value.filter(option => option.value !== currentId)
  ]
})
const mergeTargetOptions = computed(() => {
  const currentId = editingNode.value?.block_uid || editingNode.value?.id || ''
  return orderedNodeOptions.value.filter(option => option.value !== currentId)
})
const headingLevelOptions = computed(() => Array.from({ length: 6 }, (_, index) => ({
  value: index + 1,
  label: `H${index + 1} / ${index + 1} 级标题`
})))
const selectedNodeIdSet = computed(() => new Set(selectedBlockIds.value))
const selectedNodeOptions = computed(() => (
  orderedNodeOptions.value.filter(option => selectedNodeIdSet.value.has(String(option.value || '')))
))
const splitTargetBlockIds = computed(() => {
  if (selectedBlockIds.value.length === 1) {
    return [...selectedBlockIds.value]
  }
  if (selectedBlockIds.value.length === 0 && activeNodeIdForGraphTree.value) {
    return [activeNodeIdForGraphTree.value]
  }
  return []
})
const batchSelectionIds = computed(() => (
  batchOperation.value === 'split' ? splitTargetBlockIds.value : selectedBlockIds.value
))
const batchSelectedNodeOptions = computed(() => {
  const batchSelectionIdSet = new Set(batchSelectionIds.value)
  return orderedNodeOptions.value.filter(option => batchSelectionIdSet.has(String(option.value || '')))
})
const structuredModalWrapClass = computed(() => (
  props.darkMode ? 'doc-structured-modal doc-structured-modal-dark' : 'doc-structured-modal'
))
const batchModalTitle = computed(() => {
  if (batchOperation.value === 'merge') return '批量合并 block'
  if (batchOperation.value === 'delete') return '删除 block'
  return '拆分 block'
})
const currentParentLabel = computed(() => {
  const currentParentId = editForm.value.parent_block_uid
  if (!currentParentId || currentParentId === ROOT_PARENT_VALUE) return '根节点'
  return parentNodeOptions.value.find(option => option.value === currentParentId)?.label || currentParentId
})
const currentHeadingLevelLabel = computed(() => {
  const level = editForm.value.derived_title_level
  if (typeof level !== 'number') return '非标题'
  return headingLevelOptions.value.find(option => option.value === level)?.label || `${level} 级标题`
})
const currentMergeTargetLabel = computed(() => {
  const mergeTargetId = editForm.value.merge_into_block_uid
  if (!mergeTargetId) return '不合并'
  return mergeTargetOptions.value.find(option => option.value === mergeTargetId)?.label || mergeTargetId
})
const nonEmptySplitSegmentCount = computed(() => (
  batchForm.value.splitSegments.filter(segment => segment.plain_text.trim()).length
))
const splitCharacterCount = computed(() => (
  batchForm.value.splitSegments.reduce((total, segment) => total + getSplitSegmentCharCount(segment.plain_text), 0)
))
const batchModalOkButtonProps = computed(() => (
  batchOperation.value === 'split'
    ? { disabled: nonEmptySplitSegmentCount.value < 2 }
    : undefined
))
const batchModalWidth = computed(() => (
  batchOperation.value === 'split' ? 1040 : 760
))
const splitSourceText = computed(() => {
  const selectedNode = nodeMap.value.get(splitTargetBlockIds.value[0] || '')
  return String(selectedNode?.plain_text || '').trim()
})

/* 统计拆分片段的有效字数，帮助用户快速判断切分结果。 */
const getSplitSegmentCharCount = (text: string): number => text.trim().length

/* 创建拆分弹窗中的片段草稿对象。 */
const createSplitSegmentDraft = (plain_text = ''): SplitSegmentDraft => ({
  id: `${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
  plain_text
})

/* 尝试按句号、问号等边界初始化拆分片段。 */
const splitTextBySentenceBoundary = (text: string): string[] => {
  const normalized = text.trim()
  if (!normalized) return []
  const fragments = normalized
    .split(/(?<=[。！？!?；;])/)
    .map(fragment => fragment.trim())
    .filter(Boolean)
  if (fragments.length >= 2) return fragments
  if (normalized.length < 2) return [normalized]
  const midpoint = Math.max(1, Math.floor(normalized.length / 2))
  return [normalized.slice(0, midpoint).trim(), normalized.slice(midpoint).trim()].filter(Boolean)
}

/* 根据原文内容初始化拆分片段列表。 */
const buildInitialSplitSegments = (text: string): SplitSegmentDraft[] => {
  const normalized = text.trim()
  if (!normalized) {
    return [createSplitSegmentDraft(''), createSplitSegmentDraft('')]
  }
  const paragraphParts = normalized
    .split(/\r?\n\s*\r?\n/g)
    .map(part => part.trim())
    .filter(Boolean)
  const lineParts = normalized
    .split(/\r?\n/g)
    .map(part => part.trim())
    .filter(Boolean)
  const rawParts = paragraphParts.length >= 2
    ? paragraphParts
    : (lineParts.length >= 2 ? lineParts : splitTextBySentenceBoundary(normalized))
  const ensuredParts = rawParts.length >= 2 ? rawParts : [normalized, '']
  return ensuredParts.map(part => createSplitSegmentDraft(part))
}

/* 打开节点纠错弹窗并回填当前值。 */
const openNodeEdit = (nodeId: string) => {
  const node = nodeMap.value.get(nodeId)
  if (!node) return
  editingNodeId.value = nodeId
  editForm.value = {
    plain_text: String(node.plain_text || ''),
    math_content: String(node.math_content || ''),
    table_html: String(node.table_html || ''),
    caption: String(node.caption || ''),
    footnote: String(node.footnote || ''),
    parent_block_uid: node.parent_uid || ROOT_PARENT_VALUE,
    derived_title_level: typeof node.derived_level === 'number' ? node.derived_level : null,
    merge_into_block_uid: undefined
  }
  editModalVisible.value = true
}

/* 关闭节点纠错弹窗并重置局部状态。 */
const closeNodeEdit = () => {
  editModalVisible.value = false
  editingNodeId.value = null
  savingNodeEdit.value = false
}

const resetBatchForm = () => {
  batchForm.value = {
    targetBlockId: batchSelectionIds.value[0],
    splitSegments: []
  }
}

/* 清空树中通过勾选产生的多选状态。 */
const resetSelectedBlocks = () => {
  selectedBlockIds.value = []
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

const openBatchModal = (operation: StructuredBatchOperationType) => {
  if (operation === 'merge' && selectedBlockIds.value.length < 2) return
  if (operation === 'split' && splitTargetBlockIds.value.length !== 1) return
  batchOperation.value = operation
  resetBatchForm()
  if (operation === 'split') {
    batchForm.value.splitSegments = buildInitialSplitSegments(splitSourceText.value)
  }
  batchModalVisible.value = true
}

const closeBatchModal = () => {
  batchModalVisible.value = false
  submittingBatchOperation.value = false
}

const resetSplitSegmentsFromSource = () => {
  batchForm.value.splitSegments = buildInitialSplitSegments(splitSourceText.value)
}

/* 向拆分列表末尾追加一个空片段。 */
const appendSplitSegment = () => {
  batchForm.value.splitSegments.push(createSplitSegmentDraft(''))
}

/* 删除指定的拆分片段，至少保留两个片段以维持可拆分状态。 */
const removeSplitSegment = (segmentId: string) => {
  if (batchForm.value.splitSegments.length <= 2) return
  batchForm.value.splitSegments = batchForm.value.splitSegments.filter(segment => segment.id !== segmentId)
}

/* 调整拆分片段顺序，第一段仍表示保留在当前 block 的内容。 */
const moveSplitSegment = (segmentId: string, offset: -1 | 1) => {
  const currentIndex = batchForm.value.splitSegments.findIndex(segment => segment.id === segmentId)
  if (currentIndex < 0) return
  const nextIndex = currentIndex + offset
  if (nextIndex < 0 || nextIndex >= batchForm.value.splitSegments.length) return
  const nextSegments = [...batchForm.value.splitSegments]
  const [targetSegment] = nextSegments.splice(currentIndex, 1)
  nextSegments.splice(nextIndex, 0, targetSegment)
  batchForm.value.splitSegments = nextSegments
}

const buildBatchPayload = (): StructuredBatchOperationPayload => {
  if (batchOperation.value === 'merge') {
    if (!batchForm.value.targetBlockId) {
      throw new Error('请选择合并目标')
    }
    return {
      operation: 'merge',
      blockIds: selectedBlockIds.value,
      targetBlockId: batchForm.value.targetBlockId
    }
  }
  if (batchOperation.value === 'split') {
    const splitSegments = batchForm.value.splitSegments
      .map(segment => ({ plain_text: segment.plain_text.trim() }))
      .filter(segment => segment.plain_text)
    if (splitSegments.length < 2) {
      throw new Error('拆分内容至少需要两个非空片段')
    }
    return {
      operation: 'split',
      blockIds: splitTargetBlockIds.value,
      splitSegments
    }
  }
  throw new Error('不支持的批量操作')
}

const submitBatchOperation = async () => {
  if (!props.onBatchStructuredOperation) {
    closeBatchModal()
    return
  }
  try {
    const payload = buildBatchPayload()
    submittingBatchOperation.value = true
    await props.onBatchStructuredOperation(payload)
    resetSelectedBlocks()
    closeBatchModal()
  } catch (error) {
    submittingBatchOperation.value = false
    const detail = error instanceof Error ? error.message : '批量结构操作失败'
    message.error(detail)
  }
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

/* 仅提取发生变化的节点字段作为更新载荷。 */
const buildNodeEditPayload = (node: DocBlockNode): StructuredNodeUpdatePayload | null => {
  const payload: StructuredNodeUpdatePayload = {
    blockId: node.block_uid || node.id
  }
  if (editForm.value.plain_text !== String(node.plain_text || '')) {
    payload.plain_text = editForm.value.plain_text
  }
  if (editForm.value.math_content !== String(node.math_content || '')) {
    payload.math_content = editForm.value.math_content
  }
  if (editForm.value.table_html !== String(node.table_html || '')) {
    payload.table_html = editForm.value.table_html
  }
  if (editForm.value.caption !== String(node.caption || '')) {
    payload.caption = editForm.value.caption
  }
  if (editForm.value.footnote !== String(node.footnote || '')) {
    payload.footnote = editForm.value.footnote
  }
  const currentParentId = node.parent_uid || null
  const nextParentId = editForm.value.parent_block_uid === ROOT_PARENT_VALUE
    ? null
    : (editForm.value.parent_block_uid || null)
  if (nextParentId !== currentParentId) {
    payload.parent_block_uid = nextParentId
  }
  const currentLevel = typeof node.derived_level === 'number' ? node.derived_level : null
  const nextLevel = typeof editForm.value.derived_title_level === 'number'
    ? editForm.value.derived_title_level
    : null
  if (nextLevel !== currentLevel) {
    payload.derived_title_level = nextLevel
  }
  const mergeTargetId = editForm.value.merge_into_block_uid || null
  if (mergeTargetId) {
    payload.merge_into_block_uid = mergeTargetId
  }
  return Object.keys(payload).length > 1 ? payload : null
}

/* 提交节点纠错结果并刷新外层数据。 */
const submitNodeEdit = async () => {
  const node = editingNode.value
  if (!node || !props.onUpdateStructuredNode) {
    closeNodeEdit()
    return
  }
  const payload = buildNodeEditPayload(node)
  if (!payload) {
    message.info('内容未修改')
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

.edit-node-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.edit-node-id {
  color: var(--dp-sub-text, #64748b);
  font-size: 12px;
}

.edit-field-hint {
  margin-top: 6px;
  color: var(--dp-sub-text, #64748b);
  font-size: 12px;
  line-height: 1.5;
}

.edit-dialog-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.6fr) minmax(260px, 1fr);
  gap: 16px;
}

.edit-dialog-main,
.edit-dialog-side {
  min-width: 0;
}

.edit-dialog-side {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.edit-surface-card {
  padding: 12px;
  border-radius: 10px;
  border: 1px solid var(--dp-pane-border, #e2e8f0);
  background: color-mix(in srgb, var(--dp-pane-bg, #ffffff) 94%, #f8fafc 6%);
}

.edit-section-title {
  margin-bottom: 12px;
  font-size: 13px;
  font-weight: 600;
  color: var(--dp-title-strong, #0f172a);
}

.edit-form :deep(.ant-form-item) {
  margin-bottom: 12px;
}

.edit-form :deep(.ant-form-item:last-child) {
  margin-bottom: 0;
}

.edit-side-summary {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.edit-side-summary-card {
  flex: 1;
}

.edit-side-summary-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.edit-side-summary-label {
  font-size: 12px;
  color: var(--dp-sub-text, #64748b);
}

.edit-side-summary-value {
  color: var(--dp-title-text, #0f172a);
  line-height: 1.5;
  word-break: break-word;
}

.split-selection-form-item {
  margin-bottom: 16px;
}

.split-dialog-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

.split-dialog-main,
.split-dialog-side {
  min-width: 0;
}

.split-dialog-main,
.split-dialog-side,
.split-editor-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.split-overview-card,
.split-source-card,
.split-editor-card {
  padding: 14px;
  border-radius: 14px;
  border: 1px solid var(--dp-pane-border, #e2e8f0);
  background: color-mix(in srgb, var(--dp-pane-bg, #ffffff) 95%, #f8fafc 5%);
}

.split-overview-title-row,
.split-source-title-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.split-overview-title,
.split-source-title {
  font-weight: 600;
  color: var(--dp-title-strong, #0f172a);
}

.split-overview-hint,
.split-source-meta,
.split-segment-summary {
  font-size: 12px;
  line-height: 1.6;
  color: var(--dp-sub-text, #64748b);
}

.split-overview-stats {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.split-overview-stat {
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid var(--dp-pane-border, #e2e8f0);
  background: color-mix(in srgb, var(--dp-content-bg, #ffffff) 94%, #dbeafe 6%);
  color: var(--dp-title-text, #0f172a);
  font-size: 12px;
}

.split-source-text {
  margin: 12px 0 0;
  padding: 14px;
  border-radius: 12px;
  border: 1px solid var(--dp-pane-border, #e2e8f0);
  background: color-mix(in srgb, var(--dp-content-bg, #ffffff) 92%, #eff6ff 8%);
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
  line-height: 1.7;
  color: var(--dp-title-text, #0f172a);
  max-height: 420px;
  overflow: auto;
}

.split-segment-toolbar {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  align-items: center;
}

.split-segment-toolbar-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.split-segment-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.split-segment-card {
  padding: 12px;
  border-radius: 12px;
  border: 1px solid var(--dp-pane-border, #e2e8f0);
  background: color-mix(in srgb, var(--dp-content-bg, #ffffff) 97%, #eff6ff 3%);
  box-shadow: 0 10px 28px rgba(15, 23, 42, 0.06);
}

.split-segment-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
  font-size: 13px;
  color: var(--dp-title-strong, #0f172a);
}

.split-segment-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.split-segment-title {
  font-weight: 600;
}

.split-segment-badge {
  padding: 2px 10px;
  border-radius: 999px;
  background: color-mix(in srgb, #2563eb 14%, white);
  color: #1d4ed8;
  font-size: 12px;
}

.split-segment-meta {
  font-size: 12px;
  color: var(--dp-sub-text, #64748b);
}

.split-segment-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}

.split-segment-textarea :deep(textarea) {
  line-height: 1.65;
}

:deep(.doc-structured-modal .ant-modal-content) {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  box-shadow: 0 18px 48px rgba(15, 23, 42, 0.24);
}

:deep(.doc-structured-modal .ant-modal-header) {
  background: transparent;
  border-bottom: 1px solid #edf1f7;
}

:deep(.doc-structured-modal .ant-modal-title),
:deep(.doc-structured-modal .ant-form-item-label > label),
:deep(.doc-structured-modal .ant-select-selection-item),
:deep(.doc-structured-modal .ant-select-selection-placeholder),
:deep(.doc-structured-modal .ant-input),
:deep(.doc-structured-modal .ant-input-textarea),
:deep(.doc-structured-modal .ant-modal-close-x) {
  color: #0f172a;
}

:deep(.doc-structured-modal .ant-input),
:deep(.doc-structured-modal .ant-input-affix-wrapper),
:deep(.doc-structured-modal .ant-select-selector),
:deep(.doc-structured-modal .ant-input-number),
:deep(.doc-structured-modal .ant-input-textarea textarea) {
  background: #ffffff;
  border-color: #e2e8f0;
}

:deep(.doc-structured-modal .ant-modal-footer) {
  border-top: 1px solid #edf1f7;
}

:deep(.doc-structured-modal .ant-modal-body) {
  background: transparent;
}

:deep(.doc-structured-modal-dark .ant-modal-content) {
  background: #171b24;
  border-color: #2a3140;
}

:deep(.doc-structured-modal-dark .ant-modal-header),
:deep(.doc-structured-modal-dark .ant-modal-footer) {
  border-color: #2a3140;
}

:deep(.doc-structured-modal-dark .ant-modal-title),
:deep(.doc-structured-modal-dark .ant-form-item-label > label),
:deep(.doc-structured-modal-dark .ant-select-selection-item),
:deep(.doc-structured-modal-dark .ant-select-selection-placeholder),
:deep(.doc-structured-modal-dark .ant-select-multiple .ant-select-selection-item),
:deep(.doc-structured-modal-dark .ant-select-disabled.ant-select-multiple .ant-select-selection-item),
:deep(.doc-structured-modal-dark .ant-input),
:deep(.doc-structured-modal-dark .ant-input-textarea),
:deep(.doc-structured-modal-dark .ant-modal-close-x) {
  color: rgba(255, 255, 255, 0.82);
}

:deep(.doc-structured-modal-dark .ant-input),
:deep(.doc-structured-modal-dark .ant-input-affix-wrapper),
:deep(.doc-structured-modal-dark .ant-select-selector),
:deep(.doc-structured-modal-dark .ant-input-number),
:deep(.doc-structured-modal-dark .ant-input-textarea textarea) {
  background: #1d2330;
  border-color: #2a3140;
}

:deep(.doc-structured-modal-dark .ant-select-disabled .ant-select-selector),
:deep(.doc-structured-modal-dark .ant-select-multiple.ant-select-disabled .ant-select-selection-item) {
  background: #1d2330;
  color: rgba(255, 255, 255, 0.72);
}

:deep(.doc-structured-modal-dark .ant-btn-text) {
  color: rgba(255, 255, 255, 0.72);
}

:deep(.doc-structured-modal-dark .ant-btn-text:hover) {
  background: rgba(148, 163, 184, 0.14);
}

:deep(.doc-structured-modal-dark .ant-select-arrow),
:deep(.doc-structured-modal-dark .ant-modal-close-x) {
  color: rgba(255, 255, 255, 0.62);
}

:deep(.doc-structured-modal-dark .split-overview-card),
:deep(.doc-structured-modal-dark .split-source-card),
:deep(.doc-structured-modal-dark .split-editor-card),
:deep(.doc-structured-modal-dark .split-segment-card),
:deep(.doc-structured-modal-dark .edit-surface-card) {
  border-color: #2a3140;
  background: #1c2330;
}

:deep(.doc-structured-modal-dark .split-source-text) {
  border-color: #2a3140;
  background: #161b26;
  color: rgba(255, 255, 255, 0.86);
}

:deep(.doc-structured-modal-dark .split-overview-title),
:deep(.doc-structured-modal-dark .split-source-title),
:deep(.doc-structured-modal-dark .split-segment-title),
:deep(.doc-structured-modal-dark .split-segment-header),
:deep(.doc-structured-modal-dark .edit-side-summary-value),
:deep(.doc-structured-modal-dark .edit-section-title) {
  color: rgba(255, 255, 255, 0.88);
}

:deep(.doc-structured-modal-dark .split-overview-hint),
:deep(.doc-structured-modal-dark .split-source-meta),
:deep(.doc-structured-modal-dark .split-segment-summary),
:deep(.doc-structured-modal-dark .split-segment-meta),
:deep(.doc-structured-modal-dark .edit-field-hint),
:deep(.doc-structured-modal-dark .edit-side-summary-label),
:deep(.doc-structured-modal-dark .edit-node-id) {
  color: rgba(255, 255, 255, 0.58);
}

:deep(.doc-structured-modal-dark .split-overview-stat) {
  border-color: #334155;
  background: #131923;
  color: rgba(255, 255, 255, 0.8);
}

:deep(.doc-structured-modal-dark .split-segment-badge) {
  background: rgba(59, 130, 246, 0.18);
  color: #93c5fd;
}

@media (max-width: 900px) {
  .edit-dialog-layout {
    grid-template-columns: 1fr;
  }

  .split-dialog-layout {
    grid-template-columns: 1fr;
  }
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
