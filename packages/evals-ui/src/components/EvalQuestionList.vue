<template>
  <div class="eval-question-list">
    <div class="eval-question-list__toolbar">
      <a-select
        :value="filterLevel"
        placeholder="按层级筛选"
        allow-clear
        style="width: 120px"
        size="small"
        @change="(v: any) => onFilterChange('level', v)"
      >
        <a-select-option value="L1">L1</a-select-option>
        <a-select-option value="L2">L2</a-select-option>
        <a-select-option value="L3">L3</a-select-option>
        <a-select-option value="L4">L4</a-select-option>
      </a-select>
      <a-select
        :value="filterStatus"
        :disabled="!hasRun"
        :title="hasRun ? '' : '该题集还没有运行记录，状态筛选无从判定'"
        placeholder="按状态筛选"
        allow-clear
        style="width: 120px"
        size="small"
        @change="(v: any) => onFilterChange('status', v)"
      >
        <a-select-option value="completed">已完成</a-select-option>
        <a-select-option value="running">评测中</a-select-option>
        <a-select-option value="error">出错</a-select-option>
        <a-select-option value="pending">待评测</a-select-option>
      </a-select>
      <a-select
        :value="filterQuality"
        :disabled="!hasRun"
        :title="hasRun ? '' : '该题集还没有运行记录，质量筛选无从判定'"
        placeholder="按质量筛选"
        allow-clear
        style="width: 120px"
        size="small"
        @change="(v: any) => onFilterChange('quality', v)"
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
      <a-button size="small" class="eval-question-list__card-btn" @click="openCard">
        题集卡
      </a-button>
    </div>
    <div class="eval-question-list__body">
      <a-spin :spinning="loading">
        <EvalQuestionCard
          v-for="(q, idx) in questions"
          :key="q.question_id"
          :question="q"
          :index="pageStartIndex + idx + 1"
          :detail="runDetails.get(q.question_id) || null"
          :expanded="expandedId === q.question_id"
          :evaluating="evaluatingQuestionIds.has(q.question_id)"
          @toggle="onToggle"
          @evaluate="(qid) => $emit('evaluate', qid)"
          @updated="() => $emit('questionUpdated')"
        />
        <a-empty v-if="!questions.length" description="暂无题目" />
      </a-spin>
    </div>
    <div v-if="total > pageSize" class="eval-question-list__pagination">
      <a-pagination
        :current="page"
        :page-size="pageSize"
        :total="total"
        show-size-changer
        :page-size-options="[10, 20, 50]"
        @change="onPageChange"
        @show-size-change="onPageSizeChange"
      />
    </div>
    <EvalDatasetCardModal
      v-model:open="cardVisible"
      :dataset="dataset"
      :library-name="libraryName"
      :questions="cardQuestions"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import EvalQuestionCard from './EvalQuestionCard.vue'
import EvalDatasetCardModal from './EvalDatasetCardModal.vue'
import type { EvalQuestion, EvalRunDetail, EvalIntentLevel, EvalQuestionStatus, EvalQuality, EvalDataset } from '../types/eval'

/** 知识库树节点 */
export interface DocTreeNode {
  key: string
  title: string
  type: 'folder' | 'document'
  parentId: string | null
  children?: DocTreeNode[]
}

const props = defineProps<{
  /** 当前页题目（服务端已按筛选+分页返回；前端不再 filter/slice 全量） */
  questions: EvalQuestion[]
  /** 服务端筛选后的总题数，供分页器 */
  total: number
  page: number
  pageSize: number
  filterLevel?: EvalIntentLevel
  filterStatus?: EvalQuestionStatus
  filterQuality?: EvalQuality
  /** 题集有无运行记录：没有 run 时状态/质量筛选没有依据，置灰 */
  hasRun: boolean
  runDetails: Map<string, EvalRunDetail>
  loading: boolean
  evaluatingQuestionIds: Set<string>
  docTreeData?: DocTreeNode[]
  docFlatList?: DocTreeNode[]
  onExpandDetail?: (questionId: string) => void
  dataset?: EvalDataset | null
  libraryName?: string
  /** 题集卡要全量题目算层级分布；分页后当前页不够，点开时向宿主取 */
  loadAllQuestions?: (datasetId: string) => Promise<EvalQuestion[]>
}>()

const emit = defineEmits<{
  toggle: [questionId: string]
  evaluate: [questionId: string]
  'update:selectedDocIds': [docIds: string[]]
  questionUpdated: []
  /** 筛选/翻页变化：宿主按新条件去服务端取数（跨全量筛选在 SQL 里生效） */
  queryChange: [query: {
    page: number
    pageSize: number
    level?: EvalIntentLevel
    status?: EvalQuestionStatus
    quality?: EvalQuality
  }]
}>()

const expandedId = ref<string | null>(null)
const docTreeVisible = ref(false)
const cardVisible = ref(false)
/** 题集卡用的全量题目（点开时才拉） */
const cardQuestions = ref<EvalQuestion[]>([])
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
    if (flat && flat.length) {
      checkedDocKeys.value = collectAllDocKeys(props.docTreeData || [])
    } else {
      checkedDocKeys.value = []
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

/** 当前页的全局题号起点：分页后题号必须接着全量序号（第 2 页第一条是 21.，不是 1.） */
const pageStartIndex = computed(() => (props.page - 1) * props.pageSize)

/** 筛选/翻页都交给宿主去服务端取数（跨全量筛选在 SQL 里生效，前端不再 filter/slice） */
const emitQuery = (patch: Partial<{
  page: number
  pageSize: number
  level?: EvalIntentLevel
  status?: EvalQuestionStatus
  quality?: EvalQuality
}>) => {
  emit('queryChange', {
    page: props.page,
    pageSize: props.pageSize,
    level: props.filterLevel,
    status: props.filterStatus,
    quality: props.filterQuality,
    ...patch,
  })
}

const onFilterChange = (key: 'level' | 'status' | 'quality', value: unknown) => {
  const next = (value ?? undefined) as EvalIntentLevel | EvalQuestionStatus | EvalQuality | undefined
  emitQuery({ [key]: next, page: 1 } as any)
}

const onPageChange = (page: number, size: number) => {
  emitQuery({ page, pageSize: size })
}

const onPageSizeChange = (_current: number, size: number) => {
  emitQuery({ page: 1, pageSize: size })
}

/** 题集卡的层级分布要全量题目：当前页只有一页的量，点开时向宿主取全量 */
const openCard = async () => {
  const datasetId = props.dataset?.dataset_id
  if (datasetId && props.loadAllQuestions) {
    try {
      cardQuestions.value = await props.loadAllQuestions(datasetId)
    } catch {
      cardQuestions.value = props.questions
    }
  } else {
    cardQuestions.value = props.questions
  }
  cardVisible.value = true
}

const onToggle = (questionId: string) => {
  expandedId.value = expandedId.value === questionId ? null : questionId
  if (expandedId.value === questionId) {
    props.onExpandDetail?.(questionId)
  }
}
</script>

<style lang="less" scoped>
.eval-question-list {
  display: flex;
  flex-direction: column;
  min-height: 100%;

  &__toolbar {
    display: flex;
    gap: 8px;
    padding: 8px 12px;
    border-bottom: 1px solid var(--border-color);
    flex-wrap: wrap;
    align-items: center;
  }

  &__card-btn {
    margin-left: auto;
  }

  &__body {
    flex: 1;
    padding: 12px;
  }

  &__pagination {
    display: flex;
    justify-content: flex-end;
    padding: 10px 12px;
    border-top: 1px solid var(--border-color);
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
