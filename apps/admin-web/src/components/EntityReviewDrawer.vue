<template>
  <a-drawer
    :open="open"
    title="实体审核"
    placement="right"
    :width="760"
    @close="emit('update:open', false)"
  >
    <div class="entity-review-drawer">
      <div class="entity-review-toolbar">
        <a-radio-group v-model:value="activeTab" size="small" @change="loadAllData">
          <a-radio-button value="pending">待审（{{ pendingCount }}）</a-radio-button>
          <a-radio-button value="approved">已入库（{{ approvedCount }}）</a-radio-button>
          <a-radio-button value="deleted">已删除（{{ deletedCount }}）</a-radio-button>
        </a-radio-group>
        <a-button size="small" :loading="loading" @click="loadAllData">刷新</a-button>
      </div>

      <div class="entity-review-filters">
        <span class="entity-review-filter-label">层级：</span>
        <a-radio-group v-model:value="layerFilter" size="small">
          <a-radio-button value="">全部</a-radio-button>
          <a-radio-button value="concept">概念</a-radio-button>
          <a-radio-button value="condition">条件</a-radio-button>
          <a-radio-button value="action">动作</a-radio-button>
        </a-radio-group>
      </div>

      <a-typography-text type="secondary">
        待审实体仅 LLM 抽取出的新实体；通过后进入通用实体库，拒绝后将从相关文档图谱移除并重抽。
      </a-typography-text>

      <a-table
        :columns="columns"
        :data-source="visibleEntities"
        :loading="loading"
        row-key="rowKey"
        size="middle"
        :pagination="{ pageSize: 10, showSizeChanger: true }"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'status'">
            <a-tag :color="statusColor(record.status)">{{ statusLabel(record.status) }}</a-tag>
          </template>
          <template v-if="column.key === 'layer'">
            <a-tag>{{ layerLabel(record.layer) }}</a-tag>
          </template>
          <template v-if="column.key === 'source'">
            <div class="entity-review-sources">
              <template v-if="record.proposed_doc_id">
                <a-tooltip
                  v-for="(line, idx) in sourceLines(record)"
                  :key="idx"
                  :title="line"
                  placement="top"
                >
                  <a-tag class="entity-review-source-tag" @click="emitViewSource(record, line)">
                    {{ record.proposed_doc_id }} / {{ truncateSource(line, 16) }}
                  </a-tag>
                </a-tooltip>
              </template>
              <span v-else class="entity-review-sub">-</span>
            </div>
          </template>
          <template v-if="column.key === 'action'">
            <template v-if="activeTab === 'deleted'">
              <a-button type="link" size="small" @click="restoreEntity(record)">恢复</a-button>
            </template>
            <template v-else>
              <template v-if="record.status === 'pending'">
                <a-button type="link" size="small" @click="approve(record)">通过</a-button>
                <a-divider type="vertical" />
                <a-button type="link" size="small" danger @click="openReject(record)">拒绝</a-button>
                <a-divider type="vertical" />
              </template>
              <a-popconfirm
                title="确定删除该实体？删除后将触发相关文档重建。"
                @confirm="removeEntity(record)"
              >
                <a-button type="link" size="small" danger>删除</a-button>
              </a-popconfirm>
            </template>
          </template>
        </template>
      </a-table>

      <a-modal
        v-model:open="rejectModalOpen"
        title="拒绝实体"
        :width="480"
        ok-text="拒绝"
        ok-danger
        :ok-button-props="{ disabled: !rejectReason.trim() }"
        @ok="confirmReject"
        @cancel="rejectReason = ''"
      >
        <p>确定拒绝实体「{{ rejectTarget?.name }}」？拒绝后将从相关文档图谱中移除并触发重新抽取。</p>
        <a-textarea
          v-model:value="rejectReason"
          :rows="3"
          placeholder="请填写拒绝原因（必填）"
        />
      </a-modal>
    </div>
  </a-drawer>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { knowledgeApi } from '@/api/knowledge'

interface EntityItem {
  entity_id: string
  name: string
  layer: string
  aliases: string[]
  status?: 'approved' | 'pending' | 'rejected'
  source_clause: string
  proposed_doc_id: string
  created_at: string
}

interface DeletedEntity {
  library_id: string
  name: string
  deleted_at: string
}

interface EntityRow extends EntityItem {
  rowKey: string
  deleted_at?: string
}

const props = defineProps<{
  open: boolean
  libraryId: string
}>()

const emit = defineEmits<{
  (e: 'update:open', value: boolean): void
  (e: 'changed'): void
  (e: 'view-source', payload: { docId: string; sectionPath: string; libraryId: string }): void
}>()

const loading = ref(false)
const activeTab = ref<'pending' | 'approved' | 'deleted'>('pending')
const layerFilter = ref('')
const pendingList = ref<EntityItem[]>([])
const allList = ref<EntityItem[]>([])
const deletedList = ref<DeletedEntity[]>([])
const rejectModalOpen = ref(false)
const rejectTarget = ref<EntityItem | null>(null)
const rejectReason = ref('')

