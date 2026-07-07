<template>
  <div class="sleep-page care-page-shell">
    <div class="hero-panel care-glass-card care-icon-card" data-icon="BR">
      <div>
        <h1>睡眠看护驾驶舱</h1>
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

    <div class="dashboard-grid">
      <section class="score-card care-glass-card care-icon-card" data-icon="评">
        <div class="section-title">睡眠评分</div>
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

      <section class="event-card care-glass-card care-icon-card" data-icon="事">
        <div class="section-header">
          <div class="section-title">夜间守护事件流</div>
          <select v-model="eventFilter" class="dark-select">
            <option value="all">全部</option>
            <option value="abnormal">只看异常</option>
            <option value="apnea">呼吸暂停</option>
            <option value="snore">只看呼噜</option>
            <option value="environment">只看环境</option>
            <option value="device">只看设备</option>
          </select>
        </div>
        <div class="event-list">
          <div v-if="filteredEvents.length === 0" class="empty-state">
            暂无事件
          </div>
          <div
            v-for="event in filteredEvents"
            :key="`${event.eventID}-${event.timestamp}`"
            class="event-item"
            :class="[event.severity, { resolved: event.status === 'resolved' }]"
          >
            <div class="event-dot"></div>
            <div>
              <div class="event-meta">{{ formatTime(event.timestamp) }} · {{ sourceLabel(event.source) }}</div>
              <div class="event-title">
                {{ event.title }}
                <span v-if="event.status === 'resolved'" class="resolved-badge">已处理</span>
              </div>
              <div class="event-message">{{ event.message }}</div>
              <div v-if="event.status === 'resolved'" class="event-resolution">
                {{ event.resolved_by || '看护人员' }}：{{ event.resolution_note || '已确认并解除紧急状态' }}
              </div>
            </div>
          </div>
        </div>
      </section>

      <section class="heat-card care-glass-card">
        <div class="section-header">
          <div>
            <div class="section-title">呼噜影响时间轴</div>
            <p class="section-subtitle">每个格子代表一个时间段；颜色越深，说明呼噜越明显或伴随生命体征波动越大。</p>
          </div>
        </div>
        <div class="heat-legend" aria-label="呼噜影响程度图例">
          <span><i class="normal"></i>轻微</span>
          <span><i class="warning"></i>需关注</span>
          <span><i class="critical"></i>明显影响</span>
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
            <strong>{{ heatPercent(cell) }}%</strong>
            <small>{{ heatEvents(cell) }}</small>
          </div>
          <div v-if="heatmap.length === 0" class="empty-state wide">
            暂无呼噜片段。若开发板在线但这里为空，表示当前时间范围内没有确认呼噜事件。
          </div>
        </div>
        <div v-if="heatmap.length" class="heat-summary">
          {{ heatSummary }}
        </div>
      </section>
    </div>

    <div class="stability-grid">
      <div v-for="card in stabilityCards" :key="card.key" class="stability-card care-glass-card care-icon-card" :data-icon="stabilityIcon(card)">
        <div class="mini-title">{{ card.title }}</div>
        <div class="mini-value">{{ card.value }}<span>{{ card.unit }}</span></div>
        <div class="mini-bar"><i :style="{ width: `${card.value}%` }"></i></div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import request from '@/utils/request'
import { useUserStore } from '@/stores/userStore'
import { useBedStore } from '@/stores/bedStore'

const userStore = useUserStore()
const bedStore = useBedStore()

const mode = ref('live')
const seconds = ref(1800)
const date = ref(localDate())
const loading = ref(false)
const eventFilter = ref('all')
const refreshTimer = ref(null)

