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
      @pane-click="focusCanvas"
      @connect="onConnect"
      @edge-update="onEdgeUpdate"
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
    </VueFlow>

    <div class="sop-flow-toolbar">
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
      <a-tooltip v-if="!readOnly" title="添加步骤">
        <a-button size="small" @click="$emit('add-step')">
          <template #icon><PlusOutlined /></template>
        </a-button>
      </a-tooltip>
      <a-tooltip v-if="!readOnly" title="保存">
        <a-button size="small" type="primary" :disabled="!isDirty" @click="$emit('save')">
          <template #icon><SaveOutlined /></template>
        </a-button>
      </a-tooltip>
    </div>
  </div>
</template>

<script setup lang="ts">
import { markRaw, ref } from 'vue'
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
} from '@ant-design/icons-vue'
import SOPStepNode from './SOPStepNode.vue'
import SOPStepEdge from './SOPStepEdge.vue'

const props = defineProps<{
  nodes: any[]
  edges: any[]
  isDirty?: boolean
  themeClass?: string
  readOnly?: boolean
  selectedStepId?: string | null
}>()

const emit = defineEmits<{
  'step-select': [nodeId: string]
  'step-dblclick': [nodeId: string]
  'save': []
  'dirty-change': [dirty: boolean]
  'add-step': []
  'auto-layout': []
  'nodes-change': [changes: any[]]
  'edges-change': [changes: any[]]
  'connect': [connection: Connection]
  'edge-update': [{ edgeId: string; connection: Connection }]
  'delete-step': [stepId: string]
  'select-citation': [binding: CitationBinding]
}>()

const nodeTypes: Record<string, any> = {
  'sop-step': markRaw(SOPStepNode),
}

const edgeTypes: Record<string, any> = {
  'sop-edge': markRaw(SOPStepEdge),
}

const { fitView: _fitView, zoomIn: _zoomIn, zoomOut: _zoomOut } = useVueFlow()
const canvasRef = ref<HTMLElement | null>(null)

const fitView = () => _fitView({ padding: 0.2 })
const zoomIn = () => _zoomIn()
const zoomOut = () => _zoomOut()

/**
 * 让画布容器获得焦点，以支持键盘删除。
 */
const focusCanvas = () => {
  canvasRef.value?.focus()
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
 * 处理新建连线。
 */
const onConnect = (connection: Connection) => {
  emit('connect', connection)
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

/**
 * 通过键盘删除当前选中步骤。
 */
const onCanvasKeydown = (event: KeyboardEvent) => {
  if (props.readOnly || !props.selectedStepId) {
    return
  }
  if (event.key !== 'Delete' && event.key !== 'Backspace') {
    return
  }
  event.preventDefault()
  emit('delete-step', props.selectedStepId)
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
  top: 12px;
  right: 12px;
  display: flex;
  gap: 4px;
  z-index: 10;
  padding: 4px 8px;
  border-radius: 6px;
  background: var(--panel-bg, #fff);
  border: 1px solid var(--border-color, #e8e8e8);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}
</style>
