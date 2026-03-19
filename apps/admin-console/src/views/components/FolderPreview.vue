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
        :before-upload="beforeUpload"
        :accept="getAccept()"
      >
        <a-button type="primary">
          <UploadOutlined /> 上传文件
        </a-button>
      </a-upload>
    </a-space>
  </div>
</template>

<script setup lang="ts">
import { FolderOutlined, UploadOutlined } from '@ant-design/icons-vue'
import type { KnowledgeTreeNode } from '@angineer/docs-ui'

/**
 * 文件夹预览组件
 * 显示文件夹的基本信息和上传功能
 */
interface Props {
  /** 文件夹节点数据 */
  node: KnowledgeTreeNode
  /** 子文档数量 */
  childCount: number
  /** 允许上传的文件类型 */
  allowedFileTypes?: string[]
}

const props = withDefaults(defineProps<Props>(), {
  allowedFileTypes: () => ['.pdf']
})

const emit = defineEmits<{
  upload: [file: File, folderId: string]
}>()

/**
 * 验证文件类型是否允许上传
 * @param file 文件对象
 * @returns 是否允许上传
 */
const validateFileType = (file: File): boolean => {
  if (!props.allowedFileTypes || props.allowedFileTypes.length === 0) {
    return true
  }
  const fileName = file.name.toLowerCase()
  return props.allowedFileTypes.some(ext => fileName.endsWith(ext.toLowerCase()))
}

/**
 * 处理文件上传前的验证
 * @param file 文件对象
 * @returns 是否继续上传
 */
const beforeUpload = (file: File): boolean => {
  if (validateFileType(file)) {
    emit('upload', file, props.node.key)
    return false // 阻止自动上传，由父组件处理
  }
  return false
}

/**
 * 获取 accept 属性值
 * @returns accept 字符串
 */
const getAccept = (): string => {
  return props.allowedFileTypes?.join(',') || '.pdf'
}
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