const columns = [
  { title: '实体名', dataIndex: 'name', key: 'name', width: 180 },
  { title: '状态', dataIndex: 'status', key: 'status', width: 90 },
  { title: '层级', dataIndex: 'layer', key: 'layer', width: 80 },
  { title: '来源', key: 'source' },
  { title: '操作', key: 'action', width: 150 },
]

const pendingCount = computed(() => pendingList.value.length)
const approvedCount = computed(() => allList.value.filter(e => e.status === 'approved').length)
const deletedCount = computed(() => deletedList.value.length)

const deletedRows = computed<EntityRow[]>(() =>
  deletedList.value.map(item => ({
    entity_id: `deleted-${item.name}`,
    rowKey: `deleted-${item.name}`,
    name: item.name,
    layer: '',
    aliases: [],
    status: 'rejected' as const,
    source_clause: '',
    proposed_doc_id: '',
    created_at: item.deleted_at,
    deleted_at: item.deleted_at,
  }))
)

const visibleEntities = computed<EntityRow[]>(() => {
  let rows: EntityRow[] = []
  if (activeTab.value === 'pending') {
    rows = pendingList.value.map(e => ({ ...e, rowKey: e.entity_id }))
  } else if (activeTab.value === 'approved') {
    rows = allList.value
      .filter(e => e.status === 'approved')
      .map(e => ({ ...e, rowKey: e.entity_id }))
  } else {
    rows = deletedRows.value
  }
  if (layerFilter.value && activeTab.value !== 'deleted') {
    rows = rows.filter(e => e.layer === layerFilter.value)
  }
  return rows
})

function statusColor(status?: string) {
  if (status === 'pending') return 'orange'
  if (status === 'rejected') return 'red'
  return 'green'
}

function statusLabel(status?: string) {
  if (status === 'pending') return '待审核'
  if (status === 'rejected') return '已删除'
  return '已入库'
}

function layerLabel(layer: string) {
  if (layer === 'concept') return '概念'
  if (layer === 'condition') return '条件'
  if (layer === 'action') return '动作'
  return '-'
}

function sourceLines(record: EntityRow): string[] {
  return (record.source_clause || '')
    .split('/')
    .map(s => s.trim())
    .filter(Boolean)
}

function truncateSource(line: string, max = 16) {
  return line.length > max ? `${line.slice(0, max)}...` : line
}

function emitViewSource(record: EntityRow, sectionPath: string) {
  if (!record.proposed_doc_id) return
  emit('view-source', {
    docId: record.proposed_doc_id,
    sectionPath,
    libraryId: props.libraryId,
  })
}

async function loadAllData() {
  if (!props.libraryId) return
  loading.value = true
  try {
    const [pending, all, deleted] = await Promise.all([
      knowledgeApi.getPendingGraphEntities(props.libraryId),
      knowledgeApi.getAllGraphEntities(props.libraryId),
      knowledgeApi.getDeletedGraphEntities(props.libraryId),
    ])
    pendingList.value = pending
    allList.value = all
    deletedList.value = deleted
  } catch (e: any) {
    message.error(e?.message || '加载实体列表失败')
  } finally {
    loading.value = false
  }
}

async function approve(record: EntityRow) {
  try {
    await knowledgeApi.approveGraphEntity(record.entity_id)
    message.success(`已通过「${record.name}」`)
    emit('changed')
    await loadAllData()
  } catch (e: any) {
    message.error(e?.message || '审批失败')
  }
}

function openReject(record: EntityRow) {
  rejectTarget.value = { ...record }
  rejectReason.value = ''
  rejectModalOpen.value = true
}

async function confirmReject() {
  if (!rejectTarget.value || !rejectReason.value.trim()) return
  try {
    await knowledgeApi.rejectGraphEntity(rejectTarget.value.entity_id, rejectReason.value.trim())
    message.success(`已拒绝「${rejectTarget.value.name}」`)
    rejectModalOpen.value = false
    rejectReason.value = ''
    emit('changed')
    await loadAllData()
  } catch (e: any) {
    message.error(e?.message || '拒绝失败')
  }
}

async function removeEntity(record: EntityRow) {
  try {
    await knowledgeApi.deleteGraphEntity(record.entity_id)
    message.success(`已删除「${record.name}」`)
    emit('changed')
    await loadAllData()
  } catch (e: any) {
    message.error(e?.message || '删除失败')
  }
}

async function restoreEntity(record: EntityRow) {
  try {
    await knowledgeApi.restoreDeletedGraphEntity(props.libraryId, record.name)
    message.success(`已恢复「${record.name}」，下次重建时可能重新出现`)
    emit('changed')
    await loadAllData()
  } catch (e: any) {
    message.error(e?.message || '恢复失败')
  }
}

watch(() => props.open, (val) => {
  if (val) loadAllData()
})

watch(() => props.libraryId, () => {
  if (props.open) loadAllData()
})
</script>

<style lang="less" scoped>
.entity-review-drawer {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.entity-review-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.entity-review-filters {
  display: flex;
  align-items: center;
  gap: 8px;
}

.entity-review-filter-label {
  font-size: 13px;
  color: var(--text-secondary);
}

.entity-review-sub {
  font-size: 12px;
  color: var(--text-secondary);
}

.entity-review-sources {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.entity-review-source-tag {
  cursor: pointer;
  font-size: 12px;
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
