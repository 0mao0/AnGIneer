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
              <a-button type="text" size="small" title="从文档生成" @click="openSopGenerateFromDoc">
                <template #icon><FileTextOutlined /></template>
              </a-button>
              <a-button type="text" size="small" title="新建 SOP" @click="openCreateSopModal()">
                <template #icon><FileAddOutlined /></template>
              </a-button>
              <a-button type="text" size="small" title="导入 MD" @click="openImportModal()">
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
              :multiple="true"
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
                  <UploadOutlined class="action-icon" title="导入 MD" @click.stop="openImportModal(node as SOPTreeNode)" />
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
        <Panel :title="centerPanelTitle" :icon="ApartmentOutlined">
          <template #title>
            <span>{{ centerPanelTitle }}</span>
            <span v-if="metaPanelDirty" class="sop-title-dirty-dot"></span>
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
              :is-dirty="persistDirty"
              :can-undo="sopFlow.undoStack.value.length > 0"
              :can-redo="sopFlow.redoStack.value.length > 0"
              :read-only="currentMode === 'view'"
              :selected-step-id="sopFlow.selectedStepId.value"
              :dirty-step-ids="sopFlow.dirtyStepIds.value"
              :blackboard="sopFlow.blackboard.value"
              @step-select="onStepSelect"
              @step-dblclick="onStepDblClick"
              @select-citation="handleSopCitationSelect"
              @save="onSaveSop"
              @undo="onUndo"
              @redo="onRedo"
              @add-step="onAddStep"
              @auto-layout="onAutoLayout"
              @nodes-change="onNodesChange"
              @edges-change="onEdgesChange"
              @connect="onConnect"
              @edge-update="onEdgeUpdate"
              @edge-dblclick="onEdgeDblClick"
              @delete-edge="onDeleteEdge"
              @delete-step="onDeleteStep"
              @edge-label-change="onEdgeLabelChange"
              @node-drag-start="sopFlow.onNodeDragStart()"
              @node-drag-stop="sopFlow.onNodeDragStop()"
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
                  ref="metaPanelRef"
                  :sop-data="sopTree.currentSopData.value"
                  :all-sop-names="allSopNames"
                  :read-only="currentMode === 'view'"
                  @save="onSopMetaSave"
                  @cancel="onSopMetaCancel"
                  @dirty-change="onSopMetaDirtyChange"
                />
                <div v-else-if="!sopFlow.selectedStep.value" class="panel-empty">
                  选择流程图节点查看属性
                </div>
                <SOPPropertyPanel
                  v-else
                  ref="propertyPanelRef"
                  :step="sopFlow.selectedStep.value"
                  :read-only="currentMode === 'view'"
                  :step-targets="propertyStepTargets"
                  :failure-target-name="failureTargetName"
                  @save="onPropertySave"
                  @cancel="onPropertyCancel"
                  @select-citation="handleSopCitationSelect"
                  @dirty-change="onPropertyDirtyChange"
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
      title="导入 SOP"
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
        accept=".md"
      >
        <p class="ant-upload-drag-icon">
          <InboxOutlined />
        </p>
        <p class="ant-upload-text">点击或拖拽 Markdown 文件到此处</p>
        <p class="ant-upload-hint">仅支持 .md 格式的 SOP 文件，系统将自动解析步骤与变量</p>
      </a-upload-dragger>
