<template>
  <div class="user-manage" :class="appClass">
    <div class="page-header">
      <h2>用户管理</h2>
      <AppButton variant="primary" size="sm" @click="openCreate">新建用户</AppButton>
    </div>

    <a-alert
      v-if="guestSettings?.load_error"
      type="error"
      show-icon
      class="guest-load-error"
      message="游客设置文件读取失败（游客当前被临时关闭）"
      :description="`原因：${guestSettings.load_error}。点击游客行「编辑」保存一次即可恢复。`"
    />

    <div class="user-table-wrap">
      <DataTable
        :columns="columns"
        :data-source="tableRows"
        row-key="id"
        :loading="loading"
        :pagination="{ pageSize: 15 }"
        storage-key="angineer-users-v2"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'username' && isGuestRow(record)">
            <span class="guest-name">游客</span>
            <a-tag color="gold">免登录</a-tag>
          </template>
          <template v-if="column.key === 'libraries'">
            <!-- 2026-10-09 业主定版：列内同样按授权单位聚合（组名（全部）/组名（N）/组内单勾显库名），
                 与编辑弹框选择框共用 ./components/accessScope 的同一规则 -->
            <a-tag v-for="u in accessUnitsOf(record)" :key="u.key" color="blue">{{ u.label }}</a-tag>
            <span v-if="!checkedOf(record).length" class="no-lib">未绑定</span>
          </template>
          <template v-else-if="column.key === 'created_at' || column.key === 'last_login_at'">
            {{ formatTime(record[column.key as keyof AdminUserItem] as string) }}
          </template>
          <template v-else-if="column.key === 'is_admin'">
            <a-switch
              :checked="record.is_admin"
              size="small"
              :disabled="isGuestRow(record)"
              @change="(checked: boolean) => handleAdminToggle(record, checked)"
            />
          </template>
          <template v-else-if="column.key === 'is_active'">
            <a-switch
              :checked="record.is_active"
              size="small"
              @change="(checked: boolean) => (isGuestRow(record) ? handleGuestToggle(checked) : handleToggle(record, checked))"
            />
          </template>
          <template v-else-if="column.key === 'action'">
            <div class="action-cell">
              <template v-if="isGuestRow(record)">
                <AppButton variant="link" size="sm" @click="openGuestEdit">编辑</AppButton>
              </template>
              <template v-else>
                <AppButton variant="link" size="sm" @click="openEdit(record)">编辑</AppButton>
                <AppButton variant="link" size="sm" @click="openResetPassword(record)">重置密码</AppButton>
                <a-popconfirm title="确定删除该用户？此操作不可恢复" placement="left" @confirm="handleDelete(record)">
                  <AppButton variant="link" size="sm" danger>删除</AppButton>
                </a-popconfirm>
              </template>
            </div>
          </template>
        </template>
      </DataTable>
    </div>

    <a-modal v-model:open="createVisible" title="新建用户" @ok="handleCreate" :confirm-loading="saving" @cancel="resetForm">
      <!-- 横向布局（克隆 EntityReviewDrawer 的 label-col 写法，2026-10-09 业主定版）：标签与控件全部同行省高度 -->
      <a-form :model="form" :label-col="{ span: 5 }" :wrapper-col="{ span: 18 }">
        <a-form-item label="用户名" required>
          <a-input v-model:value="form.username" placeholder="登录账号" />
        </a-form-item>
        <a-form-item label="备注" required>
          <a-input v-model:value="form.display_name" placeholder="如：张三" />
        </a-form-item>
        <a-form-item label="初始密码" required>
          <a-input-password v-model:value="form.password" placeholder="至少 6 位" />
        </a-form-item>
        <a-form-item label="设为管理员">
          <a-switch v-model:checked="form.is_admin" />
        </a-form-item>
        <a-form-item label="授权知识库" required>
          <!-- 两级授权（2026-10-09 设计稿 R4/R5/R6 + 业主显示定版）：选择框按授权单位聚合——整组勾满显「组名（全部）」、
               组内勾 ≥2 显「组名（N）」、组内单勾显库名（编辑回显＝派生集，无缓存，每次开弹框重拉——R5） -->
          <AccessScopeSelect v-model="form.accessChecked" :groups="libraryGroups" :loose="looseLibraries" />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal v-model:open="editVisible" title="编辑用户" @ok="handleUpdate" :confirm-loading="saving" @cancel="resetForm">
      <!-- 横向布局（克隆 EntityReviewDrawer 的 label-col 写法，2026-10-09 业主定版）：标签与控件全部同行省高度 -->
      <a-form :model="form" :label-col="{ span: 5 }" :wrapper-col="{ span: 18 }">
        <a-form-item label="备注" required>
          <a-input v-model:value="form.display_name" />
        </a-form-item>
        <a-form-item label="设为管理员">
          <a-switch v-model:checked="form.is_admin" />
        </a-form-item>
        <a-form-item label="授权知识库" required>
          <!-- 两级授权（2026-10-09 设计稿 R4/R5/R6 + 业主显示定版）：选择框按授权单位聚合——整组勾满显「组名（全部）」、
               组内勾 ≥2 显「组名（N）」、组内单勾显库名（编辑回显＝派生集，无缓存，每次开弹框重拉——R5） -->
          <AccessScopeSelect v-model="form.accessChecked" :groups="libraryGroups" :loose="looseLibraries" />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal v-model:open="guestEditVisible" title="编辑游客权限" @ok="handleGuestSave" :confirm-loading="saving">
      <a-form :model="guestForm" :label-col="{ span: 5 }" :wrapper-col="{ span: 18 }">
        <a-form-item label="可用知识库" required>
          <!-- 游客选择器：评测语料组不展示（V3 服务端同口径 400）；扁平勾选集直存 library_ids -->
          <AccessScopeSelect v-model="guestForm.accessChecked" :groups="guestLibraryGroups" :loose="guestLooseLibraries" />
        </a-form-item>
        <a-form-item label="轮数上限" required>
          <a-input-number v-model:value="guestForm.rounds" :min="1" :max="1000" :precision="0" style="width: 160px" />
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
import { useTheme, AppButton } from '@angineer/ui-kit'
import { DataTable } from '@angineer/table-ui'
import type { DataTableColumn } from '@angineer/ui-kit'
import AccessScopeSelect from '@/components/AccessScopeSelect.vue'
import { buildAccessUnits } from '@/components/accessScope'
import { useAdminAuthStore } from '@/stores/auth'
import { usersApi, type AdminUserItem, type LibraryOptionItem, type UserAccessPayload } from '@/api/users'
import { knowledgeApi, type LibraryGroupItem } from '@/api/knowledge'
import { guestApi, type GuestSettings } from '@/api/guest'

