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
      const resp = await fetch(`/api/evals/datasets/${datasetId}`)
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
      const resp = await fetch(`/api/evals/datasets/${datasetId}/questions`)
      if (resp.ok) {
        const data = await resp.json()
        questions.value = data.questions || []
      }
    } finally {
      loading.value = false
    }
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
    const resp = await fetch(`/api/evals/datasets/${datasetId}`, { method: 'DELETE' })
    if (resp.ok) {
      await fetchDatasets()
      return true
    }
    const errText = await resp.text().catch(() => '')
    throw new Error(errText || `删除失败 (${resp.status})`)
  }

  const renameDataset = async (datasetId: string, newTitle: string) => {
    const resp = await fetch(`/api/evals/datasets/${datasetId}`, {
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
    const resp = await fetch(`/api/evals/folders/${folderId}`, {
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
    const resp = await fetch(`/api/evals/folders/${folderId}`, { method: 'DELETE' })
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
    const resp = await fetch(`/api/evals/folders/${folderId}`, {
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
    const resp = await fetch(`/api/evals/datasets/${datasetId}/move`, {
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
