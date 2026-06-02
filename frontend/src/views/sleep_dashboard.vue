<template>
  <div class="sleep-page care-page-shell">
    <div class="hero-panel care-glass-card">
      <div>
        <div class="eyebrow">Night Guardian Command Center</div>
        <h1>睡眠看护驾驶舱</h1>
        <p class="hero-copy">
          基于毫米波雷达生命体征、呼噜检测板音频特征和设备在线状态，实时评估睡眠稳定性与扰动风险。
        </p>
      </div>
      <div class="control-strip">
        <button :class="{ active: mode === 'live' }" @click="switchMode('live')">实时看护</button>
        <button :class="{ active: mode === 'history' }" @click="switchMode('history')">历史回放</button>
        <select v-if="mode === 'live'" v-model.number="seconds" @change="loadOverview">
          <option :value="600">最近 10 分钟</option>
          <option :value="1800">最近 30 分钟</option>
          <option :value="3600">最近 1 小时</option>
        </select>
        <input v-else v-model="date" type="date" @change="loadOverview" />
        <button class="refresh" :disabled="loading" @click="loadOverview">
          {{ loading ? '刷新中...' : '刷新' }}
        </button>
      </div>
    </div>

    <div class="device-row">
      <div class="device-pill" :class="{ online: devices.radar_board_online }">
        <span class="pulse"></span>
        雷达板 {{ deviceText(devices.radar_board_online) }}
      </div>
      <div class="device-pill" :class="{ online: devices.snore_board_online }">
        <span class="pulse"></span>
        呼噜板 {{ deviceText(devices.snore_board_online) }}
      </div>
      <div class="device-pill muted">音频片段 {{ devices.audio_upload_count ?? '--' }} 次</div>
      <div class="device-pill muted">数据点 {{ overview.stats?.points ?? 0 }}</div>
    </div>

    <div class="dashboard-grid">
      <section class="score-card care-glass-card">
        <div class="section-title">Sleep Quality Score</div>
        <div class="score-layout">
          <div class="score-ring" :style="scoreStyle">
            <div class="score-core">
              <strong>{{ score.score }}</strong>
              <span>/100</span>
            </div>
          </div>
          <div class="score-text">
            <h2>{{ score.label }}</h2>
            <p>{{ score.summary }}</p>
            <div class="penalty-list">
              <span v-if="topPenalties.length === 0" class="good-tag">暂无明显扣分项</span>
              <span v-for="item in topPenalties" :key="item.name" class="penalty-tag">
                {{ item.name }} -{{ item.value }}
              </span>
            </div>
          </div>
        </div>
      </section>

      <section class="event-card care-glass-card">
        <div class="section-header">
          <div class="section-title">夜间守护事件流</div>
          <select v-model="eventFilter" class="dark-select">
            <option value="all">全部</option>
            <option value="abnormal">只看异常</option>
            <option value="snore">只看呼噜</option>
            <option value="device">只看设备</option>
          </select>
        </div>
        <div class="event-list">
          <div v-if="filteredEvents.length === 0" class="empty-state">
            当前窗口没有异常事件。模拟板运行越久，这里越像夜间看护日志。
          </div>
          <div
            v-for="event in filteredEvents"
            :key="`${event.eventID}-${event.timestamp}`"
            class="event-item"
            :class="event.severity"
          >
            <div class="event-dot"></div>
            <div>
              <div class="event-meta">{{ formatTime(event.timestamp) }} · {{ sourceLabel(event.source) }}</div>
              <div class="event-title">{{ event.title }}</div>
              <div class="event-message">{{ event.message }}</div>
            </div>
          </div>
        </div>
      </section>

      <section class="heat-card care-glass-card">
        <div class="section-header">
          <div>
            <div class="section-title">呼噜扰动地图</div>
            <p class="section-subtitle">每分钟聚合呼噜强度，并标记呼噜前后心率/呼吸变化。</p>
          </div>
          <div class="worst-box">
            <span>最强扰动</span>
            <strong>{{ worstLabel }}</strong>
          </div>
        </div>
        <div class="heatmap">
          <div
            v-for="cell in heatmap"
            :key="cell.timestamp"
            class="heat-cell"
            :class="cell.severity"
            :style="{ '--level': cell.intensity || 0 }"
            :title="heatTooltip(cell)"
          >
            <span>{{ cell.label }}</span>
          </div>
          <div v-if="heatmap.length === 0" class="empty-state wide">
            暂无呼噜热力数据。启动呼噜检测模拟板后，这里会出现蓝紫橙红的时间热力条。
          </div>
        </div>
      </section>
    </div>

    <div class="stability-grid">
      <div v-for="card in stabilityCards" :key="card.key" class="stability-card care-glass-card">
        <div class="mini-title">{{ card.title }}</div>
        <div class="mini-value">{{ card.value }}<span>{{ card.unit }}</span></div>
        <div class="mini-bar"><i :style="{ width: `${card.value}%` }"></i></div>
        <p>{{ card.detail }}</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import request from '@/utils/request'
