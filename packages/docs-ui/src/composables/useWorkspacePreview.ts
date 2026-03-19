import { computed, ref, watch, type ComputedRef } from 'vue'
import type { KnowledgeTreeNode } from '../types/tree'
import { getFileExtension, getPreviewFileType } from '../utils/knowledge'

interface GraphDataLike {
  nodes: any[]
  edges: any[]
}

interface UseWorkspacePreviewOptions {
  node: ComputedRef<KnowledgeTreeNode>
  filePath: ComputedRef<string>
  graphData: ComputedRef<GraphDataLike | null | undefined>
}

export function useWorkspacePreview(options: UseWorkspacePreviewOptions) {
  const textContent = ref('')
  const syncingFromRight = ref(false)
  const syncingFromLeft = ref(false)
  const leftScrollPercent = ref(0)
  const rightScrollPercent = ref(0)
  const pdfPage = ref(1)

  const progressPercent = computed(() => Number(options.node.value.parseProgress || 0))

  const fileExtension = computed(() => {
    return getFileExtension(options.filePath.value)
  })
  const previewFileType = computed(() => getPreviewFileType({
    filePath: options.filePath.value,
    file_path: options.filePath.value,
    title: options.node.value.title
  }))
  const isPdf = computed(() => previewFileType.value === 'pdf')
  const isOffice = computed(() => ['doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx'].includes(fileExtension.value))
  const isImage = computed(() => previewFileType.value === 'image')
  const isText = computed(() => previewFileType.value === 'text' || previewFileType.value === 'markdown')

  const fileUrl = computed(() => {
    if (!options.filePath.value) return ''
    if (options.filePath.value.startsWith('http')) return options.filePath.value
    return `/api/files?path=${encodeURIComponent(options.filePath.value)}`
  })
  const pdfViewerUrl = computed(() => {
    if (!fileUrl.value) return ''
    const hashParams = `toolbar=0&navpanes=0&scrollbar=0&view=FitH&page=${pdfPage.value}`
    if (fileUrl.value.includes('#')) {
      return `${fileUrl.value}&${hashParams}`
    }
    return `${fileUrl.value}#${hashParams}`
  })
  const officePreviewUrl = computed(() => {
    if (!fileUrl.value) return ''
    return `https://view.officeapps.live.com/op/embed.aspx?src=${encodeURIComponent(window.location.origin + fileUrl.value)}`
  })

  const inferredPdfPageCount = computed(() => {
    const node = options.node.value
    const candidates = [
      node.page_count,
      node.pageCount,
      node.pages,
      node.total_pages,
      node.pdf_page_count,
      node.meta?.page_count,
      node.meta?.pages
    ]
    const maxPageFromBlocks = (options.graphData.value?.nodes || []).reduce((max, blockNode) => {
      const page = blockNode.page_idx ?? 0
      return page > max ? page : max
    }, 0)
    if (maxPageFromBlocks > 0) candidates.push(maxPageFromBlocks)

    for (const candidate of candidates) {
      const pageCount = Number(candidate || 0)
      if (Number.isFinite(pageCount) && pageCount > 0) {
        return Math.round(pageCount)
      }
    }
    return 1
  })

  const loadTextContent = async () => {
    if (!isText.value || !fileUrl.value) return
    try {
      const response = await fetch(fileUrl.value)
      textContent.value = await response.text()
    } catch {
      textContent.value = '加载文件内容失败'
    }
  }

  const syncPdfPageByPercent = (percent: number) => {
    if (!isPdf.value) return
    const totalPages = inferredPdfPageCount.value
    if (totalPages <= 1) return
    const nextPage = Math.max(1, Math.min(totalPages, Math.round(percent * (totalPages - 1)) + 1))
    if (nextPage !== pdfPage.value) {
      pdfPage.value = nextPage
    }
  }

  const onRightPaneScrollPercent = (percent: number) => {
    rightScrollPercent.value = percent
    if (syncingFromLeft.value) return
    syncPdfPageByPercent(percent)
    syncingFromRight.value = true
    leftScrollPercent.value = percent
    requestAnimationFrame(() => {
      syncingFromRight.value = false
    })
  }

  const onLeftTextScrollPercent = (percent: number) => {
    leftScrollPercent.value = percent
    if (syncingFromRight.value) return
    syncingFromLeft.value = true
    rightScrollPercent.value = percent
    syncPdfPageByPercent(percent)
    requestAnimationFrame(() => {
      syncingFromLeft.value = false
    })
  }

  const downloadFile = () => {
    if (!fileUrl.value) return
    const link = document.createElement('a')
    link.href = fileUrl.value
    link.download = options.node.value.title
    link.click()
  }

  const resetPreviewState = () => {
    pdfPage.value = 1
    leftScrollPercent.value = 0
    rightScrollPercent.value = 0
  }

  watch(options.filePath, () => {
    if (isText.value) {
      loadTextContent()
    }
  }, { immediate: true })

  return {
    progressPercent,
    isPdf,
    isOffice,
    isImage,
    isText,
    fileUrl,
    pdfViewerUrl,
    officePreviewUrl,
    textContent,
    inferredPdfPageCount,
    pdfPage,
    leftScrollPercent,
    rightScrollPercent,
    onRightPaneScrollPercent,
    onLeftTextScrollPercent,
    downloadFile,
    resetPreviewState
  }
}
