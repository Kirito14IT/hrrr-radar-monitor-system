<template>
  <div class="ward-screen" :class="{ 'alarm-active': alarmActive }">
    <header class="screen-header">
      <div>
        <p class="eyebrow">Bed Care Monitor</p>
        <h1>床位监护大屏</h1>
        <p class="subtitle">面向医院、疗养院护理人员的多床位实时看护视图</p>
      </div>
      <div class="header-right">
        <div class="clock-card care-icon-card" data-icon="时">
          <span>{{ currentDate }}</span>
          <strong>{{ currentTime }}</strong>
        </div>
        <button
          class="sound-toggle"
          :class="{ ready: alarmSoundReady, blocked: alarmSoundBlocked }"
          @click.stop="enableAlarmAudio"
        >
          {{ alarmSoundReady ? '报警声音已启用' : '启用报警声音' }}
        </button>
        <button @click="router.push('/manage/nurse_station')">返回监视台</button>
      </div>
    </header>

    <section class="dashboard-frame" aria-label="Bed monitoring dashboard">
      <aside class="dashboard-rail" aria-hidden="true">
        <span class="rail-brand">SS</span>
        <span class="active">01</span>
        <span>02</span>
        <span>03</span>
        <span>04</span>
        <span>05</span>
      </aside>

      <div class="dashboard-content">
        <div class="dashboard-toolbar">
          <div>
            <span class="toolbar-kicker">LIVE MONITORING</span>
            <strong>Bed Status</strong>
          </div>
          <div class="toolbar-actions">
            <span>{{ sortedBeds.length }} Beds</span>
            <span>{{ currentTime }}</span>
          </div>
        </div>

    <section class="summary-strip">
      <article class="care-icon-card" data-icon="BED">
        <span>总床位</span>
        <strong>{{ summary.total || beds.length }}</strong>
      </article>
      <article class="online care-icon-card" data-icon="ON">
        <span>在线床位</span>
        <strong>{{ summary.online || 0 }}</strong>
      </article>
      <article class="warning care-icon-card" data-icon="!">
        <span>需关注</span>
        <strong>{{ summary.warning || 0 }}</strong>
      </article>
      <article class="critical care-icon-card" data-icon="SOS" :class="{ pulse: summary.critical > 0 }">
        <span>紧急事件</span>
        <strong>{{ summary.critical || 0 }}</strong>
      </article>
    </section>

    <section v-if="priorityBeds.length" class="alert-strip">
      <strong>当前重点关注</strong>
      <div class="alert-list">
        <span
          v-for="bed in priorityBeds"
          :key="bed.bed_id"
          :class="isTempAbnormal(bed) && bed.risk_level === 'normal' ? 'warning' : bed.risk_level"
        >
          {{ bed.bed_label || bed.bed_id }}：{{ tempIssueShort(bed) || bed.primary_issue || riskLabel(bed.risk_level) }}
        </span>
      </div>
      <button v-if="alarmActive" class="voice-button" @click.stop="repeatAlarmNow">立即播报</button>
    </section>

    <main class="bed-grid">
      <article
        v-for="bed in sortedBeds"
        :key="bed.bed_id"
        class="bed-card"
        :class="bedCardClass(bed)"
        @click="openBed(bed)"
      >
        <div class="card-status-line"></div>

        <div v-if="bedEmergencyActive(bed)" class="bed-emergency-banner">
          <span>紧急报警</span>
          <strong>{{ emergencyEventTitle(bed.active_emergency) }}</strong>
        </div>

        <div class="card-head">
          <div>
            <span class="room">{{ bed.room || '护理房间' }}</span>
            <h2>{{ bed.bed_label || bed.bed_id }}</h2>
          </div>
          <strong class="status-badge">{{ isTempAbnormal(bed) && bed.risk_level === 'normal' ? '关注' : riskLabel(bed.risk_level) }}</strong>
        </div>

        <div class="patient-line">
          <strong>{{ bed.patient_name || '未登记患者' }}</strong>
          <span>{{ patientMeta(bed) }}</span>
        </div>

        <div class="bed-visual" aria-hidden="true">
          <div class="bed-back"></div>
          <div class="bed-mattress">
            <span class="pillow"></span>
            <span class="blanket"></span>
            <span class="rail rail-left"></span>
            <span class="rail rail-right"></span>
          </div>
          <div class="bed-base"></div>
          <i class="wheel wheel-left"></i>
          <i class="wheel wheel-right"></i>
          <span class="breath-indicator"></span>
        </div>

        <div class="vital-row">
          <div>
            <span>心率</span>
            <strong>{{ formatValue(bed.heart_rate, 'BPM') }}</strong>
          </div>
          <div>
            <span>呼吸</span>
            <strong>{{ formatValue(bed.breath_rate, 'RPM') }}</strong>
          </div>
          <div :class="{ 'temp-abnormal': isTempAbnormal(bed) }">
            <span>温湿度</span>
            <strong>{{ formatEnv(bed) }}</strong>
          </div>
          <div>
            <span>呼噜</span>
            <strong>{{ bed.snore_detected ? '检测中' : '正常' }}</strong>
          </div>
        </div>

        <div class="device-row">
          <span :class="{ on: bed.radar_board_online }">雷达</span>
          <span :class="{ on: bed.edgi_board_online }">小智</span>
          <span :class="{ on: bed.snore_board_online }">呼噜</span>
          <span :class="{ on: bed.environment_board_online }">环境</span>
        </div>

        <p class="issue-text" :class="{ 'temp-warn': isTempAbnormal(bed) && !bedEmergencyActive(bed) && bed.risk_level === 'normal' }">{{ bedIssueText(bed) }}</p>
      </article>
    </main>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useBedStore } from '@/stores/bedStore'
