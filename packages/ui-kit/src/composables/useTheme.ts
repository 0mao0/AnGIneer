/**
 * 主题 Composable - 提供主题相关的计算属性和方法
 * 用于在组件中获取主题状态和 Ant Design 主题配置
 */
import { computed } from 'vue'
import { theme as antTheme } from 'ant-design-vue'
import { useThemeStore } from '../stores/theme'

export function useTheme() {
  const themeStore = useThemeStore()

  /**
   * Ant Design 主题配置
   * 根据当前主题状态返回对应的主题配置对象
   */
  const themeConfig = computed(() => ({
    algorithm: themeStore.isDark ? antTheme.darkAlgorithm : antTheme.defaultAlgorithm,
    token: {
      colorPrimary: '#667eea',
      borderRadius: 8,
      colorBgContainer: themeStore.isDark ? '#1f1f1f' : '#ffffff',
      colorBgElevated: themeStore.isDark ? '#272727' : '#ffffff',
      colorText: themeStore.isDark ? 'rgba(255, 255, 255, 0.85)' : 'rgba(0, 0, 0, 0.88)',
      colorTextSecondary: themeStore.isDark ? 'rgba(255, 255, 255, 0.65)' : 'rgba(0, 0, 0, 0.65)',
      colorBorder: themeStore.isDark ? '#424242' : '#d9d9d9',
      colorBorderSecondary: themeStore.isDark ? '#303030' : '#f0f0f0',
    },
  }))

  /**
   * 应用容器类名
   * 用于控制整体背景色
   */
  const appClass = computed(() => ({
    'dark-mode': themeStore.isDark,
    'light-mode': !themeStore.isDark
  }))

  /**
   * 切换主题
   */
  const toggleTheme = () => {
    themeStore.toggleTheme()
  }

  /**
   * 初始化主题
   */
  const initTheme = () => {
    themeStore.initTheme()
  }

  return {
    isDark: computed(() => themeStore.isDark),
    themeConfig,
    appClass,
    toggleTheme,
    initTheme
  }
}
