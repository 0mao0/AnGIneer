<template>
  <!-- 文档预览组件 - 显示文档详情、操作按钮和解析内容 -->
  <div class="doc-preview">
    <!-- 文档头部信息 -->
    <div class="doc-header">
      <FilePdfOutlined class="big-icon file" />
      <div class="doc-meta">
        <h3>{{ node.title }}</h3>
        <a-space>
          <a-tag :color="getStatusColor(node.status)">
            {{ getStatusText(node.status) }}
          </a-tag>
          <a-tag :color="node.visible ? 'green' : 'default'">
            {{ node.visible ? '已共享' : '本地' }}
          </a-tag>
        </a-space>
      </div>
    </div>

    <!-- 操作按钮栏 -->
    <div class="doc-actions-bar">
      <a-space>
        <a-button
          v-if="node.status === 'pending' || node.status === 'failed'"
          type="primary"
          @click="$emit('parse', node.key)"
        >
          <FileSearchOutlined /> 开始解析
        </a-button>
        <a-button @click="$emit('view', node.key)">
          <EyeOutlined /> 查看原文
        </a-button>
        <a-button @click="$emit('toggle-visible', node.key, !node.visible)">
          <ShareAltOutlined /> {{ node.visible ? '取消共享' : '共享到前台' }}
        </a-button>
      </a-space>
    </div>

    <!-- 预览内容 -->
    <div class="preview-content">
      <a-empty
        v-if="node.status !== 'completed'"
        :description="node.status === 'processing' ? '正在解析中...' : '请先解析文档'"
      />
      <div v-else class="markdown-preview">
        <pre v-if="content">{{ content }}</pre>
        <a-empty v-else description="暂无预览内容" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import {
  FilePdfOutlined,
  FileSearchOutlined,
  EyeOutlined,
  ShareAltOutlined
} from '@ant-design/icons-vue'
import type { TreeNode } from '@angineer/docs-ui'

/**
 * 文档预览组件
 * 显示文档详情、操作按钮和解析后的内容
 */
interface Props {
  /** 文档节点数据 */
  node: TreeNode
  /** 文档解析内容 */
  content: string
  /** 获取状态颜色 */
  getStatusColor?: (status: string) => string
  /** 获取状态文本 */
  getStatusText?: (status: string) => string
}

withDefaults(defineProps<Props>(), {
  getStatusColor: (status: string) => {
    const colors: Record<string, string> = {
      pending: 'default',
      uploading: 'processing',
      processing: 'processing',
      completed: 'success',
      failed: 'error'
    }
    return colors[status] || 'default'
  },
  getStatusText: (status: string) => {
    const texts: Record<string, string> = {
      pending: '待处理',
      uploading: '上传中',
      processing: '解析中',
      completed: '已完成',
      failed: '解析失败'
    }
    return texts[status] || '未知'
  }
})

defineEmits<{
  parse: [docId: string]
  view: [docId: string]
  'toggle-visible': [docId: string, visible: boolean]
}>()
</script>

<style lang="less" scoped>
.doc-preview {
  .doc-header {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 16px;
    border-bottom: 1px solid #f0f0f0;

    .big-icon {
      font-size: 48px;

      &.file {
        color: #ff4d4f;
      }
    }

    .doc-meta {
      flex: 1;
      min-width: 0;

      h3 {
        margin: 0 0 8px;
        font-size: 16px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
    }
  }

  .doc-actions-bar {
    padding: 12px 16px;
    border-bottom: 1px solid #f0f0f0;
    background: #fafafa;
  }

  .preview-content {
    padding: 16px;

    .markdown-preview {
      pre {
        background: #f6f8fa;
        padding: 16px;
        border-radius: 6px;
        overflow: auto;
        max-height: 400px;
        font-size: 13px;
        line-height: 1.6;
      }
    }
  }
}

// Dark mode
:global(.dark-mode) {
  .doc-preview {
    .doc-header {
      border-bottom-color: #303030;
    }

    .doc-actions-bar {
      background: #272727;
      border-bottom-color: #303030;
    }

    .preview-content {
      .markdown-preview {
        pre {
          background: #272727;
          color: rgba(255, 255, 255, 0.85);
        }
      }
    }
  }
}
</style>
