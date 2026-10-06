<template>
  <div class="arch-map-view">
    <div class="arch-body">
      <div class="arch-sidebar">
        <div class="arch-sidebar-title arch-collapse-title" @click="showProblems = !showProblems">
          <span class="arch-collapse-arrow" :class="{ open: showProblems }">▸</span>问题清单（{{ ARCH_PROBLEMS.length }}）
        </div>
        <template v-if="showProblems">
          <div
            v-for="p in ARCH_PROBLEMS"
            :key="p.id"
            class="arch-problem-card"
            :class="[`sev-${p.severity}`, { active: activeProblemId === p.id }]"
            @click="toggleProblem(p.id)"
          >
            <div class="arch-problem-head">
              <span class="arch-problem-id">{{ p.id }}</span>
              <span class="arch-problem-title">{{ p.title }}</span>
            </div>
            <div v-if="activeProblemId === p.id" class="arch-problem-desc">
              {{ p.desc }}
              <div v-for="a in p.anchors" :key="a" class="arch-anchor">{{ a }}</div>
            </div>
          </div>
        </template>

        <div class="arch-sidebar-title arch-collapse-title" @click="showRefs = !showRefs">
          <span class="arch-collapse-arrow" :class="{ open: showRefs }">▸</span>参考文献（{{ ARCH_REFERENCES.length }}）
        </div>
        <template v-if="showRefs">
          <div v-for="r in ARCH_REFERENCES" :key="r.id" class="arch-ref-card">
            <div class="arch-ref-name">
              <span>{{ r.name }}</span>
              <a v-if="r.link" :href="r.link" target="_blank" rel="noopener" class="arch-ref-link">链接</a>
              <span v-else class="arch-ref-link pending">链接待补</span>
            </div>
            <div class="arch-ref-row"><span class="arch-ref-label">匹配度</span>{{ r.match }}</div>
            <div class="arch-ref-row"><span class="arch-ref-label">我们的优势</span>{{ r.advantage }}</div>
          </div>
        </template>
      </div>

      <div class="arch-canvas">
        <div class="arch-float-controls">
          <a-checkbox v-model:checked="onlyProblems">只看问题</a-checkbox>
          <a-button size="small" @click="resetView">重置视图</a-button>
        </div>
        <div class="arch-legend">
          <div class="arch-legend-title">图例</div>
          <div v-for="(meta, st) in STATUS_META" :key="st" class="arch-legend-item">
            <span class="arch-legend-dot" :style="{ background: meta.color }" />
            <span>{{ meta.label }}</span>
          </div>
          <div class="arch-legend-item"><span class="arch-legend-line sse" /><span>SSE 帧（后端→前端唯一通道）</span></div>
          <div class="arch-legend-item"><span class="arch-legend-line loop" /><span>回灌 / 重试</span></div>
          <div class="arch-legend-item"><span class="arch-legend-line planned" /><span>◇ 待建通路</span></div>
        </div>
        <VueFlow
          :nodes="flowNodes"
          :edges="flowEdges"
          :fit-view-on-init="true"
          :min-zoom="0.15"
          :max-zoom="2"
          :nodes-draggable="false"
          :nodes-connectable="false"
          :elements-selectable="false"
          :zoom-on-scroll="true"
          :pan-on-drag="true"
          @node-click="onNodeClick"
          @pane-click="clearSelection"
        >
          <template #node-arch="nodeProps">
            <ArchNode v-bind="nodeProps" :dimmed="isDimmed(nodeProps.id)" />
          </template>
          <template #node-bus="nodeProps">
            <a-tooltip placement="top" :mouse-enter-delay="0.2" title="SSE 帧总线：后端边跑边推、前端边收边渲染（点击查看详情）">
              <div class="arch-bus" :class="{ dimmed: isDimmed(nodeProps.id) }">
                <Handle id="t-l1" type="target" :position="Position.Left" style="top: 3%" class="arch-handle" />
                <Handle id="t-l2" type="target" :position="Position.Left" style="top: 74%" class="arch-handle" />
                <Handle id="t-l3" type="target" :position="Position.Left" style="top: 85%" class="arch-handle" />
                <Handle id="t-l4" type="target" :position="Position.Left" style="top: 97%" class="arch-handle" />
                <div class="arch-bus-title">SSE 总线</div>
                <div class="arch-bus-sub">首帧 route_debug<br />伴随全程</div>
                <div v-if="nodeProps.data.problems?.length" class="arch-node-badge">{{ nodeProps.data.problems.join(' ') }}</div>
                <Handle id="s-r" type="source" :position="Position.Right" style="top: 3%" class="arch-handle" />
              </div>
            </a-tooltip>
          </template>
          <template #node-lane="nodeProps">
            <div class="arch-lane-label">{{ nodeProps.data.label }}</div>
          </template>
          <Background :gap="24" />
        </VueFlow>
      </div>
    </div>

    <a-drawer
      v-model:open="drawerOpen"
      :title="selectedNode?.data.label"
      placement="right"
      :width="420"
    >
      <template v-if="selectedNode">
        <a-tag :color="STATUS_META[selectedNode.data.status].color">
          {{ STATUS_META[selectedNode.data.status].label }}
        </a-tag>
        <span v-if="selectedNode.data.sub" class="drawer-sub">{{ selectedNode.data.sub }}</span>
        <p class="drawer-summary">{{ selectedNode.data.summary }}</p>
        <div class="drawer-section-title">机制</div>
        <ul class="drawer-list">
          <li v-for="(d, i) in selectedNode.data.details" :key="i">{{ d }}</li>
        </ul>
        <template v-if="selectedNode.data.anchors.length">
          <div class="drawer-section-title">源码锚点</div>
          <div v-for="a in selectedNode.data.anchors" :key="a" class="arch-anchor">{{ a }}</div>
        </template>
        <template v-if="selectedProblems.length">
          <div class="drawer-section-title">关联问题</div>
          <div
            v-for="p in selectedProblems"
            :key="p.id"
            class="arch-problem-card"
            :class="`sev-${p.severity}`"
            @click="toggleProblem(p.id)"
          >
            <div class="arch-problem-head">
              <span class="arch-problem-id">{{ p.id }}</span>
              <span class="arch-problem-title">{{ p.title }}</span>
            </div>
            <div class="arch-problem-desc always">{{ p.desc }}</div>
          </div>
        </template>
      </template>
    </a-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { VueFlow, useVueFlow, Handle, Position, type Edge, type Node, type NodeMouseEvent } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import ArchNode from './archmap/ArchNode.vue'
