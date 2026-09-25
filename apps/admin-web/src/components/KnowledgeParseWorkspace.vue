<template>
    <div ref="workspaceRef" class="knowledge-parse-view">
      <!-- 使用 SplitPanes 三栏布局组件 - 比例 1.5:6:2.5 -->
    <SplitPanes
      ref="splitPanesRef"
      class="workspace-container"
      :initial-left-ratio="panelRatios.left"
      :initial-right-ratio="panelRatios.right"
      :left-collapsible="true"
      :left-collapsed="leftPanelCollapsed"
      @update:left-collapsed="onLeftCollapsedChange"
      :right-collapsible="true"
      :right-collapsed="rightPanelCollapsed"
      @update:right-collapsed="onRightCollapsedChange"
      @resize="onPanelResize"
    >
      <!-- 左侧：知识树 -->
      <template #left>
        <Panel
          title="知识树"
          :icon="FolderOutlined"
          contentClass="tree-panel-content"
        >
          <template #extra>
            <a-tooltip title="收起侧边栏">
              <a-button size="small" class="header-icon-btn" @click="splitPanesRef?.toggleLeft()">
                <template #icon><MenuFoldOutlined /></template>
              </a-button>
            </a-tooltip>
          </template>
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
              :default-expanded-keys="defaultExpandedKeys"
              :default-selected-keys="defaultSelectedKeys"
              :dark="isDark"
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
              <!-- 自定义操作按钮：根据节点状态显示不同按钮 -->
              <template #actions="{ node }">
                <template v-if="node.isFolder">
                  <template v-if="isLibRootNode(node)">
                    <button
                      type="button"
                      class="action-btn"
                      aria-label="添加子文件夹"
                      title="添加子文件夹"
                      @click.stop="showCreateSubFolderModal(node)"
                    >
                      <FolderAddOutlined />
                    </button>
                    <button
                      type="button"
                      class="action-btn"
                      aria-label="添加文件"
                      title="添加文件"
                      @click.stop="showCreateFileModal(node)"
                    >
                      <FileAddOutlined />
                    </button>
                    <button
                      type="button"
                      class="action-btn delete"
                      aria-label="批量删除文件"
                      title="批量删除文件"
                      @click.stop="showBatchDeleteModal(node)"
                    >
                      <CheckSquareOutlined />
                    </button>
                  </template>
                  <template v-else>
                    <button
                      type="button"
                      class="action-btn"
                      aria-label="重命名"
                      title="重命名"
                      @click.stop="showRenameModal(node)"
                    >
                      <EditOutlined />
                    </button>
                    <button
                      type="button"
                      class="action-btn"
                      aria-label="添加子文件夹"
                      title="添加子文件夹"
                      @click.stop="showCreateSubFolderModal(node)"
                    >
                      <FolderAddOutlined />
                    </button>
                    <button
                      type="button"
                      class="action-btn"
                      aria-label="添加文件"
                      title="添加文件"
                      @click.stop="showCreateFileModal(node)"
                    >
                      <FileAddOutlined />
                    </button>
                    <button
                      type="button"
                      class="action-btn delete"
                      aria-label="批量删除文件"
                      title="批量删除文件"
                      @click.stop="showBatchDeleteModal(node)"
                    >
                      <CheckSquareOutlined />
                    </button>
                    <button
                      type="button"
                      class="action-btn delete"
                      aria-label="删除"
                      title="删除"
                      @click.stop="handleDeleteNode(node)"
                    >
                      <DeleteOutlined />
                    </button>
                  </template>
                </template>
                <template v-else>
                  <button
                    type="button"
                    class="action-btn"
                    aria-label="重命名"
                    title="重命名"
                    @click.stop="showRenameModal(node)"
                  >
                    <EditOutlined />
                  </button>
                  <button
                    type="button"
                    class="action-btn"
                    aria-label="查看"
                    title="查看"
                    @click.stop="showDocDetail(node)"
                  >
                    <EyeOutlined />
                  </button>
                  <!-- processing状态：显示取消按钮 -->
                  <button
                    v-if="node.status === 'processing' && node.parseTaskId"
                    type="button"
                    class="action-btn warning"
                    aria-label="取消解析"
                    title="取消解析"
                    @click.stop="handleCancelParseTask(node)"
                  >
                    <StopOutlined />
                  </button>
                  <!-- 非processing状态：显示重试按钮（支持已完成/失败/取消/待处理状态的文档重新解析） -->
                  <button
                    v-if="node.status !== 'processing' && !node.isFolder"
                    type="button"
                    class="action-btn success"
                    aria-label="重新解析"
                    title="重新解析"
                    @click.stop="handleRetryParseTask(node)"
                  >
                    <ReloadOutlined />
                  </button>
                  <button
                    type="button"
                    class="action-btn delete"
                    aria-label="删除"
                    title="删除"
                    @click.stop="handleDeleteNode(node)"
                  >
                    <DeleteOutlined />
                  </button>
                </template>
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
                v-if="selectedNode.status === 'processing'"
                danger
                size="small"
                class="header-action-btn"
                @click="handleCancelParseTask(selectedNode)"
              >
                <template #icon>
                  <StopOutlined />
                </template>
                停止解析
              </a-button>
              <a-button
                v-else
                type="primary"
                size="small"
                class="header-action-btn"
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

          <template v-else>
            <template v-if="selectedNode.isFolder">
            <FolderPreview
              :node="selectedNode"
              :child-count="getChildCount(selectedNode.key, 'document')"
              :allowed-file-types="allowedFileTypes"
              @upload="handleFolderUpload"
            />
            </template>

            <template v-else>
              <div v-if="buildIdMismatch" class="build-id-mismatch-banner">
                <a-alert
                  type="warning"
                  show-icon
                  :closable="false"
                  message="内容与图谱版本不一致（build_id 不匹配），已禁用高亮联动。请重建文档解析（popo/structure 阶段）后再试。"
                />
              </div>
              <PDFParsedWorkspace
                ref="docParsedWorkspaceRef"
                :node="selectedNode"
                :library-id="selectedNode?.libraryId || 'default'"
                :content="docContent"
                :structured-stats="structuredStats"
                :structured-items="structuredItems"
                :graph-data="graphData"
                :graph-data-full-loaded="graphDataFullLoaded"
                :render-pdf-path="docRenderPdfPath"
                :on-update-structured-node="_updateStructuredNodeWrapper"
                :on-batch-structured-operation="_batchOperateStructuredNodesWrapper"
                :on-undo-last-operation="_undoLastStructuredOperationWrapper"
                :on-load-full-graph-data="loadFullGraphData"
                :on-load-graph-snapshot="loadGraphSnapshot"
                :on-build-graph="buildGraphFromDoc"
                :dark="isDark"
                @parse="parseDocument"
                @toggle-visible="toggleVisible"
                @query-structured="_loadStructuredIndexWrapper"
              />
            </template>
          </template>
        </Panel>
      </template>

      <!-- 右侧：AI 对话 -->
      <template #right>
        <Panel title="AI 对话" :icon="MessageOutlined">
          <template #extra>
            <a-select
              v-if="libraryStore.libraries.length > 1"
              :value="libraryStore.libraryId"
              :options="chatLibraryOptions"
              size="small"
              class="chat-library-switcher"
              style="min-width: 140px"
              @change="onChatLibraryChange"
            />
            <a-tooltip title="新建对话">
              <a-button size="small" class="header-icon-btn" @click="onNewChat">
                <template #icon><PlusOutlined /></template>
              </a-button>
            </a-tooltip>
            <a-tooltip title="收起侧边栏">
              <a-button size="small" class="header-icon-btn" @click="splitPanesRef?.toggleRight()">
                <template #icon><MenuUnfoldOutlined /></template>
              </a-button>
            </a-tooltip>
          </template>
          <AIChat
            ref="knowledgeChatRef"
            title=""
            placeholder="输入消息，Ctrl+Enter 发送..."
            :show-context-info="true"
            scene="knowledge"
            :session-id="chatSessionId"
            :library-id="libraryStore.libraryId"
            :transport="defaultAIChatTransport"
            @answer-complete="_handleKnowledgeAnswerCompleteWrapper"
            @select-citation="_handleKnowledgeCitationSelectWrapper"
          />
        </Panel>
      </template>
    </SplitPanes>

    </div><!-- /.knowledge-parse-view -->
    <FolderModal

      v-model:visible="folderModalVisible"

      :title="folderModalTitle"

      :loading="modalLoading"

      :folder-tree-data="folderSelectTreeData"

      v-model:name="folderForm.name"

      v-model:parent-id="folderForm.parentId"

      :is-new="folderForm.isNew"

      :library-name="folderModalLibraryName"

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



    <!-- 文件夹批量删除弹窗 -->

    <BatchDeleteModal
      v-model:visible="batchDeleteVisible"
      :folder-node="batchDeleteFolder"
      :api="api"
      @deleted="loadNodes()"
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

        <a-form-item label="启用 LLM" style="margin-bottom: 12px;">

          <a-switch

            :checked="parseSettings.use_llm"

            checked-children="开启"

            un-checked-children="关闭"

            @update:checked="handleParseUseLlmChange"

          />

        </a-form-item>

        <a-form-item label="LLM 模型" style="margin-bottom: 12px;">

          <a-select

            :value="parseSettings.llm_model || undefined"

            :loading="llmConfigsLoading"

            :disabled="!parseSettings.use_llm"

            placeholder="默认使用 Qwen3.6"

            allow-clear

            show-search

            option-filter-prop="label"

            style="width: 100%;"

            dropdown-class-name="llm-select-dropdown"

            @update:value="handleParseModelChange"

          >

            <a-select-option v-for="opt in llmModelOptions" :key="opt.value" :value="opt.value" :disabled="opt.disabled">

              <span style="font-size: 14px;">{{ opt.label }}</span>

              <a-tag v-if="opt.value.includes('付费')" color="orange" style="margin-left: 6px; font-size: 12px;">付费</a-tag>

              <a-tag v-else color="green" style="margin-left: 6px; font-size: 12px;">免费</a-tag>

            </a-select-option>

          </a-select>

        </a-form-item>

        <a-typography-text type="secondary">

          当前默认模型优先级为 Qwen3.6；若未显式选择，则按后端默认模型执行。

        </a-typography-text>

      </a-form>

    </a-modal>


