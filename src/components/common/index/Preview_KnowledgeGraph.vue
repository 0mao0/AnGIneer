<template>
  <div class="knowledge-graph">
    <div v-if="loading" class="graph-loading">
      <a-spin size="small" />
      <span>加载知识图谱...</span>
    </div>
    <a-empty v-else-if="error" :description="error" />
    <a-empty v-else-if="!entities.length" description="知识图谱为空，请先通过 API 导入数据" />
    <template v-else>
      <div ref="networkRef" class="network-container" />
      <div class="graph-overlay">
        <div class="graph-stats-bar">
          <span class="stat-item"><span class="stat-dot concept" />概念 {{ layerCounts.concept }}</span>
          <span class="stat-item"><span class="stat-dot condition" />条件 {{ layerCounts.condition }}</span>
          <span class="stat-item"><span class="stat-dot action" />动作 {{ layerCounts.action }}</span>
          <span class="stat-divider" />
          <span class="stat-item">关系 {{ relations.length }}</span>
        </div>
        <div class="graph-legend">
          <div class="legend-row">
            <span class="legend-label">边色：</span>
            <span class="legend-dot edge defines" />defines
            <span class="legend-dot edge requires" />requires
            <span class="legend-dot edge constrains" />constrains
            <span class="legend-dot edge conditions_on" />conditions_on
            <span class="legend-dot edge computes_from" />computes_from
            <span class="legend-dot edge verifies" />verifies
          </div>
        </div>
        <div class="graph-hint">拖拽平移 | 滚轮缩放 | 悬停查看详情</div>
      </div>
      <a-drawer
        v-if="selectedEntity"
        :open="drawerVisible"
        title="实体详情"
        placement="right"
        width="360"
        @close="drawerVisible = false"
      >
        <div class="entity-detail">
          <h3>{{ selectedEntity.name }}</h3>
          <p><strong>层级：</strong>{{ selectedEntity.layer }}</p>
          <p v-if="selectedEntity.aliases?.length"><strong>别名：</strong>{{ selectedEntity.aliases.join('、') }}</p>
          <p v-if="selectedEntity.source_clause"><strong>来源：</strong>{{ selectedEntity.source_clause }}</p>
          <h4>关联关系</h4>
          <div v-for="rel in selectedRelations" :key="rel.relation_id" class="rel-item">
            <span class="rel-dir">{{ rel.source === selectedEntity.name ? '→' : '←' }}</span>
            <span class="rel-type">{{ rel.type }}</span>
            <span class="rel-target">{{ rel.source === selectedEntity.name ? rel.target : rel.source }}</span>
            <span class="rel-conf">({{ rel.confidence }})</span>
          </div>
          <div v-if="!selectedRelations.length" class="no-rels">无关联关系</div>
        </div>
      </a-drawer>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'

interface GraphEntity {
  id: string
  name: string
  layer: string
  aliases: string[]
  source_clause?: string
}

interface GraphRelation {
  relation_id: string
  source: string
  target: string
  type: string
  confidence: number
  evidence?: string
  clause?: string
}

interface GraphSnapshot {
  stats: any
  entities: GraphEntity[]
  relations: GraphRelation[]
}

const loading = ref(true)
const error = ref('')
const entities = ref<GraphEntity[]>([])
const relations = ref<GraphRelation[]>([])
const networkRef = ref<HTMLElement | null>(null)
const network = ref<any>(null)
const drawerVisible = ref(false)
const selectedEntity = ref<GraphEntity | null>(null)
const selectedRelations = ref<GraphRelation[]>([])

const layerColors: Record<string, { border: string; bg: string; text: string }> = {
  concept: { border: '#2563eb', bg: '#bfdbfe', text: '#1e40af' },
  condition: { border: '#d97706', bg: '#fef3c7', text: '#92400e' },
  action: { border: '#059669', bg: '#a7f3d0', text: '#065f46' },
}