import { useUserStore } from '@/stores/userStore'

const userStore = useUserStore()

const mode = ref('live')
const seconds = ref(1800)
const date = ref(localDate())
const loading = ref(false)
const eventFilter = ref('all')
const refreshTimer = ref(null)

const overview = reactive({
  score: { score: 0, label: '等待数据', summary: '等待模拟开发板上线。', penalties: [] },
  stats: {},
  devices: {},
  heatmap: [],
  events: [],
  stability_cards: [],
  worst_disturbance: null
})

const devices = computed(() => overview.devices || {})
const score = computed(() => overview.score || { score: 0, label: '等待数据', summary: '', penalties: [] })
const heatmap = computed(() => overview.heatmap || [])
const stabilityCards = computed(() => overview.stability_cards || [])
const topPenalties = computed(() => (score.value.penalties || []).slice(0, 4))

const scoreStyle = computed(() => {
  const value = Math.max(0, Math.min(100, Number(score.value.score || 0)))
  const color = value >= 86 ? '#16a34a' : value >= 68 ? '#f59e0b' : '#ef4444'
  const track = getComputedStyle(document.documentElement)
    .getPropertyValue('--care-surface-muted').trim() || 'rgba(15,59,72,.1)'
  return {
    background: `conic-gradient(${color} ${value * 3.6}deg, ${track} 0deg)`,
    boxShadow: `0 0 36px ${color}33`
  }
})

const worstLabel = computed(() => {
  const worst = overview.worst_disturbance
  if (!worst) return '暂无'
  return `${worst.label} · ${Math.round((worst.intensity || 0) * 100)}%`
})

const filteredEvents = computed(() => {
  const events = overview.events || []
  if (eventFilter.value === 'all') return events
  if (eventFilter.value === 'abnormal') {
    return events.filter(event => ['warning', 'critical'].includes(event.severity))
  }
  if (eventFilter.value === 'snore') {
    return events.filter(event => event.type === 'snore')
  }
  return events.filter(event => event.type === 'device_offline')
})

function localDate() {
  const now = new Date()
  const offset = now.getTimezoneOffset() * 60000
  return new Date(now - offset).toISOString().slice(0, 10)
}

function userID() {
  return userStore.userInfo?.userID || userStore.userInfo?.user_id || 1
}

async function loadOverview() {
  loading.value = true
  try {
    const params = mode.value === 'history'
      ? { mode: 'history', date: date.value, userID: userID() }
      : { mode: 'live', seconds: seconds.value }
    const response = await request.get('/sleep/overview', { params })
    overview.score = response.score || overview.score
    overview.stats = response.stats || {}
    overview.devices = response.devices || {}
    overview.heatmap = response.heatmap || []
    overview.events = response.events || []
    overview.stability_cards = response.stability_cards || []
    overview.worst_disturbance = response.worst_disturbance || null
  } catch (error) {
    console.error('sleep overview load failed:', error)
    const status = error.response?.status
    const hint =
      status === 404
        ? '检测到 8081 端口有服务，但缺少 /sleep/overview 接口。\n请停止当前后端，改启动：python backend\\mock_hardware_api.py\n（不要启动 realtime_radar_processing.py 或 mock_server.py）'
        : !error.response
        ? '无法连接 8081 端口后端服务。\n请先在项目根目录执行：conda activate radar && python backend\\mock_hardware_api.py'
        : '请先启动后端：python backend\\mock_hardware_api.py'
    overview.score = {
      score: 0,
      label: status === 404 ? '后端接口缺失' : '后端未连接',
      summary: hint,
      penalties: []
    }
  } finally {
    loading.value = false
  }
}

function switchMode(nextMode) {
  mode.value = nextMode
  loadOverview()
}

function startAutoRefresh() {
  stopAutoRefresh()
  refreshTimer.value = window.setInterval(() => {
    if (mode.value === 'live') loadOverview()
  }, 2500)
}

function stopAutoRefresh() {
  if (refreshTimer.value) {
    window.clearInterval(refreshTimer.value)
    refreshTimer.value = null
  }
}

function deviceText(value) {
  if (value === null || value === undefined) return '历史模式'
  return value ? '在线' : '离线'
}

