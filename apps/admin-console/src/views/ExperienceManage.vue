<template>
  <div class="experience-workspace" :class="appClass">
    <SplitPanes
      class="workspace-container"
      :initial-left-ratio="0.18"
      :initial-right-ratio="0.28"
    >
      <template #left>
        <Panel title="经验库" :icon="ApartmentOutlined" contentClass="tree-panel-content">
          <template #extra>
            <a-space :size="4">
              <a-button type="text" size="small" title="新建 SOP" @click="openCreateSopModal()">
                <template #icon><FileAddOutlined /></template>
              </a-button>
              <a-button type="text" size="small" title="导入 JSON" @click="openImportModal()">
                <template #icon><UploadOutlined /></template>
              </a-button>
            </a-space>
          </template>

          <div class="tree-container">
            <SOPTree
              v-if="hasData"
              ref="sopTreeRef"
              :tree-data="sopTree.treeData.value"
              :show-search="true"
              search-placeholder="搜索经验..."
              :show-add-root-folder="true"
              add-root-folder-title="新建文件夹"
              :show-icon="true"
              :show-status="false"
              :draggable="true"
              :allow-add-file="false"
              :allowed-file-types="['.json']"
              :loading="sopTree.loading.value"
              empty-text="暂无经验 SOP"
              @select="onTreeSelect"
              @rename="onTreeRename"
              @add-folder="onAddFolder"
              @add-file="(node: SOPTreeNode) => openCreateSopModal(node)"
              @view="onTreeView"
              @delete="onTreeDelete"
              @drop="onTreeDrop"
              @drop-root="onTreeDropRoot"
              @drop-invalid="onInvalidDrop"
              @file-drop="handleFileDrop"
            >
              <template #actions="{ node }">
                <template v-if="node.isFolder">
                  <EditOutlined class="action-icon" title="重命名" @click.stop="onTreeRename(node as SOPTreeNode)" />
                  <FileAddOutlined class="action-icon" title="新增 SOP" @click.stop="openCreateSopModal(node as SOPTreeNode)" />
                  <UploadOutlined class="action-icon" title="导入 JSON" @click.stop="openImportModal(node as SOPTreeNode)" />
                  <FolderAddOutlined class="action-icon" title="新增子文件夹" @click.stop="onAddFolder(node as SOPTreeNode)" />
                  <DeleteOutlined class="action-icon delete" title="删除" @click.stop="onTreeDelete(node as SOPTreeNode)" />
                </template>
                <template v-else>
                  <EditOutlined class="action-icon" title="重命名" @click.stop="onTreeRename(node as SOPTreeNode)" />
                  <EyeOutlined class="action-icon" title="查看" @click.stop="onTreeView(node as SOPTreeNode)" />
                  <DeleteOutlined class="action-icon delete" title="删除" @click.stop="onTreeDelete(node as SOPTreeNode)" />
                </template>
              </template>
              <template #empty>
                <div class="empty-state">
                  <ApartmentOutlined class="empty-icon" />
                  <div class="empty-title">还没有经验 SOP</div>
                  <div class="empty-actions">
                    <a-button size="small" type="primary" @click="openCreateSopModal()">新建 SOP</a-button>
                    <a-button size="small" @click="onAddFolder(null)">新建文件夹</a-button>
                    <a-button size="small" @click="openImportModal()">导入 JSON</a-button>
                  </div>
                </div>
              </template>
            </SOPTree>

            <div v-else-if="sopTree.loading.value" class="loading-state">
              <a-spin />
            </div>
            <div v-else class="empty-state">
              <ApartmentOutlined class="empty-icon" />
              <div class="empty-title">还没有经验 SOP</div>
              <div class="empty-actions">
                <a-button size="small" type="primary" @click="openCreateSopModal()">新建 SOP</a-button>
                <a-button size="small" @click="onAddFolder(null)">新建文件夹</a-button>
                <a-button size="small" @click="openImportModal()">导入 JSON</a-button>
              </div>
            </div>
          </div>
        </Panel>
      </template>

      <template #center>
        <Panel title="流程图" :icon="ApartmentOutlined">
          <template #extra>
            <a-space>
              <a-tag v-if="currentMode === 'view'" color="blue">只读查看</a-tag>
              <a-button v-if="currentMode === 'view'" size="small" type="default" @click="switchToEditMode">
                进入编辑
              </a-button>
            </a-space>
          </template>
          <div class="canvas-container">
            <div v-if="!sopTree.currentSopData.value" class="canvas-empty">
              <ApartmentOutlined class="canvas-empty-icon" />
              <div>{{ sopTree.selectedNode.value?.isFolder ? '请从文件夹中选择一个 SOP' : '请从左侧选择一个 SOP' }}</div>
            </div>
            <SOPFlowCanvas
              v-else
              :nodes="sopFlow.nodes.value"
              :edges="sopFlow.edges.value"
              :is-dirty="sopFlow.isDirty.value"
              :read-only="currentMode === 'view'"
              :selected-step-id="sopFlow.selectedStepId.value"
              @step-select="onStepSelect"
              @step-dblclick="onStepDblClick"
              @select-citation="handleSopCitationSelect"
              @save="onSaveSop"
              @add-step="onAddStep"
              @auto-layout="sopFlow.autoLayout()"
              @nodes-change="onNodesChange"
              @edges-change="onEdgesChange"
              @connect="onConnect"
              @edge-update="onEdgeUpdate"
              @delete-step="onDeleteStep"
            />
          </div>
        </Panel>
      </template>

      <template #right>
        <Panel contentClass="right-panel-content">
          <div class="right-panel">
            <div class="tab-switcher">
              <button
                type="button"
                class="tab-btn"
                :class="{ active: rightTabKey === 'property' }"
                @click="rightTabKey = 'property'"
              >
                属性
              </button>
              <button
                type="button"
                class="tab-btn"
                :class="{ active: rightTabKey === 'ai' }"
                @click="rightTabKey = 'ai'"
              >
                AI 对话
              </button>
            </div>

            <div class="tab-body">
              <div v-if="rightTabKey === 'property'" class="property-pane">
                <SopMetaPanel
                  v-if="!sopFlow.selectedStep.value && sopTree.currentSopData.value"
                  :sop-data="sopTree.currentSopData.value"
                  :all-sop-names="allSopNames"
                  :read-only="currentMode === 'view'"
                  @save="onSopMetaSave"
                  @cancel="onSopMetaCancel"
                />
                <div v-else-if="!sopFlow.selectedStep.value" class="panel-empty">
                  选择流程图节点查看属性
                </div>
                <SOPPropertyPanel
                  v-else
                  :step="sopFlow.selectedStep.value"
                  :read-only="currentMode === 'view'"
                  @save="onPropertySave"
                  @cancel="onPropertyCancel"
                  @select-citation="handleSopCitationSelect"
                />
              </div>

              <div v-else class="chat-pane">
                <AIChat
                  title=""
                  placeholder="输入消息，Enter 发送..."
                  :show-context-info="false"
                  scene="sop"
                  :session-id="sopTree.selectedNode.value?.key || 'default'"
                />
              </div>
            </div>
          </div>
        </Panel>
      </template>
    </SplitPanes>

    <a-modal
      :open="importModalVisible"
      title="导入 SOP JSON"
      :confirm-loading="importing"
      ok-text="导入"
      cancel-text="取消"
      @ok="handleImportUpload"
      @cancel="handleImportCancel"
    >
      <a-upload-dragger
        v-model:fileList="importFileList"
        :before-upload="beforeImportUpload"
        :max-count="1"
        accept=".json"
      >
        <p class="ant-upload-drag-icon">
          <InboxOutlined />
        </p>
        <p class="ant-upload-text">点击或拖拽 JSON 文件到此处</p>
        <p class="ant-upload-hint">仅支持 .json 格式的 SOP 文件</p>
      </a-upload-dragger>
    </a-modal>

    <FolderModal
      :visible="folderModalVisible"
      :title="folderForm.isNew ? '新建文件夹' : '重命名文件夹'"
      :loading="folderModalLoading"
      :name="folderForm.name"
      :parent-id="folderForm.parentId"
      :is-new="folderForm.isNew"
      :folder-tree-data="folderTreeData"
      @update:visible="folderModalVisible = $event"
      @update:name="folderForm.name = $event"
      @update:parent-id="folderForm.parentId = $event"
      @confirm="onFolderModalConfirm"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, h, onMounted, ref } from 'vue'
