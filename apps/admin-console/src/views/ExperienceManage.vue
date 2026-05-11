<template>
  <div ref="workspaceRef" class="experience-workspace" :class="appClass">
    <SplitPanes
      class="workspace-container"
      :initial-left-ratio="0.18"
      :initial-right-ratio="0.28"
      @resize="onPanelResize"
    >
      <!-- 左侧：SOP 树 -->
      <template #left>
        <Panel title="经验库" :icon="ApartmentOutlined" contentClass="tree-panel-content">
          <div class="tree-container">
            <div v-if="sopTree.loading.value" class="loading-state">
              <a-spin />
            </div>
            <div v-else-if="sopTree.treeData.value.length === 0" class="empty-state" @click="onAddFolder(null)">
              <FolderAddOutlined class="empty-icon" />
              <div class="empty-text">
                <div class="empty-title">新建文件夹</div>
              </div>
            </div>
            <SOPTree
              v-else
              :tree-data="sopTree.treeData.value"
              @select="(_keys: string[], nodes: SOPTreeNode[]) => onTreeSelect(nodes[0])"
              @rename="onTreeRename"
              @add-folder="onAddFolder"
              @delete="onTreeDelete"
            />
          </div>
        </Panel>
      </template>

      <!-- 中间：流程图画布 -->
      <template #center>
        <Panel title="流程图" :icon="ApartmentOutlined">
          <template #extra>
            <a-space>
              <a-button size="small" @click="sopFlow.autoLayout()">自动布局</a-button>
              <a-button size="small" type="primary" :disabled="!sopFlow.isDirty.value" @click="onSaveSop">保存</a-button>
            </a-space>
          </template>
          <div class="canvas-container">
            <div v-if="!sopTree.currentSopData.value" class="canvas-empty">
              <ApartmentOutlined class="canvas-empty-icon" />
              <div>请从左侧选择一个 SOP</div>
            </div>
            <SOPFlowCanvas
              v-else
              :nodes="sopFlow.nodes.value"
              :edges="sopFlow.edges.value"
              :is-dirty="sopFlow.isDirty.value"
              @step-select="onStepSelect"
              @step-dblclick="onStepDblClick"
              @save="onSaveSop"
              @add-step="onAddStep"
              @auto-layout="sopFlow.autoLayout()"
              @nodes-change="onNodesChange"
              @edges-change="onEdgesChange"
            />
          </div>
        </Panel>
      </template>

      <!-- 右侧：属性面板 + AI 对话 -->
      <template #right>
        <Panel title="详情" :icon="InfoCircleOutlined">
          <a-tabs v-model:activeKey="rightTabKey" class="right-tabs">
            <a-tab-pane key="property" tab="属性">
              <div v-if="!sopFlow.selectedStep.value" class="panel-empty">
                双击步骤查看属性
              </div>
              <SOPPropertyPanel
                v-else
                :step="sopFlow.selectedStep.value"
                @update="onPropertyUpdate"
              />
            </a-tab-pane>
            <a-tab-pane key="ai" tab="AI 对话">
              <AIChat scene="sop" :session-id="sopTree.selectedNode.value?.key || ''" />
            </a-tab-pane>
          </a-tabs>
        </Panel>
      </template>
    </SplitPanes>

    <FolderModal
      :visible="folderModalVisible"
      :title="folderForm.isNew ? '新建文件夹' : '重命名文件夹'"
      :loading="false"
      :name="folderForm.name"
      :parent-id="folderForm.parentId"
      :is-new="folderForm.isNew"
      :folder-tree-data="[]"
      @update:visible="folderModalVisible = $event"
      @update:name="folderForm.name = $event"
      @update:parent-id="folderForm.parentId = $event"
      @confirm="onFolderModalConfirm"
    />
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { App } from 'ant-design-vue'
import {
  ApartmentOutlined,
  FolderAddOutlined,
  InfoCircleOutlined,
} from '@ant-design/icons-vue'
import { SplitPanes, Panel, AIChat, useTheme } from '@angineer/ui-kit'
import { SOPTree, SOPFlowCanvas, SOPPropertyPanel, useSopTree, useSopFlow, sopApi } from '@angineer/sop-ui'
import type { SOPTreeNode, SopStep } from '@angineer/sop-ui'
import FolderModal from './components/FolderModal.vue'

const { appClass } = useTheme()
const { modal } = App.useApp()

