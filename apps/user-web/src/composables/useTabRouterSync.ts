import { watch, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useWorkbenchStore } from '@/stores/workbench'

export function useTabRouterSync() {
  const router = useRouter()
  const route = useRoute()
  const store = useWorkbenchStore()

  onMounted(() => {
    if (route.name === 'TabDeepLink') {
      const tabKey = Array.isArray(route.params.tabKey)
        ? route.params.tabKey.join('/')
        : route.params.tabKey
      if (tabKey && !store.tabs.find(t => t.key === tabKey)) {
        if (store.tabs.find(t => t.key === tabKey)) {
          store.setActiveTab(tabKey)
        }
      }
    }
  })

  watch(() => store.activeTab, (newKey) => {
    if (!newKey) return
    const target = `/tab/${newKey}`
    if (route.path !== target) {
      router.replace(target)
    }
  })
}