import { App, Input, message, type UploadFile } from 'ant-design-vue'
import { useRouter } from 'vue-router'
import {
  ApartmentOutlined,
  DeleteOutlined,
  EditOutlined,
  EyeOutlined,
  FileAddOutlined,
  FolderAddOutlined,
  InboxOutlined,
  UploadOutlined,
} from '@ant-design/icons-vue'
import { SplitPanes, Panel, AIChat, useTheme, type CitationBinding, type DropEvent } from '@angineer/ui-kit'
import { SOPTree, SOPFlowCanvas, SOPPropertyPanel, SopMetaPanel, useSopTree, useSopFlow, sopApi } from '@angineer/sop-ui'
import type { SOPTreeNode, SopStep } from '@angineer/sop-ui'
import type { Connection } from '@vue-flow/core'
import FolderModal from './components/FolderModal.vue'

const { appClass } = useTheme()
const { modal } = App.useApp()
const router = useRouter()

const sopTree = useSopTree()
const sopFlow = useSopFlow()

const sopTreeRef = ref<InstanceType<typeof SOPTree> | null>(null)
const rightTabKey = ref<'property' | 'ai'>('property')
const currentMode = ref<'edit' | 'view'>('edit')
const pendingImportFolderId = ref<string | undefined>(undefined)
const importModalVisible = ref(false)
const importFileList = ref<UploadFile[]>([])
const importing = ref(false)
const folderModalVisible = ref(false)
const folderModalLoading = ref(false)
const folderForm = ref({
  name: '',
  parentId: '__root__' as string | undefined,
  isNew: true,
  editingFolderId: null as string | null,
})

