import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { OpenResourcePayload, WorkbenchTabType } from '@angineer/docs-ui'

interface Tab {
  key: string
  type: WorkbenchTabType
  title: string
  props: Record<string, unknown>
}

export const useWorkbenchStore = defineStore('workbench', () => {
  const tabs = ref<Tab[]>([])
  const activeTab = ref<string>('')

  const currentTab = computed(() => tabs.value.find(t => t.key === activeTab.value))

  const openTab = (tab: Tab) => {
    const existing = tabs.value.find(t => t.key === tab.key)
    if (!existing) {
      tabs.value.push(tab)
    }
    activeTab.value = tab.key
  }

  const openResource = (payload: OpenResourcePayload) => {
    openTab({
      key: payload.key,
      type: payload.type,
      title: payload.title,
      props: payload.props
    })
  }

  const closeTab = (key: string) => {
    const index = tabs.value.findIndex(t => t.key === key)
    if (index > -1) {
      tabs.value.splice(index, 1)
      if (activeTab.value === key) {
        activeTab.value = tabs.value[Math.max(0, index - 1)]?.key || ''
      }
    }
  }

  const setActiveTab = (key: string) => {
    activeTab.value = key
  }

  return {
    tabs,
    activeTab,
    currentTab,
    openTab,
    openResource,
    closeTab,
    setActiveTab
  }
}, {
  persist: {
    paths: ['tabs', 'activeTab']
  }
})
