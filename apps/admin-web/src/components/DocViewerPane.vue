<template>
  <PDFParsedWorkspace
    ref="workspaceRef"
    :node="node"
    :content="content"
    :structured-items="structuredItems"
    :graph-data="graphData"
    :render-pdf-path="renderPdfPath"
    :dark="dark"
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
 */
import { ref } from 'vue'
import { PDFParsedWorkspace } from '@angineer/docs-ui'
import type { KnowledgeTreeNode } from '@angineer/docs-ui'

defineProps<{
  node: KnowledgeTreeNode
  content: string
  structuredItems: any[]
  graphData: { nodes: any[]; edges: any[] } | null
  renderPdfPath: string
  dark: boolean
}>()

const workspaceRef = ref<InstanceType<typeof PDFParsedWorkspace> | null>(null)

defineExpose({
  setActiveLinkedItem: (id: string) => workspaceRef.value?.setActiveLinkedItem(id),
})
</script>
