<template>
  <div class="knowledge-workspace" :class="{ 'dark-mode': isDark }">
    <!-- 使用 SplitPanes 三栏布局组件 - 比例 2.5:5:2.5 -->
    <SplitPanes
      class="workspace-container"
      :initial-left-ratio="0.25"
      :initial-right-ratio="0.25"
      @resize="onPanelResize"
    >
      <!-- 左侧：知识树 -->
      <template #left>
        <Panel title="知识树" :icon="FolderOutlined">

          <div
            class="tree-container"
          >
            <!-- 空状态 -->
            <div v-if="!hasData" class="empty-state" @click="showCreateFolderModal">
              <FolderAddOutlined class="empty-icon" />
              <div class="empty-text">
                <div class="empty-title">新建文件夹</div>
              </div>
            </div>

            <!-- 知识树 - 使用 SmartTree 通用组件 -->
            <SmartTree
              v-else
              ref="smartTreeRef"
              :tree-data="treeData"
              :show-search="true"
              search-placeholder="搜索文档..."
              :show-status="true"
              :draggable="true"
              :allow-add-file="true"
              :allowed-file-types="allowedFileTypes"
              empty-text="暂无文档"
              @select="onTreeSelect"
              @rename="showRenameModal"
              @add-folder="showCreateSubFolderModal"
              @add-file="showCreateFileModal"
              @delete="handleDeleteNode"
              @view="showDocDetail"
              @drop="onTreeDrop"
              @drop-invalid="onInvalidDrop"
              @file-drop="handleFileDrop"
            >
              <!-- 自定义图标 -->
              <template #icon="{ node }">
                <FolderOutlined v-if="node?.isFolder" style="color: #faad14" />
                <FilePdfOutlined v-else style="color: #ff4d4f" />
              </template>

              <!-- 自定义状态标签 -->
              <template #status="{ node }">
                <a-tag
                  v-if="!node?.isFolder"
                  :color="node?.visible ? 'green' : 'default'"
                  size="small"
                  style="font-size: 10px; padding: 0 4px; line-height: 16px"
                >
                  {{ node?.visible ? '共享' : '本地' }}
                </a-tag>
              </template>
            </SmartTree>
          </div>
        </Panel>
      </template>

      <!-- 中间：文档解析/预览 -->
      <template #center>
        <Panel title="文档解析" :icon="FileSearchOutlined">
          <a-empty v-if="!selectedNode" description="请从左侧选择文档" class="center-empty" />

          <template v-else-if="selectedNode.isFolder">
            <FolderPreview
              :node="selectedNode"
              :child-count="getChildCount(selectedNode.key, 'document')"
              :allowed-file-types="allowedFileTypes"
              @upload="handleFolderUpload"
            />
          </template>

          <template v-else>
            <DocumentPreview
              :node="selectedNode"
              :content="docContent"
              @parse="parseDocument"
              @view="viewDocument"
              @toggle-visible="toggleVisible"
            />
          </template>
        </Panel>
      </template>

      <!-- 右侧：AI 对话 -->
      <template #right>
        <Panel title="AI 对话" :icon="MessageOutlined">
          <AIChat
            ref="aiChatRef"
            title=""
            placeholder="输入消息，Ctrl+Enter 发送..."
            :show-context-info="true"
            @send="handleChatSend"
            @ready="handleChatReady"
          />
        </Panel>
      </template>
    </SplitPanes>

    <!-- 新建/重命名文件夹弹窗 -->
    <FolderModal
      v-model:visible="folderModalVisible"
      :title="folderModalTitle"
      :loading="modalLoading"
      :folder-tree-data="[]"
      v-model:name="folderForm.name"
      v-model:parent-id="folderForm.parentId"
      :is-new="folderForm.isNew"
      @confirm="handleFolderModalOk"
    />

    <!-- 文档详情弹窗 -->
    <DocDetailModal
      v-model:visible="docDetailVisible"
      :doc="detailDoc"
      :get-folder-name="getFolderName"
      :get-status-color="getStatusColor"
      :get-status-text="getStatusText"
      @view="viewDocument"
      @delete="handleDeleteNode"
      @toggle-visible="toggleVisible"
    />
  </div>
</template>