const { appClass } = useTheme()
const authStore = useAdminAuthStore()

const users = ref<AdminUserItem[]>([])
const loading = ref(false)
const saving = ref(false)
const libraries = ref<LibraryOptionItem[]>([])
const libraryGroups = ref<LibraryGroupItem[]>([])

/** 无组归属库（default/未登记）兜底进「散库」段。数据源 = getLibraries + getLibraryGroups
 *  （后端 /knowledge/libraries/groups 直出），每次开弹框重拉（R5 无缓存） */
const looseLibraries = computed(() => {
  const grouped = new Set(libraryGroups.value.flatMap((g) => g.libraries.map((l) => l.id)))
  return libraries.value.filter((l) => !grouped.has(l.id))
})

/** 勾选叶子集 → 订阅协议（写路径与 storage 语义逐位一致）：有勾选叶子的组＝组订阅（excluded＝组内未勾成员）；
 *  无组归属的勾选＝直选；library_ids 镜像恒全量回传（V2 关时服务端只读它——回滚层不空窗） */
function serializeAccess(checked: string[]): UserAccessPayload {
  const checkedSet = new Set(checked)
  const group_subscriptions = libraryGroups.value
    .filter((g) => g.libraries.some((l) => checkedSet.has(l.id)))
    .map((g) => ({
      group: g.group_name,
      excluded_libraries: g.libraries.map((l) => l.id).filter((id) => !checkedSet.has(id)),
    }))
  const inGroup = new Set(libraryGroups.value.flatMap((g) => g.libraries.map((l) => l.id)))
  const direct_library_ids = checked.filter((id) => !inGroup.has(id))
  return { library_ids: [...checked], group_subscriptions, direct_library_ids }
}

/** 行内快捷操作（管理员切换）回传用：勾选集＝当前派生集，缺键会被 V2 保存当成「清空订阅」 */
function checkedOf(record: AdminUserItem): string[] {
  return [...(record.accessible_libraries ?? record.library_ids ?? [])]
}

