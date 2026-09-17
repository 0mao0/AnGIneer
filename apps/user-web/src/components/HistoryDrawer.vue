<template>
  <!--
    主题跟随：ant-design-vue 4.x 的 cssinjs 在主题切换后不会重刷已挂载抽屉（portal）的
    颜色 token，切主题再打开会出现「黑底黑字/白底白字」。这里用内联样式绑定 CSS 变量，
    每次主题切换（变量在 <html> 上原地更新）即时生效，不依赖 cssinjs 重算。
  -->
  <a-drawer
    :open="open"
    placement="right"
    :width="340"
    :closable="false"
    :content-wrapper-style="{ background: 'var(--bg-secondary)', color: 'var(--text-primary)' }"
    :header-style="{ background: 'var(--bg-secondary)', color: 'var(--text-primary)', borderColor: 'var(--border-color)' }"
    :body-style="{ background: 'var(--bg-secondary)', color: 'var(--text-primary)' }"
    :footer-style="{ background: 'var(--bg-secondary)', borderColor: 'var(--border-color)' }"
    @update:open="(value: boolean) => emit('update:open', value)"
  >
    <template #title>
      <div class="drawer-title-row">
        <span>历史对话</span>
        <a-button type="link" size="small" @click="emit('newChat')">
          <template #icon><PlusOutlined /></template>
          新建对话
        </a-button>
      </div>
    </template>

    <div v-if="!sessions.length" class="drawer-empty">暂无历史对话</div>
    <ul v-else class="session-list">
      <li
        v-for="record in sessions"
        :key="record.id"
        class="session-item"
        :class="{ active: record.id === currentSessionId }"
        @click="emit('restore', record)"
      >
        <div class="session-main">
          <div class="session-title">{{ record.title }}</div>
          <div class="session-meta">{{ formatRelativeTime(record.updatedAt) }} · {{ record.messageCount ?? record.messages.length }} 条</div>
        </div>
        <a-button
          type="text"
          size="small"
          class="session-delete"
          aria-label="删除会话"
          @click.stop="emit('remove', record.id)"
        >
          <template #icon><DeleteOutlined /></template>
        </a-button>
      </li>
    </ul>

  </a-drawer>
</template>

<script setup lang="ts">
/** 历史会话抽屉：列表 / 恢复 / 删除 / 新建对话（退出登录已上移到顶栏用户菜单） */
import { PlusOutlined, DeleteOutlined } from '@ant-design/icons-vue'
import type { ChatSessionRecord } from '@/composables/chatHistory'

defineProps<{
  open: boolean
  sessions: ChatSessionRecord[]
  currentSessionId?: string
}>()

const emit = defineEmits<{
  'update:open': [open: boolean]
  restore: [record: ChatSessionRecord]
  remove: [sessionId: string]
  newChat: []
}>()

const relativeTime = new Intl.RelativeTimeFormat('zh', { numeric: 'auto' })

const formatRelativeTime = (timestamp: number): string => {
  const diffMinutes = Math.round((timestamp - Date.now()) / 60_000)
  if (Math.abs(diffMinutes) < 60) return relativeTime.format(diffMinutes, 'minute')
  const diffHours = Math.round(diffMinutes / 60)
  if (Math.abs(diffHours) < 24) return relativeTime.format(diffHours, 'hour')
  const diffDays = Math.round(diffHours / 24)
  if (Math.abs(diffDays) < 30) return relativeTime.format(diffDays, 'day')
  return new Date(timestamp).toLocaleDateString('zh-CN')
}

</script>

<style lang="less" scoped>
.drawer-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.drawer-empty {
  padding: 48px 0;
  text-align: center;
  color: var(--text-tertiary);
}

.session-list {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.session-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;

  &:hover {
    background: var(--bg-tertiary);
  }

  &.active {
    background: var(--bg-tertiary);
    outline: 1px solid var(--border-color);
  }

  .session-main {
    flex: 1;
    min-width: 0;
  }

  .session-title {
    font-size: 14px;
    color: var(--text-primary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .session-meta {
    font-size: 12px;
    color: var(--text-tertiary);
    margin-top: 2px;
  }

  .session-delete {
    flex-shrink: 0;
    opacity: 0;
    color: var(--text-tertiary);
  }

  &:hover .session-delete {
    opacity: 1;
  }
}
</style>
