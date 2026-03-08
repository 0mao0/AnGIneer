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
      root.style.setProperty('--bg-primary', '#141414')
      root.style.setProperty('--bg-secondary', '#1f1f1f')
      root.style.setProperty('--bg-tertiary', '#272727')
      root.style.setProperty('--text-primary', 'rgba(255, 255, 255, 0.85)')
      root.style.setProperty('--text-secondary', 'rgba(255, 255, 255, 0.65)')
      root.style.setProperty('--border-color', '#303030')
      root.style.setProperty('--panel-bg', '#1f1f1f')
      root.style.setProperty('--panel-header-bg', '#272727')
      root.style.setProperty('--docs-bg', '#141414')
      root.style.setProperty('--docs-pane-bg', '#1f1f1f')
      root.style.setProperty('--docs-pane-border', '#303030')
      root.style.setProperty('--docs-title-bg', '#1f1f1f')
      root.style.setProperty('--docs-title-border', '#303030')
      root.style.setProperty('--docs-text', 'rgba(255, 255, 255, 0.78)')
      root.style.setProperty('--docs-text-strong', 'rgba(255, 255, 255, 0.92)')
      root.style.setProperty('--docs-text-subtle', 'rgba(255, 255, 255, 0.62)')
      root.style.setProperty('--docs-progress-bg', '#1f1f1f')
      root.style.setProperty('--docs-content-bg', '#1f1f1f')
      root.style.setProperty('--docs-code-bg', '#1d2330')
      root.style.setProperty('--docs-inline-code-bg', 'rgba(255, 255, 255, 0.12)')
      root.style.setProperty('--docs-index-card-bg', '#1d2330')
      root.style.setProperty('--docs-empty-overlay', 'rgba(20, 20, 20, 0.92)')
      root.style.setProperty('--docs-empty-text', 'rgba(255, 255, 255, 0.6)')
      root.style.setProperty('--docs-segment-bg', '#2a3345')
      root.style.setProperty('--docs-segment-border', '#38445b')
      root.style.setProperty('--docs-segment-selected-bg', '#3a4660')
      root.style.setProperty('--docs-segment-selected-text', 'rgba(255, 255, 255, 0.9)')
      root.style.setProperty('--docs-segment-shared-bg', 'linear-gradient(90deg, #49aa19 0%, #237804 100%)')
      root.style.setProperty('--docs-segment-shared-border', '#237804')
      root.style.setProperty('--docs-math-bg', 'rgba(59, 130, 246, 0.18)')
      root.style.setProperty('--docs-math-color', 'rgba(219, 234, 254, 0.95)')
    } else {
      root.classList.remove('dark')
      root.classList.add('light')
      root.style.setProperty('--bg-primary', '#f0f2f5')
      root.style.setProperty('--bg-secondary', '#ffffff')
      root.style.setProperty('--bg-tertiary', '#fafafa')
      root.style.setProperty('--text-primary', 'rgba(0, 0, 0, 0.88)')
      root.style.setProperty('--text-secondary', 'rgba(0, 0, 0, 0.65)')
      root.style.setProperty('--border-color', '#e8e8e8')
      root.style.setProperty('--panel-bg', '#ffffff')
      root.style.setProperty('--panel-header-bg', '#fafafa')
      root.style.setProperty('--docs-bg', '#f0f2f5')
      root.style.setProperty('--docs-pane-bg', '#ffffff')
      root.style.setProperty('--docs-pane-border', '#e8edf4')
      root.style.setProperty('--docs-title-bg', '#ffffff')
      root.style.setProperty('--docs-title-border', '#edf1f7')
      root.style.setProperty('--docs-text', '#595959')
      root.style.setProperty('--docs-text-strong', '#4f5d7a')
      root.style.setProperty('--docs-text-subtle', '#8c8c8c')
      root.style.setProperty('--docs-progress-bg', '#f7f9fc')
      root.style.setProperty('--docs-content-bg', '#ffffff')
      root.style.setProperty('--docs-code-bg', '#f6f8fa')
      root.style.setProperty('--docs-inline-code-bg', 'rgba(0, 0, 0, 0.04)')
      root.style.setProperty('--docs-index-card-bg', '#fafcff')
      root.style.setProperty('--docs-empty-overlay', 'rgba(255, 255, 255, 0.92)')
      root.style.setProperty('--docs-empty-text', 'rgba(0, 0, 0, 0.45)')
      root.style.setProperty('--docs-segment-bg', '#dfe5f2')
      root.style.setProperty('--docs-segment-border', '#cdd6e7')
      root.style.setProperty('--docs-segment-selected-bg', '#ffffff')
      root.style.setProperty('--docs-segment-selected-text', '#1f2937')
      root.style.setProperty('--docs-segment-shared-bg', 'linear-gradient(90deg, #52c41a 0%, #389e0d 100%)')
      root.style.setProperty('--docs-segment-shared-border', '#389e0d')
      root.style.setProperty('--docs-math-bg', '#eef3ff')
      root.style.setProperty('--docs-math-color', '#1d3a8a')
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
