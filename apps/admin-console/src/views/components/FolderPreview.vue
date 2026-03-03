<template>
  <!-- 文件夹预览组件 - 显示文件夹信息和上传按钮 -->
  <div class="folder-info">
    <FolderOutlined class="big-icon folder" />
    <h3>{{ node.title }}</h3>
    <p>包含 {{ childCount }} 个文档</p>
    <a-space>
      <a-upload
        :multiple="true"
        :show-upload-list="false"
        :before-upload="(file: File) => $emit('upload', file, node.key)"
        accept=".pdf"
      >
        <a-button type="primary">
          <UploadOutlined /> 上传 PDF
        </a-button>
      </a-upload>
    </a-space>
  </div>
</template>

<script setup lang="ts">
import { FolderOutlined, UploadOutlined } from '@ant-design/icons-vue'
import type { TreeNode } from '@angineer/docs-ui'

/**
 * 文件夹预览组件
 * 显示文件夹的基本信息和上传功能
 */
interface Props {
  /** 文件夹节点数据 */
  node: TreeNode
  /** 子文档数量 */
  childCount: number
}

defineProps<Props>()

defineEmits<{
  upload: [file: File, folderId: string]
}>()
</script>

<style lang="less" scoped>
.folder-info {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  padding: 24px;
  text-align: center;

  .big-icon {
    font-size: 64px;
    margin-bottom: 16px;

    &.folder {
      color: #faad14;
    }

    &.file {
      color: #ff4d4f;
    }
  }

  h3 {
    margin: 0 0 8px;
    font-size: 18px;
  }

  p {
    color: #8c8c8c;
    margin-bottom: 16px;
  }
}

// Dark mode
:global(.dark-mode) {
  .folder-info {
    h3 {
      color: rgba(255, 255, 255, 0.85);
    }

    p {
      color: rgba(255, 255, 255, 0.45);
    }
  }
}
</style>