import { useAlertPolicyStore } from '@/stores/alertPolicyStore'

const router = useRouter()
const bedStore = useBedStore()
const alertPolicy = useAlertPolicyStore()
const now = ref(new Date())
let timer = null
let clockTimer = null
let alarmAudioContext = null
let alarmToneTimer = null
let alarmSpeechTimer = null
const alarmSoundReady = ref(false)
const alarmSoundBlocked = ref(false)

const beds = computed(() => bedStore.beds)
const summary = computed(() => bedStore.summary)
const currentDate = computed(() => now.value.toLocaleDateString('zh-CN', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  weekday: 'long'
}))
const currentTime = computed(() => now.value.toLocaleTimeString('zh-CN', { hour12: false }))

const riskRank = level => ({
  critical: 4,
  warning: 3,
  offline: 2,
  normal: 1
}[level] || 1)

const sortedBeds = computed(() => [...beds.value].sort((a, b) => {
  const riskDiff = riskRank(b.risk_level) - riskRank(a.risk_level)
  if (riskDiff) return riskDiff
  return String(a.bed_label || a.bed_id).localeCompare(String(b.bed_label || b.bed_id), 'zh-CN')
}))

const priorityBeds = computed(() => sortedBeds.value.filter(bed => ['critical', 'warning'].includes(bed.risk_level) || bedEmergencyActive(bed) || isTempAbnormal(bed)).slice(0, 4))
const emergencyBeds = computed(() => sortedBeds.value.filter(bed => bedEmergencyActive(bed)))
const criticalBeds = computed(() => {
  const emergencyIds = new Set(emergencyBeds.value.map(bed => bed.bed_id))
  return [
    ...emergencyBeds.value,
    ...sortedBeds.value.filter(bed => bed.risk_level === 'critical' && !emergencyIds.has(bed.bed_id))
  ]
})
const alarmActive = computed(() => criticalBeds.value.length > 0)
const alarmKey = computed(() => criticalBeds.value
  .map(bed => [
    bed.bed_id,
    bed.active_emergency?.eventID,
    bed.active_emergency?.fingerprint,
    bed.active_emergency?.type,
    bed.active_emergency?.message,
    bed.primary_issue,
    bed.risk_level
  ].filter(Boolean).join(':'))
  .join('|')
)
const alarmMessage = computed(() => {
  const activeBeds = criticalBeds.value
  if (!activeBeds.length) return ''
  const firstText = bedAlarmSpeech(activeBeds[0])
  if (activeBeds.length === 1) {
    return `紧急报警，${firstText}，请护理人员立即查看。`
  }
  return `紧急报警，当前有 ${activeBeds.length} 个床位需要立即处理。重点关注，${firstText}。请查看监护大屏红色床位。`
})

function bedEmergencyActive(bed) {
  return Boolean(bed?.emergency_active && (bed?.active_emergency?.status || 'active') === 'active')
}

function bedCardClass(bed) {
  const base = bed?.risk_level || 'normal'
  const level = base === 'normal' && isTempAbnormal(bed) ? 'warning' : base
  return [
    level,
    { 'emergency-alarm': bedEmergencyActive(bed) }
  ]
}

function emergencyEventTitle(event) {
  if (!event) return '紧急事件'
  if (event.type === 'suspected_apnea') return '疑似呼吸暂停'
  if (event.type === 'snore_stop_breath_drop') return '呼噜停止伴随呼吸异常'
  if (event.type === 'night_absence') return '夜间疑似离床'
  if (event.type === 'emergency_voice') return '求救语音'
  if (event.type === 'board_fall') return '开发板摇晃'
  return event.title || event.message || '紧急事件'
}

function emergencyEventMessage(event) {
  return event?.message || event?.title || emergencyEventTitle(event)
}

function bedIssueText(bed) {
  if (bedEmergencyActive(bed)) {
    return emergencyEventMessage(bed.active_emergency)
  }
  const tempIssue = tempIssueText(bed)
  if (tempIssue) return tempIssue
  return bed?.primary_issue || '监护正常'
}

