/** 评测题集管理 composable。 */
import { ref } from 'vue'
import type { EvalDataset, EvalFolder, EvalQuestion } from '../types/eval'

/** 生成唯一 dataset_id */
function generateDatasetId(): string {
  return `ds-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

/** 生成唯一 folder_id */
function generateFolderId(): string {
  return `folder-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

/** 将路径参数编码为 URL 安全的 segment，避免中文/空格/斜杠等导致请求路径解析异常。 */
function encodePathSegment(value: string): string {
  return encodeURIComponent(value)
}

export function useEvalDataset() {
  const datasets = ref<EvalDataset[]>([])
  const currentDataset = ref<EvalDataset | null>(null)
  const questions = ref<EvalQuestion[]>([])
  const folders = ref<EvalFolder[]>([])
  const loading = ref(false)

  const fetchDatasets = async () => {
    loading.value = true
    try {
      const resp = await fetch('/api/evals/datasets')
      if (resp.ok) {
        const data = await resp.json()
        datasets.value = data.datasets || []
      }
    } finally {
      loading.value = false
    }
  }

  const fetchDataset = async (datasetId: string) => {
    loading.value = true
    try {
      const resp = await fetch(`/api/evals/datasets/${encodePathSegment(datasetId)}`)
      if (resp.ok) {
        currentDataset.value = await resp.json()
      }
    } finally {
      loading.value = false
    }
  }

  const fetchQuestions = async (datasetId: string) => {
    loading.value = true
    try {
      // fields=summary：列表只取 UI 真正渲染的列，八个 gold 列不回传
      // （生产实测 gold 占 1040 题集列表载荷的 68%、GDP100 的 84%，列表页一处不渲染）。
      // 展开/编辑需要的 gold 原文由 fetchQuestion 按需取回。
      const resp = await fetch(`/api/evals/datasets/${encodePathSegment(datasetId)}/questions?fields=summary`)
      if (resp.ok) {
        const data = await resp.json()
        questions.value = data.questions || []
      }
    } finally {
      loading.value = false
    }
  }

  /** 取单题完整原文（含 gold），原地合并进 questions。
   *  必须是原地合并、不能换数组引用：EvalQuestionList 的 watch(() => props.questions)
   *  会把当前页重置到第 1 页，展开第 5 页的题会把用户弹回首页。 */
  const fetchQuestion = async (datasetId: string, questionId: string) => {
    const resp = await fetch(
      `/api/evals/datasets/${encodePathSegment(datasetId)}/questions/${encodePathSegment(questionId)}`
    )
    if (!resp.ok) return null
    const question: EvalQuestion = await resp.json()
    const index = questions.value.findIndex(q => q.question_id === questionId)
    if (index >= 0) Object.assign(questions.value[index], question)
    return question
  }

  const createDataset = async (payload: { title: string; category: string; description?: string }) => {
    const body = { dataset_id: generateDatasetId(), ...payload }
    const resp = await fetch('/api/evals/datasets', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (resp.ok) {
      await fetchDatasets()
      return await resp.json()
    }
    const errText = await resp.text().catch(() => '')
    throw new Error(errText || `创建失败 (${resp.status})`)
  }

  const deleteDataset = async (datasetId: string) => {
    const resp = await fetch(`/api/evals/datasets/${encodePathSegment(datasetId)}`, { method: 'DELETE' })
    if (resp.ok) {
      await fetchDatasets()
      return true
    }
    const errText = await resp.text().catch(() => '')
    throw new Error(errText || `删除失败 (${resp.status})`)
  }

  const renameDataset = async (datasetId: string, newTitle: string) => {
    const resp = await fetch(`/api/evals/datasets/${encodePathSegment(datasetId)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: newTitle }),
    })
    if (resp.ok) {
      await fetchDatasets()
      return true
    }
    const errText = await resp.text().catch(() => '')
    throw new Error(errText || `重命名失败 (${resp.status})`)
  }

  const fetchFolders = async () => {
    try {
      const resp = await fetch('/api/evals/folders')
      if (resp.ok) {
        const data = await resp.json()
        folders.value = data.folders || []
      }
    } catch {
      folders.value = []
    }
  }

  const createFolder = async (payload: { title: string; category: string; parent_folder_id?: string }) => {
    const folderId = generateFolderId()
    const body = { folder_id: folderId, ...payload }
    const resp = await fetch('/api/evals/folders', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (resp.ok) {
      await fetchFolders()
      return await resp.json()
    }
    const errText = await resp.text().catch(() => '')
    throw new Error(errText || `创建文件夹失败 (${resp.status})`)
  }

  const renameFolder = async (folderId: string, newTitle: string) => {
    const resp = await fetch(`/api/evals/folders/${encodePathSegment(folderId)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: newTitle }),
    })
    if (resp.ok) {
      await fetchFolders()
      return true
    }
    const errText = await resp.text().catch(() => '')
    throw new Error(errText || `重命名文件夹失败 (${resp.status})`)
  }

  const deleteFolder = async (folderId: string) => {
    const resp = await fetch(`/api/evals/folders/${encodePathSegment(folderId)}`, { method: 'DELETE' })
    if (resp.ok) {
      await fetchFolders()
      await fetchDatasets()
      return true
    }
    const errText = await resp.text().catch(() => '')
    throw new Error(errText || `删除文件夹失败 (${resp.status})`)
  }

  /** 更新文件夹属性（如移动到新父级、更改类别等） */
  const updateFolder = async (folderId: string, updates: Record<string, any>) => {
    const resp = await fetch(`/api/evals/folders/${encodePathSegment(folderId)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates),
    })
    if (resp.ok) {
      await fetchFolders()
      return true
    }
    const errText = await resp.text().catch(() => '')
    throw new Error(errText || `更新文件夹失败 (${resp.status})`)
  }

  const moveDataset = async (datasetId: string, folderId: string, sortOrder: number = 0) => {
    const resp = await fetch(`/api/evals/datasets/${encodePathSegment(datasetId)}/move`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder_id: folderId, sort_order: sortOrder }),
    })
    if (resp.ok) {
      await fetchDatasets()
      return true
    }
    const errText = await resp.text().catch(() => '')
    throw new Error(errText || `移动失败 (${resp.status})`)
  }

  return {
    datasets,
    currentDataset,
    questions,
    folders,
    loading,
    fetchDatasets,
    fetchDataset,
    fetchQuestions,
    fetchQuestion,
    createDataset,
    deleteDataset,
    renameDataset,
    fetchFolders,
    createFolder,
    renameFolder,
    deleteFolder,
    updateFolder,
    moveDataset,
  }
}
