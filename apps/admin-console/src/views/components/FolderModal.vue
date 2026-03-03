<template>
  <!-- 文件夹弹窗组件 - 用于新建/重命名文件夹 -->
  <a-modal
    :open="visible"
    :title="title"
    :confirm-loading="loading"
    @ok="$emit('confirm')"
    @update:open="$emit('update:visible', $event)"
  >
    <a-form layout="vertical">
      <a-form-item label="名称">
        <a-input
          :value="name"
          @update:value="$emit('update:name', $event)"
          placeholder="请输入名称"
          @pressEnter="$emit('confirm')"
        />
      </a-form-item>
      <a-form-item v-if="isNew && !parentId" label="父级文件夹（可选）">
        <a-tree-select
          :value="parentId"
          @update:value="$emit('update:parent-id', $event)"
          :tree-data="folderTreeData"
          placeholder="选择父级文件夹"
          allow-clear
          tree-default-expand-all
        />
      </a-form-item>
    </a-form>
  </a-modal>
</template>

<script setup lang="ts">
/**
 * 文件夹弹窗组件
 * 用于新建文件夹或重命名现有文件夹
 */
interface Props {
  /** 弹窗可见性 */
  visible: boolean
  /** 弹窗标题 */
  title: string
  /** 确认按钮加载状态 */
  loading: boolean
  /** 文件夹树数据 */
  folderTreeData: any[]
  /** 文件夹名称 */
  name: string
  /** 父级文件夹ID */
  parentId?: string
  /** 是否为新建模式 */
  isNew: boolean
}

defineProps<Props>()

defineEmits<{
  'update:visible': [value: boolean]
  'update:name': [value: string]
  'update:parent-id': [value: string | undefined]
  confirm: []
}>()
</script>