const hasData = computed(() => sopTree.treeData.value.length > 0)

/**
 * 递归提取所有非文件夹 SOP 名称，用于重名校验。
 */
const collectSopNames = (nodes: SOPTreeNode[]): string[] => {
  const names: string[] = []
  for (const node of nodes) {
    if (node.isFolder) {
      names.push(...collectSopNames(node.children || []))
    } else {
      names.push(node.title)
    }
  }
  return names
}

const allSopNames = computed(() => collectSopNames(sopTree.treeData.value))

const folderTreeData = computed(() => {
  const convert = (nodes: SOPTreeNode[]): Array<{ value: string; title: string; children?: any[] }> => {
    return nodes
      .filter((node) => node.isFolder)
      .map((node) => ({
        value: node.key,
        title: node.title,
        children: node.children ? convert(node.children) : [],
      }))
  }
  return [
    { value: '__root__', title: '根目录' },
    ...convert(sopTree.treeData.value),
  ]
})

/**
 * 查找节点的父级链路，用于刷新后自动展开并聚焦。
 */
const findParentChain = (nodes: SOPTreeNode[], key: string, parents: string[] = []): string[] | null => {
  for (const node of nodes) {
    if (node.key === key) {
      return parents
    }
    if (node.children?.length) {
      const found = findParentChain(node.children, key, [...parents, node.key])
      if (found) {
        return found
      }
    }
  }
  return null
}

/**
 * 刷新树并将目标节点展开、选中。
 */
const refreshTreeAndFocus = async (focusKey?: string) => {
  const tree = await sopTree.fetchTreeFromApi()
  if (!focusKey || !sopTreeRef.value) {
    return
  }
  const parents = findParentChain(tree, focusKey) || []
  sopTreeRef.value.expandedKeys = Array.from(new Set([...(sopTreeRef.value.expandedKeys || []), ...parents]))
  sopTreeRef.value.selectedKeys = [focusKey]
  const focusNode = sopTree.findNode(tree, focusKey)
  if (focusNode) {
    await loadNode(focusNode)
  }
}

