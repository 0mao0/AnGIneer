<template>
  <a-config-provider :locale="zhCN" :theme="themeConfig">
    <a-app>
      <div class="app-container" :class="appClass">
        <AppHeader
          :version="appVersion"
          :project-name="projectName"
          :editable-project-name="true"
          :show-admin="true"
          :show-admin-in-right="true"
          :show-settings="true"
          @admin-click="goToAdmin"
          @update:project-name="onProjectNameChange"
          @settings-click="openSettings"
        />
        <SplitPanes
          class="main-content"
          :initial-left-ratio="0.2"
          :left-collapsible="true"
          v-model:leftCollapsed="leftCollapsed"
          :show-right-pane="false"
          @resize="handleResize"
        >
          <template #left>
            <LeftPanel v-model:active-section="activeSection" />
          </template>
          <template #center>
            <Workbench />
          </template>
        </SplitPanes>

        <!-- AI 对话悬浮按钮 -->
        <a-button
          class="ai-chat-fab"
          type="primary"
          shape="circle"
          size="large"
          :icon="h(MessageOutlined)"
          @click="aiChatVisible = !aiChatVisible"
          :title="aiChatVisible ? '关闭AI对话' : '打开AI对话'"
        />

        <!-- AI 对话悬浮面板 -->
        <Transition name="ai-panel">
          <div v-if="aiChatVisible" class="ai-chat-overlay" @click.self="aiChatVisible = false">
            <div class="ai-chat-panel" @click.stop>
              <div class="ai-chat-panel-header">
                <div class="ai-chat-panel-title">
                  <MessageOutlined />
                  <span>{{ chatPanelTitle }}</span>
                </div>
                <a-button type="text" size="small" @click="aiChatVisible = false">
                  <template #icon><CloseOutlined /></template>
                </a-button>
              </div>
              <div class="ai-chat-panel-body">
                <AIChat
                  title=""
                  :placeholder="chatPanelPlaceholder"
                  :show-context-info="true"
                  :scene="activeSection === 'sop' ? 'sops' : 'docs'"
                  :session-id="chatSessionId"
                />
              </div>
            </div>
          </div>
        </Transition>
      </div>
    </a-app>
  </a-config-provider>
</template>

<script setup lang="ts">
import { computed, ref, h } from 'vue'
import zhCN from 'ant-design-vue/es/locale/zh_CN'
import { MessageOutlined, CloseOutlined } from '@ant-design/icons-vue'
import { AppHeader, SplitPanes, AIChat, useTheme } from '@angineer/ui-kit'
import LeftPanel from './layouts/LeftPanel.vue'
import Workbench from './layouts/Workbench.vue'
import { ADMIN_CONSOLE_ORIGIN, ADMIN_CONSOLE_PORT, LOCAL_HOST } from '../../shared/ports'
import { useWorkbenchStore } from '@/stores/workbench'
import { useTabRouterSync } from '@/composables/useTabRouterSync'

type ResourcePanelSection = 'project' | 'knowledge' | 'sop'

const { themeConfig, appClass } = useTheme()

useTabRouterSync()
const activeSection = ref<ResourcePanelSection>('knowledge')
const workbenchStore = useWorkbenchStore()
const appVersion = import.meta.env.VITE_APP_VERSION || ''

const projectName = ref('示例项目')

const aiChatVisible = ref(false)
const leftCollapsed = ref(false)

const chatPanelTitle = computed(() => (
  activeSection.value === 'sop' ? 'SOP 对话' : '知识对话'
))

const chatSessionId = computed(() => workbenchStore.activeTab || 'default')

const chatPanelPlaceholder = computed(() => (
  activeSection.value === 'sop' ? '输入 SOP 问题，Enter 发送...' : '输入消息，Enter 发送...'
))

/** 跳转到管理后台（开发环境用独立端口，生产环境同源） */
const adminConsoleHref = import.meta.env.DEV
  ? `http://${LOCAL_HOST}:${ADMIN_CONSOLE_PORT}/admin/`
  : ADMIN_CONSOLE_ORIGIN

/** 跳转到管理后台 */
const goToAdmin = () => {
  window.location.href = adminConsoleHref
}

/** 项目名称变更回调 */
const onProjectNameChange = (name: string) => {
  projectName.value = name
}

/** 打开设置 */
const openSettings = () => {
  console.log('Open settings')
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

.ant-app {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.app-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  background-color: var(--bg-primary);
  transition: background-color 0.3s ease;
}

.main-content {
  flex: 1;
  min-height: 0;
}

/* --- AI 对话悬浮按钮 --- */
.ai-chat-fab {
  position: fixed;
  right: 24px;
  bottom: 24px;
  z-index: 1000;
  width: 48px;
  height: 48px;
  font-size: 20px;
  box-shadow: 0 4px 16px rgba(24, 144, 255, 0.35);
  transition: all 0.3s ease;

  &:hover {
    transform: scale(1.08);
    box-shadow: 0 6px 24px rgba(24, 144, 255, 0.45);
  }
}

/* --- AI 对话悬浮面板 --- */
.ai-chat-overlay {
  position: fixed;
  inset: 0;
  z-index: 999;
  display: flex;
  justify-content: flex-end;
  align-items: flex-end;
  pointer-events: none;
}

.ai-chat-panel {
  position: fixed;
  right: 24px;
  bottom: 84px;
  width: 440px;
  height: 600px;
  max-height: calc(100vh - 140px);
  background: var(--panel-bg, #fff);
  border-radius: 12px;
  box-shadow: 0 8px 40px rgba(0, 0, 0, 0.15);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  pointer-events: auto;
  z-index: 1001;
  border: 1px solid var(--border-color, rgba(0, 0, 0, 0.08));
}

.ai-chat-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color, rgba(0, 0, 0, 0.06));
  flex-shrink: 0;
  background: var(--panel-header-bg);
}

.ai-chat-panel-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 500;
  font-size: 14px;
  color: var(--text-primary);

  .anticon {
    color: var(--primary-color);
  }
}

.ai-chat-panel-body {
  flex: 1;
  min-height: 0;
  overflow: hidden;

  .base-chat-component {
    height: 100%;
  }
}

/* --- 面板进出动画 --- */
.ai-panel-enter-active,
.ai-panel-leave-active {
  transition: all 0.25s ease;
}

.ai-panel-enter-from,
.ai-panel-leave-to {
  opacity: 0;
  transform: translateY(12px) scale(0.97);
}
</style>
