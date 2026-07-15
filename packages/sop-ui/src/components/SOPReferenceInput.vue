/**
 * SOP @引用输入组件，支持 @ 触发下拉搜索知识库文档和 block。
 * 通过 sopApi.listKnowledgeNodes 和 getStructuredIndex 接入真实知识库。
 */
<template>
  <div class="sop-reference-input">
    <div class="reference-tags">
      <a-tag
        v-for="ref in references"
        :key="ref.id"
        closable
        @close="removeReference(ref.id)"
      >
        {{ ref.displayName }}
      </a-tag>
    </div>
    <a-input
      v-model:value="inputValue"
      :placeholder="placeholder"
      @input="onInput"
      @keydown="onKeydown"
    />
    <div v-if="showDropdown && dropdownItems.length > 0" class="reference-dropdown">
      <div
        v-for="item in dropdownItems"
        :key="item.id"
        class="dropdown-item"
        @click="selectItem(item)"
      >
        <span class="dropdown-item-title">{{ item.title }}</span>
        <span v-if="item.subtitle" class="dropdown-item-sub">{{ item.subtitle }}</span>
      </div>
    </div>
    <div v-if="showDropdown && searchLoading" class="reference-dropdown reference-dropdown--loading">
      <div class="dropdown-item">搜索中...</div>
    </div>
    <div v-if="showDropdown && !searchLoading && dropdownItems.length === 0 && searchKeyword.length > 0" class="reference-dropdown">
      <div class="dropdown-item">无匹配结果</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { sopApi } from '../composables/useSopApi'

interface ReferenceItem {
  id: string
  displayName: string
  docId?: string
  blockId?: string
}

interface DropdownItem {
  id: string
  title: string
  subtitle?: string
  docId?: string
  blockId?: string
}

const props = defineProps<{
  modelValue?: string
  placeholder?: string
  references?: ReferenceItem[]
  libraryId?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  'add-reference': [ref: ReferenceItem]
  'remove-reference': [id: string]
}>()

const inputValue = computed({
  get: () => props.modelValue || '',
  set: (val) => emit('update:modelValue', val),
})

const showDropdown = ref(false)
const dropdownItems = ref<DropdownItem[]>([])
const searchLoading = ref(false)
const searchKeyword = ref('')
let searchTimer: ReturnType<typeof setTimeout> | null = null

/** 解析输入中的 @ 搜索关键词 */
const onInput = (event: Event) => {
  const value = (event.target as HTMLInputElement).value
  const atIdx = value.lastIndexOf('@')
  if (atIdx >= 0) {
    searchKeyword.value = value.slice(atIdx + 1)
    showDropdown.value = true
    debouncedSearch(searchKeyword.value)
  } else {
    showDropdown.value = false
    searchKeyword.value = ''
    dropdownItems.value = []
  }
}

const onKeydown = (event: KeyboardEvent) => {
  if (event.key === 'Escape') {
    showDropdown.value = false
  }
}

/** 防抖搜索 */
const debouncedSearch = (keyword: string) => {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => doSearch(keyword), 300)
}

/** 执行知识库搜索：先搜文档节点，再搜文档内 block */
const doSearch = async (keyword: string) => {
  if (!keyword.trim()) {
    dropdownItems.value = []
    searchLoading.value = false
    return
  }
  searchLoading.value = true
  try {
    const nodes = await sopApi.listKnowledgeNodes(props.libraryId || 'default')
    const docNodes = nodes.filter((n) => n.type === 'document')
    const lowerKw = keyword.toLowerCase()
    const matchedDocs = docNodes.filter(
      (n) => n.title.toLowerCase().includes(lowerKw) || n.id.toLowerCase().includes(lowerKw),
    )
    const items: DropdownItem[] = []
    for (const doc of matchedDocs.slice(0, 5)) {
      items.push({
        id: `doc:${doc.id}`,
        title: doc.title,
        subtitle: '文档',
        docId: doc.id,
      })
      if (doc.strategy && doc.id) {
        try {
          const result = await sopApi.getStructuredIndex(doc.id, doc.strategy, keyword)
          const blockItems = (result.items || []).slice(0, 3)
          for (const block of blockItems) {
            const blockTitle = block.title || block.text?.slice(0, 30) || block.uid
            items.push({
              id: `block:${doc.id}:${block.uid}`,
              title: blockTitle,
              subtitle: `${doc.title} / block`,
              docId: doc.id,
              blockId: block.uid,
            })
          }
        } catch {
          // 结构化索引不可用时仅展示文档级引用
        }
      }
    }
    dropdownItems.value = items
  } catch {
    dropdownItems.value = []
  } finally {
    searchLoading.value = false
  }
}

/** 选择下拉项，构造引用并发射事件 */
const selectItem = (item: DropdownItem) => {
  const ref: ReferenceItem = {
    id: item.id,
    displayName: item.title,
    docId: item.docId,
    blockId: item.blockId,
  }
  emit('add-reference', ref)
  showDropdown.value = false
  const atIdx = inputValue.value.lastIndexOf('@')
  if (atIdx >= 0) {
    inputValue.value = inputValue.value.slice(0, atIdx)
  }
}

const removeReference = (id: string) => {
  emit('remove-reference', id)
}
</script>

<style lang="less" scoped>
.sop-reference-input {
  position: relative;
}

.reference-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 4px;
}

.reference-dropdown {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  z-index: 100;
  max-height: 200px;
  overflow-y: auto;
  background: var(--panel-bg);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);

  &--loading {
    pointer-events: none;
  }
}

.dropdown-item {
  padding: 8px 12px;
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  align-items: center;

  &:hover {
    background: var(--hover-bg, #f5f5f5);
  }
}

.dropdown-item-title {
  font-size: 13px;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 70%;
}

.dropdown-item-sub {
  font-size: 11px;
  color: var(--text-secondary);
  flex-shrink: 0;
  margin-left: 8px;
}
</style>