function bedAlarmSpeech(bed) {
  const bedName = bed?.bed_label || bed?.bed_id || '未知床位'
  const room = bed?.room ? `${bed.room}，` : ''
  const patient = bed?.patient_name ? `患者 ${bed.patient_name}，` : ''
  const event = bed?.active_emergency
  const title = emergencyEventTitle(event)
  const message = emergencyEventMessage(event)
  return `${room}${bedName}，${patient}${title}，${message}`
}

function riskLabel(level) {
  return {
    critical: '紧急',
    warning: '关注',
    offline: '离线',
    normal: '正常'
  }[level] || '正常'
}

function patientMeta(bed) {
  const parts = [bed?.patient_gender, bed?.patient_age ? `${bed.patient_age}岁` : ''].filter(Boolean)
  return parts.join(' / ') || '持续监护'
}

function formatValue(value, unit) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '--'
  return `${Number(value).toFixed(0)} ${unit}`
}

function formatEnv(bed) {
  const temp = bed?.temperature_c
  const hum = bed?.humidity_pct
  if (temp === null || temp === undefined || hum === null || hum === undefined) return '--'
  return `${Number(temp).toFixed(1)}℃ / ${Number(hum).toFixed(0)}%`
}

function isTempAbnormal(bed) {
  const temp = bed?.temperature_c
  if (temp === null || temp === undefined || Number.isNaN(Number(temp))) return false
  return temp < alertPolicy.temperatureLow || temp > alertPolicy.temperatureHigh
}

function tempIssueText(bed) {
  const temp = bed?.temperature_c
  if (temp === null || temp === undefined) return ''
  if (temp < alertPolicy.temperatureLow) return `温度偏低 (${Number(temp).toFixed(1)}℃)，需要关注`
  if (temp > alertPolicy.temperatureHigh) return `温度偏高 (${Number(temp).toFixed(1)}℃)，需要关注`
  return ''
}

function tempIssueShort(bed) {
  const temp = bed?.temperature_c
  if (temp === null || temp === undefined) return ''
  if (temp < alertPolicy.temperatureLow) return `温度偏低 ${Number(temp).toFixed(1)}℃`
  if (temp > alertPolicy.temperatureHigh) return `温度偏高 ${Number(temp).toFixed(1)}℃`
  return ''
}

function openBed(bed) {
  bedStore.setSelectedBed(bed.bed_id)
  router.push(`/manage/bed/${bed.bed_id}`)
}

async function ensureAlarmAudioContext() {
  const AudioContextClass = window.AudioContext || window.webkitAudioContext
  if (!AudioContextClass) return null
  if (!alarmAudioContext) {
    alarmAudioContext = new AudioContextClass()
  }
  if (alarmAudioContext.state === 'suspended') {
    await alarmAudioContext.resume()
  }
  alarmSoundReady.value = true
  alarmSoundBlocked.value = false
  return alarmAudioContext
}

async function playLoudAlarmTone() {
  try {
    const context = await ensureAlarmAudioContext()
    if (!context) return

    const start = context.currentTime
    const master = context.createGain()
    const compressor = context.createDynamicsCompressor()
    master.gain.setValueAtTime(0.0001, start)
    master.gain.exponentialRampToValueAtTime(0.82, start + 0.025)
    master.gain.exponentialRampToValueAtTime(0.0001, start + 1.55)
    master.connect(compressor)
    compressor.connect(context.destination)

    ;[0, 0.28, 0.56, 0.98].forEach((offset, index) => {
      const oscillator = context.createOscillator()
      const gain = context.createGain()
      const toneStart = start + offset
      const toneEnd = toneStart + 0.2

      oscillator.type = 'square'
      oscillator.frequency.setValueAtTime(index % 2 ? 1180 : 880, toneStart)
      gain.gain.setValueAtTime(0.0001, toneStart)
      gain.gain.exponentialRampToValueAtTime(1, toneStart + 0.012)
      gain.gain.exponentialRampToValueAtTime(0.0001, toneEnd)

      oscillator.connect(gain)
      gain.connect(master)
      oscillator.start(toneStart)
      oscillator.stop(toneEnd + 0.04)
    })
  } catch (error) {
    alarmSoundBlocked.value = true
    console.warn('Ward screen alarm tone was blocked:', error)
  }
}

function speakAlarm() {
  if (!alarmActive.value || !alarmMessage.value || !('speechSynthesis' in window)) return
  try {
    window.speechSynthesis.cancel()
    const utterance = new SpeechSynthesisUtterance(alarmMessage.value)
    utterance.lang = 'zh-CN'
    utterance.volume = 1
    utterance.rate = 0.92
    utterance.pitch = 1
    window.speechSynthesis.speak(utterance)
  } catch (error) {
    console.warn('Ward screen speech alarm failed:', error)
  }
}

