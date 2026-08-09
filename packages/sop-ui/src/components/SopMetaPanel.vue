/**
 * SOP 元数据属性面板组件，编辑 SOP 名称、描述，展示统计信息。
 */
<template>
  <div class="sop-meta-panel">
    <div class="panel-scroll">
      <div class="top-bar">
        <div class="step-meta">
          <span class="meta-label">SOP ID</span>
          <span class="meta-id">{{ sopData.id }}</span>
        </div>
        <div class="top-bar-actions">
          <span v-if="readOnly" class="mode-badge">只读</span>
          <template v-else-if="hasChanges">
            <a-button size="small" @click="handleCancel">取消</a-button>
            <a-button size="small" type="primary" :disabled="isNameDuplicate" @click="handleSave">保存</a-button>
          </template>
        </div>
      </div>

      <section class="section-block">
        <div class="section-header">
          <span class="section-title">名称</span>
        </div>
        <a-input
          v-model:value="draftName"
          size="small"
          class="name-input"
          placeholder="SOP 名称"
          :disabled="readOnly"
          :status="isNameDuplicate ? 'error' : undefined"
        />
        <div v-if="isNameDuplicate" class="field-error">名称已存在，请修改</div>
      </section>

      <section class="section-block">
        <div class="section-header">
          <span class="section-title">描述</span>
        </div>
        <a-textarea
          v-model:value="draftDescription"
          size="small"
          class="description-input"
          placeholder="SOP 描述"
          :disabled="readOnly"
          :auto-size="{ minRows: 2, maxRows: 6 }"
        />
      </section>

      <section class="section-block">
        <div class="section-header">
          <span class="section-title">统计信息</span>
        </div>
        <div class="stat-grid">
          <div class="stat-item">
            <span class="stat-label">步骤数</span>
            <span class="stat-value">{{ stepCount }}</span>
          </div>
        </div>

        <div v-if="toolDistribution.length" class="stat-section">
          <div class="stat-subtitle">工具分布</div>
          <div class="stat-tags">
            <a-tag v-for="item in toolDistribution" :key="item.tool" class="stat-tag">
              {{ item.label }} ×{{ item.count }}
            </a-tag>
          </div>
        </div>

        <div class="stat-section">
          <div class="stat-subtitle">审核状态</div>
          <div class="review-status-row">
            <a-tag :color="statusTagColor" size="small">{{ statusText }}</a-tag>
            <span v-if="sopData.stats?.runs" class="stat-value review-stats">
              运行 {{ sopData.stats.runs }} 次 · 成功 {{ sopData.stats.success || 0 }} 次 · 成功率 {{ successRate }}%
            </span>
          </div>
          <div v-if="isUnhealthy" class="review-warning">
            成功率低于 50%（≥10 次），建议复核该 SOP
          </div>
        </div>

        <div v-if="citedDocuments.length" class="stat-section">
          <div class="stat-subtitle">引用知识文档</div>
          <div class="stat-tags">
            <a-tag v-for="doc in citedDocuments" :key="doc" class="stat-tag">
              {{ doc }}
            </a-tag>
          </div>
        </div>
        <div v-else class="stat-empty">暂无引用知识文档</div>
      </section>

      <section class="section-block review-block">
        <div class="section-header">
          <span class="section-title">审核操作</span>
        </div>
        <a-input
          v-model:value="reviewReviewer"
          size="small"
          class="review-input"
          placeholder="审核人（可选）"
        />
        <a-textarea
          v-model:value="reviewNote"
          size="small"
          class="review-note"
          placeholder="审核意见（可选）"
          :auto-size="{ minRows: 2, maxRows: 4 }"
        />
        <div class="review-actions">
          <a-button size="small" type="primary" :loading="reviewing" @click="doReview('approve')">
            通过并发布
          </a-button>
          <a-button size="small" :loading="reviewing" @click="doReview('reject')">驳回</a-button>
          <a-button size="small" danger :loading="reviewing" @click="doReview('disable')">禁用</a-button>
        </div>

        <div v-if="auditItems.length" class="audit-block">
          <div class="audit-subtitle">审计时间线</div>
          <div v-for="item in auditItems" :key="item.at + item.action" class="audit-item">
            <div class="audit-head">
              <span class="audit-action">{{ auditActionText(item.action) }}</span>
              <span class="audit-meta">
                {{ formatAuditTime(item.at) }}{{ item.reviewer ? ' · ' + item.reviewer : '' }}
              </span>
            </div>
            <div v-if="item.note" class="audit-note">{{ item.note }}</div>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { App } from 'ant-design-vue'
