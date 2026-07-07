<template>
  <div class="breath-page care-page-shell">
    <el-button type="primary" @click="toggleAutoRefresh" style="margin: 0 0 16px;">
      {{ isAutoRefreshing ? '停止监测' : '开始监测' }}
    </el-button>

    <div class="breath-layout">
      <div id="breath-chart" class="breath-chart care-glass-card care-icon-card" data-icon="BR"></div>

      <div class="breath-monitor care-glass-card care-icon-card" data-icon="肺">
        <BreathRateMonitor :rate="currentBreathRate" :is-present="isUserPresent" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as echarts from 'echarts'
import request from '@/utils/request'
import BreathRateMonitor from './BreathRateMonitor.vue'
import { useThemeStore } from '@/stores/themeStore'

const themeStore = useThemeStore()
const isAutoRefreshing = ref(false)
const currentBreathRate = ref(0)
const isUserPresent = ref(true)
let refreshTimer = null
let myChart = null

const readToken = (name, fallback) => {
  if (typeof window === 'undefined') return fallback
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

const buildOption = () => ({
  backgroundColor: 'transparent',
  title: {
    text: '实时呼吸波形 (相位)',
    left: 'center',
    textStyle: { color: readToken('--care-text-strong', '#102333'), fontWeight: 700 }
  },
  tooltip: { trigger: 'axis' },
  xAxis: {
    type: 'category',
    show: false,
    data: [],
    axisLabel: { color: readToken('--care-muted', '#8c8c8c') }
  },
  yAxis: {
    type: 'value',
    min: -2,
    max: 2,
    splitLine: { lineStyle: { color: readToken('--care-grid-line-soft', '#eee') } },
    axisLabel: { color: readToken('--care-muted', '#8c8c8c') }
  },
  series: [{
    name: '呼吸波形',
    type: 'line',
    smooth: true,
    showSymbol: false,
    data: [],
    lineStyle: { color: 'rgb(24, 144, 255)', width: 3 },
    areaStyle: { color: 'rgba(24, 144, 255, 0.1)' }
  }]
})

const option = ref(buildOption())

const loadData = async () => {
  try {
    const res = await request.get('/detailed')

    currentBreathRate.value = res.breath_rate || 0
    isUserPresent.value = (res.target_distance || 0) > 0.1 && currentBreathRate.value > 0

    const waveform = res.phase_values || []

    option.value.series[0].data = waveform
    option.value.xAxis = { ...option.value.xAxis, data: Array.from({ length: waveform.length }, (_, i) => i) }

    if (myChart) myChart.setOption(option.value)
  } catch (err) {
    console.error('获取数据失败', err)
  }
}

const toggleAutoRefresh = () => {
  if (isAutoRefreshing.value) {
    clearInterval(refreshTimer)
    isAutoRefreshing.value = false
  } else {
    loadData()
    refreshTimer = setInterval(loadData, 200)
    isAutoRefreshing.value = true
  }
}

const initChart = () => {
  const dom = document.getElementById('breath-chart')
  if (dom) {
    myChart = echarts.init(dom)
    myChart.setOption(option.value)
  }
}

const applyTheme = () => {
  option.value = buildOption()
  if (myChart) myChart.setOption(option.value, true)
}

watch(() => themeStore.mode, () => {
  applyTheme()
})

onMounted(() => { initChart() })
onUnmounted(() => {
  clearInterval(refreshTimer)
  myChart?.dispose()
})
</script>

<style scoped>
.breath-page {
  display: flex;
  flex-direction: column;
  color: var(--care-text);
}

.breath-layout {
  display: flex;
  justify-content: space-around;
  align-items: stretch;
  flex-wrap: wrap;
  gap: 18px;
}

.breath-chart {
  width: 600px;
  max-width: 100%;
  height: 400px;
  padding: 16px;
}

.breath-monitor {
  width: 500px;
  max-width: 100%;
  padding: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
}

@media (max-width: 1100px) {
  .breath-layout {
    flex-direction: column;
    align-items: stretch;
  }

  .breath-chart,
  .breath-monitor {
    width: 100%;
  }
}
</style>
