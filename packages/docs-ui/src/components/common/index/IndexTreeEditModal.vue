<template>
  <IndexTreeModalShell
    :open="open"
    :confirm-loading="saving"
    :ok-button-props="{ disabled: !nodeEditHasChanges }"
    ok-text="保存修改"
    cancel-text="取消"
    :width="840"
    @update:open="emit('update:open', $event)"
    @cancel="emit('cancel')"
    @ok="submitEdit"
  >
    <template #title>
      <div class="edit-modal-title">
        <div class="edit-modal-title-text">修改节点内容</div>
      </div>
    </template>
    <template v-if="node">
      <div class="edit-compact-bar">
        <div class="edit-compact-main">
          <div class="edit-compact-title">{{ nodeDisplayTitle }}</div>
          <div class="edit-node-meta">
            <a-tag class="edit-node-tag edit-node-tag-type">{{ node.block_type || 'segment' }}</a-tag>
            <a-tag class="edit-node-tag">页 {{ Number(node.page_idx || 0) + 1 }}</a-tag>
            <a-tag class="edit-node-tag">块 {{ node.block_seq || 0 }}</a-tag>
            <span class="edit-node-id">{{ node.block_uid || node.id }}</span>
          </div>
        </div>
        <div class="edit-compact-metrics">
          <span class="edit-compact-metric edit-compact-metric-active">已改 {{ nodeEditChangeCount }} 项</span>
          <span class="edit-compact-metric">{{ editPlainTextLength }} 字</span>
        </div>
      </div>
      <div class="edit-dialog-layout">
        <div class="edit-dialog-main">
          <div class="edit-surface-card">
            <div class="edit-section-head">
              <div class="edit-section-title">内容编辑</div>
              <div v-if="nodeEditPendingActionLabels.length" class="edit-inline-plan-tags">
                <span v-for="action in nodeEditPendingActionLabels" :key="action" class="edit-inline-plan-tag">{{ action }}</span>
              </div>
            </div>
            <a-form layout="vertical" class="edit-form">
              <a-form-item v-if="showPlainTextEditor" label="识别文本" class="edit-form-item-card">
                <a-textarea
                  v-model:value="editForm.plain_text"
                  :auto-size="{ minRows: 5, maxRows: 10 }"
                  placeholder="修正 OCR 识别后的正文或标题文本"
                />
                <div class="edit-field-meta">
                  <span>{{ editForm.plain_text.trim().length }} 字</span>
                </div>
              </a-form-item>
              <a-form-item v-if="showMathEditor" label="公式源码" class="edit-form-item-card">
                <a-textarea
                  v-model:value="editForm.math_content"
                  :auto-size="{ minRows: 3, maxRows: 8 }"
                  placeholder="补充或修正公式源码"
                />
                <div class="edit-field-meta">
                  <span>{{ editForm.math_content.trim().length }} 字</span>
                </div>
              </a-form-item>
              <a-form-item v-if="showTableEditor" label="表格 HTML" class="edit-form-item-card">
                <a-textarea
                  v-model:value="editForm.table_html"
                  :auto-size="{ minRows: 6, maxRows: 12 }"
                  placeholder="修正表格 HTML 结构"
                />
                <div class="edit-field-meta">
                  <span>{{ editForm.table_html.trim().length }} 字</span>
                </div>
              </a-form-item>
              <a-form-item v-if="showCaptionEditor" label="题注" class="edit-form-item-card">
                <a-textarea
                  v-model:value="editForm.caption"
                  :auto-size="{ minRows: 2, maxRows: 5 }"
                  placeholder="补充图表题注"
                />
                <div class="edit-field-meta">
                  <span>{{ editForm.caption.trim().length }} 字</span>
                </div>
              </a-form-item>
              <a-form-item v-if="showFootnoteEditor" label="注释" class="edit-form-item-card">
                <a-textarea
                  v-model:value="editForm.footnote"
                  :auto-size="{ minRows: 2, maxRows: 5 }"
                  placeholder="补充脚注、来源或说明"
                />
                <div class="edit-field-meta">
                  <span>{{ editForm.footnote.trim().length }} 字</span>
                </div>
              </a-form-item>
            </a-form>
          </div>
        </div>
        <div class="edit-dialog-side">
          <div class="edit-surface-card">
            <div class="edit-section-head">
              <div class="edit-section-title">结构设置</div>
            </div>
            <a-form layout="vertical" class="edit-form">
              <a-form-item label="父级节点" class="edit-form-item-card">
                <a-select
                  v-model:value="editForm.parent_block_uid"
                  :options="parentNodeOptions"
                  allow-clear
                  show-search
                  option-filter-prop="label"
                  placeholder="选择新的父级节点"
                />
              </a-form-item>
              <a-form-item label="标题层次" class="edit-form-item-card">
                <a-select
                  v-model:value="editForm.derived_title_level"
                  :options="headingLevelOptions"
                  allow-clear
                  placeholder="留空表示非标题节点"
                />
              </a-form-item>
              <a-form-item label="合并到目标 block" class="edit-form-item-card">
                <a-select
                  v-model:value="editForm.merge_into_block_uid"
                  :options="mergeTargetOptions"
                  allow-clear
                  show-search
                  option-filter-prop="label"
                  placeholder="不合并，仅更新当前 block"
                />
              </a-form-item>
              <div v-if="hierarchyHintText" class="edit-hint-card">
                <div class="edit-hint-text">{{ hierarchyHintText }}</div>
              </div>
              <div v-if="mergeWarningText" class="edit-warning-card">
                <div class="edit-warning-title">合并提醒</div>
                <div class="edit-warning-text">{{ mergeWarningText }}</div>
              </div>
            </a-form>
          </div>
        </div>
      </div>
    </template>
  </IndexTreeModalShell>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import type {
  DocBlockNode,
  StructuredNodeUpdatePayload
} from '../../../types/knowledge'
import IndexTreeModalShell from './IndexTreeModalShell.vue'
import {
  ROOT_PARENT_VALUE,
  buildNodeEditPayload,
  buildOrderedNodeOptions,
  createEditFormFromNode,
  getNodeEditActionLabels,
  type IndexTreeEditForm
} from './indexTreeModalUtils'

