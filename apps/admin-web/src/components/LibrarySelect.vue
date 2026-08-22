<template>
  <div class="library-select">
    <a-select
      :open="selectOpen"
      :value="store.libraryId"
      :loading="store.loading"
      style="min-width: 160px"
      :dropdown-match-select-width="false"
      :dropdown-style="{ minWidth: '280px' }"
      @change="handleChange"
      @dropdown-visible-change="(v: boolean) => (selectOpen = v)"
    >
      <a-select-option
        v-for="lib in store.libraries"
        :key="lib.id"
        :value="lib.id"
        :label="lib.name"
      >
        <div class="lib-option">
          <span class="lib-option-name" :title="lib.name">{{ lib.name }}</span>
          <span class="lib-option-actions" @click.stop>
            <a-button
              type="text"
              size="small"
              title="实体审核"
              @click="openReview(lib)"
            >
              <template #icon><audit-outlined /></template>
            </a-button>
            <a-button
              type="text"
              size="small"
              title="修改知识库"
              :disabled="lib.id === 'default'"
              @click="openEditFor(lib)"
            >
              <template #icon><edit-outlined /></template>
            </a-button>
            <a-button
              type="text"
              size="small"
              danger
              title="删除知识库"
              :disabled="lib.id === 'default'"
              @click="openDeleteConfirm(lib)"
            >
              <template #icon><delete-outlined /></template>
            </a-button>
          </span>
        </div>
      </a-select-option>
    </a-select>
    <a-button title="新建知识库" @click="showCreate = true">
      <template #icon><plus-outlined /></template>
    </a-button>

    <a-modal
      v-model:open="showCreate"
      title="新建知识库"
      @ok="handleCreate"
      @cancel="showCreate = false"
      :confirm-loading="creating"
    >
      <a-form layout="vertical">
        <a-form-item label="名称" required>
          <a-input v-model:value="createForm.name" placeholder="如：DredgeAI投标知识库" />
        </a-form-item>
        <a-form-item label="描述">
          <a-input v-model:value="createForm.description" placeholder="可选" />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal
      v-model:open="showEdit"
      title="修改知识库"
      @ok="handleEdit"
      @cancel="showEdit = false"
      :confirm-loading="editing"
    >
      <a-form layout="vertical">
        <a-form-item label="名称" required>
          <a-input v-model:value="editForm.name" placeholder="如：DredgeAI投标知识库" />
        </a-form-item>
        <a-form-item label="描述">
          <a-input v-model:value="editForm.description" placeholder="可选" />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal
      v-model:open="showDelete"
      title="删除知识库"
      ok-text="永久删除"
      ok-danger
      :ok-button-props="{ disabled: deleteInput.trim() !== deleteTargetName.trim() || deleting }"
      @ok="handleDelete"
      @cancel="deleteInput = ''"
    >
      <p class="lib-delete-warning">
        将删除该知识库下的全部节点、文档解析产物、索引与图谱数据，此操作不可恢复。
      </p>
      <p>请输入完整库名确认：</p>
      <p class="lib-delete-name">{{ deleteTargetName }}</p>
      <a-input-group compact class="lib-delete-fill-group">
        <a-input
          v-model:value="deleteInput"
          :placeholder="deleteTargetName"
          class="lib-delete-fill-input"
          @pressEnter="handleDelete"
        />
        <a-button
          class="lib-delete-fill-btn"
          title="点击自动填入完整库名，再次确认后即可删除"
          @click="deleteInput = deleteTargetName"
        >
          一键填入
        </a-button>
      </a-input-group>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import { PlusOutlined, EditOutlined, DeleteOutlined, AuditOutlined } from '@ant-design/icons-vue'
import { useLibraryStore, type KnowledgeLibraryItem } from '@/stores/library'
import { knowledgeApi } from '@/api/knowledge'

const emit = defineEmits<{
  (e: 'review', lib: KnowledgeLibraryItem): void
}>()

const store = useLibraryStore()

// 下拉菜单受控：item 内点击操作 icon 时主动收起，避免抽屉/弹框打开后菜单残留
const selectOpen = ref(false)

