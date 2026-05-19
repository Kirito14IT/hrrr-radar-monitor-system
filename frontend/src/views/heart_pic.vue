<template>
  <div class="dashboard-container">
    <div class="control-panel">
      <el-button
        :type="isAutoRefreshing ? 'danger' : 'primary'"
        size="large"
        @click="toggleAutoRefresh"
      >
        {{ isAutoRefreshing ? '停止监测' : '开始实时监测' }}
      </el-button>
      <div class="device-status">
        <span class="status-pill" :class="{ online: statusState.radar_board_online }">
          雷达开发板：{{ statusState.radar_board_online ? '在线' : '离线' }}
        </span>
        <span class="status-pill" :class="{ online: statusState.snore_board_online }">
          呼噜开发板：{{ statusState.snore_board_online ? '在线' : '离线' }}
        </span>
        <span class="status-pill" :class="{ warning: statusState.snore_detected }">
          呼噜事件：{{ statusState.snore_detected ? '最近检测到' : '暂无' }}
        </span>
      </div>
    </div>

    <div class="device-panel">
      <div class="device-card" :class="{ online: statusState.radar_board_online }">
        <div class="device-title">毫米波雷达模拟板</div>
        <div class="device-value">{{ statusState.radar_board_online ? '正在连续发送' : '未连接' }}</div>
        <div class="device-meta">数据来源：心率、呼吸率、距离、相位波形</div>
        <div class="device-meta">
          帧号 {{ statusState.last_radar_frame_number || 0 }} · 最近 {{ formatAge(statusState.radar_age_seconds) }}
        </div>
        <div v-if="!statusState.radar_board_online" class="device-hint">
          终端运行：python backend\mock_device_sender.py --radar-board
        </div>
      </div>

      <div class="device-card" :class="{ online: statusState.snore_board_online, warning: statusState.snore_detected }">
        <div class="device-title">呼噜检测模拟板</div>
        <div class="device-value">
          分数 {{ statusState.snore_score.toFixed(2) }} · 音频 {{ statusState.audio_upload_count || 0 }} 次
        </div>
        <div class="device-meta">数据来源：每秒呼噜特征 + 每 10 秒一个 10 秒音频片段</div>
        <div class="device-meta">
          当前音量 {{ formatDbfs(statusState.snore_dbfs) }} · 最近心跳 {{ formatAge(statusState.snore_age_seconds) }}
        </div>
        <div class="device-meta">最近音频 {{ formatAudioTime(statusState.last_audio_received_at) }}</div>
        <div v-if="!statusState.snore_board_online" class="device-hint">
          终端运行：python backend\mock_device_sender.py --snore-board
        </div>
      </div>
    </div>

    <div class="snore-wave-card" :class="{ active: statusState.snore_board_online, warning: statusState.snore_detected }">
      <div class="snore-wave-info">
        <div class="device-title">呼噜声浪监测</div>
        <div class="snore-wave-value">{{ snorePercent.toFixed(0) }}%</div>
        <div class="device-meta">
          {{ statusState.snore_board_online ? '声浪随呼噜检测板每秒特征实时变化' : '呼噜检测板离线，声浪暂停' }}
        </div>
      </div>
      <div class="sound-bars" aria-label="snore sound bars">
        <span
          v-for="bar in snoreBars"
          :key="bar.index"
          class="sound-bar"
          :class="{ hot: statusState.snore_detected }"
          :style="{ height: `${bar.height}%`, opacity: bar.opacity }"
        ></span>
      </div>
      <div class="snore-wave-readout">
        <span>dbFS：{{ formatDbfs(statusState.snore_dbfs) }}</span>
        <span>snore_score：{{ statusState.snore_score.toFixed(2) }}</span>
        <span>{{ statusState.snore_detected ? '检测到呼噜' : '未检测到明显呼噜' }}</span>
      </div>
    </div>

    <div class="insight-grid">
      <div class="insight-card">
        <div class="insight-title">睡眠分期</div>
        <div class="insight-value">{{ insight.sleepStage }}</div>
        <div class="insight-text">{{ insight.sleepReason }}</div>
      </div>
      <div class="insight-card">
        <div class="insight-title">呼噜-生命体征关联</div>
        <div class="insight-value">{{ insight.snoreLabel }}</div>
        <div class="insight-text">{{ insight.snoreImpact }}</div>
      </div>
      <div class="insight-card">
        <div class="insight-title">实时健康摘要</div>
        <div class="insight-value">{{ insight.latestTime || '等待数据' }}</div>
        <div class="insight-text">{{ insight.summary }}</div>
      </div>
    </div>

    <div class="charts-layout">
      <div class="module-card">
        <div class="chart-header">
          <span class="dot red"></span> 心率趋势 (Heart Rate)
          <span class="chart-subtitle">共享真实时间轴</span>
        </div>
        <div id="heart-chart" class="chart-box"></div>
        <div class="monitor-box">
          <HeartRateMonitor :rate="currentHeartRate" :is-present="isUserPresent" />
        </div>
      </div>

      <div class="module-card">
        <div class="chart-header">
          <span class="dot blue"></span> 呼吸趋势 (Breath Rate)
          <span class="chart-subtitle">与心率逐秒对齐</span>
        </div>
        <div id="breath-chart" class="chart-box"></div>
        <div class="monitor-box">
          <BreathRateMonitor :rate="currentBreathRate" :is-present="isUserPresent" />
        </div>
      </div>

      <div class="module-card snore-chart-card">
        <div class="chart-header">
          <span class="dot orange"></span> 呼噜强度趋势 (Snore Level)
          <span class="chart-subtitle">与心率/呼吸同一时间轴</span>
        </div>
        <div id="snore-chart" class="chart-box compact"></div>
        <div class="snore-note">
          呼噜图使用 0-100% 强度，离线时断线；心率/呼吸率仍由雷达板独立提供。
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import * as echarts from 'echarts'
import HeartRateMonitor from './HeartRateMonitor.vue'
import BreathRateMonitor from './BreathRateMonitor.vue'
import { useUserStore } from '@/stores/userStore'
import request from '@/utils/request'