const sopTree = useSopTree()
const sopFlow = useSopFlow()

const rightTabKey = ref('property')
const folderModalVisible = ref(false)
const folderForm = ref({
  name: '',
  parentId: undefined as string | undefined,
  isNew: true,
  editingFolderId: null as string | null,
})

const onPanelResize = () => {}

const onTreeSelect = async (node: SOPTreeNode | undefined) => {
  if (!node) return
  sopTree.setSelectedNode(node)
  if (!node.isFolder) {
    const data = await sopTree.fetchSopDetail(node.key)
    if (data) {
      sopFlow.loadFromSopData(data)
    }
  }
}

const onTreeRename = (node: SOPTreeNode) => {
  if (node.isFolder) {
    folderForm.value = {
      name: node.title,
      parentId: undefined,
      isNew: false,
      editingFolderId: node.key,
    }
    folderModalVisible.value = true
  }
}

const onAddFolder = (parentNode: SOPTreeNode | null) => {
  folderForm.value = {
    name: '',
    parentId: parentNode?.key || undefined,
    isNew: true,
    editingFolderId: null,
  }
  folderModalVisible.value = true
}

const onTreeDelete = (node: SOPTreeNode) => {
  modal.confirm({
    title: node.isFolder ? '确认删除文件夹？' : '确认删除 SOP？',
    content: node.isFolder ? '删除后文件夹内所有 SOP 将变为未分类。' : `确认删除 SOP「${node.title}」？`,
    okType: 'danger',
    onOk: async () => {
      if (node.isFolder) {
        await sopApi.deleteFolder(node.key)
      } else {
        await sopTree.deleteSop(node.key)
      }
      await sopTree.fetchTreeFromApi()
    },
  })
}

const onFolderModalConfirm = async () => {
  const { name, isNew, editingFolderId, parentId } = folderForm.value
  if (isNew) {
    await sopTree.createFolder(name, parentId)
  } else if (editingFolderId) {
    await sopApi.updateFolder(editingFolderId, { title: name })
  }
  folderModalVisible.value = false
  await sopTree.fetchTreeFromApi()
}

const onStepSelect = (stepId: string) => {
  sopFlow.selectStep(stepId)
  rightTabKey.value = 'property'
}

const onStepDblClick = (stepId: string) => {
  sopFlow.selectStep(stepId)
  rightTabKey.value = 'property'
}

const onAddStep = () => {
  const newId = sopFlow.addStep(sopFlow.selectedStepId.value || undefined)
  sopFlow.selectStep(newId)
  rightTabKey.value = 'property'
}

const onPropertyUpdate = (updates: Partial<SopStep>) => {
  if (sopFlow.selectedStepId.value) {
    sopFlow.updateStepData(sopFlow.selectedStepId.value, updates)
  }
}

const onSaveSop = async () => {
  const currentData = sopTree.currentSopData.value
  if (!currentData) return
  const updatedData = sopFlow.exportToSopData(currentData)
  try {
    await sopApi.saveSop(currentData.id, updatedData)
    sopFlow.isDirty.value = false
  } catch (error) {
    console.error('保存 SOP 失败:', error)
  }
}

const onNodesChange = () => {
  sopFlow.isDirty.value = true
}

const onEdgesChange = () => {
  sopFlow.isDirty.value = true
}

onMounted(() => {
  sopTree.fetchTreeFromApi()
})
</script>

<style lang="less" scoped>
.experience-workspace {
  height: 100vh;
  overflow: hidden;
}

.workspace-container {
  height: 100%;
}

.tree-container {
  height: 100%;
  overflow: auto;
}

.loading-state {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 200px;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 200px;
  cursor: pointer;
  color: var(--text-secondary, #8c8c8c);

  &:hover {
    color: var(--primary-color, #1890ff);
  }
}

.empty-icon {
  font-size: 32px;
  margin-bottom: 8px;
}

.empty-title {
  font-size: 14px;
}

.canvas-container {
  height: 100%;
  width: 100%;
}

.canvas-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--text-secondary, #8c8c8c);
  gap: 12px;
}

.canvas-empty-icon {
  font-size: 48px;
  opacity: 0.3;
}

.panel-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 200px;
  color: var(--text-secondary, #8c8c8c);
  font-size: 13px;
}

.right-tabs {
  height: 100%;
}
</style>
