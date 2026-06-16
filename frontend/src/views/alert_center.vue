<template>
  <div class="alert-workspace care-page-shell">
    <section class="alert-hero">
      <div class="risk-card care-glass-card" :class="overallRisk.level">
        <h1>看护预警中心</h1>
        <div class="risk-summary">
          <span>{{ overallRisk.label }}</span>
          <strong>{{ overallRisk.score }}</strong>
        </div>
      </div>

      <div class="status-stack">
        <div class="status-card care-glass-card" :class="{ online: status.radar_board_online }">
          <span>雷达板</span>
          <strong>{{ status.radar_board_online ? '在线' : '离线' }}</strong>
        </div>
        <div class="status-card care-glass-card" :class="{ online: edgiBoardOnline, warning: edgiBoardNeedsAttention }">
          <span>Edgi E84</span>
          <strong>{{ edgiStatusText }}</strong>
        </div>
        <div class="status-card care-glass-card">
          <span>音频片段</span>
          <strong>{{ status.audio_upload_count ?? 0 }}</strong>
        </div>
      </div>
    </section>

    <section
      v-if="latestEmergencyEvent"
      class="emergency-workspace"
      aria-live="assertive"
    >
      <div class="emergency-heading">
        <div class="sos-mark">SOS</div>
        <div>
          <span>待处理紧急事件</span>
          <h2>请立即确认床旁情况</h2>
          <p>{{ emergencyPhrase }}</p>
        </div>
        <el-tag type="danger" effect="dark">最高优先级</el-tag>
      </div>

      <div class="emergency-meta">
        <div>
          <span>触发时间</span>
          <strong>{{ formatDateTime(latestEmergencyEvent.timestamp) }}</strong>
        </div>
        <div>
          <span>触发话术</span>
          <strong>{{ emergencyPhrase }}</strong>
        </div>
        <div>
          <span>事件来源</span>
          <strong>小智语音开发板</strong>
        </div>
      </div>

      <div class="emergency-process">
        <div class="response-steps">
          <strong>处理顺序</strong>
          <ol>
            <li>确认床旁情况</li>
            <li>检查呼吸与意识</li>
            <li>必要时联系急救</li>
          </ol>
        </div>
        <div class="resolution-form">
          <label>
            处理人
            <el-input v-model="resolvedBy" maxlength="30" placeholder="例如：夜班看护员" />
          </label>
          <label>
            处理说明
            <el-input
              v-model="resolutionNote"
              type="textarea"
              :rows="3"
              maxlength="160"
              show-word-limit
              placeholder="记录现场确认结果和采取的措施"
            />
          </label>
          <el-button
            type="danger"
            size="large"
            :loading="handlingEmergency"
            @click="resolveEmergency"
          >
            确认已处理并解除紧急状态
          </el-button>
        </div>
      </div>
    </section>

    <section class="control-row care-glass-card">
      <div>
        <strong>实时策略窗口</strong>
        <span>30 分钟 · {{ overview.stats?.points || timelineRows.length }} 点</span>
      </div>
      <div class="control-actions">
        <el-button type="primary" :loading="loading" @click="loadData">刷新</el-button>
        <el-button @click="policyVisible = !policyVisible">
          {{ policyVisible ? '收起阈值' : '阈值设置' }}
        </el-button>
        <el-button @click="policy.clearAcknowledged">恢复已处理动作</el-button>
      </div>
      <p v-if="error" class="inline-error">{{ error }}</p>
    </section>

    <section class="alert-grid">
      <article class="matrix-card care-glass-card">
        <div class="section-title">
          <div>
            <h2>异常归因矩阵</h2>
          </div>
        </div>
        <div class="matrix-list">
          <div v-for="item in riskItems" :key="item.key" class="matrix-item" :class="item.level">
            <div class="matrix-icon" aria-hidden="true">{{ item.icon }}</div>
            <div>
              <strong>{{ item.title }}</strong>
              <span>{{ item.status }}</span>
            </div>
          </div>
        </div>
      </article>

      <article class="actions-card care-glass-card">
        <div class="section-title">
          <div>
            <h2>照护动作队列</h2>
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
            </div>
            <el-button size="small" @click="policy.acknowledge(action.key)">标记已处理</el-button>
          </div>
        </div>
      </article>

      <article v-if="policyVisible" class="policy-card care-glass-card">
        <div class="section-title">
          <div>
            <h2>阈值策略</h2>
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
            温度下限 C
            <el-input-number v-model="policy.temperatureLow" :min="10" :max="25" />
          </label>
          <label>
            温度上限 C
            <el-input-number v-model="policy.temperatureHigh" :min="22" :max="38" />
          </label>
          <label>
            湿度下限 %RH
            <el-input-number v-model="policy.humidityLow" :min="20" :max="60" />
          </label>
          <label>
            湿度上限 %RH
            <el-input-number v-model="policy.humidityHigh" :min="50" :max="90" />
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
import { ElMessage } from 'element-plus'
import request from '@/utils/request'
import { useAlertPolicyStore } from '@/stores/alertPolicyStore'
import { useThemeStore } from '@/stores/themeStore'

