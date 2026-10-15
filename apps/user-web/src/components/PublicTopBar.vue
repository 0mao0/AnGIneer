<template>
  <header class="public-top-bar">
    <AppBrand />
    <SiteNav />
    <div class="top-actions">
      <a-button v-if="authStore.guestMode" type="primary" size="small" @click="emit('login')">
        登录
      </a-button>
      <a-dropdown v-else placement="bottomRight">
        <a-button type="text" class="user-menu-btn">
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
/** 公开两页顶栏：品牌 + 全站页签 + 登录/用户菜单。形态克隆 ChatTopBar（UI 判据=克隆已有模式）。 */
import { computed } from 'vue'
import { LogoutOutlined } from '@ant-design/icons-vue'
import { AppBrand } from '@angineer/ui-kit'
import { useAuthStore } from '@/stores/auth'
import SiteNav from './SiteNav.vue'

const emit = defineEmits<{ (e: 'login'): void }>()
const authStore = useAuthStore()

const displayName = computed(
  () => authStore.user?.display_name || authStore.user?.username || '未登录'
)

const onUserMenuClick = async ({ key }: { key: string | number }) => {
  if (key === 'logout') {
    await authStore.logout()
    window.location.reload()
  }
}
</script>

<style lang="less" scoped>
.public-top-bar {
  flex-shrink: 0;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  background: var(--chat-root-bg, var(--bg-primary));
  color: var(--text-primary);

  .top-actions {
    display: flex;
    align-items: center;
    gap: 4px;
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