const userStore = useUserStore()
const isAutoRefreshing = ref(false)
const currentHeartRate = ref(null)
const currentBreathRate = ref(null)
const isUserPresent = ref(false)
const soundTick = ref(0)

const statusState = reactive({
  radar_board_online: false,
  snore_board_online: false,
  audio_upload_count: 0,
  snore_detected: false,
  snore_score: 0,
  snore_dbfs: null,
  snore_level: null,
  last_audio_received_at: null,
  last_radar_frame_number: 0,
  radar_age_seconds: null,
  snore_age_seconds: null
})

const insight = reactive({
  sleepStage: '等待数据',
  sleepReason: '启动模拟开发板后，这里会根据心率、呼吸率和呼噜分数估计状态。',
  snoreLabel: '暂无事件',
  snoreImpact: '最近 3 分钟未检测到呼噜事件。',
  summary: '等待雷达模拟板和呼噜检测模拟板上线。',
  latestTime: ''
})

let refreshTimer = null
let heartChart = null
let breathChart = null
let snoreChart = null

const isNumber = (value) => typeof value === 'number' && Number.isFinite(value)

const snorePercent = computed(() => {
  if (!statusState.snore_board_online) return 0
  const level = isNumber(statusState.snore_level) ? statusState.snore_level : statusState.snore_score
  return Math.max(0, Math.min(100, Number(level || 0) * 100))
})

const snoreBars = computed(() => {
  const base = snorePercent.value / 100
  return Array.from({ length: 34 }, (_, index) => {
    const wave = Math.abs(Math.sin(index * 0.62 + soundTick.value * 0.55))
    const ripple = Math.abs(Math.cos(index * 0.29 - soundTick.value * 0.31))
    return {
      index,
      height: statusState.snore_board_online ? Math.min(100, 8 + base * (38 + 54 * wave) + 10 * ripple) : 8,
      opacity: statusState.snore_board_online ? 0.45 + 0.55 * Math.max(base, wave * base) : 0.22
    }
  })
})

