<template>
  <div class="alert-workspace care-page-shell">
    <section
      v-if="latestEmergencyEvent"
      class="emergency-workspace"
      aria-live="assertive"
    >
      <div class="emergency-heading">
        <div class="sos-mark">SOS</div>
        <div>
          <span>待处理紧急事件</span>
          <h2>{{ emergencyTitle }}</h2>
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
          <span>{{ emergencyDetailLabel }}</span>
          <strong>{{ emergencyPhrase }}</strong>
        </div>
        <div>
          <span>事件来源</span>
          <strong>{{ emergencySourceText }}</strong>
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

    <section class="control-row care-glass-card care-icon-card" data-icon="策">
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
            <p class="section-caption">横向汇总紧急事件、生命体征、呼噜、环境、离床和设备链路状态。</p>
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

      <article class="actions-card care-glass-card care-icon-card" data-icon="护">
        <div class="section-title">
          <div>
            <h2>照护动作队列</h2>
          </div>
          <el-tag :type="activeActions.length ? 'warning' : 'success'">
            {{ activeActions.length ? `${activeActions.length} 项待处理` : '无待处理' }}
          </el-tag>
        </div>

        <div v-if="activeActions.length === 0" class="empty-actions">
          <div class="empty-illustration" aria-hidden="true">
            <span class="clip-board"></span>
            <span class="search-lens"></span>
          </div>
          <p>当前没有待处理动作。若需要重新查看已处理事项，请点击“恢复已处理动作”。</p>
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

      <article v-if="policyVisible" class="policy-card care-glass-card care-icon-card" data-icon="阈">
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

    </section>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import request from '@/utils/request'
import { useAlertPolicyStore } from '@/stores/alertPolicyStore'
import { useBedStore } from '@/stores/bedStore'

const policy = useAlertPolicyStore()
const bedStore = useBedStore()

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
  radar_board_stationary: true,
  radar_motion_reason: 'disabled',
  radar_motion_delta: null,
  radar_motion_sensor_ready: null,
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
  radar_status_age_seconds: null,
  snore_age_seconds: null,
  environment_age_seconds: null,
  voice_age_seconds: null,
  temperature_c: null,
  humidity_pct: null,
  comfort_status: 'offline',
  audio_upload_count: 0,
  snore_detected: false
})

let refreshTimer = null

const latestRow = computed(() => timelineRows.value[timelineRows.value.length - 1] || {})