</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import { message, Modal } from 'ant-design-vue'
import { useRoute } from 'vue-router'
import {
  FolderOutlined,
  FolderAddOutlined,
  FileSearchOutlined,
  MessageOutlined,
  SettingOutlined,
  StopOutlined,
  ReloadOutlined,
  EditOutlined,
  FileAddOutlined,
  DeleteOutlined,
  EyeOutlined,
  PlusOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  CheckSquareOutlined
} from '@ant-design/icons-vue'

// 导入 packages 中的组件和 composables
import { SplitPanes, Panel, useSplitPanesLayout, type DropEvent } from '@angineer/ui-kit'
import { AIChat } from '@angineer/aichat-ui'
import {
  KnowledgeTree,
  PDFParsedWorkspace,
  type SmartTreeNode,
  type KnowledgeTreeNode,
  type StructuredBatchOperationPayload,
  type StructuredNodeUpdatePayload,
  type KnowledgeApiPort,
  createResourceNodeFromKnowledge,
  createOpenResourcePayload
} from '@angineer/docs-ui'
import { useKnowledgeTree, useKnowledgeParse, useKnowledgeStructuredIndex, useKnowledgeCitation, type KnowledgeChatCitation, type KnowledgeAnswerMessage } from '@angineer/docs-ui'
import { getStatusColor, getStatusText } from '@angineer/ui-kit/utils/tree'
import { useLibraryStore } from '@/stores/library'
import { getWebDocumentUrl } from '../../../shared/ports'
import { defaultAIChatTransport } from '../../../shared/chatTransport'
import FolderPreview from '../views/components/FolderPreview.vue'
import FolderModal from '../views/components/FolderModal.vue'
import DocDetailModal from '../views/components/DocDetailModal.vue'
import BatchDeleteModal from '../views/components/BatchDeleteModal.vue'

