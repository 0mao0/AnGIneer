<template>
  <div class="document-view">
    <div class="doc-header">
      <h2>{{ document?.title || (loading ? '文档加载中...' : '未打开文档') }}</h2>
    </div>
    <div class="doc-content">
      <div v-if="loading" class="loading">
        <a-spin size="large" />
      </div>
      <EmptyState
        v-else-if="loadError"
        variant="error"
        title="文档加载失败"
        :description="loadError"
        cta-text="重试"
        @cta-click="loadDocument"
      />
      <Preview_Markdown
        v-else-if="document"
        :content="document.content"
        :active-line-range="null"
      />
      <EmptyState
        v-else
        variant="empty"
        title="未打开文档"
        description="从左侧知识库选择一个文档开始查看"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { message } from 'ant-design-vue'
import { Preview_Markdown } from '@angineer/docs-ui'
import { EmptyState } from '@angineer/ui-kit'
import { knowledgeApi } from '@/api/knowledge'

const props = defineProps<{
  libraryId?: string
  docId?: string
  title?: string
}>()

const route = useRoute()
const loading = ref(true)
const loadError = ref<string>('')
const document = ref<{ id: string; title: string; content: string } | null>(null)

const loadDocument = async () => {
  const docId = (props.docId || route.params.id || '') as string
  const libraryId = props.libraryId || 'default'
  if (!docId) {
    loading.value = false
    document.value = null
    return
  }
  loading.value = true
  loadError.value = ''
  try {
    const result = await knowledgeApi.getDocument(libraryId, docId) as { content?: string; title?: string }
    document.value = {
      id: docId,
      title: props.title || result?.title || `文档 ${docId}`,
      content: result?.content || ''
    }
  } catch (err) {
    const e = err as Error
    loadError.value = e.message || '文档加载失败'
    message.error(loadError.value)
    document.value = null
  } finally {
    loading.value = false
  }
}

watch(() => [props.docId, props.libraryId], loadDocument)
onMounted(loadDocument)
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
}

.loading {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