const latestHeart = computed(() => numberOrNull(latestRow.value.heart_rate))
const latestBreath = computed(() => numberOrNull(latestRow.value.breath_rate))
const latestVitalsState = computed(() => latestRow.value.vitals_state || status.vitals_state || 'lost')
const latestSnore = computed(() => {
  return snoreIntensityValue(latestRow.value)
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
const radarBoardUnstable = computed(() => Boolean(status.radar_board_online && status.radar_board_stationary === false))
const environmentNeedsAttention = computed(() => {
  return status.environment_board_online && status.comfort_status !== 'comfortable'
})

const edgiBoardOnline = computed(() => (
  status.edgi_board_online ||
  status.snore_board_online ||
  status.environment_board_online ||
  status.voice_board_online
))

const emergencyEventTypes = new Set([
  'emergency_voice',
  'board_fall',
  'suspected_apnea',
  'snore_stop_breath_drop',
  'night_absence'
])

const isActiveEmergencyEvent = event => Boolean(event && (event.status || 'active') === 'active')
const isCriticalEmergencyEvent = event => Boolean(
  event &&
  emergencyEventTypes.has(event.type) &&
  event.severity === 'critical' &&
  isActiveEmergencyEvent(event)
)

const latestEmergencyEvent = computed(() => {
  const events = overview.events || []
  const activeStatusEmergency = isCriticalEmergencyEvent(status.active_emergency)
    ? status.active_emergency
    : null
  return activeStatusEmergency || events.find(isCriticalEmergencyEvent) || null
})

const latestApneaEvent = computed(() => {
  const events = overview.events || []
  return events.find(event =>
    event.type === 'suspected_apnea' &&
    ['warning', 'critical'].includes(event.severity) &&
    isActiveEmergencyEvent(event)
  ) || null
})

const emergencyPhrase = computed(() => {
  const event = latestEmergencyEvent.value
  if (event?.type === 'suspected_apnea') {
    return event.message || event.title || '检测到疑似呼吸暂停风险'
  }
  if (event?.type === 'snore_stop_breath_drop') {
    return event.message || event.title || '呼噜停止伴随呼吸信号跌破阈值'
  }
  if (event?.type === 'night_absence') return event.message || event.title || '夜间存在性检测超过 1 小时未检测到在床'
  if (event?.type === 'board_fall') {
    return event.message || event.title || '开发板检测到疑似摇晃'
  }
  return event?.details?.transcript || event?.details?.phrase || '求助语音'
})

const emergencyTitle = computed(() => {
  const event = latestEmergencyEvent.value
  if (event?.type === 'suspected_apnea') return '疑似呼吸暂停，请立即观察'
  if (event?.type === 'snore_stop_breath_drop') return '呼噜停止伴随呼吸信号跌破阈值'
  if (event?.type === 'night_absence') return '夜间疑似离床，请立即确认'
  if (event?.type === 'board_fall') return '开发板摇晃报警'
  if (event?.type === 'emergency_voice') return '紧急求助已触发'
  return '请立即确认床旁情况'
})

const emergencyDetailLabel = computed(() => {
  const event = latestEmergencyEvent.value
  return event?.type === 'emergency_voice' ? '触发话术' : '事件说明'
})

const emergencySourceText = computed(() => {
  const event = latestEmergencyEvent.value
  if (event?.type === 'suspected_apnea' && event?.details?.demo) return '疑似呼吸暂停'
  if (event?.type === 'suspected_apnea') return '雷达与呼噜融合检测'
  if (event?.type === 'snore_stop_breath_drop') return '呼噜与雷达融合检测'
  if (event?.type === 'night_absence') return '雷达存在性夜间离床监护'
  if (event?.type === 'board_fall') return '小智摇晃检测'
  return '小智语音开发板'
})

const riskItems = computed(() => {
  const emergency = buildEmergencyRisk()
  const apnea = buildApneaRisk()
  const heart = buildHeartRisk()
  const breath = buildBreathRisk()
  const snore = buildSnoreRisk()
  const environment = buildEnvironmentRisk()
  const presence = buildPresenceRisk()
  const devices = buildDeviceRisk()
  return [emergency, apnea, heart, breath, snore, environment, presence, devices]
})

const actionQueue = computed(() => riskItems.value
  .filter(item => item.level !== 'normal')
  .sort((a, b) => {
    const levelDiff = riskWeight(b.level) - riskWeight(a.level)
    if (levelDiff !== 0) return levelDiff
    return riskPriority(a.key) - riskPriority(b.key)
  })
  .map(item => ({
    key: `${item.key}:${item.level}`,
    level: item.level,
    title: item.actionTitle,
    detail: item.actionDetail
  })))

const activeActions = computed(() => actionQueue.value.filter(action => !policy.acknowledgedKeys.includes(action.key)))

function numberOrNull(value) {
  if (value === null || value === undefined || value === '') return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value))
}

function snoreIntensityValue(row) {
  if (!row?.snore_online && !row?.snore_board_online) return null

  const energy = numberOrNull(row.snore_level)
  const confidence = numberOrNull(row.snore_score)
  return Math.round(clamp(energy ?? 0, 0, 1) * clamp(confidence ?? 0, 0, 1) * 50)
}

function riskWeight(level) {
  if (level === 'critical') return 24
  if (level === 'warning') return 10
  return 0
}

function riskPriority(key) {
  const order = {
    emergency_voice: 0,
    board_fall: 0,
    suspected_apnea: 1,
    breath: 2,
    heart: 3,
    snore: 4,
    presence: 5,
    environment: 6,
    device: 7
  }
  return order[key] ?? 99
}

