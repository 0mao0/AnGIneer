<template>
  <div class="research-draft-table">
    <a-tabs v-model:activeKey="activeTab">
      <a-tab-pane key="sop" tab="SOP 草稿">
        <a-spin :spinning="loading">
          <a-table
            :data-source="drafts"
            :columns="sopColumns"
            :pagination="{ pageSize: 10, showSizeChanger: false }"
            :row-key="(r: any) => r.draft_id"
            :row-class-name="rowClassName"
            size="small"
            @row-click="(r: any) => emit('select-draft', r.draft_id, 'sop')"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'score_total'">
                <a-tag :color="scoreColor(record.score_total)">{{ record.score_total?.toFixed(2) }}</a-tag>
              </template>
              <template v-if="column.key === 'score_rule'">
                <a-tag :color="scoreColor(record.score_rule)">{{ record.score_rule?.toFixed(2) }}</a-tag>
              </template>
              <template v-if="column.key === 'score_model'">
                <a-tag :color="scoreColor(record.score_model)">{{ record.score_model?.toFixed(2) }}</a-tag>
              </template>
              <template v-if="column.key === 'review_status'">
                <a-tag :color="reviewColor(record.review_status)">{{ reviewText(record.review_status) }}</a-tag>
              </template>
              <template v-if="column.key === 'actions'">
                <a-space>
                  <a-button
                    v-if="record.review_status === 'pending'"
                    type="primary"
                    size="small"
                    @click.stop="emit('approve-sop', record.draft_id)"
                  >
                    批准
                  </a-button>
                  <a-button
                    v-if="record.review_status === 'pending'"
                    size="small"
                    @click.stop="emit('reject-draft', record.draft_id, 'sop')"
                  >
                    拒绝
                  </a-button>
                </a-space>
              </template>
            </template>
          </a-table>
        </a-spin>
      </a-tab-pane>

      <a-tab-pane key="eval" tab="评估草稿">
        <a-spin :spinning="loading">
          <a-table
            :data-source="evalDrafts"
            :columns="evalColumns"
            :pagination="{ pageSize: 10, showSizeChanger: false }"
            :row-key="(r: any) => r.draft_id"
            :row-class-name="evalRowClassName"
            size="small"
            @row-click="(r: any) => emit('select-draft', r.draft_id, 'eval')"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'review_status'">
                <a-tag :color="reviewColor(record.review_status)">{{ reviewText(record.review_status) }}</a-tag>
              </template>
              <template v-if="column.key === 'actions'">
                <a-space>
                  <a-button
                    v-if="record.review_status === 'pending'"
                    type="primary"
                    size="small"
                    @click.stop="emit('approve-eval', record.draft_id)"
                  >
                    批准
                  </a-button>
                  <a-button
                    v-if="record.review_status === 'pending'"
                    size="small"
                    @click.stop="emit('reject-draft', record.draft_id, 'eval')"
                  >
                    拒绝
                  </a-button>
                </a-space>
              </template>
            </template>
          </a-table>
        </a-spin>
      </a-tab-pane>
    </a-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import type { SopResearchDraft, EvalResearchDraft } from '../../types/sopResearch'

interface Props {
  drafts: SopResearchDraft[]
  evalDrafts: EvalResearchDraft[]
  selectedDraftId: string
  loading: boolean
}

const props = defineProps<Props>()

const emit = defineEmits<{
  'select-draft': [draftId: string, type: 'sop' | 'eval']
  'approve-sop': [draftId: string]
  'approve-eval': [draftId: string]
  'reject-draft': [draftId: string, type: 'sop' | 'eval']
}>()

const activeTab = ref('sop')

const sopColumns = [
  { title: '标题', dataIndex: 'title', key: 'title', ellipsis: true },
  { title: '审核状态', dataIndex: 'review_status', key: 'review_status', width: 100 },
  { title: '总分', dataIndex: 'score_total', key: 'score_total', width: 80 },
  { title: '规则分', dataIndex: 'score_rule', key: 'score_rule', width: 80 },
  { title: '模型分', dataIndex: 'score_model', key: 'score_model', width: 80 },
  { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 100 },
  { title: '操作', key: 'actions', width: 140 },
]

const evalColumns = [
  { title: '数据集', dataIndex: 'dataset_title', key: 'dataset_title', ellipsis: true },
  { title: '问题数', dataIndex: 'question_count', key: 'question_count', width: 80 },
  { title: '审核状态', dataIndex: 'review_status', key: 'review_status', width: 100 },
  { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 100 },
  { title: '操作', key: 'actions', width: 140 },
]

const scoreColor = (score: number | undefined): string => {
  if (score == null) return 'default'
  if (score >= 0.8) return 'green'
  if (score >= 0.5) return 'orange'
  return 'red'
}

const reviewColor = (status: string): string => {
  if (status === 'approved') return 'success'
  if (status === 'rejected') return 'error'
  return 'processing'
}

const reviewText = (status: string): string => {
  if (status === 'approved') return '已批准'
  if (status === 'rejected') return '已拒绝'
  return '待审核'
}

const rowClassName = (record: any) => {
  return (record as SopResearchDraft).draft_id === props.selectedDraftId ? 'selected-row' : ''
}

const evalRowClassName = (record: any) => {
  return (record as EvalResearchDraft).draft_id === props.selectedDraftId ? 'selected-row' : ''
}
</script>

<style lang="less" scoped>
.research-draft-table {
  height: 100%;
  display: flex;
  flex-direction: column;

  :deep(.ant-tabs) {
    height: 100%;
    display: flex;
    flex-direction: column;

    .ant-tabs-content-holder {
      flex: 1;
      overflow: auto;
    }
  }

  :deep(.selected-row) {
    background: var(--primary-color);
    color: #fff;
  }
}
</style>
