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
          <template #extra>
            <a-tooltip title="新建文件夹">
              <a-button type="text" size="small" @click="showCreateFolderModal">
                <FolderAddOutlined />
              </a-button>
            </a-tooltip>
          </template>

          <div
            class="tree-container"
            @dragover.prevent="onDragOver"
            @dragleave="onDragLeave"
            @drop.prevent="onDrop"
            :class="{ 'drag-over': isDragging }"
          >
            <!-- 空状态 -->
            <div v-if="!hasData" class="empty-state" @click="showCreateFolderModal">
              <FolderAddOutlined class="empty-icon" />
              <div class="empty-text">
                <div class="empty-title">新建文件夹</div>
                <div class="empty-desc">点击此处创建第一个文件夹<br>或拖拽 PDF 文件到此处上传</div>
              </div>
            </div>

            <!-- 知识树 -->
            <a-tree
              v-else
              v-model:selectedKeys="selectedKeys"
              v-model:expandedKeys="expandedKeys"
              :tree-data="treeData"
              :show-icon="false"
              :block-node="true"
              :draggable="true"
              @select="onSelect"
              @drop="onTreeDrop"
            >
              <template #title="{ data }">
                <TreeNodeItem
                  :data="data"
                  @rename="showRenameModal"
                  @create-sub-folder="showCreateSubFolderModal"
                  @delete="deleteNode"
                  @view-detail="showDocDetail"
                />
              </template>
            </a-tree>
          </div>

          <div v-if="isDragging" class="drop-hint">
            <CloudUploadOutlined />
            <span>释放上传至 {{ dropTargetFolder ? getFolderName(dropTargetFolder) : '根目录' }}</span>
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
        <RagChat
          ref="ragChatRef"
          title="AI 对话"
          :icon="MessageOutlined"
          placeholder="输入问题，基于知识库回答..."
          @send="handleRagSend"
        />
      </template>
    </SplitPanes>

    <!-- 新建/重命名文件夹弹窗 -->
    <FolderModal
      v-model:visible="folderModalVisible"
      :title="folderModalTitle"
      :loading="modalLoading"
      :folder-tree-data="folderTreeData"
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
      @delete="deleteNode"
      @toggle-visible="toggleVisible"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, nextTick } from 'vue'
import { message, Modal } from 'ant-design-vue'
import {
  FolderOutlined,
  FolderAddOutlined,
  FileSearchOutlined,
  MessageOutlined,
  CloudUploadOutlined
} from '@ant-design/icons-vue'

// 导入 packages 中的组件和 composables
import { SplitPanes, Panel, useTheme } from '@angineer/ui-kit'
import { RagChat, useKnowledgeTree, type TreeNode } from '@angineer/docs-ui'
import { knowledgeApi } from '@/api/knowledge'

// 使用主题
const { isDark } = useTheme()

// 导入本地子组件
import TreeNodeItem from './components/TreeNodeItem.vue'
import FolderPreview from './components/FolderPreview.vue'
import DocumentPreview from './components/DocumentPreview.vue'
import FolderModal from './components/FolderModal.vue'
import DocDetailModal from './components/DocDetailModal.vue'

// 使用知识树 composable
const {
  treeData,
  selectedKeys,
  expandedKeys,
  selectedNode,
  folderTreeData,
  hasData,
  buildTree,
  findNode,
  getChildCount,
  getFolderName,
  selectNode
} = useKnowledgeTree()

// RagChat 组件引用
const ragChatRef = ref<InstanceType<typeof RagChat> | null>(null)

// 面板尺寸状态
const leftWidth = ref(350)
const centerWidth = ref(700)

// 处理 RAG 发送消息
const handleRagSend = async (message: string, model: string) => {
  try {
    const result = await knowledgeApi.ragQuery(message, 'default', 4, true)
    // 添加助手回复到聊天
    if (ragChatRef.value) {
      ragChatRef.value.addMessage({
        role: 'assistant',
        content: result.answer,
        sources: result.sources?.map((s: { title?: string }) => s.title || '未知来源')
      })
    }
  } catch (error) {
    console.error('RAG 查询失败:', error)
    if (ragChatRef.value) {
      ragChatRef.value.addMessage({
        role: 'assistant',
        content: '抱歉，查询失败，请稍后重试。'
      })
    }
  }
}

// 拖拽上传状态
const isDragging = ref(false)
const dropTargetFolder = ref<string | null>(null)

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
const onPanelResize = (leftSize: number, rightSize: number) => {
  leftWidth.value = leftSize
  // 中间面板宽度 = 总宽度 - 左 - 右
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
    const nodes = await knowledgeApi.getNodes('default', false)
    treeData.value = buildTree(nodes)
  } catch (error) {
    console.error('加载节点失败:', error)
    message.error('加载知识库节点失败')
  }
}

