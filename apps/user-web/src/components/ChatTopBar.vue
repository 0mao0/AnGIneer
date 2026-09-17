<template>
  <header class="chat-top-bar">
    <AppBrand />
    <div class="top-actions">
      <a-button v-if="isAdmin" type="text" class="top-btn" title="进入管理工作台" @click="goWorkbench">
        <template #icon><AppstoreOutlined /></template>
        工作台
      </a-button>
      <a-tooltip title="历史对话">
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
 * 工作台（仅管理员可见，点击进入管理台）/ 历史 / 用户菜单（点用户名 → 退出登录）。
 */
import { computed } from 'vue'
import { AppstoreOutlined, HistoryOutlined, LogoutOutlined } from '@ant-design/icons-vue'
import { AppBrand } from '@angineer/ui-kit'
import { useAuthStore } from '@/stores/auth'
import { ADMIN_CONSOLE_ORIGIN, ADMIN_CONSOLE_PORT, createLocalOrigin } from '../../../shared/ports'

const emit = defineEmits<{
  (e: 'openHistory'): void
  (e: 'login'): void
}>()
const authStore = useAuthStore()

const displayName = computed(
  () => authStore.user?.display_name || authStore.user?.username || '未登录'
)

/** 仅管理员显示「工作台」，点击进入管理工作台 */
const isAdmin = computed(() => Boolean(authStore.user?.is_admin))

/** 管理工作台地址：开发环境用独立端口（/admin/），生产环境同源 /admin/ */
const adminConsoleHref = import.meta.env.DEV
  ? `${createLocalOrigin(ADMIN_CONSOLE_PORT)}/admin/`
  : ADMIN_CONSOLE_ORIGIN

const goWorkbench = () => {
  window.location.href = adminConsoleHref
}

const onUserMenuClick = async ({ key }: { key: string | number }) => {
  if (key === 'logout') {
    await authStore.logout()
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
  backdrop-filter: blur(8px);
  background: var(--panel-header-bg);
  border-bottom: 1px solid var(--border-color);
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
