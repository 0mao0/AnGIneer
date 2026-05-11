/**
 * SOP 流程图 Composable，管理 Vue Flow 节点/边与 SOP JSON 的双向转换。
 */
import { ref, computed } from 'vue'
import type { SopData, SopStep } from '../types/sop'

type FlowNode = { id: string; type?: string; position: { x: number; y: number }; data: { step: SopStep; stepIndex: number } }
type FlowEdge = { id: string; source: string; target: string; type?: string; data?: Record<string, any> }

const VERTICAL_GAP = 80
const HORIZONTAL_OFFSET = 200

/** 将步骤列表转换为垂直布局的节点位置 */
function computeStepPositions(stepCount: number): { x: number; y: number }[] {
  const positions = []
  for (let i = 0; i < stepCount; i++) {
    positions.push({
      x: HORIZONTAL_OFFSET,
      y: i * VERTICAL_GAP + 40,
    })
  }
  return positions
}

/** 管理 SOP 流程图状态 */
export function useSopFlow() {
  const nodes = ref<FlowNode[]>([])
  const edges = ref<FlowEdge[]>([])
  const isDirty = ref(false)
  const selectedStepId = ref<string | null>(null)

  /** 将 SOP JSON 转换为 Vue Flow Nodes/Edges */
  const loadFromSopData = (data: SopData) => {
    const positions = computeStepPositions(data.steps.length)
    nodes.value = data.steps.map((step, index) => ({
      id: step.id,
      type: 'sop-step',
      position: positions[index],
      data: { step, stepIndex: index },
    }))

    edges.value = data.steps.slice(0, -1).map((step, index) => ({
      id: `edge-${step.id}-${data.steps[index + 1].id}`,
      source: step.id,
      target: data.steps[index + 1].id,
      type: 'sop-edge',
      data: { label: '' },
    }))

    isDirty.value = false
  }

  /** 将 Vue Flow Nodes/Edges 转换回 SOP JSON */
  const exportToSopData = (baseData: SopData): SopData => {
    const sortedNodes = [...nodes.value].sort((a, b) => a.position.y - b.position.y)
    const steps: SopStep[] = sortedNodes.map((node) => node.data.step)
    return {
      ...baseData,
      steps,
    }
  }

  /** 添加新步骤节点 */
  const addStep = (afterStepId?: string) => {
    const newStepId = `step-${Date.now().toString(36)}`
    const newStep: SopStep = {
      id: newStepId,
      name: '新步骤',
      tool: 'manual',
      inputs: {},
      outputs: {},
    }

    let insertIndex = nodes.value.length
    if (afterStepId) {
      const idx = nodes.value.findIndex((n) => n.id === afterStepId)
      if (idx >= 0) insertIndex = idx + 1
    }

    const maxY = nodes.value.length > 0
      ? Math.max(...nodes.value.map((n) => n.position.y))
      : 0

    const newNode: FlowNode = {
      id: newStepId,
      type: 'sop-step',
      position: { x: HORIZONTAL_OFFSET, y: maxY + VERTICAL_GAP },
      data: { step: newStep, stepIndex: insertIndex },
    }

    nodes.value = [...nodes.value, newNode]

    if (afterStepId && insertIndex > 0) {
      const prevNodeId = afterStepId
      const nextNode = nodes.value[insertIndex + 1]
      edges.value = edges.value.filter((e) => !(e.source === prevNodeId && (!nextNode || e.target !== nextNode.id)))
      edges.value.push({
        id: `edge-${prevNodeId}-${newStepId}`,
        source: prevNodeId,
        target: newStepId,
        type: 'sop-edge',
        data: { label: '' },
      })
      if (nextNode) {
        edges.value.push({
          id: `edge-${newStepId}-${nextNode.id}`,
          source: newStepId,
          target: nextNode.id,
          type: 'sop-edge',
          data: { label: '' },
        })
      }
    } else if (nodes.value.length > 1) {
      const lastNode = nodes.value[nodes.value.length - 2]
      edges.value.push({
        id: `edge-${lastNode.id}-${newStepId}`,
        source: lastNode.id,
        target: newStepId,
        type: 'sop-edge',
        data: { label: '' },
      })
    }

    isDirty.value = true
    return newStepId
  }

  /** 删除步骤节点及相关边 */
  const removeStep = (stepId: string) => {
    const connectedEdges = edges.value.filter((e) => e.source === stepId || e.target === stepId)
    const incomingEdge = connectedEdges.find((e) => e.target === stepId)
    const outgoingEdge = connectedEdges.find((e) => e.source === stepId)

    const newEdges = edges.value.filter((e) => e.source !== stepId && e.target !== stepId)

    if (incomingEdge && outgoingEdge) {
      newEdges.push({
        id: `edge-${incomingEdge.source}-${outgoingEdge.target}`,
        source: incomingEdge.source,
        target: outgoingEdge.target,
        type: 'sop-edge',
        data: { label: '' },
      })
    }

    edges.value = newEdges
    nodes.value = nodes.value.filter((n) => n.id !== stepId)

    if (selectedStepId.value === stepId) {
      selectedStepId.value = null
    }

    isDirty.value = true
  }

  /** 自动布局（垂直排列） */
  const autoLayout = () => {
    const sorted = [...nodes.value].sort((a, b) => a.position.y - b.position.y)
    sorted.forEach((node, index) => {
      node.position = { x: HORIZONTAL_OFFSET, y: index * VERTICAL_GAP + 40 }
      node.data = { ...node.data, stepIndex: index }
    })
    nodes.value = [...sorted]
    isDirty.value = true
  }

  /** 更新指定步骤的数据 */
  const updateStepData = (stepId: string, updates: Partial<SopStep>) => {
    const node = nodes.value.find((n) => n.id === stepId)
    if (node) {
      node.data = {
        ...node.data,
        step: { ...node.data.step, ...updates },
      }
      nodes.value = [...nodes.value]
      isDirty.value = true
    }
  }

  /** 选中步骤 */
  const selectStep = (stepId: string | null) => {
    selectedStepId.value = stepId
  }

  /** 获取当前选中步骤 */
  const selectedStep = computed(() => {
    if (!selectedStepId.value) return null
    const node = nodes.value.find((n) => n.id === selectedStepId.value)
    return node?.data.step ?? null
  })

  return {
    nodes,
    edges,
    isDirty,
    selectedStepId,
    selectedStep,
    loadFromSopData,
    exportToSopData,
    addStep,
    removeStep,
    autoLayout,
    updateStepData,
    selectStep,
  }
}
