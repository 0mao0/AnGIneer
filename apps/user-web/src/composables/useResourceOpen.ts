import { createOpenResourcePayload, type ResourceNode } from '@angineer/docs-ui'
import { useWorkbenchStore } from '@/stores/workbench'

export const useResourceOpen = () => {
  const workbenchStore = useWorkbenchStore()

  const openResource = (resource: ResourceNode): boolean => {
    const payload = createOpenResourcePayload(resource)
    if (!payload) {
      return false
    }
    workbenchStore.openResource(payload)
    return true
  }

  return {
    openResource
  }
}
