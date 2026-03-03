<template>
  <!-- 知识树节点项组件 - 显示树节点的图标、名称、状态标签和操作按钮 -->
  <div
    class="tree-node"
    :class="{
      'is-folder': data.isFolder,
      'is-processing': data.status === 'processing' || data.status === 'uploading',
      'is-completed': data.status === 'completed',
      'is-failed': data.status === 'failed'
    }"
  >
    <!-- 左侧：共享状态 Tag -->
    <div class="node-left">
      <a-tag
        v-if="!data.isFolder"
        :color="data.visible ? 'green' : 'default'"
        size="small"
        class="share-tag"
      >
        {{ data.visible ? '共享' : '本地' }}
      </a-tag>
    </div>

    <!-- 中间：图标和名称 -->
    <div class="node-content">
      <FolderOutlined v-if="data.isFolder" class="folder-icon" />
      <FilePdfOutlined v-else class="file-icon" />
      <span class="node-title" :title="data.title">{{ data.title }}</span>
      <a-tag v-if="data.status === 'uploading'" color="processing" size="small" class="status-tag">
        上传中
      </a-tag>
      <a-tag v-else-if="data.status === 'processing'" color="processing" size="small" class="status-tag">
        解析中
      </a-tag>
      <a-tag v-else-if="data.status === 'failed'" color="error" size="small" class="status-tag">
        失败
      </a-tag>
    </div>

    <!-- 右侧：操作按钮 -->
    <div class="node-actions">
      <!-- 文件夹操作 -->
      <template v-if="data.isFolder">
        <a-tooltip title="重命名">
          <EditOutlined class="action-icon" @click.stop="$emit('rename', data)" />
        </a-tooltip>
        <a-tooltip title="添加子文件夹">
          <FolderAddOutlined class="action-icon" @click.stop="$emit('create-sub-folder', data.key)" />
        </a-tooltip>
        <a-tooltip title="删除">
          <DeleteOutlined class="action-icon delete" @click.stop="$emit('delete', data.key)" />
        </a-tooltip>
      </template>
      <!-- 文件操作 -->
      <template v-else>
        <a-tooltip title="修改名称">
          <EditOutlined class="action-icon" @click.stop="$emit('rename', data)" />
        </a-tooltip>
        <a-tooltip title="查看详情">
          <EyeOutlined class="action-icon" @click.stop="$emit('view-detail', data)" />
        </a-tooltip>
        <a-tooltip title="删除">
          <DeleteOutlined class="action-icon delete" @click.stop="$emit('delete', data.key)" />
        </a-tooltip>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import {
  FolderOutlined,
  FilePdfOutlined,
  EditOutlined,
  FolderAddOutlined,
  DeleteOutlined,
  EyeOutlined
} from '@ant-design/icons-vue'
import type { TreeNode } from '@angineer/docs-ui'

/**
 * 知识树节点项组件
 * 显示节点的图标、名称、状态标签和操作按钮
 */
interface Props {
  /** 节点数据 */
  data: TreeNode
}

defineProps<Props>()

defineEmits<{
  rename: [node: TreeNode]
  'create-sub-folder': [key: string]
  delete: [key: string]
  'view-detail': [node: TreeNode]
}>()
</script>

<style lang="less" scoped>
.tree-node {
  display: flex;
  align-items: center;
  width: 100%;
  gap: 4px;

  &.is-folder {
    font-weight: 500;
  }

  &.is-processing {
    .node-title {
      color: #8c8c8c;
    }
  }

  &.is-failed {
    .node-title {
      color: #ff4d4f;
    }
  }

  .node-left {
    flex-shrink: 0;

    .share-tag {
      font-size: 10px;
      padding: 0 4px;
      line-height: 16px;
      margin: 0;
    }
  }

  .node-content {
    display: flex;
    align-items: center;
    gap: 4px;
    flex: 1;
    min-width: 0;
    overflow: hidden;

    .folder-icon {
      color: #faad14;
      font-size: 14px;
      flex-shrink: 0;
    }

    .file-icon {
      color: #ff4d4f;
      font-size: 14px;
      flex-shrink: 0;
    }

    .node-title {
      flex: 1;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: 13px;
      min-width: 0;
    }

    .status-tag {
      font-size: 10px;
      padding: 0 4px;
      line-height: 16px;
      flex-shrink: 0;
    }
  }

  .node-actions {
    display: flex;
    align-items: center;
    gap: 2px;
    flex-shrink: 0;
    opacity: 0;
    transition: opacity 0.2s;

    .action-icon {
      font-size: 12px;
      color: #8c8c8c;
      cursor: pointer;
      padding: 2px;
      border-radius: 3px;
      transition: all 0.2s;

      &:hover {
        color: #1890ff;
        background: rgba(24, 144, 255, 0.1);
      }

      &.delete:hover {
        color: #ff4d4f;
        background: rgba(255, 77, 79, 0.1);
      }
    }
  }

  &:hover .node-actions {
    opacity: 1;
  }
}

// Dark mode
:global(.dark-mode) {
  .tree-node {
    .node-content {
      .node-title {
        color: rgba(255, 255, 255, 0.85);
      }
    }

    &.is-processing {
      .node-title {
        color: rgba(255, 255, 255, 0.45);
      }
    }
  }
}
</style>
