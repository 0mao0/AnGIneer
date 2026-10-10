<template>
  <div class="library-select" :class="{ 'library-select-title': props.mode === 'title' }">
    <!-- 组切换胶囊分段控件：与「AI对话」入口同族视觉语言（2026-10-06 业主审美改造） -->
    <div class="group-seg" role="tablist">
      <button
        v-for="g in GROUP_TABS"
        :key="g.value"
        type="button"
        role="tab"
        class="group-seg__btn"
        :class="{ 'is-active': groupTab === g.value }"
        :aria-selected="groupTab === g.value"
        @click="switchGroup(g.value)"
      >
        <span class="group-seg__dot" />
        <span>{{ g.label }}</span>
      </button>
    </div>
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
    <!-- 知识库管理操作（新建/改名/删除/拆分/合并/审核）全部收拢到多库管理页（spec v2.3），这里只是纯切换器 -->
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { message } from 'ant-design-vue'
import { DownOutlined } from '@ant-design/icons-vue'
import { useLibraryStore } from '@/stores/library'

const props = defineProps<{
  mode?: 'default' | 'title'
}>()

const store = useLibraryStore()

// 组 segment（plan-kb-split-groups，已完结清理）：评测语料与生产知识分栏展示；
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

const GROUP_TABS = [
  { label: '外服', value: 'prod' },
  { label: '内测', value: 'evals' },
] as const

function switchGroup(group: 'prod' | 'evals') {
  if (groupTab.value === group) return
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

// 下拉受控：hover/点击外区收起菜单
const selectOpen = ref(false)

const libraryName = computed(() => store.currentLibraryTitle)

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
/* 组切换胶囊分段控件：紫玻璃选中态 + 状态点，与「AI对话」入口同族 */
.group-seg {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  margin-right: 8px;
  padding: 3px;
  border: 1px solid rgba(165, 180, 252, 0.22);
  border-radius: 999px;
  background: rgba(148, 163, 255, 0.06);
}
.group-seg__btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 12px;
  border: none;
  border-radius: 999px;
  background: transparent;
  color: var(--text-tertiary, rgba(148, 163, 184, 0.75));
  font-size: 13px;
  line-height: 20px;
  cursor: pointer;
  transition: background 0.2s, color 0.2s;
}
.group-seg__btn:hover {
  color: #c7d2fe;
}
.group-seg__btn.is-active {
  background: linear-gradient(160deg, rgba(109, 95, 246, 0.5), rgba(72, 61, 180, 0.55) 55%, rgba(35, 120, 205, 0.45));
  color: #fff;
  font-weight: 600;
  box-shadow: 0 0 10px rgba(129, 140, 248, 0.25), inset 0 1px 0 rgba(255, 255, 255, 0.12);
}
.group-seg__dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: rgba(148, 163, 184, 0.45);
}
.group-seg__btn.is-active .group-seg__dot {
  background: #7dd3fc;
  box-shadow: 0 0 6px rgba(125, 211, 252, 0.8);
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
