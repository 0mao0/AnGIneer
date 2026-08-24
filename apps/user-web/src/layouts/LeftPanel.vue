<template>
  <div
    ref="panelRef"
    class="left-panel-container"
    :class="[appClass, { 'hide-tab-labels': hideTabLabels }]"
  >
    <a-tabs v-model:activeKey="activeTab" class="resource-tabs">
      <a-tab-pane key="project" tab="项目">
        <keep-alive>
          <ProjectSidebar />
        </keep-alive>
      </a-tab-pane>
      <a-tab-pane key="knowledge" tab="知识">
        <div class="knowledge-panel">
          <EmptyState
            v-if="error && !treeData.length"
            variant="error"
            title="加载失败"
            :description="error.message"
            cta-text="重试"
            @cta-click="loadNodes"
          />
          <!-- keep-alive 只包 KnowledgeTree，确保切 tab 后展开状态保留 -->
          <keep-alive v-else>
            <KnowledgeTree
              :tree-data="treeData"
              v-bind="treeProps"
              :loading="loading"
              @select="onTreeSelect"
            />
          </keep-alive>
        </div>
      </a-tab-pane>
      <a-tab-pane key="sop" tab="经验">
        <keep-alive>
          <SOPSidebar />
        </keep-alive>
      </a-tab-pane>
    </a-tabs>
    <div class="left-panel-footer">
      <a-select
        v-if="authStore.libraries.length > 1"
        v-model:value="authStore.activeLibraryId"
        size="small"
        class="library-switcher"
        :options="libraryOptions"
        @change="onLibraryChange"
      />
      <a-button size="small" class="logout-btn" @click="handleLogout">退出登录</a-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { KnowledgeTree, useKnowledgeTree, createResourceNodeFromKnowledge } from '@angineer/docs-ui'
import SOPSidebar from './sidebar/SOPSidebar.vue'
import ProjectSidebar from './sidebar/ProjectSidebar.vue'
import { useTheme, EmptyState } from '@angineer/ui-kit'
import { knowledgeApi } from '@/api/knowledge'
import { useAuthStore } from '@/stores/auth'
import type { SmartTreeNode } from '@angineer/docs-ui'
import { useResourceOpen } from '@/composables/useResourceOpen'
import { useRetryableLoad } from '@/composables/useRetryableLoad'

type ResourcePanelSection = 'project' | 'knowledge' | 'sop'

const props = withDefaults(defineProps<{
  activeSection?: ResourcePanelSection
}>(), {
  activeSection: 'knowledge'
})

const panelRef = ref<HTMLElement | null>(null)
const hideTabLabels = ref(false)
let resizeObserver: ResizeObserver | null = null

const emit = defineEmits<{
  'update:activeSection': [value: ResourcePanelSection]
}>()

const { appClass } = useTheme()
const activeTab = computed({
  get: () => props.activeSection,
  set: (value) => emit('update:activeSection', value)
})

const { treeData, buildTree } = useKnowledgeTree()
const authStore = useAuthStore()
const activeLibraryId = computed(() => authStore.libraryId || 'default')
const libraryNames = ref<Record<string, string>>({})
const libraryOptions = computed(() =>
  authStore.libraries.map((lid) => ({ value: lid, label: libraryNames.value[lid] || lid }))
)
const { loading, error, reload: loadNodes } = useRetryableLoad(
  async () => {
    const response = await knowledgeApi.getNodes(activeLibraryId.value, true) as unknown as any[]
    treeData.value = buildTree(response)
    return response
  },
  { errorMessage: '加载知识库节点失败，请检查网络或后端服务' }
)
const { openResource } = useResourceOpen()
const treeProps = {
  showSearch: true,
  searchPlaceholder: '搜索文档...',
  showAddRootFolder: false,
  showStatus: false,
  draggable: false,
  allowAddFile: false,
  emptyText: '暂无文档'
}

const onTreeSelect = async (_keys: string[], nodes: SmartTreeNode[]) => {
  if (nodes.length > 0) {
    const node = nodes[0]
    if (!node.isFolder) {
      onSelectDoc(node)
    }
  }
}

const onSelectDoc = (node: SmartTreeNode) => {
  const resource = createResourceNodeFromKnowledge(node, activeLibraryId.value)
  openResource(resource)
}

async function loadLibraryNames() {
  try {
    const list = await knowledgeApi.getLibraries() as unknown as { id: string; name: string }[]
    libraryNames.value = Object.fromEntries(list.map((l) => [l.id, l.name]))
  } catch {
    // 名称加载失败时回退显示原始 id
  }
}

function onLibraryChange() {
  loadNodes()
}

async function handleLogout() {
  await authStore.logout()
}

onMounted(() => {
  loadNodes()
  loadLibraryNames()
  if (panelRef.value && typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        // 面板过窄时隐藏页签文字，避免竖排（直接不显示）
        hideTabLabels.value = entry.contentRect.width > 0 && entry.contentRect.width < 150
      }
    })
    resizeObserver.observe(panelRef.value)
  }
})

onUnmounted(() => {
  if (resizeObserver) {
    resizeObserver.disconnect()
    resizeObserver = null
  }
})
</script>

<style lang="less" scoped>
.left-panel-container {
  height: 100%;
  display: flex;
  flex-direction: column;
  transition: all 0.3s ease;
  background: var(--panel-bg);
  border-right: 1px solid var(--border-color);
}

.resource-tabs {
  height: 100%;
  display: flex;
  flex-direction: column;

  :deep(.ant-tabs-tab) {
    white-space: nowrap;
  }

  :deep(.ant-tabs-nav) {
    margin: 0;
    padding: 0 16px;
    flex-shrink: 0;
    transition: background-color 0.3s ease;
    background: var(--bg-tertiary);
  }

  :deep(.ant-tabs-content-holder) {
    flex: 1;
    overflow: hidden;
  }

  :deep(.ant-tabs-content) {
    height: 100%;
  }

  :deep(.ant-tabs-tabpane) {
    height: 100%;
    overflow-y: auto;
  }
}

.left-panel-container.hide-tab-labels {
  :deep(.ant-tabs-nav) {
    padding: 0 6px;
  }

  :deep(.ant-tabs-tab-btn) {
    font-size: 0;
  }
}

.left-panel-footer {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px;
  border-top: 1px solid var(--border-color);
  flex-shrink: 0;
}

.library-switcher {
  flex: 1;
}

.knowledge-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 12px;
  gap: 8px;
  overflow: hidden;
  background: transparent;

  :deep(.smart-tree) {
    background: transparent;
  }

  :deep(.ant-tree-node-content-wrapper:hover) {
    background: rgba(0, 0, 0, 0.04) !important;
  }
}
</style>
