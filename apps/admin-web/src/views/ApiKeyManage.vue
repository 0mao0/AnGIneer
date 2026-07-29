<template>
  <div class="apikey-workspace" :class="appClass">
    <div class="content-area">
      <div class="page-header">
        <h2>API 管理</h2>
        <a-button type="primary" @click="showCreateModal = true">新建 Key</a-button>
      </div>

      <a-table
        :columns="columns"
        :data-source="keys"
        :loading="loading"
        row-key="id"
        size="middle"
        :pagination="false"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'created_at' || column.key === 'last_used_at'">
            {{ record[column.key as keyof KeyItem] ? formatTime(record[column.key as keyof KeyItem] as string) : '-' }}
          </template>
          <template v-if="column.key === 'is_active'">
            <a-switch
              :checked="record.is_active"
              size="small"
              @change="(checked: boolean) => handleToggle(record, checked)"
            />
          </template>
          <template v-if="column.key === 'action'">
            <a-button type="link" size="small" @click="handleEdit(record)">编辑</a-button>
            <a-divider type="vertical" />
            <a-popconfirm
              title="确定删除此 Key？此操作不可恢复"
              @confirm="handleDelete(record)"
            >
              <a-button type="link" danger size="small">删除</a-button>
            </a-popconfirm>
          </template>
        </template>
      </a-table>

      <a-modal
        v-model:open="showCreateModal"
        title="新建 API Key"
        @ok="handleCreate"
        @cancel="showCreateModal = false"
        :confirm-loading="creating"
      >
        <a-form :model="newKeyForm" layout="vertical">
          <a-form-item label="名称" required>
            <a-input v-model:value="newKeyForm.user_name" placeholder="如：张三" />
          </a-form-item>
        </a-form>
      </a-modal>

      <a-modal
        v-model:open="showKeyModal"
        title="Key 已创建"
        :footer="null"
        @cancel="showKeyModal = false"
      >
        <a-alert
          type="warning"
          message="此 Key 仅在此时可见一次，请立即复制保存！"
          style="margin-bottom: 12px"
        />
        <a-typography-paragraph copyable>
          <code style="font-size: 14px; word-break: break-all;">{{ createdKey }}</code>
        </a-typography-paragraph>
      </a-modal>

      <a-modal
        v-model:open="showEditModal"
        title="编辑名称"
        @ok="handleRename"
        @cancel="showEditModal = false"
        :confirm-loading="renaming"
      >
        <a-form layout="vertical">
          <a-form-item label="名称" required>
            <a-input v-model:value="editForm.name" placeholder="如：张三" />
          </a-form-item>
        </a-form>
      </a-modal>

      <ApiKeyChart />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import dayjs from 'dayjs'
import { message } from 'ant-design-vue'
import { useTheme } from '@angineer/ui-kit'
import { apiKeysApi, type KeyItem } from '@/api/apiKeys'
import ApiKeyChart from '@/components/ApiKeyChart.vue'

const { appClass } = useTheme()

const keys = ref<KeyItem[]>([])
const loading = ref(false)
const showCreateModal = ref(false)
const showKeyModal = ref(false)
const creating = ref(false)
const createdKey = ref('')

const newKeyForm = ref({
  user_name: '',
})

const showEditModal = ref(false)
const renaming = ref(false)
const editingKey = ref<KeyItem | null>(null)
const editForm = ref({ name: '' })

function formatTime(iso: string): string {
  if (!iso) return '-'
  return dayjs(iso).format('YYYY-MM-DD HH:mm')
}

const columns = [
  { title: 'Key', dataIndex: 'key_prefix', key: 'key_prefix', width: 130 },
  { title: '名称', dataIndex: 'user_name', key: 'user_name', width: 150 },
  { title: '解析文档数', dataIndex: 'doc_count', key: 'doc_count', width: 100 },
  { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 150 },
  { title: '最后使用', dataIndex: 'last_used_at', key: 'last_used_at', width: 150 },
  { title: '启用', key: 'is_active', width: 80 },
  { title: '操作', key: 'action', width: 100 },
]

async function loadKeys() {
  loading.value = true
  try {
    keys.value = await apiKeysApi.list()
  } catch (e: any) {
    message.error('加载失败: ' + (e.message || e))
  } finally {
    loading.value = false
  }
}

async function handleCreate() {
  if (!newKeyForm.value.user_name.trim()) {
    message.warning('请输入名称')
    return
  }
  creating.value = true
  try {
    const res = await apiKeysApi.create(newKeyForm.value)
    createdKey.value = res.api_key
    showCreateModal.value = false
    showKeyModal.value = true
    newKeyForm.value = { user_name: '' }
    await loadKeys()
    message.success('Key 创建成功')
  } catch (e: any) {
    message.error('创建失败: ' + (e.message || e))
  } finally {
    creating.value = false
  }
}

async function handleToggle(record: KeyItem, checked: boolean) {
  try {
    await apiKeysApi.toggle(record.id, checked)
    message.success(checked ? '已启用' : '已停用')
    await loadKeys()
  } catch (e: any) {
    message.error('操作失败: ' + (e.message || e))
  }
}

async function handleDelete(record: KeyItem) {
  try {
    await apiKeysApi.del(record.id)
    message.success('已删除')
    await loadKeys()
  } catch (e: any) {
    message.error('删除失败: ' + (e.message || e))
  }
}

function handleEdit(record: KeyItem) {
  editingKey.value = record
  editForm.value.name = record.user_name
  showEditModal.value = true
}

async function handleRename() {
  if (!editForm.value.name.trim()) {
    message.warning('请输入名称')
    return
  }
  if (!editingKey.value) return
  renaming.value = true
  try {
    await apiKeysApi.rename(editingKey.value.id, editForm.value.name.trim())
    message.success('名称已更新')
    showEditModal.value = false
    await loadKeys()
  } catch (e: any) {
    message.error('编辑失败: ' + (e.message || e))
  } finally {
    renaming.value = false
  }
}

onMounted(() => {
  loadKeys()
})
</script>

<style lang="less" scoped>
.apikey-workspace {
  height: 100%;
  background: var(--bg-primary);
  padding: 24px;
}

.content-area {
  max-width: 1100px;
  margin: 0 auto;
  :deep(.ant-table) {
    text-align: center;
    th, td { text-align: center; }
  }
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;

  h2 {
    margin: 0;
    color: var(--text-primary);
  }
}
</style>
