<template>
  <div class="research-draft-detail">
    <a-spin :spinning="loading">
      <template v-if="draft && detail">
        <div class="detail-header">
          <h4 class="detail-title">{{ detailTitle }}</h4>
          <a-tag :color="reviewColor">{{ reviewText }}</a-tag>
        </div>

        <!-- SOP 草稿：显示评分 -->
        <div v-if="!isEval" class="detail-scores">
          <span class="score-item">
            总分: <a-tag :color="scoreColor(sopDraft?.score_total)">{{ sopDraft?.score_total?.toFixed(2) }}</a-tag>
          </span>
          <span class="score-item">
            规则分: <a-tag :color="scoreColor(sopDraft?.score_rule)">{{ sopDraft?.score_rule?.toFixed(2) }}</a-tag>
          </span>
          <span class="score-item">
            模型分: <a-tag :color="scoreColor(sopDraft?.score_model)">{{ sopDraft?.score_model?.toFixed(2) }}</a-tag>
          </span>
        </div>

        <!-- Eval 草稿：显示问题数 -->
        <div v-if="isEval" class="detail-scores">
          <span class="score-item">
            问题数: <a-tag>{{ evalDraft?.question_count ?? evalItems.length }}</a-tag>
          </span>
        </div>

        <!-- SOP 验证问题 -->
        <div v-if="!isEval && validationIssues.length" class="detail-section">
          <h5>验证问题</h5>
          <a-timeline>
            <a-timeline-item
              v-for="issue in validationIssues"
              :key="issue.code"
              :color="issue.severity === 'error' ? 'red' : issue.severity === 'warning' ? 'orange' : 'blue'"
            >
              <div class="issue-message">{{ issue.message }}</div>
              <div v-if="issue.location" class="issue-location">{{ issue.location }}</div>
            </a-timeline-item>
          </a-timeline>
        </div>

        <!-- SOP 步骤列表 -->
        <div v-if="!isEval && steps.length" class="detail-section">
          <h5>步骤列表（{{ steps.length }}）</h5>
          <div v-for="(step, idx) in steps" :key="step.id || idx" class="step-card">
            <div class="step-header">
              <span class="step-index">#{{ idx + 1 }}</span>
              <span class="step-id">{{ step.id || step.name || step.name_zh }}</span>
              <a-tag v-if="step.tool">{{ step.tool }}</a-tag>
            </div>
            <div v-if="step.description || step.action" class="step-description">
              {{ step.description || step.action }}
            </div>
          </div>
        </div>

        <!-- SOP 变量 / 黑板 -->
        <div v-if="!isEval && variablesKeys.length" class="detail-section">
          <h5>变量 / 黑板</h5>
          <a-descriptions size="small" :column="1" bordered>
            <a-descriptions-item
              v-for="key in variablesKeys"
              :key="key"
              :label="key"
            >
              {{ formatValue(variables[key]) }}
            </a-descriptions-item>
          </a-descriptions>
        </div>

        <!-- SOP 警告 -->
        <div v-if="!isEval && warnings.length" class="detail-section">
          <h5>警告</h5>
          <div v-for="(w, idx) in warnings" :key="idx" class="warning-item">
            <a-alert type="warning" :message="w.message || w" show-icon />
          </div>
        </div>

        <!-- Eval 问题列表 -->
        <div v-if="isEval && evalItems.length" class="detail-section">
          <h5>评估问题（{{ evalItems.length }}）</h5>
          <div v-for="(item, idx) in evalItems" :key="item.id || idx" class="step-card">
            <div class="step-header">
              <span class="step-index">#{{ idx + 1 }}</span>
              <span class="step-id">{{ item.id || item.name || '' }}</span>
            </div>
            <div v-if="item.question || item.prompt" class="step-description">
              {{ item.question || item.prompt }}
            </div>
          </div>
        </div>

        <div class="detail-actions">
          <a-button
            v-if="draft.review_status === 'pending' && !isEval"
            type="primary"
            @click="emit('approve-sop', draft.draft_id)"
          >
            批准
          </a-button>
          <a-button
            v-if="draft.review_status === 'pending' && isEval"
            type="primary"
            @click="emit('approve-eval', draft.draft_id)"
          >
            批准
          </a-button>
          <a-button
            v-if="draft.review_status === 'pending'"
            @click="emit('reject-draft', draft.draft_id, type)"
          >
            拒绝
          </a-button>
        </div>
      </template>

      <div v-else class="detail-empty">
        <div class="detail-empty-icon">
          <FileSearchOutlined />
        </div>
        <span>选择一个草稿查看详情</span>
      </div>
    </a-spin>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { SopResearchDraft, EvalResearchDraft, ResearchValidationIssue } from '../../types/sopResearch'
