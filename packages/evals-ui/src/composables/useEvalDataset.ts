/** 评测题集管理 composable。 */
import { ref } from 'vue'
import type { EvalDataset, EvalQuestion } from '../types/eval'

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
    const resp = await fetch('/api/evals/datasets', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (resp.ok) {
      await fetchDatasets()
      return await resp.json()
    }
    return null
  }

  const deleteDataset = async (datasetId: string) => {
    const resp = await fetch(`/api/evals/datasets/${datasetId}`, { method: 'DELETE' })
    if (resp.ok) {
      await fetchDatasets()
      return true
    }
    return false
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
  }
}
