<template>
  <div class="home-view">
    <a-result title="欢迎使用 AnGIneer" sub-title="工程智能辅助设计平台">
      <template #extra>
        <a-space>
          <a-button type="primary" @click="openKnowledge">打开知识库</a-button>
          <a-button @click="openSOP">查看 SOP</a-button>
        </a-space>
      </template>
    </a-result>
    
    <a-divider />
    
    <a-row :gutter="16" class="quick-actions">
      <a-col :xs="24" :sm="12" :md="8">
        <a-card hoverable @click="openKnowledge">
          <template #cover>
            <div class="card-icon"><BookOutlined /></div>
          </template>
          <a-card-meta title="知识库" description="浏览工程规范、标准文档" />
        </a-card>
      </a-col>
      <a-col :xs="24" :sm="12" :md="8">
        <a-card hoverable @click="openSOP">
          <template #cover>
            <div class="card-icon"><ApiOutlined /></div>
          </template>
          <a-card-meta title="SOP 流程" description="执行标准作业流程" />
        </a-card>
      </a-col>
      <a-col :xs="24" :sm="12" :md="8">
        <a-card hoverable @click="openGIS">
          <template #cover>
            <div class="card-icon"><EnvironmentOutlined /></div>
          </template>
          <a-card-meta title="GIS 视图" description="地理信息可视化" />
        </a-card>
      </a-col>
    </a-row>
  </div>
</template>

<script setup lang="ts">
import { BookOutlined, ApiOutlined, EnvironmentOutlined } from '@ant-design/icons-vue'

const emit = defineEmits<{
  'navigate-section': [section: 'project' | 'knowledge' | 'sop' | 'gis']
}>()

const openKnowledge = () => {
  emit('navigate-section', 'knowledge')
}

const openSOP = () => {
  emit('navigate-section', 'sop')
}

const openGIS = () => {
  emit('navigate-section', 'gis')
}
</script>

<style lang="less" scoped>
.home-view {
  padding: 24px;
  height: 100%;
  overflow-y: auto;
}

.quick-actions {
  margin-top: 24px;
}

.card-icon {
  height: 120px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 48px;
  color: var(--primary-color);
  background: linear-gradient(135deg, var(--bg-tertiary) 0%, var(--bg-primary) 100%);
}
</style>
