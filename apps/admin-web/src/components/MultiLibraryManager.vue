<template>
  <div class="multi-lib-manager" :class="appClass">
    <div class="ml-header">
      <a-button type="primary" @click="openCreate">
        <template #icon><plus-outlined /></template>
        新建知识库
      </a-button>
      <a-button :loading="loading" @click="load">
        <template #icon><reload-outlined /></template>
        刷新
      </a-button>
      <span class="ml-header-hint">外服=生产知识（standards / dredgeai），内测=评测语料（evals）。换组只改归属登记，数据物理搬迁属阶段二。</span>
    </div>

    <a-spin :spinning="loading && !groups.length">
      <div v-if="!loading && !groups.length" class="ml-empty">暂无知识库</div>
      <div v-for="group in groups" :key="group.group_name" class="ml-group">
        <div class="ml-group-header">
          <span class="ml-group-name">{{ groupName(group.group_name) }}</span>
          <a-tag v-if="!group.known_group" color="orange">未注册组</a-tag>
          <a-tag>{{ group.libraries.length }} 库</a-tag>
          <a-tag>{{ groupDocTotal(group) }} 文档</a-tag>
        </div>
        <a-table
          :data-source="group.libraries"
          :columns="columns"
          :pagination="false"
          row-key="id"
          size="small"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'name'">
              <div class="ml-lib-name">{{ record.name || record.id }}</div>
              <div class="ml-lib-id" :title="record.id">{{ record.id }}{{ record.collection ? ` · ${record.collection}` : '' }}</div>
            </template>
            <template v-else-if="column.key === 'doc_count'">
              <span class="ml-num">{{ record.doc_count }}</span>
            </template>
            <template v-else-if="column.key === 'status'">
              <a-tag v-if="record.status === 'retired'" color="red">已退役</a-tag>
              <a-tag v-else-if="record.status === 'migrating'" color="gold">迁移中</a-tag>
              <a-tag v-else>正常</a-tag>
            </template>
            <template v-else-if="column.key === 'actions'">
              <a-button type="link" size="small" @click="openEdit(record, group.group_name)">编辑</a-button>
              <a-button
                type="link"
                size="small"
                danger
                :disabled="record.id === 'default'"
                @click="openDelete(record)"
              >
                删除
              </a-button>
            </template>
          </template>
        </a-table>
      </div>
    </a-spin>

    <!-- 新建：名称/描述/所属组 -->
    <a-modal v-model:open="showCreate" title="新建知识库" :confirm-loading="saving" @ok="handleCreate">
      <a-form layout="vertical">
        <a-form-item label="名称" required>
          <a-input v-model:value="createForm.name" placeholder="如：DredgeAI投标知识库" />
        </a-form-item>
        <a-form-item label="描述">
          <a-input v-model:value="createForm.description" placeholder="可选" />
        </a-form-item>
        <a-form-item label="所属组">
          <a-select v-model:value="createForm.group_name" :options="groupOptions" />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- 编辑：default 库禁改名（后端拒），组下拉常驻 -->
    <a-modal v-model:open="showEdit" title="编辑知识库" :confirm-loading="saving" @ok="handleEdit">
      <a-form layout="vertical">
        <a-form-item label="名称" required>
          <a-input v-model:value="editForm.name" :disabled="editForm.id === 'default'" />
        </a-form-item>
        <a-form-item label="描述">
          <a-input v-model:value="editForm.description" placeholder="可选" />
        </a-form-item>
        <a-form-item label="所属组">
          <a-select v-model:value="editForm.group_name" :options="groupOptions" />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- 删除：与 LibrarySelect 同式——输入完整库名确认 -->
    <a-modal
      v-model:open="showDelete"
      title="删除知识库"
      ok-text="永久删除"
      :ok-button-props="{ disabled: deleteInput.trim() !== deleteTarget?.name?.trim() || deleting }"
      @ok="handleDelete"
      @cancel="deleteInput = ''"
    >
      <p class="ml-delete-warning">
        将删除该知识库下的全部节点、文档解析产物、索引与图谱数据，此操作不可恢复。
      </p>
      <p>请输入完整库名确认：</p>
      <p class="ml-delete-name">{{ deleteTarget?.name }}</p>
      <a-input v-model:value="deleteInput" :placeholder="deleteTarget?.name" @pressEnter="handleDelete" />
    </a-modal>
  </div>
</template>

<script setup lang="ts">
/**
 * 多库管理 tab：全库一览（按组分组）+ 新建 / 改名 / 换组 / 删除。
 * 数据源 GET /knowledge/libraries/groups（后端注册表聚合）；换组只改注册行，
 * 不搬数据（阶段二 flip 才做物理搬迁，见 plan-kb-split-groups）。
 */
import { onActivated, onMounted, ref } from 'vue'
import { message } from 'ant-design-vue'
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons-vue'
import { useTheme } from '@angineer/ui-kit'
import { knowledgeApi, type LibraryGroupItem } from '@/api/knowledge'
import { useLibraryStore } from '@/stores/library'

const { appClass } = useTheme()
const libraryStore = useLibraryStore()

