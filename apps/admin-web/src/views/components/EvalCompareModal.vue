<template>
  <!-- 评测结果对比弹窗 - 列表模式展示两次评测的逐题对比 -->
  <a-modal
    :open="open"
    title="评测结果对比"
    width="800px"
    :footer="null"
    @update:open="$emit('update:open', $event)"
  >
    <div class="eval-compare-modal">
      <div class="eval-compare-modal__selectors">
        <a-select
          v-model:value="runIdA"
          placeholder="选择评测 1"
          style="flex: 1"
          size="small"
        >
          <a-select-option v-for="r in runs" :key="r.run_id" :value="r.run_id">
            {{ r.run_name || r.run_id.slice(0, 12) }}
          </a-select-option>
        </a-select>
        <span class="eval-compare-modal__vs">vs</span>
        <a-select
          v-model:value="runIdB"
          placeholder="选择评测 2"
          style="flex: 1"
          size="small"
        >
          <a-select-option v-for="r in runs" :key="r.run_id" :value="r.run_id">
            {{ r.run_name || r.run_id.slice(0, 12) }}
          </a-select-option>
        </a-select>
        <a-button
          size="small"
          type="primary"
          :disabled="!runIdA || !runIdB || runIdA === runIdB"
          :loading="comparing"
          @click="doCompare"
        >
          对比
        </a-button>
      </div>

      <div v-if="compareResult" class="eval-compare-modal__table-wrap">
        <div v-if="compareResult.run_a.details_count != null || compareResult.run_b.details_count != null" class="eval-compare-modal__stats">
          <a-alert
            :type="(compareResult.run_a.details_count ?? 0) < (compareResult.run_a.total_questions ?? 0) || (compareResult.run_b.details_count ?? 0) < (compareResult.run_b.total_questions ?? 0) ? 'warning' : 'info'"
            :show-icon="true"
            :message="`评测A: ${compareResult.run_a.details_count ?? '?'} / ${compareResult.run_a.total_questions ?? '?'} 题 | 评测B: ${compareResult.run_b.details_count ?? '?'} / ${compareResult.run_b.total_questions ?? '?'} 题 | 对比: ${tableData.length} 条`"
          />
        </div>
        <a-table
          :columns="columns"
          :data-source="tableData"
          :pagination="false"
          size="small"
          row-key="questionId"
          :scroll="{ y: 400 }"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.dataIndex === 'index'">
              {{ record.index }}
            </template>
            <template v-else-if="column.dataIndex === 'statusA'">
              <a-tag :color="statusColor(record.statusA)">
                {{ statusLabel(record.statusA) }}
              </a-tag>
            </template>
            <template v-else-if="column.dataIndex === 'statusB'">
              <a-tag :color="statusColor(record.statusB)">
                {{ statusLabel(record.statusB) }}
              </a-tag>
            </template>
            <template v-else-if="column.dataIndex === 'consistent'">
              <a-tag :color="record.consistent ? 'success' : 'error'">
                {{ record.consistent ? '是' : '否' }}
              </a-tag>
            </template>
            <template v-else-if="column.dataIndex === 'diff'">
              <div v-if="record.analysisLoading" class="eval-compare-modal__diff-loading">
                <a-spin size="small" /> 分析中...
              </div>
              <div v-else-if="record.analysis" class="eval-compare-modal__diff-text">
                {{ record.analysis }}
              </div>
              <a-button
                v-else
                type="link"
                size="small"
                :disabled="!runIdA || !runIdB"
                @click="analyzeDiff(record)"
              >
                分析差异
              </a-button>
            </template>
          </template>
        </a-table>
      </div>

      <a-empty v-else-if="!comparing" description="请选择两次评测进行对比" />
    </div>
  </a-modal>
</template>

<script setup lang="ts">
/**
 * 评测结果对比弹窗
 * 以列表模式展示两次评测的逐题对比，支持 LLM 差异分析
 */
import { ref, computed, watch } from 'vue'
import { evalsApi } from '../../api/evals'
import type { EvalRun, EvalCompareResult } from '@angineer/evals-ui'

interface CompareRow {
  index: number
  questionId: string
  statusA: string
  statusB: string
  consistent: boolean
  analysis: string
  analysisLoading: boolean
}

const props = defineProps<{
  open: boolean
  runs: EvalRun[]
  datasetId: string
}>()

defineEmits<{
  'update:open': [value: boolean]
}>()

