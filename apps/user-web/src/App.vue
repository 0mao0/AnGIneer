<template>
  <a-config-provider :locale="zhCN" :theme="themeConfig">
    <a-app>
      <AuthGate />
      <div v-if="authStore.isAuthed || authStore.guestMode" class="app-container" :class="appClass">
        <router-view />
      </div>
    </a-app>
  </a-config-provider>
</template>

<script setup lang="ts">
import zhCN from 'ant-design-vue/es/locale/zh_CN'
import { useTheme } from '@angineer/ui-kit'
import AuthGate from './components/AuthGate.vue'
import { useAuthStore } from '@/stores/auth'

const { themeConfig, appClass } = useTheme()
const authStore = useAuthStore()
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
</style>
