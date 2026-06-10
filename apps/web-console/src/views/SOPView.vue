<template>
  <div class="sop-view">
    <div v-if="loading" class="sop-loading">
      <a-spin tip="加载中..." />
    </div>
    <template v-else-if="sopData">
      <div class="sop-header">
        <h2>{{ sopData.name_zh || sopData.id }}</h2>
        <a-tag color="blue">待执行</a-tag>
      </div>
      <div v-if="sopData.description" class="sop-desc">{{ sopData.description }}</div>
      <div class="sop-content">
        <a-steps :current="currentStep" direction="vertical" v-if="stepList.length">
          <a-step v-for="(step, index) in stepList" :key="step.id" :title="step.title" :description="step.desc">
            <template #icon>
              <CheckCircleFilled v-if="index < currentStep" />
              <LoadingOutlined v-else-if="index === currentStep" />
              <span v-else class="step-circle">{{ index + 1 }}</span>
            </template>
          </a-step>
        </a-steps>
        <div v-else class="sop-empty">该 SOP 暂无步骤</div>
      </div>
      <div class="sop-actions" v-if="stepList.length">
        <a-button-group>
          <a-button @click="prevStep" :disabled="currentStep === 0">上一步</a-button>
          <a-button type="primary" @click="nextStep" :disabled="currentStep >= stepList.length">
            {{ currentStep >= stepList.length ? '完成' : '下一步' }}
          </a-button>
        </a-button-group>
      </div>
    </template>
    <div v-else class="sop-empty">未找到 SOP 数据</div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { CheckCircleFilled, LoadingOutlined } from '@ant-design/icons-vue'
import { sopApi } from '@angineer/sop-ui'
import type { SopData, SopStep } from '@angineer/sop-ui'

const props = defineProps<{
  sopId?: string
  title?: string
  description?: string
}>()

const route = useRoute()
const sopData = ref<SopData | null>(null)
const currentStep = ref(0)
const loading = ref(false)

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

const loadSop = async (id: string) => {
  if (!id) return
  loading.value = true
  currentStep.value = 0
  try {
    sopData.value = await sopApi.getSop(id)
  } catch (err) {
    console.error('Failed to load SOP:', err)
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
  if (currentStep.value > 0) currentStep.value--
}

const nextStep = () => {
  if (currentStep.value < stepList.value.length) currentStep.value++
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

.sop-loading,
.sop-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--text-secondary);
}
</style>
