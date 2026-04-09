<template>
  <div class="left-panel-container" :class="{ 'dark-mode': themeStore.isDark }">
    <a-tabs v-model:activeKey="activeTab" class="resource-tabs">
      <a-tab-pane key="project" tab="项目">
        <ProjectSidebar />
      </a-tab-pane>
      <a-tab-pane key="knowledge" tab="知识">
        <div class="knowledge-panel">
          <KnowledgeTree
            :tree-data="treeData"
            v-bind="treeProps"
            :loading="loading"
            @select="onTreeSelect"
          >
            <template #icon="{ node }">
              <FolderOutlined v-if="node?.isFolder" style="color: #faad14" />
              <FileTextOutlined v-else style="color: #1890ff" />
            </template>
          </KnowledgeTree>
        </div>
      </a-tab-pane>
      <a-tab-pane key="sop" tab="经验">
        <SOPSidebar />
      </a-tab-pane>
    </a-tabs>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { FolderOutlined, FileTextOutlined } from '@ant-design/icons-vue'
import { KnowledgeTree, useKnowledgeTree, createResourceNodeFromKnowledge } from '@angineer/docs-ui'
import SOPSidebar from './sidebar/SOPSidebar.vue'
import ProjectSidebar from './sidebar/ProjectSidebar.vue'
import { useThemeStore } from '@/stores'
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

const themeStore = useThemeStore()
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
@import '@/styles/variables.less';

.left-panel-container {
  height: 100%;
  display: flex;
  flex-direction: column;
  transition: all 0.3s ease;
}

.left-panel-container:not(.dark-mode) {
  background: #ffffff;
  border-right: 1px solid rgba(0, 0, 0, 0.06);
}

.left-panel-container.dark-mode {
  background: #1f1f1f;
  border-right: 1px solid rgba(255, 255, 255, 0.08);
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
  }

  .left-panel-container:not(.dark-mode) & :deep(.ant-tabs-nav) {
    background: rgba(0, 0, 0, 0.02);
  }

  .left-panel-container.dark-mode & :deep(.ant-tabs-nav) {
    background: rgba(255, 255, 255, 0.03);
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
