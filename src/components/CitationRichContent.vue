<template>
  <div class="citation-rich-content">
    <div
      v-for="(block, index) in richBlocks"
      :key="`${block.type}_${index}`"
      class="rich-block"
      :class="`media-${block.type}`"
    >
      <div v-if="block.type === 'table'" v-html="block.html" />
      <div v-else-if="block.type === 'math'" v-html="block.html" />
      <img
        v-else-if="block.type === 'image'"
        :src="block.src"
        alt="citation image"
        class="media-image"
      />
    </div>
    <div v-if="fallbackImageSources.length" class="rich-block media-images">
      <img
        v-for="(src, index) in fallbackImageSources"
        :key="`${src}_${index}`"
        :src="src"
        alt="citation image"
        class="media-image"
      />
    </div>
    <div
      v-if="contentHtml"
      class="rich-block media-content"
      v-html="contentHtml"
    />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { CitationReference } from '../../types'
import { renderFormula, renderMarkdownToHtml, resolveAssetUrl } from '../../utils/markdown'

interface Props {
  reference: CitationReference
  sourceFilePath?: string
}

const props = defineProps<Props>()

const resolvedSourceFilePath = computed(() => (
  props.sourceFilePath || props.reference.richMedia?.sourceFileName || ''
))

const formulaHtml = computed(() => {
  const source = props.reference.richMedia?.mathContent || ''
  return source ? renderFormula(source, true) : ''
})

const normalizedImageSources = computed(() => {
  const richMedia = props.reference.richMedia
  if (!richMedia) return []
  const paths = [
    ...(richMedia.imagePath ? [richMedia.imagePath] : []),
    ...(Array.isArray(richMedia.imagePaths) ? richMedia.imagePaths : [])
  ]
  return Array.from(new Set(
    paths
      .map(path => resolveAssetUrl(String(path || ''), resolvedSourceFilePath.value))
      .filter(Boolean)
  ))
})

const richBlocks = computed(() => {
  const richMedia = props.reference.richMedia
  if (!richMedia?.richMediaOrder?.length) {
    const blocks: Array<{ type: 'table' | 'math'; html: string }> = []
    if (richMedia?.tableHtml) {
      blocks.push({ type: 'table', html: richMedia.tableHtml })
    }
    if (formulaHtml.value) {
      blocks.push({ type: 'math', html: formulaHtml.value })
    }
    return blocks
  }

  const renderedImages = new Set<string>()
  const blocks: Array<
    | { type: 'table' | 'math'; html: string }
    | { type: 'image'; src: string }
  > = []

  richMedia.richMediaOrder.forEach((item) => {
    if (item.type === 'image') {
      const resolved = resolveAssetUrl(String(item.path || ''), resolvedSourceFilePath.value)
      if (resolved && !renderedImages.has(resolved)) {
        renderedImages.add(resolved)
        blocks.push({ type: 'image', src: resolved })
      }
      return
    }
    if (item.type === 'table' && richMedia.tableHtml) {
      blocks.push({ type: 'table', html: richMedia.tableHtml })
      return
    }
    if (item.type === 'math' && formulaHtml.value) {
      blocks.push({ type: 'math', html: formulaHtml.value })
    }
  })

  return blocks
})

const fallbackImageSources = computed(() => {
  const rendered = new Set(
    richBlocks.value
      .filter((item): item is { type: 'image'; src: string } => item.type === 'image')
      .map(item => item.src)
  )
  return normalizedImageSources.value.filter(src => !rendered.has(src))
})

const contentHtml = computed(() => {
  const content = String(props.reference.content || props.reference.snippet || '').trim()
  return content ? renderMarkdownToHtml(content, resolvedSourceFilePath.value) : ''
})
</script>

<style lang="less" scoped>
.citation-rich-content {
  display: flex;
  flex-direction: column;
  gap: 10px;
  color: var(--text-primary);

  .rich-block {
    min-width: 0;
  }

  .media-images {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .media-image {
    display: block;
    max-width: 100%;
    border-radius: 8px;
  }

  :deep(table) {
    width: 100%;
    border-collapse: collapse;
  }

  :deep(th),
  :deep(td) {
    border: 1px solid var(--border-color);
    padding: 6px 8px;
    vertical-align: top;
  }

  :deep(pre) {
    margin: 0;
    overflow-x: auto;
  }

  :deep(.katex-display),
  :deep(.media-formula) {
    overflow-x: auto;
  }
}
</style>
