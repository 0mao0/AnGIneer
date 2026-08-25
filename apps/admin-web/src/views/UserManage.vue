<template>
  <div class="user-manage" :class="appClass">
    <PageHeader title="用户管理" description="创建账号并配置可访问的知识库">
      <template #extra>
        <AppButton variant="primary" size="sm" @click="openCreate">新建用户</AppButton>
      </template>
    </PageHeader>

    <div class="user-table-wrap">
      <DataTable
        :columns="columns"
        :data-source="users"
        row-key="id"
        :loading="loading"
        :pagination="{ pageSize: 15 }"
        storage-key="angineer-users-v2"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'libraries'">
            <a-tag v-for="lid in record.library_ids" :key="lid" color="blue">{{ libraryLabel(lid) }}</a-tag>
            <span v-if="!record.library_ids.length" class="no-lib">未绑定</span>
          </template>
          <template v-else-if="column.key === 'created_at' || column.key === 'last_login_at'">
            {{ formatTime(record[column.key as keyof AdminUserItem] as string) }}
          </template>
          <template v-else-if="column.key === 'is_active'">
            <a-switch
              :checked="record.is_active"
              size="small"
              @change="(checked: boolean) => handleToggle(record, checked)"
            />
          </template>
          <template v-else-if="column.key === 'action'">
            <div class="action-cell">
              <AppButton variant="link" size="sm" @click="openEdit(record)">编辑</AppButton>
              <AppButton variant="link" size="sm" @click="openResetPassword(record)">重置密码</AppButton>
              <a-popconfirm title="确定删除该用户？此操作不可恢复" placement="left" @confirm="handleDelete(record)">
                <AppButton variant="link" size="sm" danger>删除</AppButton>
              </a-popconfirm>
            </div>
          </template>
        </template>
      </DataTable>
    </div>

    <a-modal v-model:open="createVisible" title="新建用户" @ok="handleCreate" :confirm-loading="saving" @cancel="resetForm">
      <a-form :model="form" layout="vertical">
        <a-form-item label="用户名" required>
          <a-input v-model:value="form.username" placeholder="登录账号" />
        </a-form-item>
        <a-form-item label="备注" required>
          <a-input v-model:value="form.display_name" placeholder="如：张三" />
        </a-form-item>
        <a-form-item label="初始密码" required>
          <a-input-password v-model:value="form.password" placeholder="至少 6 位" />
        </a-form-item>
        <a-form-item label="可访问知识库" required>
          <a-select v-model:value="form.library_ids" mode="multiple" placeholder="选择知识库" :options="libraryOptions" />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal v-model:open="editVisible" title="编辑用户" @ok="handleUpdate" :confirm-loading="saving" @cancel="resetForm">
      <a-form :model="form" layout="vertical">
        <a-form-item label="备注" required>
          <a-input v-model:value="form.display_name" />
        </a-form-item>
        <a-form-item label="可访问知识库" required>
          <a-select v-model:value="form.library_ids" mode="multiple" placeholder="选择知识库" :options="libraryOptions" />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal v-model:open="passwordVisible" title="重置密码" @ok="handleResetPassword" :confirm-loading="saving">
      <a-form layout="vertical">
        <a-form-item label="新密码" required>
          <a-input-password v-model:value="newPassword" placeholder="至少 6 位" />
        </a-form-item>
      </a-form>
      <a-alert type="info" message="重置后该用户所有登录会话将失效" />
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { message } from 'ant-design-vue'
import dayjs from 'dayjs'
import { useTheme, DataTable, PageHeader, AppButton } from '@angineer/ui-kit'
import type { DataTableColumn } from '@angineer/ui-kit'
import { usersApi, type AdminUserItem, type LibraryOptionItem } from '@/api/users'
import { knowledgeApi } from '@/api/knowledge'

const { appClass } = useTheme()

const users = ref<AdminUserItem[]>([])
const loading = ref(false)
const saving = ref(false)
const libraries = ref<LibraryOptionItem[]>([])
const libraryOptions = computed(() => libraries.value.map((l) => ({ value: l.id, label: l.name || l.id })))

const columns: DataTableColumn[] = [
  { title: '用户名', dataIndex: 'username', key: 'username', width: 140, minWidth: 120, resizable: true },
  { title: '备注', dataIndex: 'display_name', key: 'display_name', width: 140, minWidth: 100, resizable: true },
  { title: '可访问知识库', key: 'libraries', width: 240, minWidth: 180, resizable: true },
  { title: '最近登录', dataIndex: 'last_login_at', key: 'last_login_at', width: 150, minWidth: 120, resizable: true },
  { title: '启用', key: 'is_active', width: 70, minWidth: 60 },
  { title: '操作', key: 'action', width: 240, minWidth: 210, fixed: 'right' },
]

