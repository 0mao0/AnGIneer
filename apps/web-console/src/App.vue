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
          <Panel title="AI 对话" :icon="MessageOutlined">
            <AIChat
              title=""
              placeholder="输入消息，Enter 发送..."
              :show-context-info="true"
              @send="handleChatSend"
              @ready="handleChatReady"
            />
          </Panel>
        </template>
      </SplitPanes>
    </div>
  </a-config-provider>
</template>

<script setup lang="ts">
import zhCN from 'ant-design-vue/es/locale/zh_CN'
import { onMounted } from 'vue'
import { MessageOutlined } from '@ant-design/icons-vue'
import { AppHeader, SplitPanes, Panel, useTheme, type NavItem } from '@angineer/ui-kit'
import { AIChat } from '@angineer/docs-ui'
import LeftPanel from './layouts/LeftPanel.vue'
import Workbench from './layouts/Workbench.vue'
import { useChatStore } from './stores/chat'
import { ADMIN_CONSOLE_ORIGIN } from '../../shared/ports'

const { isDark, themeConfig, appClass, toggleTheme } = useTheme()
const chatStore = useChatStore()

// 组件挂载时获取模型列表
onMounted(() => {
  chatStore.fetchModels()
})

// 处理 AI Chat 准备就绪
const handleChatReady = () => {
}

// 处理发送消息
const handleChatSend = async (message: string, _model: string) => {
  try {
    await chatStore.sendMessage(message, (_chunk) => {
      // 可以在这里处理每个 chunk，如果需要的话
    })
  } catch (error) {
    console.error('发送消息失败:', error)
  }
}

// 导航项配置
const navItems: NavItem[] = [
  { key: 'project', label: '项目库' },
  { key: 'knowledge', label: '知识库' },
  { key: 'experience', label: '经验库' }
]



// 跳转到管理后台
const goToAdmin = () => {
  window.location.href = ADMIN_CONSOLE_ORIGIN
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