import { FileSearchOutlined } from '@ant-design/icons-vue'

interface Props {
  draft: SopResearchDraft | EvalResearchDraft | null
  detail: any
  type: 'sop' | 'eval'
  loading: boolean
}

const props = defineProps<Props>()

const emit = defineEmits<{
  'approve-sop': [draftId: string]
  'approve-eval': [draftId: string]
  'reject-draft': [draftId: string, type: 'sop' | 'eval']
}>()

const isEval = computed(() => props.type === 'eval')

// 按类型窄化草稿对象，便于模板安全访问专属字段
const sopDraft = computed(() => (isEval.value ? null : (props.draft as SopResearchDraft | null)))
const evalDraft = computed(() => (isEval.value ? (props.draft as EvalResearchDraft | null) : null))

const detailTitle = computed(() => {
  if (!props.draft) return ''
  if (isEval.value) return (props.draft as EvalResearchDraft).dataset_title || '评估草稿'
  return (props.draft as SopResearchDraft).title || 'SOP 草稿'
})

const reviewColor = computed(() => {
  if (!props.draft) return 'default'
  if (props.draft.review_status === 'approved') return 'success'
  if (props.draft.review_status === 'rejected') return 'error'
  return 'processing'
})

const reviewText = computed(() => {
  if (!props.draft) return ''
  if (props.draft.review_status === 'approved') return '已批准'
  if (props.draft.review_status === 'rejected') return '已拒绝'
  return '待审核'
})

const scoreColor = (score: number | undefined): string => {
  if (score == null) return 'default'
  if (score >= 0.8) return 'green'
  if (score >= 0.5) return 'orange'
  return 'red'
}

const validationIssues = computed<ResearchValidationIssue[]>(() => {
  if (!props.detail) return []
  const raw = props.detail.validation_issues || props.detail.issues || []
  return raw as ResearchValidationIssue[]
})

const steps = computed<any[]>(() => {
  if (!props.detail) return []
  return props.detail.steps || []
})

const variables = computed<Record<string, any>>(() => {
  if (!props.detail) return {}
  return props.detail.variables || props.detail.blackboard || {}
})

const variablesKeys = computed(() => Object.keys(variables.value))

const warnings = computed<any[]>(() => {
  if (!props.detail) return []
  return props.detail.warnings || []
})

// Eval 草稿的问题列表，兼容 items / questions 两种字段命名
const evalItems = computed<any[]>(() => {
  if (!props.detail) return []
  return props.detail.items || props.detail.questions || []
})

const formatValue = (val: any): string => {
  if (val === null || val === undefined) return '-'
  if (typeof val === 'object') return JSON.stringify(val)
  return String(val)
}
</script>

<style lang="less" scoped>
.research-draft-detail {
  height: 100%;
  overflow-y: auto;
  padding: 16px;
}

.detail-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 12px;

  .detail-title {
    margin: 0;
    font-size: 15px;
    font-weight: 600;
    flex: 1;
    word-break: break-all;
  }
}

.detail-scores {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;

  .score-item {
    font-size: 12px;
    color: var(--text-secondary);
  }
}

.detail-section {
  margin-bottom: 16px;

  h5 {
    margin: 0 0 8px;
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary);
  }
}

.step-card {
  border: 1px solid var(--border-color);
  border-radius: 6px;
  padding: 10px 12px;
  margin-bottom: 8px;

  .step-header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 6px;

    .step-index {
      font-weight: 600;
      color: var(--primary-color);
      font-size: 11px;
    }

    .step-id {
      font-weight: 500;
      font-size: 13px;
    }
  }

  .step-description {
    font-size: 12px;
    color: var(--text-secondary);
    line-height: 1.5;
  }
}

.issue-message {
  font-size: 12px;
}

.issue-location {
  font-size: 11px;
  color: var(--text-secondary);
  margin-top: 2px;
}

.warning-item {
  margin-bottom: 6px;
}

.detail-actions {
  display: flex;
  gap: 8px;
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid var(--border-color);
}

.detail-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--text-secondary);
  gap: 8px;

  .detail-empty-icon {
    font-size: 36px;
    opacity: 0.3;
  }
}
</style>
