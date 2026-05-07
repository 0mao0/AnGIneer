<template>
  <div ref="workspaceRef" class="knowledge-workspace" :class="appClass">
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
              <a-tooltip title="解析设置">
                <a-button
                  size="small"
                  class="header-action-btn header-icon-btn"
                  @click="showParseSettingsModal"
                >
                  <template #icon>
                    <SettingOutlined />
                  </template>
                </a-button>
              </a-tooltip>
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
              :graph-data="graphData"
              :graph-data-full-loaded="graphDataFullLoaded"
              :on-update-structured-node="_updateStructuredNodeWrapper"
              :on-batch-structured-operation="_batchOperateStructuredNodesWrapper"
              :on-undo-last-operation="_undoLastStructuredOperationWrapper"
              :on-load-full-graph-data="loadFullGraphData"
              @parse="parseDocument"
              @toggle-visible="toggleVisible"
              @query-structured="_loadStructuredIndexWrapper"
            />
          </template>
        </Panel>
      </template>

      <!-- 右侧：AI 对话 -->
      <template #right>
        <Panel title="AI 对话" :icon="MessageOutlined">
          <template #extra>
            <a-space size="small">
              <a-button
                size="small"
                class="header-action-btn"
                :loading="knowledgeEvalDrawerRef?.running || false"
                @click="openKnowledgeEvalDrawer"
              >
                评测
              </a-button>
            </a-space>
          </template>
          <AIChat
            ref="knowledgeChatRef"
            title=""
            placeholder="输入消息，Ctrl+Enter 发送..."
            :show-context-info="true"
            scene="knowledge"
            :session-id="selectedNode && !selectedNode.isFolder ? selectedNode.key : 'default'"
            @answer-complete="_handleKnowledgeAnswerCompleteWrapper"
            @select-citation="_handleKnowledgeCitationSelectWrapper"
          />
          <KnowledgeEvalDrawer
            ref="knowledgeEvalDrawerRef"
            :run-question="runKnowledgeEvalQuestion"
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

    <a-modal
      :open="parseSettingsVisible"
      title="解析设置"
      ok-text="保存"
      cancel-text="取消"
      @ok="handleParseSettingsConfirm"
      @update:open="parseSettingsVisible = $event"
    >
      <a-form layout="vertical">
        <a-form-item label="启用 LLM">
          <a-switch
            :checked="parseSettings.use_llm"
            checked-children="开启"
            un-checked-children="关闭"
            @update:checked="handleParseUseLlmChange"
          />
        </a-form-item>
        <a-form-item label="LLM 模型">
          <a-select
            :value="parseSettings.llm_model || undefined"
            :options="llmModelOptions"
            :loading="llmConfigsLoading"
            :disabled="!parseSettings.use_llm"
            placeholder="默认使用 Qwen3.6"
            allow-clear
            show-search
            option-filter-prop="label"
            @update:value="handleParseModelChange"
          />
        </a-form-item>
        <a-typography-text type="secondary">
          当前默认模型优先级为 Qwen3.6；若未显式选择，则按后端默认模型执行。
        </a-typography-text>
      </a-form>
    </a-modal>

  </div>
</template>

<script setup lang="ts">
/**
 * 知识库管理页面 - 使用 KnowledgeChatPanel 组件进行 AI 对话
 */
import { ref, computed, onMounted, onBeforeUnmount, watch, h } from 'vue'
import { message, Modal } from 'ant-design-vue'
import {
  FolderOutlined,
  FolderAddOutlined,
  FileSearchOutlined,
  MessageOutlined,
  SettingOutlined
} from '@ant-design/icons-vue'

// 导入 packages 中的组件和 composables
import { SplitPanes, Panel, AIChat, useTheme } from '@angineer/ui-kit'
import {
  KnowledgeTree,
  PDFParsedWorkspace,
  type SmartTreeNode,
  type KnowledgeTreeNode,
  type StructuredBatchOperationPayload,
  type StructuredNodeUpdatePayload,
  createResourceNodeFromKnowledge,
  createOpenResourcePayload
} from '@angineer/docs-ui'
import { useKnowledgeTree, useKnowledgeParse, useKnowledgeStructuredIndex, useKnowledgeCitation, type KnowledgeChatCitation, type KnowledgeAnswerMessage } from '@angineer/docs-ui'
import { getStatusColor, getStatusText } from '@angineer/ui-kit/utils/tree'
import { knowledgeApi } from '@/api/knowledge'
import { getWebDocumentUrl } from '../../../shared/ports'

const { appClass } = useTheme()

