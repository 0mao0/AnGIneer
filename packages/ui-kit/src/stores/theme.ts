/**
 * 主题状态管理 - 通用主题系统
 * 提供明暗主题切换功能，支持 localStorage 持久化
 * 默认使用暗色模式
 */
import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

export const useThemeStore = defineStore('theme', () => {
  // 默认暗色模式
  const isDark = ref(true)

  const toggleTheme = () => {
    isDark.value = !isDark.value
    updateCssVariables(isDark.value)
  }

  const setTheme = (dark: boolean) => {
    isDark.value = dark
    updateCssVariables(isDark.value)
  }

  // 监听主题变化，持久化到 localStorage
  watch(isDark, (newVal) => {
    localStorage.setItem('angineer-theme', newVal ? 'dark' : 'light')
    updateCssVariables(newVal)
  })

  // 更新全局 CSS 变量和 html 类名
  const updateCssVariables = (dark: boolean) => {
    const root = document.documentElement
    if (dark) {
      root.classList.add('dark')
      root.classList.remove('light')
      // 暗色模式变量
      root.style.setProperty('--bg-primary', '#141414')
      root.style.setProperty('--bg-secondary', '#1f1f1f')
      root.style.setProperty('--bg-tertiary', '#272727')
      root.style.setProperty('--text-primary', 'rgba(255, 255, 255, 0.85)')
      root.style.setProperty('--text-secondary', 'rgba(255, 255, 255, 0.65)')
      root.style.setProperty('--border-color', '#303030')
      root.style.setProperty('--panel-bg', '#1f1f1f')
      root.style.setProperty('--panel-header-bg', '#272727')
    } else {
      root.classList.remove('dark')
      root.classList.add('light')
      // 亮色模式变量
      root.style.setProperty('--bg-primary', '#f0f2f5')
      root.style.setProperty('--bg-secondary', '#ffffff')
      root.style.setProperty('--bg-tertiary', '#fafafa')
      root.style.setProperty('--text-primary', 'rgba(0, 0, 0, 0.88)')
      root.style.setProperty('--text-secondary', 'rgba(0, 0, 0, 0.65)')
      root.style.setProperty('--border-color', '#e8e8e8')
      root.style.setProperty('--panel-bg', '#ffffff')
      root.style.setProperty('--panel-header-bg', '#fafafa')
    }
  }

  const initTheme = () => {
    const savedTheme = localStorage.getItem('angineer-theme')
    if (savedTheme) {
      isDark.value = savedTheme === 'dark'
    } else {
      // 默认暗色模式
      isDark.value = true
    }
    updateCssVariables(isDark.value)
  }

  return {
    isDark,
    toggleTheme,
    setTheme,
    initTheme
  }
})
