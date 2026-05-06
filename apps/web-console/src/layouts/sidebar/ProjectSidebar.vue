<template>
  <div class="project-sidebar">
    <div class="project-header">
      <a-button type="primary" block>
        <template #icon><PlusOutlined /></template>
        新建项目
      </a-button>
    </div>
    <div class="project-list">
      <a-list :data-source="projectList" size="small">
        <template #renderItem="{ item }">
          <a-list-item @click="openProject(item)">
            <a-list-item-meta :title="item.name" :description="item.path">
              <template #avatar>
                <FolderOutlined />
              </template>
            </a-list-item-meta>
          </a-list-item>
        </template>
      </a-list>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { PlusOutlined, FolderOutlined } from '@ant-design/icons-vue'
import { createResourceNodeFromProject, type ProjectItem } from '@angineer/docs-ui'
import { useResourceOpen } from '@/composables/useResourceOpen'

const { openResource } = useResourceOpen()

const projectList = ref<ProjectItem[]>([
  { id: 'proj-1', name: '某港总体规划', path: 'D:/Projects/harbor-plan' },
  { id: 'proj-2', name: '航道扩建工程', path: 'D:/Projects/channel-expansion' }
])

const openProject = (project: ProjectItem) => {
  const resource = createResourceNodeFromProject(project)
  openResource(resource)
}
</script>

<style lang="less" scoped>
.project-sidebar {
  height: 100%;
  padding: 12px;
}

.project-header {
  margin-bottom: 12px;
}

.project-list {
  :deep(.ant-list-item) {
    cursor: pointer;
    &:hover {
      background: var(--bg-tertiary);
    }
  }
}
</style>
