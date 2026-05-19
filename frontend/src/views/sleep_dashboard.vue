<template>
  <div class="sleep-page">
    <div class="hero-panel">
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
      <section class="score-card neon-card">
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

      <section class="event-card neon-card">
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

      <section class="heat-card neon-card">
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
      <div v-for="card in stabilityCards" :key="card.key" class="stability-card">
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
  const color = value >= 86 ? '#26f7a5' : value >= 68 ? '#f7d154' : '#ff6b9a'
  return {
    background: `conic-gradient(${color} ${value * 3.6}deg, rgba(255,255,255,.08) 0deg)`,
    boxShadow: `0 0 36px ${color}55`
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
  return new Date(now.getTime() - offset).toISOString().slice(0, 10)
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
    overview.score = {
      score: 0,
      label: '后端未连接',
      summary: '请先启动 python backend\\mock_hardware_api.py。',
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
  color: #ecf7ff;
  background:
    radial-gradient(circle at 15% 12%, rgba(52, 211, 255, 0.22), transparent 32%),
    radial-gradient(circle at 84% 16%, rgba(165, 85, 255, 0.28), transparent 34%),
    linear-gradient(135deg, #06111f 0%, #09182d 48%, #120c2a 100%);
  overflow: hidden;
}

.sleep-page::before {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  background-image: linear-gradient(rgba(255,255,255,.04) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.035) 1px, transparent 1px);
  background-size: 36px 36px;
  mask-image: radial-gradient(circle at 50% 20%, black, transparent 82%);
}

.hero-panel,
.neon-card,
.stability-card,
.device-pill {
  position: relative;
  border: 1px solid rgba(123, 220, 255, 0.22);
  background: rgba(7, 18, 35, 0.72);
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.34), inset 0 0 0 1px rgba(255,255,255,.03);
  backdrop-filter: blur(14px);
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
  color: #67e8f9;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  font-size: 12px;
  margin-bottom: 8px;
}

h1 {
  margin: 0;
  font-size: 34px;
  letter-spacing: 0.04em;
}

.hero-copy {
  margin: 10px 0 0;
  color: #9fb7d5;
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
  border: 1px solid rgba(103, 232, 249, 0.28);
  border-radius: 999px;
  color: #dff8ff;
  background: rgba(7, 22, 42, 0.88);
  padding: 9px 14px;
  outline: none;
}

.control-strip button {
  cursor: pointer;
}

.control-strip button.active,
.control-strip button.refresh {
  color: #06111f;
  background: linear-gradient(135deg, #67e8f9, #a7f3d0);
  box-shadow: 0 0 18px rgba(103, 232, 249, 0.42);
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
  color: #95aac7;
}

.device-pill.online {
  color: #afffe2;
  border-color: rgba(38, 247, 165, .42);
}

.device-pill.muted {
  color: #b9c7dc;
}

.pulse {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 7px;
  background: #5f718a;
}

.online .pulse {
  background: #26f7a5;
  box-shadow: 0 0 12px #26f7a5;
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
  color: #e7fbff;
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
  color: #91a8c7;
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
  background: radial-gradient(circle, #10233d, #07111f);
  border: 1px solid rgba(255,255,255,.12);
}

.score-core strong {
  font-size: 52px;
  line-height: 1;
}

.score-core span {
  margin-top: -24px;
  color: #87a7c7;
}

.score-text h2 {
  font-size: 32px;
  margin: 0 0 10px;
}

.score-text p {
  color: #a9bad2;
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
  color: #ffd4df;
  background: rgba(255, 107, 154, 0.14);
  border: 1px solid rgba(255, 107, 154, 0.32);
}

.good-tag {
  color: #b9ffdf;
  background: rgba(38, 247, 165, 0.12);
  border: 1px solid rgba(38, 247, 165, 0.3);
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
  border-bottom: 1px solid rgba(255,255,255,.08);
}

.event-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  margin-top: 6px;
  background: #67e8f9;
  box-shadow: 0 0 16px #67e8f9;
}

.event-item.warning .event-dot {
  background: #f7d154;
  box-shadow: 0 0 18px #f7d154;
}

.event-item.critical .event-dot {
  background: #ff6b9a;
  box-shadow: 0 0 20px #ff6b9a;
}

.event-item.normal .event-dot {
  background: #26f7a5;
  box-shadow: 0 0 16px #26f7a5;
}

.event-meta {
  color: #7e93b3;
  font-size: 12px;
}

.event-title {
  font-weight: 800;
  margin: 4px 0;
}

.event-message {
  color: #aebdd2;
  font-size: 13px;
  line-height: 1.6;
}

.heat-card {
  min-height: 350px;
}

.worst-box {
  text-align: right;
  color: #91a8c7;
  font-size: 12px;
}

.worst-box strong {
  display: block;
  margin-top: 4px;
  color: #f7d154;
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
  color: rgba(255,255,255,.78);
  background: linear-gradient(180deg, rgba(59, 130, 246, calc(.18 + var(--level) * .3)), rgba(20, 28, 56, .9));
  border: 1px solid rgba(103, 232, 249, .12);
}

.heat-cell.warning {
  background: linear-gradient(180deg, rgba(168, 85, 247, calc(.26 + var(--level) * .34)), rgba(36, 22, 56, .94));
  border-color: rgba(168, 85, 247, .34);
}

.heat-cell.critical {
  background: linear-gradient(180deg, rgba(255, 107, 154, calc(.32 + var(--level) * .38)), rgba(64, 18, 45, .96));
  border-color: rgba(255, 107, 154, .45);
  box-shadow: 0 0 18px rgba(255, 107, 154, .22);
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
  color: #94a9c7;
  font-size: 13px;
}

.mini-value {
  font-size: 32px;
  font-weight: 900;
  margin: 8px 0;
}

.mini-value span {
  color: #8da5c5;
  font-size: 14px;
  margin-left: 3px;
}

.mini-bar {
  height: 8px;
  background: rgba(255,255,255,.08);
  border-radius: 999px;
  overflow: hidden;
}

.mini-bar i {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #67e8f9, #26f7a5);
  box-shadow: 0 0 12px rgba(103, 232, 249, .5);
}

.stability-card p {
  color: #8ca1bf;
  margin: 10px 0 0;
}

.empty-state {
  color: #8ea4c4;
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
