<template>
  <div class="comment-panel">
    <div class="comment-header">
      <span class="comment-title">意见（{{ comments.length + localComments.length }}）</span>
      <a-button size="small" type="primary" @click="editorOpen = !editorOpen">
        {{ editorOpen ? '收起' : '提意见' }}
      </a-button>
    </div>

    <div v-if="editorOpen" class="comment-editor">
      <div v-if="authStore.guestMode" class="guest-tip">
        未登录将以<b>游客</b>身份提交，提交后公开可见。<a @click="emit('login')">登录</a>
      </div>
      <a-select v-model:value="stepRef" size="small" allow-clear placeholder="针对整个 SOP（可指定步骤）" class="step-select">
        <a-select-option v-for="s in steps" :key="s.id" :value="s.id">步骤：{{ s.label }}</a-select-option>
      </a-select>
      <a-textarea v-model:value="draft" :maxlength="2000" :auto-size="{ minRows: 2, maxRows: 5 }"
        placeholder="例如：步骤 2 的水深公式口径与 JTS 165-2013 不一致，建议核对" />
      <div class="editor-actions">
        <a-button size="small" type="primary" :loading="submitting" @click="submitComment">提交意见</a-button>
      </div>
    </div>

    <div class="comment-list">
      <div v-for="c in allComments" :key="c.comment_id" class="comment-item">
        <div class="comment-meta">
          <span class="comment-author">{{ c.author_label || '游客' }}</span>
          <span v-if="c.step_ref" class="comment-step">步骤 {{ stepLabel(c.step_ref) }}</span>
        </div>
        <!-- 用户文本纯插值（R5）：不渲染 HTML / Markdown -->
        <div class="comment-body">{{ c.comment }}</div>
      </div>
      <div v-if="!allComments.length" class="comment-empty">还没有意见，来说说你的看法</div>
    </div>
  </div>
</template>

<script setup lang="ts">
/** SOP 意见面板：列表 + 发表框（可指定步骤）。本版只收不审——没有任何审核动作（D3）。 */
import { computed, ref, watch } from 'vue'
import { App } from 'ant-design-vue'
import { communityApi, communityApiErrorText, type SopComment } from '@/api/community'
import { useAuthStore } from '@/stores/auth'

const props = defineProps<{
  sopId: string
  steps: { id: string; label: string }[]
}>()
const emit = defineEmits<{
  (e: 'submitted'): void
  (e: 'login'): void
  /** 意见总条数变化（含本地刚提交的）——供右栏页签标签显示条数 */
  (e: 'count-change', count: number): void
}>()

const { message } = App.useApp()
const authStore = useAuthStore()

const comments = ref<SopComment[]>([])
const localComments = ref<SopComment[]>([])
const editorOpen = ref(false)
const stepRef = ref<string | undefined>(undefined)
const draft = ref('')
const submitting = ref(false)

const allComments = computed(() => [...localComments.value, ...comments.value])

function stepLabel(id: string): string {
  return props.steps.find((s) => s.id === id)?.label || id
}

async function load() {
  localComments.value = []
  try {
    const resp = await communityApi.getComments(props.sopId)
    comments.value = resp.comments || []
  } catch {
    comments.value = []
  }
}

async function submitComment() {
  if (!draft.value.trim()) {
    message.warning('意见内容不能为空')
    return
  }
  submitting.value = true
  try {
    if (authStore.guestMode) await authStore.enterGuestMode()
    const result = await communityApi.submit({
      scope: 'sop',
      kind: 'sop_comment',
      parent_ref: props.sopId,
      step_ref: stepRef.value || '',
      payload: { comment: draft.value.trim() },
    })
    localComments.value.unshift({
      comment_id: result.submission_id,
      sop_id: props.sopId,
      step_ref: stepRef.value || '',
      comment: draft.value.trim(),
      author_label: result.author_label,
      created_at: result.created_at,
    })
    draft.value = ''
    stepRef.value = undefined
    editorOpen.value = false
    message.success('意见已提交，公开可见')
    emit('submitted')
  } catch (e) {
    message.error(communityApiErrorText(e))
  } finally {
    submitting.value = false
  }
}

watch(() => props.sopId, () => void load(), { immediate: true })

watch(() => allComments.value.length, (n) => emit('count-change', n), { immediate: true })
</script>

<style lang="less" scoped>
.comment-panel {
  /* 右栏「意见」页签内容器：自行滚动，不再为页面堆叠留 margin/border */
  height: 100%;
  overflow-y: auto;
  box-sizing: border-box;
  padding: 12px;

  .comment-header {
    display: flex;
    align-items: center;
    justify-content: space-between;

    .comment-title {
      font-size: 14px;
      font-weight: 600;
    }
  }

  .comment-editor {
    margin-top: 10px;

    .step-select {
      width: 100%;
      margin-bottom: 8px;
    }

    .editor-actions {
      margin-top: 8px;
      text-align: right;
    }
  }

  .guest-tip {
    padding: 6px 10px;
    margin-bottom: 8px;
    font-size: 12px;
    border-radius: 6px;
    background: var(--bg-secondary, rgba(0, 0, 0, 0.04));
    color: var(--text-secondary);

    a {
      color: var(--primary-color);
      margin-inline-start: 6px;
    }
  }

  .comment-list {
    margin-top: 10px;
    display: flex;
    flex-direction: column;
    gap: 10px;

    .comment-item {
      padding: 8px 12px;
      border-radius: 8px;
      background: var(--bg-secondary, rgba(0, 0, 0, 0.03));

      .comment-meta {
        display: flex;
        gap: 8px;
        font-size: 12px;
        color: var(--text-tertiary);

        .comment-author {
          font-weight: 600;
        }
      }

      .comment-body {
        margin-top: 4px;
        font-size: 13px;
        white-space: pre-wrap;
        word-break: break-word;
      }
    }

    .comment-empty {
      text-align: center;
      padding: 16px 0;
      font-size: 12px;
      color: var(--text-tertiary);
    }
  }
}
</style>
