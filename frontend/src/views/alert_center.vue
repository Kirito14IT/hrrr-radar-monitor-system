<template>
  <div class="alert-workspace care-page-shell">
    <section class="alert-hero">
      <div class="risk-card care-glass-card" :class="overallRisk.level">
        <div class="care-kicker">Care Alert Center</div>
        <h1>看护预警中心</h1>
        <p>基于实时生命体征、呼噜扰动、设备心跳和睡眠事件，生成夜间看护的异常归因与动作队列。</p>
        <div class="risk-summary">
          <span>{{ overallRisk.label }}</span>
          <strong>{{ overallRisk.score }}</strong>
          <small>{{ overallRisk.reason }}</small>
        </div>
      </div>

      <div class="status-stack">
        <div class="status-card care-glass-card" :class="{ online: status.radar_board_online }">
          <span>雷达板</span>
          <strong>{{ status.radar_board_online ? '在线' : '离线' }}</strong>
          <small>{{ formatAge(status.radar_age_seconds) }}</small>
        </div>
        <div class="status-card care-glass-card" :class="{ online: status.snore_board_online }">
          <span>呼噜板</span>
          <strong>{{ status.snore_board_online ? '在线' : '离线' }}</strong>
          <small>{{ formatAge(status.snore_age_seconds) }}</small>
        </div>
        <div class="status-card care-glass-card">
          <span>音频片段</span>
          <strong>{{ status.audio_upload_count ?? 0 }}</strong>
          <small>{{ status.snore_detected ? '最近检测到呼噜' : '暂无呼噜事件' }}</small>
        </div>
      </div>
    </section>

    <section class="control-row care-glass-card">
      <div>
        <strong>实时策略窗口</strong>
        <span>最近 30 分钟 · {{ overview.stats?.points || timelineRows.length }} 个数据点</span>
      </div>
      <div class="control-actions">
        <el-button type="primary" :loading="loading" @click="loadData">刷新</el-button>
        <el-button @click="policy.clearAcknowledged">恢复已处理动作</el-button>
      </div>
      <p v-if="error" class="inline-error">{{ error }}</p>
    </section>

    <section class="alert-grid">
      <article class="matrix-card care-glass-card">
        <div class="section-title">
          <div>
            <h2>异常归因矩阵</h2>
            <p>状态徽标、颜色和文字同时表达风险，避免只依赖颜色判断。</p>
          </div>
        </div>
        <div class="matrix-list">
          <div v-for="item in riskItems" :key="item.key" class="matrix-item" :class="item.level">
            <div class="matrix-icon" aria-hidden="true">{{ item.icon }}</div>
            <div>
              <strong>{{ item.title }}</strong>
              <span>{{ item.status }}</span>
              <small>{{ item.detail }}</small>
            </div>
          </div>
        </div>
      </article>

      <article class="actions-card care-glass-card">
        <div class="section-title">
          <div>
            <h2>照护动作队列</h2>
            <p>按风险优先级生成当前最值得执行的检查项。</p>
          </div>
          <el-tag :type="activeActions.length ? 'warning' : 'success'">
            {{ activeActions.length ? `${activeActions.length} 项待处理` : '无待处理' }}
          </el-tag>
        </div>

        <div v-if="activeActions.length === 0" class="empty-actions">
          当前没有待处理动作。若需要重新查看已处理事项，请点击“恢复已处理动作”。
        </div>
        <div v-else class="action-list">
          <div v-for="action in activeActions" :key="action.key" class="action-item" :class="action.level">
            <div>
              <strong>{{ action.title }}</strong>
              <p>{{ action.detail }}</p>
            </div>
            <el-button size="small" @click="policy.acknowledge(action.key)">标记已处理</el-button>
          </div>
        </div>
      </article>

      <article class="policy-card care-glass-card">
        <div class="section-title">
          <div>
            <h2>阈值策略</h2>
            <p>本地持久化，刷新页面后仍保留。</p>
          </div>
          <el-button size="small" @click="policy.resetPolicy">恢复默认</el-button>
        </div>

        <div class="policy-grid">
          <label>
            心率下限
            <el-input-number v-model="policy.heartLow" :min="35" :max="90" />
          </label>
          <label>
            心率上限
            <el-input-number v-model="policy.heartHigh" :min="70" :max="150" />
          </label>
          <label>
            呼吸下限
            <el-input-number v-model="policy.breathLow" :min="4" :max="18" />
          </label>
          <label>
            呼吸上限
            <el-input-number v-model="policy.breathHigh" :min="16" :max="40" />
          </label>
          <label>
            呼噜阈值 %
            <el-input-number v-model="policy.snoreThreshold" :min="5" :max="100" />
          </label>
          <label>
            离线秒数
            <el-input-number v-model="policy.offlineSeconds" :min="3" :max="60" />
          </label>
        </div>
      </article>

      <article class="trend-card care-glass-card">
        <div class="section-title">
          <div>
            <h2>趋势小窗</h2>
            <p>{{ chartSummary }}</p>
          </div>
        </div>
        <div ref="trendChartEl" class="trend-chart" role="img" :aria-label="chartSummary"></div>
      </article>
    </section>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import * as echarts from 'echarts'