<script setup lang="ts">
/**
 * 知识库管理页面 - 使用 AIChat 组件进行 AI 对话
 */
import { ref, computed, onMounted } from 'vue'
import { message, Modal } from 'ant-design-vue'
import {
  FolderOutlined,
  FolderAddOutlined,
  FileSearchOutlined,
  MessageOutlined
} from '@ant-design/icons-vue'

// 导入 packages 中的组件和 composables
import { SplitPanes, Panel, useTheme } from '@angineer/ui-kit'
import { AIChat, SmartTree, type SmartTreeNode } from '@angineer/docs-ui'
import { useKnowledgeTree, type TreeNode } from '@angineer/docs-ui'
import { knowledgeApi } from '@/api/knowledge'
import { useChatStore } from '@/stores/chat'
import { FilePdfOutlined } from '@ant-design/icons-vue'

// 使用主题
const { isDark } = useTheme()

// 使用 chat store
const chatStore = useChatStore()

// 导入本地子组件
import FolderPreview from './components/FolderPreview.vue'
import DocumentPreview from './components/DocumentPreview.vue'
import FolderModal from './components/FolderModal.vue'
import DocDetailModal from './components/DocDetailModal.vue'

// SmartTree 组件引用
const smartTreeRef = ref<InstanceType<typeof SmartTree> | null>(null)

// 使用知识树 composable
const {
  treeData,
  selectedKeys,
  selectedNode,
  hasData,
  buildTree,
  getChildCount,
  getFolderName
} = useKnowledgeTree()

// AIChat 组件引用
const aiChatRef = ref<InstanceType<typeof AIChat> | null>(null)
const allowedFileTypes = ['.pdf']

// 面板尺寸状态
const leftWidth = ref(350)
const centerWidth = ref(700)

// 弹窗状态
const folderModalVisible = ref(false)
const modalLoading = ref(false)
const folderForm = ref({
  name: '',
  parentId: undefined as string | undefined,
  isNew: true,
  nodeId: ''
})

const docDetailVisible = ref(false)
const detailDoc = ref<TreeNode | null>(null)

// 文档内容
const docContent = ref('')

// 计算属性
const folderModalTitle = computed(() => folderForm.value.isNew ? '新建文件夹' : '重命名')

// 面板调整大小回调
const onPanelResize = (leftSize: number, _rightSize: number) => {
  leftWidth.value = leftSize
  centerWidth.value = window.innerWidth * 0.5
}

// 状态颜色
const getStatusColor = (status: string) => {
  const colors: Record<string, string> = {
    pending: 'default',
    uploading: 'processing',
    processing: 'processing',
    completed: 'success',
    failed: 'error'
  }
  return colors[status] || 'default'
}

// 状态文本
const getStatusText = (status: string) => {
  const texts: Record<string, string> = {
    pending: '待处理',
    uploading: '上传中',
    processing: '解析中',
    completed: '已完成',
    failed: '解析失败'
  }
  return texts[status] || '未知'
}

// 加载节点
const loadNodes = async () => {
  try {
    const response = await knowledgeApi.getNodes('default', false) as unknown as any[]
    treeData.value = buildTree(response)
  } catch (error) {
    console.error('加载节点失败:', error)
    message.error('加载知识库节点失败')
  }
}

// SmartTree 选择节点回调
const onTreeSelect = async (keys: string[], nodes: SmartTreeNode[]) => {
  selectedKeys.value = keys
  if (nodes.length > 0) {
    const node = nodes[0] as TreeNode
    selectedNode.value = node
    if (!node.isFolder && node.status === 'completed') {
      await loadDocContent(node.key)
    }
  }
}

// 加载文档内容
const loadDocContent = async (docId: string) => {
  try {
    const result = await knowledgeApi.getDocument('default', docId) as unknown as { content: string }
    docContent.value = result.content || '暂无内容'
  } catch (error) {
    docContent.value = ''
  }
}

// 显示新建文件夹弹窗
const showCreateFolderModal = () => {
  folderForm.value = { name: '', parentId: undefined, isNew: true, nodeId: '' }
  folderModalVisible.value = true
}

// 显示重命名弹窗
const showRenameModal = (node: SmartTreeNode) => {
  folderForm.value = {
    name: node.title,
    parentId: node.parentId,
    isNew: false,
    nodeId: node.key
  }
  folderModalVisible.value = true
}

