<template>
  <div class="ai-chat-view">
    <div class="ai-chat-toolbar">
      <span class="ai-chat-title">AI 对话</span>
      <a-button
        type="text"
        size="small"
        title="新建对话"
        aria-label="新建对话"
        @click="startNewChat"
      >
        <template #icon><PlusOutlined /></template>
      </a-button>
    </div>
    <div class="ai-chat-body">
      <AIChat
        ref="aiChatRef"
        title=""
        placeholder="输入消息，Enter 发送…"
        :show-context-info="true"
        :scene="'docs'"
        :session-id="chatSessionId"
        :transport="defaultAIChatTransport"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { PlusOutlined } from '@ant-design/icons-vue'
import { AIChat } from '@angineer/aichat-ui'
import { defaultAIChatTransport } from '../../../shared/chatTransport'

const chatNonce = ref(Date.now() + Math.floor(Math.random() * 1_000_000))
const chatSessionId = computed(() => `global::${chatNonce.value}`)
const aiChatRef = ref<InstanceType<typeof AIChat> | null>(null)

function startNewChat(): void {
  chatNonce.value += 1
  aiChatRef.value?.startNewChat?.()
}
</script>

<style lang="less" scoped>
.ai-chat-view {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--bg-secondary);
}

.ai-chat-toolbar {
  flex: none;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  border-bottom: 1px solid var(--border-color);
  background: var(--bg-primary);
}

.ai-chat-title {
  font-size: 15px;
  font-weight: 600;
}

.ai-chat-body {
  flex: 1;
  min-height: 0;
}
</style>
