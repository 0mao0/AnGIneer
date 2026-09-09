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
 * 原因：docs-ui 的 index.ts 是 barrel，KnowledgeStats 已静态引入其中的 useKnowledgeParse；
 * 对同一个 barrel 再写 import() 时，rollup 认定「同一模块既静态又动态引入」而不再切分，
 * pdf.js / docx-preview / katex 会原样留在落地路由块里（实测如此）。中间隔一层
 * 只被动态引入的本组件，才能真正把它们拆进懒加载块。
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
