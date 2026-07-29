<template>
  <div class="api-key-chart">
    <div class="chart-header">
      <h3>解析统计</h3>
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
    <div ref="chartRef" class="chart-container"></div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import * as echarts from 'echarts'
import dayjs from 'dayjs'
import { apiKeysApi, type StatisticsItem } from '@/api/apiKeys'

const chartRef = ref<HTMLElement | null>(null)
const timeRange = ref('7d')
const customRange = ref<any[]>([])
let chartInstance: echarts.ECharts | null = null

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
    renderChart(res.data)
  } catch (e: any) {
    console.error('加载统计数据失败:', e)
  }
}

function renderChart(data: StatisticsItem[]) {
  if (!chartRef.value) return
  if (!chartInstance) {
    chartInstance = echarts.init(chartRef.value)
  }

  const dateMap = new Map<string, Map<string, number>>()
  const allUsers = new Set<string>()

  for (const item of data) {
    const date = item.date || '未知'
    const user = item.uploaded_by || '未知'
    allUsers.add(user)
    if (!dateMap.has(date)) dateMap.set(date, new Map())
    dateMap.get(date)!.set(user, (dateMap.get(date)!.get(user) || 0) + item.count)
  }

  const sortedDates = Array.from(dateMap.keys()).sort()
  const sortedUsers = Array.from(allUsers)

  const series = sortedUsers.map(user => ({
    name: user,
    type: 'bar' as const,
    stack: 'total',
    emphasis: { focus: 'series' as const },
    data: sortedDates.map(date => dateMap.get(date)?.get(user) || 0),
  }))

  chartInstance.setOption({
    tooltip: {
      trigger: 'axis' as const,
      axisPointer: { type: 'shadow' as const },
    },
    legend: {
      top: 0,
      type: 'scroll' as const,
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '3%',
      top: 40,
      containLabel: true,
    },
    xAxis: {
      type: 'category' as const,
      data: sortedDates,
    },
    yAxis: {
      type: 'value' as const,
      name: '解析文件数',
    },
    series,
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
  border-radius: 8px;
  padding: 16px;
}
.chart-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  h3 {
    margin: 0;
    font-size: 16px;
    color: var(--text-primary);
  }
}
.chart-container {
  width: 100%;
  height: 400px;
}
</style>