/** 列表列展示：勾选集合 → 聚合标签（与选择框共用同一规则） */
function accessUnitsOf(record: AdminUserItem): ReturnType<typeof buildAccessUnits> {
  return buildAccessUnits(checkedOf(record), libraryGroups.value, looseLibraries.value)
}

// ---- 游客虚拟行（2026-10-17 游客设置，设计稿 §3.4）：非数据库记录，前端合成置顶 ----

const GUEST_ROW_ID = '__guest__'
const guestSettings = ref<GuestSettings | null>(null)

/** 游客选择器不展示评测语料组（V3：evals 不进游客允许集，服务端同口径 400 拒绝） */
const guestLibraryGroups = computed(() => libraryGroups.value.filter((g) => g.group_name !== 'evals'))
const evalsLibIds = computed(
  () => new Set(libraryGroups.value.filter((g) => g.group_name === 'evals').flatMap((g) => g.libraries.map((l) => l.id))),
)
const guestLooseLibraries = computed(() => looseLibraries.value.filter((l) => !evalsLibIds.value.has(l.id)))

/** 与真实用户同构的合成行：列分支复用（libraries 列走 accessUnitsOf → buildAccessUnits） */
const guestRow = computed(() => ({
  id: GUEST_ROW_ID,
  username: '游客',
  display_name: '免登录访客',
  is_admin: false,
  library_ids: guestSettings.value?.library_ids ?? [],
  accessible_libraries: guestSettings.value?.library_ids ?? [],
  is_active: guestSettings.value?.enabled ?? false,
  created_at: '',
  last_login_at: null as string | null,
}))
const tableRows = computed(() =>
  guestSettings.value ? [guestRow.value as unknown as AdminUserItem, ...users.value] : users.value,
)
function isGuestRow(record: any): boolean {
  return record?.id === GUEST_ROW_ID
}

async function loadGuestSettings(): Promise<void> {
  try {
    guestSettings.value = await guestApi.getSettings()
  } catch (e: any) {
    message.error('加载游客设置失败: ' + (e.message || e))
  }
}

/** 启用开关行内直切（PUT 三键恒全发——服务端按整份设置保存）；失败不动本地态=开关自动回滚 */
async function handleGuestToggle(checked: boolean): Promise<void> {
  if (!guestSettings.value) return
  try {
    guestSettings.value = await guestApi.saveSettings({
      enabled: checked,
      rounds: guestSettings.value.rounds,
      library_ids: guestSettings.value.library_ids,
    })
    message.success(checked ? '已开放游客访问' : '已关闭游客访问')
  } catch (e: any) {
    message.error('操作失败: ' + (e.message || e))
  }
}

// ---- 游客编辑弹框（复用 AccessScopeSelect 扁平勾选集 → library_ids，不走 V2 订阅序列化） ----

const guestEditVisible = ref(false)
const guestForm = reactive({ rounds: 30, accessChecked: [] as string[] })

function openGuestEdit(): void {
  void (async () => {
    await loadLibraries() // R5：无缓存——每次开弹框重拉库清单
    guestForm.rounds = guestSettings.value?.rounds ?? 30
    guestForm.accessChecked = [...(guestSettings.value?.library_ids ?? [])]
    guestEditVisible.value = true
  })()
}

async function handleGuestSave(): Promise<void> {
  if (!guestForm.accessChecked.length) {
    message.warning('请至少选择一个知识库')
    return
  }
  const rounds = Number(guestForm.rounds)
  if (!Number.isInteger(rounds) || rounds < 1 || rounds > 1000) {
    message.warning('轮数上限必须是 1–1000 的整数')
    return
  }
  saving.value = true
  try {
    guestSettings.value = await guestApi.saveSettings({
      enabled: guestSettings.value?.enabled ?? true,
      rounds,
      library_ids: guestForm.accessChecked,
    })
    message.success('已保存')
    guestEditVisible.value = false
  } catch (e: any) {
    message.error('保存失败: ' + (e.message || e))
  } finally {
    saving.value = false
  }
}

const columns: DataTableColumn[] = [
  { title: '用户名', dataIndex: 'username', key: 'username', width: 140, minWidth: 120, resizable: true },
  { title: '备注', dataIndex: 'display_name', key: 'display_name', width: 140, minWidth: 100, resizable: true },
  { title: '管理员', key: 'is_admin', width: 80, minWidth: 70 },
  { title: '授权知识库', key: 'libraries', width: 240, minWidth: 180, resizable: true },
  { title: '最近登录', dataIndex: 'last_login_at', key: 'last_login_at', width: 150, minWidth: 120, resizable: true },
  { title: '启用', key: 'is_active', width: 70, minWidth: 60 },
  { title: '操作', key: 'action', width: 240, minWidth: 210, fixed: 'right' },
]