<div class="import-sample-tip">
        <DownloadOutlined />
        <a @click.prevent="downloadSampleMd">下载示例文件</a>
        <span class="import-sample-hint">，按此格式编写后导入</span>
      </div>
    </a-modal>

    <a-modal
      :open="sopGenerateFromDocVisible"
      title="从文档生成 SOP"
      :confirm-loading="sopGenerateFromDocLoading"
      ok-text="生成"
      cancel-text="取消"
      @ok="confirmSopGenerateFromDoc"
      @cancel="sopGenerateFromDocVisible = false"
    >
      <div v-if="!docsWithGraph.length" style="padding: 16px 0; color: #9ca3af;">
        暂无已提取图谱的文档。请先在文档页面提取知识图谱。
      </div>
      <a-radio-group v-else v-model:value="selectedGenerateDocKey" :style="{ width: '100%' }">
        <a-radio
          v-for="doc in docsWithGraph"
          :key="doc.doc_id"
          :value="doc.library_id + '::' + doc.doc_id"
          :style="{ display: 'block', padding: '6px 0' }"
        >
          <span>{{ doc.name || doc.doc_id }}</span>
          <span :style="{ color: '#9ca3af', fontSize: '12px', marginLeft: '8px' }">
            {{ doc.doc_id }} · {{ doc.relation_count }} 条关系
          </span>
        </a-radio>
      </a-radio-group>
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

    <ForkEditModal
      v-model:visible="forkModalVisible"
      :condition-var="forkModalConditionVar"
      :branches="forkModalBranches"
      :default-goto="forkModalDefaultGoto"
      :step-targets="forkStepTargets"
      @confirm="onForkModalConfirm"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, h, nextTick, onMounted, ref } from 'vue'
import { App, Input, message, type UploadFile } from 'ant-design-vue'
import { useRouter, onBeforeRouteLeave } from 'vue-router'
import {
  ApartmentOutlined,
  DeleteOutlined,
  DownloadOutlined,
  EditOutlined,
  EyeOutlined,
  FileAddOutlined,
  FileTextOutlined,
  FolderAddOutlined,
  InboxOutlined,
  UploadOutlined,
} from '@ant-design/icons-vue'
import { SplitPanes, Panel, AIChat, useTheme, type CitationBinding, type DropEvent } from '@angineer/ui-kit'
import { SOPTree, SOPFlowCanvas, SOPPropertyPanel, SopMetaPanel, ForkEditModal, useSopTree, useSopFlow, sopApi } from '@angineer/sop-ui'
import type { SOPTreeNode, SopStep } from '@angineer/sop-ui'
import type { Connection } from '@vue-flow/core'
import FolderModal from './components/FolderModal.vue'

const { appClass } = useTheme()
const { modal } = App.useApp()
const router = useRouter()

const sopTree = useSopTree()
const sopFlow = useSopFlow()

const sopTreeRef = ref<InstanceType<typeof SOPTree> | null>(null)
const metaPanelRef = ref<InstanceType<typeof SopMetaPanel> | null>(null)
const propertyPanelRef = ref<InstanceType<typeof SOPPropertyPanel> | null>(null)
const rightTabKey = ref<'property' | 'ai'>('property')
const currentMode = ref<'edit' | 'view'>('edit')
const metaPanelDirty = ref(false)
const persistDirty = ref(false)
const forkModalVisible = ref(false)
const forkModalStepId = ref('')
const forkModalConditionVar = ref('')
const forkModalBranches = ref<Array<{ match: string; goto: string }>>([])
const forkModalDefaultGoto = ref('')

const forkStepTargets = computed(() => {
  return sopFlow.nodes.value
    .filter((n) => n.id !== forkModalStepId.value)
    .map((n) => ({
      id: n.id,
      name: n.data.step.name || n.data.step.name_zh || n.id,
    }))
})

/** 属性面板可用的跳转目标步骤列表，排除当前选中步骤自身。 */
const propertyStepTargets = computed(() => {
  const selectedId = sopFlow.selectedStepId.value
  return sopFlow.nodes.value
    .filter((n) => n.id !== selectedId)
    .map((n) => ({
      id: n.id,
      name: n.data.step.name || n.data.step.name_zh || n.id,
    }))
})

/** 当前选中步骤的失败跳转目标名称，用于属性面板只读展示。 */
const failureTargetName = computed(() => {
  const stepId = sopFlow.selectedStepId.value
  if (!stepId) return ''
  const failureEdge = sopFlow.edges.value.find(
    (e) => e.source === stepId && e.data?.isFailure,
  )
  if (!failureEdge) return ''
  const targetNode = sopFlow.nodes.value.find((n) => n.id === failureEdge.target)
  return targetNode?.data.step.name || targetNode?.data.step.name_zh || failureEdge.target
})

