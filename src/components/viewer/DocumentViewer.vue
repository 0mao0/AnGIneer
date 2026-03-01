<template>
  <div class="document-viewer">
    <div v-if="loading" class="loading-state">
      <a-spin size="large" tip="加载中..." />
    </div>
    
    <div v-else-if="error" class="error-state">
      <a-result status="error" :title="error.message">
        <template #extra>
          <a-button type="primary" @click="retry">重试</a-button>
        </template>
      </a-result>
    </div>
    
    <div v-else-if="document" class="document-content">
      <div class="doc-header">
        <h1>{{ document.title }}</h1>
        <div class="doc-meta">
          <a-tag v-if="document.metadata.category">{{ document.metadata.category }}</a-tag>
          <span v-if="document.metadata.version">版本: {{ document.metadata.version }}</span>
        </div>
      </div>
      
      <div class="doc-body" ref="contentRef">
        <div
          v-for="block in document.blocks"
          :key="block.id"
          :id="block.id"
          :class="['block', `block-${block.type}`]"
        >
          <component
            :is="getBlockComponent(block.type)"
            :block="block"
            @ref-click="handleRefClick"
          />
        </div>
      </div>
    </div>
    
    <a-empty v-else description="文档不存在" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, shallowRef } from 'vue'
import { useDocument } from '../../composables'
import type { DocumentBlock } from '../../types'

const props = defineProps<{
  docId: string
}>()

const emit = defineEmits<{
  refClick: [blockId: string]
}>()

const { document, loading, error, fetchDocument } = useDocument()
const contentRef = ref<HTMLElement | null>(null)

const getBlockComponent = (type: DocumentBlock['type']) => {
  const components: Record<string, any> = {
    heading: 'div',
    text: 'div',
    table: 'div',
    formula: 'div',
    figure: 'div'
  }
  return components[type] || 'div'
}

const handleRefClick = (blockId: string) => {
  emit('refClick', blockId)
}

const retry = () => {
  fetchDocument(props.docId)
}

onMounted(() => {
  fetchDocument(props.docId)
})
</script>

<style lang="less" scoped>
.document-viewer {
  height: 100%;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  background: #fff;
}

.loading-state,
.error-state {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.document-content {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
}

.doc-header {
  margin-bottom: 24px;
  padding-bottom: 16px;
  border-bottom: 1px solid #e8e8e8;

  h1 {
    margin: 0 0 8px;
    font-size: 24px;
  }

  .doc-meta {
    display: flex;
    align-items: center;
    gap: 12px;
    color: #666;
    font-size: 13px;
  }
}

.doc-body {
  .block {
    margin-bottom: 16px;
  }

  .block-heading {
    font-size: 18px;
    font-weight: 600;
    margin: 24px 0 12px;
  }

  .block-text {
    line-height: 1.8;
  }

  .block-formula {
    background: #f5f5f5;
    padding: 16px;
    border-radius: 4px;
    font-family: 'Times New Roman', serif;
  }

  .block-table {
    overflow-x: auto;
  }

  .block-figure {
    text-align: center;

    img {
      max-width: 100%;
      height: auto;
    }
  }
}
</style>