const groups = ref<LibraryGroupItem[]>([])
const loading = ref(false)
const saving = ref(false)
const deleting = ref(false)

/** 展示组名与外服/内测 tab 口径一致：注册组中文显示，未知组直出原名 */
const GROUP_LABELS: Record<string, string> = {
  standards: '外服 · 规范标准',
  dredgeai: '外服 · 疏浚工程',
  evals: '内测 · 评测语料',
}

function groupName(name: string) {
  return GROUP_LABELS[name] ?? name
}

const groupOptions = Object.entries(GROUP_LABELS).map(([value, label]) => ({ value, label }))

function groupDocTotal(group: LibraryGroupItem) {
  return group.libraries.reduce((sum, lib) => sum + (lib.doc_count || 0), 0)
}

const columns = [
  { title: '知识库', key: 'name', dataIndex: 'name' },
  { title: '文档数', key: 'doc_count', width: 90 },
  { title: '状态', key: 'status', width: 90 },
  { title: '操作', key: 'actions', width: 130 },
]

async function load() {
  loading.value = true
  try {
    groups.value = await knowledgeApi.getLibraryGroups()
  } catch (err) {
    message.error(`加载库组失败：${(err as Error).message}`)
  } finally {
    loading.value = false
  }
}

// ── 新建 ──
const showCreate = ref(false)
const createForm = ref({ name: '', description: '', group_name: 'standards' })

function openCreate() {
  createForm.value = { name: '', description: '', group_name: 'standards' }
  showCreate.value = true
}

async function handleCreate() {
  if (!createForm.value.name.trim()) {
    message.warning('请填写名称')
    return
  }
  saving.value = true
  try {
    await knowledgeApi.createLibrary(createForm.value.name.trim(), createForm.value.description, createForm.value.group_name)
    message.success('已创建')
    showCreate.value = false
    await refreshAll()
  } catch (err) {
    message.error(`创建失败：${(err as Error).message}`)
  } finally {
    saving.value = false
  }
}

// ── 编辑（改名 / 改描述 / 换组）──
const showEdit = ref(false)
const editForm = ref({ id: '', name: '', description: '', group_name: 'standards' })

function openEdit(record: LibraryGroupItem['libraries'][number], groupNameOfRow: string) {
  editForm.value = {
    id: record.id,
    name: record.name || '',
    description: record.description || '',
    group_name: groupNameOfRow,
  }
  showEdit.value = true
}

async function handleEdit() {
  if (editForm.value.id !== 'default' && !editForm.value.name.trim()) {
    message.warning('请填写名称')
    return
  }
  saving.value = true
  try {
    const patch: { name?: string; description?: string; group_name?: string } = {
      description: editForm.value.description,
    }
    if (editForm.value.id !== 'default') patch.name = editForm.value.name.trim()
    if (editForm.value.group_name) patch.group_name = editForm.value.group_name
    await knowledgeApi.updateLibrary(editForm.value.id, patch)
    message.success('已保存')
    showEdit.value = false
    await refreshAll()
  } catch (err) {
    message.error(`保存失败：${(err as Error).message}`)
  } finally {
    saving.value = false
  }
}

// ── 删除 ──
const showDelete = ref(false)
const deleteTarget = ref<LibraryGroupItem['libraries'][number] | null>(null)
const deleteInput = ref('')

function openDelete(record: LibraryGroupItem['libraries'][number]) {
  deleteTarget.value = record
  deleteInput.value = ''
  showDelete.value = true
}

async function handleDelete() {
  const target = deleteTarget.value
  if (!target || deleteInput.value.trim() !== target.name.trim()) return
  deleting.value = true
  try {
    await knowledgeApi.deleteLibrary(target.id)
    message.success('已删除')
    showDelete.value = false
    await refreshAll()
  } catch (err) {
    message.error(`删除失败：${(err as Error).message}`)
  } finally {
    deleting.value = false
  }
}

/** 改动后同步刷新本表与全局库 store（日常维护等其它视图立即看到新库/换组） */
async function refreshAll() {
  await Promise.all([load(), libraryStore.loadLibraries()])
}

onMounted(load)
onActivated(load)
</script>

<style scoped>
.multi-lib-manager {
  height: 100%;
  overflow: auto;
  padding: 16px 24px;
}
.ml-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
}
.ml-header-hint {
  margin-left: auto;
  font-size: 12px;
  color: var(--text-tertiary, rgba(0, 0, 0, 0.45));
}
.ml-empty {
  padding: 48px 0;
  text-align: center;
  color: var(--text-tertiary, rgba(0, 0, 0, 0.45));
}
.ml-group {
  margin-bottom: 24px;
}
.ml-group-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.ml-group-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}
.ml-lib-name {
  font-weight: 500;
}
.ml-lib-id {
  font-size: 12px;
  color: var(--text-tertiary, rgba(0, 0, 0, 0.45));
  word-break: break-all;
}
.ml-num {
  font-variant-numeric: tabular-nums;
}
.ml-delete-warning {
  color: var(--error-color, #ff4d4f);
  margin-bottom: 12px;
}
.ml-delete-name {
  font-weight: 600;
  word-break: break-all;
  margin-bottom: 8px;
}
</style>
