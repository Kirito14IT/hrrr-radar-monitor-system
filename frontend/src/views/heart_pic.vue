<template>
  <div class="dashboard-container care-page-shell">
    <div class="control-panel">
      <el-button
        :type="isAutoRefreshing ? 'danger' : 'primary'"
        size="large"
        @click="toggleAutoRefresh"
      >
        {{ isAutoRefreshing ? '停止监测' : '开始实时监测' }}
      </el-button>
    </div>

    <div class="snore-wave-card care-glass-card care-icon-card" data-icon="SN" :class="{ active: statusState.snore_board_online, warning: statusState.snore_detected }">
      <div class="snore-wave-info">
        <div class="device-title">呼噜声浪监测</div>
        <div class="snore-wave-value">{{ snoreIntensity.toFixed(0) }} / 100</div>
      </div>
      <div class="snore-live-panel">
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
          <span>{{ formatDbfs(statusState.snore_dbfs) }}</span>
          <span>分数 {{ statusState.snore_score.toFixed(2) }}</span>
          <span>{{ statusState.snore_detected ? '检测到呼噜' : '未检测到明显呼噜' }}</span>
        </div>
      </div>
      <div class="snore-trend-panel">
        <div class="snore-trend-title">
          <span class="dot orange"></span> 呼噜强度趋势
        </div>
        <div id="snore-chart" class="snore-inline-chart"></div>
      </div>
    </div>

    <div class="charts-layout">
      <div class="module-card care-glass-card care-icon-card" data-icon="HR">
        <div class="chart-header">
          <span class="dot red"></span> 心率趋势
        </div>
        <div id="heart-chart" class="chart-box"></div>
        <div class="monitor-box">
          <HeartRateMonitor :rate="currentHeartRate" :is-present="isUserPresent" :vitals-state="statusState.vitals_state" />
        </div>
      </div>

      <div class="module-card care-glass-card care-icon-card" data-icon="BR">
        <div class="chart-header">
          <span class="dot blue"></span> 呼吸趋势
        </div>
        <div id="breath-chart" class="chart-box"></div>
        <div class="monitor-box">
          <BreathRateMonitor :rate="currentBreathRate" :is-present="isUserPresent" :vitals-state="statusState.vitals_state" />
        </div>
      </div>

    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, watch } from 'vue'
import * as echarts from 'echarts'
import HeartRateMonitor from './HeartRateMonitor.vue'
import BreathRateMonitor from './BreathRateMonitor.vue'
import { useUserStore } from '@/stores/userStore'
import { useThemeStore } from '@/stores/themeStore'
import { useBedStore } from '@/stores/bedStore'
import request from '@/utils/request'

const userStore = useUserStore()
const themeStore = useThemeStore()
const bedStore = useBedStore()
const isAutoRefreshing = ref(false)
const currentHeartRate = ref(null)
const currentBreathRate = ref(null)
const isUserPresent = ref(false)
const soundTick = ref(0)

const statusState = reactive({
  radar_board_online: false,
  snore_board_online: false,
  snore_monitoring: false,
  snore_paused: false,
  audio_upload_count: 0,
  snore_detected: false,
  snore_score: 0,
  snore_dbfs: null,
  snore_level: null,
  last_audio_received_at: null,
  last_radar_frame_number: 0,
  radar_age_seconds: null,
  radar_status_age_seconds: null,
  radar_board_stationary: true,
  radar_motion_reason: 'disabled',
  radar_motion_delta: null,
  radar_motion_sensor_ready: null,
  snore_age_seconds: null,
  environment_board_online: false,
  voice_board_online: false,
  edgi_board_online: false,
  emergency_active: false,
  active_emergency: null,
  environment_age_seconds: null,
  temperature_c: null,
  humidity_pct: null,
  comfort_status: 'offline',
  last_environment_heartbeat_at: null,
  target_distance: null,
  target_bin: null,
  heart_rate_fresh: false,
  breath_rate_fresh: false,
  vitals_state: 'lost',
  vitals_age_seconds: null,
  last_valid_vitals_at: null
})

let refreshTimer = null
let heartChart = null
let breathChart = null
let snoreChart = null

const isNumber = (value) => typeof value === 'number' && Number.isFinite(value)

const clamp = (value, min, max) => Math.max(min, Math.min(max, value))

const snoreIntensityValue = (row) => {
  const online = row?.snore_online ?? row?.snore_board_online
  if (!online) return null

  const energy = isNumber(row.snore_level) ? clamp(Number(row.snore_level), 0, 1) : 0
  const confidence = isNumber(row.snore_score) ? clamp(Number(row.snore_score), 0, 1) : 0
  return Math.round(energy * confidence * 100)
}

