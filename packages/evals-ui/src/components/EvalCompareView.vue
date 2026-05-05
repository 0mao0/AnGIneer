<template>
  <div class="eval-compare-view">
    <div class="eval-compare-view__header">
      <span>运行对比</span>
      <a-select
        v-model:value="runIdA"
        placeholder="选择运行 A"
        style="width: 200px"
        size="small"
      >
        <a-select-option v-for="r in runs" :key="r.run_id" :value="r.run_id">
          {{ r.run_id.slice(0, 8) }} ({{ r.status }})
        </a-select-option>
      </a-select>
      <span>vs</span>
      <a-select
        v-model:value="runIdB"
        placeholder="选择运行 B"
        style="width: 200px"
        size="small"
      >
        <a-select-option v-for="r in runs" :key="r.run_id" :value="r.run_id">
          {{ r.run_id.slice(0, 8) }} ({{ r.status }})
        </a-select-option>
      </a-select>
      <a-button size="small" type="primary" :disabled="!runIdA || !runIdB" @click="doCompare">
        对比
      </a-button>
    </div>

    <div v-if="compareResult" class="eval-compare-view__body">
      <div class="eval-compare-view__summary">
        <div class="eval-compare-view__run-col">
          <div class="eval-compare-view__col-label">运行 A</div>
          <EvalScoreBar
            v-if="compareResult.run_a.summary_scores?.overall_score != null"
            label="综合"
            :score="compareResult.run_a.summary_scores.overall_score"
          />
          <EvalScoreBar
            v-if="compareResult.run_a.summary_scores?.retrieval_score != null"
            label="检索"
            :score="compareResult.run_a.summary_scores.retrieval_score"
          />
          <EvalScoreBar
            v-if="compareResult.run_a.summary_scores?.answer_score != null"
            label="回答"
            :score="compareResult.run_a.summary_scores.answer_score"
          />
        </div>
        <div class="eval-compare-view__run-col">
          <div class="eval-compare-view__col-label">运行 B</div>
          <EvalScoreBar
            v-if="compareResult.run_b.summary_scores?.overall_score != null"
            label="综合"
            :score="compareResult.run_b.summary_scores.overall_score"
          />
          <EvalScoreBar
            v-if="compareResult.run_b.summary_scores?.retrieval_score != null"
            label="检索"
            :score="compareResult.run_b.summary_scores.retrieval_score"
          />
          <EvalScoreBar
            v-if="compareResult.run_b.summary_scores?.answer_score != null"
            label="回答"
            :score="compareResult.run_b.summary_scores.answer_score"
          />
        </div>
      </div>

      <div v-if="compareResult.question_changes.length" class="eval-compare-view__changes">
        <div class="eval-compare-view__section-title">状态变化</div>
        <div
          v-for="change in compareResult.question_changes"
          :key="change.question_id"
          class="eval-compare-view__change-row"
          :class="`eval-compare-view__change-row--${change.change}`"
        >
          <span>{{ change.question_id }}</span>
          <span>{{ change.status_a }} → {{ change.status_b }}</span>
          <a-tag :color="change.change === 'improved' ? 'success' : 'error'">
            {{ change.change === 'improved' ? '改善' : '退步' }}
          </a-tag>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import EvalScoreBar from './EvalScoreBar.vue'
import type { EvalRun, EvalCompareResult } from '../types/eval'

defineProps<{
  runs: EvalRun[]
}>()

const runIdA = ref<string | undefined>(undefined)
const runIdB = ref<string | undefined>(undefined)
const compareResult = ref<EvalCompareResult | null>(null)

const doCompare = async () => {
  if (!runIdA.value || !runIdB.value) return
  try {
    const resp = await fetch(
      `/api/evals/compare?run_id_a=${runIdA.value}&run_id_b=${runIdB.value}`
    )
    if (resp.ok) {
      compareResult.value = await resp.json()
    }
  } catch (e) {
    console.error('对比失败:', e)
  }
}
</script>

<style lang="less" scoped>
.eval-compare-view {
  &__header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 12px;
    border-bottom: 1px solid var(--dp-border-color, rgba(255, 255, 255, 0.06));
  }

  &__body {
    padding: 12px;
  }

  &__summary {
    display: flex;
    gap: 24px;
    margin-bottom: 16px;
  }

  &__run-col {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  &__col-label {
    font-weight: 600;
    font-size: 14px;
    margin-bottom: 4px;
  }

  &__section-title {
    font-size: 13px;
    font-weight: 600;
    margin-bottom: 8px;
    color: var(--dp-text-secondary, rgba(255, 255, 255, 0.45));
  }

  &__change-row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 8px;
    border-radius: 4px;
    margin-bottom: 4px;
    font-size: 13px;

    &--improved {
      background: rgba(82, 196, 26, 0.1);
    }

    &--regressed {
      background: rgba(245, 34, 45, 0.1);
    }
  }
}
</style>
