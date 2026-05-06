<template>
  <div class="app-header" :class="appClass">
    <div class="header-left">
      <div class="app-logo" @click="handleLogoClick" :class="{ clickable: logoClickable }">
        <svg class="logo-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path
            d="M12 2C6.48 2 2 6.48 2 12C2 17.52 6.48 22 12 22C17.52 22 22 17.52 22 12C22 6.48 17.52 2 12 2ZM12 20C7.59 20 4 16.41 4 12C4 7.59 7.59 4 12 4C16.41 4 20 7.59 20 12C20 16.41 16.41 20 12 20ZM12.5 7H11V13L16.25 16.15L17 14.92L12.5 12.25V7Z"
            fill="url(#gradient)"
          />
          <defs>
            <linearGradient id="gradient" x1="2" y1="2" x2="22" y2="22" gradientUnits="userSpaceOnUse">
              <stop stop-color="var(--brand-gradient-start, #667eea)" />
              <stop offset="1" stop-color="var(--brand-gradient-end, #764ba2)" />
            </linearGradient>
          </defs>
        </svg>
        <span class="app-name">AnGIneer</span>
      </div>

      <a-button v-if="showHome" type="text" class="home-btn" @click="$emit('home-click')" title="返回前台">
        <HomeOutlined />
      </a-button>

      <span v-if="projectName" class="project-name">{{ projectName }}</span>

      <a-button v-if="showAdmin" type="text" class="admin-btn" @click="$emit('admin-click')">
        管理后台
      </a-button>
    </div>

    <div v-if="centerTitle" class="header-center">
      <span class="center-title">{{ centerTitle }}</span>
    </div>

    <div class="header-right">
      <a-space :size="4">
        <div v-if="navItems.length" class="nav-tabs">
          <a-button
            v-for="item in navItems"
            :key="item.key"
            type="text"
            :class="{ active: activeNav === item.key }"
            @click="$emit('nav-click', item.key)"
          >
            {{ item.label }}
          </a-button>
        </div>

        <a-button type="text" @click="doToggleTheme" class="theme-btn" title="切换主题">
          <BulbFilled v-if="isDark" />
          <BulbOutlined v-else />
        </a-button>

        <a-button v-if="showSettings" type="text" @click="$emit('settings-click')" title="设置">
          <SettingOutlined />
        </a-button>

        <a-button type="text">
          <UserOutlined />
        </a-button>
      </a-space>
    </div>
  </div>
</template>

<script setup lang="ts">
import {
  SettingOutlined,
  UserOutlined,
  BulbOutlined,
  BulbFilled,
  HomeOutlined
} from '@ant-design/icons-vue'
import { useTheme } from '../../composables/useTheme'

export interface NavItem {
  key: string
  label: string
}

interface Props {
  projectName?: string
  navItems?: NavItem[]
  activeNav?: string
  centerTitle?: string
  showAdmin?: boolean
  showHome?: boolean
  showSettings?: boolean
  logoClickable?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  projectName: '',
  navItems: () => [],
  activeNav: '',
  centerTitle: '',
  showAdmin: false,
  showHome: false,
  showSettings: false,
  logoClickable: false
})

const emit = defineEmits<{
  'nav-click': [key: string]
  'admin-click': []
  'home-click': []
  'settings-click': []
  'logo-click': []
}>()

const { isDark, appClass, toggleTheme: doToggleTheme } = useTheme()

/** 处理 Logo 点击 */
const handleLogoClick = () => {
  if (props.logoClickable) {
    emit('logo-click')
  }
}
</script>

<style lang="less" scoped>
.app-header {
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  flex-shrink: 0;
  transition: all 0.3s ease;
  backdrop-filter: blur(8px);
  background: var(--panel-header-bg, rgba(255, 255, 255, 0.8));
  border-bottom: 1px solid var(--border-color, rgba(0, 0, 0, 0.06));
  color: var(--text-primary, rgba(0, 0, 0, 0.88));
}

.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.app-logo {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 18px;
  font-weight: 700;
  letter-spacing: -0.3px;

  &.clickable {
    cursor: pointer;
  }

  .logo-icon {
    width: 28px;
    height: 28px;
  }

  .app-name {
    background: linear-gradient(135deg, var(--primary-color) 0%, var(--brand-gradient-end, #764ba2) 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
  }
}

.project-name {
  font-size: 14px;
  font-weight: 500;
  padding-left: 16px;
  border-left: 1px solid var(--border-color);
}

.home-btn {
  font-size: 14px;
  color: var(--text-secondary);

  &:hover {
    color: var(--primary-color);
  }
}

.admin-btn {
  font-size: 14px;
  color: var(--text-secondary);

  &:hover {
    color: var(--primary-color);
  }
}

.nav-tabs {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-right: 8px;

  .ant-btn {
    font-size: 14px;

    &.active {
      color: var(--primary-color);
      background: rgba(102, 126, 234, 0.1);
    }
  }
}

.header-center {
  flex: 1;
  display: flex;
  justify-content: center;

  .center-title {
    font-size: 16px;
    font-weight: 500;
  }
}

.header-right {
  display: flex;
  align-items: center;

  .btn-text {
    margin-left: 4px;
  }

  :deep(.ant-btn) {
    padding: 0 4px;
  }
}
</style>