const policy = useAlertPolicyStore()
const themeStore = useThemeStore()

const loading = ref(false)
const error = ref('')
const handlingEmergency = ref(false)
const resolvedBy = ref('')
const resolutionNote = ref('')
const policyVisible = ref(false)
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
  snore_monitoring: false,
  snore_paused: false,
  environment_board_online: false,
  environment_sensor_ok: false,
  voice_board_online: false,
  edgi_board_online: false,
  emergency_active: false,
  active_emergency: null,
  radar_age_seconds: null,
  snore_age_seconds: null,
  environment_age_seconds: null,
  voice_age_seconds: null,
  temperature_c: null,
  humidity_pct: null,
  comfort_status: 'offline',
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
const latestTemperature = computed(() => numberOrNull(latestRow.value.temperature_c ?? status.temperature_c))
const latestHumidity = computed(() => numberOrNull(latestRow.value.humidity_pct ?? status.humidity_pct))

const comfortLabelMap = {
  comfortable: '舒适',
  cold: '偏冷',
  hot: '偏热',
  dry: '偏干',
  humid: '偏湿',
  cold_dry: '偏冷偏干',
  cold_humid: '偏冷偏湿',
  hot_dry: '偏热偏干',
  hot_humid: '偏热偏湿',
  cold_critical: '过冷',
  hot_critical: '过热',
  dry_critical: '过干',
  humid_critical: '过湿',
  cold_dry_critical: '过冷过干',
  cold_humid_critical: '过冷过湿',
  hot_dry_critical: '过热过干',
  hot_humid_critical: '过热过湿',
  sensor_error: '传感器异常',
  no_data: '暂无数据',
  offline: '离线'
}

const comfortStatusLabel = computed(() => comfortLabelMap[status.comfort_status] || status.comfort_status || '离线')

const environmentNeedsAttention = computed(() => {
  return status.environment_board_online && status.comfort_status !== 'comfortable'
})

const edgiBoardOnline = computed(() => (
  status.edgi_board_online ||
  status.snore_board_online ||
  status.environment_board_online ||
  status.voice_board_online
))

const edgiBoardNeedsAttention = computed(() => {
  return Boolean(edgiBoardOnline.value && (
    status.snore_detected ||
    environmentNeedsAttention.value ||
    status.emergency_active
  ))
})

const edgiStatusText = computed(() => {
  if (!edgiBoardOnline.value) return '离线'
  if (status.emergency_active) return '紧急状态'
  if (status.snore_monitoring || status.snore_board_online) return '在线 · 呼噜监测中'
  return status.snore_paused ? '在线 · 呼噜已暂停' : '在线'
})

const environmentStatusText = computed(() => {
  if (!status.environment_board_online) return formatAge(status.environment_age_seconds)
  const temp = latestTemperature.value === null ? '-- C' : `${latestTemperature.value.toFixed(1)} C`
  const humidity = latestHumidity.value === null ? '-- %RH' : `${latestHumidity.value.toFixed(1)} %RH`
  return `${temp} · ${humidity}`
})

const eventPressure = computed(() => {
  const events = (overview.events || []).filter(event => (event.status || 'active') === 'active')
  return {
    critical: events.filter(event => event.severity === 'critical').length,
    warning: events.filter(event => event.severity === 'warning').length
  }
})

const latestEmergencyEvent = computed(() => {
  const events = overview.events || []
  return events.find(event =>
    event.type === 'emergency_voice' &&
    event.severity === 'critical' &&
    (event.status || 'active') === 'active'
  ) || status.active_emergency || null
})

const emergencyPhrase = computed(() => {
  const event = latestEmergencyEvent.value
  return event?.details?.transcript || event?.details?.phrase || '求助语音'
})

const riskItems = computed(() => {
  const emergency = buildEmergencyRisk()
  const heart = buildHeartRisk()
  const breath = buildBreathRisk()
  const snore = buildSnoreRisk()
  const environment = buildEnvironmentRisk()
  const presence = buildPresenceRisk()
  const devices = buildDeviceRisk()
  return [emergency, heart, breath, snore, environment, presence, devices]
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
      reason: '存在设备离线、离床、环境或生命体征越界风险。'
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
  const environment = latestTemperature.value === null || latestHumidity.value === null
    ? '环境无数据'
    : `环境 ${latestTemperature.value.toFixed(1)} C / ${latestHumidity.value.toFixed(1)} %RH`
  return `最新状态：${heart}，${breath}，${snore}，${environment}。`
})

