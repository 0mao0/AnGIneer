<template>
  <div class="document-view">
    <div class="doc-header">
      <h2>{{ document?.title || '文档加载中...' }}</h2>
    </div>
    <div class="doc-content">
      <div v-if="loading" class="loading">
        <a-spin size="large" />
      </div>
      <div v-else-if="document" class="markdown-body" v-html="renderedContent" />
      <a-empty v-else description="文档不存在" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { knowledgeApi } from '@/api/knowledge'

const props = defineProps<{
  libraryId?: string
  docId?: string
  title?: string
}>()

const route = useRoute()
const loading = ref(true)
const document = ref<{ id: string; title: string; content: string } | null>(null)

const renderedContent = computed(() => {
  return document.value?.content || ''
})

onMounted(async () => {
  const docId = (props.docId || route.params.id || '') as string
  const libraryId = props.libraryId || 'default'
  if (!docId) {
    loading.value = false
    document.value = null
    return
  }
  loading.value = true
  try {
    const result = await knowledgeApi.getDocument(libraryId, docId) as { content?: string; title?: string }
    document.value = {
      id: docId,
      title: props.title || result?.title || `文档 ${docId}`,
      content: result?.content || ''
    }
  } catch {
    document.value = null
  } finally {
    loading.value = false
  }
})
</script>

<style lang="less" scoped>
.document-view {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--bg-secondary);
}

.doc-header {
  padding: 16px 24px;
  border-bottom: 1px solid var(--border-color);
  
  h2 {
    margin: 0;
    font-size: 18px;
  }
}

.doc-content {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
}

.loading {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.markdown-body {
  :deep(h1) {
    font-size: 24px;
    margin-bottom: 16px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--border-color);
  }
  
  :deep(h2) {
    font-size: 20px;
    margin: 24px 0 12px;
  }
  
  :deep(p) {
    margin: 8px 0;
    line-height: 1.8;
  }
  
  :deep(.formula) {
    background: var(--bg-tertiary);
    padding: 16px;
    border-radius: 4px;
    margin: 16px 0;
    font-family: 'Times New Roman', serif;
    font-size: 16px;
  }
  
  :deep(.data-table) {
    width: 100%;
    border-collapse: collapse;
    margin: 16px 0;
    
    th, td {
      border: 1px solid var(--border-color);
      padding: 8px 12px;
      text-align: center;
    }
    
    th {
      background: var(--bg-tertiary);
    }
  }
}
</style>