import { ARCH_EDGES, ARCH_NODES, ARCH_PROBLEMS, ARCH_REFERENCES, STATUS_META, type ArchNode as ArchNodeT } from './archmap/archData'

defineOptions({ name: 'ArchMapView' })

const { fitView, onInit } = useVueFlow()

onInit(() => {
  fitView({ padding: 0.04 })
})

const onlyProblems = ref(false)
const activeProblemId = ref<string | null>(null)
const drawerOpen = ref(false)
const selectedNode = ref<ArchNodeT | null>(null)
const showProblems = ref(true)
const showRefs = ref(false)

/** 四条意图线的节点集合：默认收起，点击「意图分级」或占位节点展开 */
const LINE_NODE_IDS = [
  'n-l0', 'n-inject', 'n-ks', 'n-pipe', 'n-table',
  'n-ts', 'n-es', 'n-sop', 'n-soproute', 'n-runner', 'n-gen', 'n-draft'
]
const linesExpanded = ref(false)

const COLLAPSED_NODE: Node = {
  id: 'n-lines-collapsed',
  type: 'arch',
  position: { x: 720, y: 450 },
  data: {
    label: '四条意图线（已收起）',
    sub: 'L0 / L1 / L2 / L3·L4 · 点击展开',
    status: 'ok',
    summary: '意图分级扇出的四条执行线：L0 闲聊 / L1 语义检索 / L2 查表 / L3·L4 SOP。点击本节点或「意图分级」展开。',
    details: [],
    anchors: []
  },
  draggable: false,
  selectable: true,
  connectable: false
}