const initOption = (color, unit, yMax = null) => ({
  grid: { top: 35, right: 24, bottom: 42, left: 45 },
  tooltip: {
    trigger: 'axis',
    formatter: (params) => {
      const item = params?.[0]
      const value = item?.data
      return `${item?.axisValue || ''}<br/>${value === null || value === undefined ? '无数据' : `${value} ${unit}`}`
    }
  },
  xAxis: {
    type: 'category',
    boundaryGap: false,
    data: [],
    axisLabel: { color: '#8c8c8c', fontSize: 11 },
    axisLine: { lineStyle: { color: '#d9d9d9' } }
  },
  yAxis: {
    type: 'value',
    scale: yMax === null,
    max: yMax,
    min: yMax === null ? null : 0,
    splitLine: { lineStyle: { type: 'dashed' } },
    axisLabel: { color: '#8c8c8c' }
  },
  series: [{
    type: 'line',
    smooth: true,
    symbol: 'none',
    connectNulls: false,
    lineStyle: { width: 3, color },
    areaStyle: {
      color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
        { offset: 0, color: color.replace(')', ', 0.28)').replace('rgb', 'rgba') },
        { offset: 1, color: color.replace(')', ', 0.0)').replace('rgb', 'rgba') }
      ])
    },
    data: []
  }]
})

const optionHeart = ref(initOption('rgb(255, 87, 87)', 'BPM'))
const optionBreath = ref(initOption('rgb(24, 144, 255)', 'RPM'))
const optionSnore = ref(initOption('rgb(250, 140, 22)', '%', 100))

const formatAudioTime = (value) => {
  if (!value) return '暂无'
  try {
    return new Date(value).toLocaleTimeString()
  } catch {
    return value
  }
}

const formatDbfs = (value) => isNumber(value) ? `${Number(value).toFixed(1)} dBFS` : '--'

const formatAge = (value) => {
  if (value === null || value === undefined) return '暂无'
  if (value < 1) return '刚刚'
  return `${Number(value).toFixed(1)} 秒前`
}

const formatTimeLabel = (value) => {
  if (!value) return ''
  try {
    return new Date(value).toLocaleTimeString([], { hour12: false, minute: '2-digit', second: '2-digit' })
  } catch {
    return value
  }
}

const average = (rows, key) => {
  const values = rows.map(row => row[key]).filter(isNumber)
  if (!values.length) return null
  return values.reduce((sum, value) => sum + value, 0) / values.length
}

const setCharts = (rows) => {
  const labels = rows.map(row => formatTimeLabel(row.timestamp))
  optionHeart.value.xAxis.data = labels
  optionBreath.value.xAxis.data = labels
  optionSnore.value.xAxis.data = labels
  optionHeart.value.series[0].data = rows.map(row => isNumber(row.heart_rate) ? row.heart_rate : null)
  optionBreath.value.series[0].data = rows.map(row => isNumber(row.breath_rate) ? row.breath_rate : null)
  optionSnore.value.series[0].data = rows.map(row => row.snore_online && isNumber(row.snore_level) ? Math.round(row.snore_level * 100) : null)
  heartChart?.setOption(optionHeart.value, true)
  breathChart?.setOption(optionBreath.value, true)
  snoreChart?.setOption(optionSnore.value, true)
}

