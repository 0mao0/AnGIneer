/** angineer 图表块渲染器（v1）：v-html 后处理挂载 echarts。
 *  为什么不是 Vue 组件：markdown 输出走 v-html（不经 Vue 编译），
 *  在容器上后处理 querySelector 挂载是最贴合现有管线的方式。
 *  流式期间块未闭合时 markdown 层只出 pending 占位；闭合后 v-html 重建 DOM，
 *  本模块每次调用只挂「未挂载」的块，并 dispose 已脱离文档的旧实例（防泄漏）。 */
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { EChartsType } from 'echarts/core'

echarts.use([BarChart, LineChart, PieChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

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
  return {
    backgroundColor: 'transparent',
    color: dark ? DARK_PALETTE : LIGHT_PALETTE,
    textStyle,
    title: { text: spec.title, left: 'center', textStyle: { color: textStyle.color, fontSize: 14 } },
    tooltip: { trigger: 'axis' },
    legend,
    grid: { left: 48, right: 24, top: 40, bottom: legend ? 48 : 28, containLabel: false },
    xAxis: { type: 'category', data: spec.categories || [], axisLabel: { color: axisColor }, axisLine: { lineStyle: { color: splitColor } } },
    yAxis: {
      type: 'value',
      name: spec.unit || '',
      nameTextStyle: { color: axisColor },
      axisLabel: { color: axisColor },
      splitLine: { lineStyle: { color: splitColor } },
    },
    series: (spec.series || []).map(s => ({
      type: spec.chartType === 'line' ? 'line' : 'bar',
      name: String(s.name ?? ''),
      data: Array.isArray(s.data) ? s.data : [],
      smooth: spec.chartType === 'line',
    })),
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
