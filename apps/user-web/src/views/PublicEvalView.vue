<template>
  <div class="public-eval-view">
    <PublicTopBar @login="loginOpen = true" />
    <AuthGate v-if="loginOpen && !authStore.isAuthed" />
    <div class="workspace">
      <SplitPanes class="panes" :initial-left-ratio="0.2" :right-collapsible="false" :show-right-pane="false">
        <template #left>
          <div class="left-pane">
            <PublicTreePanel
              :tree-data="tree.treeData.value"
              :loading="tree.loading.value"
              :load-error="tree.loadError.value"
              @select="onTreeSelect"
            />
          </div>
        </template>
        <template #center>
          <div class="center-pane">
            <div class="pane-toolbar">
              <a-space>
                <a-button type="primary" size="small" @click="datasetModalOpen = true">
                  新建测试集
                </a-button>
                <a-button size="small" :disabled="!currentDataset" @click="questionModalOpen = true">
                  添加题目
                </a-button>
              </a-space>
            </div>

            <div v-if="!currentItem" class="empty-hint">从左侧分类选择一个测试集</div>
            <template v-else>
              <div class="dataset-card">
                <div class="dataset-title">
                  <span class="dataset-title-main">
                    {{ card?.title || currentItem.title }}
                    <a-tag v-if="currentItem.origin === 'user'" color="purple">网友投稿</a-tag>
                    <a-tag v-else color="blue">官方</a-tag>
                  </span>
                  <a-button size="small" @click="cardModalOpen = true">题集卡</a-button>
                </div>
                <div class="dataset-meta">
                  <span>{{ card?.question_count ?? currentItem.question_count ?? 0 }} 题</span>
                  <span v-if="currentItem.origin === 'user'">
                    · {{ currentItem.author_label || '游客' }} 投稿
                  </span>
                </div>
                <div v-if="card?.description" class="dataset-desc">{{ card.description }}</div>
              </div>

              <a-spin :spinning="questionsLoading">
                <div v-if="questions.length" class="question-list">
                  <div v-for="(q, idx) in questions" :key="q.question_id" class="question-item">
                    <div
                      class="question-row"
                      :class="{ expanded: expandedKey === q.question_id }"
                      @click="toggleQuestion(q.question_id)"
                    >
                      <EvalLevelBadge :level="(q.intent_level as any) || 'L1'" />
                      <span class="question-index">{{ offset + idx + 1 }}.</span>
                      <div class="question-body">
                        <!-- 用户文本一律纯插值（R5 硬约束：禁 v-html / renderRichText） -->
                        <div class="question-text">{{ q.question }}</div>
                      </div>
                      <!-- 答题=既有评测单题通道（save:false，1 小时自清）：官方题才有，投稿题不在评测库 -->
                      <a-button
                        v-if="q.origin === 'official'"
                        class="answer-btn"
                        size="small"
                        :loading="attemptOf(q.question_id)?.status === 'running'"
                        :disabled="hasRunning && attemptOf(q.question_id)?.status !== 'running'"
                        :title="hasRunning && attemptOf(q.question_id)?.status !== 'running' ? '同一时间只答一题，请等当前作答完成' : '让系统按本题知识库作答并判分'"
                        @click.stop="answerQuestion(q)"
                      >
                        答题
                      </a-button>
                      <span class="question-chevron">{{ expandedKey === q.question_id ? '▾' : '▸' }}</span>
                    </div>
                    <div v-if="expandedKey === q.question_id" class="question-detail">
                      <div v-if="attemptOf(q.question_id)" class="attempt-block">
                        <template v-if="attemptOf(q.question_id)?.status === 'running'">
                          <a-spin size="small" />
                          <span class="attempt-running-text">模型作答中…已 {{ elapsedText(q.question_id) }}（检索 + 判分，通常几分钟）</span>
                        </template>
                        <template v-else-if="attemptOf(q.question_id)?.status === 'failed'">
                          <div class="detail-label">模型作答</div>
                          <div class="question-answer detail-muted">{{ attemptOf(q.question_id)?.error }}</div>
                        </template>
                        <template v-else>
                          <div class="attempt-head">
                            <span class="detail-label">模型作答</span>
                            <a-tag :color="verdictColor(q.question_id)">{{ verdictText(q.question_id) }}</a-tag>
                            <span class="attempt-sub">{{ attemptMeta(q.question_id) }}</span>
                          </div>
                          <div class="question-answer">{{ attemptOf(q.question_id)?.answer }}</div>
                          <div v-if="citationText(q.question_id)" class="attempt-cites">{{ citationText(q.question_id) }}</div>
                          <div v-if="attemptOf(q.question_id)?.reason" class="attempt-reason">判分理由：{{ attemptOf(q.question_id)?.reason }}</div>
                        </template>
                      </div>
                      <div class="detail-label">参考答案</div>
                      <div v-if="q.answer" class="question-answer">{{ q.answer }}</div>
                      <div v-else class="question-answer detail-muted">本集参考答案未公开（盲测档）</div>
                      <div v-if="q.tags && q.tags.length" class="question-detail-meta">标签：{{ q.tags.join(' · ') }}</div>
                      <div v-if="q.origin === 'user'" class="question-author">
                        {{ q.author_label || '游客' }} 投稿{{ q.created_at ? ' · ' + q.created_at : '' }}
                      </div>
                    </div>
                  </div>
                  <div v-if="questionsTotal > offset + questions.length" class="load-more">
                    <a-button size="small" :loading="questionsLoading" @click="loadMoreQuestions">
                      加载更多（还剩 {{ questionsTotal - offset - questions.length }} 题）
                    </a-button>
                  </div>
                </div>
                <div v-else-if="!questionsLoading" class="empty-hint">该测试集暂无题目</div>
              </a-spin>
            </template>
          </div>
        </template>
      </SplitPanes>
    </div>

    <SubmitDatasetModal
      v-model:open="datasetModalOpen"
      :tree-nodes="tree.nodes.value"
      @submitted="onSubmitted"
      @login="loginOpen = true"
    />
    <SubmitQuestionModal
      v-model:open="questionModalOpen"
      :datasets="datasetOptions"
      :default-dataset="currentItem?.origin ? { ref_id: currentItem.ref_id, origin: currentItem.origin, title: currentItem.title } : undefined"
      @submitted="onSubmitted"
      @login="loginOpen = true"
    />
    <!-- 题集卡弹层复用后台同款组件（EvalDatasetCardModal）：发布方/测试类型/简介/来源/分布/公开锚点成绩。
         不传 questions——公开面只有分页题目，喂局部数据会把层级分布统计算歪。 -->
    <EvalDatasetCardModal v-model:open="cardModalOpen" :dataset="cardDataset" />
  </div>
