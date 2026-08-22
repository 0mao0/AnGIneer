<template>
  <div class="api-key-chart">
    <div class="chart-header">
      <div class="chart-title-wrap">
        <h3>解析统计</h3>
        <span class="chart-subtitle">按文档数 / 页数统计各上传方的解析工作量</span>
      </div>
      <div class="chart-tools">
        <a-radio-group v-model:value="timeRange" @change="loadChart" size="small">
          <a-radio-button value="7d">近7天</a-radio-button>
          <a-radio-button value="this_month">本月</a-radio-button>
          <a-radio-button value="last_month">上月</a-radio-button>
          <a-radio-button value="custom">自定义</a-radio-button>
        </a-radio-group>
        <a-range-picker
          v-if="timeRange === 'custom'"
          v-model:value="customRange"
          size="small"
          style="margin-left: 8px"
          @change="loadChart"
        />
      </div>
    </div>

    <div class="chart-summary">
      <div class="summary-item">
        <span class="summary-dot" style="background: var(--primary-color, #1677ff)"></span>
        <div class="summary-meta">
          <span class="summary-label">解析文档</span>
          <span class="summary-value">{{ totalCount }}</span>
        </div>
      </div>
      <div class="summary-item">
        <span class="summary-dot" style="background: #13c2c2"></span>
        <div class="summary-meta">
          <span class="summary-label">解析页数</span>
          <span class="summary-value">{{ totalPages }}</span>
        </div>
      </div>
    </div>

    <div class="chart-wrap">
      <div ref="chartRef" class="chart-container"></div>
      <div v-if="!rawData.length" class="chart-empty">该时间段暂无解析记录</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import * as echarts from 'echarts'
import dayjs from 'dayjs'
import { apiKeysApi, type StatisticsItem } from '@/api/apiKeys'

const chartRef = ref<HTMLElement | null>(null)
const timeRange = ref('7d')
const customRange = ref<any[]>([])
const rawData = ref<StatisticsItem[]>([])
let chartInstance: echarts.ECharts | null = null

const totalCount = computed(() => rawData.value.reduce((s, i) => s + (i.count || 0), 0))
const totalPages = computed(() => rawData.value.reduce((s, i) => s + (i.page_count || 0), 0))

function getDateRange(): { start: string; end: string } {
  const today = dayjs()
  switch (timeRange.value) {
    case '7d':
      return { start: today.subtract(7, 'day').format('YYYY-MM-DD'), end: today.format('YYYY-MM-DD') }
    case 'this_month':
      return { start: today.startOf('month').format('YYYY-MM-DD'), end: today.format('YYYY-MM-DD') }
    case 'last_month':
      return {
        start: today.subtract(1, 'month').startOf('month').format('YYYY-MM-DD'),
        end: today.subtract(1, 'month').endOf('month').format('YYYY-MM-DD'),
      }
    case 'custom':
      if (customRange.value && customRange.value.length === 2) {
        return {
          start: customRange.value[0].format('YYYY-MM-DD'),
          end: customRange.value[1].format('YYYY-MM-DD'),
        }
      }
      return { start: today.subtract(7, 'day').format('YYYY-MM-DD'), end: today.format('YYYY-MM-DD') }
    default:
      return { start: today.subtract(7, 'day').format('YYYY-MM-DD'), end: today.format('YYYY-MM-DD') }
  }
}

async function loadChart() {
  if (!chartRef.value) return
  const { start, end } = getDateRange()
  try {
    const res = await apiKeysApi.getStatistics(start, end, 'day')
    rawData.value = res.data || []
    renderChart(rawData.value)
  } catch (e: any) {
    console.error('加载统计数据失败:', e)
  }
}

const PALETTE = ['#1677ff', '#52c41a', '#faad14', '#eb2f96', '#13c2c2', '#722ed1', '#fa541c', '#2f54eb']

