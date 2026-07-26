<template>
  <div class="project-sidebar">
    <div class="project-header">
      <a-button type="primary" block @click="showCreateModal = true">
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
        <template #emptyText>
          <EmptyState
            title="暂无项目"
            description="点击上方按钮新建第一个项目"
          />
        </template>
      </a-list>
    </div>

    <a-modal
      v-model:open="showCreateModal"
      title="新建项目"
      ok-text="创建"
      cancel-text="取消"
      @ok="handleCreate"
    >
      <a-form layout="vertical">
        <a-form-item label="项目名称" required>
          <a-input v-model:value="newProject.name" placeholder="如：某港总体规划" />
        </a-form-item>
        <a-form-item label="项目路径">
          <a-input v-model:value="newProject.path" placeholder="如：D:/Projects/harbor-plan" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { PlusOutlined, FolderOutlined } from '@ant-design/icons-vue'
import { message } from 'ant-design-vue'
import { createResourceNodeFromProject, type ProjectItem } from '@angineer/docs-ui'
import { useResourceOpen } from '@/composables/useResourceOpen'
import { EmptyState } from '@angineer/ui-kit'

const { openResource } = useResourceOpen()

const projectList = ref<ProjectItem[]>([])

const showCreateModal = ref(false)
const newProject = reactive({ name: '', path: '' })

const handleCreate = () => {
  if (!newProject.name.trim()) {
    message.warning('请填写项目名称')
    return
  }
  message.info('项目创建功能开发中')
  showCreateModal.value = false
  newProject.name = ''
  newProject.path = ''
}

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