const pendingImportFolderId = ref<string | undefined>(undefined)
const importModalVisible = ref(false)

/**
 * 中间面板标题：显示当前 SOP 名称，无 SOP 时显示"流程图"。
 */
const centerPanelTitle = computed(() => {
  const data = sopTree.currentSopData.value
  return data?.name_zh || '流程图'
})
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

/**
 * 检查当前是否有未保存的修改。
 */
const hasUnsavedChanges = (): boolean => {
  return persistDirty.value
}

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
 * 弹出未保存修改确认弹窗，返回用户选择：'save' | 'discard' | 'stay'。
 * save: 保存后继续导航；discard: 不保存直接导航；stay: 留在当前页面。
 */
const confirmUnsavedNavigation = (): Promise<'save' | 'discard' | 'stay'> => {
  return new Promise((resolve) => {
    let resolved = false
    const safeResolve = (value: 'save' | 'discard' | 'stay') => {
      if (resolved) return
      resolved = true
      resolve(value)
    }
    modal.confirm({
      title: '未保存的修改',
      content: '当前有未保存的修改，是否保存？',
      okText: '保存并继续',
      cancelText: '不保存',
      onOk: () => safeResolve('save'),
      onCancel: () => safeResolve('discard'),
      maskClosable: false,
    })
  })
}

/**
 * 刷入属性面板草稿到内存。
 * force=false 时仅在有实际修改（hasChanges）时才刷入，避免点击切换节点误标脏。
 * force=true 时强制刷入，用于 AA 总保存（防止签名被意外重置导致漏刷）。
 */
const flushPropertyDraft = (force = false) => {
  if (!sopFlow.selectedStepId.value) return
  const panel = propertyPanelRef.value as any
  if (!panel) return
  if (!force && !panel.hasChanges?.value) return
  const draft = panel.buildDraftStep?.()
  if (draft) {
    sopFlow.updateStepData(sopFlow.selectedStepId.value, draft, true)
    panel.acceptDraft?.()
    sopFlow.stepPanelDirty.value.set(sopFlow.selectedStepId.value, false)
    sopFlow.stepPanelDirty.value = new Map(sopFlow.stepPanelDirty.value)
  }
}

/**
 * AA 总保存：刷所有面板草稿到内存 → 序列化整份 SOP → 持久化到 DB。
 * 步骤属性 + 流程图位置 + SOP 元数据一次性写入。
 * AA 覆盖 BB 和 CC：无论面板草稿是否已提交，都强制刷入并保存。
 */
const saveCurrentChanges = async () => {
  const currentData = sopTree.currentSopData.value
  if (!currentData) return

  flushPropertyDraft(true)

  if (metaPanelDirty.value) {
    const metaPanel = metaPanelRef.value as any
    if (metaPanel) {
      currentData.name_zh = (metaPanel.draftName || '').trim() || currentData.name_zh
      currentData.description = (metaPanel.draftDescription || '').trim() || currentData.description || ''
      if (sopTree.selectedNode.value) {
        sopTree.selectedNode.value.title = currentData.name_zh
      }
      metaPanel.acceptDraft?.()
      metaPanelDirty.value = false
    }
  }

  if (sopFlow.isDirty.value || persistDirty.value) {
    const updatedData = sopFlow.exportToSopData(currentData)
    await sopApi.saveSop(currentData.id, updatedData)
    sopTree.currentSopData.value = updatedData
    sopFlow.isDirty.value = false
    sopFlow.clearDirty()
    persistDirty.value = false
    ;(propertyPanelRef.value as any)?.acceptDraft?.()
  }
}

/**
 * BB 智能保存：flush 草稿到内存 → 检查是否可以自动触发 AA。
 * 如果所有面板草稿都已提交（无其他 BB 或 CC 脏），则自动触发 AA 持久化。
 */