import request from '@/utils/request'
import { useAlertPolicyStore } from '@/stores/alertPolicyStore'
import { useThemeStore } from '@/stores/themeStore'

const policy = useAlertPolicyStore()
const themeStore = useThemeStore()

const loading = ref(false)
const error = ref('')
const overview = reactive({
  stats: {},
  score: {},
  events: [],
  devices: {}
})
const timelineRows = ref([])
const status = reactive({
  radar_board_online: false,
  snore_board_online: false,
  radar_age_seconds: null,
  snore_age_seconds: null,
  audio_upload_count: 0,
  snore_detected: false
})

const trendChartEl = ref(null)
let trendChart = null
let refreshTimer = null

const latestRow = computed(() => timelineRows.value[timelineRows.value.length - 1] || {})

const latestHeart = computed(() => numberOrNull(latestRow.value.heart_rate))
const latestBreath = computed(() => numberOrNull(latestRow.value.breath_rate))
const latestSnore = computed(() => {
  const level = numberOrNull(latestRow.value.snore_level)
  if (level !== null) return Math.round(level * 100)
  const score = numberOrNull(latestRow.value.snore_score)
  return score === null ? null : Math.round(score * 100)
})

const eventPressure = computed(() => {
  const events = overview.events || []
  return {
    critical: events.filter(event => event.severity === 'critical').length,
    warning: events.filter(event => event.severity === 'warning').length
  }
})

const riskItems = computed(() => {
  const heart = buildHeartRisk()
  const breath = buildBreathRisk()
  const snore = buildSnoreRisk()
  const presence = buildPresenceRisk()
  const devices = buildDeviceRisk()
  return [heart, breath, snore, presence, devices]
})

const overallRisk = computed(() => {
  const score = riskItems.value.reduce((sum, item) => sum + riskWeight(item.level), 0) +
    Math.min(16, eventPressure.value.critical * 4 + eventPressure.value.warning * 2)
  const maxLevel = riskItems.value.some(item => item.level === 'critical')
    ? 'critical'
    : riskItems.value.some(item => item.level === 'warning')
      ? 'warning'
      : 'normal'
  if (maxLevel === 'critical') {
    return {
      level: 'critical',
      label: '立即关注',
      score: Math.min(100, score + 40),
      reason: '存在设备离线、离床或生命体征越界风险。'
    }
  }
  if (maxLevel === 'warning') {
    return {
      level: 'warning',
      label: '继续观察',
      score: Math.min(100, score + 20),
      reason: '出现呼噜扰动或轻度生命体征波动。'
    }
  }
  return {
    level: 'normal',
    label: '稳定',
    score: Math.max(0, score),
    reason: '当前窗口内未见明显看护风险。'
  }
})

const actionQueue = computed(() => riskItems.value
  .filter(item => item.level !== 'normal')
  .sort((a, b) => riskWeight(b.level) - riskWeight(a.level))
  .map(item => ({
    key: `${item.key}:${item.level}`,
    level: item.level,
    title: item.actionTitle,
    detail: item.actionDetail
  })))

const activeActions = computed(() => actionQueue.value.filter(action => !policy.acknowledgedKeys.includes(action.key)))

const chartSummary = computed(() => {
  if (timelineRows.value.length === 0) return '暂无趋势数据，请确认模拟后端或开发板已启动。'
  const heart = latestHeart.value === null ? '心率无数据' : `心率 ${latestHeart.value.toFixed(1)} BPM`
  const breath = latestBreath.value === null ? '呼吸无数据' : `呼吸 ${latestBreath.value.toFixed(1)} RPM`
  const snore = latestSnore.value === null ? '呼噜无数据' : `呼噜强度 ${latestSnore.value}%`
  return `最新状态：${heart}，${breath}，${snore}。`
})