interface Props {
  api: KnowledgeApiPort
  dark?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  dark: false
})

const isDark = computed(() => props.dark)
const route = useRoute()


const smartTreeRef = ref<InstanceType<typeof KnowledgeTree> | null>(null)
const docParsedWorkspaceRef = ref<InstanceType<typeof PDFParsedWorkspace> | null>(null)
const knowledgeChatRef = ref<InstanceType<typeof AIChat> | null>(null)

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

// 当前知识库（供上传默认归属）
const libraryStore = useLibraryStore()

/** 全局会话：不随文档变化，只有刷新或新建对话才换 key */
const chatNonce = ref(Date.now() + Math.floor(Math.random() * 1_000_000))
const chatSessionId = computed(() => `global::${chatNonce.value}`)
const onNewChat = () => {
  chatNonce.value += 1
  knowledgeChatRef.value?.startNewChat?.()
}

const chatLibraryOptions = computed(() =>
  libraryStore.libraries.map((lib) => ({ value: lib.id, label: lib.name || lib.id }))
)

const onChatLibraryChange = (value: string) => {
  libraryStore.setLibrary(value)
  // 切换知识库后重置会话，避免上一库上下文串场
  onNewChat()
}

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
} = useKnowledgeParse(props.api)

const {
  structuredStats,
  structuredItems,
  buildMiddleFallbackItems,
  loadStructuredStats,
  loadStructuredIndex,
  updateStructuredNode,
  batchOperateStructuredNodes,
  undoLastStructuredOperation
} = useKnowledgeStructuredIndex(props.api)

const {
  handleKnowledgeAnswerComplete,
  handleKnowledgeCitationSelect
} = useKnowledgeCitation()