const overview = reactive({
  score: { score: 0, label: '等待数据', summary: '等待真实开发板上线。', penalties: [] },
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

const stabilityIcon = card => {
  const key = String(card?.key || card?.title || '').toLowerCase()
  if (key.includes('heart') || key.includes('心')) return 'HR'
  if (key.includes('breath') || key.includes('呼')) return 'BR'
  if (key.includes('snore') || key.includes('鼾')) return 'SN'
  if (key.includes('env') || key.includes('温') || key.includes('湿')) return 'ENV'
  return 'OK'
}
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

const heatSummary = computed(() => {
  const cells = heatmap.value || []
  if (!cells.length) return ''
  const critical = cells.filter(cell => cell.severity === 'critical').length
  const warning = cells.filter(cell => cell.severity === 'warning').length
  const snoreEvents = cells.reduce((sum, cell) => sum + Number(cell.snore_events || 0), 0)
  if (critical > 0) {
    return `结论：发现 ${critical} 个明显影响时段，建议优先查看红色格子对应的事件记录。`
  }
  if (warning > 0) {
    return `结论：发现 ${warning} 个需关注时段，共 ${snoreEvents} 次呼噜相关事件，建议结合呼吸暂停事件判断。`
  }
  return `结论：当前时间范围内呼噜影响较轻，共 ${snoreEvents} 次呼噜相关记录。`
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
  if (eventFilter.value === 'apnea') {
    return events.filter(event => event.type === 'suspected_apnea')
  }
  if (eventFilter.value === 'environment') {
    return events.filter(event => event.type === 'environment' || event.source === 'environment_board')
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
      ? { mode: 'history', date: date.value, userID: userID(), bed_id: bedStore.selectedBedId }
      : { mode: 'live', seconds: seconds.value, bed_id: bedStore.selectedBedId }
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
        ? '检测到 8081 端口有服务，但缺少 /sleep/overview 接口。\n请停止当前后端，改启动：python backend\\realtime_radar_processing.py\n（不要启动 realtime_radar_processing.py 或 mock_server.py）'
        : !error.response
        ? '无法连接 8081 端口后端服务。\n请先在项目根目录执行：conda activate radar && python backend\\realtime_radar_processing.py'
        : '请先启动后端：python backend\\realtime_radar_processing.py'
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

function formatTime(value) {
  if (!value) return '--:--'
  const dateValue = new Date(value)
  if (Number.isNaN(dateValue.getTime())) return value
  return dateValue.toLocaleTimeString('zh-CN', { hour12: false })
}

function sourceLabel(source) {
  const map = {
    radar_board: '雷达板',
    snore_board: 'Edgi E84',
    environment_board: 'Edgi E84',
    radar_snore_fusion: '雷达+呼噜融合',
    xiaozhi_voice_board: '小智语音板',
    backend_api: '真实后端服务'
  }
  return map[source] || source || '系统'
}

function heatTooltip(cell) {
  const snore = Math.round((cell.avg_snore_level || 0) * 100)
  const heart = cell.heart_delta === null || cell.heart_delta === undefined ? '--' : `${cell.heart_delta >= 0 ? '+' : ''}${cell.heart_delta} BPM`
  const breath = cell.breath_delta === null || cell.breath_delta === undefined ? '--' : `${cell.breath_delta >= 0 ? '+' : ''}${cell.breath_delta} RPM`
  return `${cell.label}：${severityText(cell)}；呼噜强度 ${snore}%；事件 ${cell.snore_events || 0}；心率变化 ${heart}；呼吸变化 ${breath}`
}

function heatPercent(cell) {
  return Math.round(((cell?.intensity ?? cell?.avg_snore_level) || 0) * 100)
}

function heatEvents(cell) {
  const count = Number(cell?.snore_events || 0)
  return count > 0 ? `${count}次` : '无事件'
}

function severityText(cell) {
  if (cell?.severity === 'critical') return '明显影响'
  if (cell?.severity === 'warning') return '需关注'
  return '轻微'
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
  padding: 14px;
  color: var(--care-text);
}

.hero-panel {
  display: flex;
  justify-content: space-between;
  gap: 14px;
  align-items: center;
  border-radius: 12px;
  padding: 12px 16px;
  margin-bottom: 10px;
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
  font-size: 25px;
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
  gap: 6px;
}

.control-strip button,
.control-strip select,
.control-strip input,
.dark-select {
  border: 1px solid var(--care-border);
  border-radius: 999px;
  color: var(--care-text);
  background: var(--care-surface-strong);
  min-height: 36px;
  padding: 6px 11px;
  font-size: 14px;
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

.dashboard-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.12fr) minmax(310px, 0.88fr);
  grid-template-rows: 184px 246px;
  gap: 10px;
}

.dashboard-grid > .care-glass-card {
  min-width: 0;
  border-radius: 12px;
  padding: 14px;
}

.neon-card {
  border-radius: 22px;
  padding: 20px;
}

.score-card {
  min-height: 0;
  overflow: hidden;
}

.section-title {
  color: var(--care-text-strong);
  font-weight: 800;
  letter-spacing: 0.04em;
  font-size: 16px;
}

.section-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  margin-bottom: 8px;
}

.section-subtitle {
  color: var(--care-muted);
  margin: 8px 0 0;
  font-size: 13px;
}

.score-layout {
  display: grid;
  grid-template-columns: 140px minmax(0, 1fr);
  gap: 18px;
  align-items: center;
  margin-top: 8px;
}

.score-ring {
  width: 126px;
  height: 126px;
  border-radius: 50%;
  display: grid;
  place-items: center;
}

.score-core {
  width: 90px;
  height: 90px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: radial-gradient(circle, var(--care-surface-strong), var(--care-surface));
  border: 1px solid var(--care-border);
  color: var(--care-text-strong);
}

.score-core strong {
  font-size: 38px;
  line-height: 1;
}

.score-core span {
  margin-top: -18px;
  font-size: 12px;
  color: var(--care-muted);
}

.score-text h2 {
  font-size: 24px;
  margin: 0 0 4px;
  color: var(--care-text-strong);
}

.score-text p {
  color: var(--care-muted-strong);
  line-height: 1.45;
  font-size: 13px;
  margin: 0;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.penalty-list {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: 8px;
}

.penalty-tag,
.good-tag {
  border-radius: 999px;
  padding: 3px 7px;
  font-size: 11px;
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
  max-height: none;
  overflow: hidden;
}

.event-list {
  height: calc(100% - 38px);
  overflow: auto;
  padding-right: 4px;
}

.event-item {
  display: grid;
  grid-template-columns: 12px minmax(0, 1fr);
  gap: 8px;
  padding: 8px 0;
  border-bottom: 1px solid var(--care-divider);
}

.event-dot {
  width: 8px;
  height: 8px;
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

.event-item.resolved {
  opacity: 0.72;
}

.event-item.resolved .event-dot {
  background: var(--care-success);
  box-shadow: none;
}

.event-meta {
  color: var(--care-muted);
  font-size: 11px;
}

.event-title {
  font-weight: 800;
  margin: 2px 0;
  color: var(--care-text-strong);
  font-size: 14px;
}

.event-message {
  color: var(--care-muted-strong);
  font-size: 12px;
  line-height: 1.4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.resolved-badge {
  display: inline-block;
  margin-left: 8px;
  padding: 2px 7px;
  border: 1px solid var(--care-success);
  border-radius: 4px;
  color: var(--care-success);
  font-size: 11px;
  font-weight: 800;
  vertical-align: 2px;
}

.event-resolution {
  margin-top: 3px;
  color: var(--care-success);
  font-size: 11px;
  line-height: 1.35;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.heat-card {
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.worst-box {
  text-align: right;
  color: var(--care-muted);
  font-size: 12px;
  flex: 0 0 auto;
}

.worst-box strong {
  display: block;
  margin-top: 3px;
  color: var(--care-warning);
  font-size: 15px;
}

.heat-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 2px 0 7px;
  color: var(--care-muted);
  font-size: 11px;
}

.heat-legend span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 7px;
  border: 1px solid var(--care-border-soft);
  border-radius: 999px;
  background: var(--care-surface-2);
}

.heat-legend i {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: #38bdf8;
}

.heat-legend i.warning {
  background: #a855f7;
}

.heat-legend i.critical {
  background: #ef4444;
}

.heatmap {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(70px, 1fr));
  gap: 6px;
  margin-top: 0;
  max-height: 132px;
  overflow: auto;
  padding-right: 2px;
}

.heat-cell {
  min-height: 58px;
  border-radius: 10px;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  justify-content: space-between;
  padding: 7px;
  font-size: 11px;
  color: var(--care-text-strong);
  background: linear-gradient(180deg, rgba(56, 189, 248, calc(.18 + var(--level) * .3)), var(--care-surface-2));
  border: 1px solid var(--care-border-soft);
  transition: background 0.2s ease, border-color 0.2s ease;
}

.heat-cell span {
  color: var(--care-muted);
  font-size: 10px;
  line-height: 1;
}

.heat-cell strong {
  color: var(--care-text-strong);
  font-size: 18px;
  line-height: 1;
}

.heat-cell small {
  color: var(--care-muted-strong);
  font-size: 10px;
  line-height: 1;
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

.heat-summary {
  margin-top: 7px;
  padding: 7px 9px;
  border: 1px solid var(--care-border-soft);
  border-radius: 10px;
  color: var(--care-muted-strong);
  background: var(--care-surface-2);
  font-size: 12px;
  line-height: 1.45;
}

.stability-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-top: 10px;
}

.stability-card {
  border-radius: 12px;
  padding: 8px 12px;
  display: grid;
  grid-template-columns: minmax(100px, 1fr) auto;
  grid-template-areas:
    "title value"
    "bar bar";
  align-items: center;
  column-gap: 12px;
}

.mini-title {
  grid-area: title;
  color: var(--care-muted);
  font-size: 13px;
}

.mini-value {
  grid-area: value;
  font-size: 21px;
  font-weight: 900;
  margin: 0;
  color: var(--care-text-strong);
}

.mini-value span {
  color: var(--care-muted);
  font-size: 14px;
  margin-left: 3px;
}

.mini-bar {
  grid-area: bar;
  height: 5px;
  margin-top: 6px;
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
  line-height: 1.5;
  padding: 14px 0;
}

.empty-state.wide {
  grid-column: 1 / -1;
}

@media (max-width: 1040px) {
  .hero-panel {
    align-items: flex-start;
  }

  .control-strip {
    justify-content: flex-start;
    margin-top: 10px;
  }

  .dashboard-grid {
    grid-template-columns: 1fr;
    grid-template-rows: auto;
  }

  .score-card,
  .heat-card {
    min-height: 210px;
  }

  .event-card {
    grid-row: auto;
    height: 320px;
  }

  .stability-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 680px) {
  .sleep-page {
    padding: 10px;
  }

  .hero-panel {
    display: block;
  }

  .score-layout {
    grid-template-columns: 112px minmax(0, 1fr);
    gap: 12px;
  }

  .score-ring {
    width: 108px;
    height: 108px;
  }

  .score-core {
    width: 78px;
    height: 78px;
  }

  .score-core strong {
    font-size: 30px;
  }

  .stability-grid {
    grid-template-columns: 1fr;
  }
}
</style>