function numberOrNull(value) {
  if (value === null || value === undefined || value === '') return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function riskWeight(level) {
  if (level === 'critical') return 24
  if (level === 'warning') return 10
  return 0
}

function buildEmergencyRisk() {
  const event = latestEmergencyEvent.value
  if (!event) {
    return risk('emergency_voice', '语音求助', 'normal', '暂无求助', '当前窗口内未检测到小智语音求助。', '无需处理', '未触发语音求助。', 'SOS')
  }
  const phrase = event.details?.phrase || event.details?.transcript || '求助语音'
  return risk(
    'emergency_voice',
    '语音求助',
    'critical',
    '紧急触发',
    `小智检测到“${phrase}”。`,
    '立即确认床旁情况',
    '优先到现场或联系看护人员确认用户状态；情况紧急时联系当地急救电话。',
    'SOS'
  )
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
    if (edgiBoardOnline.value && !status.snore_board_online) {
      return risk('snore', '呼噜', 'normal', '已暂停', '小智连接正常，呼噜监测当前暂停。', '无需处理', '可在开发板主页继续呼噜监测。', 'SN')
    }
    return risk('snore', '呼噜', 'warning', '暂无数据', '暂无呼噜特征。', '检查开发板', '确认 Edgi E84 在线。', 'SN')
  }
  if (snoreValue >= policy.snoreThreshold || hasSnoreEvent) {
    return risk('snore', '呼噜', 'warning', `${snoreValue}%`, `达到策略阈值 ${policy.snoreThreshold}% 或最近检测到呼噜。`, '观察呼噜扰动', '查看驾驶舱呼噜扰动地图，确认是否伴随心率/呼吸波动。', 'SN')
  }
  return risk('snore', '呼噜', 'normal', `${snoreValue}%`, '低于当前呼噜阈值。', '无需处理', '呼噜扰动较低。', 'SN')
}

