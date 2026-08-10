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
            <Workbench
              :show-right-panel="aiChatVisible"
              @navigate-section="onNavigateSection"
            >
              <template #right>
                <div class="ai-chat-dock">
                  <div class="ai-chat-dock-header">
                    <span class="ai-chat-dock-title">AI 对话</span>
                    <a-button
                      type="text"
                      size="small"
                      title="新建对话"
                      aria-label="新建对话"
                      @click="onNewChat"
                    >
                      <template #icon><PlusOutlined /></template>
                    </a-button>
                    <a-button
                      type="text"
                      size="small"
                      title="关闭"
                      aria-label="关闭"
                      @click="aiChatVisible = false"
                    >
                      <template #icon><CloseOutlined /></template>
                    </a-button>
                  </div>
                  <div class="ai-chat-panel-body">
                    <AIChat
                      ref="aiChatRef"
                      title=""
                      :placeholder="chatPanelPlaceholder"
                      :show-context-info="true"
                      :scene="activeSection === 'sop' ? 'sops' : 'docs'"
                      :session-id="chatSessionId"
                      :transport="defaultAIChatTransport"
                      @select-citation="handleCitationSelect"
                    />
                  </div>
                </div>
              </template>
            </Workbench>
          </template>
        </SplitPanes>

        <a-button
          v-if="!aiChatVisible"
          class="ai-chat-fab"
          type="primary"
          shape="circle"
          size="large"
          :icon="h(MessageOutlined)"
          :aria-label="aiChatVisible ? '关闭AI对话' : '打开AI对话'"
          :title="aiChatVisible ? '关闭AI对话' : '打开AI对话'"
          @click="aiChatVisible = !aiChatVisible"
        />
      </div>
    </a-app>
  </a-config-provider>
</template>

<script setup lang="ts">
import { computed, ref, h } from 'vue'
import zhCN from 'ant-design-vue/es/locale/zh_CN'
import { MessageOutlined, PlusOutlined, CloseOutlined } from '@ant-design/icons-vue'
import { AppHeader, SplitPanes, AIChat, useTheme } from '@angineer/ui-kit'
import LeftPanel from './layouts/LeftPanel.vue'
import Workbench from './layouts/Workbench.vue'
import { ADMIN_CONSOLE_ORIGIN, ADMIN_CONSOLE_PORT, LOCAL_HOST } from '../../shared/ports'
import { defaultAIChatTransport } from '../../shared/chatTransport'
import { useTabRouterSync } from '@/composables/useTabRouterSync'
import { useResourceOpen } from '@/composables/useResourceOpen'

type ResourcePanelSection = 'project' | 'knowledge' | 'sop'

const { themeConfig, appClass } = useTheme()
const { openResource } = useResourceOpen()

useTabRouterSync()
const activeSection = ref<ResourcePanelSection>('knowledge')
const appVersion = import.meta.env.VITE_APP_VERSION || ''

const projectName = ref('示例项目')

const aiChatVisible = ref(false)
const leftCollapsed = ref(false)
const aiChatRef = ref<InstanceType<typeof AIChat> | null>(null)

/** 全局会话：不随文档/页签变化，只有刷新或新建对话才换 key */
const chatNonce = ref(Date.now() + Math.floor(Math.random() * 1_000_000))
const chatSessionId = computed(() => `global::${chatNonce.value}`)
const onNewChat = () => {
  chatNonce.value += 1
  aiChatRef.value?.startNewChat?.()
}

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

const onNavigateSection = (section: 'project' | 'knowledge' | 'sop' | 'gis') => {
  if (section === 'gis') {
    return
  }
  activeSection.value = section
}

/** 参考依据点击：打开文档标签并携带定位参数（PDF/章节定位由 DocumentView 消费） */
const handleCitationSelect = (citation: any) => {
  if (!citation || !citation.doc_id) return
  openResource({
    id: citation.doc_id,
    title: citation.doc_title || citation.doc_id,
    resourceType: 'knowledge',
    isFolder: false,
    libraryId: 'default',
    docId: citation.doc_id,
    metadata: {
      sectionPath: citation.section_path,
      targetId: citation.target_id,
      pageIdx: citation.page_idx,
      snippet: citation.snippet,
    },
  })
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

.ai-chat-dock {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.ai-chat-dock-header {
  display: flex;
  align-items: center;
  gap: 4px;
  height: 40px;
  min-height: 40px;
  padding: 0 8px;
  border-bottom: 1px solid var(--border-color);
}

.ai-chat-dock-title {
  flex: 1;
  min-width: 0;
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
