<template>
  <IndexTreeModalShell
    :open="open"
    :confirm-loading="loading"
    :ok-button-props="{ disabled: submitDisabled }"
    ok-text="合并选中节点"
    cancel-text="取消"
    :width="760"
    @update:open="emit('update:open', $event)"
    @cancel="emit('cancel')"
    @ok="submitMerge"
  >
    <template #title>
      <div class="merge-modal-title">合并节点</div>
    </template>
    <div class="merge-overview-card">
      <div class="merge-overview-title-row">
        <div>
          <div class="merge-overview-title">批量合并预览</div>
          <div class="merge-overview-hint">其余选中 block 会按当前文档顺序并入目标 block。</div>
        </div>
        <div class="merge-overview-stats">
          <span class="merge-overview-stat">已选 {{ selectedBlockIds.length }} 个</span>
          <span class="merge-overview-stat">保留 1 个</span>
        </div>
      </div>
    </div>
    <a-form layout="vertical" class="merge-form">
      <a-form-item label="已选 block" class="merge-form-item-card">
        <a-select mode="multiple" :value="selectedNodeValues" :options="selectedNodeOptions" disabled />
      </a-form-item>
      <a-form-item label="合并目标" class="merge-form-item-card">
        <a-select
          v-model:value="targetBlockId"
          :options="selectedNodeOptions"
          show-search
          option-filter-prop="label"
          placeholder="选择保留的目标 block"
        />
      </a-form-item>
      <div class="merge-warning-card">
        <div class="merge-warning-title">操作说明</div>
        <div class="merge-warning-text">提交后仅保留目标 block，其余内容会顺序合并并从结构树中移除。</div>
      </div>
    </a-form>
  </IndexTreeModalShell>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import type { DocBlockNode } from '../../../types/knowledge'
import IndexTreeModalShell from './IndexTreeModalShell.vue'
import { buildOrderedNodeOptions } from './indexTreeModalUtils'

interface Props {
  open: boolean
  selectedBlockIds: string[]
  nodeMap: Map<string, DocBlockNode>
  loading?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  loading: false
})

const emit = defineEmits<{
  'update:open': [value: boolean]
  cancel: []
  submit: [targetBlockId: string]
}>()

const targetBlockId = ref<string>()

const selectedNodeOptions = computed(() => {
  const selectedIdSet = new Set(props.selectedBlockIds)
  return buildOrderedNodeOptions(props.nodeMap).filter(option => selectedIdSet.has(option.value))
})
const selectedNodeValues = computed(() => selectedNodeOptions.value.map(option => option.value))
const submitDisabled = computed(() => props.selectedBlockIds.length < 2 || !targetBlockId.value)

/* 打开弹窗时自动预选第一个可保留的目标节点。 */
const resetTargetBlockId = () => {
  targetBlockId.value = props.selectedBlockIds[0]
}

watch(() => [props.open, props.selectedBlockIds.join('|')], () => {
  if (props.open) {
    resetTargetBlockId()
  }
}, { immediate: true })

/* 提交合并目标给外层批处理逻辑。 */
const submitMerge = () => {
  if (!targetBlockId.value) {
    message.warning('请选择保留的目标 block')
    return
  }
  emit('submit', targetBlockId.value)
}
</script>

<style lang="less">
.merge-modal-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--dp-title-strong);
}

.merge-overview-card {
  margin-bottom: 10px;
  padding: 10px 12px;
  border-radius: 12px;
  border: 1px solid var(--dp-pane-border);
  background: var(--dp-surface-bg);
}

.merge-overview-title-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.merge-overview-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--dp-title-strong);
}

.merge-overview-hint {
  margin-top: 2px;
  color: var(--dp-sub-text);
  font-size: 12px;
  line-height: 1.5;
}

.merge-overview-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
}

.merge-overview-stat {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  padding: 0 8px;
  border-radius: 999px;
  border: 1px solid var(--dp-badge-border);
  background: var(--dp-badge-bg);
  color: var(--dp-badge-text);
  font-size: 12px;
}

.merge-form .ant-form-item {
  margin-bottom: 10px;
}

.merge-form-item-card .ant-form-item-label {
  padding-bottom: 2px;
}

.merge-form-item-card .ant-select-selector {
  border-radius: 8px;
}

.merge-warning-card {
  padding: 8px 10px;
  border-radius: 10px;
  border: 1px solid var(--dp-warning-border);
  background: var(--dp-warning-bg);
}

.merge-warning-title {
  margin-bottom: 4px;
  font-size: 12px;
  font-weight: 600;
  color: var(--dp-warning-title);
}

.merge-warning-text {
  font-size: 12px;
  line-height: 1.6;
  color: var(--dp-warning-text);
}

@media (max-width: 640px) {
  .merge-overview-title-row {
    flex-direction: column;
  }
}
</style>
