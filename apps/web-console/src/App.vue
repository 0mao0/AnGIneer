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
          <LeftPanel v-model:active-section="activeSection" />
        </template>
        <template #center>
          <Workbench />
        </template>
        <template #right>
          <Panel :title="chatPanelTitle" :icon="MessageOutlined">
            <component
              :is="currentChatPanel"
              title=""
              :placeholder="chatPanelPlaceholder"
              :show-context-info="true"
            />
          </Panel>
        </template>
      </SplitPanes>
    </div>
  </a-config-provider>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import zhCN from 'ant-design-vue/es/locale/zh_CN'
import { MessageOutlined } from '@ant-design/icons-vue'
import { AppHeader, SplitPanes, Panel, useTheme, type NavItem } from '@angineer/ui-kit'
import { KnowledgeChatPanel, SOPChatPanel } from '@angineer/docs-ui'
import LeftPanel from './layouts/LeftPanel.vue'
import Workbench from './layouts/Workbench.vue'
import { ADMIN_CONSOLE_ORIGIN } from '../../shared/ports'

type ResourcePanelSection = 'project' | 'knowledge' | 'sop'

const { isDark, themeConfig, appClass, toggleTheme } = useTheme()
const activeSection = ref<ResourcePanelSection>('knowledge')

const currentChatPanel = computed(() => (
  activeSection.value === 'sop' ? SOPChatPanel : KnowledgeChatPanel
))

const chatPanelTitle = computed(() => (
  activeSection.value === 'sop' ? 'SOP 对话' : '知识对话'
))

const chatPanelPlaceholder = computed(() => (
  activeSection.value === 'sop' ? '输入 SOP 问题，Enter 发送...' : '输入消息，Enter 发送...'
))

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
