<template>
  <div
    ref="rootRef"
    class="markdown-preview"
    @click="onHtmlPreviewClick"
  >
    <div ref="visibleRef" class="markdown-visible" v-html="visibleHtml" />
    <div
      v-if="remainingCount > 0"
      class="markdown-remaining-hint"
    >
      加载中... ({{ renderedCount }}/{{ totalBlocks }})
    </div>
  </div>
</template>

<script setup lang="ts">
import { nextTick, ref, watch, computed, onBeforeUnmount } from 'vue'
import { toValidLine } from '../../../utils/common'

const CHUNK_SIZE = 80

const props = defineProps<{
  renderedMarkdown: string
  activeLineRange: { start: number; end: number } | null
}>()

const emit = defineEmits<{
  'select-line': [line: number]
}>()

const rootRef = ref<HTMLElement | null>(null)
const visibleRef = ref<HTMLElement | null>(null)

const allBlocks = ref<string[]>([])
const renderedChunkCount = ref(0)
let idleCallbackId: number | null = null

const totalBlocks = computed(() => allBlocks.value.length)
const renderedCount = computed(() => Math.min(renderedChunkCount.value * CHUNK_SIZE, totalBlocks.value))
const remainingCount = computed(() => totalBlocks.value - renderedCount.value)

const visibleHtml = computed(() => {
  const end = renderedChunkCount.value * CHUNK_SIZE
  return allBlocks.value.slice(0, end).join('\n')
})

const splitIntoBlocks = (html: string): string[] => {
  if (!html) return []
  const blockRegex = /(<(?:h[1-6]|p|pre|table|ul|ol|blockquote|div\.math-block|div\.media-table|div\.media-image|div\.media-formula)[^>]*>[\s\S]*?<\/(?:h[1-6]|p|pre|table|ul|ol|blockquote|div)>)/gi
  const blocks: string[] = []
  let lastIndex = 0
  let match: RegExpExecArray | null
  while ((match = blockRegex.exec(html)) !== null) {
    if (match.index > lastIndex) {
      const between = html.slice(lastIndex, match.index).trim()
      if (between) blocks.push(between)
    }
    blocks.push(match[1])
    lastIndex = match.index + match[1].length
  }
  if (lastIndex < html.length) {
    const remaining = html.slice(lastIndex).trim()
    if (remaining) blocks.push(remaining)
  }
  return blocks
}

const scheduleChunkedRender = () => {
  if (idleCallbackId !== null) {
    cancelIdleCallback(idleCallbackId)
    idleCallbackId = null
  }
  const maxChunks = Math.ceil(allBlocks.value.length / CHUNK_SIZE)
  const renderNextChunk = () => {
    if (renderedChunkCount.value >= maxChunks) {
      idleCallbackId = null
      return
    }
    renderedChunkCount.value += 1
    if (renderedChunkCount.value < maxChunks) {
      idleCallbackId = requestIdleCallback(renderNextChunk, { timeout: 100 })
    } else {
      idleCallbackId = null
    }
  }
  idleCallbackId = requestIdleCallback(renderNextChunk, { timeout: 50 })
}

watch(() => props.renderedMarkdown, (html) => {
  if (idleCallbackId !== null) {
    cancelIdleCallback(idleCallbackId)
    idleCallbackId = null
  }
  const blocks = splitIntoBlocks(html)
  allBlocks.value = blocks
  renderedChunkCount.value = blocks.length <= CHUNK_SIZE * 2 ? Math.ceil(blocks.length / CHUNK_SIZE) : 2
  if (blocks.length > CHUNK_SIZE * 2) {
    scheduleChunkedRender()
  }
}, { immediate: true })

onBeforeUnmount(() => {
  if (idleCallbackId !== null) {
    cancelIdleCallback(idleCallbackId)
    idleCallbackId = null
  }
})

const onHtmlPreviewClick = (event: MouseEvent) => {
  const target = event.target as HTMLElement | null
  const lineElement = target?.closest('[data-line-start]') as HTMLElement | null
  if (!lineElement) return
  const line = toValidLine(lineElement.getAttribute('data-line-start'))
  if (line !== null) {
    emit('select-line', line)
  }
}

