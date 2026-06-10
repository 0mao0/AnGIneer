/**
 * SOP 流程图画布组件，基于 Vue Flow 渲染 SOP 步骤流程图。
 * 支持自定义节点/边、工具栏、右键菜单。
 */
<template>
  <div
    ref="canvasRef"
    class="sop-flow-canvas"
    :class="themeClass"
    tabindex="0"
    @keydown="onCanvasKeydown"
  >
    <VueFlow
      :nodes="nodes"
      :edges="edges"
      :node-types="nodeTypes"
      :edge-types="edgeTypes"
      :connection-mode="ConnectionMode.Loose"
      :fit-view-on-init="true"
      :default-viewport="{ zoom: 1 }"
      :min-zoom="0.2"
      :max-zoom="2"
      :nodes-draggable="!readOnly"
      :nodes-connectable="!readOnly"
      :edges-updatable="!readOnly"
      :elements-selectable="true"
      :delete-key-code="null"
      @node-click="onNodeClick"
      @node-double-click="onNodeDoubleClick"
      @node-drag-start="onNodeDragStart"
      @node-drag-stop="$emit('node-drag-stop')"
      @pane-click="focusCanvas"
      @connect="onConnect"
      @edge-update="onEdgeUpdate"
      @edge-double-click="onEdgeDoubleClick"
      @edge-click="onEdgeClick"
      @nodes-change="onNodesChange"
      @edges-change="onEdgesChange"
    >
      <template #node-sop-step="nodeProps">
        <SOPStepNode
          v-bind="nodeProps"
          :deletable="!readOnly"
          @delete="emit('delete-step', nodeProps.id)"
          @select-citation="emit('select-citation', $event)"
        />
      </template>
      <template #node-sop-fork="nodeProps">
        <SOPForkNode
          v-bind="nodeProps"
          :deletable="!readOnly"
          @delete="emit('delete-step', nodeProps.id)"
        />
      </template>
    </VueFlow>

    <!-- Edge inline edit overlay -->
    <div
      v-if="editingEdgeId"
      class="edge-inline-edit"
      :style="{
        left: editingEdgePosition.x + 'px',
        top: editingEdgePosition.y + 'px',
      }"
    >
      <a-input
        ref="edgeInputRef"
        v-model:value="editingEdgeLabel"
        size="small"
        @keydown.enter="confirmEdgeEdit"
        @keydown.escape="cancelEdgeEdit"
        @blur="confirmEdgeEdit"
      />
    </div>

    <div class="sop-flow-toolbar sop-flow-toolbar--top">
      <a-tooltip v-if="!readOnly" title="撤销">
        <a-button size="small" :disabled="!canUndo" @click="$emit('undo')">
          <template #icon><UndoOutlined /></template>
        </a-button>
      </a-tooltip>
      <a-tooltip v-if="!readOnly" title="重做">
        <a-button size="small" :disabled="!canRedo" @click="$emit('redo')">
          <template #icon><RedoOutlined /></template>
        </a-button>
      </a-tooltip>
      <a-tooltip v-if="!readOnly" title="添加步骤">
        <a-button size="small" @click="$emit('add-step')">
          <template #icon><PlusOutlined /></template>
        </a-button>
      </a-tooltip>
      <a-tooltip v-if="!readOnly" title="删除选中节点">
        <a-button size="small" :disabled="!selectedStepId" @click="$emit('delete-step', selectedStepId!)">
          <template #icon><DeleteOutlined /></template>
        </a-button>
      </a-tooltip>
      <a-tooltip v-if="!readOnly" title="保存">
        <a-button size="small" type="primary" :disabled="!isDirty" @click="$emit('save')">
          <template #icon><SaveOutlined /></template>
        </a-button>
      </a-tooltip>
    </div>

    <!-- 全局黑板面板 -->
    <div v-if="blackboardEntries.length" class="sop-blackboard-panel" :class="{ collapsed: blackboardCollapsed }">
      <div class="blackboard-header" @click="blackboardCollapsed = !blackboardCollapsed">
        <span class="blackboard-title">全局变量 ({{ blackboardEntries.length }})</span>
        <component :is="blackboardCollapsed ? RightOutlined : DownOutlined" class="blackboard-toggle" />
      </div>
      <div v-if="!blackboardCollapsed" class="blackboard-body">
        <table class="blackboard-table">
          <thead>
            <tr>
              <th>变量名</th>
              <th>值</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="entry in blackboardEntries" :key="entry.key">
              <td class="bb-key">{{ entry.key }}</td>
              <td class="bb-value">{{ entry.displayValue }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="sop-flow-toolbar sop-flow-toolbar--bottom">
      <a-tooltip title="适应画布">
        <a-button size="small" @click="fitView">
          <template #icon><CompressOutlined /></template>
        </a-button>
      </a-tooltip>
      <a-tooltip title="放大">
        <a-button size="small" @click="zoomIn">
          <template #icon><ZoomInOutlined /></template>
        </a-button>
      </a-tooltip>
      <a-tooltip title="缩小">
        <a-button size="small" @click="zoomOut">
          <template #icon><ZoomOutOutlined /></template>
        </a-button>
      </a-tooltip>
      <a-tooltip title="自动布局">
        <a-button size="small" @click="$emit('auto-layout')">
          <template #icon><ApartmentOutlined /></template>
        </a-button>
      </a-tooltip>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, markRaw, nextTick, provide, ref, watch } from 'vue'
