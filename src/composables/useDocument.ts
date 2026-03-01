import { ref, computed } from 'vue'
import type { Document, DocumentBlock, Library } from '../types'

const API_BASE = '/api/docs'

export function useDocument() {
  const document = ref<Document | null>(null)
  const loading = ref(false)
  const error = ref<Error | null>(null)

  const fetchDocument = async (docId: string) => {
    loading.value = true
    error.value = null
    try {
      const response = await fetch(`${API_BASE}/documents/${docId}`)
      if (!response.ok) throw new Error('Failed to fetch document')
      document.value = await response.json()
    } catch (e) {
      error.value = e as Error
    } finally {
      loading.value = false
    }
  }

  const fetchLibrary = async (libraryId: string): Promise<Library | null> => {
    try {
      const response = await fetch(`${API_BASE}/libraries/${libraryId}`)
      if (!response.ok) throw new Error('Failed to fetch library')
      return await response.json()
    } catch {
      return null
    }
  }

  const searchDocuments = async (query: string, libraryId?: string): Promise<Document[]> => {
    try {
      const params = new URLSearchParams({ q: query })
      if (libraryId) params.append('libraryId', libraryId)
      const response = await fetch(`${API_BASE}/search?${params}`)
      if (!response.ok) throw new Error('Search failed')
      return await response.json()
    } catch {
      return []
    }
  }

  const getBlock = (blockId: string): DocumentBlock | undefined => {
    return document.value?.blocks.find(b => b.id === blockId)
  }

  const getBlocksByType = (type: DocumentBlock['type']): DocumentBlock[] => {
    return document.value?.blocks.filter(b => b.type === type) || []
  }

  return {
    document,
    loading,
    error,
    fetchDocument,
    fetchLibrary,
    searchDocuments,
    getBlock,
    getBlocksByType
  }
}
