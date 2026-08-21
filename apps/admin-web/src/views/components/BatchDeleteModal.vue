<template>
  <a-modal
    :open="visible"
    :title="`批量删除 - ${folderNode?.title || ''}`"
    :width="560"
    :ok-text="`删除选中 (${checkedKeys.length})`"
    ok-type="danger"
    cancel-text="取消"
    :ok-button-props="{ disabled: checkedKeys.length === 0, loading: deleting }"
    :mask-closable="!deleting"
    :closable="!deleting"
    @ok="handleConfirm"
    @update:open="(v: boolean) => emit('update:visible', v)"
  >
    <div class="batch-delete-body">
      <div class="batch-delete-toolbar">
        <a-checkbox
          :checked="allChecked"
          :indeterminate="indeterminate"
          @change="toggleSelectAll"
        >
          全选（{{ checkedKeys.length }}/{{ fileList.length }}）
        </a-checkbox>
        <span class="batch-delete-tip">将标记为已删除并从树中隐藏，数据保留</span>
      </div>
      <div class="batch-delete-list">
        <a-empty v-if="!fileList.length" description="该文件夹下没有文件" :image="simpleImage" />
        <label
          v-for="file in fileList"
          :key="file.key"
          class="batch-delete-item"
          :class="{ checked: checkedSet.has(file.key) }"
        >
          <a-checkbox
            :checked="checkedSet.has(file.key)"
            @change="toggleOne(file.key)"
          />
          <span class="batch-delete-item-title" :title="file.title">{{ file.title }}</span>
          <a-tag
            v-if="file.status"
            :color="getStatusColor(file.status)"
            size="small"
            class="batch-delete-item-status"
          >
            {{ getStatusText(file.status) }}
          </a-tag>
        </label>
      </div>
    </div>
  </a-modal>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Empty, message } from 'ant-design-vue'
import { getStatusColor, getStatusText } from '@angineer/ui-kit/utils/tree'
import type { KnowledgeApiPort, KnowledgeTreeNode } from '@angineer/docs-ui'

const props = defineProps<{
  visible: boolean
  folderNode: KnowledgeTreeNode | null
  api: KnowledgeApiPort
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
  deleted: []
}>()

const simpleImage = Empty.PRESENTED_IMAGE_SIMPLE

const checkedKeys = ref<string[]>([])
const checkedSet = computed(() => new Set(checkedKeys.value))
const deleting = ref(false)

// 递归收集文件夹下所有文件节点（含子文件夹）
const fileList = computed<KnowledgeTreeNode[]>(() => {
  const root = props.folderNode
  if (!root) return []
  const result: KnowledgeTreeNode[] = []
  const walk = (nodes: KnowledgeTreeNode[]) => {
    for (const node of nodes) {
      if (node.isFolder) {
        if (node.children?.length) walk(node.children as KnowledgeTreeNode[])
      } else {
        result.push(node)
      }
    }
  }
  walk([root])
  return result
})

const allChecked = computed(() => fileList.value.length > 0 && checkedKeys.value.length === fileList.value.length)
const indeterminate = computed(() => checkedKeys.value.length > 0 && checkedKeys.value.length < fileList.value.length)

function toggleSelectAll() {
  checkedKeys.value = allChecked.value ? [] : fileList.value.map(f => f.key)
}

function toggleOne(key: string) {
  if (checkedSet.value.has(key)) {
    checkedKeys.value = checkedKeys.value.filter(k => k !== key)
  } else {
    checkedKeys.value = [...checkedKeys.value, key]
  }
}

// 每次打开时默认全不选，避免误删
watch(() => props.visible, (open) => {
  if (open) checkedKeys.value = []
})

async function handleConfirm() {
  if (!checkedKeys.value.length || deleting.value) return
  deleting.value = true
  const targets = [...checkedKeys.value]
  let failed = 0
  try {
    for (const key of targets) {
      try {
        await props.api.softDeleteNode(key)
      } catch {
        failed += 1
      }
    }
    if (failed === 0) {
      message.success(`已删除 ${targets.length} 个文件（数据保留）`)
    } else {
      message.warning(`已删除 ${targets.length - failed} 个，失败 ${failed} 个`)
    }
    emit('update:visible', false)
    emit('deleted')
  } finally {
    deleting.value = false
  }
}
</script>

<style lang="less" scoped>
.batch-delete-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.batch-delete-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border-color, #f0f0f0);
}
.batch-delete-tip {
  font-size: 12px;
  color: var(--text-secondary, rgba(0, 0, 0, 0.45));
}
.batch-delete-list {
  max-height: 50vh;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}
.batch-delete-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 6px;
  cursor: pointer;
  user-select: none;

  &:hover {
    background: var(--bg-tertiary, #fafafa);
  }
  &.checked {
    background: color-mix(in srgb, var(--primary-color, #1677ff) 8%, transparent);
  }
}
.batch-delete-item-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
}
.batch-delete-item-status {
  flex-shrink: 0;
  margin-inline-end: 0;
}
</style>
