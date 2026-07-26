<template>
  <div class="project-view">
    <a-card :title="projectName || '项目详情'" :bordered="false">
      <a-descriptions :column="1" size="small">
        <a-descriptions-item label="项目 ID">{{ projectId || '-' }}</a-descriptions-item>
        <a-descriptions-item label="项目路径">{{ path || '-' }}</a-descriptions-item>
      </a-descriptions>
    </a-card>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  projectId?: string
  projectName?: string
  path?: string
}>()
</script>

<style lang="less" scoped>
.project-view {
  height: 100%;
  padding: 16px;
  overflow: auto;
}
</style>
