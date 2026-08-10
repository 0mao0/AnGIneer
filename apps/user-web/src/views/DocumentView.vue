<template>
  <div class="document-view">
    <div class="doc-content">
      <div v-if="loading" class="loading">
        <a-spin size="large" />
      </div>
      <EmptyState
        v-else-if="loadError"
        variant="error"
        title="文档加载失败"
        :description="loadError"
        cta-text="重试"
        @cta-click="loadDocument"
      />
      <PDFParsedWorkspace
        v-else-if="document && isPdfView && pdfUrl"
        :node="{ key: currentDocId, title: document.title, status: 'completed', isFolder: false, visible: true, filePath: pdfFilePath }"
        :content="document.content"
        :render-pdf-path="pdfFilePath"
        :graph-data="graphData"
        :graph-data-full-loaded="graphDataFullLoaded"
        :on-load-full-graph-data="loadGraphData"
        :side-panel-default-open="true"
        :default-parsed-tab="'Preview_IndexTree'"
      />
      <Preview_Markdown
        v-else-if="document"
        :content="document.content"
        :active-line-range="activeLineRange"
      />
      <EmptyState
        v-else
        variant="empty"
        title="未打开文档"
        description="从左侧知识库选择一个文档开始查看"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { message } from 'ant-design-vue'
import { PDFParsedWorkspace, Preview_Markdown } from '@angineer/docs-ui'
import { EmptyState } from '@angineer/ui-kit'
import { knowledgeApi } from '@/api/knowledge'

const props = defineProps<{
  libraryId?: string
  docId?: string
  title?: string
  sectionPath?: string
  targetId?: string
  pageIdx?: number
  snippet?: string
}>()

const route = useRoute()
const loading = ref(true)
const loadError = ref<string>('')
const document = ref<{ id: string; title: string; content: string } | null>(null)
const activeLineRange = ref<{ start: number; end: number } | null>(null)
const isPdfView = ref(false)
const pdfUrl = ref('')
const pdfFilePath = ref('')
const pdfPage = ref(1)
const graphData = ref<{ nodes: any[]; edges: any[] } | null>(null)
const graphDataFullLoaded = ref(false)
const graphDataLoading = ref(false)
const currentDocId = ref('')

/** 按引用定位参数在 markdown 中找原文位置（sectionPath 优先，snippet 兜底） */
const locateInContent = (content: string): { start: number; end: number } | null => {
  const lines = content.split('\n')
  const path = String(props.sectionPath || '').trim()
  const segments = path
    .split(/[\/>]/)
    .map(segment => segment.trim())
    .filter(Boolean)
  const needle = segments[segments.length - 1] || String(props.snippet || '').slice(0, 20)
  if (!needle) return null
  for (let index = 0; index < lines.length; index += 1) {
    if (lines[index].includes(needle)) {
      return { start: index + 1, end: index + 1 }
    }
  }
  return null
}

const loadDocument = async () => {
  const docId = (props.docId || route.params.id || '') as string
  const libraryId = props.libraryId || 'default'
  if (!docId) {
    loading.value = false
    document.value = null
    return
  }
  loading.value = true
  currentDocId.value = docId
  graphData.value = null
  graphDataFullLoaded.value = false
  graphDataLoading.value = false
  loadError.value = ''
  try {
    const result = await knowledgeApi.getDocument(libraryId, docId) as {
      content?: string
      title?: string
      storage?: { render_pdf?: string }
      graph_data?: { nodes: any[]; edges: any[] } | null
    }
    document.value = {
      id: docId,
      title: props.title || result?.title || `文档 ${docId}`,
      content: result?.content || ''
    }
    graphData.value = result?.graph_data || null
    graphDataFullLoaded.value = Boolean(graphData.value?.nodes?.length)
    const renderPdf = String(result?.storage?.render_pdf || '').trim()
    if (renderPdf) {
      isPdfView.value = true
      pdfFilePath.value = renderPdf
      pdfUrl.value = `/api/files?path=${encodeURIComponent(renderPdf)}`
      pdfPage.value = Math.max(1, Number(props.pageIdx || 0) + 1)
    } else {
      isPdfView.value = false
      pdfUrl.value = ''
      pdfFilePath.value = ''
      activeLineRange.value = locateInContent(document.value.content)
    }
  } catch (err) {
    const e = err as Error
    loadError.value = e.message || '文档加载失败'
    message.error(loadError.value)
    document.value = null
    activeLineRange.value = null
    isPdfView.value = false
    pdfUrl.value = ''
    pdfFilePath.value = ''
  } finally {
    loading.value = false
  }
}

const loadGraphData = async () => {
  const docId = currentDocId.value
  if (!docId || graphDataLoading.value || graphDataFullLoaded.value) return
  graphDataLoading.value = true
  try {
    const result = await knowledgeApi.getDocBlocksGraph('default', docId) as any
    const payload = result?.data || result || null
    graphData.value = payload?.nodes?.length ? payload : null
    graphDataFullLoaded.value = true
  } catch (error) {
    console.warn('[DocumentView] 加载文档图谱数据失败:', error)
    graphDataFullLoaded.value = true
  } finally {
    graphDataLoading.value = false
  }
}

watch(() => [props.pageIdx, props.targetId, props.sectionPath], () => {
  if (isPdfView.value && pdfUrl.value) {
    pdfPage.value = Math.max(1, Number(props.pageIdx || 0) + 1)
  }
})

watch(
  () => [props.docId, props.libraryId, props.sectionPath, props.snippet],
  () => {
    loadDocument()
  }
)
onMounted(loadDocument)
</script>

<style lang="less" scoped>
.document-view {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--bg-secondary);
}

.doc-content {
  flex: 1;
  overflow-y: auto;
}

.loading {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
