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
      <div class="device-status">
        <span class="status-pill" :class="{ online: statusState.radar_board_online }">
          雷达开发板：{{ statusState.radar_board_online ? '在线' : '离线' }}
        </span>
        <span class="status-pill" :class="{ online: edgiBoardOnline, warning: edgiBoardNeedsAttention }">
          Edgi E84：{{ edgiBoardStatusText }}
        </span>
        <span class="status-pill" :class="{ warning: statusState.snore_detected }">
          呼噜：{{ statusState.snore_detected ? '检测到' : '正常' }}
        </span>
        <span v-if="statusState.emergency_active" class="status-pill emergency">
          紧急求助
        </span>
      </div>
    </div>

    <div class="device-panel">
      <div class="device-card care-glass-card" :class="{ online: statusState.radar_board_online }">
        <div class="device-title">毫米波雷达开发板</div>
        <div class="device-value">{{ radarDeviceValue }}</div>
        <div v-if="statusState.radar_board_online" class="device-meta">
          {{ radarDistanceText }}
        </div>
        <div class="device-meta">
          帧 {{ statusState.last_radar_frame_number || 0 }} · {{ formatAge(statusState.radar_age_seconds) }}
        </div>
      </div>

      <div class="device-card care-glass-card" :class="{ online: statusState.snore_board_online, warning: statusState.snore_detected }">
        <div class="device-title">Edgi E84 呼噜检测开发板</div>
        <div class="device-value">
          {{ snoreMonitorText }}
        </div>
        <div class="device-meta">
          {{ formatDbfs(statusState.snore_dbfs) }} · {{ formatAge(statusState.snore_age_seconds) }}
        </div>
      </div>
    </div>

    <div class="snore-wave-card care-glass-card" :class="{ active: statusState.snore_board_online, warning: statusState.snore_detected }">
      <div class="snore-wave-info">
        <div class="device-title">呼噜声浪监测</div>
        <div class="snore-wave-value">{{ snorePercent.toFixed(0) }}%</div>
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

    <div class="insight-grid">
      <div class="insight-card care-glass-card">
        <div class="insight-title">睡眠分期</div>
        <div class="insight-value">{{ insight.sleepStage }}</div>
        <div class="insight-text">{{ insight.sleepReason }}</div>
      </div>
      <div class="insight-card care-glass-card">
        <div class="insight-title">呼噜-生命体征关联</div>
        <div class="insight-value">{{ insight.snoreLabel }}</div>
        <div class="insight-text">{{ insight.snoreImpact }}</div>
      </div>
      <div class="insight-card care-glass-card">
        <div class="insight-title">实时健康摘要</div>
        <div class="insight-value">{{ insight.latestTime || '等待数据' }}</div>
        <div class="insight-text">{{ insight.summary }}</div>
      </div>
    </div>

    <div class="charts-layout">
      <div class="module-card care-glass-card">
        <div class="chart-header">
          <span class="dot red"></span> 心率趋势
        </div>
        <div id="heart-chart" class="chart-box"></div>
        <div class="monitor-box">
          <HeartRateMonitor :rate="currentHeartRate" :is-present="isUserPresent" />
        </div>
      </div>

      <div class="module-card care-glass-card">
        <div class="chart-header">
          <span class="dot blue"></span> 呼吸趋势
        </div>
        <div id="breath-chart" class="chart-box"></div>
        <div class="monitor-box">
          <BreathRateMonitor :rate="currentBreathRate" :is-present="isUserPresent" />
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
import request from '@/utils/request'

const userStore = useUserStore()
const themeStore = useThemeStore()
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
  target_bin: null
})

