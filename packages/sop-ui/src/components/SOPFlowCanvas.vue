/**
 * SOP 流程图画布组件，基于 Vue Flow 渲染 SOP 步骤流程图。
 * 支持自定义节点/边、工具栏、右键菜单。
 */
<template>
  <div class="sop-flow-canvas" :class="themeClass">
    <VueFlow
      :nodes="nodes"
      :edges="edges"
      :node-types="nodeTypes"
      :edge-types="edgeTypes"
      :fit-view-on-init="true"
      :default-viewport="{ zoom: 1 }"
      :min-zoom="0.2"
      :max-zoom="2"
      @node-click="onNodeClick"
      @node-double-click="onNodeDoubleClick"
      @nodes-change="onNodesChange"
      @edges-change="onEdgesChange"
    >
      <Background :gap="16" />
      <Controls position="top-left" />
      <MiniMap position="bottom-right" />

      <template #node-sop-step="nodeProps">
        <SOPStepNode v-bind="nodeProps" />
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
      <a-tooltip title="添加步骤">
        <a-button size="small" @click="$emit('add-step')">
          <template #icon><PlusOutlined /></template>
        </a-button>
      </a-tooltip>
      <a-tooltip title="保存">
        <a-button size="small" type="primary" :disabled="!isDirty" @click="$emit('save')">
          <template #icon><SaveOutlined /></template>
        </a-button>
      </a-tooltip>
    </div>
  </div>
</template>

<script setup lang="ts">
import { markRaw } from 'vue'
import { VueFlow, useVueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MiniMap } from '@vue-flow/minimap'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/controls/dist/style.css'
import '@vue-flow/minimap/dist/style.css'
import {
  CompressOutlined,
  ZoomInOutlined,
  ZoomOutOutlined,
  ApartmentOutlined,
  PlusOutlined,
  SaveOutlined,
} from '@ant-design/icons-vue'
import SOPStepNode from './SOPStepNode.vue'

defineProps<{
  nodes: any[]
  edges: any[]
  isDirty?: boolean
  themeClass?: string
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
}>()

const nodeTypes: Record<string, any> = {
  'sop-step': markRaw(SOPStepNode),
}

const edgeTypes: Record<string, any> = {}

const { fitView: _fitView, zoomIn: _zoomIn, zoomOut: _zoomOut } = useVueFlow()

const fitView = () => _fitView({ padding: 0.2 })
const zoomIn = () => _zoomIn()
const zoomOut = () => _zoomOut()

const onNodeClick = (event: any) => {
  if (event.node) {
    emit('step-select', event.node.id)
  }
}

const onNodeDoubleClick = (event: any) => {
  if (event.node) {
    emit('step-dblclick', event.node.id)
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
