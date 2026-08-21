<template>
  <div class="library-select">
    <a-select
      :value="store.libraryId"
      :loading="store.loading"
      style="min-width: 160px"
      @change="handleChange"
    >
      <a-select-option v-for="lib in store.libraries" :key="lib.id" :value="lib.id">
        {{ lib.name }}
      </a-select-option>
    </a-select>
    <template v-if="!hideActions">
      <a-button size="small" title="新建知识库" @click="showCreate = true">
        <template #icon><plus-outlined /></template>
      </a-button>
      <a-button
        size="small"
        title="修改知识库名称"
        :disabled="store.libraryId === 'default'"
        @click="openEdit"
      >
        <template #icon><edit-outlined /></template>
      </a-button>
    </template>

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
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import { PlusOutlined, EditOutlined } from '@ant-design/icons-vue'
import { useLibraryStore } from '@/stores/library'
import { knowledgeApi } from '@/api/knowledge'

withDefaults(defineProps<{ hideActions?: boolean }>(), { hideActions: false })

const store = useLibraryStore()

const showCreate = ref(false)
const creating = ref(false)
const createForm = ref({ name: '', description: '' })

const showEdit = ref(false)
const editing = ref(false)
const editForm = ref({ name: '', description: '' })

onMounted(() => {
  if (store.libraries.length === 0) {
    store.loadLibraries()
  }
})

function handleChange(value: string) {
  store.setLibrary(value)
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

function openEdit() {
  const lib = store.libraries.find((l) => l.id === store.libraryId)
  if (!lib) return
  editForm.value = { name: lib.name, description: lib.description || '' }
  showEdit.value = true
}

async function handleEdit() {
  const name = editForm.value.name.trim()
  if (!name) {
    message.warning('请输入名称')
    return
  }
  editing.value = true
  try {
    await knowledgeApi.updateLibrary(store.libraryId, {
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
</script>

<style scoped>
.library-select {
  display: flex;
  align-items: center;
  gap: 4px;
}
</style>
