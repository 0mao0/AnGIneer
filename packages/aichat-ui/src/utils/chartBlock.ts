/** angineer 图表块渲染器（v1）：v-html 后处理挂载 echarts。
 *  为什么不是 Vue 组件：markdown 输出走 v-html（不经 Vue 编译），
 *  在容器上后处理 querySelector 挂载是最贴合现有管线的方式。
 *  流式期间块未闭合时 markdown 层只出 pending 占位；闭合后 v-html 重建 DOM，
 *  本模块每次调用只挂「未挂载」的块，并 dispose 已脱离文档的旧实例（防泄漏）。 */
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, TitleComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { EChartsType } from 'echarts/core'

echarts.use([BarChart, LineChart, PieChart, GridComponent, TooltipComponent, LegendComponent, TitleComponent, CanvasRenderer])

export interface AngineerChartSpec {
  chartType: 'bar' | 'line' | 'pie'
  title: string
  categories?: string[]
  series?: Array<{ name?: string; data?: number[]; value?: number }>
  unit?: string
  source?: string
}

const LIGHT_PALETTE = ['#5b8ff9', '#61ddaa', '#f6bd16', '#7262fd', '#78d3f8', '#9661bc']
const DARK_PALETTE = ['#5b8ff9', '#61ddaa', '#f6bd16', '#7262fd', '#78d3f8', '#9661bc']

const isDark = (): boolean =>
  typeof document !== 'undefined' &&
  (document.documentElement.classList.contains('dark') || document.documentElement.dataset.theme === 'dark')

const activeInstances = new Set<{ chart: EChartsType; dom: HTMLElement }>()

const maxOf = (data?: number[]): number => {
  if (!Array.isArray(data) || !data.length) return NaN
  let m = -Infinity
  for (const v of data) {
    const n = Number(v)
    if (Number.isFinite(n) && n > m) m = n
  }
  return m
}

/** 多系列 bar/line 量级差判定：首系列与其后系列 max 比值 ≥5 倍时挂双 y 轴
 *  （std-water 实测：总长 110m 与总宽 16.3m 挤同轴，窄量级系列被压扁成贴地板）。
 *  空数据/单系列/全零/非有限值一律 false（防除零），渲染不成为新失败点。 */
export const needsSecondaryAxis = (series?: AngineerChartSpec['series']): boolean => {
  if (!Array.isArray(series) || series.length < 2) return false
  const first = Math.abs(maxOf(series[0]?.data))
  if (!Number.isFinite(first) || first === 0) return false
  for (let i = 1; i < series.length; i += 1) {
    const m = Math.abs(maxOf(series[i]?.data))
    if (!Number.isFinite(m) || m === 0) continue
    if (first / m >= 5 || m / first >= 5) return true
  }
  return false
}

/** 双轴分配：以首系列 max 为左轴基准，量级偏离基准 ≥5 倍（大或小两个方向）的
 *  后续系列挂右轴。返回右轴系列下标列表（SSR 实测抓过只判「大 5 倍」单方向、
 *  小量级系列漏挂的错——两个方向都必须判）。 */
export const secondaryAxisIndexes = (series?: AngineerChartSpec['series']): number[] => {
  if (!Array.isArray(series) || series.length < 2) return []
  const base = Math.abs(maxOf(series[0]?.data))
  if (!Number.isFinite(base) || base === 0) return []
  const idx: number[] = []
  for (let i = 1; i < series.length; i += 1) {
    const m = Math.abs(maxOf(series[i]?.data))
    if (!Number.isFinite(m) || m === 0) continue
    const ratio = m / base
    if (ratio >= 5 || ratio <= 0.2) idx.push(i)
  }
  return idx
}

