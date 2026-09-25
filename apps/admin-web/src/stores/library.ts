import { defineStore } from 'pinia'
import { knowledgeApi } from '@/api/knowledge'

export interface KnowledgeLibraryItem {
  id: string
  name: string
  description?: string | null
}

/**
 * 管理员跨库视野（P4）：全局选中知识库（持久化）。
 * 管理端各页面读取该库渲染/操作；默认 default 兼容存量。
 */
export const useLibraryStore = defineStore('library', {
  state: () => ({
    libraries: [] as KnowledgeLibraryItem[],
    libraryId: (typeof localStorage !== 'undefined' ? localStorage.getItem('ag_admin_library') : null) ?? 'default',
    loading: false,
  }),
  getters: {
    currentLibraryTitle: (state) =>
      state.libraries.find((l) => l.id === state.libraryId)?.name ?? state.libraryId,
  },
  actions: {
    async loadLibraries() {
      this.loading = true
      try {
        this.libraries = (await knowledgeApi.getLibraries()) as unknown as KnowledgeLibraryItem[]
        if (!this.libraries.some((l) => l.id === this.libraryId)) {
          this.libraryId = 'default'
        }
        return this.libraries
      } finally {
        this.loading = false
      }
    },
    setLibrary(libraryId: string) {
      this.libraryId = libraryId || 'default'
      localStorage.setItem('ag_admin_library', this.libraryId)
    },
  },
})
