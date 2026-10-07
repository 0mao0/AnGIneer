<template>
  <a-drawer
    :open="props.open"
    title="迁移任务详情"
    :width="640"
    @update:open="(v: boolean) => emit('update:open', v)"
    @close="emit('close')"
  >
    <a-spin :spinning="loading && !task">
      <template v-if="task">
        <!-- 概览 -->
        <a-descriptions :column="2" size="small" bordered>
          <a-descriptions-item label="操作">{{ opLabel }}</a-descriptions-item>
          <a-descriptions-item label="状态">
            <a-tag :color="statusColor">{{ statusLabel }}</a-tag>
          </a-descriptions-item>
          <a-descriptions-item label="迁入目标" :span="2">{{ destinationLine }}</a-descriptions-item>
          <a-descriptions-item label="提交时间">{{ task.created_at }}</a-descriptions-item>
          <a-descriptions-item label="回滚窗口">{{ deadlineLine }}</a-descriptions-item>
        </a-descriptions>

        <!-- 阶段步进 -->
        <div class="mig-stages">
          <div
            v-for="s in stageFlow"
            :key="s.key"
            class="mig-stage"
            :class="{ active: s.state === 'active', done: s.state === 'done', failed: s.state === 'failed' }"
          >
            {{ s.label }}
          </div>
        </div>
        <p v-if="task.stage_message" class="mig-stage-msg">{{ task.stage_message }}</p>

        <!-- 进度 -->
        <p class="mig-progress" v-if="task.progress_total">
          已完成 {{ task.progress_done }}/{{ task.progress_total }} 篇
        </p>
        <a-progress
          v-if="task.progress_total"
          :percent="Math.round((task.progress_done / task.progress_total) * 100)"
          size="small"
        />

        <!-- 错误摘要（人话一行） -->
        <a-alert v-if="task.error" type="error" show-icon class="mig-error" :message="task.error" />
        <a-alert
          v-if="task.status === 'switch_reload_failed'"
          type="warning"
          show-icon
          class="mig-error"
          message="数据已全部迁移完成，只差服务加载新库清单一步——运维重启文档服务后本任务会自动收敛为「已完成」，无需操作。"
        />

        <!-- 六类对账 -->
        <template v-if="task.preview?.counts">
          <h4 class="mig-h">迁移内容核对</h4>
          <p class="mig-verify" :class="{ bad: task.verify && !task.verify.ok }">
            <template v-if="!task.verify">对账将在切换前自动完成</template>
            <template v-else-if="task.verify.ok">对账一致：迁移后的数量与预览完全相符</template>
            <template v-else>对账发现差异：{{ task.verify.mismatches.join('；') }}</template>
          </p>
          <ul class="mig-counts">
            <li>文档迁出 {{ task.preview.doc_ids.length }} 篇</li>
            <li>内容块 {{ task.preview.counts.chunks?.moved ?? '—' }} 个</li>
            <li>检索索引 {{ task.preview.counts.vectors?.moved ?? '—' }} 个向量点</li>
            <li>文件目录 {{ task.preview.counts.files?.doc_dirs ?? '—' }} 个</li>
            <li>
              图谱 {{ task.preview.counts.graph?.entities ?? '—' }} 实体 /
              {{ task.preview.counts.graph?.relations ?? '—' }} 关系
            </li>
          </ul>
        </template>

        <!-- 按钮组（spec §5.8 状态表） -->
        <div class="mig-actions">
          <template v-if="task.status === 'running' || task.status === 'cancelling'">
            <a-button danger :disabled="task.status === 'cancelling'" @click="askCancel">
              {{ task.status === 'cancelling' ? '取消中…' : '取消' }}
            </a-button>
          </template>
          <template v-else-if="task.status === 'interrupted'">
            <a-button type="primary" @click="doResume">继续完成</a-button>
            <a-button danger @click="doFullRollback">全部回滚</a-button>
          </template>
          <template v-else-if="task.status === 'failed' || task.status === 'cancel_failed'">
            <a-button type="primary" @click="doResume">重试（从失败点续跑）</a-button>
            <a-button danger @click="doFullRollback">全部回滚</a-button>
          </template>
          <template v-else-if="task.status === 'completed'">
            <a-button :disabled="rollbackPastDeadline" @click="askRollback">回滚</a-button>
            <span v-if="rollbackPastDeadline" class="mig-deadline-note">
              已过 7 天回滚窗口，如需合并回去请使用普通合并
            </span>
          </template>
          <a-button @click="showAudit = !showAudit">{{ showAudit ? '收起审计' : '查看审计' }}</a-button>
        </div>

        <!-- 审计 -->
        <div v-if="showAudit" class="mig-audit">
          <a-spin :spinning="auditLoading">
            <a-table
              :data-source="auditRows"
              :columns="auditColumns"
              size="small"
              :pagination="false"
              row-key="at"
            />
          </a-spin>
        </div>

        <!-- 步骤流水 -->
        <a-collapse v-if="task.steps?.length" class="mig-steps">
          <a-collapse-panel key="steps" :header="`执行流水（${task.steps.length} 条）`">
            <div v-for="(s, i) in [...task.steps].reverse()" :key="i" class="mig-step">
              <span class="mig-step-at">{{ s.at }}</span>
              <span>[{{ s.stage }}] {{ s.step }} — {{ s.status }}</span>
            </div>
          </a-collapse-panel>
        </a-collapse>
      </template>
      <a-empty v-else-if="!loading" description="任务不存在或已被清理" />
    </a-spin>
  </a-drawer>
