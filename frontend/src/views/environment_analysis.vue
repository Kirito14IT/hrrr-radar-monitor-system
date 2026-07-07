<template>
  <div class="environment-page care-page-shell">
    <section class="environment-header">
      <div>
        <h1>睡眠环境分析</h1>
      </div>
      <div class="header-actions">
        <span class="updated-at">{{ updatedText }}</span>
        <el-button type="primary" :icon="Refresh" :loading="loading" @click="loadEnvironment">
          刷新
        </el-button>
      </div>
    </section>

    <section v-if="status.emergency_active" class="emergency-strip">
      <strong>紧急求助已触发</strong>
      <span>{{ status.active_emergency?.message || '请立即确认床旁情况' }}</span>
    </section>

    <section class="score-band care-icon-card" :class="scoreLevel" data-icon="ENV">
      <div class="score-gauge" :style="scoreGaugeStyle">
        <div>
          <strong>{{ environmentScore ?? '--' }}</strong>
          <span>/100</span>
        </div>
      </div>
      <div class="score-copy">
        <span>当前睡眠环境评分</span>
        <h2>{{ scoreLabel }}</h2>
      </div>
      <div class="score-factors">
        <div v-for="factor in scoreFactors" :key="factor.key" class="score-factor" :class="factor.key">
          <span class="factor-icon" aria-hidden="true">
            <svg v-if="factor.key === 'temperature'" viewBox="0 0 24 24">
              <path d="M14 14.76V5a2 2 0 0 0-4 0v9.76a4 4 0 1 0 4 0Z" />
              <path d="M12 8v8" />
            </svg>
            <svg v-else-if="factor.key === 'humidity'" viewBox="0 0 24 24">
              <path d="M12 3.5s6 6.12 6 10.25A6 6 0 0 1 6 13.75C6 9.62 12 3.5 12 3.5Z" />
              <path d="M9.5 15.2c.72 1.14 1.62 1.7 2.7 1.7" />
            </svg>
            <svg v-else viewBox="0 0 24 24">
              <path d="M12 20V9" />
              <path d="M12 13c-4.2 0-6.8-2.4-7.5-7.2 4.8.5 7.5 2.8 7.5 7.2Z" />
              <path d="M12 14c4.2 0 6.8-2.4 7.5-7.2-4.8.5-7.5 2.8-7.5 7.2Z" />
            </svg>
          </span>
          <div>
            <span>{{ factor.label }}</span>
            <strong>{{ factor.value === null ? '--' : factor.value }}</strong>
          </div>
        </div>
      </div>
    </section>

    <section class="metric-grid">
      <article class="metric-card temperature">
        <div class="metric-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24">
            <path d="M14 14.76V5a2 2 0 0 0-4 0v9.76a4 4 0 1 0 4 0Z" />
            <path d="M12 8v8" />
          </svg>
          <span>°C</span>
        </div>
        <div class="metric-heading">
          <span>室内温度</span>
          <strong>{{ formatNumber(status.temperature_c, '°C') }}</strong>
        </div>
        <div class="metric-scale">
          <i :style="{ width: temperaturePosition }"></i>
        </div>
        <p>{{ temperatureAssessment }}</p>
      </article>

      <article class="metric-card humidity">
        <div class="metric-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24">
            <path d="M12 3.5s6 6.12 6 10.25A6 6 0 0 1 6 13.75C6 9.62 12 3.5 12 3.5Z" />
            <path d="M9.5 15.2c.72 1.14 1.62 1.7 2.7 1.7" />
          </svg>
          <span>%RH</span>
        </div>
        <div class="metric-heading">
          <span>相对湿度</span>
          <strong>{{ formatNumber(status.humidity_pct, '%') }}</strong>
        </div>
        <div class="metric-scale">
          <i :style="{ width: humidityPosition }"></i>
        </div>
        <p>{{ humidityAssessment }}</p>
      </article>

      <article class="metric-card sound">
        <div class="metric-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24">
            <path d="M4 13h3l4 5V6l-4 5H4v2Z" />
            <path d="M15.5 9.5a4 4 0 0 1 0 5" />
            <path d="M18.5 7a8 8 0 0 1 0 10" />
          </svg>
          <span>dB</span>
        </div>
        <div class="metric-heading">
          <span>环境声音</span>
          <strong>{{ formatDbfs(currentDbfs) }}</strong>
        </div>
        <div class="sound-bars" aria-hidden="true">
          <i v-for="level in 10" :key="level" :class="{ active: level <= soundBarCount }"></i>
        </div>
        <p>{{ soundAssessment }}</p>
      </article>
    </section>

    <section class="analysis-grid">
      <article class="trend-panel climate-panel care-glass-card">
        <div class="section-heading">
          <div>
            <h2>温湿度变化趋势</h2>
          </div>
          <div class="legend">
            <span><i class="temp-dot"></i>温度</span>
            <span><i class="humidity-dot"></i>湿度</span>
          </div>
        </div>
        <div ref="climateChartEl" class="environment-chart climate-chart" aria-label="最近 30 分钟温度和湿度折线图"></div>
        <div v-if="!hasClimateData" class="chart-empty">等待 AHT20 上传温湿度数据</div>
      </article>

      <article class="trend-panel sound-panel care-glass-card">
        <div class="section-heading">
          <div>
            <h2>环境声音趋势</h2>
          </div>
          <div class="legend">
            <span><i class="sound-dot"></i>dBFS</span>
          </div>
        </div>
        <div ref="soundChartEl" class="environment-chart sound-chart" aria-label="最近 30 分钟环境声音折线图"></div>
        <div v-if="!hasSoundData" class="chart-empty">等待麦克风上传相对声级</div>
      </article>

    </section>

    <p v-if="error" class="page-error">{{ error }}</p>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import * as echarts from 'echarts'