const updateInsights = (rows) => {
  if (!rows.length) {
    currentHeartRate.value = null
    currentBreathRate.value = null
    isUserPresent.value = false
    insight.sleepStage = '等待数据'
    insight.sleepReason = '还没有收到时间轴数据，请确认模拟后端正在运行。'
    insight.snoreLabel = '暂无事件'
    insight.snoreImpact = '最近 3 分钟未检测到呼噜事件。'
    insight.summary = '等待模拟开发板上线。'
    insight.latestTime = ''
    return
  }

  const latest = rows[rows.length - 1]
  const radarValid = !!latest.radar_online && isNumber(latest.heart_rate) && isNumber(latest.breath_rate)
  currentHeartRate.value = radarValid ? latest.heart_rate : null
  currentBreathRate.value = radarValid ? latest.breath_rate : null
  isUserPresent.value = radarValid
  insight.latestTime = formatTimeLabel(latest.timestamp)
  insight.sleepStage = latest.sleep_stage || '等待数据'

  if (!latest.radar_online) {
    insight.sleepReason = '雷达模拟板离线或无人，心率/呼吸图表会断线，不再用 0 伪装成真实数据。'
    insight.summary = latest.snore_online
      ? '雷达模拟板未连接；呼噜板仍在线，所以声浪和呼噜强度趋势仍可继续显示。'
      : '雷达模拟板和呼噜检测板都未连接。'
  } else if (latest.snore_detected) {
    insight.sleepReason = '当前检测到呼噜扰动，分期暂时标记为疑似呼噜扰动。'
    insight.summary = `当前心率 ${latest.heart_rate} BPM，呼吸 ${latest.breath_rate} RPM，伴随呼噜事件。`
  } else {
    insight.sleepReason = `基于当前心率 ${latest.heart_rate} BPM、呼吸 ${latest.breath_rate} RPM、呼噜分数 ${Number(latest.snore_score || 0).toFixed(2)} 估计。`
    insight.summary = '心率、呼吸率、呼噜强度三张图共用同一批秒级时间戳，事件时间点对齐。'
  }

  let lastSnoreIndex = -1
  rows.forEach((row, index) => {
    if (row.snore_detected) lastSnoreIndex = index
  })
  if (lastSnoreIndex < 0) {
    insight.snoreLabel = '暂无事件'
    insight.snoreImpact = latest.snore_online
      ? '呼噜检测板在线，但最近时间窗内没有明显呼噜事件。'
      : '呼噜检测板离线；雷达呼吸率仍可继续运行。'
    return
  }

  const beforeRows = rows.slice(Math.max(0, lastSnoreIndex - 6), lastSnoreIndex)
  const afterRows = rows.slice(lastSnoreIndex, Math.min(rows.length, lastSnoreIndex + 7))
  const beforeHr = average(beforeRows, 'heart_rate')
  const afterHr = average(afterRows, 'heart_rate')
  const beforeBr = average(beforeRows, 'breath_rate')
  const afterBr = average(afterRows, 'breath_rate')
  const eventTime = formatTimeLabel(rows[lastSnoreIndex].timestamp)

  insight.snoreLabel = `最近 ${eventTime}`
  if (beforeHr === null || afterHr === null || beforeBr === null || afterBr === null) {
    insight.snoreImpact = '呼噜事件附近缺少足够雷达生命体征数据，暂时无法估计影响。'
  } else {
    const deltaHr = afterHr - beforeHr
    const deltaBr = afterBr - beforeBr
    insight.snoreImpact = `事件后心率变化 ${deltaHr >= 0 ? '+' : ''}${deltaHr.toFixed(1)} BPM，呼吸变化 ${deltaBr >= 0 ? '+' : ''}${deltaBr.toFixed(1)} RPM。`
  }
}

const loadStatus = async () => {
  try {
    const res = await request.get('/status')
    statusState.radar_board_online = !!res.radar_board_online
    statusState.snore_board_online = !!res.snore_board_online
    statusState.audio_upload_count = res.audio_upload_count || 0
    statusState.snore_detected = !!res.snore_detected
    statusState.snore_score = Number(res.snore_score || 0)
    statusState.snore_dbfs = isNumber(res.snore_dbfs) ? Number(res.snore_dbfs) : null
    statusState.snore_level = isNumber(res.snore_level) ? Number(res.snore_level) : null
    statusState.last_audio_received_at = res.last_audio_received_at || null
    statusState.last_radar_frame_number = res.last_radar_frame_number || 0
    statusState.radar_age_seconds = res.radar_age_seconds
    statusState.snore_age_seconds = res.snore_age_seconds
  } catch (error) {
    console.warn('获取模拟设备状态失败:', error)
    statusState.radar_board_online = false
    statusState.snore_board_online = false
  }
}

