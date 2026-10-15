<template>
  <a-modal
    :open="open"
    title="添加题目"
    width="560px"
    :confirm-loading="submitting"
    ok-text="提交"
    cancel-text="取消"
    @update:open="(v: boolean) => emit('update:open', v)"
    @ok="handleSubmit"
  >
    <div v-if="authStore.guestMode" class="guest-tip">
      未登录将以<b>游客</b>身份提交，提交后公开可见。<a @click="emit('login')">登录</a>
    </div>

    <a-form layout="vertical">
      <a-form-item label="目标测试集" required>
        <a-select v-model:value="targetKey" placeholder="挂到哪个测试集名下">
          <a-select-option v-for="d in datasetOptions" :key="d.key" :value="d.key">
            {{ d.title }}{{ d.origin === 'user' ? '（网友投稿）' : '（官方）' }}
          </a-select-option>
        </a-select>
        <div class="field-hint">官方题集的投稿不会改动原集，先入公开投稿池</div>
      </a-form-item>
      <a-form-item label="题干" required>
        <a-textarea v-model:value="questionText" :maxlength="2000" :auto-size="{ minRows: 2, maxRows: 6 }"
          placeholder="题目正文" />
      </a-form-item>
      <a-form-item label="意图等级">
        <a-radio-group v-model:value="intentLevel" size="small" button-style="solid">
          <a-radio-button v-for="lv in levels" :key="lv" :value="lv">{{ lv }}</a-radio-button>
        </a-radio-group>
      </a-form-item>
      <a-form-item label="参考答案">
        <a-textarea v-model:value="answerText" :maxlength="2000" :auto-size="{ minRows: 1, maxRows: 4 }"
          placeholder="可空" />
      </a-form-item>
    </a-form>
  </a-modal>
</template>

<script setup lang="ts">
/** 投稿单题弹窗：题干/等级/参考答案可空 + 挂到哪个集（官方或网友题集均可，全部进投稿池）。 */
import { computed, ref, watch } from 'vue'
import { App } from 'ant-design-vue'
import { communityApi, communityApiErrorText, type ItemOrigin } from '@/api/community'
import { useAuthStore } from '@/stores/auth'

interface DatasetOption { ref_id: string; origin: ItemOrigin; title: string }

const props = defineProps<{
  open: boolean
  datasets: DatasetOption[]
  defaultDataset?: DatasetOption
}>()
const emit = defineEmits<{
  (e: 'update:open', v: boolean): void
  (e: 'submitted'): void
  (e: 'login'): void
}>()

const { message } = App.useApp()
const authStore = useAuthStore()
const levels = ['L1', 'L2', 'L3', 'L4']

const datasetOptions = computed(() =>
  props.datasets.map((d) => ({ ...d, key: `${d.origin}:${d.ref_id}` })),
)

const targetKey = ref('')
const questionText = ref('')
const intentLevel = ref('L1')
const answerText = ref('')
const submitting = ref(false)

watch(() => props.open, (v) => {
  if (!v) return
  if (!authStore.isAuthed) void authStore.enterGuestMode()
  if (props.defaultDataset) {
    targetKey.value = `${props.defaultDataset.origin}:${props.defaultDataset.ref_id}`
  }
})

async function handleSubmit() {
  if (!targetKey.value) {
    message.warning('请选择目标测试集')
    return
  }
  if (!questionText.value.trim()) {
    message.warning('题干不能为空')
    return
  }
  const refId = targetKey.value.slice(targetKey.value.indexOf(':') + 1)
  submitting.value = true
  try {
    if (authStore.guestMode) await authStore.enterGuestMode()
    await communityApi.submit({
      scope: 'eval',
      kind: 'question',
      parent_ref: refId,
      payload: {
        question: questionText.value.trim(),
        intent_level: intentLevel.value,
        answer: answerText.value.trim(),
      },
    })
    message.success('已提交，审核前即可见')
    questionText.value = ''
    answerText.value = ''
    emit('update:open', false)
    emit('submitted')
  } catch (e) {
    message.error(communityApiErrorText(e))
  } finally {
    submitting.value = false
  }
}
</script>

<style lang="less" scoped>
.guest-tip {
  padding: 8px 12px;
  margin-bottom: 12px;
  font-size: 12px;
  border-radius: 6px;
  background: var(--bg-secondary, rgba(0, 0, 0, 0.04));
  color: var(--text-secondary);

  a {
    color: var(--primary-color);
    margin-inline-start: 6px;
  }
}

.field-hint {
  margin-top: 4px;
  font-size: 11px;
  color: var(--text-tertiary);
}
</style>