interface Props {
  open: boolean
  node: DocBlockNode | null
  nodeMap: Map<string, DocBlockNode>
  saving?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  saving: false
})

const emit = defineEmits<{
  'update:open': [value: boolean]
  cancel: []
  submit: [payload: StructuredNodeUpdatePayload]
}>()

const editForm = ref<IndexTreeEditForm>({
  plain_text: '',
  math_content: '',
  table_html: '',
  caption: '',
  footnote: '',
  parent_block_uid: ROOT_PARENT_VALUE,
  derived_title_level: null,
  merge_into_block_uid: undefined
})

/* 当弹窗打开或节点变化时回填表单。 */
const syncEditForm = () => {
  if (!props.node) return
  editForm.value = createEditFormFromNode(props.node)
}

watch(() => [props.open, props.node?.id], () => {
  if (props.open && props.node) {
    syncEditForm()
  }
}, { immediate: true })

const showPlainTextEditor = computed(() => Boolean(props.node))
const showMathEditor = computed(() => {
  const blockType = String(props.node?.block_type || '').toLowerCase()
  return ['formula', 'equation', 'math'].includes(blockType) || Boolean(props.node?.math_content)
})
const showTableEditor = computed(() => {
  const blockType = String(props.node?.block_type || '').toLowerCase()
  return blockType === 'table' || Boolean(props.node?.table_html)
})
const showCaptionEditor = computed(() => {
  const blockType = String(props.node?.block_type || '').toLowerCase()
  return ['table', 'image', 'figure'].includes(blockType) || Boolean(props.node?.caption)
})
const showFootnoteEditor = computed(() => {
  const blockType = String(props.node?.block_type || '').toLowerCase()
  return ['table', 'image', 'figure'].includes(blockType) || Boolean(props.node?.footnote)
})

const orderedNodeOptions = computed(() => buildOrderedNodeOptions(props.nodeMap))
const parentNodeOptions = computed(() => {
  const currentId = props.node?.block_uid || props.node?.id || ''
  return [
    { value: ROOT_PARENT_VALUE, label: '设为根节点' },
    ...orderedNodeOptions.value.filter(option => option.value !== currentId)
  ]
})
const mergeTargetOptions = computed(() => {
  const currentId = props.node?.block_uid || props.node?.id || ''
  return orderedNodeOptions.value.filter(option => option.value !== currentId)
})
const headingLevelOptions = computed(() => Array.from({ length: 6 }, (_, index) => ({
  value: index + 1,
  label: `L${index + 1} / ${index + 1} 级标题`
})))
const editPlainTextLength = computed(() => String(editForm.value.plain_text || '').trim().length)
const nodeDisplayTitle = computed(() => {
  const previewText = String(
    editForm.value.plain_text
    || props.node?.plain_text
    || props.node?.title_path
    || ''
  ).trim()
  return previewText ? previewText.slice(0, 80) : '未命名节点'
})
const nodeEditPayloadPreview = computed(() => (
  props.node ? buildNodeEditPayload(props.node, editForm.value) : null
))
const nodeEditChangeCount = computed(() => {
  const payload = nodeEditPayloadPreview.value
  return payload ? Math.max(0, Object.keys(payload).length - 1) : 0
})
const nodeEditHasChanges = computed(() => nodeEditChangeCount.value > 0)
const nodeEditPendingActionLabels = computed(() => getNodeEditActionLabels(nodeEditPayloadPreview.value))
const mergeWarningText = computed(() => (
  editForm.value.merge_into_block_uid
    ? '当前 block 会在保存后并入目标 block，并从结构树中移除，请确认目标节点选择正确。'
    : ''
))
const hierarchyHintText = computed(() => {
  const targetLevel = editForm.value.derived_title_level
  if (typeof targetLevel !== 'number' || targetLevel <= 1) return ''
  if (editForm.value.parent_block_uid !== ROOT_PARENT_VALUE) {
    return `当前会作为 L${targetLevel} 节点挂到所选父级下。`
  }
  return `当前仅设置为 L${targetLevel} 时，保存后会自动挂到最近的上一级标题下；如需精确控制，请直接选择父级节点。`
})

