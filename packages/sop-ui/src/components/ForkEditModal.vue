<template>
  <a-modal
    :open="visible"
    title="编辑分支条件"
    ok-text="确定"
    cancel-text="取消"
    width="480px"
    @ok="handleOk"
    @cancel="handleCancel"
  >
    <div class="fork-modal-body">
      <!-- condition_var -->
      <div class="fork-modal-field">
        <span class="field-label">如果</span>
        <span class="var-wrapper">$</span>
        <a-input
          v-model:value="localConditionVar"
          size="small"
          placeholder="变量名"
          style="flex: 1;"
        />
        <span class="field-label">满足：</span>
      </div>

      <!-- branches -->
      <div class="fork-modal-branches">
        <div v-for="(branch, idx) in localBranches" :key="idx" class="branch-row">
          <span class="branch-dot" />
          <a-input
            v-model:value="branch.match"
            size="small"
            placeholder="匹配条件"
            style="flex: 1;"
          />
          <span class="arrow">→</span>
          <a-input
            v-model:value="branch.goto"
            size="small"
            placeholder="目标步骤 ID"
            style="width: 120px;"
          />
          <a-button type="text" size="small" danger @click="localBranches.splice(idx, 1)">
            <template #icon><DeleteOutlined /></template>
          </a-button>
        </div>
        <a-button type="dashed" size="small" block @click="localBranches.push({ match: '', goto: '' })">
          <PlusOutlined /> 添加分支
        </a-button>
      </div>

      <!-- default_goto -->
      <div class="fork-modal-field default-field">
        <span class="field-label">否则 →</span>
        <a-input
          v-model:value="localDefaultGoto"
          size="small"
          placeholder="默认目标步骤 ID"
          style="flex: 1;"
        />
      </div>
    </div>
  </a-modal>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons-vue'

interface BranchItem {
  match: string
  goto: string
}

const props = defineProps<{
  visible: boolean
  conditionVar?: string
  branches?: BranchItem[]
  defaultGoto?: string
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
  confirm: [payload: { conditionVar: string; branches: BranchItem[]; defaultGoto: string }]
}>()

const localConditionVar = ref('')
const localBranches = ref<BranchItem[]>([])
const localDefaultGoto = ref('')

watch(() => props.visible, (val) => {
  if (val) {
    localConditionVar.value = props.conditionVar || ''
    localBranches.value = (props.branches || []).map((b) => ({ ...b }))
    localDefaultGoto.value = props.defaultGoto || ''
  }
})

const handleOk = () => {
  emit('confirm', {
    conditionVar: localConditionVar.value.trim(),
    branches: localBranches.value.filter((b) => b.match.trim()),
    defaultGoto: localDefaultGoto.value.trim(),
  })
  emit('update:visible', false)
}

const handleCancel = () => {
  emit('update:visible', false)
}
</script>

<style lang="less" scoped>
.fork-modal-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.fork-modal-field {
  display: flex;
  align-items: center;
  gap: 6px;
}

.field-label {
  font-size: 13px;
  color: var(--text-secondary);
  white-space: nowrap;
}

.var-wrapper {
  font-size: 12px;
  color: var(--text-secondary);
}

.fork-modal-branches {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding-left: 8px;
}

.branch-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.branch-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #faad14;
  flex-shrink: 0;
}

.arrow {
  font-size: 12px;
  color: var(--text-secondary);
}

.default-field {
  border-top: 1px dashed var(--border-color);
  padding-top: 10px;
}
</style>
