<template>
  <div class="doc-preview" :class="{ 'dark-mode': isDark }">
    <div class="doc-actions-bar">
      <a-space>
        <a-button
          v-if="node.status === 'pending' || node.status === 'failed'"
          type="primary"
          @click="$emit('parse', node)"
        >
          <FileSearchOutlined /> 开始解析
        </a-button>
        <a-select
          :value="strategyValue"
          style="width: 180px"
          @change="onStrategyChange"
        >
          <a-select-option value="A_structured">A 自研结构化</a-select-option>
          <a-select-option value="B_mineru_rag">B MinerU-RAG</a-select-option>
          <a-select-option value="C_pageindex">C PageIndex</a-select-option>
        </a-select>
        <a-button
          v-if="node.status === 'completed'"
          @click="editable = !editable"
        >
          {{ editable ? '只读' : '编辑 Markdown' }}
        </a-button>
        <a-button
          v-if="node.status === 'completed' && editable"
          type="primary"
          @click="saveMarkdown"
        >
          保存
        </a-button>
        <a-button
          v-if="node.status === 'completed'"
          @click="emit('rebuild-structured')"
        >
          重建结构化索引
        </a-button>
        <a-switch
          :checked="node.visible"
          :checked-children="'已共享'"
          :un-checked-children="'本地'"
          @change="$emit('toggle-visible', node)"
        />
      </a-space>
      <div v-if="node.status === 'processing'" class="processing-row">
        <a-progress
          :percent="progressPercent"
          :status="node.parseError ? 'exception' : 'active'"
          size="small"
          class="processing-progress"
        />
        <span class="progress-text">{{ stageText }}</span>
      </div>
      <div v-if="node.status === 'completed'" class="structured-stats">
        <a-tag color="blue">总条目 {{ structuredTotal }}</a-tag>
        <a-tag color="green">标题 {{ strategyTypeCount('heading') }}</a-tag>
        <a-tag color="purple">条款 {{ strategyTypeCount('clause') }}</a-tag>
        <a-tag color="gold">表格 {{ strategyTypeCount('table') }}</a-tag>
        <a-tag color="cyan">图片 {{ strategyTypeCount('image') }}</a-tag>
      </div>
    </div>

    <div class="preview-content">
      <div v-if="node.status === 'completed'" class="split-preview">
        <div class="split-pane split-pane-left">
          <div class="pane-title">B1 原文</div>
          <div class="file-preview">
            <iframe
              v-if="isPdf"
              :src="fileUrl"
              class="pdf-viewer"
              frameborder="0"
            />
            <div v-else-if="isOffice" class="office-preview">
              <iframe
                :src="officePreviewUrl"
                class="office-viewer"
                frameborder="0"
              />
            </div>
            <img
              v-else-if="isImage"
              :src="fileUrl"
              class="image-viewer"
              alt="文档预览"
            />
            <pre v-else-if="isText" class="text-viewer">{{ textContent }}</pre>
            <a-empty v-else description="暂不支持该格式预览，请下载后查看">
              <template #extra>
                <a-button type="primary" @click="downloadFile">下载文件</a-button>
              </template>
            </a-empty>
          </div>
        </div>
        <div class="split-pane split-pane-right">
          <div class="pane-title">B2 Markdown</div>
          <a-textarea
            v-model:value="editableContent"
            :readonly="!editable"
            :auto-size="{ minRows: 18, maxRows: 32 }"
            class="markdown-editor"
          />
        </div>
      </div>
      <div v-else-if="node.filePath || node.file_path" class="file-preview">
        <iframe
          v-if="isPdf"
          :src="fileUrl"
          class="pdf-viewer"
          frameborder="0"
        />
        <div v-else-if="isOffice" class="office-preview">
          <iframe
            :src="officePreviewUrl"
            class="office-viewer"
            frameborder="0"
          />
        </div>
        <img
          v-else-if="isImage"
          :src="fileUrl"
          class="image-viewer"
          alt="文档预览"
        />
        <pre v-else-if="isText" class="text-viewer">{{ textContent }}</pre>
        <a-empty v-else description="暂不支持该格式预览，请下载后查看">
          <template #extra>
            <a-button type="primary" @click="downloadFile">下载文件</a-button>
          </template>
        </a-empty>
      </div>
      <a-empty v-else :description="node.status === 'processing' ? '正在解析中...' : '请先解析文档'" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { FileSearchOutlined } from '@ant-design/icons-vue'
