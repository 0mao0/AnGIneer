<template>
  <!-- 通用应用头部组件 - 统一前台和后台的标题栏 -->
  <div class="app-header" :class="{ 'dark-mode': isDark }">
    <!-- 左侧：Logo、项目名称、管理后台入口 -->
    <div class="header-left">
      <div class="app-logo" @click="handleLogoClick" :class="{ clickable: logoClickable }">
        <svg class="logo-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path
            d="M12 2C6.48 2 2 6.48 2 12C2 17.52 6.48 22 12 22C17.52 22 22 17.52 22 12C22 6.48 17.52 2 12 2ZM12 20C7.59 20 4 16.41 4 12C4 7.59 7.59 4 12 4C16.41 4 20 7.59 20 12C20 16.41 16.41 20 12 20ZM12.5 7H11V13L16.25 16.15L17 14.92L12.5 12.25V7Z"
            fill="url(#gradient)"
          />
          <defs>
            <linearGradient id="gradient" x1="2" y1="2" x2="22" y2="22" gradientUnits="userSpaceOnUse">
              <stop stop-color="#667eea" />
              <stop offset="1" stop-color="#764ba2" />
            </linearGradient>
          </defs>
        </svg>
        <span class="app-name">AnGIneer</span>
      </div>

      <!-- 返回前台 -->
      <a-button v-if="showHome" type="text" class="home-btn" @click="$emit('home-click')" title="返回前台">
        <HomeOutlined />
      </a-button>

      <!-- 项目名称 -->
      <span v-if="projectName" class="project-name">{{ projectName }}</span>

      <!-- 管理后台入口 -->
      <a-button v-if="showAdmin" type="text" class="admin-btn" @click="$emit('admin-click')">
        管理后台
      </a-button>
    </div>

    <!-- 中间：标题 -->
    <div v-if="centerTitle" class="header-center">
      <span class="center-title">{{ centerTitle }}</span>
    </div>

    <!-- 右侧：导航标签 + 操作按钮 -->
    <div class="header-right">
      <a-space size="small">
        <!-- 导航标签 -->
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

        <!-- 主题切换 -->
        <a-button type="text" @click="toggleTheme" class="theme-btn" title="切换主题">
          <BulbFilled v-if="isDark" />
          <BulbOutlined v-else />
        </a-button>

        <!-- 设置 -->
        <a-button v-if="showSettings" type="text" @click="$emit('settings-click')" title="设置">
          <SettingOutlined />
        </a-button>

        <!-- 用户 -->
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

/**
 * 导航项类型
 */
export interface NavItem {
  key: string
  label: string
}

/**
 * 通用应用头部组件
 * 统一前台和后台的标题栏样式和功能
 */
interface Props {
  /** 是否暗黑模式 */
  isDark: boolean
  /** 项目名称 */
  projectName?: string
  /** 导航项列表 */
  navItems?: NavItem[]
  /** 当前激活的导航 */
  activeNav?: string
  /** 中间标题 */
  centerTitle?: string
  /** 是否显示管理后台按钮 */
  showAdmin?: boolean
  /** 是否显示返回前台按钮 */
  showHome?: boolean
  /** 是否显示设置按钮 */
  showSettings?: boolean
  /** Logo 是否可点击 */
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
  'toggle-theme': []
}>()

/** 处理 Logo 点击 */
const handleLogoClick = () => {
  if (props.logoClickable) {
    emit('logo-click')
  }
}

/** 切换主题 */
const toggleTheme = () => {
  emit('toggle-theme')
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

  &:not(.dark-mode) {
    background: rgba(255, 255, 255, 0.8);
    border-bottom: 1px solid rgba(0, 0, 0, 0.06);
    color: rgba(0, 0, 0, 0.88);
  }

  &.dark-mode {
    background: rgba(20, 20, 20, 0.9);
    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    color: rgba(255, 255, 255, 0.85);
  }
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
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
  }
}

.project-name {
  font-size: 14px;
  font-weight: 500;
  padding-left: 16px;
  border-left: 1px solid rgba(0, 0, 0, 0.1);

  .dark-mode & {
    border-left-color: rgba(255, 255, 255, 0.1);
  }
}

.home-btn {
  font-size: 14px;
  color: rgba(0, 0, 0, 0.65);

  .dark-mode & {
    color: rgba(255, 255, 255, 0.65);
  }

  &:hover {
    color: #667eea;
  }
}

.admin-btn {
  font-size: 14px;
  color: rgba(0, 0, 0, 0.65);

  .dark-mode & {
    color: rgba(255, 255, 255, 0.65);
  }

  &:hover {
    color: #667eea;
  }
}

.nav-tabs {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-right: 16px;

  .ant-btn {
    font-size: 14px;

    &.active {
      color: #667eea;
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
}
</style>