const allowedFileTypes = ['.pdf', '.doc', '.docx', '.md']
const PANEL_LAYOUT_STORAGE_KEY = 'angineer-admin-knowledge-layout-v1'
const workspaceRef = ref<HTMLElement | null>(null)
const splitPanesRef = ref<InstanceType<typeof SplitPanes> | null>(null)

// 三栏比例 / 收起状态持久化：与评测集等三栏视图共用 ui-kit 的 useSplitPanesLayout（storageKey 不变，历史布局无损）
const {
  panelRatios,
  leftCollapsed: leftPanelCollapsed,
  rightCollapsed: rightPanelCollapsed,
  setLeftCollapsed: onLeftCollapsedChange,
  setRightCollapsed: onRightCollapsedChange,
  onPanelResize,
} = useSplitPanesLayout({
  storageKey: PANEL_LAYOUT_STORAGE_KEY,
  collapsedStorageKeys: {
    left: 'angineer-knowledge-left-collapsed',
    right: 'angineer-knowledge-right-collapsed',
  },
  getContainerWidth: () => workspaceRef.value?.clientWidth || window.innerWidth,
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
  nodeId: '',
  libraryId: '' as string
})

const docDetailVisible = ref(false)
const detailDoc = ref<KnowledgeTreeNode | null>(null)

// 文件夹批量删除
const batchDeleteVisible = ref(false)
const batchDeleteFolder = ref<KnowledgeTreeNode | null>(null)
const showBatchDeleteModal = (node: SmartTreeNode) => {
  batchDeleteFolder.value = node as KnowledgeTreeNode
  batchDeleteVisible.value = true
}

// 文档内容
const docContent = ref('')
const docContentDocId = ref('')
const docContentBuildId = ref<string | null>(null)
const graphBuildId = ref<string | null>(null)
const buildIdMismatch = ref(false)

// 计算属性
const folderModalTitle = computed(() => folderForm.value.isNew ? '新建文件夹' : '重命名')
// 弹窗展示的所属知识库名（只读）
const folderModalLibraryName = computed(() => {
  if (!folderForm.value.libraryId) return ''
  return libraryStore.libraries.find(l => l.id === folderForm.value.libraryId)?.name
    || libraryStore.libraries.find(l => l.id === folderForm.value.libraryId)?.id
    || folderForm.value.libraryId
})
const folderSelectTreeData = computed(() => [
  { value: '__root__', title: '根目录' },
  ...folderTreeData.value
])
const smartTreeProps = {
  showSearch: true,
  searchPlaceholder: '搜索文档...',
  showAddRootFolder: true,
  addRootFolderTitle: '新增一级文件夹',
  showIcon: true,
  showStatus: true,
  draggable: true,
  allowAddFile: true,
  allowedFileTypes: allowedFileTypes,
  emptyText: '暂无文档'
}

// 默认展开/选中（SmartTree 监听 prop 变化并应用）
const defaultExpandedKeys = ref<string[]>([])
const defaultSelectedKeys = ref<string[]>([])

const keepCurrentPreview = (docId: string) => docContentDocId.value === docId && Boolean(docContent.value)

/** 图谱快照加载（注入给 Preview_KnowledgeGraph，替代组件内硬编码 fetch） */
const nodeLibrary = (node?: SmartTreeNode | null): string =>
  String((node as any)?.libraryId || useLibraryStore().libraryId || 'default')

const loadGraphSnapshot = (params: { libraryId?: string; docId?: string; viewMode?: 'doc' | 'global' }) =>
  props.api.getGraphSnapshot({ ...params, libraryId: params.libraryId || nodeLibrary(selectedNode.value) })

/** 图谱构建（快速提取 / AI 深度提取，enableLlm 区分） */
const buildGraphFromDoc = (params: { libraryId?: string; docId?: string }, enableLlm: boolean) =>
  props.api.buildGraphFromDoc(params.libraryId || nodeLibrary(selectedNode.value), params.docId || '', enableLlm)

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

/**
 * 根据路由 query 自动聚焦文档并定位到结构化块（用于 SOP/AI 引用跳转）。
 */
const focusFromRouteQuery = async () => {
  const docId = String(route.query.doc_id || '').trim()
  if (!docId) {
    return
  }

  const targetId = String(route.query.target_id || '').trim()
  const preferredPageRaw = route.query.page_idx
  const preferredPageNumber = Number(preferredPageRaw)
  const preferredPage = Number.isFinite(preferredPageNumber) && preferredPageNumber > 0
    ? preferredPageNumber
    : null

  await loadNodes(docId)

  if (selectedNode.value?.key === docId && !selectedNode.value.isFolder
    && (selectedNode.value.status === 'completed' || selectedNode.value.status === 'partial')) {
    await loadGraphSummary(docId)
    if (selectedNode.value.strategy) {
      await _loadStructuredIndexWrapper()
    }
  }

  if (!targetId) {
    return
  }

  await nextTick()
  await nextTick()
  docParsedWorkspaceRef.value?.setActiveLinkedItem(targetId, {
    preferredPage,
    preferLastHighlight: true,
    groupHighlight: false
  })
}

