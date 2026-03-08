<template>
  <div class="doc-preview" :class="{ 'dark-mode': darkMode }">
    <div class="preview-content">
      <div class="split-preview">
        <div class="split-pane split-pane-left">
          <div class="pane-title pane-title-with-actions">
            <div class="pane-title-main">
              <span class="pane-title-prefix">B1</span>
              <span class="doc-name" :title="node.title">{{ node.title }}</span>
              <a-tag v-if="node.status === 'failed'" color="error" class="parse-state-tag">
                解析失败
              </a-tag>
              <a-tag v-else-if="node.status === 'processing'" color="processing" class="parse-state-tag">
                解析中 {{ progressPercent }}%
              </a-tag>
            </div>
            <div class="pane-actions-left">
              <a-button
                type="primary"
                :loading="node.status === 'processing'"
                @click="$emit('parse', node)"
                class="parse-btn action-btn"
              >
                {{ parseButtonText }}
              </a-button>
              <a-switch
                :checked="switchChecked"
                :checked-children="'共享'"
                :un-checked-children="'本地'"
                @change="onVisibleChange"
                class="visible-switch action-switch"
              />
            </div>
          </div>
          <div v-if="node.status === 'processing' || node.status === 'failed'" class="parse-progress-row">
            <a-progress
              :percent="progressPercent"
              :status="node.parseError ? 'exception' : 'active'"
              size="small"
              class="processing-progress"
            />
            <span class="progress-text">{{ stageText }}</span>
          </div>
          <div class="file-preview">
            <iframe
              v-if="isPdf"
              :src="pdfViewerUrl"
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
          <div class="pane-title pane-title-with-actions b2-pane-title">
            <a-tabs v-model:activeKey="activeTab" size="small" class="b2-tabs">
              <a-tab-pane key="preview" tab="解析结果" />
              <a-tab-pane key="markdown" tab="Markdown" />
            </a-tabs>
            <div class="pane-actions-right">
              <a-select
                v-if="hasParsedContent"
                :value="strategyValue"
                style="width: 160px"
                @change="onStrategyChange"
              >
                <a-select-option value="A_structured">A 结果</a-select-option>
                <a-select-option value="B_mineru_rag">B 结果</a-select-option>
                <a-select-option value="C_pageindex">C 结果</a-select-option>
              </a-select>
              <a-button
                type="primary"
                :loading="ingestStatusValue === 'processing'"
                :disabled="!canIngest"
                @click="triggerIngest"
                class="ingest-btn action-btn"
              >
                {{ ingestButtonText }}
              </a-button>
              <a-button
                v-if="showStatsAction"
                :icon="h(PieChartOutlined)"
                class="action-btn stats-btn"
                @click="statsModalVisible = true"
              />
            </div>
          </div>

          <div class="b2-content">
            <div v-if="activeTab === 'preview'" class="markdown-preview" v-html="renderedMarkdown" />
            <div v-else class="markdown-edit-wrap">
              <a-textarea
                v-model:value="editableContent"
                class="markdown-editor"
              />
              <div class="markdown-edit-actions">
                <a-button
                  type="primary"
                  :disabled="!isContentDirty"
                  class="action-btn"
                  @click="saveMarkdown"
                >
                  保存
                </a-button>
              </div>
            </div>
            <a-empty
              v-if="!hasParsedContent && activeTab === 'preview'"
              description="请先解析文档，解析完成后将显示结果"
              class="b2-empty"
            />
          </div>
        </div>
      </div>
    </div>

    <a-modal
      v-model:open="ingestModalVisible"
      :title="ingestStatusValue === 'processing' ? '格式化入库中' : '格式化入库结果'"
      :footer="null"
      :mask-closable="ingestStatusValue !== 'processing'"
      :closable="ingestStatusValue !== 'processing'"
    >
      <div class="ingest-modal-content">
        <a-progress
          :percent="ingestProgressPercent"
          :status="ingestProgressStatus"
          size="default"
        />
        <div class="ingest-stage">{{ ingestStageText }}</div>
        <div v-if="ingestStatusValue === 'completed'" class="ingest-result">
          总条目 {{ structuredTotal }}
        </div>
      </div>
    </a-modal>

    <a-modal
      v-model:open="statsModalVisible"
      title="入库分类统计"
      :footer="null"
    >
      <div class="stats-modal-content">
        <div class="stats-total">总条目：{{ structuredTotal }}</div>
        <div v-for="item in strategyStats" :key="item.key" class="stats-row">
          <span>{{ item.label }}</span>
          <a-tag color="blue">{{ item.value }}</a-tag>
        </div>
      </div>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { computed, h, ref, watch } from 'vue'
import { PieChartOutlined } from '@ant-design/icons-vue'
import type { SmartTreeNode } from '../../types/tree'
import type { TreeNode } from '../../composables/useKnowledgeTree'
import type { IngestStatus, KnowledgeStrategy, StructuredStats } from '../../types/knowledge'
import { getFileExtension, mapParseStageText } from '../../utils/knowledge'

