<template>
  <a-config-provider :locale="zhCN" :theme="themeConfig">
    <a-app>
      <!-- 无登录硬门（2026-09-17 改版）：有有效会话直接进，没有则以游客态直接进聊天页，
           满 30 轮由服务端闸拦再弹登录（ChatHome loginPrompt） -->
      <div class="app-container" :class="appClass">
        <router-view />
      </div>
    </a-app>
  </a-config-provider>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import zhCN from 'ant-design-vue/es/locale/zh_CN'
import { useTheme } from '@angineer/ui-kit'
import { useAuthStore } from '@/stores/auth'

const { themeConfig, appClass } = useTheme()
const authStore = useAuthStore()

onMounted(async () => {
  if (!authStore.token) {
    authStore.guestMode = true
    return
  }
  // 有 token：向服务端验证有效性（refreshMe 内部 401/403 自动登出）；
  // 会话过期则落回游客态并补签游客 cookie，保证首轮问答即落在 g: 桶
  try {
    await authStore.refreshMe()
    authStore.guestMode = false
  } catch {
    authStore.guestMode = true
    await authStore.enterGuestMode().catch(() => {})
  }
})
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
