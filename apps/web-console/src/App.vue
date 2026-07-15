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

        <a-button
          class="ai-chat-fab"
          type="primary"
          shape="circle"
          size="large"
          :icon="h(MessageOutlined)"
          @click="aiChatVisible = true"
          :title="'打开AI对话'"
        />

        <a-drawer
          v-model:open="aiChatVisible"
          title="AI 对话"
          placement="right"
          :width="440"
          :body-style="{ padding: 0, height: '100%', display: 'flex', flexDirection: 'column' }"
          :mask="false"
          :z-index="1001"
        >
          <div class="ai-chat-panel-body">
            <AIChat
              title=""
              :placeholder="chatPanelPlaceholder"
              :show-context-info="true"
              :scene="activeSection === 'sop' ? 'sops' : 'docs'"
              :session-id="chatSessionId"
            />
          </div>
        </a-drawer>
      </div>
    </a-app>
  </a-config-provider>
</template>

<script setup lang="ts">
import { computed, ref, h } from 'vue'
import zhCN from 'ant-design-vue/es/locale/zh_CN'
import { MessageOutlined } from '@ant-design/icons-vue'
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

const adminConsoleHref = import.meta.env.DEV
  ? `http://${LOCAL_HOST}:${ADMIN_CONSOLE_PORT}/admin/`
  : ADMIN_CONSOLE_ORIGIN

const goToAdmin = () => {
  window.location.href = adminConsoleHref
}

const onProjectNameChange = (name: string) => {
  projectName.value = name
}

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

.ai-chat-panel-body {
  flex: 1;
  min-height: 0;
  overflow: hidden;

  .base-chat-component {
    height: 100%;
  }
}
</style>
