<template>
  <div class="sop-view">
    <div v-if="loading" class="sop-loading">
      <a-spin tip="加载中..." />
    </div>
    <template v-else-if="sopData">
      <div class="sop-header">
        <h2>{{ sopData.name_zh || sopData.id }}</h2>
        <a-tag v-if="completed" color="success">已完成</a-tag>
        <a-tag v-else color="blue">待执行</a-tag>
      </div>
      <div v-if="sopData.description" class="sop-desc">{{ sopData.description }}</div>
      <div class="sop-content">
        <a-result
          v-if="completed"
          status="success"
          title="SOP 执行完成"
          sub-title="本流程已全部完成"
        >
          <template #extra>
            <a-button @click="prevStep">返回上一步</a-button>
            <a-button type="primary" @click="restart">从头重新执行</a-button>
          </template>
        </a-result>
        <a-steps v-else-if="stepList.length" :current="currentStep" direction="vertical">
          <a-step v-for="(step, index) in stepList" :key="step.id" :title="step.title" :description="step.desc">
            <template #icon>
              <CheckCircleFilled v-if="index < currentStep" />
              <LoadingOutlined v-else-if="index === currentStep" />
              <span v-else class="step-circle">{{ index + 1 }}</span>
            </template>
          </a-step>
        </a-steps>
        <EmptyState v-else variant="empty" title="该 SOP 暂无步骤" />
      </div>
      <div class="sop-actions" v-if="stepList.length && !completed">
        <a-button-group>
          <a-button @click="prevStep" :disabled="currentStep === 0">上一步</a-button>
          <a-button type="primary" @click="nextStep">
            {{ currentStep >= stepList.length - 1 ? '完成' : '下一步' }}
          </a-button>
        </a-button-group>
      </div>
    </template>
    <EmptyState
      v-else-if="loadError"
      variant="error"
      title="SOP 加载失败"
      :description="loadError"
      cta-text="重试"
      @cta-click="loadSop(effectiveSopId)"
    />
    <EmptyState v-else variant="empty" title="未选择 SOP" description="从左侧经验库选择一个 SOP 开始执行" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { message } from 'ant-design-vue'
import { CheckCircleFilled, LoadingOutlined } from '@ant-design/icons-vue'
import { sopApi } from '@angineer/sop-ui'
import type { SopData, SopStep } from '@angineer/sop-ui'
import { EmptyState } from '@angineer/ui-kit'
import { useSopProgress } from '@/composables/useSopProgress'

const props = defineProps<{
  sopId?: string
  title?: string
  description?: string
}>()

const route = useRoute()
const sopData = ref<SopData | null>(null)
const loading = ref(false)
const loadError = ref<string>('')
const completed = ref(false)

const stepList = computed(() => {
  if (!sopData.value?.steps) return []
  return sopData.value.steps.map((step: SopStep) => {
    const desc = typeof step.description === 'string'
      ? step.description
      : (step.description?.content || '')
    return {
      id: step.id,
      title: step.name || step.name_zh || step.id,
      desc,
    }
  })
})

const effectiveSopId = computed(() => props.sopId || (route.params.id as string) || '')

const { currentStep, markComplete } = useSopProgress(() => effectiveSopId.value)

const loadSop = async (id: string) => {
  if (!id) return
  loading.value = true
  loadError.value = ''
  completed.value = false
  try {
    sopData.value = await sopApi.getSop(id)
  } catch (err) {
    const e = err as Error
    loadError.value = e.message || 'SOP 加载失败'
    message.error(loadError.value)
    sopData.value = null
  } finally {
    loading.value = false
  }
}

watch(effectiveSopId, (id) => {
  if (id) loadSop(id)
})

onMounted(() => {
  const id = effectiveSopId.value
  if (id) loadSop(id)
})

const prevStep = () => {
  if (currentStep.value > 0) {
    currentStep.value--
    completed.value = false
  }
}

const nextStep = () => {
  if (currentStep.value < stepList.value.length) {
    currentStep.value++
    if (currentStep.value >= stepList.value.length) {
      completed.value = true
      markComplete()
      message.success('SOP 已完成执行')
    }
  }
}

const restart = () => {
  currentStep.value = 0
  completed.value = false
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
  margin-bottom: 12px;

  h2 {
    margin: 0;
    font-size: 18px;
  }
}

.sop-desc {
  color: var(--text-secondary);
  font-size: 13px;
  margin-bottom: 20px;
  line-height: 1.5;
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

.sop-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--text-secondary);
}
</style>