const onPropertySave = (step: SopStep) => {
  if (currentMode.value === 'view') return
  if (!sopFlow.selectedStepId.value) return
  sopFlow.updateStepData(sopFlow.selectedStepId.value, step)
  sopFlow.stepPanelDirty.value.set(sopFlow.selectedStepId.value, false)
  sopFlow.stepPanelDirty.value = new Map(sopFlow.stepPanelDirty.value)
  persistDirty.value = true
  checkAutoPersist()
}

/**
 * CC 保存：flush 元数据草稿到内存 → 检查是否可以自动触发 AA。
 */
const onSopMetaSave = (payload: { name_zh: string; description: string }) => {
  const currentData = sopTree.currentSopData.value
  if (!currentData) return
  currentData.name_zh = payload.name_zh
  currentData.description = payload.description || ''
  if (sopTree.selectedNode.value) {
    sopTree.selectedNode.value.title = payload.name_zh
  }
  metaPanelDirty.value = false
  persistDirty.value = true
  sopFlow.isDirty.value = true
  checkAutoPersist()
}

/**
 * 检查是否可以自动触发 AA 持久化。
 * 条件：所有面板草稿都已提交（无 BB 脏、无 CC 脏）且 persistDirty 为 true。
 */
const checkAutoPersist = async () => {
  const hasStepPanelDirty = Array.from(sopFlow.stepPanelDirty.value.values()).some(Boolean)
  if (hasStepPanelDirty || metaPanelDirty.value) return
  if (!persistDirty.value) return
  try {
    await saveCurrentChanges()
    message.success('保存成功')
  } catch (error: any) {
    message.error(error?.message || '保存 SOP 失败')
  }
}

/**
 * 重置所有脏状态（不保存，仅清除标记），用于用户选择"不保存"时。
 */
const resetDirtyState = () => {
  sopFlow.isDirty.value = false
  sopFlow.clearDirty()
  persistDirty.value = false
  metaPanelDirty.value = false
  ;(propertyPanelRef.value as any)?.acceptDraft?.()
  ;(metaPanelRef.value as any)?.acceptDraft?.()
}

/**
 * 带未保存守卫的导航：检查是否有未保存修改，有则弹窗确认。
 * 返回 true 表示可以继续导航，false 表示用户选择留在当前页面。
 */