import type { TreeNode } from '@angineer/docs-ui'
import type { SmartTreeNode } from '@angineer/docs-ui'
import { useTheme } from '@angineer/ui-kit'

/**
 * 文档预览组件
 * 显示文档详情、操作按钮和解析后的内容
 */
interface Props {
  node: TreeNode
  content: string
  structuredStats?: Record<string, any>
}

const props = withDefaults(defineProps<Props>(), {})
const { isDark } = useTheme()

const emit = defineEmits<{
  parse: [node: SmartTreeNode]
  'toggle-visible': [node: SmartTreeNode]
  'save-content': [content: string]
  'change-strategy': [strategy: 'A_structured' | 'B_mineru_rag' | 'C_pageindex']
  'rebuild-structured': []
}>()

/** 获取文件路径 */
const filePath = computed(() => props.node.filePath || props.node.file_path || '')
const progressPercent = computed(() => Number(props.node.parseProgress || 0))
const stageText = computed(() => {
  if (props.node.parseError) return `解析失败：${props.node.parseError}`
  const stage = props.node.parseStage || 'processing'
  const stageMap: Record<string, string> = {
    queued: '任务排队中',
    initializing: '正在初始化',
    mineru_processing: 'MinerU 解析中',
    reading_markdown: '读取 Markdown',
    saving_markdown: '保存解析结果',
    completed: '解析完成',
    failed: '解析失败'
  }
  return stageMap[stage] || stage
})
const strategyValue = computed(() => props.node.strategy || 'A_structured')
const structuredTotal = computed(() => Number(props.structuredStats?.total || 0))
const strategyTypeCount = (type: string) => {
  const strategy = strategyValue.value
  return Number(props.structuredStats?.strategies?.[strategy]?.[type] || 0)
}

/** 获取文件扩展名 */
const fileExtension = computed(() => {
  const path = filePath.value
  if (!path) return ''
  const match = path.match(/\.([a-zA-Z0-9]+)$/)
  return match ? match[1].toLowerCase() : ''
})

/** 判断是否为 PDF */
const isPdf = computed(() => fileExtension.value === 'pdf')

/** 判断是否为 Office 文档 */
const isOffice = computed(() => {
  const officeExts = ['doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx']
  return officeExts.includes(fileExtension.value)
})

/** 判断是否为图片 */
const isImage = computed(() => {
  const imageExts = ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'svg']
  return imageExts.includes(fileExtension.value)
})

/** 判断是否为文本文件 */
const isText = computed(() => {
  const textExts = ['txt', 'md', 'json', 'xml', 'csv', 'log', 'js', 'ts', 'py', 'java', 'cpp', 'c', 'h', 'html', 'css']
  return textExts.includes(fileExtension.value)
})

/** 文件 URL */
const fileUrl = computed(() => {
  if (!filePath.value) return ''
  // 如果路径已经是完整 URL，直接返回
  if (filePath.value.startsWith('http')) return filePath.value
  return `/api/files?path=${encodeURIComponent(filePath.value)}`
})

/** Office 文档预览 URL（使用微软在线预览服务） */
const officePreviewUrl = computed(() => {
  if (!fileUrl.value) return ''
  return `https://view.officeapps.live.com/op/embed.aspx?src=${encodeURIComponent(window.location.origin + fileUrl.value)}`
})

/** 文本文件内容 */
const textContent = ref('')
const editable = ref(false)
const editableContent = ref('')

/** 加载文本文件内容 */
const loadTextContent = async () => {
  if (!isText.value || !fileUrl.value) return
  try {
    const response = await fetch(fileUrl.value)
    textContent.value = await response.text()
  } catch (error) {
    textContent.value = '加载文件内容失败'
  }
}

const saveMarkdown = () => {
  emit('save-content', editableContent.value)
}

const onStrategyChange = (value: 'A_structured' | 'B_mineru_rag' | 'C_pageindex') => {
  emit('change-strategy', value)
}

/** 下载文件 */
const downloadFile = () => {
  if (!fileUrl.value) return
  const link = document.createElement('a')
  link.href = fileUrl.value
  link.download = props.node.title
  link.click()
}