const showCreate = ref(false)
const creating = ref(false)
const createForm = ref({ name: '', description: '' })

const showEdit = ref(false)
const editing = ref(false)
const editForm = ref({ name: '', description: '' })
const editTarget = ref<KnowledgeLibraryItem | null>(null)

const showDelete = ref(false)
const deleting = ref(false)
const deleteInput = ref('')
const deleteTarget = ref<KnowledgeLibraryItem | null>(null)
const deleteTargetName = ref('')

onMounted(() => {
  if (store.libraries.length === 0) {
    store.loadLibraries()
  }
})

function handleChange(value: string) {
  store.setLibrary(value)
}

function openReview(lib: KnowledgeLibraryItem) {
  selectOpen.value = false
  emit('review', lib)
}

function openEditFor(lib: KnowledgeLibraryItem) {
  selectOpen.value = false
  editTarget.value = lib
  editForm.value = { name: lib.name, description: lib.description || '' }
  showEdit.value = true
}

function openDeleteConfirm(lib: KnowledgeLibraryItem) {
  selectOpen.value = false
  deleteTarget.value = lib
  deleteTargetName.value = lib.name
  deleteInput.value = ''
  showDelete.value = true
}

async function handleCreate() {
  const name = createForm.value.name.trim()
  if (!name) {
    message.warning('请输入名称')
    return
  }
  creating.value = true
  try {
    const lib = await knowledgeApi.createLibrary(name, createForm.value.description.trim())
    await store.loadLibraries()
    store.setLibrary(lib.id)
    showCreate.value = false
    createForm.value = { name: '', description: '' }
    message.success('知识库已创建')
  } catch (e: any) {
    message.error('创建失败: ' + (e.message || e))
  } finally {
    creating.value = false
  }
}

async function handleEdit() {
  const name = editForm.value.name.trim()
  if (!name || !editTarget.value) {
    message.warning('请输入名称')
    return
  }
  editing.value = true
  try {
    await knowledgeApi.updateLibrary(editTarget.value.id, {
      name,
      description: editForm.value.description.trim(),
    })
    await store.loadLibraries()
    showEdit.value = false
    message.success('知识库已更新')
  } catch (e: any) {
    message.error('修改失败: ' + (e.message || e))
  } finally {
    editing.value = false
  }
}

async function handleDelete() {
  if (!deleteTarget.value) return
  if (deleteInput.value.trim() !== deleteTargetName.value.trim()) {
    message.warning('请输入完整的库名确认')
    return
  }
  const targetId = deleteTarget.value.id
  deleting.value = true
  try {
    await knowledgeApi.deleteLibrary(targetId)
    deleteTarget.value = null
    deleteInput.value = ''
    showDelete.value = false
    if (store.libraryId === targetId) {
      store.setLibrary('default')
    }
    await store.loadLibraries()
    message.success('知识库已删除')
  } catch (e: any) {
    message.error('删除失败: ' + (e?.response?.data?.detail || e.message || e))
  } finally {
    deleting.value = false
  }
}
</script>

<style scoped>
.library-select {
  display: flex;
  align-items: center;
  gap: 4px;
}
.lib-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
}
.lib-option-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.lib-option-actions {
  display: inline-flex;
  align-items: center;
  flex-shrink: 0;
  margin-left: auto;
}
.lib-delete-warning {
  color: var(--error-color, #ff4d4f);
  margin-bottom: 12px;
}
.lib-delete-name {
  font-weight: 600;
  word-break: break-all;
  margin-bottom: 8px;
}
.lib-delete-fill-group {
  display: flex;
  width: 100%;
}
.lib-delete-fill-input {
  flex: 1;
  min-width: 0;
}
.lib-delete-fill-btn {
  color: var(--text-secondary, rgba(0, 0, 0, 0.45));
  background: var(--bg-secondary, #fafafa);
  border-color: var(--border-color, #d9d9d9);
  &:hover {
    color: var(--primary-color);
    border-color: var(--primary-color);
    background: var(--bg-secondary, #fafafa);
  }
}
</style>