import request from '@/utils/request'
import { useThemeStore } from '@/stores/themeStore'
import { useBedStore } from '@/stores/bedStore'

const theme = useThemeStore()
const bedStore = useBedStore()
const loading = ref(false)
const error = ref('')
const updatedAt = ref(null)
const timeline = ref([])
const climateChartEl = ref(null)
const soundChartEl = ref(null)
let climateChart = null
let soundChart = null
let refreshTimer = null

const status = reactive({
  environment_board_online: false,
  snore_board_online: false,
  snore_monitoring: false,
  snore_paused: false,
  voice_board_online: false,
  edgi_board_online: false,
  emergency_active: false,
  active_emergency: null,
  environment_age_seconds: null,
  snore_age_seconds: null,
  voice_age_seconds: null,
  temperature_c: null,
  humidity_pct: null,
  snore_dbfs: null,
  last_audio_dbfs: null,
  comfort_status: 'offline'
})

const isNumber = value => Number.isFinite(Number(value)) && value !== null && value !== ''
const clamp = (value, min, max) => Math.min(max, Math.max(min, value))

const currentDbfs = computed(() => {
  if (isNumber(status.snore_dbfs)) return Number(status.snore_dbfs)
  if (isNumber(status.last_audio_dbfs)) return Number(status.last_audio_dbfs)
  const values = timeline.value.map(row => row.snore_dbfs ?? row.last_audio_dbfs).filter(isNumber)
  return values.length ? Number(values[values.length - 1]) : null
})

function temperatureScore(value) {
  if (!isNumber(value)) return null
  const number = Number(value)
  if (number >= 18 && number <= 24) return 100
  const distance = number < 18 ? 18 - number : number - 24
  return Math.round(clamp(100 - distance * 12, 20, 100))
}

function humidityScore(value) {
  if (!isNumber(value)) return null
  const number = Number(value)
  if (number >= 40 && number <= 60) return 100
  const distance = number < 40 ? 40 - number : number - 60
  return Math.round(clamp(100 - distance * 3, 20, 100))
}

function soundScore(value) {
  if (!isNumber(value)) return null
  const number = Number(value)
  if (number <= -55) return 100
  if (number <= -45) return Math.round(85 + (-45 - number) * 1.5)
  if (number <= -35) return Math.round(65 + (-35 - number) * 2)
  if (number <= -25) return Math.round(35 + (-25 - number) * 3)
  return 20
}

const scoreFactors = computed(() => [
  { key: 'temperature', label: '温度适宜度', value: temperatureScore(status.temperature_c), detail: '建议 18–24°C' },
  { key: 'humidity', label: '湿度适宜度', value: humidityScore(status.humidity_pct), detail: '建议 40–60%' },
  { key: 'sound', label: '环境安静度', value: soundScore(currentDbfs.value), detail: '越负越安静' }
])

const environmentScore = computed(() => {
  const weighted = [
    [temperatureScore(status.temperature_c), 0.38],
    [humidityScore(status.humidity_pct), 0.32],
    [soundScore(currentDbfs.value), 0.3]
  ].filter(([value]) => value !== null)
  if (!weighted.length) return null
  const totalWeight = weighted.reduce((sum, item) => sum + item[1], 0)
  return Math.round(weighted.reduce((sum, item) => sum + item[0] * item[1], 0) / totalWeight)
})

