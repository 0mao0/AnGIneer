<template>
  <PDFParsedWorkspace
    ref="workspaceRef"
    :node="node"
    :content="content"
    :structured-items="structuredItems"
    :graph-data="graphData"
    :render-pdf-path="renderPdfPath"
    :dark="dark"
    :library-id="resolvedLibraryId"
    :on-load-graph-snapshot="loadGraphSnapshot"
    :side-panel-default-open="false"
  />
</template>

<script setup lang="ts">
/**
 * 「查看」抽屉里预览面板的薄包装。存在的唯一目的：让 KnowledgeStats 能把它动态引入。
 *
 * KnowledgeStats 已改为子路径导入 useKnowledgeParse（不再引 docs-ui barrel），但预览组件仍须留在
 * 懒加载块里：落地路由一旦静态引到 PDF_Viewer / OfficePreview，pdf.js / docx-preview / katex
 * 就会跟着进落地路由块。
 *
 * 知识图谱能力在本薄包装里补齐（只读）：只传「读快照」不传「构建图谱」——
 * 图谱页签恢复可见，「提取图谱 / AI 深度提取」两个写按钮随之隐藏（业主 2026-10-16 定①只读化）。
 * 实现放这里而非 KnowledgeStats：调用代码随懒加载块走，不给落地路由块增重。
 */
import { computed, ref } from 'vue'
import { PDFParsedWorkspace } from '@angineer/docs-ui'
import type { KnowledgeTreeNode } from '@angineer/docs-ui'
import { knowledgeApi } from '@/api/knowledge'

const props = defineProps<{
  node: KnowledgeTreeNode
  content: string
  structuredItems: any[]
  graphData: { nodes: any[]; edges: any[] } | null
  renderPdfPath: string
  dark: boolean
  /** 当前知识库；节点自带 libraryId 时以节点为准，兜底 default（与页面其它取数口径一致） */
  libraryId?: string
}>()

const resolvedLibraryId = computed(() =>
  String((props.node as any)?.libraryId || '').trim() || props.libraryId || 'default',
)

/** 只读图谱快照（GET /graph/snapshot）：doc 视图按当前库+当前文档取数 */
const loadGraphSnapshot = (params: {
  libraryId?: string
  docId?: string
  viewMode?: 'doc' | 'global'
}) =>
  knowledgeApi.getGraphSnapshot({
    ...params,
    libraryId: params.libraryId || resolvedLibraryId.value,
    docId: params.docId || String(props.node?.key || ''),
  })

const workspaceRef = ref<InstanceType<typeof PDFParsedWorkspace> | null>(null)

defineExpose({
  setActiveLinkedItem: (id: string) => workspaceRef.value?.setActiveLinkedItem(id),
})
</script>
