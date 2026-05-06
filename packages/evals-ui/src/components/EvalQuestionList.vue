<template>
  <div class="eval-question-list">
    <div class="eval-question-list__toolbar">
      <a-select
        v-model:value="filterLevel"
        placeholder="按层级筛选"
        allow-clear
        style="width: 120px"
        size="small"
      >
        <a-select-option value="L1">L1</a-select-option>
        <a-select-option value="L2">L2</a-select-option>
        <a-select-option value="L3">L3</a-select-option>
        <a-select-option value="L4">L4</a-select-option>
      </a-select>
      <a-select
        v-model:value="filterStatus"
        placeholder="按状态筛选"
        allow-clear
        style="width: 120px"
        size="small"
      >
        <a-select-option value="passed">通过</a-select-option>
        <a-select-option value="failed">未通过</a-select-option>
        <a-select-option value="skipped">未评测</a-select-option>
        <a-select-option value="pending">待运行</a-select-option>
        <a-select-option value="error">错误</a-select-option>
      </a-select>
    </div>
    <div class="eval-question-list__body">
      <a-spin :spinning="loading">
        <EvalQuestionCard
          v-for="q in filteredQuestions"
          :key="q.question_id"
          :question="q"
          :detail="runDetails.get(q.question_id) || null"
          :expanded="expandedId === q.question_id"
          @toggle="onToggle"
        />
        <a-empty v-if="!filteredQuestions.length" description="暂无题目" />
      </a-spin>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import EvalQuestionCard from './EvalQuestionCard.vue'
import type { EvalQuestion, EvalRunDetail, EvalIntentLevel, EvalQuestionStatus } from '../types/eval'

const props = defineProps<{
  questions: EvalQuestion[]
  runDetails: Map<string, EvalRunDetail>
  loading: boolean
}>()

defineEmits<{
  toggle: [questionId: string]
}>()

const filterLevel = ref<EvalIntentLevel | undefined>(undefined)
const filterStatus = ref<EvalQuestionStatus | undefined>(undefined)
const expandedId = ref<string | null>(null)

const filteredQuestions = computed(() => {
  return props.questions.filter(q => {
    if (filterLevel.value && q.intent_level !== filterLevel.value) return false
    if (filterStatus.value) {
      const detail = props.runDetails.get(q.question_id)
      const status = detail?.status || 'pending'
      if (status !== filterStatus.value) return false
    }
    return true
  })
})

const onToggle = (questionId: string) => {
  expandedId.value = expandedId.value === questionId ? null : questionId
}
</script>

<style lang="less" scoped>
.eval-question-list {
  display: flex;
  flex-direction: column;
  height: 100%;

  &__toolbar {
    display: flex;
    gap: 8px;
    padding: 8px 12px;
    border-bottom: 1px solid var(--border-color);
  }

  &__body {
    flex: 1;
    overflow-y: auto;
    padding: 12px;
  }
}
</style>