const scoreLevel = computed(() => {
  if (environmentScore.value === null) return 'waiting'
  if (environmentScore.value >= 85) return 'excellent'
  if (environmentScore.value >= 70) return 'good'
  if (environmentScore.value >= 55) return 'warning'
  return 'poor'
})

const scoreLabel = computed(() => ({
  waiting: '等待环境数据',
  excellent: '非常适合睡眠',
  good: '环境整体良好',
  warning: '建议适当调整',
  poor: '环境需要改善'
}[scoreLevel.value]))

const scoreSummary = computed(() => {
  if (environmentScore.value === null) return '开发板上线后，将根据真实温湿度和声音数据生成评分。'
  if (scoreLevel.value === 'excellent') return '温湿度与声音环境均较稳定，有利于入睡和维持睡眠。'
  if (scoreLevel.value === 'good') return '总体适宜，仍有一项环境指标可以进一步优化。'
  if (scoreLevel.value === 'warning') return '部分指标偏离舒适区，可能影响入睡速度或夜间稳定性。'
  return '当前存在明显环境干扰，建议优先处理评分最低的指标。'
})

const scoreGaugeStyle = computed(() => {
  const value = environmentScore.value || 0
  const color = scoreLevel.value === 'poor'
    ? 'var(--care-danger)'
    : scoreLevel.value === 'warning'
      ? 'var(--care-warning)'
      : 'var(--care-primary)'
  return { background: `conic-gradient(${color} ${value * 3.6}deg, var(--care-divider) 0deg)` }
})

const temperaturePosition = computed(() => `${clamp((Number(status.temperature_c || 10) - 10) / 25 * 100, 0, 100)}%`)
const humidityPosition = computed(() => `${clamp(Number(status.humidity_pct || 0), 0, 100)}%`)
const soundBarCount = computed(() => {
  if (!isNumber(currentDbfs.value)) return 0
  return Math.round(clamp((Number(currentDbfs.value) + 70) / 5, 1, 10))
})

const temperatureAssessment = computed(() => {
  if (!isNumber(status.temperature_c)) return '等待 AHT20 上传温度数据。'
  const value = Number(status.temperature_c)
  if (value < 18) return '温度偏低，可能增加身体保温负担。'
  if (value > 24) return '温度偏高，可能造成闷热和夜间觉醒。'
  return '处于推荐睡眠温度范围。'
})

const humidityAssessment = computed(() => {
  if (!isNumber(status.humidity_pct)) return '等待 AHT20 上传湿度数据。'
  const value = Number(status.humidity_pct)
  if (value < 40) return '空气偏干，可能引起鼻腔和咽喉不适。'
  if (value > 60) return '湿度偏高，建议加强通风或除湿。'
  return '处于推荐睡眠湿度范围。'
})

const soundAssessment = computed(() => {
  if (!isNumber(currentDbfs.value)) return '等待麦克风上传相对声级。'
  const value = Number(currentDbfs.value)
  if (value <= -55) return '当前声音背景很安静。'
  if (value <= -45) return '声音环境较安静，适合睡眠。'
  if (value <= -35) return '存在可感知声音，建议排查持续声源。'
  return '声音较强，可能干扰入睡或造成觉醒。'
})

const hasClimateData = computed(() => timeline.value.some(row =>
  row.environment_online && (isNumber(row.temperature_c) || isNumber(row.humidity_pct))
))
const hasSoundData = computed(() => timeline.value.some(row => isNumber(row.snore_dbfs ?? row.last_audio_dbfs)))

const updatedText = computed(() => updatedAt.value
  ? `更新于 ${updatedAt.value.toLocaleTimeString('zh-CN', { hour12: false })}`
  : '尚未更新')

function formatNumber(value, unit) {
  return isNumber(value) ? `${Number(value).toFixed(1)}${unit}` : '--'
}

function formatDbfs(value) {
  return isNumber(value) ? `${Number(value).toFixed(1)} dBFS` : '--'
}

function formatAge(value) {
  if (!isNumber(value)) return '暂无'
  const seconds = Number(value)
  if (seconds < 1) return '刚刚'
  if (seconds < 60) return `${seconds.toFixed(0)} 秒前`
  return `${Math.floor(seconds / 60)} 分钟前`
}

function chartTokens() {
  const dark = theme.isDark
  return {
    text: dark ? '#cbd5e1' : '#41576b',
    grid: dark ? 'rgba(148,163,184,.16)' : 'rgba(100,116,139,.14)'
  }
}