function stopAlarm() {
  if (alarmToneTimer) {
    window.clearInterval(alarmToneTimer)
    alarmToneTimer = null
  }
  if (alarmSpeechTimer) {
    window.clearInterval(alarmSpeechTimer)
    alarmSpeechTimer = null
  }
  if ('speechSynthesis' in window) {
    window.speechSynthesis.cancel()
  }
}

function startAlarm() {
  stopAlarm()
  playLoudAlarmTone()
  speakAlarm()
  alarmToneTimer = window.setInterval(playLoudAlarmTone, 2600)
  alarmSpeechTimer = window.setInterval(speakAlarm, 9000)
}

async function enableAlarmAudio() {
  await ensureAlarmAudioContext()
  if (alarmActive.value) {
    startAlarm()
  }
}

function repeatAlarmNow() {
  playLoudAlarmTone()
  speakAlarm()
}

function unlockAlarmAudio() {
  enableAlarmAudio().catch(() => {
    alarmSoundBlocked.value = true
  })
}

watch(alarmKey, key => {
  if (key) {
    startAlarm()
  } else {
    stopAlarm()
  }
}, { immediate: true })

onMounted(() => {
  bedStore.loadBeds()
  timer = window.setInterval(() => bedStore.loadBeds(), 3000)
  clockTimer = window.setInterval(() => {
    now.value = new Date()
  }, 1000)
  window.addEventListener('pointerdown', unlockAlarmAudio, { once: true })
  window.addEventListener('keydown', unlockAlarmAudio, { once: true })
})

onBeforeUnmount(() => {
  if (timer) window.clearInterval(timer)
  if (clockTimer) window.clearInterval(clockTimer)
  stopAlarm()
  window.removeEventListener('pointerdown', unlockAlarmAudio)
  window.removeEventListener('keydown', unlockAlarmAudio)
})
</script>

<style scoped>
.ward-screen {
  min-height: 100vh;
  padding: 28px;
  color: #102033;
  background:
    linear-gradient(180deg, rgba(230, 247, 250, 0.92), rgba(244, 248, 251, 0.98)),
    #f4f8fb;
}

.ward-screen.alarm-active {
  box-shadow: inset 0 0 0 8px rgba(220, 38, 38, 0.18);
}

.screen-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 18px;
}

.eyebrow {
  margin: 0 0 8px;
  color: #0f8f85;
  font-size: 13px;
  font-weight: 900;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.screen-header h1 {
  margin: 0;
  color: #0f172a;
  font-size: clamp(32px, 3.4vw, 56px);
}

.subtitle {
  margin: 10px 0 0;
  color: #64748b;
  font-size: 17px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 14px;
}

.clock-card {
  min-width: 214px;
  padding: 14px 18px;
  border: 1px solid #d9e6ee;
  border-radius: 18px;
  background: #ffffff;
  box-shadow: 0 10px 28px rgba(15, 23, 42, 0.08);
}

.clock-card span {
  display: block;
  color: #64748b;
  font-size: 12px;
}

.clock-card strong {
  display: block;
  margin-top: 2px;
  color: #0f172a;
  font-size: 30px;
  letter-spacing: 0.04em;
}

button {
  border: 0;
  border-radius: 999px;
  padding: 13px 20px;
  color: #ffffff;
  background: #0f8f85;
  font-weight: 900;
  cursor: pointer;
  box-shadow: 0 10px 22px rgba(15, 143, 133, 0.22);
}

.sound-toggle {
  color: #0f172a;
  background: #ffffff;
  border: 1px solid #d9e6ee;
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.06);
}

.sound-toggle.ready {
  color: #047857;
  background: #d1fae5;
  border-color: #a7f3d0;
}

.sound-toggle.blocked {
  color: #991b1b;
  background: #fee2e2;
  border-color: #fecaca;
  animation: soundButtonPulse 1.2s ease-in-out infinite;
}

.summary-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(150px, 1fr));
  gap: 14px;
  margin-bottom: 14px;
}

.summary-strip article {
  padding: 18px 20px;
  border: 1px solid #dce8ef;
  border-radius: 20px;
  background: #ffffff;
  box-shadow: 0 12px 30px rgba(15, 23, 42, 0.07);
}

.summary-strip span {
  display: block;
  color: #64748b;
  margin-bottom: 6px;
}

.summary-strip strong {
  color: #0f172a;
  font-size: 36px;
}

