import { ref, computed } from 'vue'
import type { TableData, TableQueryResult } from '../types'

const API_BASE = '/api/docs'

export function useQuery() {
  const result = ref<TableQueryResult | null>(null)
  const loading = ref(false)
  const error = ref<Error | null>(null)
  const history = ref<TableQueryResult[]>([])

  const queryTable = async (tableId: string, params: Record<string, any>): Promise<TableQueryResult | null> => {
    loading.value = true
    error.value = null
    try {
      const response = await fetch(`${API_BASE}/tables/${tableId}/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params)
      })
      if (!response.ok) throw new Error('Query failed')
      const data = await response.json()
      result.value = data
      history.value.unshift(data)
      if (history.value.length > 50) history.value.pop()
      return data
    } catch (e) {
      error.value = e as Error
      return null
    } finally {
      loading.value = false
    }
  }

  const semanticQuery = async (question: string, libraryId?: string) => {
    loading.value = true
    error.value = null
    try {
      const response = await fetch(`${API_BASE}/query/semantic`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, libraryId })
      })
      if (!response.ok) throw new Error('Query failed')
      return await response.json()
    } catch (e) {
      error.value = e as Error
      return null
    } finally {
      loading.value = false
    }
  }

  const clearHistory = () => {
    history.value = []
  }

  return {
    result,
    loading,
    error,
    history,
    queryTable,
    semanticQuery,
    clearHistory
  }
}
