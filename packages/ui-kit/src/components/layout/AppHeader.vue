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
        <span v-if="version" class="app-version">v{{ version }}</span>
      </div>

      <a-button v-if="showHome && !showHomeInRight" type="text" class="home-btn" @click="$emit('home-click')" title="返回前台">
        <HomeOutlined />
      </a-button>

      <span v-if="projectName && !editableProjectName" class="project-name">{{ projectName }}</span>

      <a-button v-if="showAdmin && !showAdminInRight" type="text" class="admin-btn" @click="$emit('admin-click')" title="管理后台">
        <ControlOutlined />
        管理后台
      </a-button>
    </div>

    <div v-if="editableProjectName || centerTitle" class="header-center">
      <template v-if="editableProjectName">
        <input
          v-if="isEditing"
          ref="editInputRef"
          class="editable-name-input"
          :value="localProjectName"
          @blur="finishEdit"
          @keydown.enter="finishEdit"
          @keydown.escape="cancelEdit"
          @input="localProjectName = ($event.target as HTMLInputElement).value"
        />
        <span
          v-else
          class="editable-name"
          @dblclick="startEdit"
          title="双击编辑项目名称"
        >{{ localProjectName }}</span>
      </template>
      <span v-else-if="centerTitle" class="center-title">{{ centerTitle }}</span>
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

        <a-button v-if="showAdmin && showAdminInRight" type="text" class="admin-btn" @click="$emit('admin-click')" title="管理后台">
          <ControlOutlined />
        </a-button>

        <a-button v-if="showHome && showHomeInRight" type="text" class="home-btn" @click="$emit('home-click')" title="返回前台">
          <HomeOutlined />
        </a-button>

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
import { ref, nextTick, watch } from 'vue'
import {
  SettingOutlined,
  UserOutlined,
  BulbOutlined,
  BulbFilled,
  HomeOutlined,
  ControlOutlined
} from '@ant-design/icons-vue'
import { useTheme } from '../../composables/useTheme'

export interface NavItem {
  key: string
  label: string
}

interface Props {
  projectName?: string
  version?: string
  navItems?: NavItem[]
  activeNav?: string
  centerTitle?: string
  showAdmin?: boolean
  showHome?: boolean
  showSettings?: boolean
  logoClickable?: boolean
  editableProjectName?: boolean
  showHomeInRight?: boolean
  showAdminInRight?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  projectName: '',
  version: '',
  navItems: () => [],
  activeNav: '',
  centerTitle: '',
  showAdmin: false,
  showHome: false,
  showSettings: false,
  logoClickable: false,
  editableProjectName: false,
  showHomeInRight: false,
  showAdminInRight: false
})

const emit = defineEmits<{
  'nav-click': [key: string]
  'admin-click': []
  'home-click': []
  'settings-click': []
  'logo-click': []
  'update:projectName': [value: string]
}>()

const { isDark, appClass, toggleTheme: doToggleTheme } = useTheme()

const isEditing = ref(false)
const localProjectName = ref(props.projectName || '示例项目')
const editInputRef = ref<HTMLInputElement | null>(null)

watch(() => props.projectName, (val) => {
  if (val) localProjectName.value = val
})

/** 处理 Logo 点击 */
const handleLogoClick = () => {
  if (props.logoClickable) {
    emit('logo-click')
  }
}

/** 开始编辑项目名称 */
const startEdit = () => {
  isEditing.value = true
  nextTick(() => {
    editInputRef.value?.focus()
    editInputRef.value?.select()
  })
}

/** 完成编辑 */
const finishEdit = () => {
  isEditing.value = false
  const trimmed = localProjectName.value.trim()
  if (trimmed && trimmed !== props.projectName) {
    localProjectName.value = trimmed
    emit('update:projectName', trimmed)
  } else if (!trimmed) {
    localProjectName.value = props.projectName || '示例项目'
  }
}

/** 取消编辑 */
const cancelEdit = () => {
  isEditing.value = false
  localProjectName.value = props.projectName || '示例项目'
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

  .app-version {
    font-size: 11px;
    font-weight: 500;
    color: var(--text-secondary, rgba(0, 0, 0, 0.45));
    letter-spacing: 0;
    transform: translateY(1px);
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

  .editable-name {
    font-size: 16px;
    font-weight: 500;
    cursor: text;
    padding: 2px 8px;
    border-radius: 4px;
    border: 1px solid transparent;
    transition: all 0.2s ease;

    &:hover {
      border-color: var(--border-color, rgba(0, 0, 0, 0.15));
      background: var(--bg-tertiary, rgba(0, 0, 0, 0.04));
    }
  }

  .editable-name-input {
    font-size: 16px;
    font-weight: 500;
    padding: 2px 8px;
    border-radius: 4px;
    border: 1px solid var(--primary-color);
    outline: none;
    background: var(--bg-primary, #fff);
    color: var(--text-primary, rgba(0, 0, 0, 0.88));
    text-align: center;
    min-width: 120px;
    max-width: 300px;
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
