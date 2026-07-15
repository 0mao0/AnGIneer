<template>
  <div class="left-panel-container" :class="appClass">
    <a-tabs v-model:activeKey="activeTab" class="resource-tabs">
      <a-tab-pane key="project" tab="项目">
        <keep-alive>
          <ProjectSidebar />
        </keep-alive>
      </a-tab-pane>
      <a-tab-pane key="knowledge" tab="知识">
        <keep-alive>
          <div class="knowledge-panel">
            <KnowledgeTree
              :tree-data="treeData"
              v-bind="treeProps"
              :loading="loading"
              @select="onTreeSelect"
            />
          </div>
        </keep-alive>
      </a-tab-pane>
      <a-tab-pane key="sop" tab="经验">
        <keep-alive>
          <SOPSidebar />
        </keep-alive>
      </a-tab-pane>
    </a-tabs>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { KnowledgeTree, useKnowledgeTree, createResourceNodeFromKnowledge } from '@angineer/docs-ui'
import SOPSidebar from './sidebar/SOPSidebar.vue'
import ProjectSidebar from './sidebar/ProjectSidebar.vue'
import { useTheme } from '@angineer/ui-kit'
import { knowledgeApi } from '@/api/knowledge'
import type { SmartTreeNode } from '@angineer/docs-ui'
import { useResourceOpen } from '@/composables/useResourceOpen'

type ResourcePanelSection = 'project' | 'knowledge' | 'sop'

const props = withDefaults(defineProps<{
  activeSection?: ResourcePanelSection
}>(), {
  activeSection: 'knowledge'
})

const emit = defineEmits<{
  'update:activeSection': [value: ResourcePanelSection]
}>()

const { appClass } = useTheme()
const activeTab = computed({
  get: () => props.activeSection,
  set: (value) => emit('update:activeSection', value)
})

const { treeData, buildTree } = useKnowledgeTree()
const loading = ref(false)
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

const loadNodes = async () => {
  loading.value = true
  try {
    const response = await knowledgeApi.getNodes('default', true) as unknown as any[]
    treeData.value = buildTree(response)
  } catch (error) {
    console.error('加载知识库节点失败:', error)
  } finally {
    loading.value = false
  }
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
  const resource = createResourceNodeFromKnowledge(node, 'default')
  openResource(resource)
}

onMounted(() => {
  loadNodes()
})
</script>

<style lang="less" scoped>
.left-panel-container {
  height: 100%;
  display: flex;
  flex-direction: column;
  transition: all 0.3s ease;
  background: var(--panel-bg);
  border-right: 1px solid var(--border-color, rgba(0, 0, 0, 0.06));
}

.resource-tabs {
  height: 100%;
  display: flex;
  flex-direction: column;

  :deep(.ant-tabs-nav) {
    margin: 0;
    padding: 0 16px;
    flex-shrink: 0;
    transition: background-color 0.3s ease;
    background: var(--bg-tertiary, rgba(0, 0, 0, 0.02));
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

  :deep(.ant-tree-node-content-wrapper.ant-tree-node-selected) {
    background: rgba(0, 0, 0, 0.06) !important;
  }

  :deep(.ant-tree-node-content-wrapper:hover) {
    background: rgba(0, 0, 0, 0.04) !important;
  }
}
</style>