function renderChart(data: StatisticsItem[]) {
  if (!chartRef.value) return
  if (!chartInstance) {
    chartInstance = echarts.init(chartRef.value)
  }
  // 容器尺寸可能因异步布局仍未就绪，强制按当前宽高重算
  chartInstance.resize()

  const dateMap = new Map<string, Map<string, { count: number; pages: number }>>()
  const allUsers = new Set<string>()

  for (const item of data) {
    const date = item.date || '未知'
    const user = item.uploaded_by || '未知'
    allUsers.add(user)
    if (!dateMap.has(date)) dateMap.set(date, new Map())
    const userMap = dateMap.get(date)!
    const cur = userMap.get(user) || { count: 0, pages: 0 }
    cur.count += item.count || 0
    cur.pages += item.page_count || 0
    userMap.set(user, cur)
  }

  const sortedDates = Array.from(dateMap.keys()).sort()

  // 日期标签：跨年显示 YYYY-MM-DD，同年内显示 MM-DD
  const dateLabels = sortedDates.map((d) => {
    const dt = dayjs(d)
    const sameYear = dt.year() === dayjs().year()
    return sameYear ? dt.format('MM-DD') : dt.format('YYYY-MM-DD')
  })
  const sortedUsers = Array.from(allUsers)

  const countSeries = sortedUsers.map((user, idx) => ({
    name: user,
    type: 'bar' as const,
    stack: 'docs',
    barMaxWidth: 28,
    itemStyle: {
      color: PALETTE[idx % PALETTE.length],
      borderRadius: [3, 3, 0, 0],
    },
    emphasis: { focus: 'series' as const },
    data: sortedDates.map(date => dateMap.get(date)?.get(user)?.count || 0),
  }))

  // 全部用户的页数总量（单条趋势线，右轴）
  const pagesTotal = sortedDates.map(date => {
    let sum = 0
    for (const user of sortedUsers) sum += dateMap.get(date)?.get(user)?.pages || 0
    return sum
  })
  const pagesSeries = [{
    name: '页数总量',
    type: 'line' as const,
    smooth: true,
    symbol: 'circle',
    symbolSize: 6,
    lineStyle: { width: 2.5, color: '#13c2c2' },
    itemStyle: { color: '#13c2c2' },
    areaStyle: {
      color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
        { offset: 0, color: 'rgba(19,194,194,0.25)' },
        { offset: 1, color: 'rgba(19,194,194,0.02)' },
      ]),
    },
    yAxisIndex: 1,
    emphasis: { focus: 'series' as const },
    data: pagesTotal,
  }]

  chartInstance.setOption({
    tooltip: {
      trigger: 'axis' as const,
      axisPointer: { type: 'shadow' as const },
      backgroundColor: 'rgba(255,255,255,0.97)',
      borderColor: '#e8e8e8',
      borderWidth: 1,
      padding: [10, 14],
      textStyle: { color: '#333', fontSize: 12 },
      formatter(params: any[]) {
        const docRows = params.filter((p: any) => p.seriesName !== '页数总量' && p.value > 0)
          .map((p: any) => `<div style="display:flex;justify-content:space-between;gap:16px"><span>${p.marker}${p.seriesName}</span><b>${p.value} 个</b></div>`)
        const total = params.find((p: any) => p.seriesName === '页数总量')
        const blocks: string[] = []
        if (docRows.length) blocks.push(`<div style="color:#999;font-size:11px;margin-bottom:4px">文档数</div>${docRows.join('')}`)
        if (total && total.value > 0) blocks.push(`<div style="color:#999;font-size:11px;margin:6px 0 4px">页数总量</div><div style="display:flex;justify-content:space-between;gap:16px"><span>${total.marker}全部上传者</span><b>${total.value} 页</b></div>`)
        return `<div style="font-weight:600;margin-bottom:6px">${params[0]?.axisValue}</div>${blocks.join('')}`
      },
    },
    legend: {
      top: 0,
      type: 'scroll' as const,
      icon: 'roundRect',
      itemWidth: 10,
      itemHeight: 10,
      textStyle: { fontSize: 12 },
    },
    grid: {
      left: '3%',
      right: '6%',
      bottom: '3%',
      top: 44,
      containLabel: true,
    },
    xAxis: {
      type: 'category' as const,
      data: dateLabels,
      axisLine: { lineStyle: { color: '#d9d9d9' } },
      axisTick: { show: false },
      axisLabel: { color: '#666', fontSize: 12 },
    },
    yAxis: [
      {
        type: 'value' as const,
        name: '文档数',
        nameTextStyle: { color: '#999', fontSize: 12 },
        splitLine: {
          lineStyle: { color: '#c0c0c0', type: 'dotted' as const },
        },
        axisLabel: { color: '#999', fontSize: 12 },
      },
      {
        type: 'value' as const,
        name: '页数',
        nameTextStyle: { color: '#999', fontSize: 12 },
        splitLine: { show: false },
        axisLabel: { color: '#999', fontSize: 12 },
      },
    ],
    series: [...countSeries, ...pagesSeries],
  })
}

function handleResize() {
  chartInstance?.resize()
}

onMounted(() => {
  loadChart()
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  chartInstance?.dispose()
})
</script>

<style lang="less" scoped>
.api-key-chart {
  margin-top: 24px;
  background: var(--bg-primary);
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
  border: 1px solid var(--border-color, #f0f0f0);
}
.chart-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
  h3 {
    margin: 0;
    font-size: 16px;
    color: var(--text-primary);
  }
}
.chart-title-wrap {
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.chart-subtitle {
  font-size: 12px;
  color: var(--text-secondary, rgba(0, 0, 0, 0.45));
}
.chart-tools {
  display: flex;
  align-items: center;
}
.chart-summary {
  display: flex;
  gap: 32px;
  margin-bottom: 16px;
}
.summary-item {
  display: flex;
  align-items: center;
  gap: 10px;
}
.summary-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}
.summary-meta {
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.summary-label {
  font-size: 13px;
  color: var(--text-secondary, rgba(0, 0, 0, 0.45));
}
.summary-value {
  font-size: 22px;
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1;
}
.chart-wrap {
  position: relative;
}
.chart-container {
  width: 100%;
  height: 400px;
}
.chart-empty {
  position: absolute;
  inset: 0;
  height: auto;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-secondary, rgba(0, 0, 0, 0.45));
  font-size: 14px;
  border: 1px dashed var(--border-color, #d9d9d9);
  border-radius: 8px;
  background: var(--bg-primary);
}
</style>