function chartLabels() {
  return timeline.value.map(row => {
    const date = new Date(row.timestamp)
    return Number.isNaN(date.getTime()) ? row.timestamp : date.toLocaleTimeString('zh-CN', { hour12: false, hour: '2-digit', minute: '2-digit' })
  })
}

function climateChartOption() {
  const { text, grid } = chartTokens()
  const labels = chartLabels()
  return {
    animationDuration: 350,
    tooltip: { trigger: 'axis' },
    grid: { left: 52, right: 58, top: 34, bottom: 44 },
    xAxis: {
      type: 'category',
      data: labels,
      boundaryGap: false,
      axisLabel: { color: text, hideOverlap: true },
      axisLine: { lineStyle: { color: grid } }
    },
    yAxis: [
      {
        type: 'value',
        name: '温度 °C',
        min: 10,
        max: 35,
        axisLabel: { color: text },
        splitLine: { lineStyle: { color: grid } }
      },
      {
        type: 'value',
        name: '湿度 %RH',
        min: 0,
        max: 100,
        axisLabel: { color: text },
        splitLine: { show: false }
      }
    ],
    series: [
      {
        name: '温度',
        type: 'line',
        smooth: true,
        showSymbol: false,
        connectNulls: false,
        data: timeline.value.map(row => row.environment_online && isNumber(row.temperature_c) ? Number(row.temperature_c) : null),
        lineStyle: { width: 3, color: '#ef4444' },
        areaStyle: { color: 'rgba(239,68,68,.08)' }
      },
      {
        name: '湿度',
        type: 'line',
        smooth: true,
        showSymbol: false,
        connectNulls: false,
        yAxisIndex: 1,
        data: timeline.value.map(row => row.environment_online && isNumber(row.humidity_pct) ? Number(row.humidity_pct) : null),
        lineStyle: { width: 3, color: '#38bdf8' },
        areaStyle: { color: 'rgba(56,189,248,.06)' }
      }
    ]
  }
}

function soundChartOption() {
  const { text, grid } = chartTokens()
  const labels = chartLabels()
  return {
    animationDuration: 350,
    tooltip: { trigger: 'axis' },
    grid: { left: 54, right: 24, top: 34, bottom: 44 },
    xAxis: {
      type: 'category',
      data: labels,
      boundaryGap: false,
      axisLabel: { color: text, hideOverlap: true },
      axisLine: { lineStyle: { color: grid } }
    },
    yAxis: {
      type: 'value',
      name: 'dBFS',
      min: -80,
      max: 0,
      axisLabel: { color: text },
      splitLine: { lineStyle: { color: grid } }
    },
    series: [
      {
        name: '声音',
        type: 'line',
        smooth: true,
        showSymbol: false,
        connectNulls: false,
        data: timeline.value.map(row => isNumber(row.snore_dbfs ?? row.last_audio_dbfs) ? Number(row.snore_dbfs ?? row.last_audio_dbfs) : null),
        lineStyle: { width: 2, color: '#f59e0b' },
        areaStyle: { color: 'rgba(245,158,11,.08)' }
      }
    ]
  }
}

function renderChart() {
  if (climateChartEl.value) {
    if (!climateChart) climateChart = echarts.init(climateChartEl.value)
    climateChart.setOption(climateChartOption(), true)
    climateChart.resize()
  }
  if (soundChartEl.value) {
    if (!soundChart) soundChart = echarts.init(soundChartEl.value)
    soundChart.setOption(soundChartOption(), true)
    soundChart.resize()
  }
}