</template>

<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { Modal, message } from 'ant-design-vue'
import { knowledgeApi, type MigrationTask } from '@/api/knowledge'

const props = defineProps<{
  open: boolean
  taskId: string
}>()

const emit = defineEmits<{
  (e: 'update:open', v: boolean): void
  (e: 'close'): void
}>()

const task = ref<MigrationTask | null>(null)
const loading = ref(false)
const showAudit = ref(false)
const auditLoading = ref(false)
const auditRows = ref<any[]>([])

let pollTimer: number | null = null
let pollFailCount = 0

const TERMINAL = ['completed', 'failed', 'cancelled', 'cancel_failed', 'interrupted', 'switch_reload_failed']

const opLabels: Record<string, string> = {
  split: '拆分', merge: '合并', rollback: '回滚',
}
const opLabel = computed(() => opLabels[task.value?.op || ''] || task.value?.op || '')

/** 拆分目的地是否为新建库（切换阶段语义与回滚文案据此分叉） */
const isSplitToNew = computed(() => {
  const p = task.value?.params || {}
  return task.value?.op === 'split' && !!p.new_library_id
})

const destinationLine = computed(() => {
  const t = task.value
  if (!t) return '—'
  const p = t.params || {}
  if (t.op === 'rollback') return p.original_source_library_id || '—'
  if (t.op === 'split') {
    return p.new_library_id ? `新库「${p.new_name || p.new_library_id}」` : (p.target_library_id || '—')
  }
  return p.target_library_id || '—'
})

const statusLabels: Record<string, string> = {
  running: '进行中', cancelling: '取消中', completed: '已完成', failed: '失败',
  cancelled: '已取消', cancel_failed: '取消未完成', interrupted: '已中断',
  switch_reload_failed: '待服务刷新',
}
const statusLabel = computed(() => statusLabels[task.value?.status || ''] || task.value?.status || '')
const statusColor = computed(() => {
  const s = task.value?.status
  if (s === 'completed') return 'green'
  if (s === 'running' || s === 'cancelling') return 'processing'
  if (s === 'switch_reload_failed') return 'orange'
  if (s) return 'red'
  return 'default'
})

const stageNames: Record<string, string> = {
  preview: '预览', execute: '逐篇迁移', verify: '对账', switch: '切换新库', rollback: '回滚补偿',
}
const stageFlow = computed(() => {
  const t = task.value
  if (!t) return []
  const seq = t.op === 'rollback' ? ['rollback'] : ['preview', 'execute', 'verify', 'switch']
  const curIdx = seq.indexOf(t.stage)
  const failed = ['failed', 'cancel_failed', 'interrupted', 'switch_reload_failed'].includes(t.status)
  return seq.map((key, i) => ({
    key,
    // 并入已有库没有「新建库」这一步：切换阶段 = 放行两端门禁
    label: key === 'switch' && t.op === 'split' && !isSplitToNew.value
      ? '收尾放行' : (stageNames[key] || key),
    state:
      t.status === 'completed' || i < curIdx ? 'done'
        : i === curIdx ? (failed ? 'failed' : 'active')
          : '',
  }))
})

const rollbackPastDeadline = computed(() => {
  const d = task.value?.rollback_deadline
  if (!d) return false
  return new Date(d).getTime() < Date.now()
})

const deadlineLine = computed(() => {
  const d = task.value?.rollback_deadline
  if (!d) return '—'
  return rollbackPastDeadline.value ? `${d}（已过期）` : `${d} 前可一键回滚`
})

const auditColumns = [
  { title: '时间', dataIndex: 'at', key: 'at', width: 170 },
  { title: '动作', dataIndex: 'action', key: 'action', width: 80 },
  { title: '操作人', dataIndex: 'operator', key: 'operator', width: 90 },
  { title: '结果', dataIndex: 'result', key: 'result', width: 70 },
  { title: '备注', dataIndex: 'error', key: 'error' },
]

watch(
  () => [props.open, props.taskId] as const,
  ([open, id]) => {
    if (open && id) {
      void fetchOnce()
      startPolling()
    } else {
      stopPolling()
      task.value = null
      showAudit.value = false
    }
  },
)

onBeforeUnmount(stopPolling)
onMounted(() => {
  if (props.open && props.taskId) {
    void fetchOnce()
    startPolling()
  }
})

