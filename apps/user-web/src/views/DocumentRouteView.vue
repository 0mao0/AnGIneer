<template>
  <!-- 深链落地页：把 /document/:docId?library=<id> 的路由参数喂给 DocumentView。
       DocumentView 本体只吃 props（无 useRoute），此处是 URL→props 的唯一边界，
       保持 DocumentView 既能被 ChatHome 侧栏以 props 复用、又能被深链直达。 -->
  <DocumentView :doc-id="docId" :library-id="libraryId" />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import DocumentView from './DocumentView.vue'

const route = useRoute()
const docId = computed(() => String(route.params.docId || ''))
const libraryId = computed(() => String(route.query.library || 'default'))
</script>
