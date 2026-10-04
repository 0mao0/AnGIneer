import { defineStore } from 'pinia'
import { knowledgeApi } from '@/api/knowledge'

export interface KnowledgeLibraryItem {
  id: string
  name: string
  description?: string | null
  /** 注册表组名（standards/dredgeai/evals；未注册为空，视为生产组） */
  group_name?: string
}

/** 组归类：evals=评测语料，其余（含未注册）=生产（与 LibrarySelect 过滤口径一致）。 */
export function libraryGroupOf(lib?: KnowledgeLibraryItem | null): 'prod' | 'evals' {
  return lib?.group_name === 'evals' ? 'evals' : 'prod'
}

const LS_CURRENT = 'ag_admin_library'
const LS_GROUP_LIBS = 'ag_admin_group_libs'

function readGroupMap(): Record<string, string> {
  if (typeof localStorage === 'undefined') return {}
  try {
    const raw = localStorage.getItem(LS_GROUP_LIBS)
    const parsed = raw ? JSON.parse(raw) : {}
    return parsed && typeof parsed === 'object' ? (parsed as Record<string, string>) : {}
  } catch {
    return {}
  }
}

/**
 * 管理员跨库视野（P4）：全局选中知识库（持久化）。
 * 管理端各页面读取该库渲染/操作；默认 default 兼容存量。
 * 2026-10-04：按组各记「上次选中」（groupLibraries），组 tab 切换时恢复该组上一选择——
 * 否则切到评测组右侧仍挂着生产组的默认库（业主报障）。
 */
export const useLibraryStore = defineStore('library', {
  state: () => ({
    libraries: [] as KnowledgeLibraryItem[],
    libraryId: (typeof localStorage !== 'undefined' ? localStorage.getItem(LS_CURRENT) : null) ?? 'default',
    groupLibraries: readGroupMap() as Record<string, string>,
    loading: false,
  }),
  getters: {
    currentLibraryTitle: (state) =>
      state.libraries.find((l) => l.id === state.libraryId)?.name ?? state.libraryId,
    currentLibraryGroup: (state): 'prod' | 'evals' =>
      libraryGroupOf(state.libraries.find((l) => l.id === state.libraryId)),
  },
  actions: {
    async loadLibraries() {
      this.loading = true
      try {
        this.libraries = (await knowledgeApi.getLibraries()) as unknown as KnowledgeLibraryItem[]
        if (!this.libraries.some((l) => l.id === this.libraryId)) {
          this.setLibrary('default')
        }
        return this.libraries
      } finally {
        this.loading = false
      }
    },
    setLibrary(libraryId: string) {
      this.libraryId = libraryId || 'default'
      localStorage.setItem(LS_CURRENT, this.libraryId)
      this.rememberLibraryGroup(this.libraryId)
    },
    /** 记下某库归哪组（组 tab 恢复用）；库尚未加载时按 prod 记，加载后随首次选择纠正。 */
    rememberLibraryGroup(libraryId: string) {
      const group = libraryGroupOf(this.libraries.find((l) => l.id === libraryId))
      this.groupLibraries = { ...this.groupLibraries, [group]: libraryId }
      localStorage.setItem(LS_GROUP_LIBS, JSON.stringify(this.groupLibraries))
    },
  },
})
