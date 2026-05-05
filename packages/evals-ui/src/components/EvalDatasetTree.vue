<template>
  <div class="eval-dataset-tree">
    <div class="eval-dataset-tree__header">
      <span class="eval-dataset-tree__title">测试集</span>
    </div>
    <div class="eval-dataset-tree__body">
      <a-tree
        v-if="treeData.length"
        :tree-data="treeData"
        :selected-keys="selectedKeys"
        :default-expand-all="true"
        @select="onSelect"
      >
        <template #title="{ title, key }">
          <span :class="{ 'eval-dataset-tree__selected': key === selectedId }">
            {{ title }}
          </span>
        </template>
      </a-tree>
      <a-empty v-else description="暂无测试集" />
    </div>
    <div class="eval-dataset-tree__footer">
      <span class="eval-dataset-tree__stats">
        {{ datasets.length }} 个测试集 · {{ totalQuestions }} 题
      </span>
      <div class="eval-dataset-tree__actions">
        <a-button size="small" @click="$emit('import')">
          <template #icon><UploadOutlined /></template>
          导入
        </a-button>
        <a-button size="small" @click="$emit('create')">
          <template #icon><PlusOutlined /></template>
          新建
        </a-button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { UploadOutlined, PlusOutlined } from '@ant-design/icons-vue'
import type { EvalDataset } from '../types/eval'

const props = defineProps<{
  datasets: EvalDataset[]
  selectedId: string
}>()

const emit = defineEmits<{
  select: [datasetId: string]
  import: []
  create: []
}>()

const categoryLabels: Record<string, string> = {
  knowledge: '知识库评测',
  sop: 'SOP 评测',
  full_chain: '全链路评测',
}

const treeData = computed(() => {
  const groups: Record<string, EvalDataset[]> = {}
  for (const ds of props.datasets) {
    const cat = ds.category || 'knowledge'
    if (!groups[cat]) groups[cat] = []
    groups[cat].push(ds)
  }
  return Object.entries(groups).map(([cat, items]) => ({
    key: `group-${cat}`,
    title: categoryLabels[cat] || cat,
    selectable: false,
    children: items.map(item => ({
      key: item.dataset_id,
      title: `${item.title} (${item.question_count})`,
      isLeaf: true,
    })),
  }))
})

const selectedKeys = computed(() => props.selectedId ? [props.selectedId] : [])

const totalQuestions = computed(() => props.datasets.reduce((sum, ds) => sum + ds.question_count, 0))

const onSelect = (keys: (string | number)[]) => {
  if (keys.length > 0) {
    const key = String(keys[0])
    if (!key.startsWith('group-')) {
      emit('select', key)
    }
  }
}
</script>

<style lang="less" scoped>
.eval-dataset-tree {
  display: flex;
  flex-direction: column;
  height: 100%;

  &__header {
    padding: 12px 16px;
    border-bottom: 1px solid var(--dp-border-color, rgba(255, 255, 255, 0.06));
  }

  &__title {
    font-size: 15px;
    font-weight: 600;
    color: var(--dp-text-primary, rgba(255, 255, 255, 0.85));
  }

  &__body {
    flex: 1;
    overflow-y: auto;
    padding: 8px;
  }

  &__selected {
    color: @evals-primary;
    font-weight: 500;
  }

  &__footer {
    padding: 8px 12px;
    border-top: 1px solid var(--dp-border-color, rgba(255, 255, 255, 0.06));
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  &__stats {
    font-size: 12px;
    color: var(--dp-text-secondary, rgba(255, 255, 255, 0.45));
  }

  &__actions {
    display: flex;
    gap: 4px;
  }
}
</style>