interface Props {
  node: TreeNode
  content: string
  structuredStats?: StructuredStats
  ingestStatus?: IngestStatus
  ingestProgress?: number
  ingestStage?: string
  darkMode?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  darkMode: false
})

const emit = defineEmits<{
  parse: [node: SmartTreeNode]
  'toggle-visible': [node: SmartTreeNode]
  'save-content': [content: string]
  'change-strategy': [strategy: KnowledgeStrategy]
  'rebuild-structured': []
}>()

const filePath = computed(() => props.node.filePath || props.node.file_path || '')
const progressPercent = computed(() => Number(props.node.parseProgress || 0))
const ingestStatusValue = computed(() => props.ingestStatus || 'idle')
const ingestProgressPercent = computed(() => Number(props.ingestProgress || 0))
const activeTab = ref<'preview' | 'markdown'>('preview')
const ingestModalVisible = ref(false)
const statsModalVisible = ref(false)
const stageText = computed(() => mapParseStageText(props.node.parseStage, props.node.parseError))
const ingestProgressStatus = computed(() => {
  if (ingestStatusValue.value === 'failed') return 'exception'
  if (ingestStatusValue.value === 'completed') return 'success'
  return 'active'
})
const ingestStageText = computed(() => {
  if (ingestStatusValue.value === 'failed') {
    return props.ingestStage || '格式化入库失败'
  }
  if (ingestStatusValue.value === 'completed') {
    return props.ingestStage || '格式化入库完成'
  }
  return props.ingestStage || '正在格式化入库'
})
const strategyValue = computed(() => (props.node.strategy || 'A_structured') as KnowledgeStrategy)
const structuredTotal = computed(() => Number(props.structuredStats?.total || 0))
const hasParsedContent = computed(() => Boolean((props.content || '').trim()))
const parseButtonText = computed(() => {
  if (props.node.status === 'completed') return '重新解析'
  if (props.node.status === 'failed') return '重新解析'
  if (props.node.status === 'processing') return '解析中...'
  return '开始解析'
})
const ingestButtonText = computed(() => (structuredTotal.value > 0 ? '重新入库' : '格式化入库'))
const strategyTypeCount = (type: string) => {
  const strategy = strategyValue.value
  return Number(props.structuredStats?.strategies?.[strategy]?.[type] || 0)
}
const strategyStats = computed(() => ([
  { key: 'heading', label: '标题', value: strategyTypeCount('heading') },
  { key: 'clause', label: '条款', value: strategyTypeCount('clause') },
  { key: 'table', label: '表格', value: strategyTypeCount('table') },
  { key: 'image', label: '图片', value: strategyTypeCount('image') }
]))
const showStatsAction = computed(() => structuredTotal.value > 0 && ingestStatusValue.value !== 'processing')

const fileExtension = computed(() => getFileExtension(filePath.value))
const isPdf = computed(() => fileExtension.value === 'pdf')
const isOffice = computed(() => ['doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx'].includes(fileExtension.value))
const isImage = computed(() => ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'svg'].includes(fileExtension.value))
const isText = computed(() => ['txt', 'md', 'json', 'xml', 'csv', 'log', 'js', 'ts', 'py', 'java', 'cpp', 'c', 'h', 'html', 'css'].includes(fileExtension.value))

const fileUrl = computed(() => {
  if (!filePath.value) return ''
  if (filePath.value.startsWith('http')) return filePath.value
  return `/api/files?path=${encodeURIComponent(filePath.value)}`
})
const pdfViewerUrl = computed(() => {
  if (!fileUrl.value) return ''
  if (fileUrl.value.includes('#')) {
    return `${fileUrl.value}&view=FitH`
  }
  return `${fileUrl.value}#view=FitH`
})
const officePreviewUrl = computed(() => {
  if (!fileUrl.value) return ''
  return `https://view.officeapps.live.com/op/embed.aspx?src=${encodeURIComponent(window.location.origin + fileUrl.value)}`
})

const textContent = ref('')
const editableContent = ref('')
const switchChecked = ref(Boolean(props.node.visible))
const canIngest = computed(() => !isContentDirty.value)
const isContentDirty = computed(() => editableContent.value !== (props.content || ''))

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

const triggerIngest = () => {
  ingestModalVisible.value = true
  emit('rebuild-structured')
}

const onStrategyChange = (value: KnowledgeStrategy) => {
  emit('change-strategy', value)
}

const onVisibleChange = (checked: boolean) => {
  switchChecked.value = checked
  emit('toggle-visible', { ...props.node, visible: checked })
}

const downloadFile = () => {
  if (!fileUrl.value) return
  const link = document.createElement('a')
  link.href = fileUrl.value
  link.download = props.node.title
  link.click()
}

watch(filePath, () => {
  if (isText.value) {
    loadTextContent()
  }
}, { immediate: true })

watch(() => props.content, (value) => {
  editableContent.value = value || ''
}, { immediate: true })

