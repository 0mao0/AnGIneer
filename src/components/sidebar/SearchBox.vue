<template>
  <div class="search-box">
    <a-input-search
      v-model:value="searchText"
      :placeholder="placeholder"
      :loading="loading"
      allow-clear
      @search="onSearch"
      @change="onDebounceSearch"
    >
      <template #prefix>
        <SearchOutlined />
      </template>
    </a-input-search>
    
    <div v-if="showResults && results.length" class="search-results">
      <a-list :data-source="results" size="small">
        <template #renderItem="{ item }">
          <a-list-item @click="selectResult(item)">
            <a-list-item-meta :title="item.title" :description="item.preview" />
          </a-list-item>
        </template>
      </a-list>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { SearchOutlined } from '@ant-design/icons-vue'

interface SearchResult {
  id: string
  title: string
  preview: string
  type: 'document' | 'table' | 'formula'
}

const props = withDefaults(defineProps<{
  placeholder?: string
  libraryId?: string
  debounceTime?: number
}>(), {
  placeholder: '搜索知识库...',
  debounceTime: 300
})

const emit = defineEmits<{
  search: [query: string]
  select: [result: SearchResult]
}>()

const searchText = ref('')
const loading = ref(false)
const showResults = ref(false)
const results = ref<SearchResult[]>([])

let debounceTimer: ReturnType<typeof setTimeout> | null = null

const onSearch = (value: string) => {
  if (debounceTimer) clearTimeout(debounceTimer)
  performSearch(value)
}

const onDebounceSearch = () => {
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => {
    performSearch(searchText.value)
  }, props.debounceTime)
}

const performSearch = async (query: string) => {
  if (!query.trim()) {
    results.value = []
    showResults.value = false
    return
  }

  loading.value = true
  showResults.value = true

  results.value = [
    { id: 'r1', title: '航道通航水深计算', preview: '...D₀ = T + Z₀ + Z₁ + Z₂ + Z₃...', type: 'formula' },
    { id: 'r2', title: '船舶航行下沉量', preview: '表6.4.5 船舶航行时船体下沉值...', type: 'table' }
  ]

  loading.value = false
  emit('search', query)
}

const selectResult = (result: SearchResult) => {
  showResults.value = false
  emit('select', result)
}

watch(() => props.libraryId, () => {
  results.value = []
  showResults.value = false
})
</script>

<style lang="less" scoped>
.search-box {
  position: relative;
  flex-shrink: 0;
  
  :deep(.ant-input-search) {
    .ant-input {
      font-size: 13px;
    }
  }
}

.search-results {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  background: #fff;
  border: 1px solid #e8e8e8;
  border-radius: 4px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
  max-height: 300px;
  overflow-y: auto;
  z-index: 100;

  :deep(.ant-list-item) {
    cursor: pointer;
    padding: 8px 12px;

    &:hover {
      background: #f5f5f5;
    }
  }
}
</style>