import { ConnectionMode, VueFlow, useVueFlow, type Connection } from '@vue-flow/core'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import type { CitationBinding } from '@angineer/ui-kit'
import {
  CompressOutlined,
  ZoomInOutlined,
  ZoomOutOutlined,
  ApartmentOutlined,
  PlusOutlined,
  SaveOutlined,
  UndoOutlined,
  RedoOutlined,
  DeleteOutlined,
  RightOutlined,
  DownOutlined,
} from '@ant-design/icons-vue'
import SOPStepNode from './SOPStepNode.vue'
import SOPForkNode from './SOPForkNode.vue'
import SOPStepEdge from './SOPStepEdge.vue'

const props = defineProps<{
  nodes: any[]
  edges: any[]
  isDirty?: boolean
  canUndo?: boolean
  canRedo?: boolean
  themeClass?: string
  readOnly?: boolean
  selectedStepId?: string | null
  dirtyStepIds?: Set<string>
  blackboard?: Record<string, any> | null
}>()

const emit = defineEmits<{
  'step-select': [nodeId: string]
  'step-dblclick': [nodeId: string]
  'save': []
  'undo': []
  'redo': []
  'dirty-change': [dirty: boolean]
  'add-step': []
  'auto-layout': []
  'nodes-change': [changes: any[]]
  'edges-change': [changes: any[]]
  'connect': [connection: Connection]
  'edge-update': [{ edgeId: string; connection: Connection }]
  'edge-dblclick': [edgeId: string]
  'delete-step': [stepId: string]
  'delete-edge': [edgeId: string]
  'select-citation': [binding: CitationBinding]
  'edge-label-change': [{ edgeId: string; label: string }]
  'node-drag-start': []
  'node-drag-stop': []
}>()

// 注入给子边组件使用（Vue Flow 内部渲染的 edge 组件事件不冒泡）
provide('onDeleteEdge', (edgeId: string) => {
  emit('delete-edge', edgeId)
})


const nodeTypes: Record<string, any> = {
  'sop-step': markRaw(SOPStepNode),
  'sop-fork': markRaw(SOPForkNode),
}

const edgeTypes: Record<string, any> = {
  'sop-edge': markRaw(SOPStepEdge),
}

const { fitView: _fitView, zoomIn: _zoomIn, zoomOut: _zoomOut } = useVueFlow()
const canvasRef = ref<HTMLElement | null>(null)
const selectedEdgeId = ref<string | null>(null)
const editingEdgeId = ref<string | null>(null)
const editingEdgeLabel = ref('')
const editingEdgePosition = ref({ x: 0, y: 0 })
const edgeInputRef = ref<any>(null)
const blackboardCollapsed = ref(true)

/** 将 blackboard 对象转为扁平的 key-value 列表。 */
const blackboardEntries = computed(() => {
  const bb = props.blackboard
  if (!bb || typeof bb !== 'object') return []
  return Object.entries(bb).map(([key, value]) => ({
    key,
    displayValue: typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value ?? ''),
  }))
})

const fitView = () => _fitView({ padding: 0.2 })
const zoomIn = () => _zoomIn()
const zoomOut = () => _zoomOut()

const computeEdgeMidpoint = (edgeId: string): { x: number; y: number } => {
  const { getNodes } = useVueFlow()
  const edge = props.edges.find((e: any) => e.id === edgeId)
  if (!edge) return { x: 0, y: 0 }
  const nodes = getNodes.value
  const sourceNode = nodes.find((n: any) => n.id === edge.source)
  const targetNode = nodes.find((n: any) => n.id === edge.target)
  if (!sourceNode || !targetNode) return { x: 0, y: 0 }
  return {
    x: (sourceNode.position.x + targetNode.position.x) / 2,
    y: (sourceNode.position.y + targetNode.position.y) / 2,
  }
}

/**
 * 让画布容器获得焦点，以支持键盘删除。
 */
const focusCanvas = () => {
  canvasRef.value?.focus()
  selectedEdgeId.value = null
}

const onNodeClick = (event: any) => {
  focusCanvas()
  if (event.node) {
    emit('step-select', event.node.id)
  }
}

const onNodeDoubleClick = (event: any) => {
  focusCanvas()
  if (event.node) {
    emit('step-dblclick', event.node.id)
  }
}

/**
 * 节点拖拽开始时选中该步骤，确保属性面板切换到对应节点。
 */
const onNodeDragStart = (event: any) => {
  if (event.node) {
    emit('step-select', event.node.id)
  }
  emit('node-drag-start')
}

/**
 * 处理新建连线。
 */
