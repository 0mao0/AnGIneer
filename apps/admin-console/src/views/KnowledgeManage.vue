<template>
  <div ref="workspaceRef" class="knowledge-workspace" :class="{ 'dark-mode': isDark }">
    <!-- 使用 SplitPanes 三栏布局组件 - 比例 1.5:6:2.5 -->
    <SplitPanes
      class="workspace-container"
      :initial-left-ratio="panelRatios.left"
      :initial-right-ratio="panelRatios.right"
      @resize="onPanelResize"
    >
      <!-- 左侧：知识树 -->
      <template #left>
        <Panel title="知识树" :icon="FolderOutlined" contentClass="tree-panel-content">

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

            <!-- 知识树 - 使用 KnowledgeTree 语义组件 -->
            <KnowledgeTree
              v-else
              ref="smartTreeRef"
              :tree-data="treeData"
              v-bind="smartTreeProps"
              @select="onTreeSelect"
              @rename="showRenameModal"
              @add-folder="showCreateSubFolderModal"
              @add-file="showCreateFileModal"
              @delete="handleDeleteNode"
              @view="showDocDetail"
              @drop="onTreeDrop"
              @drop-root="onTreeDropRoot"
              @drop-invalid="onInvalidDrop"
              @file-drop="handleFileDrop"
            >
              <!-- 自定义图标 -->
              <template #icon="{ node }">
                <FolderOutlined v-if="node?.isFolder" style="color: #faad14" />
                <FilePdfOutlined v-else-if="getFileType(node) === 'pdf'" style="color: #ff4d4f" />
                <FileWordOutlined v-else-if="getFileType(node) === 'word'" style="color: #1890ff" />
                <FileMarkdownOutlined v-else-if="getFileType(node) === 'markdown'" style="color: #13c2c2" />
                <FileTextOutlined v-else style="color: #8c8c8c" />
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
            </KnowledgeTree>
          </div>
        </Panel>
      </template>

      <!-- 中间：文档解析/预览 -->
      <template #center>
        <Panel title="文档解析" :icon="FileSearchOutlined">
          <!-- 面板操作按钮 -->
          <template #extra>
            <a-space v-if="selectedNode && !selectedNode.isFolder">
              <a-button
                v-if="docParsedWorkspaceRef?.showHighlightToggle"
                size="small"
                class="header-action-btn"
                :type="docParsedWorkspaceRef?.highlightLinkEnabled ? 'primary' : 'default'"
                @click="docParsedWorkspaceRef?.toggleHighlightLink"
              >
                高亮联动
              </a-button>
              <a-button
                type="primary"
                size="small"
                class="header-action-btn"
                :loading="selectedNode.status === 'processing'"
                @click="parseDocument(selectedNode)"
              >
                {{ docParsedWorkspaceRef?.parseButtonText || '开始解析' }}
              </a-button>
            </a-space>
          </template>

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
            <PDFParsedWorkspace
              ref="docParsedWorkspaceRef"
              :node="selectedNode"
              :content="docContent"
              :structured-stats="structuredStats"
              :structured-items="structuredItems"
              :dark-mode="isDark"
              :graph-data="graphData"
              :on-update-structured-node="updateStructuredNode"
              :on-batch-structured-operation="batchOperateStructuredNodes"
              :on-undo-last-operation="undoLastStructuredOperation"
              @parse="parseDocument"
              @toggle-visible="toggleVisible"
              @query-structured="loadStructuredIndex"
            />
          </template>
        </Panel>
      </template>

      <!-- 右侧：AI 对话 -->
      <template #right>
        <Panel title="AI 对话" :icon="MessageOutlined">
          <KnowledgeChatPanel
            title=""
            placeholder="输入消息，Ctrl+Enter 发送..."
            :show-context-info="true"
          />
        </Panel>
      </template>
    </SplitPanes>

    <!-- 新建/重命名文件夹弹窗 -->
    <FolderModal
      v-model:visible="folderModalVisible"
      :title="folderModalTitle"
      :loading="modalLoading"
      :folder-tree-data="folderSelectTreeData"
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
 * 知识库管理页面 - 使用 KnowledgeChatPanel 组件进行 AI 对话
 */