const COLLAPSED_EDGES: Edge[] = [
  {
    id: 'ec1',
    source: 'n-level',
    target: 'n-lines-collapsed',
    label: 'L0–L4',
    type: 'smoothstep',
    style: { stroke: '#94a3b8', strokeWidth: 1.6 }
  },
  {
    id: 'ec2',
    source: 'n-lines-collapsed',
    target: 'n-loop',
    type: 'smoothstep',
    style: { stroke: '#94a3b8', strokeWidth: 1.6 }
  }
]

const problemNodeSet = computed(() => {
  const s = new Set<string>()
  for (const p of ARCH_PROBLEMS) for (const id of p.nodeIds) s.add(id)
  return s
})

const activeProblemNodeSet = computed(() => {
  if (!activeProblemId.value) return null
  const p = ARCH_PROBLEMS.find((x) => x.id === activeProblemId.value)
  return p ? new Set(p.nodeIds) : null
})

const isDimmed = (id: string) => {
  if (activeProblemNodeSet.value) return !activeProblemNodeSet.value.has(id)
  if (onlyProblems.value) return !problemNodeSet.value.has(id)
  return false
}

const flowNodes = computed<Node[]>(() => {
  const base: Node[] = ARCH_NODES
    .filter((n) => linesExpanded.value || !LINE_NODE_IDS.includes(n.id))
    .map((n) => {
      const data =
        n.id === 'n-level'
          ? {
              ...n.data,
              sub: linesExpanded.value
                ? '横向扇出四条执行线 · 点击收起 ▾'
                : 'L0–L4 · 点击展开四条线 ▸'
            }
          : n.data
      return {
        id: n.id,
        type: n.type,
        position: n.position,
        data,
        draggable: n.draggable,
        selectable: n.selectable,
        connectable: n.connectable,
        class: n.type === 'lane' ? 'lane-node' : undefined
      }
    })
  if (!linesExpanded.value) base.push(COLLAPSED_NODE)
  return base
})

const EDGE_STYLE: Record<string, { stroke: string; dash?: string; animated?: boolean }> = {
  flow: { stroke: '#94a3b8' },
  loop: { stroke: '#1677ff', dash: '6 4' },
  sse: { stroke: '#52c41a', animated: true },
  'sse-broken': { stroke: '#f5222d', animated: true },
  planned: { stroke: '#722ed1', dash: '5 5' }
}

const flowEdges = computed<Edge[]>(() => {
  const hidden = new Set(linesExpanded.value ? [] : LINE_NODE_IDS)
  const visible = ARCH_EDGES.filter((e) => !hidden.has(e.source) && !hidden.has(e.target))
  const mapped = visible.map((e) => {
    const st = EDGE_STYLE[e.kind]
    const dim = activeProblemNodeSet.value
      ? !activeProblemNodeSet.value.has(e.source) && !activeProblemNodeSet.value.has(e.target)
      : false
    return {
      id: e.id,
      source: e.source,
      target: e.target,
      sourceHandle: e.sourceHandle ?? 's-b',
      targetHandle: e.targetHandle ?? 't-t',
      label: e.label,
      type: 'smoothstep',
      animated: st.animated ?? false,
      class: dim ? 'edge-dimmed' : undefined,
      style: {
        stroke: st.stroke,
        strokeWidth: e.kind.startsWith('sse') ? 2 : 1.6,
        ...(st.dash ? { strokeDasharray: st.dash } : {})
      },
      labelStyle: { fontSize: 10, fill: st.stroke },
      labelBgStyle: { fill: 'var(--bg-primary, #f5f5f5)', fillOpacity: 0.85 }
    }
  })
  return linesExpanded.value ? mapped : [...mapped, ...COLLAPSED_EDGES]
})