import { sopApi } from '../composables/useSopApi'
import type { SopAuditEntry, SopData, SopStatus } from '../types/sop'

const { message } = App.useApp()

const TOOL_LABEL_MAP: Record<string, string> = {
  manual: '手动',
  calculator: '计算器',
  table_lookup: '表格查询',
  auto: '自动',
  sop_run: 'SOP 执行',
  llm_call: 'LLM 调用',
}

const props = defineProps<{
  sopData: SopData
  allSopNames: string[]
  readOnly?: boolean
}>()

const emit = defineEmits<{
  save: [payload: { name_zh: string; description: string }]
  cancel: []
  'dirty-change': [dirty: boolean]
  reviewed: [sopId: string]
}>()

const draftName = ref('')
const draftDescription = ref('')
const lastSavedName = ref('')
const lastSavedDescription = ref('')
const reviewNote = ref('')
const reviewReviewer = ref('')
const reviewing = ref(false)
const auditItems = ref<SopAuditEntry[]>([])

/**
 * 判断当前名称是否与其他 SOP 重复。
 */
const isNameDuplicate = computed(() => {
  const trimmed = draftName.value.trim()
  if (!trimmed) return false
  if (trimmed === lastSavedName.value) return false
  return props.allSopNames.some((name) => name === trimmed)
})

/**
 * 判断草稿是否有改动。
 */
const hasChanges = computed(() => {
  return draftName.value.trim() !== lastSavedName.value || draftDescription.value.trim() !== lastSavedDescription.value
})

/**
 * 步骤总数。
 */
const stepCount = computed(() => props.sopData.steps.length)

/**
 * 按工具类型分组统计。
 */
const toolDistribution = computed(() => {
  const counter = new Map<string, number>()
  for (const step of props.sopData.steps) {
    const tool = step.execution?.tool || 'manual'
    counter.set(tool, (counter.get(tool) || 0) + 1)
  }
  return Array.from(counter.entries())
    .map(([tool, count]) => ({ tool, label: TOOL_LABEL_MAP[tool] || tool, count }))
    .sort((a, b) => b.count - a.count)
})

/**
 * 聚合所有步骤描述中引用的知识文档，去重。
 */
const citedDocuments = computed(() => {
  const docSet = new Set<string>()
  for (const step of props.sopData.steps) {
    const citations = step.description?.citations
    if (!Array.isArray(citations)) continue
    for (const citation of citations) {
      const label = citation.reference?.docTitle || citation.reference?.docId || citation.label
      if (label) docSet.add(label)
    }
  }
  return Array.from(docSet)
})

const STATUS_TEXT_MAP: Record<SopStatus, string> = {
  draft: '待审核',
  reviewed: '已复核',
  published: '已发布',
  disabled: '已禁用',
}

const STATUS_COLOR_MAP: Record<SopStatus, string> = {
  draft: 'warning',
  reviewed: 'processing',
  published: 'success',
  disabled: 'default',
}

const statusText = computed(() => STATUS_TEXT_MAP[props.sopData.status || 'draft'])
const statusTagColor = computed(() => STATUS_COLOR_MAP[props.sopData.status || 'draft'])

const successRate = computed(() => {
  const stats = props.sopData.stats
  const runs = Number(stats?.runs || 0)
  if (!runs) return 0
  return Math.round((Number(stats?.success || 0) / runs) * 100)
})

const isUnhealthy = computed(() => {
  const stats = props.sopData.stats
  return Number(stats?.runs || 0) >= 10 && Number(stats?.success || 0) / Number(stats?.runs || 1) < 0.5
})

const AUDIT_ACTION_TEXT_MAP: Record<string, string> = {
  approve: '通过',
  reject: '驳回',
  disable: '禁用',
}

const auditActionText = (action: string) => AUDIT_ACTION_TEXT_MAP[action] || action

