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
        ref="pdfWorkspaceRef"
        v-else-if="document && isPdfView && pdfUrl"
        :node="{ key: currentDocId, title: document.title, status: 'completed', isFolder: false, visible: true, filePath: pdfFilePath }"
        :library-id="props.libraryId || authStore.libraryId || 'default'"
        :dark="isDark"
        :content="document.content"
        :render-pdf-path="pdfFilePath"
        :graph-data="graphData"
        :graph-data-full-loaded="graphDataFullLoaded"
        :graph-data-loading="graphDataLoading"
        :on-load-full-graph-data="loadGraphData"
        :side-panel-open="sidePanelOpen"
        :side-panel-default-open="false"
        :default-parsed-tab="'Preview_Markdown'"
        @update:side-panel-open="onSidePanelOpenChange"
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
        description="点击回答里的引用，可在这里溯源定位原文"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch, nextTick, computed } from 'vue'
import { message } from 'ant-design-vue'
import {
  PDFParsedWorkspace,
  Preview_Markdown,
  useKnowledgeCitation,
  type KnowledgeChatCitation,
} from '@angineer/docs-ui'
import { EmptyState, useTheme } from '@angineer/ui-kit'
import { knowledgeApi } from '@/api/knowledge'
import { useAuthStore } from '@/stores/auth'

// sidePanelOpen 必须显式默认 undefined：Vue 对 Boolean 类型 prop 缺省会强转 false，
// 「宿主没传（想本地受控）」会被误判成「宿主强制关闭」→ 展开键永远点不开（2026-10-27 实踩）
const props = withDefaults(defineProps<{
  libraryId?: string
  docId?: string
  title?: string
  sectionPath?: string
  targetId?: string
  pageIdx?: number
  snippet?: string
  sidePanelOpen?: boolean
}>(), {
  sidePanelOpen: undefined,
})

const { isDark } = useTheme()
const authStore = useAuthStore()
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
const pdfWorkspaceRef = ref<InstanceType<typeof PDFParsedWorkspace> | null>(null)
const { resolveCitationTargetNode, applyCitationToWorkspace } = useKnowledgeCitation()

/**
 * 右侧解析对比面板默认收起：整本文档图谱（单篇可达十几 MB、大书要几十秒）
 * 只在用户点工具栏「展开解析对比」后才拉；打开 PDF 本身不触发图谱加载。
 */
const localSidePanelOpen = ref(false)
const sidePanelOpen = computed(() => props.sidePanelOpen ?? localSidePanelOpen.value)
const onSidePanelOpenChange = (value: boolean) => {
  if (props.sidePanelOpen !== undefined) return
  localSidePanelOpen.value = value
}

const pendingFocusCitation = ref<{ docId: string; citation: KnowledgeChatCitation } | null>(null)

/** 直接联动入口：App 层点参考依据后直接调用，复用知识库工作区的定位逻辑 */
const focusCitation = (citation: KnowledgeChatCitation) => {
  const docId = String(citation.reference?.docId || citation.doc_id || currentDocId.value || '').trim()
  pendingFocusCitation.value = { docId, citation }
  void flushPendingCitation()
}

const flushPendingCitation = async () => {
  const pending = pendingFocusCitation.value
  const workspace = pdfWorkspaceRef.value
  if (!pending || !workspace) return
  if (pending.docId && currentDocId.value && pending.docId !== currentDocId.value) return
  const citation = pending.citation
  if (!String(citation.reference?.targetId || citation.target_id || '').trim()) {
    pendingFocusCitation.value = null
    return
  }
  const resolvedNode = resolveCitationTargetNode(citation, graphData.value?.nodes || [])
  await applyCitationToWorkspace(citation, graphData.value?.nodes || [], workspace)
  // 图谱还没就绪时保留 pending，等 graphDataFullLoaded 后再精确定位一次
  if (resolvedNode || graphDataFullLoaded.value) {
    pendingFocusCitation.value = null
  }
}

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

type DocumentPayload = {
  content?: string | null
  title?: string
  storage?: { render_pdf?: string }
  graph_data?: { nodes: any[]; edges: any[] } | null
}