</template>

<script setup lang="ts">
/** 公开测试集页（设计 §11 左栏线框）：左分类树 + 右题集卡/题目列表 + 投稿入口。
 *  题目行自建渲染（纯插值）——不复用 EvalQuestionCard：其展开区走 renderRichText(v-html)，
 *  与 R5「用户文本禁 HTML 渲染」硬约束冲突（施工记录偏差①）。 */
import { computed, onMounted, ref, watch } from 'vue'
import { SplitPanes } from '@angineer/ui-kit'
// 直连单文件、不走 evals-ui barrel：barrel 会把 EvalRunPanel 等整包送进 vite 编译，
// 其 scoped less 引用 @evals-* 变量（admin 侧 additionalData 注入，user-web 未注）即构建失败。
import EvalLevelBadge from '@angineer/evals-ui/components/EvalLevelBadge.vue'
import EvalDatasetCardModal from '@angineer/evals-ui/components/EvalDatasetCardModal.vue'
import type { EvalDataset } from '@angineer/evals-ui'
import PublicTopBar from '@/components/PublicTopBar.vue'
import AuthGate from '@/components/AuthGate.vue'
import PublicTreePanel from '@/components/public/PublicTreePanel.vue'
import SubmitDatasetModal from '@/components/public/SubmitDatasetModal.vue'
import SubmitQuestionModal from '@/components/public/SubmitQuestionModal.vue'
import { useCommunityTree, type CommunityTreeNode } from '@/composables/useCommunityTree'
import { useQuestionAttempt } from '@/composables/useQuestionAttempt'
import { communityApi, type DatasetCard, type PublicQuestion, type TreeItem } from '@/api/community'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()
const tree = useCommunityTree('eval')
const attempt = useQuestionAttempt()
const hasRunning = attempt.hasRunning
const loginOpen = ref(false)
const datasetModalOpen = ref(false)
const questionModalOpen = ref(false)

const currentItem = ref<TreeItem | null>(null)
const card = ref<DatasetCard | null>(null)
// 题目行手风琴详情（业主 10-15：点开=问题+参考答案+标签/归属）
const expandedKey = ref<string | null>(null)

function toggleQuestion(key: string) {
  expandedKey.value = expandedKey.value === key ? null : key
}
const questions = ref<PublicQuestion[]>([])
const questionsTotal = ref(0)
const offset = ref(0)
const questionsLoading = ref(false)