function formatTime(value) {
  if (!value) return '--:--'
  const dateValue = new Date(value)
  if (Number.isNaN(dateValue.getTime())) return value
  return dateValue.toLocaleTimeString('zh-CN', { hour12: false })
}

function sourceLabel(source) {
  const map = {
    radar_board: '雷达板',
    snore_board: '呼噜板',
    mock_api: '模拟后端'
  }
  return map[source] || source || '系统'
}

function heatTooltip(cell) {
  const snore = Math.round((cell.avg_snore_level || 0) * 100)
  const heart = cell.heart_delta === null || cell.heart_delta === undefined ? '--' : `${cell.heart_delta >= 0 ? '+' : ''}${cell.heart_delta} BPM`
  const breath = cell.breath_delta === null || cell.breath_delta === undefined ? '--' : `${cell.breath_delta >= 0 ? '+' : ''}${cell.breath_delta} RPM`
  return `${cell.label} 呼噜强度 ${snore}%；事件 ${cell.snore_events}；心率变化 ${heart}；呼吸变化 ${breath}`
}

onMounted(() => {
  loadOverview()
  startAutoRefresh()
})

onBeforeUnmount(() => {
  stopAutoRefresh()
})
</script>

<style scoped>
.sleep-page {
  min-height: calc(100vh - 90px);
  margin: -20px;
  padding: 22px;
  color: var(--care-text);
}

.hero-panel {
  display: flex;
  justify-content: space-between;
  gap: 20px;
  align-items: center;
  border-radius: 22px;
  padding: 24px 26px;
  margin-bottom: 16px;
}

.eyebrow {
  color: var(--care-primary-strong);
  letter-spacing: 0.18em;
  text-transform: uppercase;
  font-size: 12px;
  margin-bottom: 8px;
}

h1 {
  margin: 0;
  font-size: 34px;
  letter-spacing: 0.04em;
  color: var(--care-text-strong);
}

.hero-copy {
  margin: 10px 0 0;
  color: var(--care-muted);
  max-width: 720px;
}

.control-strip {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 10px;
}

.control-strip button,
.control-strip select,
.control-strip input,
.dark-select {
  border: 1px solid var(--care-border);
  border-radius: 999px;
  color: var(--care-text);
  background: var(--care-surface-strong);
  padding: 9px 14px;
  outline: none;
  transition: background 0.2s ease, color 0.2s ease, border-color 0.2s ease;
}

.control-strip button {
  cursor: pointer;
  font-weight: 600;
}

.control-strip button:hover,
.control-strip select:hover,
.control-strip input:hover,
.dark-select:hover {
  border-color: var(--care-primary-border);
}

.control-strip button.active,
.control-strip button.refresh {
  color: var(--care-text-on-primary);
  background: linear-gradient(135deg, var(--care-primary), var(--care-accent));
  border-color: transparent;
  box-shadow: 0 0 18px var(--care-primary-soft);
}

.device-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 16px;
}

.device-pill {
  border-radius: 999px;
  padding: 8px 14px;
  border: 1px solid var(--care-border);
  background: var(--care-surface-strong);
  color: var(--care-muted);
  transition: background 0.2s ease, color 0.2s ease, border-color 0.2s ease;
}

.device-pill.online {
  color: var(--care-success);
  border-color: var(--care-success);
  background: var(--care-success-soft);
}

.device-pill.muted {
  color: var(--care-muted-strong);
}

.pulse {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 7px;
  background: var(--care-muted);
}

.online .pulse {
  background: var(--care-success);
  box-shadow: 0 0 12px var(--care-success);
}

.dashboard-grid {
  display: grid;
  grid-template-columns: minmax(420px, 1fr) minmax(360px, 0.8fr);
  gap: 16px;
}

.neon-card {
  border-radius: 22px;
  padding: 20px;
}

.score-card {
  min-height: 310px;
}

.section-title {
  color: var(--care-text-strong);
  font-weight: 800;
  letter-spacing: 0.04em;
  font-size: 17px;
}

.section-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  margin-bottom: 14px;
}

.section-subtitle {
  color: var(--care-muted);
  margin: 8px 0 0;
  font-size: 13px;
}

.score-layout {
  display: grid;
  grid-template-columns: 220px 1fr;
  gap: 28px;
  align-items: center;
  margin-top: 20px;
}

.score-ring {
  width: 210px;
  height: 210px;
  border-radius: 50%;
  display: grid;
  place-items: center;
}

.score-core {
  width: 150px;
  height: 150px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: radial-gradient(circle, var(--care-surface-strong), var(--care-surface));
  border: 1px solid var(--care-border);
  color: var(--care-text-strong);
}

.score-core strong {
  font-size: 52px;
  line-height: 1;
}