const snoreIntensity = computed(() => snoreIntensityValue(statusState) ?? 0)

const snoreBars = computed(() => {
  const base = snoreIntensity.value / 100
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

const readToken = (name, fallback) => {
  if (typeof window === 'undefined') return fallback
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

const chartColors = {
  heart: 'rgb(253, 164, 175)',
  breath: 'rgb(147, 197, 253)',
  snore: 'rgb(253, 186, 116)'
}

const buildOption = (color, unit, yMax = null) => ({
  grid: { top: 35, right: 24, bottom: 42, left: 45 },
  tooltip: {
    trigger: 'axis',
    backgroundColor: readToken('--care-surface-strong', '#fff'),
    borderColor: readToken('--care-border', '#d9d9d9'),
    textStyle: { color: readToken('--care-text', '#333') },
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
    axisLabel: { color: readToken('--care-muted', '#8c8c8c'), fontSize: 13 },
    axisLine: { lineStyle: { color: readToken('--care-border-soft', '#d9d9d9') } }
  },
  yAxis: {
    type: 'value',
    scale: yMax === null,
    max: yMax,
    min: yMax === null ? null : 0,
    splitLine: { lineStyle: { color: readToken('--care-grid-line-soft', '#eee'), type: 'dashed' } },
    axisLabel: { color: readToken('--care-muted', '#8c8c8c'), fontSize: 13 }
  },
  series: [{
    type: 'line',
    smooth: true,
    symbol: 'none',
    connectNulls: true,
    lineStyle: { width: 2.5, color },
    areaStyle: {
      color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
        { offset: 0, color: color.replace(')', ', 0.16)').replace('rgb', 'rgba') },
        { offset: 1, color: color.replace(')', ', 0.0)').replace('rgb', 'rgba') }
      ])
    },
    data: []
  }]
})

const optionHeart = ref(buildOption(chartColors.heart, 'BPM', 180))
const optionBreath = ref(buildOption(chartColors.breath, 'RPM', 40))
const optionSnore = ref(buildOption(chartColors.snore, '分', 100))

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

const applyThemeToCharts = () => {
  optionHeart.value = buildOption(chartColors.heart, 'BPM', 180)
  optionBreath.value = buildOption(chartColors.breath, 'RPM', 40)
  optionSnore.value = buildOption(chartColors.snore, '分', 100)
  if (heartChart) heartChart.setOption(optionHeart.value, true)
  if (breathChart) breathChart.setOption(optionBreath.value, true)
  if (snoreChart) snoreChart.setOption(optionSnore.value, true)
}

const setCharts = (rows) => {
  const labels = rows.map(row => formatTimeLabel(row.timestamp))
  optionHeart.value.xAxis.data = labels
  optionBreath.value.xAxis.data = labels
  optionSnore.value.xAxis.data = labels
  optionHeart.value.series[0].data = rows.map(row => isNumber(row.heart_rate) ? row.heart_rate : null)
  optionBreath.value.series[0].data = rows.map(row => isNumber(row.breath_rate) ? row.breath_rate : null)
  optionSnore.value.series[0].data = rows.map(row => snoreIntensityValue(row))
  heartChart?.setOption(optionHeart.value, true)
  breathChart?.setOption(optionBreath.value, true)
  snoreChart?.setOption(optionSnore.value, true)
}

const updateInsights = (rows) => {
  if (!rows.length) {
    currentHeartRate.value = null
    currentBreathRate.value = null
    isUserPresent.value = false
    return
  }

  const latest = rows[rows.length - 1]
  const radarOnline = !!latest.radar_online
  const vitalsState = latest.vitals_state || (radarOnline ? 'recovering' : 'lost')
  const radarValid = radarOnline && vitalsState !== 'lost' && isNumber(latest.heart_rate) && isNumber(latest.breath_rate)
  currentHeartRate.value = radarValid ? latest.heart_rate : null
  currentBreathRate.value = radarValid ? latest.breath_rate : null
  statusState.heart_rate_fresh = !!latest.heart_rate_fresh
  statusState.breath_rate_fresh = !!latest.breath_rate_fresh
  statusState.vitals_state = vitalsState
  statusState.vitals_age_seconds = latest.vitals_age_seconds ?? null
  statusState.last_valid_vitals_at = latest.last_valid_vitals_at || null
  statusState.target_distance = isNumber(latest.target_distance) ? Number(latest.target_distance) : statusState.target_distance
  statusState.target_bin = latest.target_bin ?? statusState.target_bin
  statusState.environment_board_online = !!latest.environment_online
  statusState.temperature_c = isNumber(latest.temperature_c) ? Number(latest.temperature_c) : statusState.temperature_c
  statusState.humidity_pct = isNumber(latest.humidity_pct) ? Number(latest.humidity_pct) : statusState.humidity_pct
  statusState.comfort_status = latest.comfort_status || statusState.comfort_status
  isUserPresent.value = radarOnline
}

const loadStatus = async () => {
  try {
    const res = await request.get('/status', { params: { bed_id: bedStore.selectedBedId } })
    statusState.radar_board_online = !!res.radar_board_online
    statusState.snore_board_online = !!res.snore_board_online
    statusState.snore_monitoring = !!res.snore_monitoring
    statusState.snore_paused = !!res.snore_paused
    statusState.audio_upload_count = res.audio_upload_count || 0
    statusState.snore_detected = !!res.snore_detected
    statusState.snore_score = Number(res.snore_score || 0)
    statusState.snore_dbfs = isNumber(res.snore_dbfs) ? Number(res.snore_dbfs) : null
    statusState.snore_level = isNumber(res.snore_level) ? Number(res.snore_level) : null
    statusState.last_audio_received_at = res.last_audio_received_at || null
    statusState.last_radar_frame_number = res.last_radar_frame_number || 0
    statusState.radar_age_seconds = res.radar_age_seconds
    statusState.radar_status_age_seconds = res.radar_status_age_seconds
    statusState.radar_board_stationary = res.radar_board_stationary !== false
    statusState.radar_motion_reason = res.radar_motion_reason || 'disabled'
    statusState.radar_motion_delta = isNumber(res.radar_motion_delta) ? Number(res.radar_motion_delta) : null
    statusState.radar_motion_sensor_ready = res.radar_motion_sensor_ready
    statusState.snore_age_seconds = res.snore_age_seconds
    statusState.environment_board_online = !!res.environment_board_online
    statusState.voice_board_online = !!res.voice_board_online
    statusState.edgi_board_online = !!res.edgi_board_online
    statusState.emergency_active = !!res.emergency_active
    statusState.active_emergency = res.active_emergency || null
    statusState.environment_age_seconds = res.environment_age_seconds
    statusState.temperature_c = isNumber(res.temperature_c) ? Number(res.temperature_c) : null
    statusState.humidity_pct = isNumber(res.humidity_pct) ? Number(res.humidity_pct) : null
    statusState.comfort_status = res.comfort_status || 'offline'
    statusState.last_environment_heartbeat_at = res.last_environment_heartbeat_at || null
    statusState.target_distance = isNumber(res.target_distance) ? Number(res.target_distance) : statusState.target_distance
    statusState.target_bin = res.target_bin ?? statusState.target_bin
    statusState.heart_rate_fresh = !!res.heart_rate_fresh
    statusState.breath_rate_fresh = !!res.breath_rate_fresh
    statusState.vitals_state = res.vitals_state || (statusState.radar_board_online ? 'recovering' : 'lost')
    statusState.vitals_age_seconds = res.vitals_age_seconds ?? null
    statusState.last_valid_vitals_at = res.last_valid_vitals_at || null
  } catch (error) {
    console.warn('获取模拟设备状态失败:', error)
    statusState.radar_board_online = false
    statusState.snore_board_online = false
    statusState.vitals_state = 'lost'
  }
}

const loadSensorData = async () => {
  try {
    const res = await request.get('/timeline', { params: { seconds: 180, bed_id: bedStore.selectedBedId } })
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
      const latestSnoreScore = isNumber(latest.snore_score) ? Number(latest.snore_score) : null
      const latestSnoreDetected = !!latest.snore_detected && (latestSnoreScore === null || latestSnoreScore >= 0.4)
      await request.post('/save-vitals-with-user', {
        userID: userStore.userInfo.userID,
        bed_id: bedStore.selectedBedId,
        heart_rate: latest.heart_rate,
        breath_rate: latest.breath_rate,
        target_distance: latest.target_distance || 0,
        timestamp: latest.timestamp,
        snore_detected: latestSnoreDetected,
        snore_score: latestSnoreScore,
        snore_level: isNumber(latest.snore_level) ? Number(latest.snore_level) : null
      }).catch(err => console.warn('保存用户生命体征失败:', err))
    }
  } catch (error) {
    console.error('获取时间轴数据失败:', error)
    isUserPresent.value = false
    currentHeartRate.value = null
    currentBreathRate.value = null
    statusState.vitals_state = 'lost'
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
  heartChart?.dispose()
  breathChart?.dispose()
  snoreChart?.dispose()
})

