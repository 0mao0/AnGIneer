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
        <a-select-option value="completed">已完成</a-select-option>
        <a-select-option value="running">评测中</a-select-option>
        <a-select-option value="error">出错</a-select-option>
        <a-select-option value="pending">待评测</a-select-option>
      </a-select>
      <a-select
        v-model:value="filterQuality"
        placeholder="按质量筛选"
        allow-clear
        style="width: 120px"
        size="small"
      >
        <a-select-option value="correct">正确</a-select-option>
        <a-select-option value="wrong">错误</a-select-option>
      </a-select>
      <a-popover
        v-model:open="docTreeVisible"
        trigger="click"
        placement="bottomLeft"
        overlay-class-name="eval-doc-filter-popover"
      >
        <template #content>
          <div class="eval-doc-filter-panel">
            <div class="eval-doc-filter-panel__actions">
              <a-button type="link" size="small" @click="selectAllDocs">全选</a-button>
              <a-button type="link" size="small" @click="clearAllDocs">清空</a-button>
            </div>
            <a-tree
              v-model:checkedKeys="checkedDocKeys"
              :tree-data="docTreeData"
              :field-names="{ title: 'title', key: 'key', children: 'children' }"
              checkable
              :selectable="false"
              :default-expand-all="true"
              height="280"
              class="eval-doc-filter-tree"
            />
          </div>
        </template>
        <a-button size="small" class="eval-doc-filter-btn">
          测试规范：{{ docFilterLabel }}
        </a-button>
      </a-popover>
    </div>
    <div class="eval-question-list__body">
      <a-spin :spinning="loading">
        <EvalQuestionCard
          v-for="q in filteredQuestions"
          :key="q.question_id"
          :question="q"
          :detail="runDetails.get(q.question_id) || null"
          :expanded="expandedId === q.question_id"
          :evaluating="evaluatingQuestionIds.has(q.question_id)"
          @toggle="onToggle"
          @evaluate="(qid) => $emit('evaluate', qid)"
          @updated="() => $emit('questionUpdated')"
        />
        <a-empty v-if="!filteredQuestions.length" description="暂无题目" />
      </a-spin>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import EvalQuestionCard from './EvalQuestionCard.vue'
import type { EvalQuestion, EvalRunDetail, EvalIntentLevel, EvalQuestionStatus, EvalQuality } from '../types/eval'

/** 知识库树节点 */
export interface DocTreeNode {
  key: string
  title: string
  type: 'folder' | 'document'
  parentId: string | null
  children?: DocTreeNode[]
}

const props = defineProps<{
  questions: EvalQuestion[]
  runDetails: Map<string, EvalRunDetail>
  loading: boolean
  evaluatingQuestionIds: Set<string>
  docTreeData?: DocTreeNode[]
  docFlatList?: DocTreeNode[]
}>()

const emit = defineEmits<{
  toggle: [questionId: string]
  evaluate: [questionId: string]
  'update:selectedDocIds': [docIds: string[]]
  questionUpdated: []
}>()

const filterLevel = ref<EvalIntentLevel | undefined>(undefined)
const filterStatus = ref<EvalQuestionStatus | undefined>(undefined)
const filterQuality = ref<EvalQuality | undefined>(undefined)
const expandedId = ref<string | null>(null)
const docTreeVisible = ref(false)
const checkedDocKeys = ref<string[]>([])

/** 收集树中所有文档节点的 key */
const collectAllDocKeys = (nodes: DocTreeNode[]): string[] => {
  const keys: string[] = []
  const walk = (list: DocTreeNode[]) => {
    for (const n of list) {
      if (n.type === 'document') keys.push(n.key)
      if (n.children) walk(n.children)
    }
  }
  walk(nodes)
  return keys
}

/** 当前选中的文档 ID 列表（仅叶子文档节点） */
const selectedDocIds = computed(() => {
  const flat = props.docFlatList || []
  return checkedDocKeys.value.filter(k => flat.some(n => n.key === k && n.type === 'document'))
})

watch(selectedDocIds, (ids) => {
  emit('update:selectedDocIds', ids)
}, { immediate: true })

/** 筛选标签 */
const docFilterLabel = computed(() => {
  const allDocCount = (props.docFlatList || []).filter(n => n.type === 'document').length
  const selectedCount = selectedDocIds.value.length
  if (selectedCount === 0) return '无'
  if (selectedCount >= allDocCount) return '全部'
  return `${selectedCount} 项`
})

/** 默认全选 */
watch(
  () => props.docFlatList,
  (flat) => {
    if (flat && flat.length && checkedDocKeys.value.length === 0) {
      checkedDocKeys.value = collectAllDocKeys(props.docTreeData || [])
    }
  },
  { immediate: true }
)

const selectAllDocs = () => {
  checkedDocKeys.value = collectAllDocKeys(props.docTreeData || [])
}

const clearAllDocs = () => {
  checkedDocKeys.value = []
}

const filteredQuestions = computed(() => {
  const allDocCount = (props.docFlatList || []).filter(n => n.type === 'document').length
  const shouldFilterByDoc = selectedDocIds.value.length > 0 && selectedDocIds.value.length < allDocCount
  return props.questions.filter(q => {
    if (filterLevel.value && q.intent_level !== filterLevel.value) return false
    if (filterStatus.value) {
      const detail = props.runDetails.get(q.question_id)
      const status = detail?.status || 'pending'
      if (status !== filterStatus.value) return false
    }
    if (filterQuality.value) {
      const detail = props.runDetails.get(q.question_id)
      const quality = (detail?.quality as string | null) || null
      if (quality !== filterQuality.value) return false
    }
    if (shouldFilterByDoc && q.doc_ids?.length > 0) {
      const hasOverlap = q.doc_ids.some(id => selectedDocIds.value.includes(id))
      if (!hasOverlap) return false
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
    flex-wrap: wrap;
    align-items: center;
  }

  &__body {
    flex: 1;
    overflow-y: auto;
    padding: 12px;
  }
}

.eval-doc-filter-btn {
  font-size: 12px;
}
</style>

<style lang="less">
.eval-doc-filter-popover {
  .ant-popover-inner {
    padding: 0;
  }
}

.eval-doc-filter-panel {
  width: 280px;

  &__actions {
    display: flex;
    justify-content: flex-end;
    gap: 4px;
    padding: 4px 8px;
    border-bottom: 1px solid var(--border-color);
  }
}

.eval-doc-filter-tree {
  font-size: 12px;

  .ant-tree-node-content-wrapper {
    padding: 0 4px;
  }
}
</style>