const runIdA = ref<string | undefined>(undefined)
const runIdB = ref<string | undefined>(undefined)
const comparing = ref(false)
const compareResult = ref<EvalCompareResult | null>(null)
const analysisMap = ref<Map<string, { analysis: string; loading: boolean }>>(new Map())

/** 运行名称映射 */
const runNameMap = computed(() => {
  const map = new Map<string, string>()
  for (const r of props.runs) {
    map.set(r.run_id, r.run_name || r.run_id.slice(0, 12))
  }
  return map
})

/** 表格列定义 */
const columns = computed(() => [
  { title: '序号', dataIndex: 'index', width: 60, align: 'center' as const },
  { title: '题号', dataIndex: 'questionId', width: 120 },
  {
    title: runNameMap.value.get(runIdA.value || '') || '评测1',
    dataIndex: 'statusA',
    width: 100,
    align: 'center' as const,
  },
  {
    title: runNameMap.value.get(runIdB.value || '') || '评测2',
    dataIndex: 'statusB',
    width: 100,
    align: 'center' as const,
  },
  { 
    title: '一致', 
    dataIndex: 'consistent', 
    width: 70, 
    align: 'center' as const,
  },
  { title: '差异', dataIndex: 'diff', width: 300 },
])

/** 表格数据 */
const tableData = computed<CompareRow[]>(() => {
  if (!compareResult.value) return []
  const changes = compareResult.value.question_changes
  return changes.map((c, i) => {
    const key = c.question_id
    const cached = analysisMap.value.get(key)
    return {
      index: i + 1,
      questionId: c.question_id,
      statusA: c.status_a,
      statusB: c.status_b,
      consistent: c.consistent,
      analysis: cached?.analysis || '',
      analysisLoading: cached?.loading || false,
    }
  })
})

/** 状态标签颜色映射 */
const statusColor = (status: string): string => {
  if (status === 'correct') return 'success'
  if (status === 'wrong') return 'error'
  if (status === 'missing') return 'default'
  return 'processing'
}

/** 状态标签文本映射 */
const statusLabel = (status: string): string => {
  if (status === 'correct') return '正确'
  if (status === 'wrong') return '错误'
  if (status === 'missing') return '缺失'
  if (status === 'pending') return '待评测'
  if (status === 'running') return '评测中'
  return status
}

/** 执行对比 */
const doCompare = async () => {
  if (!runIdA.value || !runIdB.value) return
  comparing.value = true
  analysisMap.value = new Map()
  try {
    const data = await evalsApi.compare(runIdA.value, runIdB.value)
    compareResult.value = data as unknown as EvalCompareResult
  } catch (e: any) {
    compareResult.value = null
  } finally {
    comparing.value = false
  }
}

/** 使用 LLM 分析单题差异 */
const analyzeDiff = async (record: CompareRow) => {
  if (!runIdA.value || !runIdB.value) return
  const key = record.questionId
  const next = new Map(analysisMap.value)
  next.set(key, { analysis: '', loading: true })
  analysisMap.value = next

  try {
    const data = await evalsApi.analyzeCompare(runIdA.value, runIdB.value, key)
    const analysis = (data as any)?.analysis || '分析完成，无详细结果'
    const next2 = new Map(analysisMap.value)
    next2.set(key, { analysis, loading: false })
    analysisMap.value = next2
  } catch {
    const next3 = new Map(analysisMap.value)
    next3.set(key, { analysis: '分析失败', loading: false })
    analysisMap.value = next3
  }
}

/** 弹窗关闭时重置状态 */
watch(() => props.open, (val) => {
  if (!val) {
    compareResult.value = null
    analysisMap.value = new Map()
  }
})
</script>

<style lang="less" scoped>
.eval-compare-modal {
  &__selectors {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 16px;
  }

  &__vs {
    font-weight: 600;
    color: var(--text-secondary, rgba(0, 0, 0, 0.45));
    flex-shrink: 0;
  }

  &__table-wrap {
    margin-top: 8px;
  }

  &__stats {
    margin-bottom: 12px;
  }

  &__diff-loading {
    display: flex;
    align-items: center;
    gap: 4px;
    font-size: 12px;
    color: var(--text-secondary, rgba(0, 0, 0, 0.45));
  }

  &__diff-text {
    font-size: 12px;
    line-height: 1.6;
    color: var(--text-primary, rgba(0, 0, 0, 0.85));
    white-space: pre-wrap;
  }
}
</style>