// 显示创建子文件夹弹窗
const showCreateSubFolderModal = (parentNode: SmartTreeNode | null) => {
  folderForm.value = {
    name: '',
    parentId: parentNode?.key || undefined,
    isNew: true,
    nodeId: ''
  }
  folderModalVisible.value = true
}

// 显示创建文件弹窗 - 触发文件选择并上传
const showCreateFileModal = (parentNode: SmartTreeNode) => {
  const input = document.createElement('input')
  input.type = 'file'
  input.accept = allowedFileTypes.join(',')
  input.onchange = async (e) => {
    const file = (e.target as HTMLInputElement).files?.[0]
    if (file) {
      await uploadFile(file, parentNode.key)
    }
  }
  input.click()
}

// 处理文件夹弹窗确认
const handleFolderModalOk = async () => {
  if (!folderForm.value.name.trim()) {
    message.error('请输入文件夹名称')
    return
  }

  modalLoading.value = true
  try {
    if (folderForm.value.isNew) {
      await knowledgeApi.createNode({
        library_id: 'default',
        title: folderForm.value.name,
        node_type: 'folder',
        parent_id: folderForm.value.parentId
      })
      message.success('创建成功')
    } else {
      await knowledgeApi.updateNode(folderForm.value.nodeId, {
        title: folderForm.value.name
      })
      message.success('重命名成功')
    }
    folderModalVisible.value = false
    await loadNodes()
  } catch (error) {
    message.error(folderForm.value.isNew ? '创建失败' : '重命名失败')
  } finally {
    modalLoading.value = false
  }
}

// 删除节点
const handleDeleteNode = async (node: SmartTreeNode) => {
  const nodeType = node.isFolder ? '文件夹' : '文件'
  const hasChildren = node.children && node.children.length > 0
  const warningText = hasChildren ? '\n注意：该文件夹包含子项目，删除后将一并删除！' : ''

  Modal.confirm({
    title: `确认删除${nodeType}`,
    content: `确定要删除 "${node.title}" 吗？${warningText}`,
    okText: '删除',
    okType: 'danger',
    cancelText: '取消',
    async onOk() {
      try {
        await knowledgeApi.deleteNode(node.key)
        message.success('删除成功')
        await loadNodes()
      } catch (error) {
        message.error('删除失败')
      }
    }
  })
}

// 显示文档详情
const showDocDetail = (node: SmartTreeNode) => {
  detailDoc.value = node as TreeNode
  docDetailVisible.value = true
}

// 解析文档
const parseDocument = async (node: SmartTreeNode) => {
  try {
    await knowledgeApi.parseDocument('default', node.key, node.filePath)
    message.success('开始解析文档')
    await loadNodes()
  } catch (error) {
    message.error('解析失败')
  }
}

// 查看文档
const viewDocument = (node: SmartTreeNode) => {
  console.log('查看文档:', node)
}

// 切换可见性
const toggleVisible = async (node: SmartTreeNode) => {
  try {
    await knowledgeApi.updateNode(node.key, {
      visible: !node.visible
    })
    message.success('更新成功')
    await loadNodes()
  } catch (error) {
    message.error('更新失败')
  }
}

// 处理 SmartTree 组件的文件拖拽上传事件
const handleFileDrop = async (files: File[], targetFolder: SmartTreeNode | null) => {
  if (targetFolder && !targetFolder.isFolder) {
    message.warning('仅支持拖拽到文件夹或根目录')
    return
  }
  const parentId = targetFolder?.key
  for (const file of files) {
    if (smartTreeRef.value?.validateFileType(file)) {
      await uploadFile(file, parentId)
    } else {
      const allowedTypes = smartTreeRef.value?.getAllowedFileTypesDesc() || '指定类型'
      message.warning(`不支持的文件类型: ${file.name}，请上传 ${allowedTypes} 文件`)
    }
  }
}

// 上传文件
const uploadFile = async (file: File, parentId?: string) => {
  try {
    await knowledgeApi.uploadDocument('default', file, parentId)
    message.success(`上传成功: ${file.name}`)
    await loadNodes()
  } catch (error) {
    message.error(`上传失败: ${file.name}`)
  }
}

