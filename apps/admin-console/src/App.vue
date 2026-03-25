<template>
  <a-config-provider :locale="zhCN" :theme="themeConfig">
    <div class="app-container" :class="appClass">
      <!-- 使用通用头部组件 -->
      <AppHeader
        :is-dark="isDark"
        project-name="管理后台"
        :nav-items="navItems"
        active-nav="knowledge"
        :show-home="true"
        :show-settings="true"
        logo-clickable
        @home-click="confirmGoToFrontend"
        @logo-click="confirmGoToFrontend"
        @nav-click="handleNavClick"
        @settings-click="openSettings"
        @toggle-theme="toggleTheme"
      />

      <!-- 主内容区 -->
      <div class="main-content">
        <router-view />
      </div>
    </div>
  </a-config-provider>
</template>

<script setup lang="ts">
import zhCN from 'ant-design-vue/es/locale/zh_CN'
import { Modal } from 'ant-design-vue'
import { useRouter } from 'vue-router'
import { AppHeader, useTheme, type NavItem } from '@angineer/ui-kit'
import { WEB_CONSOLE_ORIGIN } from '../../shared/ports'

const router = useRouter()
const { isDark, themeConfig, appClass, toggleTheme } = useTheme()

// 导航项配置
const navItems: NavItem[] = [
  { key: 'project', label: '项目库' },
  { key: 'knowledge', label: '知识库' },
  { key: 'experience', label: '经验库' }
]

// 处理导航点击
const handleNavClick = (key: string) => {
  const routeMap: Record<string, string> = {
    project: '/project',
    knowledge: '/knowledge',
    experience: '/experience'
  }
  const path = routeMap[key]
  if (path) {
    router.push(path)
  }
}

// 打开设置
const openSettings = () => {
  console.log('Open settings')
  // TODO: 实现设置弹窗
}

// 确认返回前台
const confirmGoToFrontend = () => {
  Modal.confirm({
    title: '返回前台首页',
    content: '确定要返回前台首页吗？未保存的修改将会丢失。',
    okText: '确定',
    cancelText: '取消',
    onOk: () => {
      window.location.href = WEB_CONSOLE_ORIGIN
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

.app-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  background-color: var(--bg-primary, #141414);
  transition: background-color 0.3s ease;
}

.main-content {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
</style>