async function fetchOnce() {
  if (!props.taskId) return
  loading.value = true
  try {
    task.value = await knowledgeApi.getMigration(props.taskId)
    pollFailCount = 0
  } catch (e: any) {
    pollFailCount += 1
    // 瞬时失败不中断轮询；连续 5 次才停（克隆 useKnowledgeParse 容错口径）
    if (pollFailCount >= 5) {
      stopPolling()
      message.error('任务状态读取失败：' + (e.message || e))
    }
  } finally {
    loading.value = false
  }
}

function startPolling() {
  stopPolling()
  pollTimer = window.setInterval(() => {
    const s = task.value?.status
    if (!props.open || !props.taskId) return
    if (s && TERMINAL.includes(s)) {
      stopPolling()
      return
    }
    void fetchOnce()
  }, 2000)
}

function stopPolling() {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}

async function callApi(fn: () => Promise<{ message?: string }>) {
  try {
    const resp = await fn()
    message.success(resp.message || '操作已提交')
    pollFailCount = 0
    await fetchOnce()
    startPolling()
  } catch (e: any) {
    message.error(e.message || '操作失败')
  }
}

function askCancel() {
  Modal.confirm({
    title: '取消这次迁移？',
    content: `已迁移的 ${task.value?.progress_done ?? 0} 篇会自动撤回原库，库内容回到迁移前。`,
    okText: '取消迁移',
    okButtonProps: { danger: true },
    onOk: () => callApi(() => knowledgeApi.cancelMigration(props.taskId)),
  })
}

function doResume() {
  void callApi(() => knowledgeApi.resumeMigration(props.taskId))
}

function doFullRollback() {
  Modal.confirm({
    title: '全部回滚？',
    content: '已迁移的文档会全部撤回原库，库内容回到迁移前。',
    okText: '全部回滚',
    okButtonProps: { danger: true },
    onOk: () => callApi(() => knowledgeApi.cancelMigration(props.taskId)),
  })
}

function askRollback() {
  const toExisting = task.value?.op === 'split' && !isSplitToNew.value
  Modal.confirm({
    title: '把这次迁移整体撤回？',
    content: toExisting
      ? '迁出的文档将全部撤回原库（目标库自有文档不动），目标库不会被停用。'
      : '迁移到新库的文档将全部撤回原库；拆分回滚时，新库期间新增的文档也会一并撤回。',
    okText: '回滚',
    okButtonProps: { danger: true },
    onOk: () => callApi(() => knowledgeApi.rollbackMigration(props.taskId)),
  })
}

watch(showAudit, (v) => {
  if (v && auditRows.value.length === 0) void loadAudit()
})

async function loadAudit() {
  auditLoading.value = true
  try {
    const resp = await knowledgeApi.getMigrationAudit({ limit: 500 })
    const digest = task.value?.preview?.digest || ''
    const id = props.taskId
    auditRows.value = resp.entries.filter(
      (e: any) =>
        (digest && e.preview_digest === digest) ||
        JSON.stringify(e.params || {}).includes(id),
    )
  } catch (e: any) {
    message.error('审计读取失败：' + (e.message || e))
  } finally {
    auditLoading.value = false
  }
}
</script>

<style scoped>
.mig-stages {
  display: flex;
  gap: 8px;
  margin: 16px 0 8px;
}
.mig-stage {
  flex: 1;
  text-align: center;
  padding: 6px 0;
  border-radius: 4px;
  background: var(--bg-secondary, #f5f5f5);
  color: var(--text-secondary, rgba(0, 0, 0, 0.45));
}
.mig-stage.active {
  background: var(--primary-color, #1677ff);
  color: #fff;
}
.mig-stage.done {
  background: #f6ffed;
  color: #389e0d;
  border: 1px solid #b7eb8f;
}
.mig-stage.failed {
  background: #fff2f0;
  color: #cf1322;
  border: 1px solid #ffccc7;
}
.mig-stage-msg {
  color: var(--text-secondary, rgba(0, 0, 0, 0.65));
}
.mig-progress {
  margin-bottom: 4px;
  font-weight: 600;
}
.mig-error {
  margin: 12px 0;
}
.mig-h {
  margin: 16px 0 4px;
}
.mig-verify.bad {
  color: #cf1322;
}
.mig-counts {
  margin: 0 0 8px;
  padding-left: 20px;
}
.mig-actions {
  display: flex;
  gap: 8px;
  margin: 16px 0;
  align-items: center;
}
.mig-deadline-note {
  color: var(--text-secondary, rgba(0, 0, 0, 0.45));
}
.mig-audit {
  margin-bottom: 12px;
}
.mig-steps {
  margin-bottom: 12px;
}
.mig-step {
  font-size: 12px;
  line-height: 1.8;
}
.mig-step-at {
  color: var(--text-tertiary, rgba(0, 0, 0, 0.45));
  margin-right: 8px;
}
</style>