// 查找节点
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

// 查找父节点链
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

// 查找第一个文件节点（深度优先）
const findFirstFileNode = (nodes: SmartTreeNode[]): SmartTreeNode | null => {
  for (const node of nodes) {
    if (!node.isFolder) return node
    if (node.children?.length) {
      const found = findFirstFileNode(node.children)
      if (found) return found
    }
  }
  return null
}

// 加载节点：所有知识库可视（库根虚拟节点），各库内容挂在库下
const loadNodes = async (focusNodeKey?: string) => {
  try {
    const [response, libraries] = await Promise.all([
      props.api.getNodes(undefined, false) as unknown as any[],
      libraryStore.loadLibraries(),
    ])
    treeData.value = buildTree(response, libraries)
    // 默认展开所有库根虚拟节点，保证库内容可见
    const libRootKeys = (treeData.value as unknown as SmartTreeNode[])
      .filter(n => String(n.key).startsWith('lib:'))
      .map(n => n.key)
    if (libRootKeys.length) {
      defaultExpandedKeys.value = Array.from(new Set([...defaultExpandedKeys.value, ...libRootKeys]))
      if (smartTreeRef.value) {
        smartTreeRef.value.expandedKeys = Array.from(new Set([
          ...(smartTreeRef.value.expandedKeys || []),
          ...libRootKeys
        ]))
      }
    }
    // 校验当前选中节点是否仍存在（列表页可能已删除该文档），不存在则清空选中态与视图缓存
    const currentSelectedKey = selectedKeys.value[0]
    if (currentSelectedKey && !findNode(treeData.value as unknown as SmartTreeNode[], currentSelectedKey)) {
      selectedKeys.value = []
      defaultSelectedKeys.value = []
      selectedNode.value = null
      docContent.value = ''
      docContentDocId.value = ''
      graphData.value = null
      structuredStats.value = {}
      structuredItems.value = []
      docRenderPdfPath.value = ''
      stopParsePolling()
    }
    if (!focusNodeKey && !selectedKeys.value.length) {
      const firstFile = findFirstFileNode(treeData.value as unknown as SmartTreeNode[])
      if (firstFile) {
        focusNodeKey = firstFile.key
      }
    }
    if (focusNodeKey) {
      // 模拟用户点击：展开目标文件祖先链 + 高亮选中目标文件
      const parents = findParentChain(treeData.value as unknown as SmartTreeNode[], focusNodeKey) || []
      defaultExpandedKeys.value = Array.from(new Set([
        ...defaultExpandedKeys.value,
        ...parents
      ]))
      defaultSelectedKeys.value = [focusNodeKey]
      if (smartTreeRef.value) {
        smartTreeRef.value.selectedKeys = [focusNodeKey]
      }
      selectedKeys.value = [focusNodeKey]
      const node = findNode(treeData.value as unknown as SmartTreeNode[], focusNodeKey)
      if (node) {
        selectedNode.value = node as unknown as KnowledgeTreeNode
        if (!node.isFolder) {
          // completed/partial/failed 均尝试加载：failed 可能有部分产物（如结构完成但 fts 失败），可预览与高亮
          if (['completed', 'partial', 'failed'].includes(String(node.status))) {
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
      // completed/partial/failed 均尝试加载：failed 可能有部分产物（如结构完成但 fts 失败），可预览与高亮
      if (['completed', 'partial', 'failed'].includes(node.status)) {
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
const docRenderPdfPath = ref<string>('')
const loadDocContent = async (docId: string) => {
  try {
    const result = await props.api.getDocument(nodeLibrary(selectedNode.value), docId) as unknown as {
      content: string
      storage?: { source_file?: string | null; render_pdf?: string | null }
      graph_data?: { nodes: any[]; edges: any[] } | null
      build_id?: string | null
    }
    // 解析中 content 可能尚未生成，不覆盖已有内容，只更新 render_pdf
    if (result.content) {
      docContent.value = result.content
    }
    docContentDocId.value = docId
    docContentBuildId.value = result.build_id || null
    graphData.value = null
    graphDataFullLoaded.value = false
    buildIdMismatch.value = false
    docRenderPdfPath.value = result?.storage?.render_pdf || ''
    if (selectedNode.value && selectedNode.value.key === docId && result?.storage?.source_file) {
      selectedNode.value.filePath = result.storage.source_file
    }
    await loadGraphSummary(docId)
  } catch (error) {
    docContent.value = ''
    docContentDocId.value = ''
    graphData.value = null
    buildIdMismatch.value = false
    structuredStats.value = {}
  }
}

const loadGraphSummary = async (docId: string) => {
  // 解析进行中，structure 阶段存在“先写 meta、后盖章 md”的短暂窗口，
  // 期间 md 与 meta 的 build_id 会瞬时不一致。先短重试再判定，避免误禁高亮联动。
  const MISMATCH_MAX_RETRIES = 3
  const MISMATCH_RETRY_DELAY_MS = 800
  try {
    graphDataLoading.value = true
    for (let attempt = 0; attempt < MISMATCH_MAX_RETRIES; attempt++) {
      // 高亮依赖节点 bbox，必须加载完整图（summary 会剥离 bbox）
      const result = await props.api.getDocBlocksGraph(nodeLibrary(selectedNode.value), docId) as any
      if (selectedNode.value?.key !== docId) {
        // 重试间隙用户已切换文档，丢弃本次结果
        return
      }
      graphBuildId.value = result?.build_id || null
      // 孪生产物一致性校验：md 与 graph 的 build_id 都存在且不一致时禁用高亮
      if (
        docContentBuildId.value &&
        graphBuildId.value &&
        docContentBuildId.value !== graphBuildId.value
      ) {
        if (attempt < MISMATCH_MAX_RETRIES - 1) {
          await new Promise((resolve) => setTimeout(resolve, MISMATCH_RETRY_DELAY_MS))
          continue
        }
        buildIdMismatch.value = true
        graphData.value = null
        return
      }
      graphData.value = result?.data || null
      return
    }
  } catch {
    graphData.value = null
    buildIdMismatch.value = false
  } finally {
    graphDataLoading.value = false
  }
}

const loadFullGraphData = async () => {
  if (!selectedNode.value || graphDataFullLoaded.value || graphDataLoading.value) return
  try {
    graphDataLoading.value = true
    const result = await props.api.getDocBlocksGraph(nodeLibrary(selectedNode.value), selectedNode.value.key) as any
    graphData.value = result?.data || null
    graphDataFullLoaded.value = true
  } catch {
  } finally {
    graphDataLoading.value = false
  }
}

// 显示新建文件夹弹窗
const showCreateFolderModal = () => {
  folderForm.value = {
    name: '',
    parentId: undefined,
    isNew: true,
    nodeId: '',
    libraryId: useLibraryStore().libraryId || 'default'
  }
  folderModalVisible.value = true
}

// 显示重命名弹窗
const showRenameModal = (node: SmartTreeNode) => {
  if (isLibRootNode(node)) {
    message.warning('知识库根目录不可重命名（库名请在列表模式修改）')
    return
  }
  folderForm.value = {
    name: node.title,
    parentId: node.parentId,
    isNew: false,
    nodeId: node.key,
    libraryId: String((node as any).libraryId || useLibraryStore().libraryId || 'default')
  }
  folderModalVisible.value = true
}

// 显示创建子文件夹弹窗
const showCreateSubFolderModal = (parentNode: SmartTreeNode | null) => {
  folderForm.value = {
    name: '',
    parentId: parentNode?.key || undefined,
    isNew: true,
    nodeId: '',
    libraryId: String((parentNode as any)?.libraryId || useLibraryStore().libraryId || 'default')
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
      const parentNode = folderForm.value.parentId
        ? findNode(treeData.value as unknown as SmartTreeNode[], folderForm.value.parentId)
        : null
      // 库根虚拟节点下新建 → 该库根级（parent_id 置空）
      const isLibRootParent = parentNode ? isLibRootNode(parentNode as SmartTreeNode) : false
      const targetLibrary = (parentNode as any)?.libraryId || useLibraryStore().libraryId || 'default'
      await props.api.createNode({
        library_id: targetLibrary,
        title: folderForm.value.name,
        node_type: 'folder',
        parent_id: isLibRootParent ? undefined : folderForm.value.parentId
      })
      message.success('创建成功')
    } else {
      await props.api.updateNode(folderForm.value.nodeId, {
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

// 是否库根虚拟节点（key 约定 lib:{id}）：知识树展示所有库的可视化，库根不可删除
const isLibRootNode = (node: SmartTreeNode): boolean =>
  String(node?.key || '').startsWith('lib:')

// 库根节点禁止删除（删库需走列表模式的二次确认）
const isDefaultRootFolder = (node: SmartTreeNode): boolean => isLibRootNode(node)

// 删除节点
const handleDeleteNode = async (node: SmartTreeNode) => {
  if (isDefaultRootFolder(node)) {
    message.warning('知识库根目录不可删除；如需删除整个知识库，请在「列表」模式下操作（有二次确认）')
    return
  }
  const nodeType = node.isFolder ? '文件夹' : '文件'
  const previewText = node.isFolder
    ? `确定要删除「${node.title}」文件夹吗？其中所有文件将被标记删除并从树中隐藏，数据保留。`
    : `确定要删除「${node.title}」吗？将标记为已删除并从树中隐藏，文件内容保留，可在「列表」模式恢复或永久删除。`
  Modal.confirm({
    title: `确认删除${nodeType}`,
    content: previewText,
    okText: '删除',
    okType: 'danger',
    cancelText: '取消',
    async onOk() {
      try {
        await props.api.softDeleteNode(node.key)
        message.success('已删除（数据保留）')
        await loadNodes()
      } catch (error) {
        const detail = (error as any)?.response?.data?.detail || (error as any)?.message
        message.error(detail ? `删除失败: ${detail}` : '删除失败')
      }
    }
  })
}


/** 取消正在运行的解析任务 */
const handleCancelParseTask = async (node: SmartTreeNode) => {
  if (!node.parseTaskId) {
    message.warning('该节点没有正在运行的任务')
    return
  }
  Modal.confirm({
    title: '确认取消解析',
    content: `确定要取消「${node.title}」的解析任务吗？取消后可以重新解析或删除该文件。`,
    okText: '取消任务',
    okType: 'danger',
    cancelText: '保留任务',
    async onOk() {
      try {
        stopParsePolling()
        await props.api.cancelParseTask(node.parseTaskId!)
        // 立即更新选中节点状态，无需等待树刷新
        if (selectedNode.value && selectedNode.value.key === node.key) {
          selectedNode.value.status = 'failed'
          selectedNode.value.parseStage = 'cancelled'
          selectedNode.value.parseError = '用户手动取消任务'
          selectedNode.value.parseProgress = 100
        }
        message.success('任务已取消')
        await loadNodes(node.key)
      } catch (error) {
        const detail = (error as any)?.response?.data?.detail || (error as any)?.message
        message.error(detail ? `取消失败: ${detail}` : '取消失败')
      }
    }
  })
}

/** 重试失败的解析任务 */
const handleRetryParseTask = async (node: SmartTreeNode) => {
  Modal.confirm({
    title: '重新解析',
    content: `确定要重新解析「${node.title}」吗？将使用之前的设置重新开始解析。`,
    okText: '开始解析',
    cancelText: '取消',
    async onOk() {
      try {
        const result = await props.api.retryParseTask(node.key) as any
        message.success(result?.message || '已重新启动解析')
        await loadNodes(node.key)
        const taskId = result?.task_id
        if (taskId) {
          _startParsePollingWrapper(taskId, node.key)
        }
      } catch (error) {
        const detail = (error as any)?.response?.data?.detail || (error as any)?.message
        message.error(detail ? `重试失败: ${detail}` : '重试失败')
      }
    }
  })
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
    const result = await props.api.parseDocumentAsync(nodeLibrary(node), node.key, node.filePath, parseOptions) as any
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
  const resource = createResourceNodeFromKnowledge(node, (node as any).libraryId || 'default')
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
    await props.api.updateNode(node.key, {
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

// 上传文件：未指定文件夹（含库根虚拟节点）时上传到该库根级
const uploadFile = async (file: File, parentId?: string) => {
  let targetLibrary = ''
  if (parentId && parentId.startsWith('lib:')) {
    targetLibrary = parentId.slice(4)
    parentId = undefined
  } else if (parentId) {
    targetLibrary = String((findNode(treeData.value as unknown as SmartTreeNode[], parentId) as any)?.libraryId || useLibraryStore().libraryId || 'default')
  } else {
    targetLibrary = String(useLibraryStore().libraryId || 'default')
  }
  const tempKey = `__uploading_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
  const tempNode: KnowledgeTreeNode = {
    key: tempKey,
    title: file.name,
    isFolder: false,
    visible: false,
    status: 'uploading',
    parentId,
    libraryId: targetLibrary,
    filePath: file.name
  }

  if (parentId) {
    const parent = findNode(treeData.value as unknown as SmartTreeNode[], parentId)
    if (parent) {
      if (!parent.children) parent.children = []
      parent.children.push(tempNode)
    }
  } else {
    treeData.value.push(tempNode)
  }

  if (smartTreeRef.value) {
    if (parentId) {
      smartTreeRef.value.expandedKeys = Array.from(new Set([
        ...(smartTreeRef.value.expandedKeys || []),
        parentId
      ]))
    }
    smartTreeRef.value.selectedKeys = [tempKey]
  }
  selectedKeys.value = [tempKey]
  selectedNode.value = tempNode

  try {
    const result = await props.api.uploadDocument(targetLibrary, file, parentId) as any
    message.success(`上传成功: ${file.name}`)
    const docId = result?.doc_id || result?.node?.id
    await loadNodes(docId)
    if (docId) {
      const uploadedNode = findNode(treeData.value as unknown as SmartTreeNode[], docId)
      if (uploadedNode) {
        parseDocument(uploadedNode)
      }
    }
  } catch (error) {
    message.error(`上传失败: ${file.name}`)
    if (parentId) {
      const parent = findNode(treeData.value as unknown as SmartTreeNode[], parentId)
      if (parent?.children) {
        parent.children = parent.children.filter(n => n.key !== tempKey)
      }
    } else {
      treeData.value = treeData.value.filter(n => n.key !== tempKey)
    }
    if (selectedKeys.value[0] === tempKey) {
      selectedKeys.value = []
      selectedNode.value = null
    }
  }
}

// 处理文件夹上传
const handleFolderUpload = (file: File, folderId: string) => {
  uploadFile(file, folderId)
}

// 树拖拽
const onTreeDrop = async (event: DropEvent) => {
  const { dragKey, targetParentKey, siblings } = event
  if (dragKey.startsWith('lib:')) {
    message.warning('知识库根目录不可移动')
    await loadNodes()
    return
  }
  // 拖到虚拟库根 → 该库根级
  const realParentKey = targetParentKey?.startsWith('lib:') ? undefined : targetParentKey
  const realSiblings = siblings.filter(s => !s.key.startsWith('lib:'))
  try {
    for (let index = 0; index < realSiblings.length; index++) {
      await props.api.updateNode(realSiblings[index].key, {
        parent_id: realParentKey,
        sort_order: index,
      })
    }
    message.success('移动成功')
    await loadNodes(dragKey)
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

const onTreeDropRoot = async (dragNodeKeys: string[]) => {
  const dragNodeKey = dragNodeKeys[0]
  if (!dragNodeKey) return
  if (dragNodeKey.startsWith('lib:')) {
    message.warning('知识库根目录不可移动')
    await loadNodes()
    return
  }
  try {
    const rootNodes = (treeData.value as unknown as SmartTreeNode[])
      .filter(node => node.key !== dragNodeKey && !node.key.startsWith('lib:'))
    for (let index = 0; index < rootNodes.length; index++) {
      const node = rootNodes[index]
      await props.api.updateNode(node.key, {
        parent_id: null,
        sort_order: index
      })
    }
    await props.api.updateNode(dragNodeKey, {
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
onMounted(async () => {
  loadStoredParseSettings()
  void fetchLlmConfigs()
  const routeDocId = String(route.query.doc_id || '').trim()
  if (routeDocId) {
    await focusFromRouteQuery()
  } else {
    await loadNodes()
  }
})

watch(
  () => [route.query.doc_id, route.query.target_id, route.query.page_idx],
  () => {
    if (!String(route.query.doc_id || '').trim()) {
      return
    }
    void focusFromRouteQuery()
  }
)

watch(() => selectedNode.value?.key, () => {
  if (!selectedNode.value || selectedNode.value.isFolder) {
    stopParsePolling()
    return
  }
  if (selectedNode.value.status === 'processing' && selectedNode.value.parseTaskId) {
    _startParsePollingWrapper(selectedNode.value.parseTaskId, selectedNode.value.key)
  }
})

// 列表页删除/新增节点后，切回解析页时重新拉取左侧树，避免展示已删除的文件

onBeforeUnmount(() => {
  stopParsePolling()
})
</script>

<style lang="less" scoped>
.knowledge-workspace {
  height: 100%;
  background: var(--bg-primary);
  display: flex;
  flex-direction: column;
}

.build-id-mismatch-banner {
  flex: 0 0 auto;
  padding: 8px 16px 0;
}

.knowledge-list-view {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.knowledge-parse-view {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;

  // 三栏 Panel header：背景与内容区统一，下边线用灰色分隔
  :deep(.panel-header) {
    background: var(--panel-bg);
    border-bottom: 1px solid var(--panel-header-divider, var(--border-color));
  }

  // 左侧知识树区域：暗色下用纯黑（SmartTree 本身透明，背景由容器承载）
  :deep(.tree-panel-content) {
    background: var(--tree-bg, var(--panel-bg));
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

  // 删除类按钮（单个删除 / 批量删除）常驻大红色（SmartTree 基础色特异性高，需 !important 覆盖）
  :deep(.action-btn.delete) {
    color: #ff4d4f !important;

    &:hover {
      color: #ff4d4f !important;
      background: rgba(255, 77, 79, 0.15);
    }
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

.chat-library-switcher {
  margin-right: 8px;
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

:deep(.llm-select-dropdown) {
  .ant-select-item-option-content {
    font-size: 14px !important;
  }
}
</style>
