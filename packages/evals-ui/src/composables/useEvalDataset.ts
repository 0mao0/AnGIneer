/** 评测题集管理 composable。 */
import { ref } from 'vue'
import type { EvalDataset, EvalQuestion } from '../types/eval'

/** 生成唯一 dataset_id */
function generateDatasetId(): string {
  return `ds-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

export function useEvalDataset() {
  const datasets = ref<EvalDataset[]>([])
  const currentDataset = ref<EvalDataset | null>(null)
  const questions = ref<EvalQuestion[]>([])
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

  return {
    datasets,
    currentDataset,
    questions,
    loading,
    fetchDatasets,
    fetchDataset,
    fetchQuestions,
    createDataset,
    deleteDataset,
    renameDataset,
  }
}
