<template>
  <div class="knowledge-graph">
    <div class="graph-toolbar">
      <a-radio-group v-if="libraryId && docId" :value="viewMode" size="small" @change="onViewModeChange">
        <a-radio-button value="doc">本文档</a-radio-button>
        <a-radio-button value="global">全局</a-radio-button>
      </a-radio-group>
      <div class="graph-toolbar-actions">
        <a-button v-if="showExtractButton && !loading" type="primary" size="small" :loading="extractLoading" @click="handleExtract">
          提取图谱
        </a-button>
        <a-button v-if="showDeepExtractButton && !deepExtractLoading" size="small" :loading="deepExtractLoading" @click="handleDeepExtract">
          AI 深度提取
        </a-button>
      </div>
    </div>
    <div v-if="loading" class="graph-loading">
      <a-spin size="small" />
      <span>加载知识图谱...</span>
    </div>
    <div v-else-if="!entities.length && viewMode === 'doc' && !extractLoading && !deepExtractLoading" class="graph-empty">
      <div class="graph-empty-text">本文档尚未提取图谱</div>
      <div class="graph-empty-desc">点击下方按钮快速扫描文档中的工程术语，建立基础实体关系</div>
    </div>
    <div v-else-if="!entities.length && viewMode === 'global'" class="graph-empty">
      <div class="graph-empty-text">暂无全局图谱数据</div>
    </div>
    <template v-else-if="entities.length">
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
          <div class="legend-item"><span class="legend-dot defines" />定义</div>
          <div class="legend-item"><span class="legend-dot requires" />需要</div>
          <div class="legend-item"><span class="legend-dot constrains" />约束</div>
          <div class="legend-item"><span class="legend-dot conditions_on" />条件</div>
          <div class="legend-item"><span class="legend-dot computes_from" />计算</div>
          <div class="legend-item"><span class="legend-dot verifies" />验证</div>
        </div>
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
          <div v-for="rel in selectedRelations" :key="rel.relation_id" class="rel-item" @click="openEdgeDetail(rel)">
            <span class="rel-dir">{{ rel.source === selectedEntity.name ? '→' : '←' }}</span>
            <span class="rel-type">{{ relationTypeLabel[rel.type] || rel.type }}</span>
            <span class="rel-target">{{ rel.source === selectedEntity.name ? rel.target : rel.source }}</span>
            <span class="rel-conf">({{ rel.confidence }})</span>
            <div v-if="rel.evidence" class="rel-evidence-preview">{{ rel.evidence.slice(0, 60) }}...</div>
          </div>
          <div v-if="!selectedRelations.length" class="no-rels">无关联关系</div>
        </div>
      </a-drawer>
      <a-drawer
        v-if="selectedEdge"
        :open="edgeDrawerVisible"
        title="关系详情"
        placement="right"
        width="400"
        @close="edgeDrawerVisible = false"
      >
        <div class="edge-detail">
          <div class="edge-triple">
            <span class="edge-source">{{ selectedEdge.source }}</span>
            <span class="edge-arrow">&rarr;</span>
            <span class="edge-type">{{ relationTypeLabel[selectedEdge.type] || selectedEdge.type }}</span>
            <span class="edge-arrow">&rarr;</span>
            <span class="edge-target">{{ selectedEdge.target }}</span>
          </div>
          <p><strong>置信度：</strong>{{ selectedEdge.confidence }}</p>
          <p v-if="selectedEdge.clause"><strong>来源条文：</strong>{{ selectedEdge.clause }}</p>
          <div v-if="selectedEdge.evidence" class="edge-evidence-section">
            <h4>验证详情 (V1/V2/V3)</h4>
            <pre class="edge-evidence">{{ selectedEdge.evidence }}</pre>
          </div>
          <div v-else class="edge-evidence-empty">该关系尚无验证记录（规则抽取或置信度低于验证阈值）</div>
        </div>
      </a-drawer>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'

const props = withDefaults(defineProps<{
  libraryId?: string
  docId?: string
}>(), {
  libraryId: '',
  docId: '',
})

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