watch(() => props.node.key, () => {
  activeTab.value = 'preview'
  ingestModalVisible.value = false
  statsModalVisible.value = false
})

watch(() => props.node.visible, (value) => {
  switchChecked.value = Boolean(value)
}, { immediate: true })

watch(ingestStatusValue, (value) => {
  if (value === 'processing') {
    ingestModalVisible.value = true
  }
})

const renderMarkdown = (content: string): string => {
  if (!content) return ''
  return content
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>')
    .replace(/\n/g, '<br/>')
}

const renderedMarkdown = computed(() => renderMarkdown(editableContent.value || props.content || ''))
</script>

<style lang="less" scoped>
.doc-preview {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #fff;

  .preview-content {
    flex: 1;
    overflow: hidden;
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
        min-height: 0;
      }

      .split-pane-left {
        border-right: 1px solid #f0f0f0;
      }

      .pane-title {
        font-size: 13px;
        color: #595959;
        padding: 10px 12px;
        border-bottom: 1px solid #f0f0f0;
        background: #fff;
      }

      .pane-title-with-actions {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        min-height: 48px;
      }

      .pane-title-main {
        display: flex;
        align-items: center;
        gap: 8px;
        min-width: 0;
        flex: 1;
      }

      .pane-title-prefix {
        color: #8c8c8c;
        font-weight: 600;
      }

      .doc-name {
        font-size: 14px;
        font-weight: 600;
        color: #262626;
        min-width: 0;
        max-width: 100%;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      .parse-state-tag {
        margin-inline-start: 2px;
      }

      .pane-actions-left,
      .pane-actions-right {
        display: flex;
        align-items: center;
        gap: 8px;
        min-width: 0;
      }

      .action-btn {
        height: 30px;
        padding: 0 14px;
        border-radius: 8px;
        font-size: 13px;
      }

      .action-switch {
        min-width: 72px;
      }

      .parse-progress-row {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 8px 12px;
        border-bottom: 1px solid #f0f0f0;
        background: #fafafa;
      }

      .processing-progress {
        flex: 1;
        margin-bottom: 0;
      }

      .progress-text {
        color: #8c8c8c;
        font-size: 12px;
        white-space: nowrap;
      }

      .file-preview {
        flex: 1;
        overflow: hidden;
        position: relative;
        min-height: 0;

        .pdf-viewer,
        .office-viewer {
          width: 100%;
          height: 100%;
          min-height: 460px;
          border: none;
          background: #fff;
        }

        .office-preview {
          width: 100%;
          height: 100%;
        }

        .image-viewer {
          width: 100%;
          height: 100%;
          object-fit: contain;
          background: #f7f7f7;
        }

        .text-viewer {
          margin: 0;
          width: 100%;
          height: 100%;
          overflow: auto;
          background: #fafafa;
          color: #262626;
          padding: 14px;
          font-size: 13px;
          line-height: 1.6;
        }
      }

      .split-pane-right {
        .b2-pane-title {
          .b2-tabs {
            flex: 1;
            min-width: 0;
            margin-right: 8px;
          }

          :deep(.ant-tabs-nav) {
            margin: 0;
          }

          :deep(.ant-tabs-tab) {
            padding: 6px 10px;
          }
        }

        .b2-content {
          flex: 1;
          min-height: 0;
          overflow: auto;
          position: relative;
        }

        .markdown-preview {
          padding: 14px;
          color: #262626;
          line-height: 1.7;
          word-break: break-word;

          :deep(pre) {
            background: #f6f8fa;
            border-radius: 8px;
            padding: 12px;
            overflow: auto;
          }

          :deep(code) {
            background: rgba(0, 0, 0, 0.04);
            padding: 2px 4px;
            border-radius: 4px;
          }
        }

        .markdown-edit-wrap {
          display: flex;
          flex-direction: column;
          gap: 10px;
          height: 100%;
          padding: 12px;
          box-sizing: border-box;
        }

        .markdown-editor {
          flex: 1;
          min-height: 280px;
          resize: none;
          font-family: SFMono-Regular, Consolas, 'Liberation Mono', Menlo, monospace;
          font-size: 13px;
          line-height: 1.6;
        }

        .markdown-edit-actions {
          display: flex;
          justify-content: flex-end;
        }

        .b2-empty {
          position: absolute;
          inset: 0;
          display: flex;
          align-items: center;
          justify-content: center;
          pointer-events: none;
          background: rgba(255, 255, 255, 0.85);
        }
      }
    }
  }

  .ingest-modal-content {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding-top: 6px;
  }

  .ingest-stage {
    font-size: 13px;
    color: #595959;
  }

  .ingest-result {
    font-size: 14px;
    color: #1677ff;
    font-weight: 600;
  }

  .stats-modal-content {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .stats-total {
    font-weight: 600;
    color: #262626;
  }

  .stats-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  &.dark-mode {
    background: #141414;

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
        color: rgba(255, 255, 255, 0.85);

        pre {
          background: #272727;
          color: rgba(255, 255, 255, 0.85);
        }
      }
    }
  }
}
</style>