const formatAuditTime = (iso: string) => {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

const loadAudit = async () => {
  try {
    const result = await sopApi.getSopAudit(props.sopData.id)
    auditItems.value = result.audit || []
  } catch (error) {
    auditItems.value = []
  }
}

const doReview = async (action: 'approve' | 'reject' | 'disable') => {
  reviewing.value = true
  try {
    await sopApi.reviewSop(
      props.sopData.id,
      action,
      reviewNote.value.trim(),
      reviewReviewer.value.trim(),
    )
    message.success('审核操作成功')
    reviewNote.value = ''
    emit('reviewed', props.sopData.id)
    await loadAudit()
  } catch (error: any) {
    message.error(error?.message || '审核操作失败')
  } finally {
    reviewing.value = false
  }
}

/**
 * 同步外部数据为本地草稿。
 */
const syncDraft = (data: SopData) => {
  draftName.value = data.name_zh || ''
  draftDescription.value = data.description || ''
  lastSavedName.value = draftName.value.trim()
  lastSavedDescription.value = draftDescription.value.trim()
}

/**
 * 取消编辑，还原为上次保存值。
 */
const handleCancel = () => {
  draftName.value = lastSavedName.value
  draftDescription.value = lastSavedDescription.value
  emit('cancel')
}

/**
 * 保存元数据。
 */
const handleSave = () => {
  if (isNameDuplicate.value) return
  const trimmedName = draftName.value.trim()
  if (!trimmedName) return
  emit('save', {
    name_zh: trimmedName,
    description: draftDescription.value.trim(),
  })
  lastSavedName.value = trimmedName
  lastSavedDescription.value = draftDescription.value.trim()
}

/**
 * 外部接受草稿（如画布统一保存时），更新签名使面板不再显示为脏。
 */
const acceptDraft = () => {
  lastSavedName.value = draftName.value.trim()
  lastSavedDescription.value = draftDescription.value.trim()
}

watch(hasChanges, (val) => {
  emit('dirty-change', val)
})

watch(() => props.sopData, (data) => {
  syncDraft(data)
}, { immediate: true, deep: true })

watch(() => props.sopData.id, loadAudit, { immediate: true })

defineExpose({ hasChanges, draftName, draftDescription, acceptDraft })
</script>

<style lang="less" scoped>
.sop-meta-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: var(--bg-primary);
}

.panel-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.top-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.step-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.meta-label {
  color: var(--text-secondary);
}

.meta-id {
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--bg-tertiary);
  color: var(--text-primary);
  font-family: Consolas, monospace;
}

.mode-badge {
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 12px;
  color: var(--text-secondary);
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
}

.top-bar-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.section-block {
  border: 1px solid var(--border-color);
  border-radius: 10px;
  background: var(--panel-bg);
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.name-input,
.description-input {
  :deep(.ant-input),
  :deep(.ant-input-affix-wrapper) {
    border-radius: 8px;
  }
}

.field-error {
  font-size: 12px;
  color: #ff4d4f;
  line-height: 1.4;
}

.stat-grid {
  display: flex;
  gap: 16px;
}

.stat-item {
  display: flex;
  align-items: center;
  gap: 6px;
}

.stat-label {
  font-size: 12px;
  color: var(--text-secondary);
}

.stat-value {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.stat-section {
  margin-top: 4px;
}

.stat-subtitle {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 6px;
}

.stat-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.stat-tag {
  font-size: 11px;
  border-radius: 6px;
}

.stat-empty {
  color: var(--text-secondary);
  font-size: 12px;
  margin-top: 4px;
}

.review-status-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.review-stats {
  font-size: 12px;
  font-weight: 400;
}

.review-warning {
  margin-top: 6px;
  padding: 6px 8px;
  border-radius: 6px;
  background: rgba(250, 173, 20, 0.12);
  color: #d48806;
  font-size: 12px;
  line-height: 1.5;
}

.review-block {
  gap: 8px;
}

.review-note {
  :deep(.ant-input) {
    border-radius: 8px;
  }
}

.review-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.audit-block {
  border-top: 1px dashed var(--border-color);
  padding-top: 8px;
  margin-top: 4px;
}

.audit-subtitle {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 6px;
}

.audit-item {
  padding: 6px 0;
  border-bottom: 1px solid var(--border-color);
}

.audit-item:last-child {
  border-bottom: none;
}

.audit-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.audit-action {
  font-size: 12px;
  font-weight: 600;
  color: var(--primary-color);
}

.audit-meta {
  font-size: 11px;
  color: var(--text-secondary);
}

.audit-note {
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-primary);
  line-height: 1.5;
}
</style>