const edgeColors: Record<string, string> = {
  defines: '#8b5cf6',
  requires: '#ec4899',
  constrains: '#ef4444',
  conditions_on: '#f59e0b',
  computes_from: '#10b981',
  verifies: '#3b82f6',
}

const entityMap = computed(() => {
  const m = new Map<string, GraphEntity>()
  for (const e of entities.value) m.set(e.name, e)
  return m
})

const layerCounts = computed(() => {
  const c: Record<string, number> = { concept: 0, condition: 0, action: 0 }
  for (const e of entities.value) c[e.layer] = (c[e.layer] || 0) + 1
  return c
})

function buildVisNodes() {
  return entities.value.map((e, i) => {
    const c = layerColors[e.layer] || layerColors.concept
    const angle = (2 * Math.PI * i) / entities.value.length
    const radius = 180
    return {
      id: e.name,
      label: e.name.length > 12 ? e.name.slice(0, 12) + '...' : e.name,
      title: `${e.name} [${e.layer}]${e.aliases?.length ? '\n别名: ' + e.aliases.join(', ') : ''}`,
      shape: 'ellipse',
      size: e.layer === 'concept' ? 24 : e.layer === 'condition' ? 22 : 20,
      x: Math.cos(angle) * radius + (i % 7) * 20,
      y: Math.sin(angle) * radius + (i % 5) * 15,
      physics: true,
      mass: 2,
      font: { size: 12, color: '#1e293b', strokeWidth: 2, strokeColor: '#ffffff' },
      borderWidth: 2,
      color: {
        border: c.border,
        background: c.bg,
        highlight: { border: c.border, background: c.text },
      },
    }
  })
}

function buildVisEdges() {
  const seen = new Set<string>()
  return relations.value.map(r => {
    const key = `${r.source}|${r.target}|${r.type}`
    if (seen.has(key)) return null
    seen.add(key)
    return {
      id: r.relation_id,
      from: r.source,
      to: r.target,
      label: r.type,
      font: { size: 9, color: '#64748b', strokeWidth: 0, align: 'middle' },
      arrows: { to: { enabled: true, scaleFactor: 0.6 } },
      color: { color: edgeColors[r.type] || '#94a3b8', highlight: '#1e293b' },
      width: 1.5,
      smooth: { type: 'curvedCW', roundness: 0.1 },
      dashes: r.confidence < 0.5,
    }
  }).filter(Boolean)
}

function buildOptions() {
  return {
    autoResize: true,
    physics: {
      solver: 'forceAtlas2Based',
      forceAtlas2Based: {
        gravitationalConstant: -40,
        centralGravity: 0.005,
        springLength: 180,
        springConstant: 0.02,
        damping: 0.4,
      },
      stabilization: { iterations: 200, fit: true, updateInterval: 25 },
    },
    interaction: {
      hover: true,
      tooltipDelay: 100,
      zoomView: true,
      dragView: true,
      navigationButtons: false,
    },
    nodes: {
      borderWidth: 2,
      chosen: { node: (v: any, _id: string, _s: boolean, h: boolean) => { if (h) { v.borderWidth = 3; v.shadowSize = 6 } } },
    },
    edges: {
      smooth: { type: 'curvedCW', roundness: 0.1 },
      chosen: { edge: (v: any) => { v.width = 3 } },
    },
  }
}

