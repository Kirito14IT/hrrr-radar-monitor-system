<template>
  <div>
    <el-button type="primary" @click="toggleAutoRefresh" style="margin: 20px 0;">
      {{ isAutoRefreshing ? '停止监测' : '开始监测' }}
    </el-button>

    <div style="display: flex; justify-content: space-around; flex-wrap: wrap;">
      <div id="breath-chart" style="width: 600px; height: 400px;"></div>

      <div style="width: 500px; display: flex; align-items: center; justify-content: center;">
        <BreathRateMonitor :rate="currentBreathRate" :is-present="isUserPresent" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, reactive } from 'vue'
import * as echarts from 'echarts'
import request from '@/utils/request'
import BreathRateMonitor from './BreathRateMonitor.vue' // 引入刚才写的组件

const isAutoRefreshing = ref(false)
const currentBreathRate = ref(0)
const isUserPresent = ref(true)
let refreshTimer = null
let myChart = null

// 图表配置
const option = ref({
  title: { text: '实时呼吸波形 (相位)' },
  tooltip: { trigger: 'axis' },
  xAxis: { type: 'category', show: false }, // 隐藏X轴刻度
  yAxis: { type: 'value', min: -2, max: 2 }, // 根据模拟数据范围调整
  series: [{
    name: '呼吸波形',
    type: 'line',
    smooth: true,
    showSymbol: false,
    data: [],
    lineStyle: { color: '#1890ff', width: 3 }, // 蓝色线条
    areaStyle: { color: 'rgba(24, 144, 255, 0.1)' }
  }]
})

const loadData = async () => {
  try {
    const res = await request.get('/detailed')

    // 1. 获取呼吸率
    currentBreathRate.value = res.breath_rate || 0
    isUserPresent.value = (res.target_distance || 0) > 0.1 && currentBreathRate.value > 0

    // 2. 获取波形数据 (phase_values)
    // 这是后端生成的 100 个点的数组，直接显示就是波形
    const waveform = res.phase_values || []

    // 更新图表
    option.value.series[0].data = waveform
    // X轴数据简单生成 1-100 即可
    option.value.xAxis = { data: Array.from({length: waveform.length}, (_, i) => i) }

    if (myChart) myChart.setOption(option.value)

  } catch (err) {
    console.error("获取数据失败", err)
  }
}

const toggleAutoRefresh = () => {
  if (isAutoRefreshing.value) {
    clearInterval(refreshTimer)
    isAutoRefreshing.value = false
  } else {
    loadData()
    refreshTimer = setInterval(loadData, 200) // 10Hz刷新，波形更流畅
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

onMounted(() => { initChart() })
onUnmounted(() => { clearInterval(refreshTimer) })
</script>