const syncActiveLineHighlight = () => {
  const root = rootRef.value
  if (!root) return
  const range = props.activeLineRange
  const prev = root.querySelectorAll('.active-markdown-block')
  prev.forEach(el => el.classList.remove('active-markdown-block'))
  if (!range) return
  const elements = Array.from(root.querySelectorAll('[data-line-start]'))
  let bestEl: Element | null = null
  let minDiff = Number.POSITIVE_INFINITY
  for (const el of elements) {
    const line = Number(el.getAttribute('data-line-start'))
    if (!Number.isFinite(line)) continue
    if (line > range.end) continue
    const diff = Math.abs(line - range.start)
    if (diff < minDiff) {
      minDiff = diff
      bestEl = el
    }
  }
  if (bestEl) {
    bestEl.classList.add('active-markdown-block')
    bestEl.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }
}

watch(() => props.activeLineRange, () => {
  requestAnimationFrame(syncActiveLineHighlight)
}, { immediate: true })

watch(visibleHtml, async () => {
  await nextTick()
  syncActiveLineHighlight()
})
</script>

<style lang="less" scoped>
.active-markdown-block {
  background-color: rgba(255, 235, 59, 0.3);
  transition: background-color 0.3s;
  border-radius: 4px;
  box-shadow: 0 0 0 2px rgba(255, 235, 59, 0.3);
}

.markdown-preview {
  height: 100%;
  min-height: 100%;
  box-sizing: border-box;
  padding: 12px 14px;
  color: var(--dp-title-text);
  line-height: 1.7;
}

.markdown-remaining-hint {
  text-align: center;
  padding: 12px;
  color: var(--dp-sub-text);
  font-size: 12px;
}

.markdown-preview :deep(h1),
.markdown-preview :deep(h2),
.markdown-preview :deep(h3),
.markdown-preview :deep(h4),
.markdown-preview :deep(h5),
.markdown-preview :deep(h6) {
  margin: 1.1em 0 0.65em;
  color: var(--dp-title-strong);
  line-height: 1.35;
  font-weight: 700;
}

.markdown-preview :deep(h1) {
  font-size: 26px;
  border-bottom: 1px solid var(--dp-pane-border);
  padding-bottom: 8px;
}

.markdown-preview :deep(h2) {
  font-size: 22px;
  border-bottom: 1px solid color-mix(in srgb, var(--dp-pane-border) 75%, transparent 25%);
  padding-bottom: 6px;
}

.markdown-preview :deep(h3) { font-size: 19px; }
.markdown-preview :deep(h4) { font-size: 17px; }
.markdown-preview :deep(h5) { font-size: 15px; }
.markdown-preview :deep(h6) { font-size: 14px; color: var(--dp-sub-text); }

.markdown-preview :deep(p) {
  margin: 0.55em 0;
  line-height: 1.8;
}

.markdown-preview :deep(ul),
.markdown-preview :deep(ol) {
  margin: 0.45em 0 0.8em 1.3em;
  padding: 0;
}

.markdown-preview :deep(li) {
  margin: 0.26em 0;
}

.markdown-preview :deep(blockquote) {
  margin: 0.8em 0;
  padding: 0.55em 0.9em;
  border-left: 3px solid #60a5fa;
  background: color-mix(in srgb, var(--dp-content-bg) 88%, #dbeafe 12%);
  border-radius: 6px;
}

.markdown-preview :deep(pre) {
  margin: 0.8em 0;
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--dp-code-bg);
  overflow-x: auto;
}

.markdown-preview :deep(code) {
  border-radius: 4px;
  padding: 2px 5px;
  font-size: 12px;
  background: var(--dp-inline-code-bg);
}

.markdown-preview :deep(pre code) {
  padding: 0;
  background: transparent;
}

.markdown-preview :deep(table) {
  width: 100%;
  margin: 0.8em 0;
  border-collapse: collapse;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid var(--dp-pane-border);
}

.markdown-preview :deep(th),
.markdown-preview :deep(td) {
  border: 1px solid var(--dp-pane-border);
  padding: 6px 8px;
  text-align: left;
  vertical-align: top;
}

.markdown-preview :deep(th) {
  font-weight: 600;
  background: color-mix(in srgb, var(--dp-content-bg) 86%, #e2e8f0 14%);
}

.markdown-preview :deep(.math-block) {
  margin: 0.9em 0;
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--dp-math-bg);
}
</style>
