<template>
  <div class="tab-error-boundary">
    <slot v-if="!hasError" />
    <a-result v-else status="error" :title="errorTitle" :sub-title="errorMessage">
      <template #extra>
        <a-space>
          <a-button type="primary" @click="resetError">重试</a-button>
          <a-button @click="closeTab">关闭此标签</a-button>
        </a-space>
      </template>
    </a-result>
  </div>
</template>

<script setup lang="ts">
import { ref, onErrorCaptured } from 'vue'

const props = withDefaults(defineProps<{
  errorTitle?: string
  tabKey?: string
}>(), {
  errorTitle: '该标签页发生错误'
})

const emit = defineEmits<{
  (e: 'close', tabKey: string): void
}>()

const hasError = ref(false)
const errorMessage = ref('')

onErrorCaptured((error) => {
  hasError.value = true
  errorMessage.value = error.message
  console.error('[TabErrorBoundary]', props.tabKey, error)
  return false
})

const resetError = () => {
  hasError.value = false
  errorMessage.value = ''
}

const closeTab = () => {
  if (props.tabKey) {
    emit('close', props.tabKey)
  }
  resetError()
}
</script>

<style lang="less" scoped>
.tab-error-boundary {
  height: 100%;
  overflow: auto;
}
</style>
