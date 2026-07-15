<template>
  <div class="workbench-container" :class="appClass">
    <div class="tabs-bar">
      <a-tabs v-model:activeKey="activeTab" type="editable-card" hide-add @edit="handleTabEdit">
        <a-tab-pane v-for="tab in tabs" :key="tab.key" :closable="tabs.length > 1">
          <template #tab>
            <span>
              <component :is="getIcon(tab.type)" />
              {{ tab.title }}
            </span>
          </template>
        </a-tab-pane>
      </a-tabs>
    </div>
    <div class="content-area">
      <div v-if="tabs.length === 0" class="empty-state">
        <a-empty description="打开文档或项目开始工作" />
      </div>
      <TabErrorBoundary
        v-else
        :tab-key="currentTab?.key"
        @close="closeTabFromError"
      >
        <component :is="currentViewer" v-bind="currentTab?.props" />
      </TabErrorBoundary>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { FileTextOutlined, ApiOutlined, EnvironmentOutlined } from '@ant-design/icons-vue'
import type { WorkbenchTabType } from '@angineer/docs-ui'
import { TabErrorBoundary } from '@angineer/ui-kit'
import { useWorkbenchStore } from '@/stores/workbench'
import { useTheme } from '@angineer/ui-kit'
import DocumentView from '@/views/DocumentView.vue'
import SOPView from '@/views/SOPView.vue'
import GISView from '@/views/GISView.vue'
import ProjectView from '@/views/ProjectView.vue'

const workbenchStore = useWorkbenchStore()
const { appClass } = useTheme()

const activeTab = computed({
  get: () => workbenchStore.activeTab,
  set: (val) => workbenchStore.setActiveTab(val)
})

const tabs = computed(() => workbenchStore.tabs)
const currentTab = computed(() => tabs.value.find(t => t.key === activeTab.value))
const viewerMap: Record<WorkbenchTabType, unknown> = {
  document: DocumentView,
  sop: SOPView,
  gis: GISView,
  code: DocumentView,
  project: ProjectView
}

const currentViewer = computed(() => {
  if (!currentTab.value) return null
  return viewerMap[currentTab.value.type] || null
})

const getIcon = (type: string) => {
  switch (type) {
    case 'document':
      return FileTextOutlined
    case 'sop':
      return ApiOutlined
    case 'gis':
      return EnvironmentOutlined
    default:
      return FileTextOutlined
  }
}

const handleTabEdit = (targetKey: string | MouseEvent | KeyboardEvent, action: 'add' | 'remove') => {
  if (action !== 'remove' || typeof targetKey !== 'string') {
    return
  }
  workbenchStore.closeTab(targetKey)
}

const closeTabFromError = (tabKey: string) => {
  workbenchStore.closeTab(tabKey)
}
</script>

<style lang="less" scoped>
.workbench-container {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--bg-secondary);
  transition: background-color 0.3s;
}

.tabs-bar {
  background: var(--panel-bg);
  border-bottom: 1px solid var(--border-color, rgba(0, 0, 0, 0.06));
  transition: background-color 0.3s, border-color 0.3s;

  :deep(.ant-tabs) {
    .ant-tabs-nav {
      margin: 0;
      padding: 0 8px;
    }
  }
}

.content-area {
  flex: 1;
  overflow: hidden;
  background: var(--bg-primary);
  transition: background-color 0.3s;
}

.empty-state {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
