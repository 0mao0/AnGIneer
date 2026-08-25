<template>
  <a-config-provider :locale="zhCN" :theme="themeConfig">
    <a-app>
      <div class="app-container" :class="appClass">
        <AppHeader
          layout="admin"
          :version="appVersion"
          :nav-items="navItems"
          :active-nav="activeNav"
          :module-items="navItems"
          :active-module="activeModule"
          :view-items="viewItems"
          :active-view="knowledgeView"
          :show-theme-toggle="false"
          logo-clickable
          @logo-click="confirmGoToFrontend"
          @module-click="handleNavClick"
          @view-change="handleViewChange"
          @nav-click="handleNavClick"
        >
          <template #user-menu>
            <a-button type="text" title="AI 对话" @click="router.push('/chat')">
              <WechatFilled />
            </a-button>
            <a-button type="text" title="用户管理" @click="router.push('/users')">
              <TeamOutlined />
            </a-button>
            <a-button type="text" title="API 管理" class="api-text-btn" @click="router.push('/api-keys')">
              API
            </a-button>
            <a-button type="text" title="切换主题" @click="toggleTheme">
              <BulbFilled v-if="isDark" />
              <BulbOutlined v-else />
            </a-button>
          </template>
        </AppHeader>

        <div class="main-content">
          <router-view />
        </div>
      </div>
    </a-app>
  </a-config-provider>
</template>

<script setup lang="ts">
import zhCN from 'ant-design-vue/es/locale/zh_CN'
import { Modal } from 'ant-design-vue'
import { BulbFilled, BulbOutlined, TeamOutlined, WechatFilled } from '@ant-design/icons-vue'
import { useRouter, useRoute } from 'vue-router'
import { computed, provide, ref } from 'vue'
import { AppHeader, useTheme, type NavItem } from '@angineer/ui-kit'
import { WEB_CONSOLE_ORIGIN } from '../../shared/ports'

const router = useRouter()
const route = useRoute()
const { themeConfig, appClass, isDark, toggleTheme } = useTheme()
const appVersion = import.meta.env.VITE_APP_VERSION || ''

/** 知识库视图状态（列表|解析）：由头部统一控制 */
const knowledgeView = ref<'list' | 'parse'>('list')
provide('knowledgeView', knowledgeView)

/** 当前模块为知识库时才显示视图切换（列表|解析） */
const viewItems = computed(() =>
  activeNav.value === 'knowledge'
    ? [
        { key: 'list', label: '列表' },
        { key: 'parse', label: '解析' }
      ]
    : []
)

/** 获取前台首页地址（开发环境用独立端口，生产环境同源） */
const webConsoleHref = import.meta.env.DEV ? WEB_CONSOLE_ORIGIN : '/'

/** 模块导航：AI 对话/用户管理/API 管理改为右上角图标入口，不再出现在模块下拉里 */
const navItems: NavItem[] = [
  { key: 'project', label: '项目库' },
  { key: 'knowledge', label: '知识库' },
  { key: 'experience', label: '经验库' },
  { key: 'evals', label: '评测集' },
  { key: 'dream-cycle', label: '健康检查' }
]

/** 模块下拉常驻：AI 对话/用户管理/API 管理由图标进入，但下拉保持显示，方便随时切回各模块 */
const activeModule = computed(() => {
  if (activeNav.value === 'chat') return 'AI 对话'
  if (activeNav.value === 'users') return '用户管理'
  if (activeNav.value === 'api-keys') return 'API 管理'
  return activeNav.value
})

const activeNav = computed(() => {
  const path = route.path
  if (path.startsWith('/chat')) return 'chat'
  if (path.startsWith('/evals')) return 'evals'
  if (path.startsWith('/project')) return 'project'
  if (path.startsWith('/experience')) return 'experience'
  if (path.startsWith('/dream-cycle')) return 'dream-cycle'
  if (path.startsWith('/users')) return 'users'
  if (path.startsWith('/api-keys')) return 'api-keys'
  return 'knowledge'
})

/** 导航项点击 */
const handleNavClick = (key: string) => {
  const routeMap: Record<string, string> = {
    chat: '/chat',
    project: '/project',
    knowledge: '/knowledge',
    experience: '/experience',
    evals: '/evals',
    'dream-cycle': '/dream-cycle',
    users: '/users',
    'api-keys': '/api-keys'
  }
  const path = routeMap[key]
  if (path) {
    router.push(path)
  }
}

/** 知识库视图切换 */
const handleViewChange = (key: string) => {
  if (key === 'list' || key === 'parse') {
    knowledgeView.value = key
  }
}

/** 确认返回前台 */
const confirmGoToFrontend = () => {
  Modal.confirm({
    title: '返回前台首页',
    content: '确定要返回前台首页吗？未保存的修改将会丢失。',
    okText: '确定',
    cancelText: '取消',
    onOk: () => {
      window.location.href = webConsoleHref
    }
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
  overflow: hidden;
}

.api-text-btn {
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.5px;
}

</style>
