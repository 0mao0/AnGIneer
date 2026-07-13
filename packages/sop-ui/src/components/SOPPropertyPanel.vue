/**
 * SOP 步骤属性面板组件，使用更高信息密度的布局编辑当前步骤。
 */
<template>
  <div class="sop-property-panel">
    <div class="panel-scroll">
      <div class="top-bar">
        <div class="step-meta">
          <span class="meta-label">步骤 ID</span>
          <span class="meta-id">{{ draft.id }}</span>
        </div>
        <div class="top-bar-actions">
          <span v-if="readOnly" class="mode-badge">只读</span>
          <template v-if="!readOnly && hasChanges">
            <a-button size="small" @click="handleCancel">取消</a-button>
            <a-button size="small" type="primary" @click="handleSave">保存</a-button>
          </template>
        </div>
      </div>

      <a-input
        v-model:value="draft.name"
        size="small"
        class="name-input"
        placeholder="步骤名称"
        :disabled="readOnly"
      />

      <section class="section-block">
        <div class="section-header">
          <span class="section-title">描述</span>
          <a-button
            v-if="!readOnly"
            size="small"
            type="default"
            :loading="parsingAi"
            @click="handleAiParse"
          >
            AI 解析
          </a-button>
        </div>
        <InlineCitationEditor
          v-model="draft.description"
          class="description-input"
          placeholder="步骤描述，备注内容也合并填写在这里"
          :disabled="readOnly"
          :search-citations="searchCitations"
          @select-citation="emit('selectCitation', $event)"
        />
      </section>

      <section class="section-block">
        <div class="section-header compact execution-header" @click="toggleExecutionExpanded">
          <button
            type="button"
            class="section-toggle"
            :aria-expanded="executionExpanded"
            @click.stop="toggleExecutionExpanded"
          >
            <CaretRightOutlined class="section-toggle-icon" :class="{ expanded: executionExpanded }" />
            <span class="section-title">执行定义</span>
          </button>
          <a-select
            v-if="draft.execution.tool === 'conditional'"
            v-model:value="draft.execution.tool"
            size="small"
            class="header-tool-select"
            :disabled="readOnly"
          >
            <a-select-option
              v-for="option in toolOptions"
              :key="option.value"
              :value="option.value"
            >
              {{ option.label }}
            </a-select-option>
          </a-select>
        </div>

        <div v-show="executionExpanded" class="execution-body">
          <div v-if="draft.execution.tool !== 'conditional'" class="tool-row">
            <span class="mini-label">工具</span>
            <a-select
              v-model:value="draft.execution.tool"
              size="small"
              class="tool-select"
              :disabled="readOnly"
            >
              <a-select-option
                v-for="option in toolOptions"
                :key="option.value"
                :value="option.value"
              >
                {{ option.label }}
              </a-select-option>
            </a-select>
          </div>

          <template v-if="draft.execution.tool !== 'conditional'">
          <div class="kv-table">
            <div class="kv-section-header">
              <span>输入参数</span>
              <a-button v-if="!readOnly" type="text" size="small" @click="addInputRow">
                <template #icon><PlusOutlined /></template>
              </a-button>
            </div>
            <div class="kv-header-row">
              <span>键</span>
              <span>值</span>
              <span />
            </div>
            <div v-if="!inputRows.length" class="kv-empty">暂无输入参数</div>
            <div v-for="(row, index) in inputRows" :key="`input-${index}`" class="kv-row">
              <a-input
                v-model:value="row.key"
                size="small"
                class="kv-key"
                placeholder="参数名"
                :disabled="readOnly"
              />
              <a-input
                v-model:value="row.value"
                size="small"
                class="kv-value"
                placeholder="参数值"
                :disabled="readOnly"
              />
              <a-button v-if="!readOnly" type="text" size="small" danger @click="removeInputRow(index)">
                <template #icon><DeleteOutlined /></template>
              </a-button>
            </div>
          </div>

          <div class="kv-table">
            <div class="kv-section-header">
              <span>输出</span>
              <a-button v-if="!readOnly" type="text" size="small" @click="addOutputRow">
                <template #icon><PlusOutlined /></template>
              </a-button>
            </div>
            <div class="kv-header-row">
              <span>键</span>
              <span>值</span>
              <span />
            </div>
            <div v-if="!outputRows.length" class="kv-empty">暂无输出</div>
            <div v-for="(row, index) in outputRows" :key="`output-${index}`" class="kv-row">
              <a-input
                v-model:value="row.key"
                size="small"
                class="kv-key"
                placeholder="输出名"
                :disabled="readOnly"
              />
              <a-input
                v-model:value="row.value"
                size="small"
                class="kv-value"
                placeholder="输出值"
                :disabled="readOnly"
              />
              <a-button v-if="!readOnly" type="text" size="small" danger @click="removeOutputRow(index)">
                <template #icon><DeleteOutlined /></template>
              </a-button>
            </div>
          </div>
          </template>

          <template v-else>
          <div class="fork-field">
            <span class="mini-label">条件变量</span>
            <div class="var-input-wrap">
              <span class="var-prefix">$</span>
              <a-input
                v-model:value="forkConditionVar"
                size="small"
                placeholder="变量名"
                :disabled="readOnly"
              />
            </div>
          </div>

          <div class="fork-field">
            <div class="kv-section-header">
              <span>分支列表</span>
              <a-button v-if="!readOnly" type="text" size="small" @click="forkBranches.push({ match: '', goto: '' })">
                <template #icon><PlusOutlined /></template>
              </a-button>
            </div>
            <div v-if="!forkBranches.length" class="kv-empty">暂无分支</div>
            <div v-for="(branch, idx) in forkBranches" :key="idx" class="branch-card">
              <div class="branch-card-row">
                <a-input
                  v-model:value="branch.match"
                  size="small"
                  placeholder="匹配条件，例如: 上水标准"
                  :disabled="readOnly"
                />
                <a-button v-if="!readOnly" type="text" size="small" danger @click="forkBranches.splice(idx, 1)">
                  <template #icon><DeleteOutlined /></template>
                </a-button>
              </div>
              <div class="branch-card-row">
                <span class="mini-label">跳转</span>
                <a-select
                  v-model:value="branch.goto"
                  size="small"
                  placeholder="目标步骤"
                  :disabled="readOnly"
                  allow-clear
                  show-search
                  :filter-option="(input: string, option: any) => {
                    const label = option.label || ''
                    return label.toLowerCase().includes(input.toLowerCase())
                  }"
                >
                  <a-select-option
                    v-for="target in stepTargets"
                    :key="target.id"
                    :value="target.id"
                    :label="target.name || target.id"
                  >
                    {{ target.name || target.id }}
                  </a-select-option>
                </a-select>
              </div>
            </div>
          </div>

          <div class="fork-field">
            <span class="mini-label">默认跳转</span>
            <a-select
              v-model:value="forkDefaultGoto"
              size="small"
              placeholder="无匹配时的目标步骤（可选）"
              :disabled="readOnly"
              allow-clear
              show-search
              :filter-option="(input: string, option: any) => {
                const label = option.label || ''
                return label.toLowerCase().includes(input.toLowerCase())
              }"
            >
              <a-select-option
                v-for="target in stepTargets"
                :key="target.id"
                :value="target.id"
                :label="target.name || target.id"
              >
                {{ target.name || target.id }}
              </a-select-option>
            </a-select>
          </div>
          </template>
        </div>
      </section>

      <!-- 失败跳转（只读，由画布失败边控制） -->
      <section v-if="failureTargetName" class="section-block failure-section">
        <div class="section-header">
          <span class="section-title">⚠ 失败跳转</span>
        </div>
        <div class="failure-info">
          <span class="failure-label">目标步骤</span>
          <a-tag color="red">{{ failureTargetName }}</a-tag>
        </div>
      </section>

      <!-- 知识图谱标注：原则 / 反例 / 案例 -->
      <section v-if="step.principles?.length" class="section-block enrichment-section">
        <div class="section-header">
          <span class="section-title">✅ 原则 ({{ step.principles.length }})</span>
        </div>
        <div v-for="p in step.principles" :key="p.principle_id" class="enrich-item">
          <a-tag color="green" class="enrich-cat">{{ categoryLabel(p.category) }}</a-tag>
          <span class="enrich-text">{{ p.principle_text }}</span>
          <span v-if="p.source_clause" class="enrich-source">{{ p.source_clause }}</span>
        </div>
      </section>
      <section v-if="step.warnings?.length" class="section-block enrichment-section">
        <div class="section-header">
          <span class="section-title">⚠️ 反例 ({{ step.warnings.length }})</span>
        </div>
        <div v-for="w in step.warnings" :key="w.warning_id" class="enrich-item">
          <a-tag :color="severityColor(w.severity)" class="enrich-cat">{{ w.severity }}</a-tag>
          <span class="enrich-text">{{ w.warning_text }}</span>
          <span v-if="w.source_section" class="enrich-source">{{ w.source_section }}</span>
        </div>
      </section>
      <section v-if="step.examples?.length" class="section-block enrichment-section">
        <div class="section-header">
          <span class="section-title">📋 案例 ({{ step.examples.length }})</span>
        </div>
        <a-collapse ghost expand-icon-position="right">
          <a-collapse-panel v-for="ex in step.examples" :key="ex.example_id" :header="ex.title">
            <div v-if="ex.inputs_json && ex.inputs_json !== '{}'" class="enrich-code">{{ ex.inputs_json }}</div>
            <div v-if="ex.computation_text" class="enrich-code">{{ ex.computation_text }}</div>
          </a-collapse-panel>
        </a-collapse>
      </section>
    </div>

    <a-modal
      :open="aiPreviewVisible"
      title="AI 解析预览"
      ok-text="写入"
      cancel-text="取消"
      @ok="applyAiSuggestion"
      @cancel="aiPreviewVisible = false"
    >
      <template v-if="aiSuggestion">
        <div class="preview-block">
          <div class="preview-title">建议工具</div>
          <div class="preview-value">{{ getToolLabel(aiSuggestion.tool) }}</div>
        </div>

        <div class="preview-block">
          <div class="preview-title">建议输入</div>
          <div v-if="!aiInputPreview.length" class="preview-empty">未识别到输入参数</div>
          <div v-for="(row, index) in aiInputPreview" :key="`preview-input-${index}`" class="preview-row">
            <span>{{ row.key }}</span>
            <span>{{ row.value || '-' }}</span>
          </div>
        </div>

        <div class="preview-block">
          <div class="preview-title">建议输出</div>
          <div v-if="!aiOutputPreview.length" class="preview-empty">未识别到输出参数</div>
          <div v-for="(row, index) in aiOutputPreview" :key="`preview-output-${index}`" class="preview-row">
            <span>{{ row.key }}</span>
            <span>{{ row.value || '-' }}</span>
          </div>
        </div>
      </template>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { CaretRightOutlined, DeleteOutlined, PlusOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import { InlineCitationEditor } from '@angineer/ui-kit'
import type { CitationBinding, InlineCitationCandidate, InlineCitationSearchPayload } from '@angineer/ui-kit'
import { mapReferenceSearchCandidate } from '@angineer/ui-kit/utils/citation'
import { sopApi } from '../composables/useSopApi'
import type { SopStep } from '../types/sop'

interface KvRow {
  key: string
  value: string
}

interface AiSuggestion {
  tool: string
  inputs: Record<string, string>
  outputs: Record<string, string>
}

const toolOptions = [
  { value: 'manual', label: '手动' },
  { value: 'calculator', label: '计算器' },
  { value: 'table_lookup', label: '表格查询' },
  { value: 'auto', label: '自动' },
  { value: 'sop_run', label: 'SOP 执行' },
  { value: 'llm_call', label: 'LLM 调用' },
  { value: 'conditional', label: '条件分支' },
]

interface StepTarget {
  id: string
  name?: string
}

const props = defineProps<{
  step: SopStep
  readOnly?: boolean
  stepTargets?: StepTarget[]
  failureTargetName?: string
}>()

const emit = defineEmits<{
  save: [step: SopStep]
  cancel: []
  selectCitation: [binding: CitationBinding]
  'dirty-change': [dirty: boolean]
}>()

const draft = ref<SopStep>({
  id: '',
  name: '',
  description: { content: '', citations: [] },
  execution: {
    tool: 'manual',
    inputs: {},
    outputs: {},
  },
})
const inputRows = ref<KvRow[]>([])
const outputRows = ref<KvRow[]>([])
const lastLoadedSignature = ref('')
const parsingAi = ref(false)
const aiPreviewVisible = ref(false)
const aiSuggestion = ref<AiSuggestion | null>(null)
const executionExpanded = ref(false)
const forkConditionVar = ref('')
const forkBranches = ref<Array<{ match: string; goto: string }>>([])
const forkDefaultGoto = ref('')

/**
 * 将对象映射为可编辑键值对列表。
 */
const toRows = (record: Record<string, any> | undefined): KvRow[] => {
  return Object.entries(record || {}).map(([key, value]) => ({
    key,
    value: String(value ?? ''),
  }))
}

/**
 * 将键值对列表整理回对象，自动忽略空 key。
 */
const toRecord = (rows: KvRow[]): Record<string, string> => {
  return rows.reduce<Record<string, string>>((result, row) => {
    const key = row.key.trim()
    if (!key) {
      return result
    }
    result[key] = row.value.trim()
    return result
  }, {})
}

/**
 * 生成当前草稿对应的完整步骤对象。
 */
const buildDraftStep = (): SopStep => {
  const { ui_meta: _ui_meta, ...rest } = draft.value as any
  const base: SopStep = {
    ...rest,
    execution: {
      tool: draft.value.execution.tool,
      inputs: toRecord(inputRows.value),
      outputs: toRecord(outputRows.value),
    },
  }
  if (draft.value.execution.tool === 'conditional') {
    base.condition_var = forkConditionVar.value || undefined
    base.branches = forkBranches.value.filter((b) => b.match)
    base.default_goto = forkDefaultGoto.value || undefined
  } else {
    base.condition_var = undefined
    base.branches = undefined
    base.default_goto = undefined
  }
  return base
}

/**
 * 生成可比较的草稿签名。
 */
const getStepSignature = (step: SopStep): string => {
  return JSON.stringify({
    id: step.id,
    name: step.name || '',
    description: step.description,
    tool: step.execution.tool || 'manual',
    inputs: Object.entries(step.execution.inputs || {})
      .map(([key, value]) => [key.trim(), String(value ?? '').trim()])
      .filter(([key]) => key)
      .sort(([a], [b]) => a.localeCompare(b, 'zh-CN')),
    outputs: Object.entries(step.execution.outputs || {})
      .map(([key, value]) => [key.trim(), String(value ?? '').trim()])
      .filter(([key]) => key)
      .sort(([a], [b]) => a.localeCompare(b, 'zh-CN')),
    branches: (step.branches || []).map((b) => ({
      match: String(b.match || '').trim(),
      goto: b.goto || '',
    })),
    condition_var: (step.condition_var || '').trim(),
    default_goto: (step.default_goto || '').trim(),
  })
}

const searchCitations = async (query: string): Promise<InlineCitationCandidate[]> => {
  const payload: InlineCitationSearchPayload = {
    library_id: 'default',
    query,
    limit: 10,
    types: ['content', 'table', 'formula', 'figure'],
  }
  const response = await sopApi.searchKnowledgeReferences(payload)
  const items = Array.isArray(response?.items) ? response.items : []
  return items.map((item: any) => mapReferenceSearchCandidate(item, payload))
}

/**
 * 将外部步骤同步为本地草稿。
 */
const syncDraft = (step: SopStep) => {
  draft.value = {
    ...step,
    execution: {
      tool: step.execution?.tool || 'manual',
      inputs: { ...(step.execution?.inputs || {}) },
      outputs: { ...(step.execution?.outputs || {}) },
    },
  }
  inputRows.value = toRows(step.execution?.inputs)
  outputRows.value = toRows(step.execution?.outputs)
  if (step.execution?.tool === 'conditional') {
    forkConditionVar.value = step.condition_var
      || step.execution?.inputs?.condition_var
      || ''
    forkBranches.value = (step.branches || []).map((b) => ({
      match: String(b.match || ''),
      goto: b.goto || '',
    }))
    forkDefaultGoto.value = step.default_goto || ''
  } else {
    forkConditionVar.value = ''
    forkBranches.value = []
    forkDefaultGoto.value = ''
  }
  lastLoadedSignature.value = getStepSignature(buildDraftStep())
  aiPreviewVisible.value = false
  aiSuggestion.value = null
}

/**
 * 当前草稿是否有改动。
 */
const hasChanges = computed(() => {
  return getStepSignature(buildDraftStep()) !== lastLoadedSignature.value
})

/**
 * 预览用的 AI 输入行。
 */
const aiInputPreview = computed(() => toRows(aiSuggestion.value?.inputs))

/**
 * 预览用的 AI 输出行。
 */
const aiOutputPreview = computed(() => toRows(aiSuggestion.value?.outputs))

/**
 * 获取工具显示文案。
 */
const getToolLabel = (tool: string) => {
  return toolOptions.find((option) => option.value === tool)?.label || tool || '手动'
}

const categoryLabel = (cat: string) => {
  return { mandatory: '强制', recommended: '推荐', constraint: '限制', optional: '可选' }[cat] || cat
}

const severityColor = (sev: string) => {
  return { safety: 'red', economic: 'orange', quality: 'gold' }[sev] || 'default'
}

/**
 * 切换执行定义区块的展开状态。
 */
const toggleExecutionExpanded = () => {
  executionExpanded.value = !executionExpanded.value
}

/**
 * 添加输入参数行。
 */
const addInputRow = () => {
  inputRows.value.push({ key: '', value: '' })
}

/**
 * 删除输入参数行。
 */
const removeInputRow = (index: number) => {
  inputRows.value.splice(index, 1)
}

/**
 * 添加输出参数行。
 */
const addOutputRow = () => {
  outputRows.value.push({ key: '', value: '' })
}

/**
 * 删除输出参数行。
 */
const removeOutputRow = (index: number) => {
  outputRows.value.splice(index, 1)
}

/**
 * 调用后端解析描述中的工具、输入和输出。
 */
const handleAiParse = async () => {
  const description = draft.value.description?.content?.trim()
  if (!description) {
    message.warning('请先填写步骤描述')
    return
  }

  executionExpanded.value = true
  parsingAi.value = true
  try {
    aiSuggestion.value = await sopApi.parseStepDescription(description)
    aiPreviewVisible.value = true
  } catch (error: any) {
    message.error(error?.message || 'AI 解析失败')
  } finally {
    parsingAi.value = false
  }
}

/**
 * 将 AI 解析结果写回当前草稿。
 */
const applyAiSuggestion = () => {
  if (!aiSuggestion.value) {
    aiPreviewVisible.value = false
    return
  }
  draft.value.execution.tool = aiSuggestion.value.tool || 'manual'
  inputRows.value = toRows(aiSuggestion.value.inputs)
  outputRows.value = toRows(aiSuggestion.value.outputs)
  aiPreviewVisible.value = false
}

/**
 * 还原为最近一次载入的步骤值。
 */
const handleCancel = () => {
  syncDraft(props.step)
  emit('cancel')
}

/**
 * 提交当前草稿。
 */
const handleSave = () => {
  const nextStep = buildDraftStep()
  emit('save', nextStep)
  lastLoadedSignature.value = getStepSignature(nextStep)
}

/**
 * 外部接受草稿（如画布统一保存时），更新签名使面板不再显示为脏。
 */
const acceptDraft = () => {
  lastLoadedSignature.value = getStepSignature(buildDraftStep())
}

watch(hasChanges, (val) => {
  emit('dirty-change', val)
})

watch(() => props.step, (step) => {
  syncDraft(step)
  executionExpanded.value = false
}, { immediate: true })

defineExpose({ hasChanges, buildDraftStep, acceptDraft })
</script>

<style lang="less" scoped>
.sop-property-panel {
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
  color: var(--text-secondary, #8c8c8c);
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

.name-input,
.description-input {
  :deep(.ant-input) {
    border-radius: 8px;
  }
}

.section-block {
  border: 1px solid var(--border-color);
  border-radius: 10px;
  background: var(--panel-bg);
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;

  &.compact {
    margin-bottom: -2px;
  }
}

.execution-header {
  cursor: pointer;
  user-select: none;
}

.section-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0;
  border: none;
  background: transparent;
  color: inherit;
  cursor: pointer;
}

.section-toggle-icon {
  font-size: 12px;
  color: var(--text-secondary, #8c8c8c);
  transition: transform 0.2s ease, color 0.2s ease;

  &.expanded {
    transform: rotate(90deg);
    color: var(--primary-color, #1890ff);
  }
}

.section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.execution-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.tool-row {
  display: grid;
  grid-template-columns: 56px 1fr;
  gap: 8px;
  align-items: center;
}

.mini-label {
  font-size: 12px;
  color: var(--text-secondary, #8c8c8c);
}

.tool-select {
  width: 100%;
}

.kv-table {
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 8px;
  background: var(--bg-secondary);
}

.kv-section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
}

.kv-header-row,
.kv-row {
  display: grid;
  grid-template-columns: 1fr 1.2fr 28px;
  gap: 8px;
  align-items: center;
}

.kv-header-row {
  padding: 0 2px 6px;
  font-size: 11px;
  color: var(--text-secondary, #8c8c8c);
}

.kv-row + .kv-row {
  margin-top: 6px;
}

.kv-empty,
.preview-empty {
  color: var(--text-secondary, #8c8c8c);
  font-size: 12px;
  padding: 6px 0;
}

.preview-block + .preview-block {
  margin-top: 12px;
}

.preview-title {
  margin-bottom: 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
}

.preview-value {
  font-size: 13px;
  color: var(--text-primary);
}

.preview-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  padding: 4px 0;
  font-size: 12px;
  color: var(--text-secondary);
}

.failure-section {
  border-color: rgba(255, 77, 79, 0.35) !important;
  background: rgba(255, 77, 79, 0.04) !important;
}

.failure-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.failure-label {
  font-size: 12px;
  color: var(--text-secondary, #667085);
}

.fork-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.header-tool-select {
  margin-left: auto;
  width: 100px;
  flex-shrink: 0;
}

.branch-card {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  background: var(--bg-secondary, rgba(0, 0, 0, 0.02));
  border-radius: 4px;
}

.branch-card + .branch-card {
  margin-top: 6px;
}

.branch-card-row {
  display: flex;
  align-items: center;
  gap: 6px;

  &:first-child {
    flex-shrink: 0;
  }

  &:last-child {
    flex: 1;
    min-width: 0;
  }

  .mini-label {
    flex-shrink: 0;
  }

  :deep(.ant-select) {
    flex: 1;
    min-width: 0;
  }
}

.var-input-wrap {
  display: flex;
  align-items: stretch;

  .var-prefix {
    display: inline-flex;
    align-items: center;
    padding: 0 6px;
    font-size: 12px;
    color: var(--text-secondary);
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    border-right: 0;
    border-radius: 4px 0 0 4px;
    white-space: nowrap;
  }

  :deep(.ant-input) {
    border-radius: 0 4px 4px 0;
    height: 100%;
  }
}

.enrichment-section {
  margin-top: 12px;
}
.enrich-item {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 4px 0;
  font-size: 13px;
  line-height: 1.5;
  flex-wrap: wrap;
}
.enrich-cat {
  flex-shrink: 0;
  font-size: 11px;
}
.enrich-text {
  flex: 1;
  min-width: 0;
  color: var(--text-primary, #1e293b);
}
.enrich-source {
  font-size: 11px;
  color: var(--text-secondary, #64748b);
  flex-shrink: 0;
}
.enrich-code {
  background: var(--bg-secondary, #f8fafc);
  border: 1px solid var(--border-color, #e2e8f0);
  border-radius: 4px;
  padding: 8px;
  font-size: 12px;
  white-space: pre-wrap;
  margin: 4px 0;
}
</style>