import { ref, computed, nextTick, onMounted, onBeforeUnmount, watch, h } from 'vue'
import { message, Modal } from 'ant-design-vue'
import {
  FolderOutlined,
  FolderAddOutlined,
  FileSearchOutlined,
  MessageOutlined,
  FilePdfOutlined,
  FileWordOutlined,
  FileMarkdownOutlined,
  FileTextOutlined
} from '@ant-design/icons-vue'

// 导入 packages 中的组件和 composables
import { SplitPanes, Panel, useTheme } from '@angineer/ui-kit'
import {
  KnowledgeChatPanel,
  KnowledgeTree,
  PDFParsedWorkspace,
  type SmartTreeNode,
  type KnowledgeTreeNode,
  type KnowledgeStrategy,
  type ParseTaskInfo,
  type StructuredIndexItem,
  type StructuredBatchOperationPayload,
  type StructuredNodeUpdatePayload,
  type StructuredStats,
  getPreviewFileType,
  mapNodeStatusText,
  createResourceNodeFromKnowledge,
  createOpenResourcePayload
} from '@angineer/docs-ui'
import { useKnowledgeTree } from '@angineer/docs-ui'
import { knowledgeApi } from '@/api/knowledge'
import { getWebDocumentUrl } from '../../../shared/ports'

// 使用主题
const { isDark } = useTheme()

// 导入本地子组件
import FolderPreview from './components/FolderPreview.vue'
import FolderModal from './components/FolderModal.vue'
import DocDetailModal from './components/DocDetailModal.vue'

// SmartTree 组件引用
const smartTreeRef = ref<InstanceType<typeof KnowledgeTree> | null>(null)
// PDFParsedWorkspace 组件引用
const docParsedWorkspaceRef = ref<InstanceType<typeof PDFParsedWorkspace> | null>(null)

// 使用知识树 composable
const {
  treeData,
  selectedKeys,
  selectedNode,
  hasData,
  buildTree,
  folderTreeData,
  getChildCount,
  getFolderName
} = useKnowledgeTree()

const allowedFileTypes = ['.pdf', '.doc', '.docx', '.md']
const PANEL_LAYOUT_STORAGE_KEY = 'angineer-admin-knowledge-layout-v1'
const workspaceRef = ref<HTMLElement | null>(null)

const clampRatio = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value))

const panelRatios = ref({
  left: 0.15,
  right: 0.25
})

// 面板尺寸状态
const parsePollTimer = ref<number | null>(null)
const structuredStats = ref<StructuredStats>({})
const structuredItems = ref<StructuredIndexItem[]>([])
const graphData = ref<{ nodes: any[]; edges: any[] } | null>(null)

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
const detailDoc = ref<KnowledgeTreeNode | null>(null)

// 文档内容
const docContent = ref('')
const docContentDocId = ref('')

// 计算属性
const folderModalTitle = computed(() => folderForm.value.isNew ? '新建文件夹' : '重命名')
const folderSelectTreeData = computed(() => [
  { value: '__root__', title: '根目录' },
  ...folderTreeData.value
])
const smartTreeProps = {
  showSearch: true,
  searchPlaceholder: '搜索文档...',
  showStatus: true,
  draggable: true,
  allowAddFile: true,
  allowedFileTypes: allowedFileTypes,
  emptyText: '暂无文档'
}