const createVisible = ref(false)
const editVisible = ref(false)
const passwordVisible = ref(false)
const newPassword = ref('')
const editingUser = ref<AdminUserItem | null>(null)
const form = reactive({ username: '', display_name: '', password: '', is_admin: false, accessChecked: [] as string[] })

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
    const [libs, groups] = await Promise.all([
      knowledgeApi.getLibraries() as unknown as Promise<LibraryOptionItem[]>,
      knowledgeApi.getLibraryGroups() as unknown as Promise<LibraryGroupItem[]>,
    ])
    libraries.value = libs
    libraryGroups.value = groups
  } catch (e: any) {
    message.error('加载知识库清单失败: ' + (e.message || e))
  }
}

function resetForm(): void {
  form.username = ''
  form.display_name = ''
  form.password = ''
  form.is_admin = false
  form.accessChecked = []
  newPassword.value = ''
  editingUser.value = null
}

function openCreate(): void {
  resetForm()
  void (async () => {
    await loadLibraries() // R5：无缓存——每次开弹框重拉派生数据源
    createVisible.value = true
  })()
}

function openEdit(record: AdminUserItem): void {
  editingUser.value = record
  form.display_name = record.display_name
  form.is_admin = record.is_admin
  void (async () => {
    await loadLibraries() // R5：每次打开重新拉取，避免旧快照勾选回显过期
    form.accessChecked = checkedOf(record)
    editVisible.value = true
  })()
}

function openResetPassword(record: AdminUserItem): void {
  editingUser.value = record
  newPassword.value = ''
  passwordVisible.value = true
}

async function handleCreate(): Promise<void> {
  if (!form.username.trim() || !form.password.trim() || !form.accessChecked.length) {
    message.warning('请填写用户名、密码并选择至少一个知识库')
    return
  }
  saving.value = true
  try {
    await usersApi.create({
      username: form.username.trim(),
      display_name: form.display_name.trim(),
      password: form.password,
      is_admin: form.is_admin,
      ...serializeAccess(form.accessChecked),
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

/** 编辑对象＝当前登录账号（按用户名匹配）时刷新会话用户：右上角显示名/管理员态实时跟手。
 *  非本人编辑不动会话，避免每次保存都多打一次 /auth/me */
async function syncSelfSession(username: string): Promise<void> {
  if (!authStore.user || authStore.user.username !== username) return
  try {
    await authStore.refreshMe()
  } catch {
    // refreshMe 内部对 401/403 已登出；其余失败保持现状，不影响保存结果
  }
}

async function handleUpdate(): Promise<void> {
  if (!editingUser.value || !form.accessChecked.length) {
    message.warning('请选择至少一个知识库')
    return
  }
  const edited = editingUser.value
  saving.value = true
  try {
    await usersApi.update(edited.id, {
      display_name: form.display_name.trim(),
      is_admin: form.is_admin,
      ...serializeAccess(form.accessChecked),
    })
    message.success('已保存')
    editVisible.value = false
    resetForm()
    await loadUsers()
    await syncSelfSession(edited.username)
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

async function handleAdminToggle(record: AdminUserItem, checked: boolean): Promise<void> {
  try {
    await usersApi.update(record.id, {
      display_name: record.display_name,
      is_admin: checked,
      // 必须原样回传现状订阅：V2 保存按「订阅全删重插」执行，缺订阅键＝洗空该用户检索权限
      ...serializeAccess(checkedOf(record)),
    })
    record.is_admin = checked
    message.success(checked ? '已设为管理员' : '已取消管理员')
    // 行内开关改的是自己时，会话里的管理员态也要跟手（取消自己管理员→刷新即登出）
    await syncSelfSession(record.username)
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
  loadGuestSettings()
})
</script>

<style scoped lang="less">
@import '../../../../packages/ui-kit/src/styles/variables.less';

.user-manage {
  padding: 24px;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  max-width: 1100px;
  margin-left: auto;
  margin-right: auto;
  h2 {
    margin: 0;
    color: var(--text-primary);
  }
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

.guest-load-error {
  max-width: 1100px;
  margin: 0 auto 12px;
}
.guest-name {
  margin-right: 6px;
}
</style>