import FolderPreview from './components/FolderPreview.vue'
import FolderModal from './components/FolderModal.vue'
import DocDetailModal from './components/DocDetailModal.vue'
import KnowledgeEvalDrawer from './components/KnowledgeEvalDrawer.vue'

const smartTreeRef = ref<InstanceType<typeof KnowledgeTree> | null>(null)
const docParsedWorkspaceRef = ref<InstanceType<typeof PDFParsedWorkspace> | null>(null)
const knowledgeChatRef = ref<InstanceType<typeof AIChat> | null>(null)
const knowledgeEvalDrawerRef = ref<InstanceType<typeof KnowledgeEvalDrawer> | null>(null)

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

const {
  parseSettingsVisible,
  llmConfigsLoading,
  llmConfigOptions,
  parseSettings,
  llmModelOptions,
  loadStoredParseSettings,
  fetchLlmConfigs,
  buildParseOptionsPayload,
  showParseSettingsModal,
  handleParseSettingsConfirm,
  handleParseUseLlmChange,
  handleParseModelChange,
  stopParsePolling,
  startParsePolling
} = useKnowledgeParse(knowledgeApi)

const {
  structuredStats,
  structuredItems,
  buildMiddleFallbackItems,
  loadStructuredStats,
  loadStructuredIndex,
  updateStructuredNode,
  batchOperateStructuredNodes,
  undoLastStructuredOperation
} = useKnowledgeStructuredIndex(knowledgeApi)

const {
  handleKnowledgeAnswerComplete,
  handleKnowledgeCitationSelect
} = useKnowledgeCitation()

const allowedFileTypes = ['.pdf', '.doc', '.docx', '.md']
const PANEL_LAYOUT_STORAGE_KEY = 'angineer-admin-knowledge-layout-v1'
const workspaceRef = ref<HTMLElement | null>(null)

const clampRatio = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value))

const panelRatios = ref({
  left: 0.15,
  right: 0.25
})

const graphData = ref<{ nodes: any[]; edges: any[] } | null>(null)
const graphDataLoading = ref(false)
const graphDataFullLoaded = ref(false)

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
  showAddRootFolder: true,
  addRootFolderTitle: '新增一级文件夹',
  showStatus: true,
  draggable: true,
  allowAddFile: true,
  allowedFileTypes: allowedFileTypes,
  emptyText: '暂无文档'
}

/* 读取聊天面板中最新一条助手回答，用于同步评测过程结果。 */
const getLatestKnowledgeAssistantMessage = (): KnowledgeAnswerMessage | null => {
  const messages = Array.isArray(knowledgeChatRef.value?.messages)
    ? knowledgeChatRef.value.messages as KnowledgeAnswerMessage[]
    : []
  const latestMessage = [...messages].reverse().find(item => item.role === 'assistant')
  return latestMessage || null
}

/* 供评测抽屉调用，发送单条测试问题并返回回答、链路和引用。 */
const runKnowledgeEvalQuestion = async (question: string) => {
  knowledgeChatRef.value?.clearComposer?.()
  await knowledgeChatRef.value?.sendMessage(question, '', undefined, { includeDebug: true, includeRetrieved: true })
  knowledgeChatRef.value?.clearComposer?.()
  const latestAnswer = getLatestKnowledgeAssistantMessage()
  return {
    answer: latestAnswer?.content || '',
    queryChain: latestAnswer?.queryChain || '',
    citations: latestAnswer?.citations || [],
    strategy: latestAnswer?.strategy || '',
    task_type: latestAnswer?.task_type || '',
    confidence: latestAnswer?.confidence,
    retrieved_items: latestAnswer?.retrieved_items || [],
    debug: latestAnswer?.debug || {}
  }
}