/**
 * 载入指定树节点对应的 SOP 或文件夹状态。
 */
const loadNode = async (node: SOPTreeNode, mode: 'edit' | 'view' = 'edit') => {
  sopTree.setSelectedNode(node)
  currentMode.value = node.isFolder ? 'edit' : mode
  if (node.isFolder) {
    sopTree.currentSopData.value = null
    sopFlow.nodes.value = []
    sopFlow.edges.value = []
    sopFlow.isDirty.value = false
    sopFlow.selectStep(null)
    return
  }
  const data = await sopTree.fetchSopDetail(node.key)
  if (data) {
    sopFlow.loadFromSopData(data)
  }
}

/**
 * 打开新建 SOP 弹窗。
 */
const openCreateSopModal = (parentNode?: SOPTreeNode | null) => {
  const nameRef = ref('')
  modal.confirm({
    title: '新建 SOP',
    content: () => h(Input, {
      value: nameRef.value,
      placeholder: '输入 SOP 名称',
      'onUpdate:value': (value: string) => {
        nameRef.value = value
      },
    }),
    okText: '创建',
    cancelText: '取消',
    async onOk() {
      const trimmed = nameRef.value.trim()
      if (!trimmed) {
        throw new Error('请输入 SOP 名称')
      }
      const sopId = await sopTree.createEmptySop(trimmed, parentNode?.key)
      message.success('创建成功')
      await refreshTreeAndFocus(sopId)
    },
  })
}

/**
 * 打开 JSON 导入弹窗。
 */
const openImportModal = (parentNode?: SOPTreeNode | null) => {
  pendingImportFolderId.value = parentNode?.key
  importFileList.value = []
  importModalVisible.value = true
}

/**
 * 阻止 Ant Upload 自动上传。
 */
const beforeImportUpload = () => false

/**
 * 执行 SOP JSON 导入。
 */
const handleImportUpload = async () => {
  if (!importFileList.value.length) {
    return
  }
  const file = importFileList.value[0] as any
  importing.value = true
  try {
    const actualFile = (file.originFileObj || file) as File
    const sopId = await sopTree.importSopJson(actualFile, pendingImportFolderId.value)
    importModalVisible.value = false
    importFileList.value = []
    message.success(`导入成功: ${actualFile.name}`)
    await refreshTreeAndFocus(sopId)
  } catch (error: any) {
    message.error(error?.message || '导入失败')
  } finally {
    importing.value = false
    pendingImportFolderId.value = undefined
  }
}

/**
 * 关闭 SOP JSON 导入弹窗。
 */
const handleImportCancel = () => {
  importModalVisible.value = false
  importFileList.value = []
  pendingImportFolderId.value = undefined
}

/**
 * 响应树节点选择。
 */
const onTreeSelect = async (_keys: string[], nodes: SOPTreeNode[]) => {
  const node = nodes[0]
  if (!node) return
  await loadNode(node, 'edit')
}

/**
 * 查看节点时直接载入。
 */
const onTreeView = async (node: SOPTreeNode) => {
  await loadNode(node, 'view')
}

/**
 * 打开文件夹新建或重命名弹窗。
 */
const onTreeRename = (node: SOPTreeNode) => {
  if (node.isFolder) {
    folderForm.value = {
      name: node.title,
      parentId: node.parentId || '__root__',
      isNew: false,
      editingFolderId: node.key,
    }
    folderModalVisible.value = true
    return
  }

  const renameRef = ref(node.title)
  modal.confirm({
    title: '重命名 SOP',
    content: () => h(Input, {
      value: renameRef.value,
      placeholder: '输入新的 SOP 名称',
      'onUpdate:value': (value: string) => {
        renameRef.value = value
      },
    }),
    okText: '保存',
    cancelText: '取消',
    async onOk() {
      const trimmed = renameRef.value.trim()
      if (!trimmed) {
        throw new Error('请输入 SOP 名称')
      }
      await sopTree.renameSop(node.key, trimmed)
      message.success('重命名成功')
      await refreshTreeAndFocus(node.key)
    },
  })
}

