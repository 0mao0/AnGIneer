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
      <div class="floating-controls">
        <template v-if="activeTab === 'Preview_Markdown'">
          <div class="floating-group">
            <a-button
              type="primary"
              size="small"
              :disabled="!isContentDirty"
              class="action-btn"
              @click="emit('save-markdown')"
            >
              保存
            </a-button>
            <a-button
              size="small"
              :disabled="!isContentDirty"
              class="action-btn"
              @click="emit('cancel-markdown')"
            >
              取消
            </a-button>
          </div>
        </template>
        <template v-if="isIndexMode">
          <div class="floating-group">
            <a-select
              :value="strategyValue"
              size="small"
              class="strategy-select"
              @change="emit('strategy-change', $event)"
            >
              <a-select-option value="A_structured">结构化</a-select-option>
              <a-select-option value="B_mineru_rag">MinerU-RAG</a-select-option>
              <a-select-option value="C_pageindex">PageIndex</a-select-option>
            </a-select>
            <a-button
              type="primary"
              size="small"
              :loading="ingestStatusValue === 'processing'"
              :disabled="!canIngest"
              class="ingest-btn action-btn"
              @click="emit('trigger-ingest')"
            >
              {{ ingestButtonText }}
            </a-button>
          </div>
        </template>
      </div>
      <Preview_HTML
        v-if="activeTab === 'Preview_HTML'"
        :rendered-markdown="renderedMarkdown"
        :active-line-range="activeLineRange"
        @select-line="emit('select-line', $event)"
      />
      <Preview_Markdown
        v-else-if="activeTab === 'Preview_Markdown'"
        :editable-content="editableContent"
        :active-line-range="activeLineRange"
        @update:editable-content="emit('update:editableContent', $event)"
        @select-line="emit('select-line', $event)"
      />
      <div v-else class="index-layout">
        <div class="index-toolbar">
          <div class="index-summary-row">
            <span class="summary-tag">
              <span class="summary-item total">总{{ indexSummaryStats.total }}</span>
              <span class="summary-divider">|</span>
              <span class="summary-item figure">图形{{ indexSummaryStats.figure }}</span>
              <span class="summary-divider">|</span>
              <span class="summary-item table">表格{{ indexSummaryStats.table }}</span>
              <span class="summary-divider">|</span>
              <span class="summary-item formula">公式{{ indexSummaryStats.formula }}</span>
            </span>
          </div>
        </div>

        <Preview_IndexList
          v-if="activeTab === 'Preview_IndexList'"
          ref="indexContentScrollRef"
          :items="flatIndexItems"
          :current-page="indexCurrentPage"
          :page-size="indexPageSize"
          :active-linked-item-id="activeLinkedItemId"
          :node-map="graphNodeLookup"
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
          @toggle="onTreeToggle"
          @select="onNodeSelect"
        />
        <Preview_IndexGraph
          v-else
          :node-map="nodeMap"
          :children-map="childrenMap"
          :roots="roots"
          :expanded-node-ids="expandedGraphNodeIds"
          :active-node-id="activeNodeIdForGraphTree"
          :viewport-state="graphViewportState"
          @toggle="onGraphToggle"
          @select="onNodeSelect"
          @update-viewport="onViewportUpdate"
        />
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
import type { KnowledgeStrategy, StructuredIndexItem, DocBlocksGraph as DocBlocksGraphType } from '../../../types/knowledge'
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
  editableContent: string
  isContentDirty: boolean
  strategyValue: KnowledgeStrategy
  ingestStatusValue: 'idle' | 'processing' | 'completed' | 'failed'
  canIngest: boolean
  ingestButtonText: string
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
  graphData?: DocBlocksGraphType | null
}>()

type ParsedPdfViewerComponentEventMap = ParsedPdfViewerBridgeEventMap & {
  'update:editableContent': [value: string]
  'save-markdown': []
  'cancel-markdown': []
  'strategy-change': [value: KnowledgeStrategy]
  'trigger-ingest': []
  'hover-item': [id: string | null]
  'select-line': [line: number]
}

const emit = defineEmits<ParsedPdfViewerComponentEventMap>()

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
  onNodeSelect,
  onViewportUpdate,
  expandAncestors,
  setViewMode
} = useParsedPdfViewer(props, emit)

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

.strategy-select {
  width: 90px;
}

.strategy-select :deep(.ant-select-selector) {
  height: 24px !important;
  font-size: 12px;
}

.b2-content {
  position: relative;
  flex: 1;
  min-height: 0;
  overflow-y: overlay;
  background: var(--dp-content-bg);
}

.index-layout {
  display: flex;
  flex-direction: column;
  min-height: 100%;
  padding: 10px;
}

.index-toolbar {
  flex-shrink: 0;
}

.index-summary-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
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