const guardAndNavigate = async (): Promise<boolean> => {
  if (!hasUnsavedChanges()) return true

  const choice = await confirmUnsavedNavigation()
  if (choice === 'stay') return false
  if (choice === 'save') {
    try {
      await saveCurrentChanges()
      message.success('已保存')
    } catch (error: any) {
      message.error(error?.message || '保存失败')
      return false
    }
  }
  if (choice === 'discard') {
    resetDirtyState()
  }
  return true
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
  // SmartTree deep-clones treeData internally; use original node for reactive propagation
  const originalNode = sopTree.findNode(sopTree.treeData.value, node.key) || node
  sopTree.setSelectedNode(originalNode)
  currentMode.value = node.isFolder ? 'edit' : mode
  metaPanelDirty.value = false
  persistDirty.value = false
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
 * 执行 SOP Markdown 导入。
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
 * 关闭 SOP 导入弹窗。
 */
const handleImportCancel = () => {
  importModalVisible.value = false
  importFileList.value = []
  pendingImportFolderId.value = undefined
}

const sopGenerateFromDocVisible = ref(false)
const sopGenerateFromDocLoading = ref(false)
const docsWithGraph = ref<Array<{ library_id: string; doc_id: string; name: string; relation_count: number }>>([])
const selectedGenerateDocKey = ref<string>('')

const openSopGenerateFromDoc = async () => {
  sopGenerateFromDocLoading.value = true
  try {
    docsWithGraph.value = await sopApi.listDocsWithGraph()
    selectedGenerateDocKey.value = ''
    sopGenerateFromDocVisible.value = true
  } catch (e: any) {
    message.error(e?.message || '获取文档列表失败')
  } finally {
    sopGenerateFromDocLoading.value = false
  }
}

const confirmSopGenerateFromDoc = async () => {
  if (!selectedGenerateDocKey.value) {
    message.warning('请先选择一个文档')
    return
  }
  const parts = selectedGenerateDocKey.value.split('::')
  const libraryId = parts[0]
  const docId = parts.slice(1).join('::')
  sopGenerateFromDocLoading.value = true
  try {
    const result = await sopApi.generateSopsFromDoc(libraryId, docId)
    const count = result?.total ?? result?.generated?.length ?? 0
    message.success(`成功生成 ${count} 个 SOP`)
    sopGenerateFromDocVisible.value = false
    selectedGenerateDocKey.value = ''
    await sopTree.fetchTreeFromApi()
    setTimeout(async () => {
      await sopTree.fetchTreeFromApi()
    }, 500)
  } catch (e: any) {
    message.error(e?.message || '生成失败')
  } finally {
    sopGenerateFromDocLoading.value = false
  }
}

/**
 * 下载示例 Markdown 文件。
 */
const downloadSampleMd = () => {
  const content = `# 示例：矩形面积计算

Description: 根据矩形的长和宽计算面积。

**输出变量**: 面积 S

## 实施步骤

### Step 1. 获取矩形的长 L

*   **Inputs**: L（矩形长度）
*   **Tool**: user_input
*   **Action**: 查阅【已知条件】获取矩形的长 L。
*   **Outputs**: L

### Step 2. 获取矩形的宽 W

*   **Inputs**: W（矩形宽度）
*   **Tool**: user_input
*   **Action**: 查阅【已知条件】获取矩形的宽 W。
*   **Outputs**: W

### Step 3. 计算矩形面积 S

*   **Inputs**: L、W
*   **Tool**: calculator
*   **Action**: 代入公式计算：S = L × W。
*   **Outputs**: S
`
  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = '示例.md'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

/**
 * 响应树节点选择。
 */
const onTreeSelect = async (_keys: string[], nodes: SOPTreeNode[]) => {
  if (nodes.length !== 1) return
  const node = nodes[0]
  if (!node) return
  const previousKey = sopTree.selectedNode.value?.key
  const canNavigate = await guardAndNavigate()
  if (!canNavigate) {
    await nextTick()
    if (sopTreeRef.value && previousKey) {
      sopTreeRef.value.selectedKeys = [previousKey]
    }
    return
  }
  await loadNode(node, 'edit')
}

/**
 * 查看节点时直接载入。
 */
const onTreeView = async (node: SOPTreeNode) => {
  const previousKey = sopTree.selectedNode.value?.key
  const canNavigate = await guardAndNavigate()
  if (!canNavigate) {
    await nextTick()
    if (sopTreeRef.value && previousKey) {
      sopTreeRef.value.selectedKeys = [previousKey]
    }
    return
  }
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
    const focusKey = event.dragKeys?.[0] || event.dragKey
    await refreshTreeAndFocus(focusKey)
  } catch (error: any) {
    message.error(error?.message || '移动失败')
    await refreshTreeAndFocus()
  }
}

/**
 * 拖到根目录。
 */
const onTreeDropRoot = async (dragNodeKeys: string[]) => {
  try {
    const firstKey = dragNodeKeys[0]
    if (dragNodeKeys.length === 1) {
      await sopTree.moveNodeToRoot(firstKey)
    } else {
      await sopTree.moveNodesToRoot(dragNodeKeys)
    }
    message.success('已移动到根目录')
    await refreshTreeAndFocus(firstKey)
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
    if (!file.name.toLowerCase().endsWith('.md')) {
      message.warning(`仅支持导入 Markdown 文件: ${file.name}`)
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
 * 切换前先把上一个步骤的面板草稿刷入内存，避免丢失未保存的属性修改。
 */
const onStepSelect = (stepId: string) => {
  flushPropertyDraft()
  sopFlow.selectStep(stepId)
  rightTabKey.value = 'property'
}

/**
 * 双击步骤后切到属性页。
 */
const onStepDblClick = (stepId: string) => {
  const node = sopFlow.nodes.value.find((n) => n.id === stepId)
  if (node?.type === 'sop-fork') {
    const step = node.data.step
    forkModalStepId.value = stepId
    forkModalConditionVar.value = step.condition_var || ''
    forkModalBranches.value = (step.branches || []).map((b: any) => ({
      match: String(b.match || ''),
      goto: b.goto || '',
    }))
    forkModalDefaultGoto.value = step.default_goto || ''
    forkModalVisible.value = true
    return
  }
  sopFlow.selectStep(stepId)
  rightTabKey.value = 'property'
}

/**
 * 确认 Fork 编辑弹窗内容，更新步骤数据并同步分支连线。
 */
const onForkModalConfirm = (payload: { conditionVar: string; branches: Array<{ match: string; goto: string }>; defaultGoto: string }) => {
  if (!forkModalStepId.value) return
  sopFlow.updateStepData(forkModalStepId.value, {
    condition_var: payload.conditionVar || undefined,
    branches: payload.branches.map((b) => ({
      match: b.match,
      goto: b.goto || undefined,
    })),
    default_goto: payload.defaultGoto || undefined,
  } as any)
  sopFlow.syncBranchEdges()
  message.success('分支条件已更新')
}

/**
 * 处理连线标签变更事件。
 */
const onEdgeLabelChange = (payload: { edgeId: string; label: string }) => {
  sopFlow.updateEdgeLabel(payload.edgeId, payload.label)
  persistDirty.value = true
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
  persistDirty.value = true
}

/**
 * 引用跳转。
 */
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
 * 属性面板内容变化时标记步骤为脏，显示红点。
 * 当面板草稿变脏时：标记红点 + stepPanelDirty + persistDirty。
 * 当面板草稿变干净时（BB 保存后）：仅清除 stepPanelDirty，
 * 不移除红点（因为数据可能还没持久化，红点由 persistDirty 控制）。
 */
const onPropertyDirtyChange = (dirty: boolean) => {
  if (sopFlow.selectedStepId.value) {
    sopFlow.stepPanelDirty.value.set(sopFlow.selectedStepId.value, dirty)
    sopFlow.stepPanelDirty.value = new Map(sopFlow.stepPanelDirty.value)
    if (dirty) {
      sopFlow.markStepDirty(sopFlow.selectedStepId.value)
      persistDirty.value = true
    }
  }
}

/**
 * SOP 元数据面板取消编辑。
 */
const onSopMetaCancel = () => {}

/**
 * SOP 元数据面板脏状态变化时，同步 CC 脏标记和 persistDirty。
 */
const onSopMetaDirtyChange = (dirty: boolean) => {
  metaPanelDirty.value = dirty
  if (dirty) {
    persistDirty.value = true
    sopFlow.isDirty.value = true
  }
}

/**
 * 从只读模式切换回编辑模式。
 */
/**
 * 保存整份 SOP。
 */
const onSaveSop = async () => {
  if (currentMode.value === 'view') {
    message.warning('只读模式下不能保存')
    return
  }
  try {
    await saveCurrentChanges()
    message.success('保存成功')
  } catch (error: any) {
    message.error(error?.message || '保存 SOP 失败')
  }
}

/**
 * 撤销上一步操作。
 * 若撤销栈已空且无其他脏标记，说明回到初始状态，persistDirty 置 false。
 */
const onUndo = () => {
  sopFlow.undo()
  const hasStepPanelDirty = Array.from(sopFlow.stepPanelDirty.value.values()).some(Boolean)
  if (sopFlow.undoStack.value.length === 0 && !hasStepPanelDirty && !metaPanelDirty.value) {
    persistDirty.value = false
    sopFlow.isDirty.value = false
    sopFlow.dirtyStepIds.value = new Set()
    sopFlow.nodes.value = sopFlow.nodes.value.map((n) => ({
      ...n,
      data: { ...n.data, dirty: false },
    }))
  } else {
    persistDirty.value = true
  }
}

/**
 * 重做上一步撤销的操作。
 */
const onRedo = () => {
  sopFlow.redo()
  persistDirty.value = true
}

/**
 * 自动布局画布。
 */
const onAutoLayout = () => {
  sopFlow.autoLayout()
  persistDirty.value = true
}

/**
 * 同步流程图节点变化，同步 persistDirty。
 */
const onNodesChange = (changes: any[]) => {
  sopFlow.handleNodesChange(changes)
  if (sopFlow.isDirty.value) {
    persistDirty.value = true
  }
}

/**
 * 同步流程图连线变化，同步 persistDirty。
 */
const onEdgesChange = (changes: any[]) => {
  sopFlow.handleEdgesChange(changes)
  if (sopFlow.isDirty.value) {
    persistDirty.value = true
  }
}

/**
 * 新建两个步骤之间的连接。
 */
const onConnect = (connection: Connection) => {
  if (currentMode.value === 'view') {
    return
  }
  sopFlow.connectSteps(connection)
  persistDirty.value = true
}

/**
 * 更新现有连线的端点关系。
 */
const onEdgeUpdate = ({ edgeId, connection }: { edgeId: string; connection: Connection }) => {
  if (currentMode.value === 'view') {
    return
  }
  sopFlow.updateEdgeConnection(edgeId, connection)
  persistDirty.value = true
}

/**
 * 双击边 → 编辑分支条件标签。
 */
const onEdgeDblClick = (edgeId: string) => {
  if (currentMode.value === 'view') return
  const edge = sopFlow.edges.value.find((e) => e.id === edgeId)
  if (!edge) return
  let inputValue = edge.data?.label || ''
  modal.confirm({
    title: '编辑分支条件',
    content: h('div', { style: 'margin-top: 16px' }, [
      h('div', { style: 'margin-bottom: 8px; font-size: 13px; color: var(--text-secondary, #666)' }, '分支条件文字（显示在连接线上）：'),
      h(Input, {
        modelValue: inputValue,
        'onUpdate:modelValue': (v: string) => { inputValue = v },
        placeholder: '例如：岩石、≥50、淤泥...',
        style: 'margin-top: 4px',
      }),
    ]),
    okText: '确定',
    cancelText: '取消',
    onOk: () => {
      if (inputValue.trim()) {
        sopFlow.updateEdgeLabel(edgeId, inputValue.trim())
      }
    },
  })
}
const onDeleteStep = (stepId: string) => {
  if (currentMode.value === 'view') {
    message.warning('只读模式下不能删除步骤')
    return
  }
  const node = sopFlow.nodes.value.find((n) => n.id === stepId)
  const stepName = node?.data?.step?.name || stepId
  modal.confirm({
    title: '确认删除',
    content: `确定要删除步骤「${stepName}」吗？`,
    okText: '删除',
    okType: 'danger',
    cancelText: '取消',
    onOk: () => {
      sopFlow.removeStep(stepId)
      persistDirty.value = true
    },
  })
}

const onDeleteEdge = (edgeId: string) => {
  if (currentMode.value === 'view') return
  modal.confirm({
    title: '确认删除',
    content: '确定要删除这条连线吗？',
    okText: '删除',
    okType: 'danger',
    cancelText: '取消',
    onOk: () => {
      sopFlow.removeEdge(edgeId)
      persistDirty.value = true
    },
  })
}

onBeforeRouteLeave(async (_to, _from, next) => {
  const canLeave = await guardAndNavigate()
  if (canLeave) {
    next()
  } else {
    next(false)
  }
})

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

.import-sample-tip {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 12px;
  font-size: 13px;
  color: var(--text-secondary, #8c8c8c);

  a {
    color: var(--primary-color, #1890ff);
    text-decoration: none;

    &:hover {
      text-decoration: underline;
    }
  }
}

.import-sample-hint {
  color: var(--text-tertiary, #bfbfbf);
}

.sop-title-dirty-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--error-color, #ff4d4f);
  margin-left: 6px;
  vertical-align: middle;
}
</style>