const loadSensorData = async () => {
  try {
    const res = await request.get('/timeline', { params: { seconds: 180 } })
    const rows = Array.isArray(res.data) ? res.data : []
    setCharts(rows)
    updateInsights(rows)
    await loadStatus()
    soundTick.value += 1

    const latest = rows[rows.length - 1]
    if (
      isAutoRefreshing.value &&
      userStore.userInfo?.userID &&
      latest?.radar_online &&
      isNumber(latest.heart_rate) &&
      isNumber(latest.breath_rate)
    ) {
      await request.post('/save-vitals-with-user', {
        userID: userStore.userInfo.userID,
        heart_rate: latest.heart_rate,
        breath_rate: latest.breath_rate,
        target_distance: latest.target_distance || 0,
        timestamp: latest.timestamp
      }).catch(err => console.warn('保存用户生命体征失败:', err))
    }
  } catch (error) {
    console.error('获取时间轴数据失败:', error)
    isUserPresent.value = false
    currentHeartRate.value = null
    currentBreathRate.value = null
  }
}

const toggleAutoRefresh = () => {
  if (isAutoRefreshing.value) {
    clearInterval(refreshTimer)
    refreshTimer = null
    isAutoRefreshing.value = false
  } else {
    loadSensorData()
    refreshTimer = setInterval(loadSensorData, 2000)
    isAutoRefreshing.value = true
  }
}

const startAutoRefresh = () => {
  if (isAutoRefreshing.value) return
  loadSensorData()
  refreshTimer = setInterval(loadSensorData, 2000)
  isAutoRefreshing.value = true
}

const handleResize = () => {
  heartChart?.resize()
  breathChart?.resize()
  snoreChart?.resize()
}

onMounted(() => {
  heartChart = echarts.init(document.getElementById('heart-chart'))
  breathChart = echarts.init(document.getElementById('breath-chart'))
  snoreChart = echarts.init(document.getElementById('snore-chart'))
  heartChart.setOption(optionHeart.value)
  breathChart.setOption(optionBreath.value)
  snoreChart.setOption(optionSnore.value)
  startAutoRefresh()
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  if (refreshTimer) clearInterval(refreshTimer)
  window.removeEventListener('resize', handleResize)
})
</script>