function buildEmergencyRisk() {
  const event = latestEmergencyEvent.value
  if (!event) {
    return risk('emergency_voice', '紧急事件', 'normal', '暂无事件', '当前窗口内未检测到语音求助或摇晃报警。', '无需处理', '未触发紧急事件。', 'SOS')
  }
  if (event.type === 'snore_stop_breath_drop') {
    return risk(
      'snore_stop_breath_drop',
      '呼吸异常',
      'critical',
      '呼噜停止后异常',
      event.message || '呼噜停止后呼吸/存在性信号跌破阈值。',
      '立即观察呼吸状态',
      '优先确认患者呼吸、体位和雷达位置；确认安全后在告警中心解除事件。',
      'AP'
    )
  }
  if (event.type === 'night_absence') {
    return risk(
      'night_absence',
      '离床报警',
      'critical',
      '超过 1 小时未在床',
      event.message || '夜间存在性检测连续超过 1 小时未检测到病人在床。',
      '立即确认床位情况',
      '优先确认患者是否离床、跌倒或误离监护范围；确认安全后在告警中心解除事件。',
      'OUT'
    )
  }
  if (event.type === 'board_fall') {
    return risk(
      'board_fall',
      '开发板摇晃',
      'critical',
      '摇晃触发',
      event.message || '开发板检测到疑似摇晃。',
      '立即确认人员与设备状态',
      '优先到现场确认是否摔倒、设备是否脱落；如存在受伤风险，及时联系看护人员或急救。',
      'FALL'
    )
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

function buildApneaRisk() {
  const event = latestApneaEvent.value
  if (!event) {
    return risk(
      'suspected_apnea',
      '疑似暂停',
      'normal',
      '暂无提示',
      '当前窗口未发现雷达与呼噜同时支持的疑似暂停。',
      '无需处理',
      '继续观察呼吸与呼噜趋势。',
      'AP'
    )
  }
  const details = event.details || {}
  const duration = Number(details.duration_seconds)
  const confidence = Number(details.confidence)
  const statusText = Number.isFinite(duration) ? `${duration.toFixed(0)} 秒` : '疑似暂停'
  const detail = Number.isFinite(confidence)
    ? `融合置信度 ${Math.round(confidence * 100)}%，请结合现场观察。`
    : '雷达呼吸减弱并伴随呼噜声变化。'
  return risk(
    'suspected_apnea',
    '疑似暂停',
    event.severity === 'critical' ? 'critical' : 'warning',
    statusText,
    detail,
    '确认呼吸状态',
    '确认用户呼吸、睡姿和雷达位置；如存在明显不适或异常，请联系看护人员或急救。',
    'AP'
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
  if (latestVitalsState.value === 'recovering' && value !== null) {
    return risk('heart', '心率', 'normal', `${value.toFixed(1)} BPM`, '雷达信号短暂恢复中，沿用最近有效心率。', '继续观察', '若 8 秒内未恢复，系统会自动转为暂无生命体征。', 'HR')
  }
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
  if (latestVitalsState.value === 'recovering' && value !== null) {
    return risk('breath', '呼吸', 'normal', `${value.toFixed(1)} RPM`, '雷达信号短暂恢复中，沿用最近有效呼吸率。', '继续观察', '恢复期数据不会参与呼吸暂停报警判定。', 'BR')
  }
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
    const response = await request.post(`/beds/${bedStore.selectedBedId}/emergency/resolve`, {
      event_id: event.eventID,
      bed_id: bedStore.selectedBedId,
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
    return risk('presence', '离床/无人', 'warning', '等待数据', '尚未获取到雷达目标距离。', '等待目标数据', '确认真实后端服务和雷达板已启动，稍后刷新预警中心。', 'PR')
  }
  if (row.radar_online === false || row.target_distance === 0 || row.target_distance === null) {
    return risk('presence', '离床/无人', 'critical', '疑似无人', '雷达在线状态或目标距离显示疑似离床。', '确认床旁状态', '检查雷达视场、目标距离和是否存在离床情况。', 'PR')
  }
  const distance = numberOrNull(row.target_distance)
  return risk('presence', '离床/无人', 'normal', distance === null ? '等待距离' : `${distance.toFixed(2)} m`, '目标存在状态正常。', '无需处理', '目标距离稳定。', 'PR')
}

function buildDeviceRisk() {
  const radarAge = Number(status.radar_age_seconds)
  const radarStatusAge = Number(status.radar_status_age_seconds)
  const radarSeenAge = Number.isFinite(radarStatusAge) ? radarStatusAge : radarAge
  const radarOffline = !status.radar_board_online || radarSeenAge > policy.offlineSeconds
  const edgiOffline = !status.snore_board_online &&
    !status.environment_board_online &&
    !status.voice_board_online &&
    !status.edgi_board_online
  if (radarOffline || edgiOffline) {
    return risk('device', '设备链路', 'critical', '存在离线', `离线判定阈值 ${policy.offlineSeconds} 秒。`, '恢复设备链路', '检查雷达板和 Edgi E84 是否仍在运行，必要时重启对应端。', 'DV')
  }
  if (radarBoardUnstable.value) {
    return risk('device', '设备链路', 'warning', '雷达未静止', '雷达板在线，但已暂停原始数据传输。', '放稳雷达板', '将雷达板固定后等待 2 秒，数据会自动恢复。', 'DV')
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
      request.get('/sleep/overview', { params: { mode: 'live', seconds: 1800, bed_id: bedStore.selectedBedId } }),
      request.get('/timeline', { params: { seconds: 1800, bed_id: bedStore.selectedBedId } }),
      request.get('/status', { params: { bed_id: bedStore.selectedBedId } })
    ])

    if (overviewResult.status === 'fulfilled') {
      Object.assign(overview, {
        stats: overviewResult.value.stats || {},
        score: overviewResult.value.score || {},
        events: (overviewResult.value.events || []).filter(isActiveEmergencyEvent),
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
    error.value = '看护预警中心无法连接真实后端服务，请先启动 backend/realtime_radar_processing.py。'
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadData()
  refreshTimer = window.setInterval(loadData, 5000)
})

onBeforeUnmount(() => {
  if (refreshTimer) window.clearInterval(refreshTimer)
})
</script>

<style scoped>
.alert-workspace {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.section-title p,
.matrix-item small,
.action-item p,
.control-row span {
  color: var(--care-muted);
  line-height: 1.55;
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
  grid-template-columns: 1fr;
  gap: 18px;
}

.matrix-card,
.actions-card,
.policy-card {
  padding: 20px;
}

.matrix-card {
  position: relative;
  overflow: hidden;
  min-height: 420px;
  padding: 30px;
  background:
    linear-gradient(90deg, rgba(255, 255, 255, .98) 0%, rgba(255, 255, 255, .96) 68%, rgba(235, 243, 255, .92) 100%);
}

.actions-card {
  padding: 30px;
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

.section-caption {
  margin: 0;
  color: var(--care-muted);
  font-size: 13px;
  line-height: 1.55;
}

.matrix-list {
  display: grid;
  position: relative;
  z-index: 1;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  max-width: 1020px;
  gap: 14px 16px;
  margin-top: 32px;
}

.matrix-item {
  display: grid;
  grid-template-columns: 44px minmax(0, 1fr);
  gap: 12px;
  align-items: center;
  min-height: 88px;
  padding: 14px 16px;
  border-radius: 16px;
  border: 1px solid var(--care-border-soft);
  background: rgba(255, 255, 255, .82);
  box-shadow: 0 10px 26px rgba(34, 46, 97, .05);
  backdrop-filter: blur(10px);
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
  width: 44px;
  height: 44px;
  display: grid;
  place-items: center;
  border-radius: 13px;
  color: var(--care-link);
  background: linear-gradient(135deg, rgba(50, 91, 242, .14), rgba(96, 165, 250, .18));
  font-size: 12px;
  font-weight: 900;
  animation: matrixIconFloat 2.8s ease-in-out infinite;
  will-change: transform, box-shadow;
}

.matrix-item.warning .matrix-icon {
  color: var(--care-warning);
  background: var(--care-warning-soft);
  animation-name: matrixIconWarning;
}

.matrix-item.critical .matrix-icon {
  color: var(--care-danger);
  background: var(--care-danger-soft);
  animation-name: matrixIconCritical;
}

.matrix-item strong,
.matrix-item span {
  display: block;
}

.matrix-item span {
  margin: 2px 0 0;
  font-weight: 800;
  font-size: 14px;
  line-height: 1.25;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.matrix-item strong {
  color: var(--care-text-strong);
  font-size: 15px;
  line-height: 1.2;
}

.matrix-visual {
  position: absolute;
  top: 26px;
  right: 42px;
  width: 260px;
  height: 126px;
  pointer-events: none;
}

.visual-ring {
  position: absolute;
  right: 0;
  bottom: 0;
  width: 190px;
  height: 58px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(50, 91, 242, .28), rgba(50, 91, 242, .08) 46%, transparent 70%);
  filter: blur(.1px);
}

.ring-b {
  right: 34px;
  bottom: 20px;
  width: 150px;
  height: 46px;
  opacity: .72;
}

.visual-shield {
  position: absolute;
  right: 68px;
  top: 0;
  width: 76px;
  height: 76px;
  display: grid;
  place-items: center;
  border-radius: 24px 24px 34px 34px;
  color: #ffffff;
  background: linear-gradient(135deg, #6ba7ff, #325bf2);
  box-shadow: 0 18px 38px rgba(50, 91, 242, .22);
  font-size: 38px;
  font-weight: 900;
}

@keyframes matrixIconFloat {
  0%, 100% {
    transform: translateY(0) scale(1);
    box-shadow: 0 0 0 rgba(50, 91, 242, 0);
  }
  50% {
    transform: translateY(-2px) scale(1.04);
    box-shadow: 0 8px 18px rgba(50, 91, 242, .12);
  }
}

@keyframes matrixIconWarning {
  0%, 100% {
    transform: translateY(0) scale(1);
    box-shadow: 0 0 0 rgba(245, 158, 11, 0);
  }
  50% {
    transform: translateY(-2px) scale(1.05);
    box-shadow: 0 8px 18px rgba(245, 158, 11, .18);
  }
}

@keyframes matrixIconCritical {
  0%, 100% {
    transform: translateY(0) scale(1);
    box-shadow: 0 0 0 0 rgba(239, 68, 68, .18);
  }
  50% {
    transform: translateY(-2px) scale(1.06);
    box-shadow: 0 0 0 7px rgba(239, 68, 68, .08), 0 8px 18px rgba(239, 68, 68, .18);
  }
}

.action-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
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
  min-height: 230px;
  display: grid;
  place-items: center;
  gap: 14px;
  padding: 34px;
  border-radius: 18px;
  text-align: center;
  color: var(--care-muted);
  background: rgba(248, 250, 255, .78);
  border: 1px solid var(--care-border-soft);
}

.empty-actions p {
  max-width: 520px;
  margin: 0;
  color: var(--care-muted-strong);
  line-height: 1.75;
}

.empty-illustration {
  position: relative;
  width: 156px;
  height: 108px;
}

.clip-board {
  position: absolute;
  left: 46px;
  top: 10px;
  width: 62px;
  height: 78px;
  border: 8px solid rgba(50, 91, 242, .24);
  border-radius: 14px;
  background: rgba(255, 255, 255, .8);
}

.clip-board::before {
  content: '';
  position: absolute;
  left: 15px;
  top: -18px;
  width: 32px;
  height: 18px;
  border-radius: 10px 10px 4px 4px;
  background: rgba(50, 91, 242, .3);
}

.clip-board::after {
  content: '';
  position: absolute;
  left: 13px;
  right: 13px;
  top: 22px;
  height: 6px;
  border-radius: 999px;
  background:
    linear-gradient(#c7d7ff, #c7d7ff) 0 0 / 100% 6px no-repeat,
    linear-gradient(#dbe6ff, #dbe6ff) 0 18px / 72% 6px no-repeat;
}

.search-lens {
  position: absolute;
  right: 22px;
  bottom: 20px;
  width: 38px;
  height: 38px;
  border: 7px solid rgba(50, 91, 242, .24);
  border-radius: 50%;
}

.search-lens::after {
  content: '';
  position: absolute;
  right: -18px;
  bottom: -12px;
  width: 28px;
  height: 8px;
  border-radius: 999px;
  background: rgba(50, 91, 242, .24);
  transform: rotate(42deg);
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

.policy-card {
  grid-column: 1 / -1;
}

@media (max-width: 1180px) {
  .alert-grid,
  .policy-grid,
  .emergency-process {
    grid-template-columns: 1fr;
  }

  .matrix-list {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .matrix-visual {
    opacity: .36;
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

  .matrix-card,
  .actions-card {
    padding: 20px;
  }

  .matrix-list {
    grid-template-columns: 1fr;
  }

  .matrix-visual {
    display: none;
  }
}
</style>
