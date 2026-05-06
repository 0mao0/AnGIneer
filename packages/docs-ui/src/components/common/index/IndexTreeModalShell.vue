<template>
  <a-modal
    :open="open"
    :confirm-loading="confirmLoading"
    :ok-button-props="okButtonProps"
    :ok-text="okText"
    :cancel-text="cancelText"
    :width="width"
    :wrap-class-name="wrapClassName"
    @update:open="emit('update:open', $event)"
    @ok="emit('ok')"
    @cancel="onCancel"
  >
    <template #title>
      <slot name="title">
        <div class="index-tree-modal-title">{{ title }}</div>
      </slot>
    </template>
    <slot />
  </a-modal>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useTheme } from '@angineer/ui-kit'

interface Props {
  open: boolean
  title?: string
  width?: number | string
  confirmLoading?: boolean
  okText?: string
  cancelText?: string
  okButtonProps?: Record<string, unknown>
}

withDefaults(defineProps<Props>(), {
  title: '',
  width: 840,
  confirmLoading: false,
  okText: '确认',
  cancelText: '取消',
  okButtonProps: () => ({})
})

const emit = defineEmits<{
  'update:open': [value: boolean]
  ok: []
  cancel: []
}>()

const { isDark } = useTheme()

const wrapClassName = computed(() => {
  const base = 'index-tree-modal'
  return isDark.value ? `${base} ${base}-dark` : base
})

/* 同步关闭行为给外层弹窗状态。 */
const onCancel = () => {
  emit('cancel')
  emit('update:open', false)
}
</script>

<style lang="less" scoped>
.index-tree-modal-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--dp-title-strong);
}

:deep(.ant-modal-content) {
  background: var(--dp-pane-bg);
  border: 1px solid var(--dp-pane-border);
  box-shadow: 0 18px 48px rgba(15, 23, 42, 0.24);
}

:deep(.ant-modal-header) {
  background: transparent;
  border-bottom: 1px solid var(--dp-pane-border);
  padding-top: 12px;
  padding-bottom: 10px;
}

:deep(.ant-modal-title),
:deep(.ant-form-item-label > label),
:deep(.ant-select-selection-item),
:deep(.ant-select-selection-placeholder),
:deep(.ant-input),
:deep(.ant-input-textarea),
:deep(.ant-modal-close-x) {
  color: var(--dp-title-strong);
}

:deep(.ant-input),
:deep(.ant-input-affix-wrapper),
:deep(.ant-select-selector),
:deep(.ant-input-number),
:deep(.ant-input-textarea textarea) {
  background: var(--dp-pane-bg);
  border-color: var(--dp-pane-border);
}

:deep(.ant-modal-footer) {
  border-top: 1px solid var(--dp-pane-border);
  padding-top: 10px;
  padding-bottom: 10px;
}

:deep(.ant-modal-body) {
  background: transparent;
  padding-top: 10px;
  max-height: min(66vh, 680px);
  overflow: auto;
}

:deep(.ant-modal-close) {
  top: 10px;
}

:deep(.ant-select-selector),
:deep(.ant-input),
:deep(.ant-input-textarea textarea) {
  min-height: 34px;
  padding-top: 4px;
  padding-bottom: 4px;
}
</style>

<style lang="less">
.index-tree-modal-dark .ant-modal-content {
  background: var(--dp-pane-bg);
  border-color: var(--dp-pane-border);
}

.index-tree-modal-dark .ant-modal-header,
.index-tree-modal-dark .ant-modal-footer {
  border-color: var(--dp-pane-border);
}

.index-tree-modal-dark .ant-modal-title,
.index-tree-modal-dark .ant-form-item-label > label,
.index-tree-modal-dark .ant-select-selection-item,
.index-tree-modal-dark .ant-select-selection-placeholder,
.index-tree-modal-dark .ant-select-multiple .ant-select-selection-item,
.index-tree-modal-dark .ant-select-disabled.ant-select-multiple .ant-select-selection-item,
.index-tree-modal-dark .ant-input,
.index-tree-modal-dark .ant-input-textarea,
.index-tree-modal-dark .ant-modal-close-x {
  color: var(--dp-title-text);
}

.index-tree-modal-dark .ant-input,
.index-tree-modal-dark .ant-input-affix-wrapper,
.index-tree-modal-dark .ant-select-selector,
.index-tree-modal-dark .ant-input-number,
.index-tree-modal-dark .ant-input-textarea textarea {
  background: var(--dp-content-bg);
  border-color: var(--dp-pane-border);
}

.index-tree-modal-dark .ant-select-disabled .ant-select-selector,
.index-tree-modal-dark .ant-select-multiple.ant-select-disabled .ant-select-selection-item {
  background: var(--dp-content-bg);
  color: var(--dp-sub-text);
}

.index-tree-modal-dark .ant-btn-text {
  color: var(--dp-sub-text);
}

.index-tree-modal-dark .ant-btn-text:hover {
  background: var(--dp-hover-bg);
}

.index-tree-modal-dark .ant-select-arrow,
.index-tree-modal-dark .ant-modal-close-x {
  color: var(--dp-sub-text);
}
</style>