.score-core span {
  margin-top: -24px;
  color: var(--care-muted);
}

.score-text h2 {
  font-size: 32px;
  margin: 0 0 10px;
  color: var(--care-text-strong);
}

.score-text p {
  color: var(--care-muted-strong);
  line-height: 1.8;
}

.penalty-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 16px;
}

.penalty-tag,
.good-tag {
  border-radius: 999px;
  padding: 6px 10px;
  font-size: 12px;
}

.penalty-tag {
  color: var(--care-danger);
  background: var(--care-danger-soft);
  border: 1px solid var(--care-danger);
}

.good-tag {
  color: var(--care-success);
  background: var(--care-success-soft);
  border: 1px solid var(--care-success);
}

.event-card {
  grid-row: span 2;
  max-height: 676px;
  overflow: hidden;
}

.event-list {
  max-height: 596px;
  overflow: auto;
  padding-right: 5px;
}

.event-item {
  display: grid;
  grid-template-columns: 18px 1fr;
  gap: 12px;
  padding: 14px 0;
  border-bottom: 1px solid var(--care-divider);
}

.event-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  margin-top: 6px;
  background: var(--care-accent);
  box-shadow: 0 0 16px var(--care-accent);
}

.event-item.warning .event-dot {
  background: var(--care-warning);
  box-shadow: 0 0 18px var(--care-warning);
}

.event-item.critical .event-dot {
  background: var(--care-danger);
  box-shadow: 0 0 20px var(--care-danger);
}

.event-item.normal .event-dot {
  background: var(--care-success);
  box-shadow: 0 0 16px var(--care-success);
}

.event-meta {
  color: var(--care-muted);
  font-size: 12px;
}

.event-title {
  font-weight: 800;
  margin: 4px 0;
  color: var(--care-text-strong);
}

.event-message {
  color: var(--care-muted-strong);
  font-size: 13px;
  line-height: 1.6;
}

.heat-card {
  min-height: 350px;
}

.worst-box {
  text-align: right;
  color: var(--care-muted);
  font-size: 12px;
}

.worst-box strong {
  display: block;
  margin-top: 4px;
  color: var(--care-warning);
  font-size: 18px;
}

.heatmap {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(54px, 1fr));
  gap: 8px;
  margin-top: 12px;
}

.heat-cell {
  min-height: 48px;
  border-radius: 12px;
  display: flex;
  align-items: flex-end;
  justify-content: center;
  padding: 6px;
  font-size: 11px;
  color: var(--care-text-strong);
  background: linear-gradient(180deg, rgba(56, 189, 248, calc(.18 + var(--level) * .3)), var(--care-surface-2));
  border: 1px solid var(--care-border-soft);
  transition: background 0.2s ease, border-color 0.2s ease;
}

.heat-cell.warning {
  background: linear-gradient(180deg, rgba(168, 85, 247, calc(.26 + var(--level) * .34)), var(--care-surface-2));
  border-color: rgba(168, 85, 247, .34);
}

.heat-cell.critical {
  background: linear-gradient(180deg, rgba(239, 68, 68, calc(.32 + var(--level) * .38)), var(--care-surface-2));
  border-color: var(--care-danger);
  box-shadow: 0 0 18px var(--care-danger-soft);
}

.stability-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(200px, 1fr));
  gap: 16px;
  margin-top: 16px;
}

.stability-card {
  border-radius: 18px;
  padding: 18px;
}

.mini-title {
  color: var(--care-muted);
  font-size: 13px;
}

.mini-value {
  font-size: 32px;
  font-weight: 900;
  margin: 8px 0;
  color: var(--care-text-strong);
}

.mini-value span {
  color: var(--care-muted);
  font-size: 14px;
  margin-left: 3px;
}

.mini-bar {
  height: 8px;
  background: var(--care-surface-muted);
  border-radius: 999px;
  overflow: hidden;
}

.mini-bar i {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, var(--care-primary), var(--care-success));
  box-shadow: 0 0 12px var(--care-primary-soft);
}

.stability-card p {
  color: var(--care-muted-strong);
  margin: 10px 0 0;
}

.empty-state {
  color: var(--care-muted);
  line-height: 1.8;
  padding: 24px 0;
}

.empty-state.wide {
  grid-column: 1 / -1;
}

@media (max-width: 1280px) {
  .hero-panel,
  .score-layout {
    grid-template-columns: 1fr;
    display: block;
  }

  .control-strip {
    justify-content: flex-start;
    margin-top: 16px;
  }

  .dashboard-grid,
  .stability-grid {
    grid-template-columns: 1fr;
  }

  .event-card {
    grid-row: auto;
  }
}
</style>
