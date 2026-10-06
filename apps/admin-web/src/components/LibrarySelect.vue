<template>
  <div class="library-select" :class="{ 'library-select-title': props.mode === 'title' }">
    <a-radio-group
      v-model:value="groupTab"
      size="small"
      option-type="button"
      class="library-group-tabs"
      :options="[
        { label: '外服', value: 'prod' },
        { label: '内测', value: 'evals' },
      ]"
      @change="handleGroupChange"
    />
    <template v-if="props.mode === 'title'">
      <a-dropdown :trigger="['hover']" v-model:open="selectOpen">
        <div class="library-title-trigger">
          <span class="library-title-name">{{ libraryName }}</span>
          <DownOutlined class="library-title-icon" />
        </div>
        <template #overlay>
          <a-menu @click="handleMenuClick">
            <a-menu-item v-for="lib in filteredLibraries" :key="lib.id">
              <span class="lib-option-name" :title="lib.name">{{ lib.name }}</span>
              <a-tag v-if="lib.status === 'migrating'" color="gold" class="lib-migrating-tag">迁移中</a-tag>
            </a-menu-item>
          </a-menu>
        </template>
      </a-dropdown>
    </template>
    <template v-else>
      <a-select
      :open="selectOpen"
      :value="store.libraryId"
      :loading="store.loading"
      style="min-width: 160px"
      :dropdown-match-select-width="false"
      :dropdown-style="{ minWidth: '280px' }"
      option-label-prop="label"
      @change="handleChange"
      @dropdown-visible-change="(v: boolean) => (selectOpen = v)"
    >
      <a-select-option
        v-for="lib in filteredLibraries"
        :key="lib.id"
        :value="lib.id"
        :label="lib.name"
      >
        <span class="lib-option-name" :title="lib.name">{{ lib.name }}</span>
        <a-tag v-if="lib.status === 'migrating'" color="gold" class="lib-migrating-tag">迁移中</a-tag>
      </a-select-option>
    </a-select>
    </template>
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
    <!-- 库管理操作（改名/删除/拆分/合并/实体审核）收拢到多库管理页（spec v2.3），下拉只留切换 + 迁移中徽章 -->
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { message } from 'ant-design-vue'
import { PlusOutlined, DownOutlined } from '@ant-design/icons-vue'
import { useLibraryStore } from '@/stores/library'
import { knowledgeApi } from '@/api/knowledge'

const props = defineProps<{
  mode?: 'default' | 'title'
}>()

const store = useLibraryStore()

// 组 segment（plan-kb-split-groups）：评测语料与生产知识分栏展示，操作能力一致；
// 组判定由后端注册表直出 group_name，前端只过滤（evals=评测语料，其余=生产）。
// 切组 = 恢复该组「上次选中」的库（store.groupLibraries）；无记录则取该组默认库/首库。
const groupTab = ref<'prod' | 'evals'>(store.currentLibraryGroup)

function libsOfGroup(group: 'prod' | 'evals') {
  return group === 'evals'
    ? store.libraries.filter((l) => l.group_name === 'evals')
    : store.libraries.filter((l) => l.group_name !== 'evals')
}

const filteredLibraries = computed(() => libsOfGroup(groupTab.value))

// 选中库变化（含库列表加载完成后的纠正）时，组 tab 跟随，避免「tab=生产、右侧库属于评测」的错位
watch(
  () => store.currentLibraryGroup,
  (g) => {
    groupTab.value = g
  },
)

function handleGroupChange(e: unknown) {
  // ant-design-vue 的 radio-group change 传的是 RadioChangeEvent（值在 e.target.value），不是裸值；
  // 直接比对第一个参数会恒判为非 evals（业主实踩：点「评测」右侧仍回默认库）。兼容两种调用形态。
  const raw = (e as { target?: { value?: unknown } })?.target?.value ?? e
  const group: 'prod' | 'evals' = raw === 'evals' ? 'evals' : 'prod'
  groupTab.value = group
  const list = libsOfGroup(group)
  const remembered = store.groupLibraries[group]
  const next =
    list.find((l) => l.id === remembered)?.id ??
    list.find((l) => l.id === 'default')?.id ??
    list[0]?.id
  if (next) {
    store.setLibrary(next)
  } else {
    message.warning(group === 'evals' ? '内测组暂无知识库' : '外服组暂无知识库')
  }
}

// 下拉菜单受控：避免弹框打开后菜单残留
const selectOpen = ref(false)

const libraryName = computed(() => store.currentLibraryTitle)

const showCreate = ref(false)
const creating = ref(false)
const createForm = ref({ name: '', description: '' })

onMounted(() => {
  if (store.libraries.length === 0) {
    store.loadLibraries()
  }
})

function handleChange(value: string) {
  store.setLibrary(value)
}

function handleMenuClick(info: { key: string }) {
  store.setLibrary(info.key)
  selectOpen.value = false
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
</script>

<style scoped>
.library-select {
  display: flex;
  align-items: center;
  gap: 4px;
}
.library-group-tabs {
  margin-right: 8px;
}
.library-select-title {
  min-width: auto;
}
.library-title-trigger {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 4px;
  transition: background-color 0.2s;
}
.library-title-trigger:hover {
  background-color: var(--bg-secondary, #f5f5f5);
}
.library-title-name {
  font-size: 20px;
  font-weight: 600;
  color: var(--text-primary);
}
.library-title-icon {
  font-size: 12px;
  color: var(--text-tertiary);
}
.lib-option-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: inline-block;
  max-width: 240px;
  vertical-align: middle;
}
.lib-migrating-tag {
  margin-left: 8px;
}
</style>