/**
 * 打开新建文件夹弹窗。
 */
const onAddFolder = (parentNode: SOPTreeNode | null) => {
  folderForm.value = {
    name: '',
    parentId: parentNode?.key || '__root__',
    isNew: true,
    editingFolderId: null,
  }
  folderModalVisible.value = true
}

/**
 * 删除 SOP 或文件夹。
 */
const onTreeDelete = (node: SOPTreeNode) => {
  const requestPreview = node.isFolder
    ? sopApi.getFolderDeletePreview(node.key)
    : sopApi.getSopDeletePreview(node.key)

  requestPreview
    .then((preview) => {
      const lines = [
        `将删除 ${preview.document_count} 个 SOP、${preview.folder_count} 个文件夹，共 ${preview.total_nodes} 个节点。`,
        preview.sample_titles.length ? `示例：${preview.sample_titles.join('、')}` : '',
      ].filter(Boolean)
      modal.confirm({
        title: node.isFolder ? `确认删除文件夹「${node.title}」？` : `确认删除 SOP「${node.title}」？`,
        content: () => h('div', { class: 'delete-preview' }, [
          h('div', { class: 'delete-preview-main' }, lines[0]),
          ...(lines[1] ? [h('div', { class: 'delete-preview-sub' }, lines[1])] : []),
        ]),
        okType: 'danger',
        okText: '删除',
        cancelText: '取消',
        async onOk() {
          if (node.isFolder) {
            await sopApi.deleteFolder(node.key)
          } else {
            await sopTree.deleteSop(node.key)
          }
          message.success('删除成功')
          await refreshTreeAndFocus()
        },
      })
    })
    .catch((error: any) => {
      message.error(error?.message || '获取删除影响预览失败')
    })
}

/**
 * 提交文件夹弹窗。
 */
const onFolderModalConfirm = async () => {
  const { name, isNew, editingFolderId, parentId } = folderForm.value
  if (!name.trim()) {
    message.error('请输入文件夹名称')
    return
  }

  const targetParentId = !parentId || parentId === '__root__' ? undefined : parentId
  folderModalLoading.value = true
  try {
    if (isNew) {
      await sopTree.createFolder(name.trim(), targetParentId)
      message.success('创建成功')
    } else if (editingFolderId) {
      await sopApi.updateFolder(editingFolderId, {
        title: name.trim(),
        parent_folder_id: targetParentId || null,
      })
      message.success('重命名成功')
    }
    folderModalVisible.value = false
    await refreshTreeAndFocus(editingFolderId || undefined)
  } finally {
    folderModalLoading.value = false
  }
}

/**
 * 拖拽移动节点。
 */
const onTreeDrop = async (event: DropEvent) => {
  try {
    await sopTree.moveNode(event)
    message.success('移动成功')
    await refreshTreeAndFocus(event.dragKey)
  } catch (error: any) {
    message.error(error?.message || '移动失败')
    await refreshTreeAndFocus()
  }
}

/**
 * 拖到根目录。
 */
const onTreeDropRoot = async (dragNodeKey: string) => {
  try {
    await sopTree.moveNodeToRoot(dragNodeKey)
    message.success('已移动到根目录')
    await refreshTreeAndFocus(dragNodeKey)
  } catch (error: any) {
    message.error(error?.message || '移动失败')
    await refreshTreeAndFocus()
  }
}

/**
 * 处理非法拖拽提示。
 */
const onInvalidDrop = (reason: string) => {
  const messages: Record<string, string> = {
    'same-node': '不能拖到自身',
    'drop-to-descendant': '不能拖到子节点中',
    'drop-into-file': '不能拖入文件节点',
  }
  message.warning(messages[reason] || '无效的拖拽操作')
}