function numberOrNull(value) {
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function riskWeight(level) {
  if (level === 'critical') return 24
  if (level === 'warning') return 10
  return 0
}

function formatAge(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '暂无心跳'
  if (number < 1) return '刚刚'
  return `${number.toFixed(1)} 秒前`
}

function buildHeartRisk() {
  const value = latestHeart.value
  if (value === null) {
    return risk('heart', '心率', 'warning', '暂无心率', '雷达心率暂未形成有效数据。', '检查雷达距离与目标存在', '确认目标位于雷达有效距离内，并观察实时生命体征页是否恢复心率。', 'HR')
  }
  if (value < policy.heartLow || value > policy.heartHigh) {
    return risk('heart', '心率', 'critical', `${value.toFixed(1)} BPM`, `超出策略范围 ${policy.heartLow}-${policy.heartHigh} BPM。`, '复核心率异常', '检查雷达采样是否稳定；如接入真实对象，请结合人工观察判断。', 'HR')
  }
  return risk('heart', '心率', 'normal', `${value.toFixed(1)} BPM`, '处于当前策略范围。', '无需处理', '心率稳定。', 'HR')
}

function buildBreathRisk() {
  const value = latestBreath.value
  if (value === null) {
    return risk('breath', '呼吸', 'warning', '暂无呼吸率', '雷达呼吸率暂未形成有效数据。', '观察呼吸波形恢复', '确认雷达板在线，并检查实时呼吸曲线是否恢复。', 'BR')
  }
  if (value < policy.breathLow || value > policy.breathHigh) {
    return risk('breath', '呼吸', 'critical', `${value.toFixed(1)} RPM`, `超出策略范围 ${policy.breathLow}-${policy.breathHigh} RPM。`, '复核呼吸异常', '优先查看呼吸趋势是否连续越界，排除无人或距离异常。', 'BR')
  }
  return risk('breath', '呼吸', 'normal', `${value.toFixed(1)} RPM`, '处于当前策略范围。', '无需处理', '呼吸稳定。', 'BR')
}

function buildSnoreRisk() {
  const snoreValue = latestSnore.value
  const hasSnoreEvent = Boolean(status.snore_detected)
  if (snoreValue === null) {
    return risk('snore', '呼噜', 'warning', '暂无呼噜特征', '呼噜板尚未提供有效特征。', '确认呼噜板在线', '检查呼噜检测模拟板是否在持续发送 heartbeat。', 'SN')
  }
  if (snoreValue >= policy.snoreThreshold || hasSnoreEvent) {
    return risk('snore', '呼噜', 'warning', `${snoreValue}%`, `达到策略阈值 ${policy.snoreThreshold}% 或最近检测到呼噜。`, '观察呼噜扰动', '查看驾驶舱呼噜扰动地图，确认是否伴随心率/呼吸波动。', 'SN')
  }
  return risk('snore', '呼噜', 'normal', `${snoreValue}%`, '低于当前呼噜阈值。', '无需处理', '呼噜扰动较低。', 'SN')
}

function buildPresenceRisk() {
  const row = latestRow.value
  if (timelineRows.value.length === 0) {
    return risk('presence', '离床/无人', 'warning', '等待数据', '尚未获取到雷达目标距离。', '等待目标数据', '确认模拟后端和雷达板已启动，稍后刷新预警中心。', 'PR')
  }
  if (row.radar_online === false || row.target_distance === 0 || row.target_distance === null) {
    return risk('presence', '离床/无人', 'critical', '疑似无人', '雷达在线状态或目标距离显示疑似离床。', '确认床旁状态', '检查雷达视场、目标距离和是否存在离床情况。', 'PR')
  }
  const distance = numberOrNull(row.target_distance)
  return risk('presence', '离床/无人', 'normal', distance === null ? '等待距离' : `${distance.toFixed(2)} m`, '目标存在状态正常。', '无需处理', '目标距离稳定。', 'PR')
}

function buildDeviceRisk() {
  const radarOffline = !status.radar_board_online || Number(status.radar_age_seconds) > policy.offlineSeconds
  const snoreOffline = !status.snore_board_online || Number(status.snore_age_seconds) > policy.offlineSeconds
  if (radarOffline || snoreOffline) {
    return risk('device', '设备链路', 'critical', '存在离线', `离线判定阈值 ${policy.offlineSeconds} 秒。`, '恢复设备链路', '检查雷达板和呼噜板终端是否仍在运行，必要时重启模拟发送器。', 'DV')
  }
  return risk('device', '设备链路', 'normal', '双板在线', '雷达板与呼噜板心跳正常。', '无需处理', '设备链路稳定。', 'DV')
}

function risk(key, title, level, statusText, detail, actionTitle, actionDetail, icon) {
  return {
    key,
    title,
    level,
    status: statusText,
    detail,
    actionTitle,
    actionDetail,
    icon
  }
}

async function loadData() {
  loading.value = true
  error.value = ''
  try {
    const [overviewResult, timelineResult, statusResult] = await Promise.allSettled([
      request.get('/sleep/overview', { params: { mode: 'live', seconds: 1800 } }),
      request.get('/timeline', { params: { seconds: 1800 } }),
      request.get('/status')
    ])

    if (overviewResult.status === 'fulfilled') {
      Object.assign(overview, {
        stats: overviewResult.value.stats || {},
        score: overviewResult.value.score || {},
        events: overviewResult.value.events || [],
        devices: overviewResult.value.devices || {}
      })
    }
    if (timelineResult.status === 'fulfilled') {
      timelineRows.value = timelineResult.value.data || []
    }
    if (statusResult.status === 'fulfilled') {
      Object.assign(status, statusResult.value || {})
    }

    if ([overviewResult, timelineResult, statusResult].some(result => result.status === 'rejected')) {
      error.value = '部分数据接口暂时不可用，页面已显示可用数据。'
    }
  } catch (err) {
    console.error('预警中心数据加载失败:', err)
    error.value = '看护预警中心无法连接模拟后端，请先启动 backend/mock_hardware_api.py。'
  } finally {
    loading.value = false
    await nextTick()
    renderChart()
  }
}

function renderChart() {
  if (!trendChartEl.value) return
  if (!trendChart) {
    trendChart = echarts.init(trendChartEl.value)
  }
  const rows = timelineRows.value
  const labels = rows.map(row => formatTimeLabel(row.timestamp))
  const muted = readToken('--care-muted', '#64748b')
  const grid = readToken('--care-grid-line-soft', 'rgba(100,116,139,.14)')
  const strongText = readToken('--care-muted-strong', '#41576b')
  trendChart.setOption({
    backgroundColor: 'transparent',
    color: ['#ef4444', '#38bdf8', '#f59e0b'],
    tooltip: { trigger: 'axis' },
    legend: {
      top: 0,
      textStyle: { color: strongText },
      data: ['心率', '呼吸率', '呼噜强度']
    },
    grid: { left: 42, right: 24, top: 42, bottom: 34 },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: labels,
      axisLabel: { color: muted }
    },
    yAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: grid } },
      axisLabel: { color: muted }
    },
    series: [
      {
        name: '心率',
        type: 'line',
        smooth: true,
        showSymbol: false,
        connectNulls: false,
        data: rows.map(row => row.radar_online ? numberOrNull(row.heart_rate) : null)
      },
      {
        name: '呼吸率',
        type: 'line',
        smooth: true,
        showSymbol: false,
        connectNulls: false,
        data: rows.map(row => row.radar_online ? numberOrNull(row.breath_rate) : null)
      },
      {
        name: '呼噜强度',
        type: 'line',
        smooth: true,
        showSymbol: false,
        connectNulls: false,
        data: rows.map(row => {
          const level = numberOrNull(row.snore_level)
          return level === null ? null : Math.round(level * 100)
        })
      }
    ]
  })
}

