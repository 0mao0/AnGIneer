/**
 * 主题切换防闪烁（方案 A：底层遮罩淡出）
 *
 * 原理：主题切换分两条链路——CSS 变量在 <html> 上同步生效，ant-design-vue cssinjs
 * 要晚 1–2 帧才把组件 token 样式注入完，中间那一帧就是「瞬间黑一下」的来源。
 * 修法：主题值一变（此时 <html> 变量还是旧主题色），立刻在页面底层
 * （z-index:-1，不遮挡任何交互）铺一层旧主题底色；等 <head> 里出现 cssinjs
 * 新插入/修改的样式（MutationObserver 侦测）后淡出。新色在遮罩下完成换装，
 * 肉眼只剩一次平滑渐变。
 *
 * 兜底：Observer 1s 没等到样式变动（首帧缓存命中等场景）也强制收场；
 * 任何情况下遮罩都会消失，不存在卡死路径。
 */
import { useThemeStore } from '../stores/theme'

let installed = false

export function installThemeTransition() {
  if (installed || typeof document === 'undefined') return
  installed = true

  const themeStore = useThemeStore()

  const veil = document.createElement('div')
  veil.style.cssText = [
    'position:fixed', 'inset:0', 'z-index:-1', 'pointer-events:none',
    'opacity:1', 'transition:opacity .3s ease',
  ].join(';')

  const hideVeil = () => {
    veil.style.opacity = '0'
    window.setTimeout(() => veil.remove(), 350)
  }

  themeStore.$subscribe(() => {
    if (veil.isConnected) return
    // 此刻 <html> 内联变量仍是旧主题色：遮罩取它当过渡色
    const prevBg = getComputedStyle(document.documentElement).getPropertyValue('--bg-primary').trim()
    veil.style.backgroundColor = prevBg || (themeStore.isDark ? '#f0f2f5' : '#141414')
    document.body.appendChild(veil)

    let settled = false
    const finish = () => {
      if (settled) return
      settled = true
      observer.disconnect()
      window.clearTimeout(fallback)
      // 再等一帧：cssinjs 一批常有多条样式，rAF 收口时最后一次插入也已落盘
      requestAnimationFrame(() => requestAnimationFrame(hideVeil))
    }

    const observer = new MutationObserver((records) => {
      const touched = records.some((r) =>
        Array.from(r.addedNodes).some((n) => n instanceof HTMLStyleElement) ||
        (r.target instanceof HTMLStyleElement),
      )
      if (touched) finish()
    })
    observer.observe(document.head, { childList: true, subtree: true, attributes: true })

    const fallback = window.setTimeout(finish, 1000)
  })
}
