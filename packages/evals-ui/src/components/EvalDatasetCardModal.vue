<template>
  <a-modal
    :open="open"
    :title="dataset?.title || '题集卡'"
    :footer="null"
    :width="560"
    @cancel="handleCancel"
  >
    <div v-if="dataset" class="eval-dataset-card">
      <a-descriptions :column="2" size="small" bordered :label-style="{ whiteSpace: 'nowrap' }">
        <a-descriptions-item label="题数">{{ dataset.question_count }}</a-descriptions-item>
        <a-descriptions-item label="分类">{{ dataset.category }}</a-descriptions-item>
        <a-descriptions-item v-if="card.publisher" label="发布方">{{ card.publisher }}</a-descriptions-item>
        <a-descriptions-item v-if="card.domain" label="测试类型">{{ card.domain }}</a-descriptions-item>
        <a-descriptions-item v-if="card.purpose" label="题集简介" :span="2">{{ card.purpose }}</a-descriptions-item>
        <a-descriptions-item v-if="card.source_url" label="来源" :span="2">
          <a :href="card.source_url" target="_blank" rel="noopener">{{ card.source_url }}</a>
          <div v-if="card.source_note" class="eval-dataset-card__note">{{ card.source_note }}</div>
        </a-descriptions-item>
        <a-descriptions-item v-else-if="card.source_note" label="来源说明" :span="2">{{ card.source_note }}</a-descriptions-item>
        <a-descriptions-item
          v-if="dataset.library_id"
          label="知识库"
          :span="card.mode ? 1 : 2"
        >{{ libraryName || dataset.library_id }}</a-descriptions-item>
        <a-descriptions-item v-if="card.mode" label="方式">{{ card.mode }}</a-descriptions-item>
      </a-descriptions>

      <div v-if="distributionRows.length || levelRows.length" class="eval-dataset-card__charts">
        <div v-if="distributionRows.length" class="eval-dataset-card__chart">
          <div class="eval-dataset-card__section">题集分布</div>
          <div class="eval-dataset-card__bars">
            <div v-for="row in distributionRows" :key="row.label" class="eval-dataset-card__bar">
              <div class="eval-dataset-card__bar-count">{{ row.count }} 题</div>
              <div class="eval-dataset-card__bar-track">
                <div class="eval-dataset-card__bar-fill" :style="{ height: barPercent(distributionRows, row.count) }"></div>
              </div>
              <div class="eval-dataset-card__bar-label" :title="row.note ? `${row.label}（${row.note}）` : row.label">{{ row.label }}</div>
            </div>
          </div>
        </div>
        <div v-if="levelRows.length" class="eval-dataset-card__chart">
          <div class="eval-dataset-card__section">层级分布（L0-L4）</div>
          <div class="eval-dataset-card__bars">
            <div v-for="row in levelRows" :key="row.label" class="eval-dataset-card__bar">
              <div class="eval-dataset-card__bar-count">{{ row.count }} 题</div>
              <div class="eval-dataset-card__bar-track">
                <div class="eval-dataset-card__bar-fill eval-dataset-card__bar-fill--level" :style="{ height: barPercent(levelRows, row.count) }"></div>
              </div>
              <div class="eval-dataset-card__bar-label" :title="row.label">{{ row.label }}</div>
            </div>
          </div>
        </div>
      </div>

      <template v-if="leaderboardRows.length">
        <div class="eval-dataset-card__section">公开锚点成绩</div>
        <div class="eval-dataset-card__rows">
          <div v-for="row in leaderboardRows" :key="row.label" class="eval-dataset-card__row">
            <span class="eval-dataset-card__label">{{ row.label }}</span>
            <span class="eval-dataset-card__value">{{ row.score }}</span>
            <span v-if="row.note" class="eval-dataset-card__note">{{ row.note }}</span>
          </div>
        </div>
      </template>

      <a-empty
        v-if="!hasCardMeta"
        description="未登记扩展信息（发布方/来源/锚点等）"
        :image-style="{ height: '48px' }"
      />
    </div>
  </a-modal>
</template>

<script setup lang="ts">
/** 题集卡弹层：只读展示 eval_dataset.meta；meta 缺省退化为题数/分类基础信息。 */
import { computed } from 'vue'
import type { EvalDataset, EvalDatasetCardMeta } from '../types/eval'

const props = defineProps<{
  open: boolean
  dataset?: EvalDataset | null
  /** 知识库名称（宿主解析；缺省显示 dataset.library_id 原值） */
  libraryName?: string
  /** meta.distribution 缺省时按题目层级自动统计 */
  questions?: { intent_level?: string | null }[]
}>()

const emit = defineEmits<{
  'update:open': [open: boolean]
}>()

const card = computed<EvalDatasetCardMeta>(() => props.dataset?.meta || {})

const hasCardMeta = computed(() =>
  Boolean(
    card.value.publisher
    || card.value.domain
    || card.value.purpose
    || card.value.source_url
    || card.value.source_note
    || card.value.distribution?.length
    || card.value.leaderboard?.length
  )
)

const distributionRows = computed(() => card.value.distribution || [])

const levelRows = computed(() => {
  const counts = new Map<string, number>()
  for (const q of props.questions || []) {
    const level = q.intent_level || '未知'
    counts.set(level, (counts.get(level) || 0) + 1)
  }
  return [...counts.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([label, count]) => ({ label, count }))
})

const barPercent = (rows: { count: number }[], count: number) => {
  const max = Math.max(1, ...rows.map(r => r.count))
  return `${Math.max(4, Math.round((count / max) * 100))}%`
}

const leaderboardRows = computed(() => card.value.leaderboard || [])

const handleCancel = () => emit('update:open', false)
</script>

<style lang="less" scoped>
.eval-dataset-card {
  display: flex;
  flex-direction: column;
  gap: 12px;

  &__section {
    font-size: 13px;
    font-weight: 600;
  }

  &__rows {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  &__charts {
    display: flex;
    gap: 16px;
    align-items: flex-start;
  }

  &__chart {
    flex: 1;
    min-width: 0;
  }

  &__bars {
    display: flex;
    align-items: flex-end;
    gap: 12px;
    padding: 4px 2px 0;
  }

  &__bar {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
  }

  &__bar-count {
    font-size: 11px;
    color: var(--text-secondary);
  }

  &__bar-track {
    width: 100%;
    max-width: 96px;
    height: 64px;
    display: flex;
    align-items: flex-end;
    border-radius: 4px;
    background: var(--border-color);
  }

  &__bar-fill {
    width: 100%;
    border-radius: 4px;
    background: var(--evals-dataset-bar-color, #6a5fe0);
  }

  &__bar-fill--level {
    background: var(--evals-dataset-bar-color-level, #52c41a);
  }

  &__bar-label {
    max-width: 100%;
    font-size: 11px;
    line-height: 1.3;
    text-align: center;
    color: var(--text-secondary);
    word-break: break-word;
  }

  &__row {
    display: flex;
    align-items: baseline;
    gap: 8px;
    font-size: 12px;
    line-height: 1.6;
  }

  &__label {
    color: var(--text-secondary);
  }

  &__value {
    font-weight: 600;
  }

  &__note {
    color: var(--text-secondary);
    font-size: 11px;
  }
}
</style>
