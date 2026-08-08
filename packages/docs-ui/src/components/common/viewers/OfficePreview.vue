<template>
  <div class="local-office-preview">
    <div v-if="loading" class="office-loading">
      <a-spin size="large" />
      <div class="office-loading-text">正在渲染{{ extLabel }}...</div>
    </div>
    <div v-if="error" class="office-error">
      <a-alert type="error" :message="`${extLabel} 预览失败`" :description="error" show-icon />
    </div>
    <div ref="containerRef" class="office-doc-container" :class="`office-doc-${ext}`" />
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { renderAsync } from 'docx-preview'
import * as XLSX from 'xlsx'

const props = defineProps<{ fileUrl: string }>()

const containerRef = ref<HTMLElement | null>(null)
const loading = ref(false)
const error = ref('')

const ext = computed(() => {
  const m = props.fileUrl.match(/path=([^&#]*)/)
  const decoded = m ? decodeURIComponent(m[1]) : props.fileUrl
  return (decoded.split('.').pop() || '').toLowerCase()
})
const extLabel = computed(() => {
  const map: Record<string, string> = { docx: 'Word', xls: 'Excel', xlsx: 'Excel' }
  return map[ext.value] || 'Office'
})

const isDocx = computed(() => ext.value === 'docx')
const isSheet = computed(() => ['xls', 'xlsx'].includes(ext.value))

async function load() {
  if (!props.fileUrl || (!isDocx.value && !isSheet.value)) return
  loading.value = true
  error.value = ''
  if (containerRef.value) containerRef.value.innerHTML = ''
  try {
    const res = await fetch(props.fileUrl)
    if (!res.ok) throw new Error(`文件加载失败 (HTTP ${res.status})`)
    if (isDocx.value) {
      const blob = await res.blob()
      await renderAsync(blob, containerRef.value!, undefined, {
        className: 'docx',
        inWrapper: true,
        breakPages: true,
        ignoreLastRenderedPageBreak: true,
        useBase64URL: true,
      })
    } else {
      const buf = await res.arrayBuffer()
      const wb = XLSX.read(buf, { type: 'array' })
      const first = wb.SheetNames[0]
      const html = XLSX.utils.sheet_to_html(wb.Sheets[first], { id: 'xlsx-table' })
      if (containerRef.value) containerRef.value.innerHTML = html
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

watch(() => props.fileUrl, load, { immediate: true })
onBeforeUnmount(() => {
  if (containerRef.value) containerRef.value.innerHTML = ''
})
</script>

<style scoped>
.local-office-preview {
  position: relative;
  height: 100%;
  overflow: auto;
  background: var(--color-bg-container, #fff);
}
.office-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 48px 0;
}
.office-loading-text {
  color: var(--text-secondary, #666);
  font-size: 13px;
}
.office-error {
  padding: 16px;
}
.office-doc-container {
  padding: 12px 16px;
  min-height: 100%;
}
.office-doc-container :deep(.docx-wrapper) {
  padding: 8px 0 24px;
}
.office-doc-container :deep(.docx) {
  margin: 0 auto 16px;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.12);
  background: #fff;
}
.office-doc-container :deep(table) {
  border-collapse: collapse;
  width: 100%;
  font-size: 13px;
}
.office-doc-container :deep(td),
.office-doc-container :deep(th) {
  border: 1px solid var(--border-color, #d9d9d9);
  padding: 4px 8px;
  word-break: break-all;
}
</style>