interface BuildResponse {
  packets_processed: number
  total_entities_found: number
  total_relations_added: number
  snapshot: GraphSnapshot
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
const edgeDrawerVisible = ref(false)
const selectedEdge = ref<GraphRelation | null>(null)
const extractLoading = ref(false)
const deepExtractLoading = ref(false)
const viewMode = ref<'doc' | 'global'>('doc')
const hasExtracted = ref(false)
const hasDeepExtracted = ref(false)

const showExtractButton = computed(() => props.libraryId && props.docId && !hasExtracted.value)
const showDeepExtractButton = computed(() => props.libraryId && props.docId && hasExtracted.value && !hasDeepExtracted.value)

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

const relationTypeLabel: Record<string, string> = {
  defines: '定义',
  requires: '需要',
  constrains: '约束',
  conditions_on: '条件',
  computes_from: '计算',
  verifies: '验证',
}

const entityMap = computed(() => {
  const m = new Map<string, GraphEntity>()
  for (const e of entities.value) m.set(e.name, e)
  return m
})

const relationMap = computed(() => {
  const m = new Map<string, GraphRelation>()
  for (const r of relations.value) m.set(r.relation_id, r)
  return m
})

const layerCounts = computed(() => {
  const c: Record<string, number> = { concept: 0, condition: 0, action: 0 }
  for (const e of entities.value) c[e.layer] = (c[e.layer] || 0) + 1
  return c
})

function buildSnapshotUrl() {
  if (viewMode.value === 'doc' && props.libraryId && props.docId) {
    return `/api/graph/snapshot?library_id=${props.libraryId}&doc_id=${props.docId}`
  }
  return '/api/graph/snapshot'
}

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
      label: relationTypeLabel[r.type] || r.type,
      font: { size: 9, color: '#64748b', strokeWidth: 0, align: 'middle' },
      arrows: { to: { enabled: false } },
      color: { color: edgeColors[r.type] || '#94a3b8', highlight: '#1e293b' },
      width: 1.5,
      dashes: r.confidence < 0.5,
    }
  }).filter(Boolean)
}

function buildOptions() {
  return {
    autoResize: true,
    physics: {
      solver: 'barnesHut',
      barnesHut: {
        gravitationalConstant: -3000,
        centralGravity: 0.3,
        springLength: 200,
        springConstant: 0.03,
        damping: 0.3,
        avoidOverlap: 0.5,
      },
      stabilization: { iterations: 50, fit: true, updateInterval: 50 },
    },
    interaction: {
      hover: true,
      tooltipDelay: 200,
      zoomView: true,
      dragView: true,
      navigationButtons: false,
      hideEdgesOnDrag: true,
      hideEdgesOnZoom: true,
    },
    nodes: {
      borderWidth: 2,
      borderWidthSelected: 3,
    },
    edges: {
      smooth: false,
      width: 1.5,
    },
    configure: { enabled: false },
  }
}

async function fetchGraph() {
  loading.value = true
  error.value = ''
  try {
    const url = buildSnapshotUrl()
    const resp = await fetch(url)
    if (!resp.ok) throw new Error(`API error: ${resp.status}`)
    const data: GraphSnapshot = await resp.json()
    entities.value = data.entities || []
    relations.value = data.relations || []
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

  network.value.once('stabilizationIterationsDone', () => {
    network.value.setOptions({ physics: false })
  })

  network.value.on('click', (params: any) => {
    if (params.nodes?.length) {
      const name = params.nodes[0]
      const entity = entityMap.value.get(name)
      if (!entity) return
      selectedEntity.value = entity
      selectedRelations.value = relations.value.filter(r => r.source === name || r.target === name)
      drawerVisible.value = true
      edgeDrawerVisible.value = false
    } else if (params.edges?.length) {
      const relId = params.edges[0]
      const rel = relationMap.value.get(relId)
      if (!rel) return
      openEdgeDetail(rel)
    }
  })

  network.value.on('dragStart', () => {
    network.value.setOptions({ physics: { enabled: true, stabilization: false } })
  })

  network.value.on('dragEnd', () => {
    setTimeout(() => {
      if (network.value) network.value.setOptions({ physics: false })
    }, 500)
  })
}

async function handleExtract() {
  if (!props.libraryId || !props.docId) return
  extractLoading.value = true
  try {
    const resp = await fetch('/api/graph/build/from-doc', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        library_id: props.libraryId,
        doc_id: props.docId,
        enable_llm_extraction: false,
      }),
    })
    if (!resp.ok) throw new Error(`Extract error: ${resp.status}`)
    const data: BuildResponse = await resp.json()
    hasExtracted.value = true
    entities.value = data.snapshot.entities || []
    relations.value = data.snapshot.relations || []
    await rebuildNetwork()
  } catch (e: any) {
    error.value = e.message || '提取失败'
  } finally {
    extractLoading.value = false
  }
}

