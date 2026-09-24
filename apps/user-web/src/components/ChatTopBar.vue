<template>
  <header class="chat-top-bar">
    <AppBrand />
    <div class="top-actions">
      <!-- 游客不显示历史入口（产品决策 2026-09-18）：历史仅登录账号可见，游客档只服务端留存 -->
      <a-tooltip v-if="!authStore.guestMode" title="历史对话">
        <a-button type="text" class="top-btn" aria-label="历史对话" @click="emit('openHistory')">
          <template #icon><HistoryOutlined /></template>
        </a-button>
      </a-tooltip>
      <!-- 游客态：顶栏只留「登录」入口（D2）；登录/登出菜单仅登录态可见 -->
      <a-button v-if="authStore.guestMode" type="primary" size="small" class="login-btn" @click="emit('login')">
        登录
      </a-button>
      <a-dropdown v-else placement="bottomRight">
        <a-button type="text" class="top-btn user-menu-btn">
          <span class="user-name">{{ displayName }}</span>
        </a-button>
        <template #overlay>
          <a-menu @click="onUserMenuClick">
            <a-menu-item key="logout">
              <template #icon><LogoutOutlined /></template>
              退出登录
            </a-menu-item>
          </a-menu>
        </template>
      </a-dropdown>
    </div>
  </header>
</template>

<script setup lang="ts">
/**
 * 对话首页极简顶栏：品牌（logo+名称+版本 hover 发版弹层+主题灯泡，由 AppBrand 统一渲染）+
 * 历史 / 用户菜单（点用户名 → 退出登录）。
 */
import { computed } from 'vue'
import { HistoryOutlined, LogoutOutlined } from '@ant-design/icons-vue'
import { AppBrand } from '@angineer/ui-kit'
import { useAuthStore } from '@/stores/auth'

const emit = defineEmits<{
  (e: 'openHistory'): void
  (e: 'login'): void
}>()
const authStore = useAuthStore()

const displayName = computed(
  () => authStore.user?.display_name || authStore.user?.username || '未登录'
)

const onUserMenuClick = async ({ key }: { key: string | number }) => {
  if (key === 'logout') {
    await authStore.logout()
    // 退出即「从零开始」：整页刷新回到全新游客态（清空内存会话/历史面板/输入上下文），
    // 避免旧会话残留在界面上却又因身份作废无法续聊的错位状态
    window.location.reload()
  }
}
</script>

<style lang="less" scoped>
.chat-top-bar {
  flex-shrink: 0;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  transition: all 0.3s ease;
  background: var(--chat-root-bg, var(--bg-primary));
  color: var(--text-primary);

  .top-actions {
    display: flex;
    align-items: center;
    gap: 4px;

    :deep(.ant-btn) {
      padding: 0 4px;
    }
  }

  .top-btn {
    color: var(--text-secondary);
  }

  .user-menu-btn {
    display: flex;
    align-items: center;
    max-width: 200px;

    .user-name {
      font-size: 13px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
  }
}
</style>
