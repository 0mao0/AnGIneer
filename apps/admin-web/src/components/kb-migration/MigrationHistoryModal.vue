<template>
  <a-modal
    :open="props.open"
    title="迁移记录"
    :width="880"
    :footer="null"
    @update:open="(v: boolean) => emit('update:open', v)"
  >
    <a-table
      :data-source="tasks"
      :columns="columns"
      :loading="loading"
      size="small"
      row-key="id"
      :pagination="{ pageSize: 15, showSizeChanger: false }"
      :custom-row="customRow"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'op'">
          {{ opLabels[record.op] || record.op }}
        </template>
        <template v-else-if="column.key === 'libraries'">
          {{ libraryPath(record) }}
        </template>
        <template v-else-if="column.key === 'status'">
          <a-tag :color="statusColor(record.status)">{{ statusLabels[record.status] || record.status }}</a-tag>
        </template>
        <template v-else-if="column.key === 'verify'">
          <template v-if="!record.verify">—</template>
          <template v-else-if="record.verify.ok">一致</template>
          <template v-else>差异：{{ record.verify.mismatches.join('；') }}</template>
        </template>
      </template>
    </a-table>
    <p class="hist-hint">点击任意行查看任务详情与审计。</p>
  </a-modal>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { knowledgeApi, type MigrationTask } from '@/api/knowledge'

const props = defineProps<{ open: boolean }>()

const emit = defineEmits<{
  (e: 'update:open', v: boolean): void
  (e: 'open-task', id: string): void
}>()

const tasks = ref<MigrationTask[]>([])
const loading = ref(false)

const opLabels: Record<string, string> = { split: '拆分', merge: '合并', rollback: '回滚' }
const statusLabels: Record<string, string> = {
  running: '进行中', cancelling: '取消中', completed: '已完成', failed: '失败',
  cancelled: '已取消', cancel_failed: '取消未完成', interrupted: '已中断',
  switch_reload_failed: '待服务刷新',
}

const columns = [
  { title: '时间', dataIndex: 'created_at', key: 'created_at', width: 165 },
  { title: '操作', key: 'op', width: 60 },
  { title: '库', key: 'libraries', ellipsis: true },
  { title: '状态', key: 'status', width: 100 },
  { title: '对账', key: 'verify', width: 120 },
]

watch(
  () => props.open,
  (open) => {
    if (open) void load()
  },
)

async function load() {
  loading.value = true
  try {
    tasks.value = (await knowledgeApi.listMigrations()).tasks
  } catch (e: any) {
    message.error('迁移记录读取失败：' + (e.message || e))
  } finally {
    loading.value = false
  }
}

/** 库路径人话：拆分「A → 新库」；合并「A → B」；回滚「回滚：B → A」 */
function libraryPath(t: MigrationTask): string {
  const p = t.params || {}
  if (t.op === 'rollback') {
    const kind = opLabels[p.rollback_kind] || p.rollback_kind || ''
    return `回滚${kind}：${p.library_id || ''} → ${p.original_source_library_id || ''}`
  }
  const target = t.op === 'split' ? p.new_library_id : p.target_library_id
  return `${p.source_library_id || ''} → ${target || ''}`
}

function statusColor(status: string): string {
  if (status === 'completed') return 'green'
  if (status === 'running' || status === 'cancelling') return 'processing'
  if (status === 'switch_reload_failed') return 'orange'
  if (status) return 'red'
  return 'default'
}

function customRow(record: MigrationTask) {
  return {
    style: { cursor: 'pointer' },
    onClick: () => {
      emit('open-task', record.id)
      emit('update:open', false)
    },
  }
}
</script>

<style scoped>
.hist-hint {
  margin: 8px 0 0;
  color: var(--text-tertiary, rgba(0, 0, 0, 0.45));
  font-size: 12px;
}
</style>