function readToken(name, fallback) {
  if (typeof window === 'undefined') return fallback
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

function formatTimeLabel(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
}

function resizeChart() {
  trendChart?.resize()
}

watch(timelineRows, () => nextTick(renderChart))
watch(() => themeStore.mode, () => nextTick(renderChart))

onMounted(() => {
  loadData()
  refreshTimer = window.setInterval(loadData, 5000)
  window.addEventListener('resize', resizeChart)
})

onBeforeUnmount(() => {
  if (refreshTimer) window.clearInterval(refreshTimer)
  window.removeEventListener('resize', resizeChart)
  trendChart?.dispose()
})
</script>

<style scoped>
.alert-workspace {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.alert-hero {
  display: grid;
  grid-template-columns: minmax(460px, 1fr) minmax(300px, 0.55fr);
  gap: 18px;
}

.risk-card {
  position: relative;
  padding: 28px;
  overflow: hidden;
}

.risk-card::after {
  content: "";
  position: absolute;
  right: -60px;
  top: -70px;
  width: 240px;
  height: 240px;
  border-radius: 50%;
  background: var(--care-primary-soft);
}

.risk-card.warning::after {
  background: var(--care-warning-soft);
}

.risk-card.critical::after {
  background: var(--care-danger-soft);
}

.risk-card h1 {
  margin: 10px 0;
  font-size: 36px;
}

.risk-card p {
  max-width: 720px;
  color: var(--care-muted);
  line-height: 1.7;
}

.risk-summary {
  display: grid;
  width: fit-content;
  min-width: 210px;
  margin-top: 22px;
  padding: 16px;
  border-radius: 18px;
  background: var(--care-surface-2);
  border: 1px solid var(--care-border-soft);
}

.risk-summary span {
  color: var(--care-muted);
  font-weight: 800;
}

.risk-summary strong {
  font-size: 46px;
  line-height: 1;
  color: var(--care-primary-strong);
}

.risk-card.warning .risk-summary strong {
  color: var(--care-warning);
}

.risk-card.critical .risk-summary strong {
  color: var(--care-danger);
}

.risk-summary small,
.status-card small,
.section-title p,
.matrix-item small,
.action-item p,
.control-row span {
  color: var(--care-muted);
  line-height: 1.55;
}

.status-stack {
  display: grid;
  gap: 12px;
}

.status-card {
  padding: 18px;
  border-left: 5px solid var(--care-warning);
}

.status-card.online {
  border-left-color: var(--care-success);
}

.status-card span {
  color: var(--care-muted);
  font-size: 13px;
}

.status-card strong {
  display: block;
  margin: 6px 0;
  font-size: 24px;
}

.control-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 16px 18px;
  flex-wrap: wrap;
}

.control-row > div:first-child {
  display: grid;
  gap: 4px;
}

.control-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.inline-error {
  flex-basis: 100%;
  margin: 0;
  color: var(--care-danger);
}

.alert-grid {
  display: grid;
  grid-template-columns: minmax(360px, 0.9fr) minmax(360px, 1fr);
  gap: 18px;
}

.matrix-card,
.actions-card,
.policy-card,
.trend-card {
  padding: 20px;
}

.section-title {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}

.section-title h2 {
  margin: 0 0 6px;
  font-size: 22px;
}

.matrix-list {
  display: grid;
  gap: 12px;
}

.matrix-item {
  display: grid;
  grid-template-columns: 48px 1fr;
  gap: 12px;
  align-items: center;
  padding: 14px;
  border-radius: 18px;
  border: 1px solid var(--care-border-soft);
  background: var(--care-surface-soft);
}

.matrix-item.warning {
  border-color: var(--care-warning);
  background: var(--care-warning-soft);
}

.matrix-item.critical {
  border-color: var(--care-danger);
  background: var(--care-danger-soft);
}

.matrix-icon {
  width: 48px;
  height: 48px;
  display: grid;
  place-items: center;
  border-radius: 16px;
  color: var(--care-link);
  background: var(--care-accent-soft);
  font-weight: 900;
}

.matrix-item.warning .matrix-icon {
  color: var(--care-warning);
  background: var(--care-warning-soft);
}

.matrix-item.critical .matrix-icon {
  color: var(--care-danger);
  background: var(--care-danger-soft);
}

.matrix-item strong,
.matrix-item span {
  display: block;
}

.matrix-item span {
  margin: 3px 0;
  font-weight: 800;
}

.action-list {
  display: grid;
  gap: 12px;
}

.action-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 14px;
  border-radius: 18px;
  background: var(--care-surface-2);
  border: 1px solid var(--care-border-soft);
}

.action-item.warning {
  border-color: var(--care-warning);
}

.action-item.critical {
  border-color: var(--care-danger);
}

.action-item p {
  margin: 5px 0 0;
}

.empty-actions {
  padding: 28px;
  border-radius: 18px;
  color: var(--care-muted);
  background: var(--care-primary-soft);
  border: 1px dashed var(--care-primary-border);
}

.policy-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(150px, 1fr));
  gap: 14px;
}

.policy-grid label {
  display: grid;
  gap: 8px;
  color: var(--care-muted);
  font-size: 13px;
  font-weight: 800;
}

.trend-card {
  min-height: 360px;
}

.trend-chart {
  width: 100%;
  height: 280px;
}

@media (max-width: 1180px) {
  .alert-hero,
  .alert-grid,
  .policy-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .alert-workspace {
    padding: 16px;
  }

  .control-row,
  .action-item {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
