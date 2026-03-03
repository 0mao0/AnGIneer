<template>
  <a-config-provider :locale="zhCN" :theme="themeConfig">
    <div class="app-container" :class="appClass">
      <AppHeader
        :is-dark="isDark"
        project-name="示例项目"
        :nav-items="navItems"
        :show-settings="true"
        @nav-click="goToAdmin"
        @settings-click="openSettings"
        @toggle-theme="toggleTheme"
      />
      <SplitPanes
        class="main-content"
        :initial-left-ratio="0.2"
        :initial-right-ratio="0.2"
        @resize="handleResize"
      >
        <template #left>
          <LeftPanel />
        </template>
        <template #center>
          <Workbench />
        </template>
        <template #right>
          <RagChat
            ref="ragChatRef"
            title="AI 对话"
            :placeholder="'输入消息，@ 引用知识库内容...'"
            :context-items="contextItems"
            @send="handleRagSend"
            @remove-context="removeContext"
          />
        </template>
      </SplitPanes>
    </div>
  </a-config-provider>
</template>

<script setup lang="ts">
import zhCN from 'ant-design-vue/es/locale/zh_CN'
import { ref, computed } from 'vue'
import { AppHeader, SplitPanes, useTheme, type NavItem } from '@angineer/ui-kit'
import { RagChat } from '@angineer/docs-ui'
import LeftPanel from './layouts/LeftPanel.vue'
import Workbench from './layouts/Workbench.vue'
import { useChatStore } from '@/stores/chat'

const { isDark, themeConfig, appClass, toggleTheme } = useTheme()
const chatStore = useChatStore()
const ragChatRef = ref<InstanceType<typeof RagChat> | null>(null)

// 计算属性
const contextItems = computed(() => chatStore.contextItems)

// 处理 RAG 发送消息
const handleRagSend = async (message: string, model: string) => {
  try {
    await chatStore.sendMessage(message, model)
  } catch (error) {
    console.error('发送消息失败:', error)
  }
}

// 移除上下文引用
const removeContext = (id: string) => {
  chatStore.removeContextItem(id)
}

// 导航项配置
const navItems: NavItem[] = [
  { key: 'project', label: '项目库' },
  { key: 'knowledge', label: '知识库' },
  { key: 'experience', label: '经验库' }
]

// 处理导航点击
const handleNavClick = (key: string) => {
  console.log('Nav clicked:', key)
  // TODO: 实现导航切换逻辑
}

// 跳转到管理后台
const goToAdmin = () => {
  window.location.href = 'http://localhost:3002'
}

// 打开设置
const openSettings = () => {
  console.log('Open settings')
  // TODO: 实现设置弹窗
}

const handleResize = (leftSize: number, rightSize: number) => {
  console.log('Resize:', leftSize, rightSize)
}
</script>

<style lang="less">
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html, body, #app {
  height: 100%;
  overflow: hidden;
}

.app-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  transition: background-color 0.3s ease;

  &.light-mode {
    background-color: #f5f5f5;
  }

  &.dark-mode {
    background-color: #141414;
  }
}

.main-content {
  flex: 1;
  min-height: 0;
}
</style>