// 面板调整大小回调
const onPanelResize = (leftSize: number, rightSize: number) => {
  const containerWidth = workspaceRef.value?.clientWidth || window.innerWidth
  if (containerWidth <= 0) return
  const left = clampRatio(leftSize / containerWidth, 0.1, 0.45)
  const right = clampRatio(rightSize / containerWidth, 0.16, 0.45)
  if (left + right >= 0.85) return
  panelRatios.value = { left, right }
  localStorage.setItem(PANEL_LAYOUT_STORAGE_KEY, JSON.stringify(panelRatios.value))
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
const getStatusText = (status: string) => mapNodeStatusText(status)

const getFileType = (node?: Partial<SmartTreeNode> | null) => getPreviewFileType(node)

const keepCurrentPreview = (docId: string) => docContentDocId.value === docId && Boolean(docContent.value)

const extractPageHintFromLine = (line: string): number | null => {
  const match = line.match(/[（(]\s*(\d{1,4})\s*[）)]\s*$/)
  if (!match) return null
  const page = Number(match[1])
  if (!Number.isFinite(page) || page <= 0) return null
  return Math.round(page)
}

const buildMiddleFallbackItems = (content: string): StructuredIndexItem[] => {
  if (!content.trim()) return []
  const lines = content.split('\n')
  const result: StructuredIndexItem[] = []
  let orderIndex = 0
  lines.forEach((line: string, index: number) => {
    const trimmed = (line || '').trim()
    if (!trimmed) return
    const headingMatch = trimmed.match(/^(#{1,6})\s+(.+)$/)
    const numberedMatch = trimmed.match(/^(\d+(?:\.\d+)*)(?:[、.)])?\s*(.*)$/)
    if (!headingMatch && !numberedMatch) return
    const numberedPrefix = numberedMatch?.[1] || ''
    const numberedText = (numberedMatch?.[2] || '').trim()
    const text = (
      headingMatch?.[2]
      || (numberedPrefix && numberedText ? `${numberedPrefix} ${numberedText}` : numberedPrefix)
      || numberedText
      || ''
    ).trim().slice(0, 200)
    if (!text) return
    const pageHint = extractPageHintFromLine(trimmed)
    result.push({
      id: `middle-${index + 1}`,
      item_type: headingMatch ? 'heading' : 'section',
      title: text,
      content: text,
      order_index: orderIndex++,
      meta: {
        line_start: index + 1,
        line_end: index + 1,
        heading_level: headingMatch ? headingMatch[1].length : undefined,
        page: pageHint ?? undefined,
        page_no: pageHint ?? undefined
      }
    })
  })
  return result
}

// 加载节点
const loadNodes = async (focusNodeKey?: string) => {
  try {
    const response = await knowledgeApi.getNodes('default', false) as unknown as any[]
    treeData.value = buildTree(response)
    if (focusNodeKey) {
      const findParentChain = (nodes: SmartTreeNode[], key: string, parents: string[] = []): string[] | null => {
        for (const node of nodes) {
          if (node.key === key) return parents
          if (node.children?.length) {
            const found = findParentChain(node.children, key, [...parents, node.key])
            if (found) return found
          }
        }
        return null
      }
      const findNode = (nodes: SmartTreeNode[], key: string): SmartTreeNode | null => {
        for (const node of nodes) {
          if (node.key === key) return node
          if (node.children?.length) {
            const found = findNode(node.children, key)
            if (found) return found
          }
        }
        return null
      }
      const parents = findParentChain(treeData.value as unknown as SmartTreeNode[], focusNodeKey) || []
      if (smartTreeRef.value) {
        smartTreeRef.value.expandedKeys = Array.from(new Set([
          ...(smartTreeRef.value.expandedKeys || []),
          ...parents
        ]))
        smartTreeRef.value.selectedKeys = [focusNodeKey]
      }
      selectedKeys.value = [focusNodeKey]
      const node = findNode(treeData.value as unknown as SmartTreeNode[], focusNodeKey)
      if (node) {
        selectedNode.value = node as unknown as KnowledgeTreeNode
        if (!node.isFolder) {
          if (node.status === 'completed') {
            await loadDocContent(node.key)
            await loadStructuredStats(node.key)
          } else {
            if (!keepCurrentPreview(node.key)) {
              docContent.value = ''
              docContentDocId.value = ''
              graphData.value = null
              structuredStats.value = {}
              structuredItems.value = []
            }
          }
          if (node.status === 'processing' && (node as any).parseTaskId) {
            startParsePolling((node as any).parseTaskId, node.key)
          } else {
            stopParsePolling()
          }
        }
      }
    }
  } catch (error) {
    console.error('加载节点失败:', error)
    message.error('加载知识库节点失败')
  }
}

// SmartTree 选择节点回调
const onTreeSelect = async (keys: string[], nodes: SmartTreeNode[]) => {
  selectedKeys.value = keys
  if (nodes.length > 0) {
    const node = nodes[0] as KnowledgeTreeNode
    selectedNode.value = node
    if (!node.isFolder) {
      if (node.status === 'completed') {
        await loadDocContent(node.key)
        await loadStructuredStats(node.key)
        if (node.strategy) {
          await loadStructuredIndex()
        } else {
          structuredItems.value = buildMiddleFallbackItems(docContent.value)
        }
      } else {
        if (!keepCurrentPreview(node.key)) {
          docContent.value = ''
          docContentDocId.value = ''
          graphData.value = null
          structuredStats.value = {}
          structuredItems.value = []
        }
      }
      if (node.status === 'processing' && node.parseTaskId) {
        startParsePolling(node.parseTaskId, node.key)
      } else {
        stopParsePolling()
      }
    }
  }
}

// 加载文档内容
const loadDocContent = async (docId: string) => {
  try {
    const result = await knowledgeApi.getDocument('default', docId) as unknown as {
      content: string
      storage?: { source_file?: string | null }
      graph_data?: { nodes: any[]; edges: any[] } | null
    }
    docContent.value = result.content || '暂无内容'
    docContentDocId.value = docId
    graphData.value = result?.graph_data || null
    if (selectedNode.value && selectedNode.value.key === docId && result?.storage?.source_file) {
      selectedNode.value.filePath = result.storage.source_file
    }
  } catch (error) {
    docContent.value = ''
    docContentDocId.value = ''
    graphData.value = null
    structuredStats.value = {}
  }
}

const loadStructuredStats = async (docId: string) => {
  try {
    const result = await knowledgeApi.getStructuredStats(docId) as any
    structuredStats.value = result || {}
  } catch (error) {
    structuredStats.value = {}
  }
}

const loadStructuredIndex = async (itemType?: string, keyword?: string) => {
  if (!selectedNode.value || selectedNode.value.isFolder) {
    structuredItems.value = []
    return
  }
  const strategy = selectedNode.value.strategy as KnowledgeStrategy | undefined
  if (!strategy) {
    structuredItems.value = []
    return
  }
  try {
    const result = await knowledgeApi.getStructuredIndex(selectedNode.value.key, strategy, itemType, keyword)
    const fromApi = Array.isArray(result?.items) ? result.items : []
    structuredItems.value = fromApi.length ? fromApi : buildMiddleFallbackItems(docContent.value)
  } catch (error) {
    structuredItems.value = buildMiddleFallbackItems(docContent.value)
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

// 生成删除确认弹窗内容
const buildDeleteConfirmContent = (node: SmartTreeNode, preview: {
  total_nodes: number
  folder_count: number
  document_count: number
  sample_doc_titles: string[]
}) => {
  const stats = preview.document_count > 0
    ? `${preview.document_count} 个文档${preview.folder_count > 0 ? `、${preview.folder_count} 个文件夹` : ''}`
    : `${preview.folder_count} 个文件夹`
  const lines = [
    `确定删除 "${node.title}"？此操作不可恢复。`,
    `将删除 ${stats}（共 ${preview.total_nodes} 个节点）。`
  ]
  return h('div', { style: 'white-space: pre-line;' }, [
    ...lines.map(line => h('div', line)),
    ...(preview.sample_doc_titles.length > 0
      ? [h('div', { style: 'margin-top: 8px; color: #666;' }, preview.sample_doc_titles.slice(0, 3).join('、'))]
      : [])
  ])
}

// 显示删除确认弹窗
const showDeleteConfirm = (
  node: SmartTreeNode,
  nodeType: string,
  preview: {
    total_nodes: number
    folder_count: number
    document_count: number
    sample_doc_titles: string[]
  }
) => {
  Modal.confirm({
    title: `确认删除${nodeType}`,
    content: buildDeleteConfirmContent(node, preview),
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

// 删除节点
const handleDeleteNode = async (node: SmartTreeNode) => {
  const nodeType = node.isFolder ? '文件夹' : '文件'
  try {
    const preview = await knowledgeApi.getDeleteNodePreview(node.key)
    showDeleteConfirm(node, nodeType, preview)
  } catch (error) {
    console.error('获取删除影响范围失败。', error)
    message.error('获取删除影响范围失败，请确认后端服务已更新并重试')
  }
}

// 显示文档详情
const showDocDetail = (node: SmartTreeNode) => {
  detailDoc.value = node as KnowledgeTreeNode
  docDetailVisible.value = true
}

// 解析文档
const parseDocument = async (node: SmartTreeNode) => {
  try {
    if (selectedNode.value && selectedNode.value.key === node.key) {
      selectedNode.value.status = 'processing'
      selectedNode.value.parseError = ''
      selectedNode.value.parseProgress = 0
      selectedNode.value.parseStage = 'queued'
    }
    const result = await knowledgeApi.parseDocumentAsync('default', node.key, node.filePath) as any
    const taskId = result?.task_id
    message.success('开始解析文档')
    await loadNodes(node.key)
    if (taskId) {
      startParsePolling(taskId, node.key)
    }
  } catch (error) {
    const detail = (error as any)?.response?.data?.detail || (error as any)?.message
    message.error(detail ? `解析失败: ${detail}` : '解析失败')
  }
}

/* 更新单个结构节点并刷新当前文档的索引数据。 */
const updateStructuredNode = async (payload: StructuredNodeUpdatePayload) => {
  if (!selectedNode.value || selectedNode.value.isFolder) return
  try {
    await knowledgeApi.updateDocumentBlock('default', selectedNode.value.key, payload)
    await loadDocContent(selectedNode.value.key)
    await loadStructuredStats(selectedNode.value.key)
    await loadStructuredIndex()
    message.success('节点内容已更新')
  } catch (error) {
    const detail = (error as any)?.response?.data?.detail || (error as any)?.message
    message.error(detail ? `节点更新失败: ${detail}` : '节点更新失败')
    throw error
  }
}

const batchOperateStructuredNodes = async (payload: StructuredBatchOperationPayload) => {
  if (!selectedNode.value || selectedNode.value.isFolder) return
  try {
    const result = await knowledgeApi.batchOperateDocumentBlocks('default', selectedNode.value.key, payload)
    await loadDocContent(selectedNode.value.key)
    await loadStructuredStats(selectedNode.value.key)
    await loadStructuredIndex()
    if (payload.operation === 'merge') {
      const targetBlockId = String(result.target_block_id || payload.targetBlockId || '').trim()
      if (targetBlockId) {
        await nextTick()
        docParsedWorkspaceRef.value?.setActiveLinkedItem(targetBlockId)
      }
    }
    if (payload.operation === 'split') {
      const focusBlockId = String(result.created_block_ids?.[0] || payload.blockIds?.[0] || '').trim()
      if (focusBlockId) {
        await nextTick()
        docParsedWorkspaceRef.value?.setActiveLinkedItem(focusBlockId)
      }
    }
    if (payload.operation === 'relevel') {
      const focusBlockId = String(result.updated_block_ids?.[0] || payload.blockIds?.[0] || '').trim()
      if (focusBlockId) {
        await nextTick()
        docParsedWorkspaceRef.value?.setActiveLinkedItem(focusBlockId)
      }
    }
    const successText = payload.operation === 'merge'
      ? '批量合并已完成'
      : payload.operation === 'relevel'
        ? (
            typeof payload.targetLevel === 'number'
              ? `已将 ${result.updated_block_ids?.length || payload.blockIds.length || 0} 个节点设为 L${payload.targetLevel}`
              : `已调整 ${result.updated_block_ids?.length || payload.blockIds.length || 0} 个标题层级`
          )
      : payload.operation === 'delete'
        ? `已删除 ${result.removed_block_ids?.length || payload.blockIds.length || 0} 个 block`
        : `Block 已拆分为 ${Math.max(2, (result.created_block_ids?.length || 0) + 1)} 段`
    message.success(successText)
  } catch (error) {
    const detail = (error as any)?.response?.data?.detail || (error as any)?.message
    message.error(detail ? `结构操作失败: ${detail}` : '结构操作失败')
    throw error
  }
}

const undoLastStructuredOperation = async () => {
  if (!selectedNode.value || selectedNode.value.isFolder) return
  try {
    const result = await knowledgeApi.undoLastDocumentBlockOperation('default', selectedNode.value.key)
    await loadDocContent(selectedNode.value.key)
    await loadStructuredStats(selectedNode.value.key)
    await loadStructuredIndex()
    const firstRestoredId = String(result.restored_block_ids?.[0] || '').trim()
    if (firstRestoredId) {
      await nextTick()
      docParsedWorkspaceRef.value?.setActiveLinkedItem(firstRestoredId)
    }
    message.success('最近一次结构操作已撤回')
  } catch (error) {
    const detail = (error as any)?.response?.data?.detail || (error as any)?.message
    message.error(detail ? `撤回结构操作失败: ${detail}` : '撤回结构操作失败')
    throw error
  }
}

const stopParsePolling = () => {
  if (parsePollTimer.value) {
    window.clearInterval(parsePollTimer.value)
    parsePollTimer.value = null
  }
}

const startParsePolling = (taskId: string, docId: string) => {
  stopParsePolling()
  parsePollTimer.value = window.setInterval(async () => {
    try {
      const task = await knowledgeApi.getParseTask(taskId) as ParseTaskInfo
      if (selectedNode.value && selectedNode.value.key === docId) {
        selectedNode.value.parseProgress = task.progress || 0
        selectedNode.value.parseStage = task.stage || ''
        selectedNode.value.parseError = task.error || ''
        selectedNode.value.status = task.status === 'completed'
          ? 'completed'
          : task.status === 'failed'
            ? 'failed'
            : 'processing'
      }
      if (task.status === 'completed' || task.status === 'failed') {
        stopParsePolling()
        await loadNodes(docId)
        if (task.status === 'completed') {
          await loadDocContent(docId)
          await loadStructuredStats(docId)
          message.success('文档解析完成')
        } else {
          message.error(task.error || '文档解析失败')
        }
      }
    } catch (error) {
      stopParsePolling()
    }
  }, 1500)
}

// 查看文档
const viewDocument = (node: SmartTreeNode) => {
  const resource = createResourceNodeFromKnowledge(node, 'default')
  const payload = createOpenResourcePayload(resource)
  if (!payload) {
    message.warning('当前节点不可查看')
    return
  }
  const targetUrl = getWebDocumentUrl(String(payload.props.docId || node.key))
  window.open(targetUrl, '_blank', 'noopener,noreferrer')
}

// 切换可见性
const toggleVisible = async (node: SmartTreeNode) => {
  const targetVisible = typeof node.visible === 'boolean' ? node.visible : !node.visible
  try {
    await knowledgeApi.updateNode(node.key, {
      visible: targetVisible
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
    const result = await knowledgeApi.uploadDocument('default', file, parentId) as any
    message.success(`上传成功: ${file.name}`)
    const focusNodeKey = result?.doc_id || result?.node?.id
    await loadNodes(focusNodeKey)
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
  const dropPos = String(dropNode.pos || '')
  const dropPosParts = dropPos.split('-')
  const dropNodeIndex = Number(dropPosParts[dropPosParts.length - 1] || 0)
  const relativeDropPosition = (info.dropPosition as number) - dropNodeIndex

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

  const nextTree = JSON.parse(JSON.stringify(treeData.value as unknown as SmartTreeNode[])) as SmartTreeNode[]
  let dragObj: SmartTreeNode | undefined

  const removeNode = (nodes: SmartTreeNode[]): boolean => {
    for (let i = 0; i < nodes.length; i++) {
      if (nodes[i].key === nodeId) {
        dragObj = nodes[i]
        nodes.splice(i, 1)
        return true
      }
      const childNodes = nodes[i].children
      if (childNodes?.length && removeNode(childNodes)) {
        return true
      }
    }
    return false
  }

  const insertIntoNode = (nodes: SmartTreeNode[], targetKey: string, node: SmartTreeNode): boolean => {
    for (const current of nodes) {
      if (current.key === targetKey) {
        if (!current.children) current.children = []
        current.children.push(node)
        return true
      }
      if (current.children?.length && insertIntoNode(current.children, targetKey, node)) {
        return true
      }
    }
    return false
  }

  const insertAtGap = (nodes: SmartTreeNode[], targetKey: string, node: SmartTreeNode): boolean => {
    for (let i = 0; i < nodes.length; i++) {
      if (nodes[i].key === targetKey) {
        const insertIndex = relativeDropPosition < 0 ? i : i + 1
        nodes.splice(insertIndex, 0, node)
        return true
      }
      const childNodes = nodes[i].children
      if (childNodes?.length && insertAtGap(childNodes, targetKey, node)) {
        return true
      }
    }
    return false
  }

  const getSiblingList = (nodes: SmartTreeNode[], parentId: string | null): SmartTreeNode[] => {
    if (!parentId) return nodes
    const walk = (items: SmartTreeNode[]): SmartTreeNode | null => {
      for (const item of items) {
        if (item.key === parentId) return item
        if (item.children?.length) {
          const found = walk(item.children)
          if (found) return found
        }
      }
      return null
    }
    const parentNode = walk(nodes)
    return parentNode?.children || []
  }

  const findParentIdByKey = (
    nodes: SmartTreeNode[],
    key: string,
    parentId: string | null = null
  ): string | null | undefined => {
    for (const node of nodes) {
      if (node.key === key) {
        return parentId
      }
      if (node.children?.length) {
        const found = findParentIdByKey(node.children, key, node.key)
        if (found !== undefined) {
          return found
        }
      }
    }
    return undefined
  }

  removeNode(nextTree)
  if (!dragObj) {
    await loadNodes()
    return
  }

  if (!dropToGap) {
    insertIntoNode(nextTree, dropNode.key as string, dragObj)
  } else {
    insertAtGap(nextTree, dropNode.key as string, dragObj)
  }

  const fallbackParentId = (dropNode.dataRef?.parentId as string | undefined) || null
  const resolvedGapParentId = findParentIdByKey(nextTree, dropNode.key as string)
  const newParentId = !dropToGap
    ? (dropNode.key as string)
    : (resolvedGapParentId === undefined ? fallbackParentId : resolvedGapParentId)

  const siblings = getSiblingList(nextTree, newParentId)

  try {
    for (let index = 0; index < siblings.length; index++) {
      const sibling = siblings[index]
      await knowledgeApi.updateNode(sibling.key, {
        parent_id: newParentId,
        sort_order: index
      })
    }
    message.success('移动成功')
    await loadNodes(nodeId)
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

const onTreeDropRoot = async (dragNodeKey: string) => {
  try {
    const rootNodes = (treeData.value as unknown as SmartTreeNode[]).filter(node => node.key !== dragNodeKey)
    for (let index = 0; index < rootNodes.length; index++) {
      const node = rootNodes[index]
      await knowledgeApi.updateNode(node.key, {
        parent_id: null,
        sort_order: index
      })
    }
    await knowledgeApi.updateNode(dragNodeKey, {
      parent_id: null,
      sort_order: rootNodes.length
    })
    message.success('已移动到根目录')
    await loadNodes(dragNodeKey)
  } catch (error: any) {
    message.error('移动失败: ' + (error.response?.data?.detail || error?.message || '未知错误'))
    await loadNodes()
  }
}

// 组件挂载时加载数据
onMounted(() => {
  try {
    const saved = localStorage.getItem(PANEL_LAYOUT_STORAGE_KEY)
    if (saved) {
      const parsed = JSON.parse(saved) as { left?: number; right?: number }
      const left = clampRatio(Number(parsed.left || 0.15), 0.1, 0.45)
      const right = clampRatio(Number(parsed.right || 0.25), 0.16, 0.45)
      if (left + right < 0.85) {
        panelRatios.value = { left, right }
      }
    }
  } catch {
    panelRatios.value = { left: 0.15, right: 0.25 }
  }
  loadNodes()
})

watch(() => selectedNode.value?.key, () => {
  if (!selectedNode.value || selectedNode.value.isFolder) {
    stopParsePolling()
    return
  }
  if (selectedNode.value.status === 'processing' && selectedNode.value.parseTaskId) {
    startParsePolling(selectedNode.value.parseTaskId, selectedNode.value.key)
  }
})

onBeforeUnmount(() => {
  stopParsePolling()
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
  padding: 5px;
  width: 100%;
  min-width: 0;
  background: transparent;

  :deep(.smart-tree) {
    background: transparent;
  }
}

.tree-panel-content {
  background: transparent;
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

.header-action-btn {
  height: 28px;
  border-radius: 6px;
  font-size: 12px;
  padding-inline: 10px;
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
