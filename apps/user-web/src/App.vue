<template>
  <a-config-provider :locale="zhCN" :theme="themeConfig">
    <a-app>
      <AuthGate />
      <div v-if="authStore.isAuthed" class="app-container" :class="appClass">
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
        >
          <template #user-menu>
            <a-dropdown placement="bottomRight">
              <a-button type="text" class="user-menu-btn" aria-label="个人菜单">
                <UserOutlined />
              </a-button>
              <template #overlay>
                <a-menu @click="onUserMenuClick">
                  <a-menu-item key="logout">退出登录</a-menu-item>
                </a-menu>
              </template>
            </a-dropdown>
          </template>
        </AppHeader>
        <SplitPanes
          ref="splitPanesRef"
          class="main-content"
          :initial-left-ratio="0.2"
          :initial-right-ratio="0.25"
          :left-collapsible="true"
          v-model:leftCollapsed="leftCollapsed"
          :right-collapsible="true"
          v-model:rightCollapsed="rightCollapsed"
          @resize="handleResize"
        >
          <template #left>
            <LeftPanel v-model:active-section="activeSection" />
          </template>
          <template #center>
            <Workbench
              ref="workbenchRef"
              @navigate-section="onNavigateSection"
            />
          </template>
          <template #right>
            <Panel title="AI 对话" :icon="MessageOutlined" contentClass="chat-panel-content">
              <template #extra>
                <a-select
                  v-if="authStore.libraries.length > 1"
                  v-model:value="authStore.activeLibraryId"
                  size="small"
                  class="chat-library-switcher"
                  :options="libraryOptions"
                  style="min-width: 140px"
                />
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
                  title="收起侧边栏"
                  aria-label="收起侧边栏"
                  @click="splitPanesRef?.toggleRight()"
                >
                  <template #icon><MenuUnfoldOutlined /></template>
                </a-button>
              </template>
              <AIChat
                ref="aiChatRef"
                title=""
                :placeholder="chatPanelPlaceholder"
                :show-context-info="true"
                :scene="activeSection === 'sop' ? 'sops' : 'docs'"
                :session-id="chatSessionId"
                :library-id="authStore.libraryId || 'default'"
                :transport="defaultAIChatTransport"
                @select-citation="handleCitationSelect"
              />
            </Panel>
          </template>
        </SplitPanes>
      </div>
    </a-app>
  </a-config-provider>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, nextTick } from 'vue'
import zhCN from 'ant-design-vue/es/locale/zh_CN'
import { MessageOutlined, PlusOutlined, UserOutlined, MenuUnfoldOutlined } from '@ant-design/icons-vue'
import { AppHeader, Panel, SplitPanes, useTheme } from '@angineer/ui-kit'
import { AIChat } from '@angineer/aichat-ui'
import LeftPanel from './layouts/LeftPanel.vue'
import Workbench from './layouts/Workbench.vue'
import AuthGate from './components/AuthGate.vue'
import { ADMIN_CONSOLE_ORIGIN, ADMIN_CONSOLE_PORT, LOCAL_HOST } from '../../shared/ports'
import { defaultAIChatTransport } from '../../shared/chatTransport'
import { useAuthStore } from '@/stores/auth'
import { knowledgeApi } from '@/api/knowledge'
import { useTabRouterSync } from '@/composables/useTabRouterSync'
import { useResourceOpen } from '@/composables/useResourceOpen'

type ResourcePanelSection = 'project' | 'knowledge' | 'sop'

const { themeConfig, appClass } = useTheme()
const { openResource } = useResourceOpen()

useTabRouterSync()
const activeSection = ref<ResourcePanelSection>('knowledge')
const appVersion = import.meta.env.VITE_APP_VERSION || ''

const projectName = ref('示例项目')

const authStore = useAuthStore()

const libraryNames = ref<Record<string, string>>({})
const libraryOptions = computed(() =>
  authStore.libraries.map((lid) => ({ value: lid, label: libraryNames.value[lid] || lid }))
)

const loadLibraryNames = async () => {
  try {
    const list = await knowledgeApi.getLibraries() as unknown as { id: string; name: string }[]
    libraryNames.value = Object.fromEntries(list.map((l) => [l.id, l.name]))
  } catch {
    // 名称加载失败时回退显示原始 id
  }
}

onMounted(() => {
  void loadLibraryNames()
})

const leftCollapsed = ref(false)
const rightCollapsed = ref(false)
const splitPanesRef = ref<InstanceType<typeof SplitPanes> | null>(null)
const workbenchRef = ref<InstanceType<typeof Workbench> | null>(null)
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

const onUserMenuClick = async ({ key }: { key: string }) => {
  if (key === 'logout') {
    await authStore.logout()
  }
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

/** 参考依据点击：打开/激活文档标签，并把引用直接交给当前文档视图联动（复用知识库工作区定位逻辑） */
const handleCitationSelect = async (citation: any) => {
  if (!citation || !citation.doc_id) return
  openResource({
    id: citation.doc_id,
    title: citation.doc_title || citation.doc_id,
    resourceType: 'knowledge',
    isFolder: false,
    libraryId: authStore.libraryId || 'default',
    docId: citation.doc_id,
  })
  await nextTick()
  workbenchRef.value?.focusCitation?.(citation)
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

.chat-panel-content {
  height: 100%;
  min-height: 0;

  .base-chat-component {
    height: 100%;
  }
}

.chat-library-switcher {
  margin-right: 8px;
}
</style>