/**
 * 处理文件拖拽导入。
 */
const handleFileDrop = async (files: File[], targetFolder: SOPTreeNode | null) => {
  for (const file of files) {
    if (!file.name.toLowerCase().endsWith('.json')) {
      message.warning(`仅支持导入 JSON 文件: ${file.name}`)
      continue
    }
    try {
      const sopId = await sopTree.importSopJson(file, targetFolder?.key)
      message.success(`导入成功: ${file.name}`)
      await refreshTreeAndFocus(sopId)
    } catch (error: any) {
      message.error(error?.message || `导入失败: ${file.name}`)
    }
  }
}

/**
 * 选中步骤后切到属性页。
 */
const onStepSelect = (stepId: string) => {
  sopFlow.selectStep(stepId)
  rightTabKey.value = 'property'
}

/**
 * 双击步骤后切到属性页。
 */
const onStepDblClick = (stepId: string) => {
  sopFlow.selectStep(stepId)
  rightTabKey.value = 'property'
}

/**
 * 新增步骤并切换到属性面板。
 */
const onAddStep = () => {
  if (currentMode.value === 'view') {
    return
  }
  const newId = sopFlow.addStep(sopFlow.selectedStepId.value || undefined)
  sopFlow.selectStep(newId)
  rightTabKey.value = 'property'
}

/**
 * 保存属性面板草稿到流程图状态。
 */
const onPropertySave = (step: SopStep) => {
  if (currentMode.value === 'view') {
    message.warning('只读模式下不能修改步骤')
    return
  }
  if (!sopFlow.selectedStepId.value) {
    return
  }
  sopFlow.updateStepData(sopFlow.selectedStepId.value, step)
  message.success('步骤属性已更新，请保存 SOP')
}

const handleSopCitationSelect = (binding: CitationBinding) => {
  const reference = binding?.reference
  if (!reference?.docId) {
    return
  }
  const href = router.resolve({
    name: 'knowledge',
    query: {
      doc_id: reference.docId,
      target_id: reference.targetId || undefined,
      target_type: reference.targetType || undefined,
      page_idx: reference.pageIdx ? String(reference.pageIdx) : undefined,
    }
  }).href
  window.open(href, '_blank')
}

/**
 * 属性面板取消时保留当前已保存状态。
 */
const onPropertyCancel = () => {}

/**
 * 保存 SOP 元数据（名称、描述）。
 */
const onSopMetaSave = async (payload: { name_zh: string; description: string }) => {
  const currentData = sopTree.currentSopData.value
  if (!currentData) return
  try {
    await sopApi.updateSopMeta(currentData.id, {
      name_zh: payload.name_zh,
      description: payload.description,
    })
    currentData.name_zh = payload.name_zh
    currentData.description = payload.description
    if (sopTree.selectedNode.value) {
      sopTree.selectedNode.value.title = payload.name_zh
    }
    await refreshTreeAndFocus(currentData.id)
    message.success('SOP 元数据已保存')
  } catch (error: any) {
    message.error(error?.message || '保存 SOP 元数据失败')
  }
}

/**
 * SOP 元数据面板取消编辑。
 */
const onSopMetaCancel = () => {}

/**
 * 从只读模式切换回编辑模式。
 */
const switchToEditMode = () => {
  if (!sopTree.selectedNode.value || sopTree.selectedNode.value.isFolder) {
    return
  }
  currentMode.value = 'edit'
  message.success('已切换为编辑模式')
}

/**
 * 保存整份 SOP。
 */
const onSaveSop = async () => {
  if (currentMode.value === 'view') {
    message.warning('只读模式下不能保存')
    return
  }
  const currentData = sopTree.currentSopData.value
  if (!currentData) return
  const updatedData = sopFlow.exportToSopData(currentData)
  try {
    await sopApi.saveSop(currentData.id, updatedData)
    sopTree.currentSopData.value = updatedData
    sopFlow.isDirty.value = false
    message.success('保存成功')
  } catch (error: any) {
    message.error(error?.message || '保存 SOP 失败')
  }
}