async function handleDeepExtract() {
  if (!props.libraryId || !props.docId) return
  deepExtractLoading.value = true
  try {
    const resp = await fetch('/api/graph/build/from-doc', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        library_id: props.libraryId,
        doc_id: props.docId,
        enable_llm_extraction: true,
      }),
    })
    if (!resp.ok) throw new Error(`Deep extract error: ${resp.status}`)
    const data: BuildResponse = await resp.json()
    hasDeepExtracted.value = true
    entities.value = data.snapshot.entities || []
    relations.value = data.snapshot.relations || []
    await rebuildNetwork()
  } catch (e: any) {
    error.value = e.message || '深度提取失败'
  } finally {
    deepExtractLoading.value = false
  }
}

function openEdgeDetail(rel: GraphRelation) {
  selectedEdge.value = rel
  edgeDrawerVisible.value = true
  drawerVisible.value = false
}

async function rebuildNetwork() {
  await nextTick()
  if (network.value) {
    network.value.destroy()
    network.value = null
  }
  initNetwork()
}

function onViewModeChange(e: any) {
  viewMode.value = e.target.value
  fetchGraph()
}

watch(() => [props.libraryId, props.docId], async () => {
  hasExtracted.value = false
  hasDeepExtracted.value = false
  viewMode.value = 'doc'
  await fetchGraph()
})

const reload = async () => {
  await fetchGraph()
  await rebuildNetwork()
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
.graph-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 8px;
  gap: 8px;
}
.graph-toolbar-actions {
  display: flex;
  gap: 6px;
}
.graph-loading {
  display: flex; align-items: center; justify-content: center; gap: 8px;
  height: 200px; color: #6b7280;
}
.graph-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 200px;
  gap: 8px;
  color: #6b7280;
}
.graph-empty-text {
  font-size: 15px;
  font-weight: 500;
  color: #374151;
}
.graph-empty-desc {
  font-size: 12px;
  color: #9ca3af;
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
  top: 40px; bottom: 8px; left: 8px; right: 8px;
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
  position: absolute;
  bottom: 8px; left: 8px;
  padding: 6px 10px;
  background: rgba(255,255,255,0.92);
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  font-size: 11px;
  display: flex;
  flex-direction: column;
  gap: 3px;
  pointer-events: auto;
}
.legend-item {
  display: flex;
  align-items: center;
  gap: 5px;
}
.legend-dot {
  display: inline-block;
  width: 16px;
  height: 3px;
  border-radius: 1px;
}
.legend-dot.defines { background: #8b5cf6; }
.legend-dot.requires { background: #ec4899; }
.legend-dot.constrains { background: #ef4444; }
.legend-dot.conditions_on { background: #f59e0b; }
.legend-dot.computes_from { background: #10b981; }
.legend-dot.verifies { background: #3b82f6; }
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
  display: flex; align-items: flex-start; gap: 6px;
  padding: 4px 0; font-size: 13px;
  border-bottom: 1px solid #f3f4f6;
  cursor: pointer; flex-wrap: wrap;
}
.rel-item:hover { background: #f8fafc; }
.rel-dir { color: #9ca3af; font-size: 12px; }
.rel-type { color: #6366f1; font-weight: 500; min-width: 80px; }
.rel-target { flex: 1; }
.rel-conf { color: #9ca3af; font-size: 11px; }
.rel-evidence-preview { width: 100%; color: #6b7280; font-size: 11px; padding-left: 18px; }
.no-rels { color: #9ca3af; font-size: 13px; padding: 8px 0; }
.edge-detail {
  h4 { margin: 12px 0 6px; font-size: 14px; }
  p { margin: 4px 0; font-size: 13px; }
}
.edge-triple {
  display: flex; align-items: center; gap: 6px;
  padding: 8px 0; font-size: 14px; flex-wrap: wrap;
}
.edge-source { font-weight: 600; color: #1e293b; }
.edge-arrow { color: #94a3b8; }
.edge-type { color: #6366f1; font-weight: 500; padding: 1px 6px; border-radius: 4px; background: #eef2ff; }
.edge-target { font-weight: 600; color: #1e293b; }
.edge-evidence-section { margin-top: 12px; }
.edge-evidence {
  background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px;
  padding: 12px; font-size: 12px; line-height: 1.6;
  white-space: pre-wrap; max-height: 400px; overflow-y: auto;
}
.edge-evidence-empty { color: #9ca3af; font-size: 13px; padding: 12px 0; }
</style>