async function fetchGraph() {
  loading.value = true
  error.value = ''
  try {
    const resp = await fetch('/api/graph/snapshot')
    if (!resp.ok) throw new Error(`API error: ${resp.status}`)
    const data: GraphSnapshot = await resp.json()
    entities.value = data.entities || []
    relations.value = data.relations || []
    if (!entities.value.length) error.value = '知识图谱为空'
  } catch (e: any) {
    error.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
}

function initNetwork() {
  if (!networkRef.value || !(window as any).vis || !entities.value.length) return
  const data = {
    nodes: new (window as any).vis.DataSet(buildVisNodes()),
    edges: new (window as any).vis.DataSet(buildVisEdges()),
  }
  network.value = new (window as any).vis.Network(networkRef.value, data, buildOptions())

  network.value.on('click', (params: any) => {
    if (!params.nodes?.length) return
    const name = params.nodes[0]
    const entity = entityMap.value.get(name)
    if (!entity) return
    selectedEntity.value = entity
    selectedRelations.value = relations.value.filter(r => r.source === name || r.target === name)
    drawerVisible.value = true
  })
}

const reload = async () => {
  await fetchGraph()
  await nextTick()
  if (network.value) {
    network.value.destroy()
    network.value = null
  }
  initNetwork()
}

onMounted(async () => {
  await fetchGraph()
  if (!(window as any).vis) {
    const script = document.createElement('script')
    script.src = 'https://unpkg.com/vis-network@9.1.9/dist/vis-network.min.js'
    script.onload = () => nextTick(() => initNetwork())
    document.head.appendChild(script)
  } else {
    await nextTick()
    initNetwork()
  }
})

onBeforeUnmount(() => {
  if (network.value) { network.value.destroy(); network.value = null }
})

defineExpose({ reload })
</script>

<style lang="less" scoped>
.knowledge-graph {
  position: relative;
  width: 100%;
  height: 100%;
  min-height: 400px;
}
.graph-loading {
  display: flex; align-items: center; justify-content: center; gap: 8px;
  height: 200px; color: #6b7280;
}
.network-container {
  width: 100%;
  height: 100%;
  min-height: 400px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
}
.graph-overlay {
  position: absolute;
  top: 8px; left: 8px; right: 8px;
  pointer-events: none;
}
.graph-stats-bar {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 4px 10px;
  background: rgba(255,255,255,0.92);
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  font-size: 12px;
  pointer-events: auto;
}
.stat-item { display: inline-flex; align-items: center; gap: 3px; }
.stat-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; }
.stat-dot.concept { background: #2563eb; }
.stat-dot.condition { background: #d97706; }
.stat-dot.action { background: #059669; }
.stat-divider { width: 1px; height: 14px; background: #d1d5db; margin: 0 2px; }
.graph-legend {
  margin-top: 4px;
  padding: 4px 10px;
  background: rgba(255,255,255,0.92);
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  font-size: 11px;
  display: inline-block;
  pointer-events: auto;
}
.legend-row { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; }
.legend-label { color: #6b7280; margin-right: 2px; }
.legend-dot.edge { display: inline-block; width: 16px; height: 3px; border-radius: 1px; }
.legend-dot.edge.defines { background: #8b5cf6; }
.legend-dot.edge.requires { background: #ec4899; }
.legend-dot.edge.constrains { background: #ef4444; }
.legend-dot.edge.conditions_on { background: #f59e0b; }
.legend-dot.edge.computes_from { background: #10b981; }
.legend-dot.edge.verifies { background: #3b82f6; }
.graph-hint {
  margin-top: 4px;
  padding: 2px 8px;
  background: rgba(255,255,255,0.85);
  border: 1px solid #e5e7eb;
  border-radius: 4px;
  font-size: 11px;
  color: #9ca3af;
  display: inline-block;
  pointer-events: auto;
}
.entity-detail {
  h3 { margin-bottom: 8px; }
  h4 { margin: 12px 0 6px; font-size: 14px; }
  p { margin: 4px 0; font-size: 13px; }
}
.rel-item {
  display: flex; align-items: center; gap: 6px;
  padding: 4px 0; font-size: 13px;
  border-bottom: 1px solid #f3f4f6;
}
.rel-dir { color: #9ca3af; font-size: 12px; }
.rel-type { color: #6366f1; font-weight: 500; min-width: 80px; }
.rel-target { flex: 1; }
.rel-conf { color: #9ca3af; font-size: 11px; }
.no-rels { color: #9ca3af; font-size: 13px; padding: 8px 0; }
</style>
