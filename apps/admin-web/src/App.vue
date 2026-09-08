<template>
  <a-config-provider :locale="zhCN" :theme="themeConfig">
    <a-app>
      <AuthGate />
      <div v-if="authStore.isAuthed && authStore.user?.is_admin" class="app-container" :class="appClass">
        <AppHeader
          layout="admin"
          :nav-items="navItems"
          :active-nav="activeNav"
          :module-items="navItems"
          :active-module="activeModule"
          :view-items="viewItems"
          :active-view="activeView"
          :show-theme-toggle="false"
          logo-clickable
          @logo-click="confirmGoToFrontend"
          @module-click="handleNavClick"
          @view-change="handleViewChange"
          @nav-click="handleNavClick"
        >
          <template #user-menu>
            <a-button type="text" title="AI 对话" @click="openUserChat">
              <WechatFilled />
            </a-button>
            <a-button type="text" title="API 管理" class="api-text-btn" @click="router.push('/api-keys')">
              API
            </a-button>
            <a-button type="text" title="用户管理" @click="router.push('/users')">
              <TeamOutlined />
            </a-button>
            <a-dropdown placement="bottomRight">
              <a-button type="text" class="user-menu-btn" :title="adminDisplayName">
                <span class="user-name">{{ adminDisplayName }}</span>
              </a-button>
              <template #overlay>
                <a-menu @click="onAdminUserMenuClick">
                  <a-menu-item key="logout">
                    <template #icon><LogoutOutlined /></template>
                    退出登录
                  </a-menu-item>
                </a-menu>
              </template>
            </a-dropdown>
          </template>
        </AppHeader>

        <div class="main-content">
          <router-view />
        </div>
      </div>
    </a-app>
  </a-config-provider>
</template>

<script setup lang="ts">
import zhCN from 'ant-design-vue/es/locale/zh_CN'
import { LogoutOutlined, TeamOutlined, WechatFilled } from '@ant-design/icons-vue'
import { useRouter, useRoute } from 'vue-router'
import { computed, provide, ref, watch } from 'vue'
import { AppHeader, useTheme, type NavItem } from '@angineer/ui-kit'
import AuthGate from './components/AuthGate.vue'
import { useAdminAuthStore } from './stores/auth'

const router = useRouter()
const route = useRoute()
const authStore = useAdminAuthStore()
const { themeConfig, appClass } = useTheme()

/** 知识库视图状态（日常维护|夜间测试|AI对话）：由头部统一控制 */
const knowledgeView = ref<'maintenance' | 'nightly' | 'aichat'>('maintenance')
provide('knowledgeView', knowledgeView)

/** 评测集视图状态（日常测试|夜间维护）：?view=nightly 深链直达（企微卡片入口）。
 * mount 未等 router.isReady()，setup 时 route.query 恒为空，必须 watch 到导航解析后再同步。 */
const evalView = ref<'workbench' | 'nightly'>('workbench')
provide('evalView', evalView)
watch(() => route.query.view, (v) => {
  if (v === 'nightly') evalView.value = 'nightly'
}, { immediate: true })

/** 头部视图切换按模块显示：知识库=日常维护|夜间维护|AI对话，评测集=日常测试|夜间测试 */
const viewItems = computed(() => {
  if (activeNav.value === 'knowledge') {
    return [
      { key: 'maintenance', label: '日常维护' },
      { key: 'nightly', label: '夜间维护' },
      { key: 'aichat', label: 'AI对话' }
    ]
  }
  if (activeNav.value === 'evals') {
    return [
      { key: 'workbench', label: '日常测试' },
      { key: 'nightly', label: '夜间测试' }
    ]
  }
  return []
})

/** 当前模块激活的视图 key（头部高亮用） */
const activeView = computed(() => (activeNav.value === 'evals' ? evalView.value : knowledgeView.value))

/** 模块导航：AI 对话/用户管理/API 管理改为右上角图标入口，不再出现在模块下拉里 */
const navItems: NavItem[] = [
  { key: 'project', label: '项目库' },
  { key: 'knowledge', label: '知识库' },
  { key: 'experience', label: '经验库' },
  { key: 'evals', label: '评测集' },
  { key: 'dream-cycle', label: '健康检查' }
]

/** 下拉只承载功能性模块；管理类入口（用户管理/API 管理）不占用选中态，下拉显示灰色占位 */
const activeModule = computed(() => {
  if (['users', 'api-keys'].includes(activeNav.value)) return ''
  return activeNav.value
})

const activeNav = computed(() => {
  const path = route.path
  if (path.startsWith('/evals')) return 'evals'
  if (path.startsWith('/project')) return 'project'
  if (path.startsWith('/experience')) return 'experience'
  if (path.startsWith('/dream-cycle')) return 'dream-cycle'
  if (path.startsWith('/users')) return 'users'
  if (path.startsWith('/api-keys')) return 'api-keys'
  return 'knowledge'
})

/** 导航项点击 */
const handleNavClick = (key: string) => {
  const routeMap: Record<string, string> = {
    project: '/project',
    knowledge: '/knowledge',
    experience: '/experience',
    evals: '/evals',
    'dream-cycle': '/dream-cycle',
    users: '/users',
    'api-keys': '/api-keys'
  }
  const path = routeMap[key]
  if (path) {
    router.push(path)
  }
}

/** 头部视图切换：按当前模块分发到对应视图状态 */
const handleViewChange = (key: string) => {
  if (activeNav.value === 'evals') {
    if (key === 'workbench' || key === 'nightly') {
      evalView.value = key
    }
    return
  }
  if (key === 'maintenance' || key === 'nightly' || key === 'aichat') {
    knowledgeView.value = key
  }
}

/** 右上角用户名：与 userweb 交互一致（点用户名 → 退出登录） */
const adminDisplayName = computed(
  () => authStore.user?.display_name || authStore.user?.username || '未登录'
)

/** AI 对话按钮：暂不跳转 */
const openUserChat = () => {}

const onAdminUserMenuClick = async ({ key }: { key: string | number }) => {
  if (key === 'logout') {
    await authStore.logout()
  }
}

/** 管理端 logo 点击：不做跳转 */
const confirmGoToFrontend = () => {}
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

.main-content {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.api-text-btn {
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.5px;
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
</style>
