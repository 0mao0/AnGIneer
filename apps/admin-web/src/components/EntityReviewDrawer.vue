<template>
  <a-drawer
    :open="open"
    title="实体审核"
    placement="right"
    :width="720"
    @close="emit('update:open', false)"
  >
    <div class="entity-review-drawer">
      <div class="entity-review-toolbar">
        <a-radio-group v-model:value="activeTab" size="small" @change="loadCurrent">
          <a-radio-button value="pending">待审核</a-radio-button>
          <a-radio-button value="all">全部实体</a-radio-button>
        </a-radio-group>
        <a-button size="small" :loading="loading" @click="loadCurrent">刷新</a-button>
      </div>
      <a-typography-text type="secondary">
        待审核实体仅 LLM 抽取出的新实体；通过后进入通用实体库，拒绝后将从相关文档图谱移除并重抽。
      </a-typography-text>

      <a-table
        :columns="columns"
        :data-source="entities"
        :loading="loading"
        row-key="entity_id"
        size="middle"
        :pagination="{ pageSize: 10, showSizeChanger: true }"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'status'">
            <a-tag :color="statusColor(record.status)">{{ statusLabel(record.status) }}</a-tag>
          </template>
          <template v-if="column.key === 'layer'">
            <a-tag>{{ record.layer }}</a-tag>
          </template>
          <template v-if="column.key === 'source'">
            <div>{{ record.source_clause || '-' }}</div>
            <div class="entity-review-sub">{{ record.proposed_doc_id || '' }}</div>
          </template>
          <template v-if="column.key === 'action'">
            <template v-if="record.status === 'pending'">
              <a-button type="link" size="small" @click="approve(record)">通过</a-button>
              <a-divider type="vertical" />
              <a-button type="link" size="small" danger @click="openReject(record)">拒绝</a-button>
            </template>
            <span v-else class="entity-review-sub">—</span>
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
import { ref, watch } from 'vue'
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

const props = defineProps<{
  open: boolean
  libraryId: string
}>()

const emit = defineEmits<{
  (e: 'update:open', value: boolean): void
  (e: 'changed'): void
}>()

const loading = ref(false)
const activeTab = ref<'pending' | 'all'>('pending')
const entities = ref<EntityItem[]>([])
const rejectModalOpen = ref(false)
const rejectTarget = ref<EntityItem | null>(null)
const rejectReason = ref('')

const columns = [
  { title: '实体名', dataIndex: 'name', key: 'name', width: 180 },
  { title: '状态', dataIndex: 'status', key: 'status', width: 90 },
  { title: '层级', dataIndex: 'layer', key: 'layer', width: 90 },
  { title: '来源', key: 'source' },
  { title: '操作', key: 'action', width: 140 },
]

function statusColor(status?: string) {
  if (status === 'pending') return 'orange'
  if (status === 'rejected') return 'red'
  return 'green'
}

function statusLabel(status?: string) {
  if (status === 'pending') return '待审核'
  if (status === 'rejected') return '已拒绝'
  return '已通过'
}

async function loadCurrent() {
  if (!props.libraryId) return
  loading.value = true
  try {
    if (activeTab.value === 'pending') {
      entities.value = await knowledgeApi.getPendingGraphEntities(props.libraryId)
    } else {
      entities.value = await knowledgeApi.getAllGraphEntities(props.libraryId)
    }
  } catch (e: any) {
    message.error(e?.message || '加载实体列表失败')
  } finally {
    loading.value = false
  }
}

async function approve(record: EntityItem) {
  try {
    await knowledgeApi.approveGraphEntity(record.entity_id)
    message.success(`已通过「${record.name}」`)
    emit('changed')
    await loadCurrent()
  } catch (e: any) {
    message.error(e?.message || '审批失败')
  }
}

function openReject(record: EntityItem) {
  rejectTarget.value = record
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
    await loadCurrent()
  } catch (e: any) {
    message.error(e?.message || '拒绝失败')
  }
}

watch(() => props.open, (val) => {
  if (val) loadCurrent()
})

watch(() => props.libraryId, () => {
  if (props.open) loadCurrent()
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
}

.entity-review-sub {
  font-size: 12px;
  color: var(--text-secondary);
}
</style>