async function loadEnvironment() {
  loading.value = true
  error.value = ''
  try {
    const [statusResult, timelineResult] = await Promise.all([
      request.get('/status', { params: { bed_id: bedStore.selectedBedId } }),
      request.get('/timeline', { params: { seconds: 1800, bed_id: bedStore.selectedBedId } })
    ])
    Object.assign(status, {
      environment_board_online: !!statusResult.environment_board_online,
      snore_board_online: !!statusResult.snore_board_online,
      snore_monitoring: !!statusResult.snore_monitoring,
      snore_paused: !!statusResult.snore_paused,
      voice_board_online: !!statusResult.voice_board_online,
      edgi_board_online: !!statusResult.edgi_board_online,
      emergency_active: !!statusResult.emergency_active,
      active_emergency: statusResult.active_emergency || null,
      environment_age_seconds: statusResult.environment_age_seconds,
      snore_age_seconds: statusResult.snore_age_seconds,
      voice_age_seconds: statusResult.voice_age_seconds,
      temperature_c: isNumber(statusResult.temperature_c) ? Number(statusResult.temperature_c) : null,
      humidity_pct: isNumber(statusResult.humidity_pct) ? Number(statusResult.humidity_pct) : null,
      snore_dbfs: isNumber(statusResult.snore_dbfs) ? Number(statusResult.snore_dbfs) : null,
      last_audio_dbfs: isNumber(statusResult.last_audio_dbfs) ? Number(statusResult.last_audio_dbfs) : null,
      comfort_status: statusResult.comfort_status || 'offline'
    })
    timeline.value = Array.isArray(timelineResult.data) ? timelineResult.data : []
    updatedAt.value = new Date()
  } catch (err) {
    console.error('环境分析数据加载失败:', err)
    error.value = '无法连接环境数据接口，请确认后端服务运行在 8081 端口。'
  } finally {
    loading.value = false
    await nextTick()
    renderChart()
  }
}

function handleResize() {
  climateChart?.resize()
  soundChart?.resize()
}

watch(() => theme.isDark, () => nextTick(renderChart))

onMounted(() => {
  loadEnvironment()
  refreshTimer = window.setInterval(loadEnvironment, 5000)
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  if (refreshTimer) window.clearInterval(refreshTimer)
  window.removeEventListener('resize', handleResize)
  climateChart?.dispose()
  soundChart?.dispose()
  climateChart = null
  soundChart = null
})
</script>

<style scoped>
.environment-page {
  display: grid;
  gap: 18px;
}

.emergency-strip {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 18px;
  color: #fff;
  background: var(--care-danger);
  border-radius: 8px;
}

.emergency-strip span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.environment-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  padding: 4px 2px;
}

.environment-header h1 {
  margin: 6px 0 8px;
  color: var(--care-text-strong);
  font-size: 32px;
  letter-spacing: 0;
}

