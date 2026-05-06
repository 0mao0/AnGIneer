<template>
  <div class="sop-view">
    <div class="sop-header">
      <h2>{{ sop?.title || 'SOP 加载中...' }}</h2>
      <a-tag color="blue">{{ sop?.status || '待执行' }}</a-tag>
    </div>
    <div class="sop-content">
      <a-steps :current="currentStep" direction="vertical">
        <a-step v-for="(step, index) in steps" :key="index" :title="step.title" :description="step.description">
          <template #icon>
            <CheckCircleFilled v-if="index < currentStep" />
            <LoadingOutlined v-else-if="index === currentStep" />
            <span v-else class="step-circle">{{ index + 1 }}</span>
          </template>
        </a-step>
      </a-steps>
    </div>
    <div class="sop-actions">
      <a-button-group>
        <a-button @click="prevStep" :disabled="currentStep === 0">上一步</a-button>
        <a-button type="primary" @click="nextStep" :disabled="currentStep >= steps.length">
          {{ currentStep >= steps.length ? '完成' : '下一步' }}
        </a-button>
      </a-button-group>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { CheckCircleFilled, LoadingOutlined } from '@ant-design/icons-vue'

const props = defineProps<{
  sopId?: string
  title?: string
  description?: string
}>()

const route = useRoute()
const sop = ref<any>(null)
const currentStep = ref(0)

const steps = ref([
  { title: '确定设计船型', description: '根据港口性质和货运量确定设计船型' },
  { title: '收集基础资料', description: '收集水文、气象、地质等基础资料' },
  { title: '航道选线', description: '确定航道轴线和走向' },
  { title: '计算航道尺度', description: '计算航道宽度和水深' },
  { title: '验证与优化', description: '进行船舶操纵模拟验证' }
])

onMounted(async () => {
  const sopId = (props.sopId || route.params.id || '') as string
  sop.value = {
    id: sopId,
    title: props.title || '航道设计流程',
    status: '执行中'
  }
})

const prevStep = () => {
  if (currentStep.value > 0) {
    currentStep.value--
  }
}

const nextStep = () => {
  if (currentStep.value < steps.value.length) {
    currentStep.value++
  }
}
</script>

<style lang="less" scoped>
.sop-view {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--bg-secondary);
  padding: 24px;
}

.sop-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 24px;
  
  h2 {
    margin: 0;
  }
}

.sop-content {
  flex: 1;
  overflow-y: auto;
}

.sop-actions {
  margin-top: 24px;
  padding-top: 16px;
  border-top: 1px solid var(--border-color);
}
</style>
