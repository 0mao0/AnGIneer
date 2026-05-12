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
          :initial-right-ratio="0.2"
          @resize="handleResize"
        >
          <template #left>
            <LeftPanel v-model:active-section="activeSection" />
          </template>
          <template #center>
            <Workbench />
          </template>
          <template #right>
            <Panel :title="chatPanelTitle" :icon="MessageOutlined">
              <AIChat
                title=""
                :placeholder="chatPanelPlaceholder"
                :show-context-info="true"
                :scene="activeSection === 'sop' ? 'sops' : 'docs'"
                :session-id="chatSessionId"
              />
            </Panel>
          </template>
        </SplitPanes>
      </div>
    </a-app>
  </a-config-provider>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import zhCN from 'ant-design-vue/es/locale/zh_CN'
import { MessageOutlined } from '@ant-design/icons-vue'
import { AppHeader, SplitPanes, Panel, AIChat, useTheme } from '@angineer/ui-kit'
import LeftPanel from './layouts/LeftPanel.vue'
import Workbench from './layouts/Workbench.vue'
import { ADMIN_CONSOLE_ORIGIN } from '../../shared/ports'
import { useWorkbenchStore } from '@/stores/workbench'

type ResourcePanelSection = 'project' | 'knowledge' | 'sop'

const { themeConfig, appClass } = useTheme()
const activeSection = ref<ResourcePanelSection>('knowledge')
const workbenchStore = useWorkbenchStore()
const appVersion = import.meta.env.VITE_APP_VERSION || ''

const projectName = ref('示例项目')

const chatPanelTitle = computed(() => (
  activeSection.value === 'sop' ? 'SOP 对话' : '知识对话'
))

const chatSessionId = computed(() => workbenchStore.activeTab || 'default')

const chatPanelPlaceholder = computed(() => (
  activeSection.value === 'sop' ? '输入 SOP 问题，Enter 发送...' : '输入消息，Enter 发送...'
))

/** 跳转到管理后台 */
const goToAdmin = () => {
  window.location.href = ADMIN_CONSOLE_ORIGIN
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
</style>