/** 应用文档元信息：有 render_pdf 切 PDF 视图，否则走 markdown 预览并定位行 */
const applyDocumentPayload = (payload: DocumentPayload | null, docId: string) => {
  document.value = {
    id: docId,
    title: props.title || payload?.title || `文档 ${docId}`,
    content: payload?.content || ''
  }
  graphData.value = payload?.graph_data || null
  graphDataFullLoaded.value = Boolean(graphData.value?.nodes?.length)
  const renderPdf = String(payload?.storage?.render_pdf || '').trim()
  if (renderPdf) {
    isPdfView.value = true
    pdfFilePath.value = renderPdf
    pdfUrl.value = `/api/files?path=${encodeURIComponent(renderPdf)}`
    pdfPage.value = Math.max(1, Number(props.pageIdx || 0) + 1)
    if (props.targetId) {
      void applyCitationFocus()
    }
    return
  }
  isPdfView.value = false
  pdfUrl.value = ''
  pdfFilePath.value = ''
  activeLineRange.value = locateInContent(document.value.content)
}

/**
 * PDF 首屏不阻塞在全文上：轻量接口拿到 render_pdf 后立刻发 PDF 请求，
 * content.md（大文档可到 MB 级）在后台补进解析面板，不参与首屏时序。
 */
const loadFullDocumentInBackground = async (libraryId: string, docId: string) => {
  try {
    const result = await knowledgeApi.getDocument(libraryId, docId) as DocumentPayload
    if (currentDocId.value !== docId) return
    if (document.value) document.value.content = result?.content || ''
    if (result?.graph_data) {
      graphData.value = result.graph_data
      graphDataFullLoaded.value = Boolean(result.graph_data?.nodes?.length)
    }
  } catch (error) {
    console.warn('[DocumentView] 后台加载文档全文失败:', error)
  }
}

const loadDocument = async () => {
  const docId = (props.docId || '') as string
  const libraryId = props.libraryId || authStore.libraryId || 'default'
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
    const light = await knowledgeApi.getDocument(libraryId, docId, { includeContent: false }) as DocumentPayload
    if (String(light?.storage?.render_pdf || '').trim()) {
      applyDocumentPayload(light, docId)
      void loadFullDocumentInBackground(libraryId, docId)
      return
    }
    // 非 PDF 的 markdown 预览仍需要全文，走一次完整加载
    const result = await knowledgeApi.getDocument(libraryId, docId) as DocumentPayload
    applyDocumentPayload(result, docId)
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
    await nextTick()
    void flushPendingCitation()
  }
}

const loadGraphData = async () => {
  const docId = currentDocId.value
  if (!docId || graphDataLoading.value || graphDataFullLoaded.value) return
  graphDataLoading.value = true
  try {
    const libraryId = props.libraryId || authStore.libraryId || 'default'
    const result = await knowledgeApi.getDocBlocksGraph(libraryId, docId) as any
    const payload = result?.data || result || null
    graphData.value = payload?.nodes?.length ? payload : null
    graphDataFullLoaded.value = true
  } catch (error) {
    // 失败不能记成「已加载完」：否则收起再展开也不会重试，面板永远缺定位框
    console.warn('[DocumentView] 加载文档图谱数据失败:', error)
  } finally {
    graphDataLoading.value = false
  }
}

/** 兼容历史 tab 携带的定位参数：与直接引用走同一条定位队列 */
const applyCitationFocus = () => {
  const targetId = String(props.targetId || '').trim()
  if (!targetId) return
  focusCitation({
    target_id: targetId,
    section_path: props.sectionPath,
    page_idx: props.pageIdx,
    snippet: props.snippet,
    score: 0,
    reference: {
      targetId,
      sectionPath: props.sectionPath,
      pageIdx: props.pageIdx,
      snippet: props.snippet,
    },
  })
}

watch(() => [props.pageIdx, props.targetId, props.sectionPath, props.snippet], () => {
  if (!document.value) return
  if (isPdfView.value && pdfUrl.value) {
    if (props.targetId) {
      void applyCitationFocus()
    }
  } else {
    activeLineRange.value = locateInContent(document.value.content)
  }
})

// 完整图谱就绪后再定位，保证目标块在 linkedHighlights 中可解析
watch(() => graphDataFullLoaded.value, () => {
  void flushPendingCitation()
})

// 工作区（含 PDF 画布）挂载可能晚于 loadDocument 收尾的 flush 一拍：
// 组件一出现就把积压的 pending 放出来，首击定位不再依赖图谱是否就绪
watch(pdfWorkspaceRef, workspace => {
  if (workspace) void flushPendingCitation()
})

watch(
  () => [props.docId, props.libraryId],
  () => {
    loadDocument()
  }
)
onMounted(loadDocument)

defineExpose({
  focusCitation,
})
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