const currentDataset = computed(() => currentItem.value?.kind === 'dataset' ? currentItem.value : null)

const cardModalOpen = ref(false)
// EvalDatasetCardModal 吃后台 EvalDataset 形状；公开面 DatasetCard 是其白名单子集，
// 缺省字段给空串——library_id 留空即「知识库」行不渲染（不向公网露内部库 id）。
const cardDataset = computed(() => {
  const c = card.value
  if (!c) return null
  return {
    dataset_id: c.dataset_id,
    title: c.title,
    category: '',
    description: c.description || '',
    schema_version: '',
    version: c.version || '',
    library_id: '',
    question_count: c.question_count ?? 0,
    source_file: '',
    meta: c.meta || {},
    folder_id: '',
    sort_order: 0,
    created_at: '',
    updated_at: '',
  } as unknown as EvalDataset
})

const datasetOptions = computed(() =>
  tree.items.value.map((item) => ({ ref_id: item.ref_id, origin: item.origin, title: item.title })),
)

/** ---- 答题（复用评测单题通道，见 useQuestionAttempt 头注释） ---- */

function attemptOf(questionId: string) {
  return attempt.attempts[questionId]
}

function answerQuestion(q: PublicQuestion) {
  const ds = currentDataset.value
  if (!ds) return
  expandedKey.value = q.question_id
  void attempt.start(ds.ref_id, q.question_id)
}

function elapsedText(questionId: string): string {
  void attempt.tick.value // 心跳依赖：驱动每秒重渲染
  const a = attempt.attempts[questionId]
  if (!a) return '0 秒'
  const ms = a.status === 'running' ? Date.now() - a.startedAt : a.elapsedMs
  const sec = Math.max(0, Math.floor(ms / 1000))
  if (sec < 60) return `${sec} 秒`
  return `${Math.floor(sec / 60)} 分 ${sec % 60} 秒`
}

// quality 取值与后台评测一致：correct / wrong / uncertain（EvalQuestionCard 同口径）
function verdictText(questionId: string): string {
  const a = attempt.attempts[questionId]
  if (a?.quality === 'correct') return '判分：正确'
  if (a?.quality === 'wrong') return '判分：错误'
  if (a?.quality === 'uncertain') return '判分：存疑'
  return '判分：未判定'
}

function verdictColor(questionId: string): string {
  const a = attempt.attempts[questionId]
  if (a?.quality === 'correct') return 'green'
  if (a?.quality === 'wrong') return 'red'
  if (a?.quality === 'uncertain') return 'orange'
  return 'default'
}

function attemptMeta(questionId: string): string {
  const a = attempt.attempts[questionId]
  if (!a) return ''
  const parts: string[] = []
  if (a.score !== null) parts.push(`得分 ${a.score}`)
  if (a.latencyMs > 0) parts.push(`链路耗时 ${(a.latencyMs / 1000).toFixed(1)} 秒`)
  if (a.judge) parts.push(`判官 ${a.judge}`)
  return parts.join(' · ')
}