const buildOption = (spec: AngineerChartSpec, dark: boolean): echarts.EChartsCoreOption => {
  const axisColor = dark ? 'rgba(255,255,255,0.65)' : 'rgba(0,0,0,0.65)'
  const splitColor = dark ? 'rgba(255,255,255,0.12)' : 'rgba(0,0,0,0.08)'
  const textStyle = { color: dark ? 'rgba(255,255,255,0.85)' : 'rgba(0,0,0,0.88)' }
  const legend = spec.series && spec.series.length > 1
    ? { bottom: 0, textStyle: { color: axisColor } }
    : undefined
  if (spec.chartType === 'pie') {
    const data = (spec.series || []).map(s => ({ name: String(s.name ?? ''), value: Number(s.value ?? 0) }))
    return {
      backgroundColor: 'transparent',
      color: dark ? DARK_PALETTE : LIGHT_PALETTE,
      textStyle,
      title: { text: spec.title, left: 'center', textStyle: { color: textStyle.color, fontSize: 14 } },
      tooltip: { trigger: 'item' },
      legend,
      series: [{ type: 'pie', radius: ['38%', '66%'], center: ['50%', '54%'], data }],
    }
  }
  const dualAxis = needsSecondaryAxis(spec.series)
  const rightIdx = new Set(secondaryAxisIndexes(spec.series))
  const barLineSeries = (spec.series || []).map((s, i) => ({
    type: spec.chartType === 'line' ? 'line' : 'bar',
    name: String(s.name ?? ''),
    data: Array.isArray(s.data) ? s.data : [],
    smooth: spec.chartType === 'line',
    yAxisIndex: rightIdx.has(i) ? 1 : 0,
  }))
  const leftAxis = {
    type: 'value',
    name: spec.unit || '',
    nameTextStyle: { color: axisColor },
    axisLabel: { color: axisColor },
    splitLine: { lineStyle: { color: splitColor } },
  }
  return {
    backgroundColor: 'transparent',
    color: dark ? DARK_PALETTE : LIGHT_PALETTE,
    textStyle,
    title: { text: spec.title, left: 'center', textStyle: { color: textStyle.color, fontSize: 14 } },
    tooltip: { trigger: 'axis' },
    legend,
    grid: { left: 48, right: dualAxis ? 56 : 24, top: 40, bottom: legend ? 48 : 28, containLabel: false },
    xAxis: { type: 'category', data: spec.categories || [], axisLabel: { color: axisColor }, axisLine: { lineStyle: { color: splitColor } } },
    yAxis: dualAxis
      ? [
          leftAxis,
          { type: 'value', axisLabel: { color: axisColor }, splitLine: { show: false } },
        ]
      : leftAxis,
    series: barLineSeries,
  }
}

const mountOne = (el: HTMLElement): void => {
  const attr = el.getAttribute('data-chart')
  if (!attr) return
  let spec: AngineerChartSpec
  try {
    spec = JSON.parse(attr) as AngineerChartSpec
  } catch {
    el.textContent = '图表数据格式错误'
    return
  }
  if (!spec || typeof spec.chartType !== 'string') {
    el.textContent = '图表数据不完整'
    return
  }
  const chart = echarts.init(el)
  chart.setOption(buildOption(spec, isDark()))
  activeInstances.add({ chart, dom: el })
  el.setAttribute('data-mounted', '1')
}

/** 扫描 root 内未挂载的 angineer 图表块并挂载；先回收已脱离文档的旧实例。 */
export const mountChartBlocks = (root: HTMLElement): void => {
  for (const item of [...activeInstances]) {
    if (!document.contains(item.dom)) {
      item.chart.dispose()
      activeInstances.delete(item)
    }
  }
  if (!root.querySelector('.angineer-chart-block')) return
  root.querySelectorAll<HTMLElement>('.angineer-chart-block[data-chart]').forEach(el => {
    if (el.getAttribute('data-mounted')) return
    mountOne(el)
  })
}

let themeObserverStarted = false

/** 主题切换重上色：宿主暗色双形态（html.dark 类 / data-theme 属性，见 styles/index.less 注释）。 */
export const startChartThemeObserver = (): void => {
  if (themeObserverStarted || typeof document === 'undefined') return
  themeObserverStarted = true
  const observer = new MutationObserver(() => {
    const dark = isDark()
    for (const item of activeInstances) {
      const attr = item.dom.getAttribute('data-chart')
      if (!attr) continue
      try {
        item.chart.setOption(buildOption(JSON.parse(attr) as AngineerChartSpec, dark))
      } catch {
        /* spec 已在挂载时校验过，防御性忽略 */
      }
    }
  })
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class', 'data-theme'] })
}