.environment-header p,
.score-copy p,
.metric-card p,
.data-note p {
  margin: 0;
  color: var(--care-muted);
  line-height: 1.65;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.updated-at {
  color: var(--care-muted);
  font-size: 12px;
}

.score-band {
  display: grid;
  grid-template-columns: 148px minmax(220px, .8fr) minmax(420px, 1.4fr);
  align-items: center;
  gap: 28px;
  padding: 24px 28px;
  border: 1px solid var(--care-border);
  border-left: 7px solid var(--care-primary);
  border-radius: 8px;
  background: var(--care-surface);
  box-shadow: var(--care-shadow-soft);
}

.score-band.warning {
  border-left-color: var(--care-warning);
}

.score-band.poor {
  border-left-color: var(--care-danger);
}

.score-band.waiting {
  border-left-color: var(--care-muted);
}

.score-gauge {
  width: 128px;
  height: 128px;
  display: grid;
  place-items: center;
  border-radius: 50%;
}

.score-gauge > div {
  width: 100px;
  height: 100px;
  display: grid;
  place-content: center;
  border-radius: 50%;
  text-align: center;
  background: var(--care-surface-strong);
}

.score-gauge strong {
  color: var(--care-text-strong);
  font-size: 38px;
  line-height: 1;
}

.score-gauge span {
  color: var(--care-muted);
  font-size: 12px;
}

.score-copy span,
.section-heading span,
.metric-heading span {
  color: var(--care-muted);
  font-size: 12px;
  font-weight: 800;
}

.score-copy h2,
.section-heading h2 {
  margin: 5px 0 8px;
  color: var(--care-text-strong);
  font-size: 22px;
  letter-spacing: 0;
}

.score-factors {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  border-left: 1px solid var(--care-divider);
}

.score-factor {
  display: grid;
  grid-template-columns: 54px 1fr;
  align-items: center;
  gap: 14px;
  padding: 8px 22px;
  border-right: 1px solid var(--care-divider);
}

.factor-icon {
  width: 54px;
  height: 54px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: #eef4ff;
  color: var(--care-primary);
  box-shadow: inset 0 0 0 1px rgba(50, 91, 242, .08);
}

.factor-icon svg,
.metric-icon svg {
  width: 24px;
  height: 24px;
  fill: none;
  stroke: currentColor;
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.score-factor.temperature .factor-icon {
  background: #eef4ff;
  color: #325bf2;
}

.score-factor.humidity .factor-icon {
  background: #eef8ff;
  color: #0ea5e9;
}

.score-factor.sound .factor-icon {
  background: #eefcf4;
  color: #22c55e;
}

.score-factors span,
.score-factors small {
  color: var(--care-muted);
}

.score-factors strong {
  color: var(--care-text-strong);
  font-size: 24px;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

.metric-card {
  display: grid;
  grid-template-columns: 58px 1fr;
  gap: 12px 16px;
  padding: 20px;
  border: 1px solid var(--care-border);
  border-radius: 8px;
  background: var(--care-surface);
  box-shadow: var(--care-shadow-card);
}

.metric-icon {
  width: 58px;
  height: 58px;
  display: grid;
  grid-template-rows: 1fr auto;
  place-items: center;
  border-radius: 8px;
  color: var(--care-primary);
  background: #eef4ff;
  font-size: 12px;
  font-weight: 900;
  box-shadow: inset 0 0 0 1px rgba(50, 91, 242, .08);
}

.metric-icon svg {
  margin-top: 7px;
}

.metric-icon span {
  margin-bottom: 7px;
  line-height: 1;
}

.temperature .metric-icon { background: #fff1f2; color: #fb7185; }
.humidity .metric-icon { background: #eff8ff; color: #38bdf8; }
.sound .metric-icon { background: #fff7ed; color: #fdba74; }

.metric-heading {
  display: grid;
  align-content: center;
  gap: 5px;
}

.metric-heading strong {
  color: var(--care-text-strong);
  font-size: 28px;
}

.metric-scale,
.sound-bars,
.metric-card p {
  grid-column: 1 / -1;
}

.metric-scale {
  height: 7px;
  overflow: hidden;
  border-radius: 4px;
  background: var(--care-divider);
}

.metric-scale i {
  display: block;
  height: 100%;
  max-width: 100%;
  border-radius: inherit;
  background: var(--care-primary);
}

.temperature .metric-scale { background: #ffe4e6; }
.humidity .metric-scale { background: #e0f2fe; }
.temperature .metric-scale i { background: #fda4af; }
.humidity .metric-scale i { background: #93c5fd; }

.sound-bars {
  height: 28px;
  display: flex;
  align-items: flex-end;
  gap: 5px;
}

.sound-bars i {
  width: 9%;
  height: 20%;
  border-radius: 2px;
  background: var(--care-divider);
}

.sound-bars i:nth-child(2n) { height: 42%; }
.sound-bars i:nth-child(3n) { height: 68%; }
.sound-bars i:nth-child(5n) { height: 92%; }
.sound-bars i.active { background: #fed7aa; }

.analysis-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
}

.trend-panel {
  position: relative;
  padding: 20px;
  border-radius: 8px;
}

.section-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.legend {
  display: flex;
  gap: 14px;
}

.legend span {
  display: flex;
  align-items: center;
  gap: 6px;
}

.legend i {
  width: 9px;
  height: 9px;
  border-radius: 50%;
}

.temp-dot { background: #ef4444; }
.humidity-dot { background: #38bdf8; }
.sound-dot { background: #f59e0b; }

.environment-chart {
  width: 100%;
  height: 260px;
}

.chart-empty {
  position: absolute;
  inset: 138px 20px auto;
  color: var(--care-muted);
  text-align: center;
}

.data-note {
  margin-top: 20px;
  padding: 16px;
  border-left: 4px solid var(--care-accent);
  background: var(--care-accent-soft);
}

.data-note strong {
  color: var(--care-text-strong);
}

.data-note p {
  margin-top: 6px;
  font-size: 12px;
}

.page-error {
  margin: 0;
  color: var(--care-danger);
}

@media (max-width: 1180px) {
  .score-band {
    grid-template-columns: 128px 1fr;
  }

  .score-factors {
    grid-column: 1 / -1;
    border-top: 1px solid var(--care-divider);
    border-left: 0;
    padding-top: 14px;
  }

  .analysis-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 820px) {
  .environment-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .metric-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 560px) {
  .environment-page {
    gap: 14px;
  }

  .score-band {
    grid-template-columns: 1fr;
    padding: 20px;
  }

  .score-gauge {
    margin: 0 auto;
  }

  .score-copy {
    text-align: center;
  }

  .score-factors {
    grid-template-columns: 1fr;
  }

  .score-factor {
    border-right: 0;
    border-bottom: 1px solid var(--care-divider);
  }

  .section-heading,
  .legend,
  .header-actions {
    align-items: flex-start;
    flex-direction: column;
  }

  .environment-chart {
    height: 240px;
  }
}
</style>
