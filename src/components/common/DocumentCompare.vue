<template>
  <div class="document-compare">
    <div class="compare-pane left-pane">
      <div class="pane-header">
        <span class="pane-title">{{ leftTitle }}</span>
        <a-select v-if="showDocSelect" :value="localSelectedDoc" style="width: 180px" size="small" @change="handleDocChange">
          <a-select-option v-for="doc in documents" :key="doc.id" :value="doc.id">
            {{ doc.name }}
          </a-select-option>
        </a-select>
      </div>
      <div class="pane-content">
        <slot name="left">
          <div class="placeholder">
            <FilePdfOutlined style="font-size: 48px; color: #ff4d4f" />
            <p>PDF 预览区域</p>
          </div>
        </slot>
      </div>
    </div>
    
    <div class="compare-divider" @mousedown="startResize">
      <div class="divider-handle" />
    </div>
    
    <div class="compare-pane right-pane">
      <div class="pane-header">
        <span class="pane-title">{{ rightTitle }}</span>
        <a-space v-if="showModeSwitch">
          <a-button 
            :type="mode === 'preview' ? 'primary' : 'default'" 
            size="small"
            @click="$emit('update:mode', 'preview')"
          >
            预览
          </a-button>
          <a-button 
            :type="mode === 'edit' ? 'primary' : 'default'" 
            size="small"
            @click="$emit('update:mode', 'edit')"
          >
            编辑
          </a-button>
        </a-space>
      </div>
      <div class="pane-content">
        <slot name="right" :mode="mode" :content="content" :onSave="handleSave">
          <div v-if="mode === 'preview'" class="markdown-preview" v-html="renderedContent" />
          <div v-else class="markdown-editor">
            <a-textarea
              :value="content"
              :rows="20"
              @update:value="$emit('update:content', $event)"
            />
            <div v-if="showSaveButton" class="editor-actions">
              <a-button type="primary" size="small" @click="handleSave">
                <SaveOutlined /> 保存
              </a-button>
            </div>
          </div>
        </slot>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { FilePdfOutlined, SaveOutlined } from '@ant-design/icons-vue'

interface Document {
  id: string
  name: string
}

interface Props {
  leftTitle?: string
  rightTitle?: string
  mode?: 'preview' | 'edit'
  content?: string
  documents?: Document[]
  selectedDoc?: string
  showDocSelect?: boolean
  showModeSwitch?: boolean
  showSaveButton?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  leftTitle: 'PDF 原文',
  rightTitle: 'Markdown',
  mode: 'preview',
  content: '',
  documents: () => [],
  selectedDoc: '',
  showDocSelect: true,
  showModeSwitch: true,
  showSaveButton: true
})

const emit = defineEmits<{
  'update:mode': [mode: 'preview' | 'edit']
  'update:content': [content: string]
  'update:selectedDoc': [docId: string]
  save: [content: string]
  'docChange': [docId: string]
}>()

const localSelectedDoc = ref(props.selectedDoc)

watch(() => props.selectedDoc, (newVal) => {
  localSelectedDoc.value = newVal
})

const handleDocChange = (value: string) => {
  localSelectedDoc.value = value
  emit('update:selectedDoc', value)
  emit('docChange', value)
}

const renderedContent = computed(() => {
  if (!props.content) return ''
  return props.content
    .replace(/^### (.*$)/gm, '<h3>$1</h3>')
    .replace(/^## (.*$)/gm, '<h2>$1</h2>')
    .replace(/^# (.*$)/gm, '<h1>$1</h1>')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\n/g, '<br/>')
})

const handleSave = () => {
  emit('save', props.content)
}

const startResize = () => {
  // 后续可以实现拖拽调整宽度
}
</script>

<style lang="less" scoped>
.document-compare {
  display: flex;
  height: 100%;
  gap: 4px;
}

.compare-pane {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: #fff;
  border-radius: 4px;
  overflow: hidden;
}

.pane-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: #fafafa;
  border-bottom: 1px solid #f0f0f0;
  flex-shrink: 0;
}

.pane-title {
  font-weight: 500;
}

.pane-content {
  flex: 1;
  overflow: auto;
  padding: 12px;
}

.compare-divider {
  width: 8px;
  cursor: col-resize;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f0f0f0;
  
  &:hover {
    background: #e0e0e0;
  }
  
  .divider-handle {
    width: 4px;
    height: 40px;
    background: #ccc;
    border-radius: 2px;
  }
}

.placeholder {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #999;
  
  p {
    margin-top: 12px;
  }
}

.markdown-preview {
  line-height: 1.8;
  
  h1 { font-size: 24px; margin: 16px 0; }
  h2 { font-size: 20px; margin: 14px 0; }
  h3 { font-size: 16px; margin: 12px 0; }
  
  code {
    background: #f5f5f5;
    padding: 2px 6px;
    border-radius: 4px;
    font-family: monospace;
  }
}

.markdown-editor {
  height: 100%;
  display: flex;
  flex-direction: column;
  
  .editor-actions {
    margin-top: 8px;
    text-align: right;
  }
}
</style>