const toggleLines = () => {
  linesExpanded.value = !linesExpanded.value
  nextTick(() => fitView({ duration: 300 }))
}

const onNodeClick = (ev: NodeMouseEvent) => {
  if (ev.node.id === 'n-level' || ev.node.id === 'n-lines-collapsed') {
    toggleLines()
    return
  }
  const node = ARCH_NODES.find((n) => n.id === ev.node.id)
  if (!node || node.type === 'lane') return
  selectedNode.value = node
  drawerOpen.value = true
}

const selectedProblems = computed(() => {
  const ids = selectedNode.value?.data.problems ?? []
  return ARCH_PROBLEMS.filter((p) => ids.includes(p.id))
})

const toggleProblem = (id: string) => {
  activeProblemId.value = activeProblemId.value === id ? null : id
  if (activeProblemId.value) {
    const p = ARCH_PROBLEMS.find((x) => x.id === activeProblemId.value)
    if (p && p.nodeIds.some((nid) => LINE_NODE_IDS.includes(nid)) && !linesExpanded.value) {
      toggleLines()
    }
  }
}

const clearSelection = () => {
  activeProblemId.value = null
}

const resetView = () => {
  activeProblemId.value = null
  onlyProblems.value = false
  fitView({ duration: 300 })
}
</script>

<style lang="less" scoped>
.arch-map-view {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--bg-primary, #f5f5f5);
}

.arch-body {
  flex: 1;
  min-height: 0;
  display: flex;
}

