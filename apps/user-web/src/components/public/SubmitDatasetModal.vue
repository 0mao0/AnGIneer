<template>
  <a-modal
    :open="open"
    title="投稿测试集"
    width="680px"
    :confirm-loading="submitting"
    ok-text="提交"
    cancel-text="取消"
    @update:open="(v: boolean) => emit('update:open', v)"
    @ok="handleSubmit"
  >
    <div v-if="authStore.guestMode" class="guest-tip">
      未登录将以<b>游客</b>身份提交，提交后公开可见。<a @click="emit('login')">登录</a>
    </div>

    <a-form layout="vertical" class="submit-form">
      <a-form-item label="测试集标题" required>
        <a-input v-model:value="formTitle" :maxlength="120" placeholder="一句话说明这套题考什么" />
      </a-form-item>
      <a-form-item label="所属子专业">
        <a-select v-model:value="formNode" allow-clear placeholder="可不选（提交后由人工归类）">
          <a-select-option v-for="n in nodeOptions" :key="n.node_id" :value="n.node_id">
            {{ n.path }}
          </a-select-option>
        </a-select>
      </a-form-item>
      <a-form-item label="描述">
        <a-textarea v-model:value="formDesc" :maxlength="2000" :auto-size="{ minRows: 2, maxRows: 4 }"
          placeholder="语料来源、适用场景（可空）" />
      </a-form-item>

      <a-form-item label="题目" required>
        <div class="item-head">
          <span>共 {{ items.length }} 题</span>
          <a-space size="small">
            <a-button size="small" @click="addItem">加一题</a-button>
            <a-button size="small" @click="fileInput?.click()">导入 JSON</a-button>
            <input ref="fileInput" type="file" accept=".json" class="hidden-file" @change="onImportFile" />
          </a-space>
        </div>
        <div v-for="(it, idx) in items" :key="idx" class="item-row">
          <div class="item-line">
            <span class="item-idx">{{ idx + 1 }}.</span>
            <a-select v-model:value="it.intent_level" size="small" class="item-level">
              <a-select-option v-for="lv in levels" :key="lv" :value="lv">{{ lv }}</a-select-option>
            </a-select>
            <a-button size="small" type="text" danger @click="items.splice(idx, 1)">删</a-button>
          </div>
          <a-textarea v-model:value="it.question" :maxlength="2000" :auto-size="{ minRows: 1, maxRows: 4 }"
            placeholder="题干（必填）" />
          <a-input v-model:value="it.answer" :maxlength="2000" placeholder="参考答案（可空）" size="small" class="item-answer" />
        </div>
      </a-form-item>
    </a-form>
  </a-modal>
</template>

<script setup lang="ts">
/** 投稿测试集弹窗：标题/子专业/描述 + 逐题行（题干/等级/参考答案可空）+ JSON 整包导入。
 *  JSON 导入兼容 eval bundle v2（items[].question）与裸数组 [{question, ...}] 两种形态。 */
import { computed, ref, watch } from 'vue'
import { App } from 'ant-design-vue'
import { communityApi, communityApiErrorText, type TreeNode } from '@/api/community'
import { useAuthStore } from '@/stores/auth'

const props = defineProps<{ open: boolean; treeNodes: TreeNode[] }>()
const emit = defineEmits<{
  (e: 'update:open', v: boolean): void
  (e: 'submitted'): void
  (e: 'login'): void
}>()

const { message } = App.useApp()
const authStore = useAuthStore()
const levels = ['L1', 'L2', 'L3', 'L4']

const formTitle = ref('')
const formNode = ref<string | undefined>(undefined)
const formDesc = ref('')
const submitting = ref(false)
const fileInput = ref<HTMLInputElement>()

interface ItemDraft { question: string; intent_level: string; answer: string }
const items = ref<ItemDraft[]>([{ question: '', intent_level: 'L1', answer: '' }])

watch(() => props.open, (v) => {
  if (v && !authStore.isAuthed) void authStore.enterGuestMode()
})

/** 子专业下拉：叶子节点 + 「一级 / 二级」全路径显示 */
const nodeOptions = computed(() => {
  const byId: Record<string, TreeNode> = {}
  props.treeNodes.forEach((n) => { byId[n.node_id] = n })
  return props.treeNodes
    .filter((n) => n.parent_id)
    .map((n) => {
      const parent = byId[n.parent_id!]
      return { node_id: n.node_id, path: parent ? `${parent.title} / ${n.title}` : n.title }
    })
})

function addItem() {
  if (items.value.length >= 200) {
    message.warning('单个题集最多 200 题')
    return
  }
  items.value.push({ question: '', intent_level: 'L1', answer: '' })
}

function onImportFile(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  ;(e.target as HTMLInputElement).value = ''
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => {
    try {
      const parsed = JSON.parse(String(reader.result || ''))
      const rawItems: any[] = Array.isArray(parsed)
        ? parsed
        : Array.isArray(parsed?.items)
          ? parsed.items
          : []
      const mapped = rawItems
        .filter((it) => it && String(it.question || '').trim())
        .slice(0, 200)
        .map((it) => ({
          question: String(it.question),
          intent_level: levels.includes(it.intent_level) ? it.intent_level : 'L1',
          answer: String(it.answer || it.gold_answer || ''),
        }))
      if (!mapped.length) {
        message.error('JSON 里没解析出带题干的题目（支持题集 bundle 或 [{question}] 数组）')
        return
      }
      items.value = mapped
      if (!formTitle.value && typeof parsed?.dataset?.title === 'string') {
        formTitle.value = parsed.dataset.title
      }
      message.success(`已导入 ${mapped.length} 题，请核对后提交`)
    } catch {
      message.error('JSON 解析失败，请检查文件格式')
    }
  }
  reader.readAsText(file)
}

async function handleSubmit() {
  const validItems = items.value.filter((it) => it.question.trim())
  if (!formTitle.value.trim()) {
    message.warning('请填写测试集标题')
    return
  }
  if (!validItems.length) {
    message.warning('题集至少包含一道题')
    return
  }
  submitting.value = true
  try {
    if (authStore.guestMode) await authStore.enterGuestMode()  // 提交前兜签发竞态（R3）
    await communityApi.submit({
      scope: 'eval',
      kind: 'dataset',
      node_id: formNode.value || '',
      title: formTitle.value.trim(),
      payload: {
        description: formDesc.value.trim(),
        items: validItems.map((it) => ({
          question: it.question.trim(),
          intent_level: it.intent_level,
          answer: it.answer.trim(),
        })),
      },
    })
    message.success('已提交，审核前即可见（标注「网友投稿」）')
    items.value = [{ question: '', intent_level: 'L1', answer: '' }]
    formTitle.value = ''
    formDesc.value = ''
    formNode.value = undefined
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

.submit-form {
  .item-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
    font-size: 12px;
    color: var(--text-tertiary);
  }

  .item-row {
    border: 1px solid var(--border-color, rgba(0, 0, 0, 0.08));
    border-radius: 6px;
    padding: 8px;
    margin-bottom: 8px;

    .item-line {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 6px;

      .item-idx {
        font-size: 12px;
        color: var(--text-tertiary);
      }

      .item-level {
        width: 72px;
      }
    }

    .item-answer {
      margin-top: 6px;
    }
  }
}

.hidden-file {
  display: none;
}
</style>