function truncateText(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max)}…` : text
}

function citationText(questionId: string): string {
  const cites = attempt.attempts[questionId]?.citations || []
  if (!cites.length) return ''
  const shown = cites
    .slice(0, 4)
    .map((c) => `${c.marker ? `[${c.marker}] ` : ''}${truncateText(c.title, 28)}`)
    .join('；')
  return `引用 ${cites.length} 处：${shown}${cites.length > 4 ? '…' : ''}`
}

async function openItem(item: TreeItem) {
  currentItem.value = item
  card.value = null
  questions.value = []
  questionsTotal.value = 0
  offset.value = 0
  expandedKey.value = null
  attempt.reset() // 题号可能跨集重名，清掉上一集的作答态
  if (item.kind !== 'dataset') return
  try {
    card.value = await communityApi.getDataset(item.ref_id, item.origin)
  } catch {
    card.value = null
  }
  await fetchQuestions(false)
}

async function fetchQuestions(append: boolean) {
  const item = currentItem.value
  if (!item || item.kind !== 'dataset') return
  questionsLoading.value = true
  try {
    const resp = await communityApi.getQuestions(item.ref_id, item.origin, offset.value, 50)
    questions.value = append ? [...questions.value, ...resp.items] : resp.items
    questionsTotal.value = resp.total
  } catch {
    if (!append) questions.value = []
  } finally {
    questionsLoading.value = false
  }
}

function loadMoreQuestions() {
  offset.value += 50
  void fetchQuestions(true)
}

function onTreeSelect(row: CommunityTreeNode | null) {
  tree.select(row)
  const item = row?.communityItem || null
  if (item) void openItem(item)
  else currentItem.value = null
}

async function onSubmitted() {
  await tree.reload(true)
  // 新投稿条目大概率在树尾；不自动跳转，用户点选即可（避免打断当前浏览）
}

watch(() => tree.selectedItem.value, (item) => {
  if (!item && currentItem.value) currentItem.value = null
})

onMounted(async () => {
  if (!authStore.isAuthed) void authStore.enterGuestMode()  // 页面挂载即签游客 cookie（R3 兜签发竞态）
  await tree.reload()
  if (tree.selectedItem.value) void openItem(tree.selectedItem.value)
})
</script>

<style lang="less" scoped>
.public-eval-view {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--bg-primary);

  .workspace {
    flex: 1;
    min-height: 0;

    .panes {
      height: 100%;
    }
  }

  .left-pane {
    height: 100%;
    padding: 8px 4px;
  }

  .center-pane {
    height: 100%;
    overflow-y: auto;
    padding: 16px 24px;
    color: var(--text-primary);
  }

  .pane-toolbar {
    margin-bottom: 12px;
  }

  .empty-hint {
    padding: 40px 0;
    text-align: center;
    color: var(--text-tertiary);
    font-size: 13px;
  }

  .dataset-card {
    margin-bottom: 16px;

    .dataset-title {
      font-size: 17px;
      font-weight: 600;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;

      .dataset-title-main {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        min-width: 0;
      }
    }

    .dataset-meta {
      margin-top: 4px;
      font-size: 12px;
      color: var(--text-tertiary);
      display: flex;
      gap: 6px;
    }

    .dataset-desc {
      margin-top: 8px;
      font-size: 13px;
      color: var(--text-secondary);
      white-space: pre-wrap;
    }

  }

  .question-list {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .question-item {
    display: flex;
    flex-direction: column;
  }

  .question-row {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    padding: 10px 12px;
    border: 1px solid var(--border-color, rgba(0, 0, 0, 0.08));
    border-radius: 8px;
    cursor: pointer;
    transition: background 0.15s;

    &:hover {
      background: var(--bg-hover, rgba(0, 0, 0, 0.03));
    }

    &.expanded {
      border-color: var(--primary-color);
    }

    .question-index {
      color: var(--text-tertiary);
      font-size: 13px;
      flex-shrink: 0;
      padding-top: 1px;
    }

    .question-body {
      min-width: 0;
      flex: 1;

      .question-text {
        font-size: 14px;
        white-space: pre-wrap;
        word-break: break-word;
      }
    }

    .question-chevron {
      flex-shrink: 0;
      color: var(--text-tertiary);
      font-size: 12px;
      padding-top: 2px;
    }

    .answer-btn {
      flex-shrink: 0;
      margin-top: -2px;
    }
  }

  .question-detail {
    margin: -1px 12px 0 12px;
    padding: 10px 12px;
    border: 1px solid var(--border-color, rgba(0, 0, 0, 0.08));
    border-top: none;
    border-radius: 0 0 8px 8px;
    background: var(--bg-secondary, rgba(0, 0, 0, 0.02));

    .detail-label {
      font-size: 12px;
      font-weight: 600;
      color: var(--text-secondary);
      margin-bottom: 4px;
    }

    .question-answer {
      font-size: 13px;
      color: var(--text-primary);
      white-space: pre-wrap;
      word-break: break-word;

      &.detail-muted {
        color: var(--text-tertiary);
      }
    }

    .question-detail-meta,
    .question-author {
      margin-top: 6px;
      font-size: 11px;
      color: var(--text-tertiary);
    }

    .attempt-block {
      margin-bottom: 10px;
      padding-bottom: 10px;
      border-bottom: 1px dashed var(--border-color, rgba(0, 0, 0, 0.08));

      .attempt-head {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 4px;
        flex-wrap: wrap;

        .detail-label {
          margin-bottom: 0;
        }
      }

      .attempt-sub {
        font-size: 11px;
        color: var(--text-tertiary);
      }

      .attempt-running-text {
        margin-left: 8px;
        font-size: 12px;
        color: var(--text-secondary);
      }

      .attempt-cites,
      .attempt-reason {
        margin-top: 6px;
        font-size: 11px;
        color: var(--text-tertiary);
        white-space: pre-wrap;
        word-break: break-word;
      }
    }
  }

  .load-more {
    padding: 12px 0;
    text-align: center;
  }
}
</style>
