/**
 * SOP 流程图 Composable，管理 Vue Flow 节点/边与 SOP JSON 的双向转换。
 */
import { computed, ref } from 'vue'
import {
  MarkerType,
  type Connection,
} from '@vue-flow/core'
import type { SopData, SopStep, BranchTarget, FlowBranchEdgeData } from '../types/sop'

interface FlowNode {
  id: string
  type: 'sop-step' | 'sop-fork'
  position: { x: number; y: number }
  data: {
    step: SopStep
    stepIndex: number
    dirty?: boolean
    branchEdges?: Array<{ id: string; label: string; target: string; isDefault?: boolean }>
  }
  selected?: boolean
}

interface FlowEdge {
  id: string
  source: string
  target: string
  sourceHandle?: string
  targetHandle?: string
  type: 'sop-edge'
  data: FlowBranchEdgeData
  markerEnd: {
    type: MarkerType
    width: number
    height: number
  }
  selected?: boolean
}

const VERTICAL_GAP = 110
const HORIZONTAL_OFFSET = 220
const DEFAULT_SOURCE_HANDLE = 'bottom'
const DEFAULT_TARGET_HANDLE = 'top'

/**
 * 归一化任意来源的方向值，兼容旧的 source-/target- 前缀。
 */
function normalizeHandleDirection(handle?: string, fallback: string = DEFAULT_SOURCE_HANDLE): string {
  return String(handle || fallback).replace(/^source-/, '').replace(/^target-/, '') || fallback
}

/**
 * 归一化 source handle 方向值。
 */
function resolveSourceHandle(handle?: string): string {
  return normalizeHandleDirection(handle, DEFAULT_SOURCE_HANDLE)
}

/**
 * 归一化 target handle 方向值。
 */
function resolveTargetHandle(handle?: string): string {
  return normalizeHandleDirection(handle, DEFAULT_TARGET_HANDLE)
}

/**
 * 生成无向节点对 key，用于避免两个节点之间残留双向或重复连线。
 */
function createPairKey(source: string, target: string): string {
  return [source, target].sort().join('::')
}

/**
 * 生成默认垂直布局坐标。
 */
function computeDefaultPosition(index: number): { x: number; y: number } {
  return {
    x: HORIZONTAL_OFFSET,
    y: index * VERTICAL_GAP + 40,
  }
}

/**
 * 生成边 ID。
 */
function createEdgeId(source: string, target: string): string {
  return `edge-${source}-${target}`
}

/**
 * 生成运行时边对象。
 */
function createFlowEdge(
  source: string,
  target: string,
  sourceHandle: string = DEFAULT_SOURCE_HANDLE,
  targetHandle: string = DEFAULT_TARGET_HANDLE,
): FlowEdge {
  return {
    id: createEdgeId(source, target),
    source,
    target,
    sourceHandle: resolveSourceHandle(sourceHandle),
    targetHandle: resolveTargetHandle(targetHandle),
    type: 'sop-edge',
    data: { label: '' },
    markerEnd: {
      type: MarkerType.ArrowClosed,
      width: 18,
      height: 18,
    },
  }
}

/**
 * 根据节点 ID 查找节点。
 */
function getNodeById(nodesList: FlowNode[], nodeId: string): FlowNode | undefined {
  return nodesList.find((node) => node.id === nodeId)
}

/**
 * 按当前边关系推导步骤展示顺序。
 */
function getOrderedNodeIds(nodesList: FlowNode[], edgesList: FlowEdge[]): string[] {
  const incomingCount = new Map<string, number>()
  const outgoingMap = new Map<string, string[]>()
  const nodeMap = new Map(nodesList.map((node) => [node.id, node]))

  for (const node of nodesList) {
    incomingCount.set(node.id, 0)
    outgoingMap.set(node.id, [])
  }
  for (const edge of edgesList) {
    incomingCount.set(edge.target, (incomingCount.get(edge.target) || 0) + 1)
    const targets = outgoingMap.get(edge.source) || []
    targets.push(edge.target)
    outgoingMap.set(edge.source, targets)
  }

  const startNodes = nodesList
    .filter((node) => (incomingCount.get(node.id) || 0) === 0)
    .sort((a, b) => (a.position.y - b.position.y) || (a.position.x - b.position.x))

  const ordered: string[] = []
  const visited = new Set<string>()
  const queue: string[] = startNodes.map((n) => n.id)

  while (queue.length > 0) {
    const currentId = queue.shift()!
    if (visited.has(currentId) || !nodeMap.has(currentId)) continue
    visited.add(currentId)
    ordered.push(currentId)
    const targets = outgoingMap.get(currentId) || []
    for (const targetId of targets) {
      if (!visited.has(targetId) && !queue.includes(targetId)) {
        queue.push(targetId)
      }
    }
  }

  const remaining = nodesList
    .filter((node) => !visited.has(node.id))
    .sort((a, b) => (a.position.y - b.position.y) || (a.position.x - b.position.x))
    .map((node) => node.id)

  return [...ordered, ...remaining]
}

