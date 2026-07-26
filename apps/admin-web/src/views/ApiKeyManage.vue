<template>
  <div class="apikey-workspace" :class="appClass">
    <div class="content-area">
      <div class="page-header">
        <h2>API Key 管理</h2>
        <a-button type="primary" @click="showCreateModal = true">新建 Key</a-button>
      </div>

      <a-table
        :columns="columns"
        :data-source="keys"
        :loading="loading"
        row-key="id"
        size="middle"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'is_active'">
            <a-tag :color="record.is_active ? 'green' : 'red'">
              {{ record.is_active ? '启用' : '停用' }}
            </a-tag>
          </template>
          <template v-if="column.key === 'action'">
            <a-popconfirm
              v-if="record.is_active"
              title="确定停用此 Key？"
              @confirm="handleDeactivate(record.id)"
            >
              <a-button type="link" danger size="small">停用</a-button>
            </a-popconfirm>
            <a-popconfirm
              v-else
              title="确定重新启用此 Key？"
              @confirm="handleReactivate(record.id)"
            >
              <a-button type="link" size="small">启用</a-button>
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
          <a-form-item label="用户名" required>
            <a-input v-model:value="newKeyForm.user_name" placeholder="如：张三" />
          </a-form-item>
          <a-form-item label="邮箱">
            <a-input v-model:value="newKeyForm.email" placeholder="用于通知" />
          </a-form-item>
          <a-form-item label="速率限制（次/分钟）">
            <a-input-number v-model:value="newKeyForm.rate_limit_per_minute" :min="1" :max="10000" />
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
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import { useTheme } from '@angineer/ui-kit'
import { apiKeysApi, type KeyItem } from '@/api/apiKeys'

const { appClass } = useTheme()

const keys = ref<KeyItem[]>([])
const loading = ref(false)
const showCreateModal = ref(false)
const showKeyModal = ref(false)
const creating = ref(false)
const createdKey = ref('')

const newKeyForm = ref({
  user_name: '',
  email: '',
  rate_limit_per_minute: 60,
})

const columns = [
  { title: '标识', dataIndex: 'key_prefix', key: 'key_prefix' },
  { title: '用户', dataIndex: 'user_name', key: 'user_name' },
  { title: '邮箱', dataIndex: 'email', key: 'email' },
  { title: '速率限制', dataIndex: 'rate_limit_per_minute', key: 'rate_limit_per_minute' },
  { title: '状态', key: 'is_active' },
  { title: '创建时间', dataIndex: 'created_at', key: 'created_at' },
  { title: '最后使用', dataIndex: 'last_used_at', key: 'last_used_at' },
  { title: '操作', key: 'action', width: 100 },
]

async function loadKeys() {
  loading.value = true
  try {
    keys.value = await apiKeysApi.list()
  } catch (e: any) {
    message.error('加载 Key 列表失败: ' + (e.message || e))
  } finally {
    loading.value = false
  }
}

async function handleCreate() {
  if (!newKeyForm.value.user_name.trim()) {
    message.warning('请输入用户名')
    return
  }
  creating.value = true
  try {
    const res = await apiKeysApi.create(newKeyForm.value)
    createdKey.value = res.api_key
    showCreateModal.value = false
    showKeyModal.value = true
    newKeyForm.value = { user_name: '', email: '', rate_limit_per_minute: 60 }
    await loadKeys()
    message.success('Key 创建成功')
  } catch (e: any) {
    message.error('创建失败: ' + (e.message || e))
  } finally {
    creating.value = false
  }
}

async function handleDeactivate(id: number) {
  try {
    await apiKeysApi.deactivate(id)
    message.success('已停用')
    await loadKeys()
  } catch (e: any) {
    message.error('操作失败: ' + (e.message || e))
  }
}

async function handleReactivate(id: number) {
  try {
    await apiKeysApi.reactivate(id)
    message.success('已启用')
    await loadKeys()
  } catch (e: any) {
    message.error('操作失败: ' + (e.message || e))
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
