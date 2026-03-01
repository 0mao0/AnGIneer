import { ref, computed } from 'vue'
import type { Reference, ReferenceContext } from '../types'

const API_BASE = '/api/docs'

export function useRefAnchor() {
  const contextItems = ref<ReferenceContext[]>([])
  const loading = ref(false)

  const addContext = (ref: Reference, selectedText?: string) => {
    const existing = contextItems.value.find(item => item.reference.id === ref.id)
    if (!existing) {
      contextItems.value.push({
        id: `ctx-${Date.now()}`,
        reference: ref,
        selectedText,
        timestamp: Date.now()
      })
    }
  }

  const removeContext = (id: string) => {
    const index = contextItems.value.findIndex(item => item.id === id)
    if (index > -1) {
      contextItems.value.splice(index, 1)
    }
  }

  const clearContext = () => {
    contextItems.value = []
  }

  const fetchReference = async (blockId: string): Promise<Reference | null> => {
    loading.value = true
    try {
      const response = await fetch(`${API_BASE}/references/${blockId}`)
      if (!response.ok) throw new Error('Failed to fetch reference')
      return await response.json()
    } catch {
      return null
    } finally {
      loading.value = false
    }
  }

  const copyReference = async (ref: Reference): Promise<boolean> => {
    try {
      const text = `[${ref.title}](${ref.source})`
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      return false
    }
  }

  const getContextText = (): string => {
    return contextItems.value
      .map(item => `[${item.reference.title}]\n${item.selectedText || item.reference.content}`)
      .join('\n\n---\n\n')
  }

  return {
    contextItems,
    loading,
    addContext,
    removeContext,
    clearContext,
    fetchReference,
    copyReference,
    getContextText
  }
}