const insight = reactive({
  sleepStage: '等待数据',
  sleepReason: '启动真实开发板后，这里会根据心率、呼吸率和呼噜分数估计状态。',
  snoreLabel: '暂无事件',
  snoreImpact: '最近 3 分钟未检测到呼噜事件。',
  summary: '等待雷达开发板和 Edgi E84 开发板上线。',
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

const hasRadarVitals = computed(() => isNumber(currentHeartRate.value) && isNumber(currentBreathRate.value))

const radarDeviceValue = computed(() => {
  if (!statusState.radar_board_online) return '未连接'
  if (!hasRadarVitals.value) return '等待生命体征计算'
  return '正在连续发送'
})

const radarDistanceText = computed(() => {
  const distance = statusState.target_distance
  if (!isNumber(distance) || distance <= 0) return '目标距离：等待处理'
  const bin = statusState.target_bin === null || statusState.target_bin === undefined ? '--' : statusState.target_bin
  return `目标距离：${Number(distance).toFixed(2)} 米 · bin ${bin}`
})

const edgiBoardOnline = computed(() => (
  statusState.edgi_board_online ||
  statusState.environment_board_online ||
  statusState.snore_board_online ||
  statusState.voice_board_online
))

const edgiBoardNeedsAttention = computed(() => {
  return Boolean(edgiBoardOnline.value && (
    statusState.snore_detected ||
    statusState.emergency_active
  ))
})

const edgiBoardStatusText = computed(() => {
  if (!edgiBoardOnline.value) return '离线'
  if (statusState.emergency_active) return '紧急状态'
  if (statusState.snore_monitoring || statusState.snore_board_online) return '在线 · 呼噜监测中'
  return statusState.snore_paused ? '在线 · 呼噜已暂停' : '在线'
})

const snoreMonitorText = computed(() => {
  if (statusState.snore_monitoring || statusState.snore_board_online) {
    return `呼噜分数 ${statusState.snore_score.toFixed(2)}`
  }
  return edgiBoardOnline.value ? '监测已暂停' : '等待开发板'
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

const readToken = (name, fallback) => {
  if (typeof window === 'undefined') return fallback
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
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

const optionHeart = ref(buildOption('rgb(255, 87, 87)', 'BPM'))
const optionBreath = ref(buildOption('rgb(24, 144, 255)', 'RPM'))
const optionSnore = ref(buildOption('rgb(250, 140, 22)', '%', 100))

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

const applyThemeToCharts = () => {
  const tokens = {
    heart: 'rgb(255, 87, 87)',
    breath: 'rgb(24, 144, 255)',
    snore: 'rgb(250, 140, 22)'
  }
  optionHeart.value = buildOption(tokens.heart, 'BPM')
  optionBreath.value = buildOption(tokens.breath, 'RPM')
  optionSnore.value = buildOption(tokens.snore, '%', 100)
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
  const radarOnline = !!latest.radar_online
  const radarValid = radarOnline && isNumber(latest.heart_rate) && isNumber(latest.breath_rate)
  currentHeartRate.value = radarValid ? latest.heart_rate : null
  currentBreathRate.value = radarValid ? latest.breath_rate : null
  statusState.target_distance = isNumber(latest.target_distance) ? Number(latest.target_distance) : statusState.target_distance
  statusState.target_bin = latest.target_bin ?? statusState.target_bin
  statusState.environment_board_online = !!latest.environment_online
  statusState.temperature_c = isNumber(latest.temperature_c) ? Number(latest.temperature_c) : statusState.temperature_c
  statusState.humidity_pct = isNumber(latest.humidity_pct) ? Number(latest.humidity_pct) : statusState.humidity_pct
  statusState.comfort_status = latest.comfort_status || statusState.comfort_status
  isUserPresent.value = radarOnline
  insight.latestTime = formatTimeLabel(latest.timestamp)
  insight.sleepStage = latest.sleep_stage || '等待数据'

  if (!latest.radar_online) {
    insight.sleepReason = '雷达开发板离线或无人，心率/呼吸图表会断线，不再用 0 伪装成真实数据。'
    insight.summary = latest.snore_online
      ? '雷达开发板未连接；Edgi E84 仍在线，所以声浪和呼噜强度趋势仍可继续显示。'
      : '雷达开发板和 Edgi E84 都未连接。'
  } else if (!radarValid) {
    const distanceText = isNumber(latest.target_distance) && latest.target_distance > 0
      ? `，目标距离 ${Number(latest.target_distance).toFixed(2)} 米`
      : ''
    insight.sleepReason = `雷达开发板在线${distanceText}，正在等待存在检测、信号分解或模型推理给出心率/呼吸率。`
    insight.summary = '已收到雷达时间轴数据；生命体征暂为空时不再伪装成离线或 0 值。'
  } else if (latest.snore_detected) {
    insight.sleepReason = '当前检测到呼噜扰动，分期暂时标记为疑似呼噜扰动。'
    insight.summary = `当前心率 ${latest.heart_rate} BPM，呼吸 ${latest.breath_rate} RPM，伴随呼噜事件。`
  } else {
    insight.sleepReason = `基于当前心率 ${latest.heart_rate} BPM、呼吸 ${latest.breath_rate} RPM、呼噜分数 ${Number(latest.snore_score || 0).toFixed(2)} 估计。`
    insight.summary = '心率、呼吸率和呼噜强度共用同一批秒级时间戳；温湿度请在睡眠环境分析页面查看。'
  }

  let lastSnoreIndex = -1
  rows.forEach((row, index) => {
    if (row.snore_detected) lastSnoreIndex = index
  })
  if (lastSnoreIndex < 0) {
    insight.snoreLabel = '暂无事件'
    insight.snoreImpact = latest.snore_online
      ? 'Edgi E84 在线，但最近时间窗内没有明显呼噜事件。'
      : 'Edgi E84 呼噜心跳离线；雷达呼吸率仍可继续运行。'
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
.device-status { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 13px; color: var(--care-muted); }
.status-pill {
  padding: 5px 10px;
  border-radius: 999px;
  background: var(--care-surface-strong);
  color: var(--care-muted-strong);
  border: 1px solid var(--care-border-soft);
  transition: background 0.2s ease, color 0.2s ease, border-color 0.2s ease;
}
.status-pill.online { background: var(--care-success-soft); color: var(--care-success); border-color: var(--care-success); }
.status-pill.warning { background: var(--care-warning-soft); color: var(--care-warning); border-color: var(--care-warning); }
.status-pill.emergency { background: var(--care-danger); color: #fff; border-color: var(--care-danger); }
.device-panel { display: grid; grid-template-columns: minmax(280px, 0.95fr) minmax(360px, 1.35fr); gap: 14px; margin-bottom: 18px; }
.device-card {
  border: 1px solid var(--care-border-soft);
  background: var(--care-surface-strong);
  color: var(--care-text);
  border-radius: var(--care-radius-md);
  padding: 14px 16px;
  box-shadow: var(--care-shadow-soft);
  transition: background 0.3s ease, color 0.3s ease, border-color 0.3s ease, box-shadow 0.3s ease;
}
.device-card.online { background: linear-gradient(135deg, var(--care-success-soft), var(--care-surface-strong)); border-color: var(--care-success); }
.device-card.warning { background: linear-gradient(135deg, var(--care-warning-soft), var(--care-surface-strong)); border-color: var(--care-warning); }
.device-title { font-size: 14px; color: var(--care-muted); margin-bottom: 8px; }
.device-value { font-size: 20px; font-weight: 700; color: var(--care-text-strong); margin-bottom: 6px; }
.device-meta { font-size: 12px; color: var(--care-muted); line-height: 1.8; }
.device-hint {
  margin-top: 8px;
  font-family: Consolas, 'Courier New', monospace;
  font-size: 12px;
  color: var(--care-danger);
  background: var(--care-danger-soft);
  border-radius: 6px;
  padding: 6px 8px;
}
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
.insight-grid { display: grid; grid-template-columns: repeat(3, minmax(220px, 1fr)); gap: 14px; margin-bottom: 18px; }
.insight-card {
  background: var(--care-surface-strong);
  color: var(--care-text);
  border-radius: var(--care-radius-md);
  border: 1px solid var(--care-border-soft);
  padding: 14px 16px;
  box-shadow: var(--care-shadow-soft);
  min-height: 118px;
  transition: background 0.3s ease, color 0.3s ease, border-color 0.3s ease;
}
.insight-title { color: var(--care-muted); font-size: 13px; margin-bottom: 8px; }
.insight-value { font-size: 22px; color: var(--care-text-strong); font-weight: 700; margin-bottom: 8px; }
.insight-text { color: var(--care-muted-strong); font-size: 13px; line-height: 1.7; }
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
.dot.red { background: #ff5757; }
.dot.blue { background: #1890ff; }
.dot.orange { background: var(--care-warning); }
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
@media (max-width: 1100px) {
  .insight-grid { grid-template-columns: 1fr; }
}
@media (max-width: 900px) {
  .device-panel { grid-template-columns: 1fr; }
  .snore-wave-card { grid-template-columns: 1fr; }
  .snore-trend-panel { grid-column: auto; }
  .snore-wave-readout { flex-wrap: wrap; }
}
</style>