<style scoped>
.dashboard-container { padding: 0; }
.control-panel { margin-bottom: 20px; display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.device-status { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 13px; color: #666; }
.status-pill { padding: 5px 10px; border-radius: 999px; background: #f5f5f5; color: #777; border: 1px solid #e8e8e8; }
.status-pill.online { background: #e6f7ed; color: #237804; border-color: #b7eb8f; }
.status-pill.warning { background: #fff7e6; color: #ad6800; border-color: #ffd591; }
.device-panel { display: grid; grid-template-columns: repeat(2, minmax(260px, 1fr)); gap: 14px; margin-bottom: 18px; }
.device-card { border: 1px solid #efefef; background: #fafafa; border-radius: 12px; padding: 14px 16px; box-shadow: 0 2px 10px rgba(0,0,0,0.03); }
.device-card.online { background: linear-gradient(135deg, #f6ffed, #ffffff); border-color: #b7eb8f; }
.device-card.warning { background: linear-gradient(135deg, #fff7e6, #ffffff); border-color: #ffd591; }
.device-title { font-size: 14px; color: #666; margin-bottom: 8px; }
.device-value { font-size: 20px; font-weight: 700; color: #1f1f1f; margin-bottom: 6px; }
.device-meta { font-size: 12px; color: #8c8c8c; line-height: 1.8; }
.device-hint { margin-top: 8px; font-family: Consolas, 'Courier New', monospace; font-size: 12px; color: #cf1322; background: #fff1f0; border-radius: 6px; padding: 6px 8px; }
.snore-wave-card { display: grid; grid-template-columns: 220px 1fr 280px; align-items: center; gap: 18px; background: radial-gradient(circle at 10% 20%, #fff7e6, #ffffff 45%); border: 1px solid #ffd591; border-radius: 16px; padding: 16px 18px; margin-bottom: 18px; box-shadow: 0 4px 20px rgba(250, 140, 22, 0.12); }
.snore-wave-card.active { border-color: #ffc069; }
.snore-wave-card.warning { box-shadow: 0 0 0 1px #fa8c16, 0 8px 28px rgba(250, 140, 22, 0.25); }
.snore-wave-value { font-size: 34px; font-weight: 800; color: #fa8c16; line-height: 1; margin-bottom: 8px; }
.sound-bars { height: 96px; display: flex; align-items: center; justify-content: center; gap: 5px; padding: 0 10px; border-radius: 14px; background: linear-gradient(180deg, rgba(255,247,230,0.88), rgba(255,255,255,0.9)); overflow: hidden; }
.sound-bar { width: 9px; min-height: 8px; border-radius: 999px; background: linear-gradient(180deg, #ff4d4f, #fa8c16, #ffd666); transition: height 0.35s ease, opacity 0.35s ease; box-shadow: 0 0 12px rgba(250, 140, 22, 0.35); }
.sound-bar.hot { background: linear-gradient(180deg, #ff1f1f, #fa541c, #ffc53d); box-shadow: 0 0 18px rgba(250, 84, 28, 0.6); }
.snore-wave-readout { display: flex; flex-direction: column; gap: 8px; color: #8c4a00; font-size: 13px; }
.insight-grid { display: grid; grid-template-columns: repeat(3, minmax(220px, 1fr)); gap: 14px; margin-bottom: 18px; }
.insight-card { background: #fff; border-radius: 12px; border: 1px solid #edf0f2; padding: 14px 16px; box-shadow: 0 2px 12px rgba(0,0,0,0.04); min-height: 118px; }
.insight-title { color: #8c8c8c; font-size: 13px; margin-bottom: 8px; }
.insight-value { font-size: 22px; color: #1f1f1f; font-weight: 700; margin-bottom: 8px; }
.insight-text { color: #595959; font-size: 13px; line-height: 1.7; }
.charts-layout { display: grid; grid-template-columns: repeat(2, minmax(360px, 1fr)); gap: 20px; }
.module-card { background: #fff; border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,0.05); padding: 20px; display: flex; flex-direction: column; min-width: 0; }
.snore-chart-card { grid-column: 1 / -1; }
.chart-header { font-size: 18px; font-weight: bold; margin-bottom: 15px; display: flex; align-items: center; gap: 8px; }
.chart-subtitle { font-size: 12px; color: #8c8c8c; font-weight: 400; }
.dot { width: 8px; height: 8px; border-radius: 50%; }
.dot.red { background: #ff5757; }
.dot.blue { background: #1890ff; }
.dot.orange { background: #fa8c16; }
.chart-box { width: 100%; height: 250px; margin-bottom: 20px; }
.chart-box.compact { height: 220px; margin-bottom: 8px; }
.monitor-box { height: 220px; }
.snore-note { color: #8c8c8c; font-size: 13px; line-height: 1.7; }
@media (max-width: 1200px) {
  .snore-wave-card { grid-template-columns: 1fr; }
  .charts-layout { grid-template-columns: 1fr; }
}
@media (max-width: 1100px) {
  .insight-grid { grid-template-columns: 1fr; }
}
@media (max-width: 900px) {
  .device-panel { grid-template-columns: 1fr; }
}
</style>