.summary-strip .online strong { color: #0f8f85; }
.summary-strip .warning strong { color: #d97706; }
.summary-strip .critical strong { color: #dc2626; }
.summary-strip .pulse { animation: subtleRedPulse 1.25s ease-in-out infinite; }

.alert-strip {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 16px;
  padding: 14px 18px;
  border: 1px solid #fecaca;
  border-radius: 18px;
  background: #fff7f7;
}

.voice-button {
  margin-left: auto;
  white-space: nowrap;
  background: #dc2626;
  box-shadow: 0 10px 22px rgba(220, 38, 38, 0.22);
}

.alert-strip > strong {
  color: #991b1b;
  white-space: nowrap;
}

.alert-list {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.alert-list span {
  border-radius: 999px;
  padding: 7px 12px;
  color: #92400e;
  background: #fef3c7;
  font-weight: 800;
}

.alert-list .critical {
  color: #ffffff;
  background: #dc2626;
}

.bed-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(330px, 1fr));
  gap: 18px;
}

.bed-card {
  position: relative;
  overflow: hidden;
  min-height: 380px;
  padding: 18px;
  border: 2px solid #dce8ef;
  border-radius: 24px;
  background: #ffffff;
  box-shadow: 0 14px 34px rgba(15, 23, 42, 0.08);
  cursor: pointer;
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
}

.bed-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 20px 44px rgba(15, 23, 42, 0.12);
}

.bed-card.warning {
  border-color: #f59e0b;
  background: #fffaf0;
}

.bed-card.critical {
  border-color: #ef4444;
  background: #fff7f7;
  animation: criticalCardPulse 1.3s ease-in-out infinite;
}

.bed-card.emergency-alarm {
  border-color: #dc2626;
  background:
    linear-gradient(180deg, rgba(254, 226, 226, 0.96), rgba(255, 247, 247, 0.98)),
    #fff7f7;
  box-shadow: 0 0 0 4px rgba(220, 38, 38, 0.12), 0 18px 46px rgba(220, 38, 38, 0.28);
  animation: emergencyBedFlash 0.95s ease-in-out infinite;
}

.bed-card.offline {
  border-color: #cbd5e1;
  background: #f8fafc;
  opacity: 0.72;
}

.card-status-line {
  position: absolute;
  inset: 0 0 auto 0;
  height: 8px;
  background: #16a34a;
}

.warning .card-status-line { background: #f59e0b; }
.critical .card-status-line { background: #ef4444; }
.emergency-alarm .card-status-line {
  height: 12px;
  background: linear-gradient(90deg, #991b1b, #ef4444, #991b1b);
}
.offline .card-status-line { background: #94a3b8; }

.bed-emergency-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin: 8px 0 12px;
  padding: 10px 12px;
  border: 1px solid #fecaca;
  border-radius: 14px;
  color: #ffffff;
  background: linear-gradient(135deg, #b91c1c, #ef4444);
  box-shadow: 0 10px 22px rgba(220, 38, 38, 0.24);
}

.bed-emergency-banner span {
  font-size: 13px;
  font-weight: 900;
  letter-spacing: 0.1em;
}

.bed-emergency-banner strong {
  font-size: 15px;
  text-align: right;
}

.card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-top: 10px;
}

.room {
  color: #64748b;
  font-size: 13px;
}

.card-head h2 {
  margin: 4px 0 0;
  color: #0f172a;
  font-size: 34px;
}

.status-badge {
  border-radius: 999px;
  padding: 7px 13px;
  color: #047857;
  background: #d1fae5;
}

.warning .status-badge {
  color: #92400e;
  background: #fef3c7;
}

.critical .status-badge {
  color: #ffffff;
  background: #dc2626;
}

.offline .status-badge {
  color: #475569;
  background: #e2e8f0;
}

.patient-line {
  margin: 12px 0 10px;
}

.patient-line strong,
.patient-line span {
  display: block;
}

.patient-line strong {
  color: #102033;
  font-size: 18px;
}

.patient-line span {
  margin-top: 4px;
  color: #64748b;
}

.bed-visual {
  position: relative;
  height: 128px;
  margin: 14px 0 16px;
}

.bed-back {
  position: absolute;
  left: 10px;
  top: 30px;
  width: 42px;
  height: 84px;
  border-radius: 14px 8px 8px 14px;
  background: #bfe7ee;
  border: 2px solid #80cbd7;
}

.bed-mattress {
  position: absolute;
  left: 44px;
  right: 16px;
  top: 42px;
  height: 62px;
  border-radius: 18px;
  background: #eaf8fb;
  border: 2px solid #9dd8e0;
  box-shadow: inset 0 -18px 0 rgba(20, 184, 166, 0.12);
}

.pillow {
  position: absolute;
  left: 14px;
  top: 10px;
  width: 52px;
  height: 32px;
  border-radius: 12px;
  background: #ffffff;
  border: 1px solid #c9e7ed;
}

.blanket {
  position: absolute;
  left: 74px;
  right: 14px;
  top: 9px;
  bottom: 10px;
  border-radius: 14px;
  background: linear-gradient(135deg, #d7f1f5, #a7e1e7);
}

.rail {
  position: absolute;
  top: -9px;
  width: 54px;
  height: 10px;
  border-radius: 999px;
  background: #78c7d2;
}

.rail-left { left: 76px; }
.rail-right { right: 22px; }

.bed-base {
  position: absolute;
  left: 48px;
  right: 28px;
  top: 106px;
  height: 8px;
  border-radius: 999px;
  background: #7aa7b2;
}

.wheel {
  position: absolute;
  top: 113px;
  width: 13px;
  height: 13px;
  border-radius: 50%;
  background: #64748b;
}

.wheel-left { left: 70px; }
.wheel-right { right: 46px; }

.breath-indicator {
  position: absolute;
  left: 142px;
  top: 18px;
  width: 86px;
  height: 28px;
  border-top: 4px solid #0f8f85;
  border-radius: 50%;
  opacity: 0.72;
  animation: calmBreath 2.6s ease-in-out infinite;
}

.warning .breath-indicator { border-color: #d97706; }
.critical .breath-indicator {
  border-color: #dc2626;
  animation-duration: 1.1s;
}
.emergency-alarm .breath-indicator {
  border-color: #dc2626;
  animation: alarmBreath 0.7s ease-in-out infinite;
}
.offline .breath-indicator { display: none; }

.vital-row {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
}

.vital-row div {
  padding: 11px 12px;
  border-radius: 14px;
  background: #f4f8fb;
}

.vital-row span {
  display: block;
  color: #64748b;
  font-size: 12px;
}

.vital-row strong {
  display: block;
  margin-top: 5px;
  color: #0f172a;
  font-size: 17px;
}

.device-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 13px;
}

.device-row span {
  border-radius: 999px;
  padding: 5px 10px;
  color: #64748b;
  background: #e2e8f0;
  font-size: 12px;
  font-weight: 800;
}

.device-row span.on {
  color: #047857;
  background: #d1fae5;
}

.issue-text {
  display: flex;
  align-items: center;
  margin: 14px 0 0;
  color: #475569;
  font-weight: 800;
}

.issue-text::before {
  content: '';
  width: 8px;
  height: 8px;
  margin-right: 8px;
  border-radius: 50%;
  background: #16a34a;
}

.warning .issue-text::before { background: #f59e0b; }
.critical .issue-text::before { background: #ef4444; }
.emergency-alarm .issue-text {
  color: #991b1b;
}
.emergency-alarm .issue-text::before {
  width: 10px;
  height: 10px;
  background: #dc2626;
  box-shadow: 0 0 0 6px rgba(220, 38, 38, 0.14);
}
.offline .issue-text::before { background: #94a3b8; }

@keyframes calmBreath {
  0%, 100% { transform: scaleX(0.88); opacity: 0.45; }
  50% { transform: scaleX(1.08); opacity: 0.9; }
}

@keyframes criticalCardPulse {
  0%, 100% { box-shadow: 0 14px 34px rgba(15, 23, 42, 0.08); }
  50% { box-shadow: 0 14px 38px rgba(220, 38, 38, 0.22); }
}

@keyframes emergencyBedFlash {
  0%, 100% {
    box-shadow: 0 0 0 4px rgba(220, 38, 38, 0.12), 0 18px 46px rgba(220, 38, 38, 0.24);
    transform: translateY(0);
  }
  50% {
    box-shadow: 0 0 0 8px rgba(220, 38, 38, 0.2), 0 24px 58px rgba(220, 38, 38, 0.38);
    transform: translateY(-2px);
  }
}

@keyframes alarmBreath {
  0%, 100% { transform: scaleX(0.82); opacity: 0.45; }
  50% { transform: scaleX(1.18); opacity: 1; }
}

@keyframes subtleRedPulse {
  0%, 100% { border-color: #dce8ef; }
  50% { border-color: #ef4444; }
}

@keyframes soundButtonPulse {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.04); }
}

/* Silver Shield inspired monitoring wall */
.ward-screen {
  --ward-blue: #325bf2;
  --ward-blue-dark: #222e61;
  --ward-ink: #1f2940;
  --ward-muted: #7982a6;
  --ward-line: #e4e9f3;
  --ward-soft: #f5f7fb;
  --ward-red: #e53935;
  --ward-yellow: #f59e0b;
  padding: 24px !important;
  color: var(--ward-ink) !important;
  background:
    radial-gradient(circle at 12% 8%, rgba(50, 91, 242, 0.08), transparent 28%),
    linear-gradient(135deg, #f8f9fc 0%, #eef2f8 52%, #f9fbff 100%) !important;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Microsoft YaHei", sans-serif !important;
}

.screen-header {
  max-width: 1680px;
  margin: 0 auto 18px !important;
  padding: 0 6px;
}

.eyebrow {
  color: var(--ward-blue) !important;
}

.screen-header h1 {
  color: var(--ward-blue-dark) !important;
  font-size: clamp(30px, 3vw, 48px) !important;
  letter-spacing: -0.04em;
}

.subtitle {
  max-width: 680px;
  color: var(--ward-muted) !important;
}

.clock-card,
.sound-toggle,
.header-right > button:not(.sound-toggle) {
  border-color: rgba(121, 130, 166, 0.2) !important;
  background: rgba(255, 255, 255, 0.92) !important;
  box-shadow: 0 14px 34px rgba(34, 46, 97, 0.08) !important;
}

.clock-card strong {
  color: var(--ward-blue-dark) !important;
}

.header-right > button:not(.sound-toggle) {
  color: #ffffff !important;
  background: linear-gradient(135deg, var(--ward-blue), #5ca8ff) !important;
}

.dashboard-frame {
  display: grid;
  grid-template-columns: 74px minmax(0, 1fr);
  gap: 0;
  max-width: 1680px;
  margin: 0 auto;
  min-height: calc(100vh - 158px);
  padding: 16px;
  border: 1px solid rgba(194, 202, 220, 0.72);
  border-radius: 34px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.86), rgba(246, 248, 252, 0.92)),
    #ffffff;
  box-shadow:
    0 30px 80px rgba(34, 46, 97, 0.12),
    inset 0 1px 0 rgba(255, 255, 255, 0.9);
}

.dashboard-rail {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 13px;
  padding: 14px 10px;
  border-right: 1px solid rgba(228, 233, 243, 0.92);
}

.dashboard-rail span {
  display: grid;
  place-items: center;
  width: 42px;
  height: 42px;
  border-radius: 16px;
  color: var(--ward-muted);
  background: #f1f4fa;
  font-size: 12px;
  font-weight: 900;
  letter-spacing: -0.02em;
  transition: transform 0.22s cubic-bezier(0.25, 0.46, 0.45, 0.94), box-shadow 0.22s ease;
}

.dashboard-rail .rail-brand,
.dashboard-rail .active {
  color: #ffffff;
  background: linear-gradient(135deg, var(--ward-blue), #69bdff);
  box-shadow: 0 12px 22px rgba(50, 91, 242, 0.24);
}

.dashboard-rail span:hover {
  transform: translateY(-2px);
}

.dashboard-content {
  min-width: 0;
  padding: 18px 20px 20px;
  border-radius: 28px;
  background:
    linear-gradient(135deg, rgba(248, 250, 255, 0.94), rgba(255, 255, 255, 0.98)),
    #ffffff;
}

.dashboard-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  margin-bottom: 16px;
  padding: 12px 14px;
  border: 1px solid rgba(228, 233, 243, 0.96);
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.88);
}

.toolbar-kicker {
  display: block;
  margin-bottom: 2px;
  color: var(--ward-blue);
  font-size: 11px;
  font-weight: 900;
  letter-spacing: 0.14em;
}

.dashboard-toolbar strong {
  color: var(--ward-blue-dark);
  font-size: 18px;
}

.toolbar-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.toolbar-actions span {
  padding: 8px 12px;
  border: 1px solid rgba(121, 130, 166, 0.18);
  border-radius: 999px;
  color: var(--ward-blue-dark);
  background: #f7f9fd;
  font-size: 12px;
  font-weight: 800;
}

.dashboard-frame .summary-strip {
  grid-template-columns: repeat(4, minmax(126px, 1fr)) !important;
  gap: 12px !important;
  margin-bottom: 14px !important;
}

.dashboard-frame .summary-strip article {
  padding: 14px 16px !important;
  border: 1px solid rgba(228, 233, 243, 0.96) !important;
  border-radius: 18px !important;
  background: #ffffff !important;
  box-shadow: 0 12px 26px rgba(34, 46, 97, 0.06) !important;
}

.dashboard-frame .summary-strip span {
  color: var(--ward-muted) !important;
  font-size: 12px !important;
}

.dashboard-frame .summary-strip strong {
  color: var(--ward-blue-dark) !important;
  font-size: 30px !important;
}

.dashboard-frame .summary-strip .online strong { color: #16a34a !important; }
.dashboard-frame .summary-strip .warning strong { color: var(--ward-yellow) !important; }
.dashboard-frame .summary-strip .critical strong { color: var(--ward-red) !important; }

.dashboard-frame .alert-strip {
  margin-bottom: 14px !important;
  border: 1px solid rgba(229, 57, 53, 0.34) !important;
  border-radius: 18px !important;
  background: linear-gradient(135deg, #fff7f7, #ffffff) !important;
  box-shadow: 0 12px 30px rgba(229, 57, 53, 0.08);
}

.dashboard-frame .bed-grid {
  grid-template-columns: repeat(auto-fill, minmax(258px, 1fr)) !important;
  gap: 14px !important;
}

.dashboard-frame .bed-card {
  min-height: 318px !important;
  padding: 15px !important;
  border: 1.5px solid rgba(228, 233, 243, 0.96) !important;
  border-radius: 22px !important;
  background: #ffffff !important;
  box-shadow: 0 12px 30px rgba(34, 46, 97, 0.07) !important;
}

.dashboard-frame .bed-card:hover {
  transform: translateY(-4px) scale(1.01) !important;
  box-shadow: 0 18px 44px rgba(34, 46, 97, 0.12) !important;
}

.dashboard-frame .bed-card.warning {
  border-color: rgba(245, 158, 11, 0.8) !important;
  background: linear-gradient(180deg, #fffaf0, #ffffff) !important;
}

.dashboard-frame .bed-card.critical,
.dashboard-frame .bed-card.emergency-alarm {
  border-color: rgba(229, 57, 53, 0.9) !important;
  background: linear-gradient(180deg, #fff4f4, #ffffff) !important;
  box-shadow: 0 0 0 4px rgba(229, 57, 53, 0.08), 0 18px 46px rgba(229, 57, 53, 0.18) !important;
}

.dashboard-frame .bed-card.offline {
  background: #f7f8fb !important;
  opacity: 0.68 !important;
}

.dashboard-frame .card-status-line {
  height: 5px !important;
  background: var(--ward-blue) !important;
}

.dashboard-frame .warning .card-status-line { background: var(--ward-yellow) !important; }
.dashboard-frame .critical .card-status-line,
.dashboard-frame .emergency-alarm .card-status-line { background: var(--ward-red) !important; }
.dashboard-frame .offline .card-status-line { background: #b8c0d2 !important; }

.dashboard-frame .card-head {
  margin-top: 6px !important;
}

.dashboard-frame .room {
  color: var(--ward-muted) !important;
}

.dashboard-frame .card-head h2 {
  color: var(--ward-blue-dark) !important;
  font-size: 28px !important;
  letter-spacing: -0.04em;
}

.dashboard-frame .status-badge {
  color: var(--ward-blue) !important;
  background: rgba(50, 91, 242, 0.1) !important;
}

.dashboard-frame .warning .status-badge {
  color: #b45309 !important;
  background: #fff3cc !important;
}

.dashboard-frame .critical .status-badge,
.dashboard-frame .emergency-alarm .status-badge {
  color: #ffffff !important;
  background: var(--ward-red) !important;
}

.dashboard-frame .bed-visual {
  height: 92px !important;
  margin: 6px 0 12px !important;
  transform: scale(0.82);
  transform-origin: center;
  opacity: 0.92;
}

.dashboard-frame .bed-back,
.dashboard-frame .bed-mattress {
  border-color: rgba(50, 91, 242, 0.26) !important;
}

.dashboard-frame .bed-back {
  background: #dce8ff !important;
}

.dashboard-frame .bed-mattress {
  background: #f4f8ff !important;
}

.dashboard-frame .blanket {
  background: linear-gradient(135deg, #e7efff, #bcd3ff) !important;
}

.dashboard-frame .breath-indicator {
  border-color: var(--ward-blue) !important;
}

.dashboard-frame .vital-row {
  gap: 8px !important;
}

.dashboard-frame .vital-row div {
  padding: 10px 11px !important;
  border: 1px solid rgba(228, 233, 243, 0.9);
  border-radius: 14px !important;
  background: #f7f9fd !important;
}

.dashboard-frame .vital-row span,
.dashboard-frame .patient-line span,
.dashboard-frame .issue-text,
.dashboard-frame .device-row span {
  color: var(--ward-muted) !important;
}

.dashboard-frame .issue-text::before {
  background: #16a34a !important;
}

.dashboard-frame .issue-text.temp-warn::before {
  background: var(--ward-yellow) !important;
}

.dashboard-frame .vital-row strong,
.dashboard-frame .patient-line strong {
  color: var(--ward-blue-dark) !important;
}

.dashboard-frame .temp-abnormal strong {
  color: var(--ward-yellow) !important;
  font-weight: 900;
}

.dashboard-frame .temp-abnormal span {
  color: var(--ward-yellow) !important;
}

.dashboard-frame .device-row span.on {
  color: #1f8f63 !important;
  background: #e7f8ef !important;
}

.dashboard-frame .bed-emergency-banner {
  border-color: rgba(229, 57, 53, 0.28) !important;
  background: linear-gradient(135deg, #f04438, #e53935) !important;
}

@media (max-width: 980px) {
  .screen-header,
  .header-right,
  .alert-strip {
    align-items: stretch;
    flex-direction: column;
  }

  .summary-strip {
    grid-template-columns: repeat(2, 1fr);
  }

  .dashboard-frame {
    grid-template-columns: 1fr;
    padding: 12px;
  }

  .dashboard-rail {
    flex-direction: row;
    justify-content: flex-start;
    border-right: 0;
    border-bottom: 1px solid rgba(228, 233, 243, 0.92);
    overflow-x: auto;
  }

  .dashboard-toolbar,
  .toolbar-actions {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