.arch-sidebar {
  width: 280px;
  flex-shrink: 0;
  overflow-y: auto;
  padding: 12px;
  border-right: 1px solid var(--border-color, #f0f0f0);
  background: var(--bg-secondary, #fff);
}

.arch-sidebar-title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 10px;
  color: var(--text-primary, rgba(0, 0, 0, 0.88));
}

.arch-collapse-title {
  cursor: pointer;
  user-select: none;
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 4px;

  &:hover { color: var(--primary-color, #1677ff); }
}

.arch-collapse-arrow {
  display: inline-block;
  font-size: 11px;
  transition: transform 0.15s;

  &.open { transform: rotate(90deg); }
}

.arch-ref-card {
  padding: 8px 10px;
  margin-bottom: 8px;
  border-radius: 6px;
  border: 1px solid var(--border-color, #f0f0f0);
  border-left: 3px solid #1677ff;
}

.arch-ref-name {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary, rgba(0, 0, 0, 0.88));
}

.arch-ref-link {
  font-size: 11px;
  font-weight: 400;
  white-space: nowrap;

  &.pending { color: var(--text-secondary, rgba(0, 0, 0, 0.45)); }
}

.arch-ref-row {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-secondary, rgba(0, 0, 0, 0.65));
}

.arch-ref-label {
  display: inline-block;
  margin-right: 6px;
  padding: 0 4px;
  border-radius: 3px;
  background: var(--bg-primary, #f5f5f5);
  font-size: 11px;
  color: var(--text-primary, rgba(0, 0, 0, 0.75));
}

.arch-problem-card {
  padding: 8px 10px;
  margin-bottom: 8px;
  border-radius: 6px;
  border: 1px solid var(--border-color, #f0f0f0);
  border-left-width: 3px;
  cursor: pointer;
  transition: background 0.2s;

  &:hover { background: var(--bg-primary, #f5f5f5); }
  &.active { background: var(--bg-primary, #f5f5f5); box-shadow: 0 0 0 1px currentColor; }

  &.sev-high { border-left-color: #f5222d; color: #f5222d; }
  &.sev-mid { border-left-color: #fa8c16; color: #fa8c16; }
  &.sev-low { border-left-color: #8c8c8c; color: #8c8c8c; }
}

.arch-problem-head {
  display: flex;
  align-items: center;
  gap: 6px;

  .arch-problem-id {
    font-weight: 700;
    font-size: 12px;
  }

  .arch-problem-title {
    font-size: 12px;
    font-weight: 600;
    color: var(--text-primary, rgba(0, 0, 0, 0.88));
  }
}

.arch-problem-desc {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-secondary, rgba(0, 0, 0, 0.65));
}

.arch-anchor {
  margin-top: 4px;
  font-family: monospace;
  font-size: 11px;
  color: var(--text-secondary, rgba(0, 0, 0, 0.55));
  word-break: break-all;
}

.arch-legend {
  position: absolute;
  right: 16px;
  bottom: 16px;
  z-index: 10;
  padding: 8px 12px;
  background: transparent;
}

.arch-legend-title {
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 6px;
  color: var(--text-primary, rgba(0, 0, 0, 0.88));
}

.arch-legend-item {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
  font-size: 12px;
  color: var(--text-secondary, rgba(0, 0, 0, 0.65));
}

.arch-legend-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}

.arch-legend-line {
  width: 22px;
  height: 0;
  border-top: 2px solid #94a3b8;

  &.sse { border-top-color: #52c41a; }
  &.loop { border-top-color: #1677ff; border-top-style: dashed; }
  &.planned { border-top-color: #722ed1; border-top-style: dashed; }
}

.arch-canvas {
  flex: 1;
  min-width: 0;
  position: relative;
}

.arch-float-controls {
  position: absolute;
  top: 12px;
  right: 16px;
  z-index: 10;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 6px 12px;
  border-radius: 6px;
  background: var(--bg-secondary, #fff);
  box-shadow: 0 1px 6px rgba(0, 0, 0, 0.15);
}

.arch-lane-label {
  font-size: 14px;
  font-weight: 700;
  letter-spacing: 6px;
  color: var(--text-secondary, rgba(0, 0, 0, 0.4));
  writing-mode: vertical-rl;
  white-space: nowrap;
}

.arch-bus {
  position: relative;
  width: 90px;
  height: 960px;
  border-radius: 10px;
  background: rgba(82, 196, 26, 0.08);
  border: 2px dashed #52c41a;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-top: 40px;
  cursor: pointer;
  transition: opacity 0.25s;

  &.dimmed {
    opacity: 0.18;
  }

  .arch-bus-title {
    writing-mode: vertical-rl;
    font-size: 15px;
    font-weight: 700;
    letter-spacing: 8px;
    color: #52c41a;
  }

  .arch-bus-sub {
    margin-top: 16px;
    writing-mode: vertical-rl;
    font-size: 11px;
    letter-spacing: 2px;
    color: var(--text-secondary, rgba(0, 0, 0, 0.45));
    line-height: 1.8;
  }

  .arch-handle {
    opacity: 0;
    pointer-events: none;
  }

  .arch-node-badge {
    position: absolute;
    bottom: -9px;
    left: 50%;
    transform: translateX(-50%);
    padding: 0 6px;
    border-radius: 8px;
    background: #f5222d;
    color: #fff;
    font-size: 10px;
    font-weight: 700;
    line-height: 16px;
  }
}

.drawer-sub {
  margin-left: 8px;
  font-size: 12px;
  color: var(--text-secondary, rgba(0, 0, 0, 0.45));
}

.drawer-summary {
  margin: 12px 0;
  font-size: 13px;
  line-height: 1.6;
}

.drawer-section-title {
  margin: 14px 0 6px;
  font-size: 13px;
  font-weight: 600;
}

.drawer-list {
  padding-left: 18px;
  font-size: 12.5px;
  line-height: 1.8;
  color: var(--text-secondary, rgba(0, 0, 0, 0.75));
}
</style>

<style lang="less">
.arch-canvas {
  .vue-flow {
    background: var(--bg-primary, #f5f5f5);
  }

  .lane-node {
    pointer-events: none;
    z-index: -1;
  }

  .vue-flow__edge.edge-dimmed {
    opacity: 0.12;
  }
}
</style>
