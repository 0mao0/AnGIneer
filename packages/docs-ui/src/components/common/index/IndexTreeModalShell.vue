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

interface Props {
  open: boolean
  title?: string
  width?: number | string
  confirmLoading?: boolean
  okText?: string
  cancelText?: string
  darkMode?: boolean
  okButtonProps?: Record<string, unknown>
}

const props = withDefaults(defineProps<Props>(), {
  title: '',
  width: 840,
  confirmLoading: false,
  okText: '确认',
  cancelText: '取消',
  darkMode: false,
  okButtonProps: () => ({})
})

const emit = defineEmits<{
  'update:open': [value: boolean]
  ok: []
  cancel: []
}>()

const wrapClassName = computed(() => (
  props.darkMode ? 'index-tree-modal index-tree-modal-dark' : 'index-tree-modal'
))

/* 同步关闭行为给外层弹窗状态。 */
const onCancel = () => {
  emit('cancel')
  emit('update:open', false)
}
</script>

<style lang="less">
.index-tree-modal-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--dp-title-strong, #0f172a);
}

.index-tree-modal .ant-modal-content {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  box-shadow: 0 18px 48px rgba(15, 23, 42, 0.24);
}

.index-tree-modal .ant-modal-header {
  background: transparent;
  border-bottom: 1px solid #edf1f7;
  padding-top: 12px;
  padding-bottom: 10px;
}

.index-tree-modal .ant-modal-title,
.index-tree-modal .ant-form-item-label > label,
.index-tree-modal .ant-select-selection-item,
.index-tree-modal .ant-select-selection-placeholder,
.index-tree-modal .ant-input,
.index-tree-modal .ant-input-textarea,
.index-tree-modal .ant-modal-close-x {
  color: #0f172a;
}

.index-tree-modal .ant-input,
.index-tree-modal .ant-input-affix-wrapper,
.index-tree-modal .ant-select-selector,
.index-tree-modal .ant-input-number,
.index-tree-modal .ant-input-textarea textarea {
  background: #ffffff;
  border-color: #e2e8f0;
}

.index-tree-modal .ant-modal-footer {
  border-top: 1px solid #edf1f7;
  padding-top: 10px;
  padding-bottom: 10px;
}

.index-tree-modal .ant-modal-body {
  background: transparent;
  padding-top: 10px;
  max-height: min(66vh, 680px);
  overflow: auto;
}

.index-tree-modal .ant-modal-close {
  top: 10px;
}

.index-tree-modal .ant-select-selector,
.index-tree-modal .ant-input,
.index-tree-modal .ant-input-textarea textarea {
  min-height: 34px;
  padding-top: 4px;
  padding-bottom: 4px;
}

.index-tree-modal-dark .ant-modal-content {
  background: #141922;
  border-color: #242c39;
}

.index-tree-modal-dark .ant-modal-header,
.index-tree-modal-dark .ant-modal-footer {
  border-color: #242c39;
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
  color: rgba(255, 255, 255, 0.82);
}

.index-tree-modal-dark .ant-input,
.index-tree-modal-dark .ant-input-affix-wrapper,
.index-tree-modal-dark .ant-select-selector,
.index-tree-modal-dark .ant-input-number,
.index-tree-modal-dark .ant-input-textarea textarea {
  background: #0f141d;
  border-color: #242c39;
}

.index-tree-modal-dark .ant-select-disabled .ant-select-selector,
.index-tree-modal-dark .ant-select-multiple.ant-select-disabled .ant-select-selection-item {
  background: #0f141d;
  color: rgba(255, 255, 255, 0.72);
}

.index-tree-modal-dark .ant-btn-text {
  color: rgba(255, 255, 255, 0.72);
}

.index-tree-modal-dark .ant-btn-text:hover {
  background: rgba(148, 163, 184, 0.14);
}

.index-tree-modal-dark .ant-select-arrow,
.index-tree-modal-dark .ant-modal-close-x {
  color: rgba(255, 255, 255, 0.62);
}
</style>