// 处理文件夹上传
const handleFolderUpload = (file: File, folderId: string) => {
  uploadFile(file, folderId)
}

// 树拖拽
const onTreeDrop = async (info: any) => {
  const { dragNode, node: dropNode } = info
  if (!dragNode || !dropNode) {
    return
  }

  if (dragNode.key === dropNode.key) {
    return
  }

  const nodeId = dragNode.key as string
  const isDropNodeFolder = dropNode.dataRef?.isFolder === true
  const dropToGap = info.dropToGap

  if (!dropToGap && !isDropNodeFolder) {
    message.warning('不能将节点拖入文件')
    await loadNodes()
    return
  }

  const findNodeByKey = (nodes: SmartTreeNode[], key: string): SmartTreeNode | null => {
    for (const node of nodes) {
      if (node.key === key) return node
      if (node.children?.length) {
        const child = findNodeByKey(node.children, key)
        if (child) return child
      }
    }
    return null
  }

  const isDescendantNode = (source: SmartTreeNode | null, targetKey: string): boolean => {
    if (!source?.children?.length) return false
    for (const child of source.children) {
      if (child.key === targetKey || isDescendantNode(child, targetKey)) return true
    }
    return false
  }

  const sourceNode = findNodeByKey(treeData.value as unknown as SmartTreeNode[], nodeId)
  if (isDescendantNode(sourceNode, dropNode.key as string)) {
    message.warning('不能拖拽到自身子级目录')
    await loadNodes()
    return
  }

  const newParentId = !dropToGap ? (dropNode.key as string) : ((dropNode.dataRef?.parentId as string | undefined) || null)

  try {
    await knowledgeApi.updateNode(nodeId, {
      parent_id: newParentId
    })
    message.success('移动成功')
    await loadNodes()
  } catch (error: any) {
    message.error('移动失败: ' + (error.response?.data?.detail || error?.message || '未知错误'))
    await loadNodes()
  }
}

const onInvalidDrop = async (reason: string) => {
  if (reason === 'drop-into-file') {
    message.warning('不能将节点拖入文件')
  } else if (reason === 'drop-to-descendant') {
    message.warning('不能拖拽到自身子级目录')
  }
  await loadNodes()
}

// ===== AI 对话相关 =====

/**
 * 处理 AI 对话发送消息
 */
const handleChatSend = async (message: string, _model: string) => {
  try {
    await chatStore.sendMessage(message, (_chunk) => {
      // 可以在这里处理每个 chunk，如果需要的话
    })
  } catch (error) {
    console.error('发送消息失败:', error)
  }
}

/**
 * AIChat 组件就绪回调
 */
const handleChatReady = () => {
  console.log('AIChat 组件已就绪')
}

// 组件挂载时加载数据
onMounted(() => {
  loadNodes()
})
</script>

<style lang="less" scoped>
.knowledge-workspace {
  height: 100%;
  background: var(--bg-primary, #141414);

  &.dark-mode {
    background: var(--bg-primary, #141414);
  }
}

.workspace-container {
  height: 100%;
}

.tree-container {
  height: 100%;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 8px;
  // 确保容器有明确的宽度限制
  width: 100%;
  min-width: 0;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 300px;
  cursor: pointer;
  border: 2px dashed var(--border-color, #434343);
  border-radius: 8px;
  margin: 16px;

  &:hover {
    border-color: #1890ff;
    background: rgba(24, 144, 255, 0.05);
  }

  .empty-icon {
    font-size: 48px;
    color: var(--text-secondary, rgba(255, 255, 255, 0.45));
    margin-bottom: 16px;
  }

  .empty-text {
    text-align: center;

    .empty-title {
      font-size: 16px;
      font-weight: 500;
      color: var(--text-primary, rgba(255, 255, 255, 0.88));
      margin-bottom: 8px;
    }

    .empty-desc {
      font-size: 14px;
      color: var(--text-secondary, rgba(255, 255, 255, 0.45));
      line-height: 1.6;
    }
  }
}

.drop-hint {
  position: absolute;
  bottom: 16px;
  left: 50%;
  transform: translateX(-50%);
  background: #1890ff;
  color: #fff;
  padding: 8px 16px;
  border-radius: 20px;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
}

.center-empty {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
