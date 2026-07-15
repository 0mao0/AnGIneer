<template>
  <a-modal
    :open="visible"
    title="导入测试集"
    :confirm-loading="uploading"
    @ok="handleUpload"
    @cancel="handleCancel"
  >
    <a-upload-dragger
      v-model:fileList="fileList"
      :before-upload="beforeUpload"
      :max-count="1"
      accept=".json"
    >
      <p class="ant-upload-drag-icon">
        <InboxOutlined />
      </p>
      <p class="ant-upload-text">点击或拖拽 JSON 文件到此处</p>
      <p class="ant-upload-hint">仅支持 .json 格式的评测题集文件</p>
    </a-upload-dragger>
    <div class="import-sample-tip">
      <DownloadOutlined />
      <a @click.prevent="downloadSampleJson">下载示例文件</a>
      <span class="import-sample-hint">，按此格式编写后导入</span>
    </div>
  </a-modal>
</template>

<script setup lang="ts">
/** 评测测试集导入弹窗，支持拖拽上传和示例文件下载。 */
import { ref } from 'vue'
import { message } from 'ant-design-vue'
import { InboxOutlined, DownloadOutlined } from '@ant-design/icons-vue'
import type { UploadFile } from 'ant-design-vue'

defineProps<{
  visible: boolean
}>()

const emit = defineEmits<{
  'update:visible': [val: boolean]
  uploaded: []
}>()

const fileList = ref<UploadFile[]>([])
const uploading = ref(false)

const beforeUpload = () => false

/** 下载示例评测题集 JSON 文件，帮助用户了解导入格式。 */
const downloadSampleJson = () => {
  const sample = {
    dataset: {
      dataset_id: 'sample-knowledge-001',
      title: '示例：知识库评测题集',
      category: 'knowledge',
      description: '这是一个示例评测题集，展示 JSON 导入格式。请根据实际需求修改后上传。',
      schema_version: 'eval.bundle.v2',
      version: '1.0',
      library_id: 'default',
    },
    items: [
      {
        question_id: 'q001',
        question: '海港码头前沿设计水深如何确定？',
        task_type: 'definition',
        intent_level: 'L1',
        library_id: 'default',
        doc_ids: [],
        difficulty: 'easy',
        tags: ['港口工程', '水深'],
        retrieval: {
          gold_section_paths: ['第三章/3.2 码头前沿水深'],
          gold_chunk_ids: [],
          gold_doc_ids: [],
        },
        answer: {
          gold_answer: '码头前沿设计水深应根据设计船型满载吃水和必要的富裕水深之和确定。',
          correctness_checks: [
            { type: 'contains_all', keywords: ['设计船型', '满载吃水', '富裕水深'] },
          ],
          semantic_threshold: 0.65,
          must_cite_target_ids: [],
          must_cite_section_paths: [],
          refusal_expected: false,
        },
      },
      {
        question_id: 'q002',
        question: '极端高水位与设计高水位的区别是什么？',
        task_type: 'comparison',
        intent_level: 'L2',
        library_id: 'default',
        doc_ids: [],
        difficulty: 'medium',
        tags: ['港口工程', '水位'],
        answer: {
          gold_answer: '设计高水位是港口建筑物设计采用的正常使用高水位；极端高水位是校核港口建筑物安全采用的极端高水位，重现期更长。',
          correctness_checks: [
            { type: 'contains_all', keywords: ['设计高水位', '极端高水位', '重现期'] },
          ],
          semantic_threshold: 0.65,
          must_cite_target_ids: [],
          must_cite_section_paths: [],
          refusal_expected: false,
        },
      },
    ],
  }
  const blob = new Blob([JSON.stringify(sample, null, 2)], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = '示例评测题集.json'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

const handleUpload = async () => {
  if (!fileList.value.length) return
  uploading.value = true
  try {
    const file = fileList.value[0] as any
    const formData = new FormData()
    formData.append('file', file.originFileObj || file)
    const resp = await fetch('/api/evals/datasets/import', {
      method: 'POST',
      body: formData,
    })
    const result = await resp.json().catch(() => ({}))
    if (!resp.ok) {
      const errMsg = result.detail || result.message || JSON.stringify(result) || `请求失败 (${resp.status})`
      throw new Error(errMsg)
    }
    fileList.value = []
    emit('update:visible', false)
    emit('uploaded')
    message.success('导入成功')
  } catch (e: any) {
    const errMsg = e?.message || '导入失败，请检查文件格式'
    message.error(errMsg)
    console.error('导入失败:', e)
  } finally {
    uploading.value = false
  }
}

const handleCancel = () => {
  fileList.value = []
  emit('update:visible', false)
}
</script>

<style lang="less" scoped>
.import-sample-tip {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 12px;
  font-size: 13px;
  color: var(--text-secondary);

  a {
    color: var(--primary-color);
    text-decoration: none;

    &:hover {
      text-decoration: underline;
    }
  }
}

.import-sample-hint {
  color: var(--text-tertiary, #bfbfbf);
}
</style>
