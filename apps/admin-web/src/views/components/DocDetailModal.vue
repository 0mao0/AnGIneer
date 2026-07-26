<template>
  <!-- 文档详情弹窗组件 - 显示文档详细信息和操作 -->
  <a-modal
    :open="visible"
    title="文档详情"
    width="600px"
    :footer="null"
    @update:open="$emit('update:visible', $event)"
  >
    <a-descriptions v-if="doc" :column="1" bordered>
      <a-descriptions-item label="文档名称">{{ doc.title }}</a-descriptions-item>
      <a-descriptions-item label="文件类型">PDF 文档</a-descriptions-item>
      <a-descriptions-item label="解析状态">
        <a-tag :color="getStatusColor(doc.status || 'pending')">{{ getStatusText(doc.status || 'pending') }}</a-tag>
      </a-descriptions-item>
      <a-descriptions-item label="共享状态">
        <a-switch
          :checked="doc.visible"
          @change="(checked: boolean) => doc && $emit('toggle-visible', { ...doc, visible: checked })"
        />
        <span style="margin-left: 8px">{{ doc.visible ? '已共享到前台' : '仅本地可见' }}</span>
      </a-descriptions-item>
      <a-descriptions-item label="所属文件夹">
        {{ doc.parentId ? getFolderName(doc.parentId) : '根目录' }}
      </a-descriptions-item>
    </a-descriptions>

    <div class="detail-actions">
      <a-space>
        <a-button type="primary" @click="doc && $emit('view', doc)">
          <EyeOutlined /> 查看文档
        </a-button>
        <a-button danger @click="handleDelete">
          <DeleteOutlined /> 删除文档
        </a-button>
      </a-space>
    </div>
  </a-modal>
</template>

<script setup lang="ts">
import { EyeOutlined, DeleteOutlined } from '@ant-design/icons-vue'
import type { SmartTreeNode } from '@angineer/docs-ui'

/**
 * 文档详情弹窗组件
 * 显示文档的详细信息和操作按钮
 */
interface Props {
  /** 弹窗可见性 */
  visible: boolean
  /** 文档数据 */
  doc: SmartTreeNode | null
  /** 获取文件夹名称 */
  getFolderName: (folderId: string) => string
  /** 获取状态颜色 */
  getStatusColor: (status: string) => string
  /** 获取状态文本 */
  getStatusText: (status: string) => string
}

const props = defineProps<Props>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
  view: [node: SmartTreeNode]
  delete: [node: SmartTreeNode]
  'toggle-visible': [node: SmartTreeNode]
}>()

/** 处理删除事件并交给父组件统一确认。 */
const handleDelete = () => {
  if (!props.doc) return

  emit('delete', props.doc)
  emit('update:visible', false)
}
</script>

<style lang="less" scoped>
.detail-actions {
  margin-top: 16px;
  text-align: center;
}
</style>