// 选择节点
const onSelect = async (keys: string[]) => {
  if (keys.length > 0) {
    selectNode(keys[0])
    if (selectedNode.value && !selectedNode.value.isFolder && selectedNode.value.status === 'completed') {
      await loadDocContent(selectedNode.value.key)
    }
  }
}

// 加载文档内容
const loadDocContent = async (docId: string) => {
  try {
    const result = await knowledgeApi.getDocument('default', docId)
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
const showRenameModal = (node: TreeNode) => {
  folderForm.value = {
    name: node.title,
    parentId: node.parentId,
    isNew: false,
    nodeId: node.key
  }
  folderModalVisible.value = true
}

// 显示创建子文件夹弹窗
const showCreateSubFolderModal = (parentId: string) => {
  folderForm.value = { name: '', parentId, isNew: true, nodeId: '' }
  folderModalVisible.value = true
}

// 处理文件夹弹窗确认
const handleFolderModalOk = async () => {
  if (!folderForm.value.name.trim()) {
    message.warning('请输入名称')
    return
  }

  modalLoading.value = true
  try {
    if (folderForm.value.isNew) {
      await knowledgeApi.createNode({
        title: folderForm.value.name,
        node_type: 'folder',
        library_id: 'default',
        parent_id: folderForm.value.parentId,
        visible: true
      })
      message.success('文件夹创建成功')
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
const deleteNode = async (key: string) => {
  const node = findNode(treeData.value, key)
  if (!node) return

  Modal.confirm({
    title: `删除${node.isFolder ? '文件夹' : '文档'}`,
    content: `确定要删除 "${node.title}" 吗？${node.isFolder ? '文件夹内的所有内容将被删除。' : ''}`,
    okText: '删除',
    okType: 'danger',
    cancelText: '取消',
    async onOk() {
      try {
        await knowledgeApi.deleteNode(key)
        message.success('删除成功')
        if (selectedNode.value?.key === key) {
          selectedNode.value = null
          selectedKeys.value = []
        }
        await loadNodes()
      } catch (error) {
        message.error('删除失败')
      }
    }
  })
}

// 显示文档详情
const showDocDetail = (node: TreeNode) => {
  detailDoc.value = node
  docDetailVisible.value = true
}

// 切换可见性
const toggleVisible = async (key: string, checked: boolean) => {
  try {
    await knowledgeApi.updateNode(key, { visible: checked })
    message.success(`已${checked ? '共享到前台' : '设为本地'}`)
    await loadNodes()
    if (selectedNode.value?.key === key) {
      selectedNode.value.visible = checked
    }
    if (detailDoc.value?.key === key) {
      detailDoc.value.visible = checked
    }
  } catch (error) {
    message.error('更新失败')
  }
}

// 解析文档
const parseDocument = async (docId: string) => {
  const node = findNode(treeData.value, docId)
  if (!node) return

  try {
    await knowledgeApi.updateNode(docId, { status: 'processing' })
    node.status = 'processing'
    message.loading({ content: `正在解析 "${node.title}"...`, key: docId, duration: 0 })

    const result = await knowledgeApi.parseDocument(docId, 'default')

    if (result.success) {
      message.success({ content: `"${node.title}" 解析完成`, key: docId })
      node.status = 'completed'
      await loadDocContent(docId)
    } else {
      throw new Error(result.message || '解析失败')
    }
  } catch (error: any) {
    message.error({ content: `"${node.title}" 解析失败：${error.message}`, key: docId })
    node.status = 'failed'
    await knowledgeApi.updateNode(docId, { status: 'failed' })
  }
}

// 查看文档
const viewDocument = (docId: string) => {
  window.open(`/api/knowledge/document/${docId}/view`, '_blank')
}

// 拖拽上传相关
const onDragOver = (e: DragEvent) => {
  isDragging.value = true
}

const onDragLeave = () => {
  isDragging.value = false
  dropTargetFolder.value = null
}

const onDrop = async (e: DragEvent) => {
  isDragging.value = false
  const files = e.dataTransfer?.files
  if (!files || files.length === 0) return

  const folderId = dropTargetFolder.value

  for (const file of Array.from(files)) {
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      message.warning(`跳过 ${file.name}，仅支持 PDF 文件`)
      continue
    }
    await uploadFile(file, folderId)
  }
  dropTargetFolder.value = null
}

const onTreeDrop = (info: any) => {
  const dropKey = info.node.key
  const dropNode = findNode(treeData.value, dropKey)
  if (dropNode?.isFolder) {
    dropTargetFolder.value = dropKey
  }
}

// 文件夹上传
const handleFolderUpload = async (file: File, folderId: string) => {
  await uploadFile(file, folderId)
  return false
}

// 上传文件
const uploadFile = async (file: File, folderId?: string | null) => {
  const docName = file.name.replace(/\.pdf$/i, '')

  try {
    const node = await knowledgeApi.createNode({
      title: docName,
      node_type: 'document',
      library_id: 'default',
      parent_id: folderId || undefined,
      visible: false,
      status: 'uploading'
    })

    message.success(`"${docName}" 已添加到知识树`)
    await loadNodes()

    if (folderId && !expandedKeys.value.includes(folderId)) {
      expandedKeys.value.push(folderId)
    }

    setTimeout(() => {
      parseDocument(node.id)
    }, 500)
  } catch (error) {
    message.error(`"${docName}" 添加失败`)
  }
}

// 发送聊天消息
const sendMessage = async () => {
  await sendRagMessage()
}

onMounted(() => {
  loadNodes()
})
</script>

<style lang="less" scoped>
.knowledge-workspace {
  height: 100%;
  width: 100%;
  display: flex;
  flex-direction: column;
  background: var(--bg-primary, #141414);
  overflow: hidden;
  transition: background-color 0.3s ease;

  .workspace-container {
    flex: 1;
    width: 100%;

    :deep(.pane) {
      overflow: hidden;
    }

    // 中间面板空状态样式
    :deep(.center-empty) {
      .ant-empty-description {
        color: rgba(255, 255, 255, 0.65);
      }
    }
  }

  .tree-container {
    padding: 8px;
    min-height: 100%;

    :deep(.ant-tree) {
      .ant-tree-treenode {
        padding: 2px 0;

        &:hover {
          background: #f5f5f5;
        }

        &.ant-tree-treenode-selected {
          background: #e6f7ff;
        }

        .ant-tree-indent {
          .ant-tree-indent-unit {
            width: 12px;
          }
        }
      }

      .ant-tree-node-content-wrapper {
        flex: 1;
        min-width: 0;
        padding: 0 4px;
      }
    }

    &.drag-over {
      background: rgba(24, 144, 255, 0.05);
    }

    .empty-state {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      height: 100%;
      min-height: 300px;
      cursor: pointer;
      padding: 24px;
      border: 2px dashed #d9d9d9;
      border-radius: 8px;
      margin: 16px;
      transition: all 0.3s ease;

      &:hover {
        border-color: #1890ff;
        background: rgba(24, 144, 255, 0.02);

        .empty-icon {
          color: #1890ff;
          transform: scale(1.1);
        }
      }

      .empty-icon {
        font-size: 64px;
        color: #bfbfbf;
        margin-bottom: 16px;
        transition: all 0.3s ease;
      }

      .empty-text {
        text-align: center;

        .empty-title {
          font-size: 16px;
          font-weight: 500;
          color: #262626;
          margin-bottom: 8px;
        }

        .empty-desc {
          font-size: 13px;
          color: #8c8c8c;
          line-height: 1.6;
        }
      }
    }
  }

  .drop-hint {
    position: absolute;
    bottom: 16px;
    left: 50%;
    transform: translateX(-50%);
    display: flex;
    align-items: center;
    gap: 8px;
    background: #1890ff;
    color: #fff;
    padding: 8px 16px;
    border-radius: 20px;
    font-size: 13px;
    white-space: nowrap;
    box-shadow: 0 4px 12px rgba(24, 144, 255, 0.4);

    .anticon {
      font-size: 16px;
    }
  }
}

// Dark mode
:global(.dark-mode) {
  .knowledge-workspace {
    background: #141414;

    .tree-container {
      :deep(.ant-tree) {
        .ant-tree-treenode {
          &:hover {
            background: #272727;
          }

          &.ant-tree-treenode-selected {
            background: #111b26;
          }
        }
      }

      .empty-state {
        border-color: #424242;

        &:hover {
          border-color: #1890ff;
          background: rgba(24, 144, 255, 0.05);
        }

        .empty-icon {
          color: #595959;
        }

        .empty-text {
          .empty-title {
            color: rgba(255, 255, 255, 0.85);
          }

          .empty-desc {
            color: rgba(255, 255, 255, 0.45);
          }
        }
      }
    }
  }
}
</style>