/** 监听文件路径变化，加载文本内容 */
watch(filePath, () => {
  if (isText.value) {
    loadTextContent()
  }
}, { immediate: true })

watch(() => props.content, (value) => {
  editableContent.value = value || ''
}, { immediate: true })
</script>

<style lang="less" scoped>
.doc-preview {
  display: flex;
  flex-direction: column;
  height: 100%;

  .doc-actions-bar {
    padding: 12px 16px;
    border-bottom: 1px solid #f0f0f0;
    background: #f5f7fa;
    flex-shrink: 0;
  }

  .preview-content {
    flex: 1;
    overflow: auto;
    padding: 0;

    .split-preview {
      display: flex;
      height: 100%;
      min-height: 500px;

      .split-pane {
        flex: 1;
        min-width: 0;
        display: flex;
        flex-direction: column;
      }

      .split-pane-left {
        border-right: 1px solid #f0f0f0;
      }

      .pane-title {
        font-size: 12px;
        color: #8c8c8c;
        padding: 8px 12px;
        border-bottom: 1px solid #f0f0f0;
      }
    }

    .file-preview {
      height: 100%;

      .pdf-viewer {
        width: 100%;
        height: 100%;
        min-height: 500px;
      }

      .office-preview {
        width: 100%;
        height: 100%;
        min-height: 500px;

        .office-viewer {
          width: 100%;
          height: 100%;
          min-height: 500px;
        }
      }

      .image-viewer {
        max-width: 100%;
        max-height: 100%;
        display: block;
        margin: 0 auto;
      }

      .text-viewer {
        background: #f6f8fa;
        padding: 16px;
        border-radius: 6px;
        overflow: auto;
        max-height: 100%;
        font-size: 13px;
        line-height: 1.6;
        white-space: pre-wrap;
        word-wrap: break-word;
        margin: 16px;
      }
    }

    .markdown-preview {
      padding: 16px;

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

    .markdown-editor {
      margin: 12px;
      flex: 1;
    }
  }

  .processing-row {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 6px;
  }

  .processing-progress {
    width: 240px;
    margin: 0;
  }

  .progress-text {
    color: #8c8c8c;
    font-size: 12px;
    line-height: 1.2;
  }

  .structured-stats {
    margin-top: 8px;
  }

  &.dark-mode {
    .doc-actions-bar {
      background: #1f1f1f !important;
      border-bottom-color: #303030 !important;
    }

    .doc-actions-bar :deep(.ant-select .ant-select-selector) {
      background: #262626 !important;
      border-color: #434343 !important;
      color: rgba(255, 255, 255, 0.88) !important;
    }

    .doc-actions-bar :deep(.ant-select .ant-select-selection-item) {
      color: rgba(255, 255, 255, 0.88) !important;
    }

    .doc-actions-bar :deep(.ant-select .ant-select-arrow) {
      color: rgba(255, 255, 255, 0.65) !important;
    }

    .doc-actions-bar :deep(.ant-select.ant-select-focused .ant-select-selector) {
      border-color: #4096ff !important;
      box-shadow: 0 0 0 2px rgba(24, 144, 255, 0.2) !important;
    }
  }
}

// Dark mode
:global(.dark-mode) {
  .doc-preview {
    .doc-actions-bar {
      background: #1f1f1f !important;
      border-bottom-color: #303030 !important;
    }

    .doc-actions-bar :deep(.ant-select .ant-select-selector) {
      background: #262626 !important;
      border-color: #434343 !important;
      color: rgba(255, 255, 255, 0.88) !important;
    }

    .doc-actions-bar :deep(.ant-select .ant-select-selection-item) {
      color: rgba(255, 255, 255, 0.88) !important;
    }

    .doc-actions-bar :deep(.ant-select .ant-select-arrow) {
      color: rgba(255, 255, 255, 0.65) !important;
    }

    .doc-actions-bar :deep(.ant-select.ant-select-focused .ant-select-selector) {
      border-color: #4096ff !important;
      box-shadow: 0 0 0 2px rgba(24, 144, 255, 0.2) !important;
    }

    .preview-content {
      .split-preview {
        .split-pane-left,
        .pane-title {
          border-color: #303030;
        }
      }

      .file-preview {
        .text-viewer {
          background: #272727;
          color: rgba(255, 255, 255, 0.85);
        }
      }

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
