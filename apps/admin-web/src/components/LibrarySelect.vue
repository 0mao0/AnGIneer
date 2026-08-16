<template>
  <a-select
    :value="store.libraryId"
    :loading="store.loading"
    style="min-width: 160px"
    @change="handleChange"
  >
    <a-select-option v-for="lib in store.libraries" :key="lib.id" :value="lib.id">
      {{ lib.name || lib.id }}（{{ lib.id }}）
    </a-select-option>
  </a-select>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useLibraryStore } from '@/stores/library'

const store = useLibraryStore()

onMounted(() => {
  if (store.libraries.length === 0) {
    store.loadLibraries()
  }
})

function handleChange(value: string) {
  store.setLibrary(value)
}
</script>