/**
 * 同步流程图节点变化。
 */
const onNodesChange = (changes: any[]) => {
  sopFlow.handleNodesChange(changes)
}

/**
 * 同步流程图连线变化。
 */
const onEdgesChange = (changes: any[]) => {
  sopFlow.handleEdgesChange(changes)
}

/**
 * 新建两个步骤之间的连接。
 */
const onConnect = (connection: Connection) => {
  if (currentMode.value === 'view') {
    return
  }
  sopFlow.connectSteps(connection)
}

/**
 * 更新现有连线的端点关系。
 */
const onEdgeUpdate = ({ edgeId, connection }: { edgeId: string; connection: Connection }) => {
  if (currentMode.value === 'view') {
    return
  }
  sopFlow.updateEdgeConnection(edgeId, connection)
}

/**
 * 删除当前步骤节点。
 */
const onDeleteStep = (stepId: string) => {
  if (currentMode.value === 'view') {
    message.warning('只读模式下不能删除步骤')
    return
  }
  sopFlow.removeStep(stepId)
}

onMounted(() => {
  refreshTreeAndFocus()
})
</script>

<style lang="less" scoped>
.experience-workspace {
  height: 100%;
  overflow: hidden;
  background: var(--bg-primary);
}

.workspace-container {
  height: 100%;
}

.tree-container {
  height: 100%;
  min-height: 0;
  padding: 5px;
}

.loading-state,
.canvas-empty,
.panel-empty,
.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
}

.loading-state {
  height: 100%;
}

.empty-state {
  height: 100%;
  flex-direction: column;
  gap: 12px;
  padding: 24px;
  text-align: center;
}

.empty-icon {
  font-size: 40px;
  color: var(--text-secondary, #8c8c8c);
  opacity: 0.35;
}

.empty-title {
  font-size: 14px;
  color: var(--text-primary);
}

.empty-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
}

.canvas-container {
  height: 100%;
  width: 100%;
}

.canvas-empty {
  flex-direction: column;
  height: 100%;
  color: var(--text-secondary, #8c8c8c);
  gap: 12px;
}

.canvas-empty-icon {
  font-size: 48px;
  opacity: 0.3;
}

.right-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}

.tab-switcher {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px 6px;
  border-bottom: 1px solid var(--border-color);
  background: var(--panel-header-bg);
  flex-shrink: 0;
}

.tab-btn {
  border: none;
  background: transparent;
  color: var(--text-secondary);
  padding: 5px 10px;
  border-radius: 999px;
  cursor: pointer;
  font-size: 12px;
  transition: all 0.2s ease;

  &.active {
    background: rgba(24, 144, 255, 0.12);
    color: var(--primary-color);
    font-weight: 600;
  }
}

.tab-body {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.property-pane,
.chat-pane {
  height: 100%;
  min-height: 0;
}

.panel-empty {
  height: 100%;
  color: var(--text-secondary, #8c8c8c);
  font-size: 13px;
  padding: 20px;
  text-align: center;
}

.chat-pane {
  :deep(.base-chat-component) {
    height: 100%;
  }
}

.tree-panel-content,
.right-panel-content {
  background: transparent;
  overflow: hidden;
}

.delete-preview-main {
  color: var(--text-primary);
  line-height: 1.6;
}

.delete-preview-sub {
  margin-top: 6px;
  color: var(--text-secondary, #8c8c8c);
  line-height: 1.5;
}

.action-icon {
  font-size: 12px;
  color: var(--text-secondary, rgba(0, 0, 0, 0.45));
  cursor: pointer;
  padding: 2px;
  border-radius: 3px;
  transition: all 0.2s;

  &:hover {
    color: var(--primary-color);
    background: rgba(24, 144, 255, 0.1);
  }

  &.delete:hover {
    color: var(--tree-danger-hover);
    background: rgba(255, 77, 79, 0.1);
  }
}

:deep(.right-panel-content) {
  padding: 0;
}
</style>
