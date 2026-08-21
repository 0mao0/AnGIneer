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
          <template v-if="column.key === 'library_name'">
            {{ record.library_name || record.library_id || '-' }}
          </template>
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
          <a-form-item label="备注" required>
            <a-input v-model:value="newKeyForm.user_name" placeholder="如：DredgeAI投标（哪个系统在用这把钥匙）" />
          </a-form-item>
          <a-form-item label="访问范围">
            <a-select v-model:value="newKeyForm.scope">
              <a-select-option value="both">文档 + 对话</a-select-option>
              <a-select-option value="doc">仅文档 API</a-select-option>
              <a-select-option value="chat">仅对话 API</a-select-option>
            </a-select>
          </a-form-item>
          <a-form-item label="知识库" required extra="该 Key 将只能访问所选库">
            <div class="library-picker">
              <a-select
                v-model:value="newKeyForm.library_id"
                placeholder="选择知识库"
                style="flex: 1"
                :options="libraryOptions"
              />
              <a-button size="small" title="新建知识库" @click="showCreateLib = true">
                <template #icon><plus-outlined /></template>
              </a-button>
            </div>
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
        title="编辑 Key"
        @ok="handleUpdate"
        @cancel="showEditModal = false"
        :confirm-loading="updating"
      >
        <a-form :model="editForm" layout="vertical">
          <a-form-item label="备注" required>
            <a-input v-model:value="editForm.user_name" placeholder="如：DredgeAI投标" />
          </a-form-item>
          <a-form-item label="访问范围">
            <a-select v-model:value="editForm.scope">
              <a-select-option value="both">文档 + 对话</a-select-option>
              <a-select-option value="doc">仅文档 API</a-select-option>
              <a-select-option value="chat">仅对话 API</a-select-option>
            </a-select>
          </a-form-item>
          <a-form-item label="知识库" required extra="换绑后历史文档仍留在原库">
            <div class="library-picker">
              <a-select
                v-model:value="editForm.library_id"
                placeholder="选择知识库"
                style="flex: 1"
                :options="libraryOptions"
              />
              <a-button size="small" title="新建知识库" @click="showCreateLib = true">
                <template #icon><plus-outlined /></template>
              </a-button>
            </div>
          </a-form-item>
        </a-form>
      </a-modal>

      <a-modal
        v-model:open="showCreateLib"
        title="新建知识库"
        @ok="handleCreateLibrary"
        @cancel="showCreateLib = false"
        :confirm-loading="creatingLib"
      >
        <a-form layout="vertical">
          <a-form-item label="名称" required>
            <a-input v-model:value="createLibName" placeholder="如：DredgeAI投标知识库" />
          </a-form-item>
        </a-form>
      </a-modal>

      <ApiKeyChart />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import dayjs from 'dayjs'
import { message } from 'ant-design-vue'
import { PlusOutlined } from '@ant-design/icons-vue'
import { useTheme } from '@angineer/ui-kit'
import { apiKeysApi, type KeyItem } from '@/api/apiKeys'
import { knowledgeApi } from '@/api/knowledge'
import ApiKeyChart from '@/components/ApiKeyChart.vue'

const { appClass } = useTheme()

const keys = ref<KeyItem[]>([])
const loading = ref(false)
const showCreateModal = ref(false)
const showKeyModal = ref(false)
const creating = ref(false)
const createdKey = ref('')

interface LibraryOptionItem { id: string; name: string }
const libraries = ref<LibraryOptionItem[]>([])
const libraryOptions = computed(() =>
  libraries.value.map((l) => ({ value: l.id, label: l.name || l.id }))
)

const showCreateLib = ref(false)
const creatingLib = ref(false)
const createLibName = ref('')

const newKeyForm = ref({
  user_name: '',
  scope: 'both' as 'doc' | 'chat' | 'both',
  library_id: '',
})

const showEditModal = ref(false)
const updating = ref(false)
const editingKey = ref<KeyItem | null>(null)
const editForm = ref({ user_name: '', scope: 'both' as 'doc' | 'chat' | 'both', library_id: '' })

function formatTime(iso: string): string {
  if (!iso) return '-'
  return dayjs(iso).format('YYYY-MM-DD HH:mm')
}

const columns = [
  { title: 'Key', dataIndex: 'key_prefix', key: 'key_prefix', width: 130 },
  { title: '备注', dataIndex: 'user_name', key: 'user_name', width: 150 },
  { title: '知识库', dataIndex: 'library_name', key: 'library_name', width: 160 },
  { title: '解析文档数', dataIndex: 'doc_count', key: 'doc_count', width: 100 },
  { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 150 },
  { title: '最后使用', dataIndex: 'last_used_at', key: 'last_used_at', width: 150 },
  { title: '启用', key: 'is_active', width: 80 },
  { title: '操作', key: 'action', width: 140 },
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

async function loadLibraries() {
  try {
    libraries.value = (await knowledgeApi.getLibraries()) as unknown as LibraryOptionItem[]
  } catch (e: any) {
    message.error('加载知识库失败: ' + (e.message || e))
  }
}

async function handleCreateLibrary() {
  const name = createLibName.value.trim()
  if (!name) {
    message.warning('请输入名称')
    return
  }
  creatingLib.value = true
  try {
    const lib = await knowledgeApi.createLibrary(name, '')
    await loadLibraries()
    // 优先填到当前打开的表单
    if (showCreateModal.value) newKeyForm.value.library_id = lib.id
    if (showEditModal.value) editForm.value.library_id = lib.id
    showCreateLib.value = false
    createLibName.value = ''
    message.success('知识库已创建')
  } catch (e: any) {
    message.error('创建失败: ' + (e.message || e))
  } finally {
    creatingLib.value = false
  }
}

async function handleCreate() {
  if (!newKeyForm.value.user_name.trim()) {
    message.warning('请输入备注')
    return
  }
  if (!newKeyForm.value.library_id) {
    message.warning('请选择知识库')
    return
  }
  creating.value = true
  try {
    const res = await apiKeysApi.create(newKeyForm.value)
    createdKey.value = res.api_key
    showCreateModal.value = false
    showKeyModal.value = true
    newKeyForm.value = { user_name: '', scope: 'both', library_id: '' }
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
  editForm.value = {
    user_name: record.user_name,
    scope: record.scope as 'doc' | 'chat' | 'both',
    library_id: record.library_id,
  }
  showEditModal.value = true
}

async function handleUpdate() {
  if (!editForm.value.user_name.trim()) {
    message.warning('请输入备注')
    return
  }
  if (!editForm.value.library_id) {
    message.warning('请选择知识库')
    return
  }
  if (!editingKey.value) return
  updating.value = true
  try {
    await apiKeysApi.update(editingKey.value.id, {
      user_name: editForm.value.user_name.trim(),
      scope: editForm.value.scope,
      library_id: editForm.value.library_id.trim(),
    })
    message.success('Key 已更新')
    showEditModal.value = false
    await loadKeys()
  } catch (e: any) {
    message.error('更新失败: ' + (e.message || e))
  } finally {
    updating.value = false
  }
}

onMounted(() => {
  loadKeys()
  loadLibraries()
})
</script>

<style lang="less" scoped>
.apikey-workspace {
  height: 100%;
  overflow-y: auto;
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

.library-picker {
  display: flex;
  align-items: center;
  gap: 4px;
}
</style>