/* 提交节点编辑结果给外层工作区。 */
const submitEdit = () => {
  if (!props.node) return
  const payload = buildNodeEditPayload(props.node, editForm.value)
  if (!payload) {
    message.info('内容未修改')
    emit('update:open', false)
    return
  }
  emit('submit', payload)
}
</script>

<style lang="less">
.edit-modal-title {
  display: flex;
  flex-direction: column;
}

.edit-modal-title-text {
  font-size: 15px;
  font-weight: 600;
  color: var(--dp-title-strong);
}

.edit-node-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.edit-compact-bar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
  padding: 10px 12px;
  border-radius: 12px;
  border: 1px solid var(--dp-pane-border);
  background: var(--dp-surface-bg);
}

.edit-compact-main {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.edit-compact-title {
  font-size: 14px;
  font-weight: 600;
  line-height: 1.4;
  color: var(--dp-title-strong);
  word-break: break-word;
}

.edit-compact-metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
  justify-content: flex-end;
}

.edit-node-id {
  color: var(--dp-sub-text);
  font-size: 12px;
}

.edit-compact-metric {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  padding: 1px 8px;
  border-radius: 999px;
  border: 1px solid var(--dp-badge-border);
  background: var(--dp-badge-bg);
  color: var(--dp-badge-text);
  font-size: 12px;
}

.edit-compact-metric-active {
  border-color: var(--dp-badge-active-border);
  background: var(--dp-badge-active-bg);
  color: var(--dp-badge-active-text);
}

.edit-inline-plan-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.edit-inline-plan-tag,
.edit-node-tag {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 20px;
  padding: 0 8px;
  border-radius: 999px;
  border: 1px solid var(--dp-tag-border);
  background: var(--dp-tag-bg);
  color: var(--dp-title-text);
  font-size: 11px;
}

.edit-node-tag-type,
.edit-inline-plan-tag {
  border-color: var(--dp-tag-active-border);
  background: var(--dp-tag-active-bg);
  color: var(--dp-tag-active-text);
  font-weight: 500;
}

.edit-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}

.edit-dialog-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.7fr) minmax(280px, 0.95fr);
  gap: 10px;
}

.edit-dialog-main,
.edit-dialog-side {
  min-width: 0;
}

.edit-dialog-side {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.edit-surface-card {
  padding: 10px;
  border-radius: 12px;
  border: 1px solid var(--dp-pane-border);
  background: var(--dp-surface-bg);
  box-shadow: none;
}

.edit-section-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--dp-title-strong);
}

.edit-form .ant-form-item {
  margin-bottom: 8px;
}

.edit-form .ant-form-item:last-child {
  margin-bottom: 0;
}

.edit-form-item-card {
  padding: 0;
  border: none;
  background: transparent;
}

.edit-form-item-card .ant-form-item-label {
  padding-bottom: 2px;
}

.edit-form .ant-form-item-label > label {
  min-height: 20px;
  font-size: 12px;
}

.edit-form-item-card textarea,
.edit-form-item-card .ant-select-selector {
  border-radius: 8px;
}

.edit-field-meta {
  display: flex;
  justify-content: flex-end;
  margin-top: 2px;
  color: var(--dp-sub-text);
  font-size: 11px;
  line-height: 1.2;
}

.edit-warning-card {
  margin-top: 4px;
  padding: 8px 10px;
  border-radius: 10px;
  border: 1px solid var(--dp-warning-border);
  background: var(--dp-warning-bg);
}

.edit-hint-card {
  margin-top: 4px;
  padding: 8px 10px;
  border-radius: 10px;
  border: 1px solid var(--dp-hint-border);
  background: var(--dp-hint-bg);
}

.edit-warning-title {
  margin-bottom: 4px;
  font-size: 12px;
  font-weight: 600;
  color: var(--dp-warning-title);
}

.edit-warning-text {
  font-size: 12px;
  line-height: 1.6;
  color: var(--dp-warning-text);
}

.edit-hint-text {
  font-size: 12px;
  line-height: 1.6;
  color: var(--dp-badge-active-text);
}

@media (max-width: 900px) {
  .edit-compact-bar {
    flex-direction: column;
  }

  .edit-dialog-layout {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .edit-section-head {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
