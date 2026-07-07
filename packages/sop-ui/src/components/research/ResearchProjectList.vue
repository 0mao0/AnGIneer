<template>
  <div class="research-project-list">
    <div class="project-list-header">
      <a-button type="primary" size="small" @click="emit('create-project')">
        <template #icon><PlusOutlined /></template>
        新建项目
      </a-button>
      <a-tooltip title="刷新">
        <a-button type="text" size="small" @click="emit('refresh')">
          <template #icon><ReloadOutlined /></template>
        </a-button>
      </a-tooltip>
    </div>

    <a-spin :spinning="loading">
      <div class="project-items">
        <div
          v-for="proj in projects"
          :key="proj.project_id"
          class="project-item"
          :class="{ selected: proj.project_id === selectedProjectId }"
          @click="emit('select-project', proj.project_id)"
        >
          <div class="project-title">{{ proj.title }}</div>
          <div class="project-doc">{{ proj.doc_title }}</div>
        </div>

        <div v-if="!projects.length && !loading" class="project-empty">
          <FileSearchOutlined class="empty-icon" />
          <span>暂无研究项目</span>
        </div>
      </div>
    </a-spin>
  </div>
</template>

<script setup lang="ts">
import type { ResearchProject } from '../../types/sopResearch'
import { PlusOutlined, ReloadOutlined, FileSearchOutlined } from '@ant-design/icons-vue'

interface Props {
  projects: ResearchProject[]
  selectedProjectId: string
  loading: boolean
}

defineProps<Props>()

const emit = defineEmits<{
  'select-project': [projectId: string]
  'create-project': []
  refresh: []
}>()
</script>

<style lang="less" scoped>
.research-project-list {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.project-list-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;
}

.project-items {
  flex: 1;
  overflow-y: auto;
  padding: 4px;
}

.project-item {
  padding: 10px 12px;
  margin: 2px 0;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.2s;

  &:hover {
    background: var(--bg-tertiary);
  }

  &.selected {
    background: var(--primary-color);
    color: #fff;

    .project-doc {
      color: rgba(255, 255, 255, 0.75);
    }
  }
}

.project-title {
  font-weight: 500;
  font-size: 13px;
  margin-bottom: 2px;
}

.project-doc {
  font-size: 12px;
  color: var(--text-secondary);
}

.project-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 16px;
  color: var(--text-secondary);
  gap: 8px;

  .empty-icon {
    font-size: 32px;
    opacity: 0.35;
  }
}
</style>
