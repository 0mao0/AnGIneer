<template>
  <a-config-provider :locale="zhCN" :theme="themeConfig">
    <a-app>
      <!-- 无登录硬门（2026-09-17 改版）：有有效会话直接进，没有则以游客态直接进聊天页，
           满 30 轮由服务端闸拦再弹登录（ChatHome loginPrompt） -->
      <div class="app-container" :class="appClass">
        <div class="app-main">
          <router-view />
        </div>
        <!-- 备案位：站点标语沉底；全透明、无边框，与页面融为一体；右侧 GitHub 入口 -->
        <footer class="site-footer">
          <span class="footer-tagline">AnGIneer - Re-engineering the Future of Engineering.</span>
          <a
            class="footer-oss"
            href="https://github.com/0mao0/AnGIneer"
            target="_blank"
            rel="noopener"
            title="GitHub 仓库"
          >
            <svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor" aria-hidden="true">
              <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z" />
            </svg>
            <span>开源项目</span>
          </a>
        </footer>
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

.app-main {
  flex: 1;
  min-height: 0;
}

.site-footer {
  flex-shrink: 0;
  /* 标语 + 开源项目链接作为一个整体居中 */
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 3px 16px 5px;
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-tertiary);
  /* 透明会把 .app-container 的 --bg-primary 露出来（暗色 #141414），
     与上方聊天区 --chat-root-bg（暗色纯黑）形成色带；与 ChatTopBar 同源取色才能无缝 */
  background: var(--chat-root-bg, var(--bg-primary));

  .footer-oss {
    flex-shrink: 0;
    margin-inline-start: 12px;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    color: inherit;
    white-space: nowrap;

    &:hover {
      color: var(--text-secondary);
    }
  }
}
</style>
