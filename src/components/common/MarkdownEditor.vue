<template>
  <div class="markdown-editor-component">
    <div class="editor-toolbar">
      <a-space>
        <a-button size="small" @click="insertFormat('**', '**')">
          <BoldOutlined />
        </a-button>
        <a-button size="small" @click="insertFormat('*', '*')">
          <ItalicOutlined />
        </a-button>
        <a-button size="small" @click="insertFormat('`', '`')">
          <CodeOutlined />
        </a-button>
        <a-divider type="vertical" />
        <a-button size="small" @click="insertFormat('# ', '')">
          <Header />
        </a-button>
        <a-button size="small" @click="insertFormat('## ', '')">
          <Header :level="2" />
        </a-button>
        <a-button size="small" @click="insertFormat('- ', '')">
          <UnorderedListOutlined />
        </a-button>
        <a-button size="small" @click="insertFormat('1. ', '')">
          <OrderedListOutlined />
        </a-button>
        <a-divider type="vertical" />
        <a-button size="small" @click="insertFormat('[', '](url)')">
          <LinkOutlined />
        </a-button>
        <a-button size="small" @click="insertFormat('![alt](', ')')">
          <PictureOutlined />
        </a-button>
      </a-space>
    </div>
    <div class="editor-content">
      <a-textarea
        ref="textareaRef"
        :value="modelValue"
        :rows="rows"
        :placeholder="placeholder"
        @update:value="$emit('update:modelValue', $event)"
      />
    </div>
    <div v-if="showWordCount" class="editor-footer">
      <span class="word-count">字数：{{ wordCount }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import {
  BoldOutlined,
  ItalicOutlined,
  CodeOutlined,
  UnorderedListOutlined,
  OrderedListOutlined,
  LinkOutlined,
  PictureOutlined
} from '@ant-design/icons-vue'

interface Props {
  modelValue?: string
  rows?: number
  placeholder?: string
  showWordCount?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  modelValue: '',
  rows: 15,
  placeholder: '输入 Markdown 内容...',
  showWordCount: true
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const textareaRef = ref<any>(null)

const wordCount = computed(() => {
  return props.modelValue.trim().length
})

const insertFormat = (prefix: string, suffix: string) => {
  const textarea = textareaRef.value?.resizableTextArea?.textArea as HTMLTextAreaElement | undefined
  if (!textarea) return
  
  const start = textarea.selectionStart
  const end = textarea.selectionEnd
  const text = props.modelValue
  const selectedText = text.substring(start, end)
  
  const newText = text.substring(0, start) + prefix + selectedText + suffix + text.substring(end)
  emit('update:modelValue', newText)
  
  setTimeout(() => {
    textarea.focus()
    textarea.setSelectionRange(start + prefix.length, end + prefix.length)
  }, 0)
}
</script>

<style lang="less" scoped>
.markdown-editor-component {
  display: flex;
  flex-direction: column;
  border: 1px solid #d9d9d9;
  border-radius: 4px;
  overflow: hidden;
  
  &:focus-within {
    border-color: #1890ff;
  }
}

.editor-toolbar {
  padding: 8px 12px;
  background: #fafafa;
  border-bottom: 1px solid #f0f0f0;
  flex-shrink: 0;
}

.editor-content {
  flex: 1;
  
  :deep(.ant-input) {
    border: none;
    border-radius: 0;
    
    &:focus {
      box-shadow: none;
    }
  }
}

.editor-footer {
  padding: 6px 12px;
  background: #fafafa;
  border-top: 1px solid #f0f0f0;
  flex-shrink: 0;
  
  .word-count {
    font-size: 12px;
    color: #999;
  }
}
</style>