const onConnect = (connection: Connection) => {
  emit('connect', connection)
}

/**
 * 处理边双击（用于编辑分支条件标签）。
 */
const onEdgeDoubleClick = (event: any) => {
  if (props.readOnly) return
  if (event.edge) {
    const mid = computeEdgeMidpoint(event.edge.id)
    editingEdgeId.value = event.edge.id
    editingEdgeLabel.value = event.edge.data?.label || ''
    editingEdgePosition.value = mid
    emit('edge-dblclick', event.edge.id)
  }
}

/**
 * 处理边单击（选中边以支持键盘删除）。
 */
const onEdgeClick = (event: any) => {
  if (event.edge) {
    selectedEdgeId.value = event.edge.id
  }
}

/**
 * 处理边重连。
 */
const onEdgeUpdate = (...args: any[]) => {
  const payload = args[0]?.edge && args[0]?.connection
    ? args[0]
    : { edge: args[0], connection: args[1] }
  if (!payload?.edge?.id || !payload?.connection) {
    return
  }
  emit('edge-update', {
    edgeId: payload.edge.id,
    connection: payload.connection,
  })
}

const confirmEdgeEdit = () => {
  if (editingEdgeId.value && editingEdgeLabel.value.trim()) {
    emit('edge-label-change', {
      edgeId: editingEdgeId.value,
      label: editingEdgeLabel.value.trim(),
    })
  }
  editingEdgeId.value = null
  editingEdgeLabel.value = ''
}

const cancelEdgeEdit = () => {
  editingEdgeId.value = null
  editingEdgeLabel.value = ''
}

watch(editingEdgeId, async (val) => {
  if (val) {
    await nextTick()
    edgeInputRef.value?.focus?.()
  }
})

/**
 * 通过键盘删除当前选中步骤或边。
 */
const onCanvasKeydown = (event: KeyboardEvent) => {
  if (props.readOnly) return
  if (event.key !== 'Delete' && event.key !== 'Backspace') return
  event.preventDefault()
  if (selectedEdgeId.value) {
    emit('delete-edge', selectedEdgeId.value)
    selectedEdgeId.value = null
    return
  }
  if (props.selectedStepId) {
    emit('delete-step', props.selectedStepId)
  }
}

const onNodesChange = (changes: any[]) => {
  emit('nodes-change', changes)
}

const onEdgesChange = (changes: any[]) => {
  emit('edges-change', changes)
}
</script>

<style lang="less" scoped>
.sop-flow-canvas {
  position: relative;
  width: 100%;
  height: 100%;
  background: var(--panel-bg, #fff);
}

.sop-flow-toolbar {
  position: absolute;
  right: 12px;
  display: flex;
  gap: 4px;
  z-index: 10;
  padding: 4px 8px;
  border-radius: 6px;
  background: var(--panel-bg, #fff);
  border: 1px solid var(--border-color, #e8e8e8);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);

  &--top {
    top: 12px;
    flex-direction: row;
  }

  &--bottom {
    bottom: 12px;
    flex-direction: column;
  }
}

.edge-inline-edit {
  position: absolute;
  z-index: 100;
  transform: translate(-50%, -50%);
  pointer-events: auto;

  :deep(.ant-input) {
    width: 140px;
    text-align: center;
    border: 2px solid var(--primary-color, #1890ff);
    border-radius: 4px;
    box-shadow: 0 2px 8px rgba(24, 144, 255, 0.2);
  }
}

.sop-blackboard-panel {
  position: absolute;
  left: 12px;
  bottom: 12px;
  z-index: 10;
  min-width: 200px;
  max-width: 320px;
  max-height: 260px;
  border-radius: 6px;
  background: var(--panel-bg, #fff);
  border: 1px solid var(--border-color, #e8e8e8);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  overflow: hidden;
  display: flex;
  flex-direction: column;

  &.collapsed {
    max-height: none;
  }
}

.blackboard-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 10px;
  cursor: pointer;
  user-select: none;
  border-bottom: 1px solid var(--border-color, #e8e8e8);

  &:hover {
    background: var(--hover-bg, rgba(0, 0, 0, 0.02));
  }
}

.blackboard-title {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-primary, #262626);
}

.blackboard-toggle {
  font-size: 10px;
  color: var(--text-secondary, #667085);
}

.blackboard-body {
  overflow-y: auto;
  max-height: 220px;
}

.blackboard-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;

  th {
    padding: 4px 10px;
    text-align: left;
    font-weight: 500;
    color: var(--text-secondary, #667085);
    background: var(--hover-bg, rgba(0, 0, 0, 0.02));
    border-bottom: 1px solid var(--border-color, #e8e8e8);
  }

  td {
    padding: 4px 10px;
    border-bottom: 1px solid var(--border-color, #e8e8e8);
  }
}

.bb-key {
  font-weight: 500;
  color: var(--text-primary, #262626);
  white-space: nowrap;
}

.bb-value {
  color: var(--text-secondary, #667085);
  word-break: break-all;
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