/** 管理 SOP 流程图状态 */
export function useSopFlow() {
  const nodes = ref<FlowNode[]>([])
  const edges = ref<FlowEdge[]>([])
  const isDirty = ref(false)
  const selectedStepId = ref<string | null>(null)
  const dirtyStepIds = ref<Set<string>>(new Set())

  /**
   * 同步节点中的步骤序号。
   */
  const syncStepIndexes = () => {
    const orderedIds = getOrderedNodeIds(nodes.value, edges.value)
    const indexMap = new Map(orderedIds.map((id, index) => [id, index]))
    nodes.value = nodes.value
      .map((node) => ({
        ...node,
        data: {
          ...node.data,
          stepIndex: indexMap.get(node.id) ?? node.data.stepIndex,
        },
      }))
      .sort((a, b) => (a.data.stepIndex - b.data.stepIndex) || (a.position.y - b.position.y))
  }

  /**
   * 同步所有 fork 节点的 branchEdges，确保 handles 与 edges 始终一致。
   */
  const syncBranchEdges = () => {
    const sourceEdgesMap = new Map<string, Array<{ id: string; label: string; target: string; isDefault: boolean }>>()
    for (const edge of edges.value) {
      if (!sourceEdgesMap.has(edge.source)) {
        sourceEdgesMap.set(edge.source, [])
      }
      sourceEdgesMap.get(edge.source)!.push({
        id: edge.id,
        label: edge.data?.label || '',
        target: edge.target,
        isDefault: !!edge.data?.isDefault,
      })
    }
    nodes.value = nodes.value.map((node) => {
      if (node.type !== 'sop-fork') return node
      return {
        ...node,
        data: {
          ...node.data,
          branchEdges: sourceEdgesMap.get(node.id) || [],
        },
      }
    })
  }

  /**
   * 根据步骤数据创建节点。
   */
  const createFlowNode = (step: SopStep, index: number, nodeType?: 'sop-step' | 'sop-fork'): FlowNode => {
    const position = step.ui_meta?.position || computeDefaultPosition(index)
    const type = nodeType || (step.execution?.tool === 'conditional' ? 'sop-fork' : 'sop-step')
    return {
      id: step.id,
      type,
      position: {
        x: position.x,
        y: position.y,
      },
      data: {
        step,
        stepIndex: index,
        dirty: false,
      },
    }
  }

  /** 判断节点是否为分叉类型。 */
  const isForkNode = (nodeId: string): boolean => {
    return nodes.value.some((n) => n.id === nodeId && n.type === 'sop-fork')
  }

  /**
   * 约束边集合，分叉节点允许多出边，汇合节点允许多入边。
   */
  const normalizeEdges = (inputEdges: FlowEdge[]): FlowEdge[] => {
    const filtered: FlowEdge[] = []
    const usedSources = new Set<string>()
    const usedTargets = new Set<string>()
    const usedPairs = new Set<string>()
    const validNodeIds = new Set(nodes.value.map((node) => node.id))
    const forkNodeIds = new Set(nodes.value.filter((n) => n.type === 'sop-fork').map((n) => n.id))

    for (const edge of inputEdges) {
      if (!validNodeIds.has(edge.source) || !validNodeIds.has(edge.target) || edge.source === edge.target) {
        continue
      }
      const pairKey = createPairKey(edge.source, edge.target)
      if (usedPairs.has(pairKey)) {
        continue
      }
      // 非分叉节点只允许一条出边
      if (!forkNodeIds.has(edge.source) && usedSources.has(edge.source)) {
        continue
      }
      // 非汇合节点只允许一条入边（汇合 = 被多个来源指向的节点）
      const convergingTargets = new Set(
        inputEdges
          .filter((e) => validNodeIds.has(e.source) && validNodeIds.has(e.target) && e.source !== e.target)
          .filter((e) => inputEdges.filter((e2) => e2.target === e.target).length > 1)
          .map((e) => e.target),
      )
      if (!convergingTargets.has(edge.target) && usedTargets.has(edge.target)) {
        continue
      }
      usedSources.add(edge.source)
      usedTargets.add(edge.target)
      usedPairs.add(pairKey)
      filtered.push({
        ...createFlowEdge(
          edge.source,
          edge.target,
          resolveSourceHandle(edge.sourceHandle),
          resolveTargetHandle(edge.targetHandle),
        ),
        id: edge.id || createEdgeId(edge.source, edge.target),
        data: { label: edge.data?.label || '' },
      })
    }
    return filtered
  }

  /**
   * 将 SOP JSON 转换为 Vue Flow Nodes/Edges。
   */
  const loadFromSopData = (data: SopData) => {
    nodes.value = data.steps.map((step, index) => createFlowNode(step, index))
    const validIds = new Set(data.steps.map((step) => step.id))
    const stepMap = new Map(data.steps.map((step) => [step.id, step]))
    const runtimeEdges: FlowEdge[] = []

    data.steps.forEach((step, index) => {
      // 条件分叉步骤：从 branches 创建多条出边
      if (step.execution?.tool === 'conditional') {
        const branches = step.branches
        if (branches && branches.length > 0) {
          branches.forEach((branch, branchIdx) => {
            const targetId = branch.goto
            if (targetId && validIds.has(targetId) && targetId !== step.id) {
              const targetStep = stepMap.get(targetId)
              runtimeEdges.push({
                ...createFlowEdge(
                  step.id,
                  targetId,
                  `branch-${branchIdx}`,
                  targetStep?.ui_meta?.target_handle || DEFAULT_TARGET_HANDLE,
                ),
                id: `edge-${step.id}-branch-${branchIdx}`,
                data: { label: branch.match || '' },
              })
            }
          })
        }
        // default_goto
        const defaultGoto = step.default_goto
        if (defaultGoto && validIds.has(defaultGoto) && defaultGoto !== step.id) {
          const targetStep = stepMap.get(defaultGoto)
          runtimeEdges.push({
            ...createFlowEdge(
              step.id,
              defaultGoto,
              `branch-default`,
              targetStep?.ui_meta?.target_handle || DEFAULT_TARGET_HANDLE,
            ),
            id: `edge-${step.id}-branch-default`,
            data: { label: '默认', isDefault: true },
          })
        }
        return
      }

      const nextId = validIds.has(step.next_step_id || '') ? step.next_step_id : data.steps[index + 1]?.id
      if (!nextId || nextId === step.id) {
        return
      }
      const targetStep = stepMap.get(nextId)
      runtimeEdges.push(createFlowEdge(
        step.id,
        nextId,
        step.ui_meta?.source_handle || DEFAULT_SOURCE_HANDLE,
        targetStep?.ui_meta?.target_handle || DEFAULT_TARGET_HANDLE,
      ))
    })

    edges.value = normalizeEdges(runtimeEdges)
    syncBranchEdges()
    syncStepIndexes()
    isDirty.value = false
    dirtyStepIds.value = new Set()
    selectedStepId.value = null
  }

  /**
   * 将 Vue Flow Nodes/Edges 转换回 SOP JSON。
   */
  const exportToSopData = (baseData: SopData): SopData => {
    const orderedIds = getOrderedNodeIds(nodes.value, edges.value)
    const nodeMap = new Map(nodes.value.map((node) => [node.id, node]))
    const outgoingEdgesMap = new Map<string, FlowEdge[]>()
    const incomingEdgesMap = new Map<string, FlowEdge[]>()
    for (const edge of edges.value) {
      if (!outgoingEdgesMap.has(edge.source)) outgoingEdgesMap.set(edge.source, [])
      outgoingEdgesMap.get(edge.source)!.push(edge)
      if (!incomingEdgesMap.has(edge.target)) incomingEdgesMap.set(edge.target, [])
      incomingEdgesMap.get(edge.target)!.push(edge)
    }

    const steps: SopStep[] = orderedIds
      .map((id) => nodeMap.get(id))
      .filter((node): node is FlowNode => Boolean(node))
      .map((node) => {
        const outgoingEdges = outgoingEdgesMap.get(node.id) || []
        const incomingEdges = incomingEdgesMap.get(node.id) || []
        const outgoingEdge = outgoingEdges[0]
        const incomingEdge = incomingEdges[0]

        // 分叉节点：从出边构建 branches，正确分离 default_goto
        if (node.type === 'sop-fork') {
          const defaultEdge = outgoingEdges.find((e) => e.data?.isDefault)
          const branchEdges = outgoingEdges.filter((e) => !e.data?.isDefault)
          const branches: BranchTarget[] = branchEdges.map((edge) => ({
            match: edge.data?.label || '',
            goto: edge.target || undefined,
          }))
          return {
            ...node.data.step,
            next_step_id: undefined,
            branches,
            default_goto: defaultEdge?.target || undefined,
            execution: {
              ...node.data.step.execution,
            },
            ui_meta: {
              position: {
                x: Number(node.position.x || 0),
                y: Number(node.position.y || 0),
              },
              source_handle: node.data.step.ui_meta?.source_handle || DEFAULT_SOURCE_HANDLE,
              target_handle: node.data.step.ui_meta?.target_handle || DEFAULT_TARGET_HANDLE,
            },
          }
        }

        return {
          ...node.data.step,
          next_step_id: outgoingEdge?.target,
          ui_meta: {
            position: {
              x: Number(node.position.x || 0),
              y: Number(node.position.y || 0),
            },
            source_handle: normalizeHandleDirection(
              outgoingEdge?.sourceHandle,
              node.data.step.ui_meta?.source_handle || DEFAULT_SOURCE_HANDLE,
            ),
            target_handle: normalizeHandleDirection(
              incomingEdge?.targetHandle,
              node.data.step.ui_meta?.target_handle || DEFAULT_TARGET_HANDLE,
            ),
          },
        }
      })

    return {
      ...baseData,
      steps,
    }
  }

  /**
   * 应用节点变化。
   */
  const handleNodesChange = (changes: Array<any>) => {
    const removeChanges = changes.filter((change) => change.type === 'remove' && typeof change.id === 'string')
    if (removeChanges.length) {
      removeChanges.forEach((change) => removeStep(String(change.id)))
      return
    }

    const nextNodes = [...nodes.value]
    for (const change of changes) {
      const node = getNodeById(nextNodes, String(change.id || ''))
      if (!node) {
        continue
      }
      if (change.type === 'position' && change.position) {
        const newX = Number(change.position.x ?? node.position.x)
        const newY = Number(change.position.y ?? node.position.y)
        if (node.position.x !== newX || node.position.y !== newY) {
          node.position = { x: newX, y: newY }
          const next = new Set(dirtyStepIds.value)
          next.add(node.id)
          dirtyStepIds.value = next
        }
        continue
      }
      if (change.type === 'select') {
        node.selected = Boolean(change.selected)
      }
    }
    nodes.value = nextNodes
    syncStepIndexes()
  }

  /**
   * 应用边变化。
   */
  const handleEdgesChange = (changes: Array<any>) => {
    let nextEdges = [...edges.value]
    let changed = false
    for (const change of changes) {
      if (change.type === 'remove' && typeof change.id === 'string') {
        nextEdges = nextEdges.filter((edge) => edge.id !== change.id)
        changed = true
        continue
      }
      if (change.type === 'select' && typeof change.id === 'string') {
        const edge = nextEdges.find((item) => item.id === change.id)
        if (edge) {
          edge.selected = Boolean(change.selected)
        }
      }
    }
    edges.value = normalizeEdges(nextEdges)
    if (changed) {
      isDirty.value = true
    }
    syncStepIndexes()
  }

  /**
   * 建立连接。分叉节点允许多条出边。
   */
  const connectSteps = (connection: Connection) => {
    if (!connection.source || !connection.target || connection.source === connection.target) {
      return
    }
    const pairKey = createPairKey(connection.source, connection.target)
    const sourceIsFork = isForkNode(connection.source)

    let nextEdges = edges.value.filter(
      (edge) => createPairKey(edge.source, edge.target) !== pairKey,
    )

    // 非分叉节点：替换已有出边
    if (!sourceIsFork) {
      nextEdges = nextEdges.filter((edge) => edge.source !== connection.source)
    }

    nextEdges.push(createFlowEdge(
      connection.source,
      connection.target,
      connection.sourceHandle || DEFAULT_SOURCE_HANDLE,
      connection.targetHandle || DEFAULT_TARGET_HANDLE,
    ))
    edges.value = normalizeEdges(nextEdges)
    if (connection.source) {
      const next = new Set(dirtyStepIds.value)
      next.add(connection.source)
      dirtyStepIds.value = next
    }
    isDirty.value = true
    syncBranchEdges()
    syncStepIndexes()
  }

  /**
   * 更新现有边的连接关系。
   */
  const updateEdgeConnection = (edgeId: string, connection: Connection) => {
    if (!connection.source || !connection.target || connection.source === connection.target) {
      return
    }
    const pairKey = createPairKey(connection.source, connection.target)
    const sourceIsFork = isForkNode(connection.source)

    let nextEdges = edges.value.filter(
      (edge) =>
        edge.id !== edgeId &&
        createPairKey(edge.source, edge.target) !== pairKey,
    )

    if (!sourceIsFork) {
      nextEdges = nextEdges.filter((edge) => edge.source !== connection.source)
    }

    nextEdges.push(createFlowEdge(
      connection.source,
      connection.target,
      connection.sourceHandle || DEFAULT_SOURCE_HANDLE,
      connection.targetHandle || DEFAULT_TARGET_HANDLE,
    ))
    edges.value = normalizeEdges(nextEdges)
    isDirty.value = true
    syncBranchEdges()
    syncStepIndexes()
  }

  /**
   * 添加新步骤节点。
   */
  const addStep = (afterStepId?: string) => {
    const newStepId = `step-${Date.now().toString(36)}`
    const sourceNode = afterStepId ? nodes.value.find((node) => node.id === afterStepId) : null
    const newStep: SopStep = {
      id: newStepId,
      name: '新步骤',
      description: { content: '', citations: [] },
      execution: {
        tool: 'manual',
        inputs: {},
        outputs: {},
      },
      ui_meta: {
        position: sourceNode
          ? {
              x: sourceNode.position.x + 220,
              y: sourceNode.position.y,
            }
          : computeDefaultPosition(nodes.value.length),
        source_handle: DEFAULT_SOURCE_HANDLE,
        target_handle: DEFAULT_TARGET_HANDLE,
      },
    }

    nodes.value = [...nodes.value, createFlowNode(newStep, nodes.value.length)]

    if (afterStepId) {
      const sourceIsFork = isForkNode(afterStepId)
      // 分叉节点：追加一条新出边（不影响已有分支）
      if (sourceIsFork) {
        edges.value = normalizeEdges([
          ...edges.value,
          createFlowEdge(afterStepId, newStepId),
        ])
      } else {
        const replacedEdge = edges.value.find((edge) => edge.source === afterStepId)
        const nextEdges = edges.value.filter((edge) => edge.source !== afterStepId)
        nextEdges.push(createFlowEdge(afterStepId, newStepId))
        if (replacedEdge) {
          nextEdges.push(createFlowEdge(newStepId, replacedEdge.target))
        }
        edges.value = normalizeEdges(nextEdges)
      }
    } else if (nodes.value.length > 1) {
      const orderedIds = getOrderedNodeIds(nodes.value, edges.value)
      const previousId = orderedIds[orderedIds.length - 2]
      if (previousId) {
        edges.value = normalizeEdges([
          ...edges.value.filter((edge) => edge.source !== previousId),
          createFlowEdge(previousId, newStepId),
        ])
      }
    }

    selectedStepId.value = newStepId
    isDirty.value = true
    syncBranchEdges()
    syncStepIndexes()
    return newStepId
  }

  /**
   * 删除步骤节点及相关边。
   */
  const removeStep = (stepId: string) => {
    const incomingEdges = edges.value.filter((edge) => edge.target === stepId)
    const outgoingEdges = edges.value.filter((edge) => edge.source === stepId)
    const deletedIsFork = isForkNode(stepId)
    const nextEdges = edges.value.filter((edge) => edge.source !== stepId && edge.target !== stepId)

    // 分叉节点删除：将每条入边连接到每条出边（或第一条出边）
    if (deletedIsFork && outgoingEdges.length > 0) {
      for (const inEdge of incomingEdges) {
        for (const outEdge of outgoingEdges) {
          if (inEdge.source !== outEdge.target) {
            nextEdges.push(createFlowEdge(
              inEdge.source,
              outEdge.target,
              inEdge.sourceHandle || DEFAULT_SOURCE_HANDLE,
              outEdge.targetHandle || DEFAULT_TARGET_HANDLE,
            ))
          }
        }
      }
    } else {
      // 普通节点：入边接出边
      const incomingEdge = incomingEdges[0]
      const outgoingEdge = outgoingEdges[0]
      if (incomingEdge && outgoingEdge && incomingEdge.source !== outgoingEdge.target) {
        nextEdges.push(createFlowEdge(
          incomingEdge.source,
          outgoingEdge.target,
          incomingEdge.sourceHandle || DEFAULT_SOURCE_HANDLE,
          outgoingEdge.targetHandle || DEFAULT_TARGET_HANDLE,
        ))
      }
    }

    edges.value = normalizeEdges(nextEdges)
    nodes.value = nodes.value.filter((node) => node.id !== stepId)
    if (selectedStepId.value === stepId) {
      selectedStepId.value = null
    }
    isDirty.value = true
    syncBranchEdges()
    syncStepIndexes()
  }

  /**
   * 删除单条边。
   */
  const removeEdge = (edgeId: string) => {
    const edge = edges.value.find((e) => e.id === edgeId)
    if (edge) {
      const next = new Set(dirtyStepIds.value)
      next.add(edge.source)
      dirtyStepIds.value = next
    }
    edges.value = normalizeEdges(edges.value.filter((e) => e.id !== edgeId))
    isDirty.value = true
    syncBranchEdges()
    syncStepIndexes()
  }

  /**
   * 自动布局（DAG 分支布局，BFS 分配层级 + 分支水平展开）。
   */
  const autoLayout = () => {
    const outgoingMap = new Map<string, string[]>()
    const incomingMap = new Map<string, string[]>()
    for (const n of nodes.value) {
      outgoingMap.set(n.id, [])
      incomingMap.set(n.id, [])
    }
    for (const edge of edges.value) {
      outgoingMap.get(edge.source)?.push(edge.target)
      incomingMap.get(edge.target)?.push(edge.source)
    }

    // BFS from start nodes to assign depth
    const depthMap = new Map<string, number>()
    const startIds = nodes.value
      .filter((n) => (incomingMap.get(n.id) || []).length === 0)
      .map((n) => n.id)

    const queue: string[] = [...startIds]
    for (const id of queue) depthMap.set(id, 0)

    while (queue.length > 0) {
      const cur = queue.shift()!
      const curDepth = depthMap.get(cur) || 0
      for (const target of outgoingMap.get(cur) || []) {
        const newDepth = curDepth + 1
        if (!depthMap.has(target) || depthMap.get(target)! < newDepth) {
          depthMap.set(target, newDepth)
        }
        if (!queue.includes(target)) queue.push(target)
      }
    }

    // Assign columns via BFS traversal
    const columnMap = new Map<string, number>()
    for (const id of startIds) columnMap.set(id, 0)

    const visited = new Set<string>()
    const colQueue: string[] = [...startIds]
    while (colQueue.length > 0) {
      const cur = colQueue.shift()!
      if (visited.has(cur)) continue
      visited.add(cur)
      const curCol = columnMap.get(cur) || 0
      const children = outgoingMap.get(cur) || []

      if (children.length === 1) {
        // Single child: inherit column
        if (!columnMap.has(children[0])) {
          columnMap.set(children[0], curCol)
        }
        if (!visited.has(children[0]) && !colQueue.includes(children[0])) {
          colQueue.push(children[0])
        }
      } else if (children.length > 1) {
        // Fork: spread children horizontally
        const spread = children.length - 1
        children.forEach((childId, idx) => {
          const offset = idx - spread / 2
          if (!columnMap.has(childId)) {
            columnMap.set(childId, curCol + offset)
          }
          if (!visited.has(childId) && !colQueue.includes(childId)) {
            colQueue.push(childId)
          }
        })
      }
    }

    // For join nodes (multiple predecessors), average their predecessors' columns
    for (const node of nodes.value) {
      const preds = incomingMap.get(node.id) || []
      if (preds.length > 1) {
        const avgCol = preds.reduce((sum, pid) => sum + (columnMap.get(pid) || 0), 0) / preds.length
        columnMap.set(node.id, Math.round(avgCol))
      }
    }

    // Apply positions
    nodes.value = nodes.value.map((node) => {
      const depth = depthMap.get(node.id) ?? 0
      const col = columnMap.get(node.id) ?? 0
      const x = HORIZONTAL_OFFSET + col * HORIZONTAL_OFFSET
      const y = depth * VERTICAL_GAP + 40
      const oldPos = node.position
      if (oldPos.x !== x || oldPos.y !== y) {
        const next = new Set(dirtyStepIds.value)
        next.add(node.id)
        dirtyStepIds.value = next
      }
      return {
        ...node,
        position: { x, y },
        data: {
          ...node.data,
          step: {
            ...node.data.step,
            ui_meta: {
              ...(node.data.step.ui_meta || {}),
              position: { x, y },
            },
          },
        },
      }
    })
    isDirty.value = true
    syncBranchEdges()
    syncStepIndexes()
  }

  /**
   * 更新指定步骤的数据。
   */
  const updateStepData = (stepId: string, updates: Partial<SopStep>) => {
    const targetNode = nodes.value.find((node) => node.id === stepId)
    if (!targetNode) {
      return
    }

    const next = new Set(dirtyStepIds.value)
    next.add(stepId)
    dirtyStepIds.value = next

    nodes.value = nodes.value.map((node) => {
      if (node.id !== stepId) return node
      return {
        ...node,
        data: {
          ...node.data,
          step: {
            ...node.data.step,
            ...updates,
            execution: {
              ...node.data.step.execution,
              ...(updates.execution || {}),
              inputs: updates.execution?.inputs
                ? { ...updates.execution.inputs }
                : { ...node.data.step.execution.inputs },
              outputs: updates.execution?.outputs
                ? { ...updates.execution.outputs }
                : { ...node.data.step.execution.outputs },
            },
            ui_meta: {
              ...(node.data.step.ui_meta || {}),
              ...(updates.ui_meta || {}),
            },
          },
        },
      }
    })
    isDirty.value = true
  }

  /**
   * 标记步骤节点为脏（红点），由属性面板 dirty-change 事件触发。
   */
  const markStepDirty = (stepId: string) => {
    const next = new Set(dirtyStepIds.value)
    next.add(stepId)
    dirtyStepIds.value = next
  }

  /**
   * 选中步骤。
   */
  const selectStep = (stepId: string | null) => {
    selectedStepId.value = stepId
  }

  /**
   * 获取当前选中步骤。
   */
  const selectedStep = computed(() => {
    if (!selectedStepId.value) return null
    const node = nodes.value.find((item) => item.id === selectedStepId.value)
    return node?.data.step ?? null
  })

  /**
   * 更新边标签（分支条件文字）。
   */
  const updateEdgeLabel = (edgeId: string, label: string) => {
    const edge = edges.value.find((e) => e.id === edgeId)
    if (!edge) return
    edge.data = { ...edge.data, label }
    edges.value = [...edges.value]
    if (edge.source) {
      const next = new Set(dirtyStepIds.value)
      next.add(edge.source)
      dirtyStepIds.value = next
    }
    isDirty.value = true
    syncBranchEdges()
  }

  /**
   * 清除所有节点的 dirty 标记。
   */
  const clearDirty = () => {
    dirtyStepIds.value = new Set()
  }

  return {
    nodes,
    edges,
    isDirty,
    selectedStepId,
    selectedStep,
    dirtyStepIds,
    loadFromSopData,
    exportToSopData,
    handleNodesChange,
    handleEdgesChange,
    connectSteps,
    updateEdgeConnection,
    addStep,
    removeStep,
    removeEdge,
    autoLayout,
    updateStepData,
    syncBranchEdges,
    updateEdgeLabel,
    clearDirty,
    markStepDirty,
    selectStep,
  }
}
