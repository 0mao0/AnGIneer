<template>
  <div class="left-panel-container" :class="{ 'dark-mode': themeStore.isDark }">
    <a-tabs v-model:activeKey="activeTab" class="resource-tabs">
      <a-tab-pane key="project" tab="项目">
        <ProjectSidebar />
      </a-tab-pane>
      <a-tab-pane key="knowledge" tab="知识">
        <div class="knowledge-panel">
          <SmartTree
            ref="smartTreeRef"
            :tree-data="treeData"
            :show-search="true"
            search-placeholder="搜索文档..."
            :show-add-root-folder="false"
            :show-status="false"
            :draggable="false"
            :allow-add-file="false"
            :loading="loading"
            empty-text="暂无文档"
            @select="onTreeSelect"
          >
            <template #icon="{ node }">
              <FolderOutlined v-if="node?.isFolder" style="color: #faad14" />
              <FileTextOutlined v-else style="color: #1890ff" />
            </template>
          </SmartTree>
        </div>
      </a-tab-pane>
      <a-tab-pane key="sop" tab="经验">
        <SOPSidebar />
      </a-tab-pane>
    </a-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { FolderOutlined, FileTextOutlined } from '@ant-design/icons-vue'
import { SmartTree } from '@angineer/docs-ui'
import SOPSidebar from './sidebar/SOPSidebar.vue'
import ProjectSidebar from './sidebar/ProjectSidebar.vue'
import { useThemeStore } from '@/stores'
import { knowledgeApi } from '@/api/knowledge'
import type { SmartTreeNode } from '@angineer/docs-ui'

const themeStore = useThemeStore()
const activeTab = ref('knowledge')

const smartTreeRef = ref<InstanceType<typeof SmartTree> | null>(null)
const treeData = ref<SmartTreeNode[]>([])
const loading = ref(false)

interface TreeNode {
  key: string
  title: string
  isFolder: boolean
  visible: boolean
  status: string
  parentId?: string
  filePath?: string
  children?: TreeNode[]
}

const buildTree = (nodes: any[]): TreeNode[] => {
  const nodeMap = new Map<string, TreeNode>()
  const roots: TreeNode[] = []

  nodes.forEach(n => {
    nodeMap.set(n.id, {
      key: n.id,
      title: n.title,
      isFolder: n.type === 'folder',
      visible: n.visible,
      status: n.status || 'pending',
      parentId: n.parent_id,
      filePath: n.file_path
    })
  })

  nodes.forEach(n => {
    const node = nodeMap.get(n.id)!
    if (n.parent_id && nodeMap.has(n.parent_id)) {
      const parent = nodeMap.get(n.parent_id)!
      if (!parent.children) parent.children = []
      parent.children.push(node)
    } else {
      roots.push(node)
    }
  })

  return roots
}

const loadNodes = async () => {
  loading.value = true
  try {
    const response = await knowledgeApi.getNodes('default', true) as unknown as any[]
    treeData.value = buildTree(response) as unknown as SmartTreeNode[]
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

const onSelectDoc = (node: any) => {
  console.log('Select doc:', node)
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
}
</style>