/* 打开评测抽屉。 */
const openKnowledgeEvalDrawer = async () => {
  knowledgeEvalDrawerRef.value?.open?.()
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

const keepCurrentPreview = (docId: string) => docContentDocId.value === docId && Boolean(docContent.value)

const _loadStructuredIndexWrapper = () => loadStructuredIndex(selectedNode.value, docContent.value)

const _startParsePollingWrapper = (taskId: string, docId: string) => startParsePolling(
  taskId, docId, selectedNode.value, loadNodes, loadDocContent, loadStructuredStats
)

const _handleKnowledgeAnswerCompleteWrapper = (msg: KnowledgeAnswerMessage) => handleKnowledgeAnswerComplete(
  msg, selectedNode, graphData, loadNodes, loadDocContent, loadStructuredStats, _loadStructuredIndexWrapper, docParsedWorkspaceRef.value, keepCurrentPreview
)

const _handleKnowledgeCitationSelectWrapper = (citation: KnowledgeChatCitation) => handleKnowledgeCitationSelect(
  citation, selectedNode, graphData, loadNodes, loadDocContent, loadStructuredStats, _loadStructuredIndexWrapper, docParsedWorkspaceRef.value, keepCurrentPreview
)

const _updateStructuredNodeWrapper = (payload: StructuredNodeUpdatePayload) => updateStructuredNode(
  payload, selectedNode.value, loadDocContent, loadStructuredStats, _loadStructuredIndexWrapper
)

const _batchOperateStructuredNodesWrapper = (payload: StructuredBatchOperationPayload) => batchOperateStructuredNodes(
  payload, selectedNode.value, docParsedWorkspaceRef.value, loadDocContent, loadStructuredStats, _loadStructuredIndexWrapper
)

const _undoLastStructuredOperationWrapper = () => undoLastStructuredOperation(
  selectedNode.value, docParsedWorkspaceRef.value, loadDocContent, loadStructuredStats, _loadStructuredIndexWrapper
)

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
            _startParsePollingWrapper((node as any).parseTaskId, node.key)
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
          await _loadStructuredIndexWrapper()
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
        _startParsePollingWrapper(node.parseTaskId, node.key)
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
    graphDataFullLoaded.value = false
    if (selectedNode.value && selectedNode.value.key === docId && result?.storage?.source_file) {
      selectedNode.value.filePath = result.storage.source_file
    }
    loadGraphSummary(docId)
  } catch (error) {
    docContent.value = ''
    docContentDocId.value = ''
    graphData.value = null
    structuredStats.value = {}
  }
}

const loadGraphSummary = async (docId: string) => {
  try {
    graphDataLoading.value = true
    const result = await knowledgeApi.getDocBlocksGraphSummary('default', docId) as any
    graphData.value = result?.data || null
  } catch {
    graphData.value = null
  } finally {
    graphDataLoading.value = false
  }
}

const loadFullGraphData = async () => {
  if (!selectedNode.value || graphDataFullLoaded.value || graphDataLoading.value) return
  try {
    graphDataLoading.value = true
    const result = await knowledgeApi.getDocBlocksGraph('default', selectedNode.value.key) as any
    graphData.value = result?.data || null
    graphDataFullLoaded.value = true
  } catch {
  } finally {
    graphDataLoading.value = false
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
      ? [h('div', { style: 'margin-top: 8px; color: var(--text-secondary);' }, preview.sample_doc_titles.slice(0, 3).join('、'))]
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
    if (parseSettings.value.use_llm && !llmConfigOptions.value.length) {
      await fetchLlmConfigs()
    }
    const parseOptions = buildParseOptionsPayload()
    if (selectedNode.value && selectedNode.value.key === node.key) {
      selectedNode.value.status = 'processing'
      selectedNode.value.parseError = ''
      selectedNode.value.parseProgress = 0
      selectedNode.value.parseStage = 'queued'
    }
    const result = await knowledgeApi.parseDocumentAsync('default', node.key, node.filePath, parseOptions) as any
    const taskId = result?.task_id
    message.success('开始解析文档')
    await loadNodes(node.key)
    if (taskId) {
      _startParsePollingWrapper(taskId, node.key)
    }
  } catch (error) {
    const detail = (error as any)?.response?.data?.detail || (error as any)?.message
    message.error(detail ? `解析失败: ${detail}` : '解析失败')
  }
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
  loadStoredParseSettings()
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
  void fetchLlmConfigs()
  loadNodes()
})

watch(() => selectedNode.value?.key, () => {
  if (!selectedNode.value || selectedNode.value.isFolder) {
    stopParsePolling()
    return
  }
  if (selectedNode.value.status === 'processing' && selectedNode.value.parseTaskId) {
    _startParsePollingWrapper(selectedNode.value.parseTaskId, selectedNode.value.key)
  }
})

onBeforeUnmount(() => {
  stopParsePolling()
})
</script>

<style lang="less" scoped>
.knowledge-workspace {
  height: 100%;
  background: var(--bg-primary);
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
  border: 2px dashed var(--border-color);
  border-radius: 8px;
  margin: 16px;

  &:hover {
    border-color: var(--primary-color);
    background: var(--bg-tertiary);
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

.header-icon-btn {
  padding-inline: 8px;
}

.drop-hint {
  position: absolute;
  bottom: 16px;
  left: 50%;
  transform: translateX(-50%);
  background: var(--primary-color);
  color: var(--bg-secondary);
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
