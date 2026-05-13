<template>
  <a-config-provider :locale="zhCN" :theme="themeConfig">
    <a-app>
      <div class="app-container" :class="appClass">
        <AppHeader
          :version="appVersion"
          :nav-items="navItems"
          :active-nav="activeNav"
          :show-home="true"
          :show-home-in-right="true"
          :show-settings="true"
          logo-clickable
          @home-click="confirmGoToFrontend"
          @logo-click="confirmGoToFrontend"
          @nav-click="handleNavClick"
          @settings-click="openSettings"
        />

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
import { useRouter, useRoute } from 'vue-router'
import { computed } from 'vue'
import { AppHeader, useTheme, type NavItem } from '@angineer/ui-kit'
import { WEB_CONSOLE_ORIGIN } from '../../shared/ports'

const router = useRouter()
const route = useRoute()
const { themeConfig, appClass } = useTheme()
const appVersion = import.meta.env.VITE_APP_VERSION || ''

/** 获取前台首页地址（开发环境用独立端口，生产环境同源） */
const webConsoleHref = import.meta.env.DEV ? WEB_CONSOLE_ORIGIN : '/'

const navItems: NavItem[] = [
  { key: 'project', label: '项目库' },
  { key: 'knowledge', label: '知识库' },
  { key: 'experience', label: '经验库' },
  { key: 'evals', label: '评测集' }
]

const activeNav = computed(() => {
  const path = route.path
  if (path.startsWith('/evals')) return 'evals'
  if (path.startsWith('/project')) return 'project'
  if (path.startsWith('/experience')) return 'experience'
  return 'knowledge'
})

/** 导航项点击 */
const handleNavClick = (key: string) => {
  const routeMap: Record<string, string> = {
    project: '/project',
    knowledge: '/knowledge',
    experience: '/experience',
    evals: '/evals'
  }
  const path = routeMap[key]
  if (path) {
    router.push(path)
  }
}

/** 打开设置 */
const openSettings = () => {
  console.log('Open settings')
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
</style>