// 主题切换时重新应用 ECharts 主题色
watch(() => themeStore.mode, () => {
  applyThemeToCharts()
})
</script>

<style scoped>
.dashboard-container { padding: 0; color: var(--care-text); }
.control-panel { margin-bottom: 20px; display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.device-title { font-size: 14px; color: var(--care-muted); margin-bottom: 8px; }
.snore-wave-card {
  display: grid;
  grid-template-columns: 170px minmax(300px, 0.9fr) minmax(380px, 1.2fr);
  align-items: center;
  gap: 18px;
  background: radial-gradient(circle at 10% 20%, var(--care-warning-soft), var(--care-surface-strong) 45%);
  border: 1px solid var(--care-warning);
  border-radius: var(--care-radius-lg);
  padding: 16px 18px;
  margin-bottom: 18px;
  box-shadow: var(--care-shadow-soft);
  color: var(--care-text);
  transition: background 0.3s ease, color 0.3s ease, border-color 0.3s ease, box-shadow 0.3s ease;
}
.snore-wave-card.active { border-color: var(--care-warning); }
.snore-wave-card.warning { box-shadow: 0 0 0 1px var(--care-warning), 0 8px 28px var(--care-warning-soft); }
.snore-wave-value { font-size: 34px; font-weight: 800; color: var(--care-warning); line-height: 1; margin-bottom: 8px; }
.snore-live-panel {
  min-width: 0;
  display: grid;
  gap: 10px;
}
.sound-bars {
  height: 96px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 0 10px;
  border-radius: 14px;
  background: linear-gradient(180deg, var(--care-warning-soft), var(--care-surface-strong));
  overflow: hidden;
}
.sound-bar {
  width: 9px;
  min-height: 8px;
  border-radius: 999px;
  background: linear-gradient(180deg, var(--care-danger), var(--care-warning), #ffd666);
  transition: height 0.35s ease, opacity 0.35s ease;
  box-shadow: 0 0 12px var(--care-warning-soft);
}
.sound-bar.hot { background: linear-gradient(180deg, #ff1f1f, var(--care-warning), #ffc53d); box-shadow: 0 0 18px rgba(250, 84, 28, 0.6); }
.snore-wave-readout { display: flex; justify-content: space-between; gap: 12px; color: var(--care-muted-strong); font-size: 15px; }
.snore-trend-panel {
  min-width: 0;
  padding-left: 18px;
  border-left: 1px solid var(--care-border-soft);
}
.snore-trend-title {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--care-text-strong);
  font-size: 16px;
  font-weight: 700;
}
.snore-inline-chart {
  width: 100%;
  height: 170px;
}
.charts-layout { display: grid; grid-template-columns: repeat(2, minmax(360px, 1fr)); gap: 20px; }
.module-card {
  background: var(--care-surface-strong);
  color: var(--care-text);
  border-radius: var(--care-radius-md);
  border: 1px solid var(--care-border-soft);
  box-shadow: var(--care-shadow-soft);
  padding: 20px;
  display: flex;
  flex-direction: column;
  min-width: 0;
  transition: background 0.3s ease, color 0.3s ease, border-color 0.3s ease, box-shadow 0.3s ease;
}
.chart-header { font-size: 18px; font-weight: bold; margin-bottom: 15px; display: flex; align-items: center; gap: 8px; color: var(--care-text-strong); }
.chart-subtitle { font-size: 12px; color: var(--care-muted); font-weight: 400; }
.dot { width: 8px; height: 8px; border-radius: 50%; }
.dot.red { background: #fda4af; }
.dot.blue { background: #93c5fd; }
.dot.orange { background: #fdba74; }
.dot.green { background: var(--care-success); }
.chart-box { width: 100%; height: 250px; margin-bottom: 20px; }
.monitor-box { height: 220px; }
.snore-note { color: var(--care-muted); font-size: 13px; line-height: 1.7; }
@media (max-width: 1200px) {
  .snore-wave-card { grid-template-columns: 150px 1fr; }
  .snore-trend-panel {
    grid-column: 1 / -1;
    padding-left: 0;
    padding-top: 14px;
    border-left: 0;
    border-top: 1px solid var(--care-border-soft);
  }
  .charts-layout { grid-template-columns: 1fr; }
}
@media (max-width: 900px) {
  .snore-wave-card { grid-template-columns: 1fr; }
  .snore-trend-panel { grid-column: auto; }
  .snore-wave-readout { flex-wrap: wrap; }
}
</style>