const createVisible = ref(false)
const editVisible = ref(false)
const passwordVisible = ref(false)
const newPassword = ref('')
const editingUser = ref<AdminUserItem | null>(null)
const form = reactive({ username: '', display_name: '', password: '', library_ids: [] as string[] })

function libraryLabel(lid: string): string {
  return libraries.value.find((l) => l.id === lid)?.name || lid
}

function formatTime(iso: string): string {
  return iso ? dayjs(iso).format('YYYY-MM-DD HH:mm') : '-'
}

async function loadUsers(): Promise<void> {
  loading.value = true
  try {
    users.value = await usersApi.list()
  } catch (e: any) {
    message.error('加载用户失败: ' + (e.message || e))
  } finally {
    loading.value = false
  }
}

async function loadLibraries(): Promise<void> {
  try {
    libraries.value = (await knowledgeApi.getLibraries()) as unknown as LibraryOptionItem[]
  } catch (e: any) {
    message.error('加载知识库失败: ' + (e.message || e))
  }
}

function resetForm(): void {
  form.username = ''
  form.display_name = ''
  form.password = ''
  form.library_ids = []
  newPassword.value = ''
  editingUser.value = null
}

function openCreate(): void {
  resetForm()
  createVisible.value = true
}

function openEdit(record: AdminUserItem): void {
  editingUser.value = record
  form.display_name = record.display_name
  form.library_ids = [...record.library_ids]
  editVisible.value = true
}

function openResetPassword(record: AdminUserItem): void {
  editingUser.value = record
  newPassword.value = ''
  passwordVisible.value = true
}

async function handleCreate(): Promise<void> {
  if (!form.username.trim() || !form.password.trim() || !form.library_ids.length) {
    message.warning('请填写用户名、密码并选择至少一个知识库')
    return
  }
  saving.value = true
  try {
    await usersApi.create({
      username: form.username.trim(),
      display_name: form.display_name.trim(),
      password: form.password,
      library_ids: form.library_ids,
    })
    message.success('用户已创建')
    createVisible.value = false
    resetForm()
    await loadUsers()
  } catch (e: any) {
    message.error('创建失败: ' + (e.message || e))
  } finally {
    saving.value = false
  }
}

async function handleUpdate(): Promise<void> {
  if (!editingUser.value || !form.library_ids.length) {
    message.warning('请选择至少一个知识库')
    return
  }
  saving.value = true
  try {
    await usersApi.update(editingUser.value.id, { display_name: form.display_name.trim(), library_ids: form.library_ids })
    message.success('已保存')
    editVisible.value = false
    resetForm()
    await loadUsers()
  } catch (e: any) {
    message.error('保存失败: ' + (e.message || e))
  } finally {
    saving.value = false
  }
}

async function handleResetPassword(): Promise<void> {
  if (!editingUser.value || !newPassword.value) return
  saving.value = true
  try {
    await usersApi.resetPassword(editingUser.value.id, newPassword.value)
    message.success('密码已重置')
    passwordVisible.value = false
  } catch (e: any) {
    message.error('重置失败: ' + (e.message || e))
  } finally {
    saving.value = false
  }
}

async function handleToggle(record: AdminUserItem, checked: boolean): Promise<void> {
  try {
    await usersApi.setActive(record.id, checked)
    record.is_active = checked
    message.success(checked ? '已启用' : '已禁用')
  } catch (e: any) {
    message.error('操作失败: ' + (e.message || e))
  }
}

async function handleDelete(record: AdminUserItem): Promise<void> {
  try {
    await usersApi.del(record.id)
    message.success('用户已删除')
    await loadUsers()
  } catch (e: any) {
    message.error('删除失败: ' + (e.message || e))
  }
}

onMounted(() => {
  loadLibraries()
  loadUsers()
})
</script>

<style scoped lang="less">
@import '../../../../packages/ui-kit/src/styles/variables.less';

.user-manage {
  padding: 24px;
}
.user-table-wrap {
  max-width: 1100px;
  margin: 0 auto;
}
.no-lib {
  color: @text-tertiary;
  font-size: @font-size-sm;
}

.action-cell {
  display: flex;
  align-items: center;
  gap: 2px;
  white-space: nowrap;
}
</style>