function formatDateTime(value) {
  if (!value) return '--'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

async function resolveEmergency() {
  const event = latestEmergencyEvent.value
  if (!event) return
  if (!resolvedBy.value.trim()) {
    ElMessage.warning('请填写处理人')
    return
  }
  if (!resolutionNote.value.trim()) {
    ElMessage.warning('请填写现场处理说明')
    return
  }

  handlingEmergency.value = true
  try {
    const response = await request.post('/emergency/resolve', {
      event_id: event.eventID,
      source: event.source || 'xiaozhi_voice_board',
      resolved_by: resolvedBy.value.trim(),
      resolution_note: resolutionNote.value.trim()
    })
    if (response.status !== 'success' && response.status !== 'not_found') {
      throw new Error(response.message || '解除紧急状态失败')
    }
    ElMessage.success(response.status === 'not_found' ? '该事件已由其他终端处理' : '紧急状态已解除并留存记录')
    resolutionNote.value = ''
    await loadData()
  } catch (err) {
    console.error('解除紧急状态失败:', err)
    ElMessage.error(err.message || '解除失败，请检查后端连接')
  } finally {
    handlingEmergency.value = false
  }
}

function buildEnvironmentRisk() {
  if (!status.environment_board_online) {
    const level = edgiBoardOnline.value ? 'normal' : 'warning'
    return risk('environment', '睡眠环境', level, '等待采样', 'Edgi E84 已连接，当前暂无环境心跳。', '检查环境采集', '确认 AHT20 与环境上报线程运行。', 'EV')
  }
  const temperature = latestTemperature.value
  const humidity = latestHumidity.value
  if (temperature === null || humidity === null) {
    return risk('environment', '睡眠环境', 'warning', '暂无温湿度', 'Edgi E84 在线，但当前窗口没有有效温湿度数值。', '复核环境数据', '查看实时页温湿度趋势是否断线，确认 AHT20 读数有效。', 'EV')
  }
  const outOfPolicy = temperature < policy.temperatureLow ||
    temperature > policy.temperatureHigh ||
    humidity < policy.humidityLow ||
    humidity > policy.humidityHigh
  const critical = status.comfort_status?.endsWith('_critical')
  if (outOfPolicy || critical) {
    return risk(
      'environment',
      '睡眠环境',
      critical ? 'critical' : 'warning',
      `${temperature.toFixed(1)} C / ${humidity.toFixed(1)} %RH`,
      `策略范围 ${policy.temperatureLow}-${policy.temperatureHigh} C，${policy.humidityLow}-${policy.humidityHigh} %RH。`,
      '调整房间环境',
      '检查空调、加湿器、通风和传感器摆放，避免温湿度持续影响睡眠稳定性。',
      'EV'
    )
  }
  return risk('environment', '睡眠环境', 'normal', `${temperature.toFixed(1)} C / ${humidity.toFixed(1)} %RH`, '处于当前温湿度策略范围。', '无需处理', '睡眠环境舒适。', 'EV')
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
  const edgiOffline = !status.snore_board_online &&
    !status.environment_board_online &&
    !status.voice_board_online &&
    !status.edgi_board_online
  if (radarOffline || edgiOffline) {
    return risk('device', '设备链路', 'critical', '存在离线', `离线判定阈值 ${policy.offlineSeconds} 秒。`, '恢复设备链路', '检查雷达板和 Edgi E84 是否仍在运行，必要时重启对应端。', 'DV')
  }
  return risk('device', '设备链路', 'normal', '两块开发板在线', '雷达板与 Edgi E84 心跳正常。', '无需处理', '设备链路稳定。', 'DV')
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
    color: ['#ef4444', '#38bdf8', '#f59e0b', '#16a34a', '#0ea5e9'],
    tooltip: { trigger: 'axis' },
    legend: {
      top: 0,
      textStyle: { color: strongText },
      data: ['心率', '呼吸率', '呼噜强度', '温度', '湿度']
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
      },
      {
        name: '温度',
        type: 'line',
        smooth: true,
        showSymbol: false,
        connectNulls: false,
        data: rows.map(row => row.environment_online ? numberOrNull(row.temperature_c) : null)
      },
      {
        name: '湿度',
        type: 'line',
        smooth: true,
        showSymbol: false,
        connectNulls: false,
        data: rows.map(row => row.environment_online ? numberOrNull(row.humidity_pct) : null)
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
watch(policyVisible, () => nextTick(() => {
  renderChart()
  resizeChart()
}))

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

.status-card.warning {
  border-left-color: var(--care-warning);
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

.emergency-workspace {
  overflow: hidden;
  border: 1px solid rgba(239, 68, 68, 0.72);
  border-left: 8px solid #ef4444;
  border-radius: 8px;
  background: var(--care-surface);
  box-shadow: 0 18px 42px rgba(127, 29, 29, 0.18);
}

.emergency-heading {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr) auto;
  align-items: center;
  gap: 18px;
  padding: 22px 24px;
  border-bottom: 1px solid rgba(239, 68, 68, 0.28);
}

.sos-mark {
  width: 72px;
  height: 72px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  color: #fff;
  background: #dc2626;
  font-size: 22px;
  font-weight: 900;
  box-shadow: 0 0 0 8px rgba(239, 68, 68, 0.12);
}

.emergency-heading span,
.emergency-meta span {
  color: var(--care-danger);
  font-size: 13px;
  font-weight: 800;
}

.emergency-heading h2 {
  margin: 4px 0 6px;
  font-size: 26px;
}

.emergency-heading p {
  margin: 0;
  color: var(--care-muted);
}

.emergency-meta {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  border-bottom: 1px solid var(--care-border-soft);
}

.emergency-meta > div {
  display: grid;
  gap: 6px;
  padding: 16px 24px;
  border-right: 1px solid var(--care-border-soft);
}

.emergency-meta > div:last-child {
  border-right: 0;
}

.emergency-meta strong {
  overflow-wrap: anywhere;
}

.emergency-process {
  display: grid;
  grid-template-columns: minmax(280px, 0.8fr) minmax(340px, 1.2fr);
  gap: 28px;
  padding: 22px 24px 26px;
}

.response-steps ol {
  margin: 14px 0 0;
  padding-left: 24px;
  color: var(--care-muted);
  line-height: 1.9;
}

.resolution-form {
  display: grid;
  gap: 14px;
}

.resolution-form label {
  display: grid;
  gap: 7px;
  color: var(--care-muted);
  font-size: 13px;
  font-weight: 800;
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

.policy-card,
.trend-card {
  grid-column: 1 / -1;
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
  .policy-grid,
  .emergency-process {
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

  .emergency-heading {
    grid-template-columns: 56px minmax(0, 1fr);
    padding: 18px;
  }

  .emergency-heading .el-tag {
    grid-column: 1 / -1;
    justify-self: start;
  }

  .sos-mark {
    width: 56px;
    height: 56px;
    font-size: 17px;
  }

  .emergency-meta {
    grid-template-columns: 1fr;
  }

  .emergency-meta > div {
    border-right: 0;
    border-bottom: 1px solid var(--care-border-soft);
  }

  .emergency-process {
    padding: 18px;
  }
}
</style>
