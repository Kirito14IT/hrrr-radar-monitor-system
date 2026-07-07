<template>
  <div class="layout-container">
    <aside class="sidebar" aria-label="主导航">
      <div
        class="sidebar-header"
        @mouseenter="startApneaHoverTrigger"
        @mouseleave="cancelApneaHoverTrigger"
      >
        <img src="@/assets/logo.svg" alt="睡眠看护系统 Logo" class="logo" />
        <div class="brand-copy">
          <strong>Radar Care</strong>
          <span>生命体征监测</span>
        </div>
      </div>

      <nav class="menu-container">
        <el-menu
          router
          :default-active="activePath"
          class="el-menu-vertical"
          :background-color="menuBg"
          :text-color="menuText"
          :active-text-color="menuActive"
        >
          <el-menu-item index="/manage/project_intro">
            <span class="menu-motion-icon project" aria-hidden="true"><i></i></span>
            <span>项目首页</span>
          </el-menu-item>
          <el-menu-item index="/manage/heart_pic">
            <span class="menu-motion-icon vitals" aria-hidden="true"><i></i></span>
            <span>生命体征监测</span>
          </el-menu-item>
          <el-menu-item index="/manage/sleep_dashboard">
            <span class="menu-motion-icon sleep" aria-hidden="true"><i></i></span>
            <span>睡眠看护驾驶舱</span>
          </el-menu-item>
          <el-menu-item index="/manage/alert_center">
            <span class="menu-motion-icon alert" aria-hidden="true"><i></i></span>
            <span>看护预警中心</span>
          </el-menu-item>
          <el-menu-item index="/manage/environment_analysis">
            <span class="menu-motion-icon environment" aria-hidden="true"><i></i></span>
            <span>睡眠环境分析</span>
          </el-menu-item>
          <el-menu-item index="/manage/data">
            <span class="menu-motion-icon history" aria-hidden="true"><i></i></span>
            <span>历史数据</span>
          </el-menu-item>
        </el-menu>
      </nav>

      <div class="sidebar-footer">
        <span class="status-dot"></span>
        <div>
          <strong>雷达 + Edgi E84 看护</strong>
        </div>
      </div>
    </aside>

    <main class="main-content">
      <header class="top-bar">
        <div class="top-bar-title">
          <span class="page-motion-icon" :class="currentPageIcon" aria-hidden="true"><i></i></span>
          <strong>{{ route.meta.title || '睡眠看护系统' }}</strong>
          <span v-if="currentBedLabel" class="bed-chip">
            <span class="bed-chip-icon" aria-hidden="true">🛏</span>
            {{ currentBedLabel }}
          </span>
        </div>
        <div class="top-bar-actions">
          <button
            class="bed-monitor-entry"
            :class="{ active: route.path === '/manage/nurse_station' }"
            @click="router.push('/manage/nurse_station')"
          >
            床位监视
          </button>
          <WardStatusBar />
        </div>
      </header>

      <section class="content-area">
        <RouterView />
      </section>
    </main>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import WardStatusBar from '@/components/WardStatusBar.vue'
import { useBedStore } from '@/stores/bedStore'
import request from '@/utils/request'

const route = useRoute()
const router = useRouter()
const bedStore = useBedStore()
const activePath = computed(() => route.path)
const pageIconByPath = {
  '/manage/project_intro': 'project',
  '/manage/heart_pic': 'vitals',
  '/manage/sleep_dashboard': 'sleep',
  '/manage/alert_center': 'alert',
  '/manage/environment_analysis': 'environment',
  '/manage/data': 'history',
  '/manage/nurse_station': 'nurse'
}
const currentPageIcon = computed(() => {
  if (route.path.startsWith('/manage/bed')) return 'nurse'
  return pageIconByPath[route.path] || 'project'
})

const currentBedLabel = computed(() => {
  const bed = bedStore.selectedBed
  if (!bed) return ''
  const label = bed.bed_label || bed.bed_id || ''
  const patient = bed.patient_name || ''
  return patient ? `${label} · ${patient}` : label
})

const menuBg = computed(() => 'transparent')
const menuText = computed(() => 'var(--care-sidebar-text)')
const menuActive = computed(() => 'var(--care-sidebar-text-active)')

const HOVER_TRIGGER_DELAY_MS = 5000
const APNEA_TRIGGER_COOLDOWN_MS = 10000
const EMERGENCY_POLL_MS = 3000
const EMERGENCY_TONE_REPEAT_MS = 4000

let apneaHoverTimer = null
let apneaTriggering = false
let lastApneaTriggeredAt = 0
let emergencyPollTimer = null
let emergencyToneTimer = null
let lastEmergencySoundKey = ''
let acknowledgedEmergencyKey = ''
let emergencyDialogKey = ''
let emergencyDialogOpen = false
let emergencyDialogClosingBySystem = false
let alarmAudioContext = null

const isEdgiOnline = status => Boolean(
  status?.edgi_board_online ||
  status?.snore_board_online ||
  status?.environment_board_online ||
  status?.voice_board_online
)

const fetchDeviceStatus = () => request.get('/status')

const isActiveEmergencyEvent = event => Boolean(event && (event.status || 'active') === 'active')

const emergencySoundKey = event => {
  if (!event) return ''
  return [
    event.eventID,
    event.fingerprint,
    event.type,
    event.timestamp,
    event.message,
  ].filter(value => value !== null && value !== undefined && value !== '').join(':')
}

const emergencyTitleText = event => {
  if (event?.type === 'suspected_apnea') return '疑似呼吸暂停，请立即观察'
  if (event?.type === 'snore_stop_breath_drop') return '呼噜停止伴随呼吸信号跌破阈值'
  if (event?.type === 'night_absence') return '夜间疑似离床，请立即确认'
  if (event?.type === 'emergency_voice') return '紧急求助已触发'
  if (event?.type === 'board_fall') return '开发板摇晃报警'
  return event?.title || '紧急报警'
}

const emergencySourceText = event => {
  if (event?.type === 'suspected_apnea' && event?.details?.demo) return '疑似呼吸暂停'
  if (event?.type === 'suspected_apnea') return '雷达与呼噜融合检测'
  if (event?.type === 'snore_stop_breath_drop') return '呼噜与雷达融合检测'
  if (event?.type === 'night_absence') return '雷达存在性夜间离床监护'
  if (event?.type === 'emergency_voice') return '小智语音开发板'
  if (event?.type === 'board_fall') return '小智摇晃检测'
  return event?.source || '看护系统'
}

const formatEmergencyTime = value => {
  if (!value) return '--'
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString('zh-CN', { hour12: false })
}

const emergencyMessageText = event => {
  const message = event?.message || event?.title || '检测到紧急报警事件。'
  return [
    message,
    '',
    `触发时间：${formatEmergencyTime(event?.timestamp)}`,
    `事件来源：${emergencySourceText(event)}`,
    '',
    '请立即确认床旁情况。',
  ].join('\n')
}

const ensureAlarmAudioContext = async () => {
  const AudioContextClass = window.AudioContext || window.webkitAudioContext
  if (!AudioContextClass) return null
  if (!alarmAudioContext) {
    alarmAudioContext = new AudioContextClass()
  }
  if (alarmAudioContext.state === 'suspended') {
    await alarmAudioContext.resume()
  }
  return alarmAudioContext
}

const unlockAlarmAudio = () => {
  ensureAlarmAudioContext().catch(() => {})
}

const playEmergencyTone = async () => {
  try {
    const context = await ensureAlarmAudioContext()
    if (!context) return

    const start = context.currentTime
    const master = context.createGain()
    master.gain.setValueAtTime(0.0001, start)
    master.gain.exponentialRampToValueAtTime(0.18, start + 0.02)
    master.gain.exponentialRampToValueAtTime(0.0001, start + 1.35)
    master.connect(context.destination)

    ;[0, 0.36, 0.72].forEach((offset, index) => {
      const oscillator = context.createOscillator()
      const gain = context.createGain()
      const toneStart = start + offset
      const toneEnd = toneStart + 0.22

      oscillator.type = 'sine'
      oscillator.frequency.setValueAtTime(index === 1 ? 1040 : 880, toneStart)
      gain.gain.setValueAtTime(0.0001, toneStart)
      gain.gain.exponentialRampToValueAtTime(1, toneStart + 0.015)
      gain.gain.exponentialRampToValueAtTime(0.0001, toneEnd)

      oscillator.connect(gain)
      gain.connect(master)
      oscillator.start(toneStart)
      oscillator.stop(toneEnd + 0.03)
    })
  } catch (error) {
    console.warn('Emergency tone playback was blocked:', error)
  }
}

const stopEmergencyTone = () => {
  if (emergencyToneTimer) {
    window.clearInterval(emergencyToneTimer)
    emergencyToneTimer = null
  }
}

const startEmergencyTone = () => {
  stopEmergencyTone()
  playEmergencyTone()
  emergencyToneTimer = window.setInterval(playEmergencyTone, EMERGENCY_TONE_REPEAT_MS)
}

const showEmergencyDialog = (event, key) => {
  if (!key || acknowledgedEmergencyKey === key) return
  if (emergencyDialogOpen && emergencyDialogKey === key) return

  if (emergencyDialogOpen) {
    emergencyDialogClosingBySystem = true
    ElMessageBox.close()
  }

  emergencyDialogOpen = true
  emergencyDialogKey = key
  emergencyDialogClosingBySystem = false

  ElMessageBox.alert(emergencyMessageText(event), emergencyTitleText(event), {
    type: 'error',
    customClass: 'care-emergency-message-box',
    confirmButtonText: '知道了，前往预警中心',
    closeOnClickModal: false,
    closeOnPressEscape: false,
    showClose: false,
    autofocus: true,
  }).then(() => {
    if (emergencyDialogClosingBySystem) return
    acknowledgedEmergencyKey = key
    stopEmergencyTone()
    router.push('/manage/alert_center').catch(() => {})
  }).catch(() => {
    // Programmatic close when the backend resolves the event.
  }).finally(() => {
    if (emergencyDialogKey === key) {
      emergencyDialogOpen = false
      emergencyDialogKey = ''
      emergencyDialogClosingBySystem = false
    }
  })
}

const pollEmergencySound = async () => {
  try {
    const status = await fetchDeviceStatus()
    const event = status?.active_emergency
    if (!status?.emergency_active || !isActiveEmergencyEvent(event)) {
      lastEmergencySoundKey = ''
      acknowledgedEmergencyKey = ''
      stopEmergencyTone()
      if (emergencyDialogOpen) {
        emergencyDialogClosingBySystem = true
        ElMessageBox.close()
      }
      return
    }

    const key = emergencySoundKey(event)
    if (key && key !== lastEmergencySoundKey) {
      lastEmergencySoundKey = key
      acknowledgedEmergencyKey = ''
      startEmergencyTone()
      showEmergencyDialog(event, key)
      return
    }

    if (key && acknowledgedEmergencyKey !== key && !emergencyToneTimer) {
      startEmergencyTone()
    }
    if (key) {
      showEmergencyDialog(event, key)
    }
  } catch (error) {
    console.warn('Failed to poll emergency status:', error)
  }
}

const cancelApneaHoverTrigger = () => {
  if (apneaHoverTimer) {
    window.clearTimeout(apneaHoverTimer)
    apneaHoverTimer = null
  }
}

const triggerDemoApnea = async () => {
  if (apneaTriggering) return

  const now = Date.now()
  const cooldownRemaining = APNEA_TRIGGER_COOLDOWN_MS - (now - lastApneaTriggeredAt)
  if (cooldownRemaining > 0) {
    ElMessage.warning(`紧急事件请 ${Math.ceil(cooldownRemaining / 1000)} 秒后再试`)
    return
  }

  apneaTriggering = true
  try {
    const status = await fetchDeviceStatus()
    if (!status?.radar_board_online || !isEdgiOnline(status)) {
      return
    }

    lastApneaTriggeredAt = Date.now()
    await request.post('/demo/apnea', {
      source: 'brand_hover_debug',
      duration_seconds: 8,
      note: 'Radar Care logo hover for 5 seconds',
    })
    ElMessage.success('呼吸暂停事件')
  } catch (error) {
    console.error('Failed to trigger demo apnea event:', error)
    ElMessage.error('请确认后端已启动')
  } finally {
    apneaTriggering = false
  }
}

const startApneaHoverTrigger = () => {
  cancelApneaHoverTrigger()
  apneaHoverTimer = window.setTimeout(() => {
    apneaHoverTimer = null
    triggerDemoApnea()
  }, HOVER_TRIGGER_DELAY_MS)
}

onMounted(() => {
  pollEmergencySound()
  emergencyPollTimer = window.setInterval(pollEmergencySound, EMERGENCY_POLL_MS)
  window.addEventListener('pointerdown', unlockAlarmAudio, { once: true })
  window.addEventListener('keydown', unlockAlarmAudio, { once: true })
})

onBeforeUnmount(() => {
  cancelApneaHoverTrigger()
  if (emergencyPollTimer) window.clearInterval(emergencyPollTimer)
  stopEmergencyTone()
  if (emergencyDialogOpen) {
    emergencyDialogClosingBySystem = true
    ElMessageBox.close()
  }
  window.removeEventListener('pointerdown', unlockAlarmAudio)
  window.removeEventListener('keydown', unlockAlarmAudio)
})
</script>

<style scoped>
.layout-container {
  display: flex;
  min-height: 100vh;
  background: var(--care-page-gradient);
  color: var(--care-text);
  transition: background 0.35s ease, color 0.35s ease;
}

.sidebar {
  position: sticky;
  top: 0;
  width: 280px;
  height: 100vh;
  display: flex;
  flex-direction: column;
  padding: 18px 14px;
  color: var(--care-sidebar-text);
  background: var(--care-sidebar-bg);
  box-shadow: 10px 0 34px var(--care-shadow-color, rgba(7, 24, 39, 0.18));
  z-index: 10;
  border-right: 1px solid var(--care-border-soft);
  transition: background 0.35s ease, color 0.35s ease, box-shadow 0.35s ease;
}

.sidebar-header {
  display: grid;
  grid-template-columns: 58px 1fr;
  gap: 12px;
  align-items: center;
  padding: 12px 10px 22px;
  border-bottom: 1px solid var(--care-sidebar-divider);
}

.logo {
  width: 58px;
  height: 58px;
  object-fit: contain;
  filter: drop-shadow(0 12px 24px var(--care-accent-soft));
}

.brand-copy {
  display: grid;
  gap: 3px;
}

.brand-copy strong {
  font-size: 20px;
  color: var(--care-sidebar-text-strong);
}

.brand-copy span,
.sidebar-footer small,
.top-kicker {
  color: var(--care-sidebar-muted);
  font-size: 14px;
}

.menu-container {
  flex: 1;
  padding-top: 18px;
}

.el-menu-vertical {
  border-right: none;
  background: transparent;
}

.el-menu-item {
  min-height: 52px;
  margin: 8px 0;
  border-radius: 16px;
  font-size: 17px;
  font-weight: 700;
  color: var(--care-sidebar-text);
  background: transparent !important;
  transition: transform 0.18s ease, background 0.18s ease, box-shadow 0.18s ease, color 0.18s ease;
}

.el-menu-item:hover {
  transform: translateX(3px);
  background: var(--care-sidebar-hover) !important;
  color: var(--care-sidebar-text-active) !important;
}

.el-menu-item.is-active {
  background: var(--care-sidebar-active) !important;
  color: var(--care-sidebar-text-active) !important;
  box-shadow: 0 12px 28px var(--care-accent-soft);
}

.menu-motion-icon,
.page-motion-icon {
  --icon-color: #325bf2;
  --icon-bg: rgba(50, 91, 242, 0.10);
  --icon-ring: rgba(50, 91, 242, 0.18);
  position: relative;
  flex: 0 0 auto;
  display: inline-grid;
  place-items: center;
  border: 1px solid var(--icon-ring);
  background:
    radial-gradient(circle at 30% 25%, rgba(255, 255, 255, .92), transparent 38%),
    var(--icon-bg);
  color: var(--icon-color);
  overflow: hidden;
}

.menu-motion-icon {
  width: 32px;
  height: 32px;
  margin-right: 12px;
  border-radius: 12px;
  box-shadow: inset 0 0 0 1px rgba(255,255,255,.56);
}

.page-motion-icon {
  width: 42px;
  height: 42px;
  border-radius: 16px;
  box-shadow: 0 10px 22px rgba(50, 91, 242, .12);
}

.menu-motion-icon::after,
.page-motion-icon::after {
  content: '';
  position: absolute;
  inset: 6px;
  border-radius: inherit;
  border: 1px solid currentColor;
  opacity: .10;
  animation: iconSoftPulse 2.8s ease-in-out infinite;
}

.menu-motion-icon i,
.page-motion-icon i,
.menu-motion-icon i::before,
.menu-motion-icon i::after,
.page-motion-icon i::before,
.page-motion-icon i::after {
  content: '';
  position: absolute;
  display: block;
  box-sizing: border-box;
}

.menu-motion-icon.project i,
.page-motion-icon.project i {
  width: 15px;
  height: 17px;
  border: 2px solid currentColor;
  border-radius: 6px 6px 8px 8px;
  transform: translateY(1px);
}

.menu-motion-icon.project i::before,
.page-motion-icon.project i::before {
  width: 7px;
  height: 2px;
  left: 2px;
  top: 4px;
  border-radius: 999px;
  background: currentColor;
  box-shadow: 0 5px 0 currentColor;
  opacity: .72;
}

.menu-motion-icon.vitals i,
.page-motion-icon.vitals i {
  width: 18px;
  height: 12px;
  border-left: 2px solid currentColor;
  border-bottom: 2px solid currentColor;
  transform: translateY(2px);
}

.menu-motion-icon.vitals i::before,
.page-motion-icon.vitals i::before {
  width: 18px;
  height: 10px;
  left: 0;
  top: 0;
  border-bottom: 2px solid currentColor;
  clip-path: polygon(0 62%, 24% 62%, 36% 24%, 51% 86%, 65% 45%, 100% 45%, 100% 68%, 70% 68%, 54% 100%, 36% 42%, 30% 76%, 0 76%);
  background: currentColor;
  opacity: .82;
  animation: vitalLine 1.8s ease-in-out infinite;
}

.menu-motion-icon.sleep i,
.page-motion-icon.sleep i {
  width: 17px;
  height: 17px;
  border-radius: 50%;
  background: currentColor;
  transform: translateX(-2px);
}

.menu-motion-icon.sleep i::before,
.page-motion-icon.sleep i::before {
  width: 17px;
  height: 17px;
  left: 6px;
  top: -2px;
  border-radius: 50%;
  background: #ffffff;
}

.menu-motion-icon.alert,
.page-motion-icon.alert {
  --icon-color: #e23744;
  --icon-bg: rgba(226, 55, 68, 0.10);
  --icon-ring: rgba(226, 55, 68, 0.18);
}

.menu-motion-icon.alert i,
.page-motion-icon.alert i {
  width: 16px;
  height: 15px;
  border: 2px solid currentColor;
  border-radius: 9px 9px 5px 5px;
  transform-origin: 50% 0;
  animation: bellNudge 2.4s ease-in-out infinite;
}

.menu-motion-icon.alert i::before,
.page-motion-icon.alert i::before {
  width: 7px;
  height: 3px;
  left: 3px;
  bottom: -6px;
  border-radius: 999px;
  background: currentColor;
}

.menu-motion-icon.environment,
.page-motion-icon.environment {
  --icon-color: #27b36a;
  --icon-bg: rgba(39, 179, 106, 0.10);
  --icon-ring: rgba(39, 179, 106, 0.18);
}

.menu-motion-icon.environment i,
.page-motion-icon.environment i {
  width: 2px;
  height: 18px;
  border-radius: 999px;
  background: currentColor;
  transform: translateY(2px);
}

.menu-motion-icon.environment i::before,
.page-motion-icon.environment i::before,
.menu-motion-icon.environment i::after,
.page-motion-icon.environment i::after {
  width: 10px;
  height: 14px;
  top: 2px;
  border: 2px solid currentColor;
  border-radius: 10px 10px 2px 10px;
  animation: leafSway 2.8s ease-in-out infinite;
}

.menu-motion-icon.environment i::before,
.page-motion-icon.environment i::before {
  right: 1px;
  transform: rotate(-42deg);
}

.menu-motion-icon.environment i::after,
.page-motion-icon.environment i::after {
  left: 1px;
  transform: scaleX(-1) rotate(-42deg);
}

.menu-motion-icon.history i,
.page-motion-icon.history i {
  width: 18px;
  height: 18px;
  border: 2px solid currentColor;
  border-radius: 50%;
}

.menu-motion-icon.history i::before,
.page-motion-icon.history i::before {
  width: 2px;
  height: 6px;
  left: 7px;
  top: 4px;
  border-radius: 999px;
  background: currentColor;
  transform-origin: 50% 100%;
  animation: clockTick 3s steps(6) infinite;
}

.menu-motion-icon.history i::after,
.page-motion-icon.history i::after {
  width: 6px;
  height: 2px;
  left: 7px;
  top: 9px;
  border-radius: 999px;
  background: currentColor;
}

.menu-motion-icon.nurse i,
.page-motion-icon.nurse i {
  width: 19px;
  height: 12px;
  border: 2px solid currentColor;
  border-radius: 5px;
  transform: translateY(3px);
}

.menu-motion-icon.nurse i::before,
.page-motion-icon.nurse i::before {
  width: 8px;
  height: 6px;
  left: -2px;
  top: -7px;
  border: 2px solid currentColor;
  border-bottom: 0;
  border-radius: 5px 5px 0 0;
}

.menu-motion-icon.nurse i::after,
.page-motion-icon.nurse i::after {
  width: 22px;
  height: 2px;
  left: -3px;
  bottom: -5px;
  border-radius: 999px;
  background: currentColor;
}

.sidebar-footer {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: auto;
  padding: 14px;
  border-radius: 18px;
  background: var(--care-sidebar-footer-bg);
  border: 1px solid var(--care-sidebar-divider);
  color: var(--care-sidebar-text);
}

.status-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--care-success);
  box-shadow: 0 0 16px var(--care-success);
}

.main-content {
  min-width: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
}

.top-bar {
  position: sticky;
  top: 0;
  z-index: 5;
  min-height: 64px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 12px 16px 0;
  padding: 0 22px;
  border: 1px solid var(--care-border);
  border-radius: 22px;
  background: var(--care-surface);
  box-shadow: var(--care-shadow-soft);
  backdrop-filter: blur(12px);
  transition: background 0.35s ease, border-color 0.35s ease, box-shadow 0.35s ease;
}

.top-bar-title {
  display: flex;
  align-items: center;
  gap: 12px;
}

.top-bar strong {
  color: var(--care-text-strong);
  font-size: 20px;
}

.bed-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-left: 8px;
  padding: 5px 14px;
  border: 1px solid rgba(15, 143, 133, 0.22);
  border-radius: 999px;
  background: linear-gradient(135deg, rgba(15, 143, 133, 0.08), rgba(2, 132, 199, 0.06));
  color: #0f725e;
  font-size: 14px;
  font-weight: 800;
  white-space: nowrap;
}

.bed-chip-icon {
  font-size: 15px;
  line-height: 1;
}

@keyframes iconSoftPulse {
  0%, 100% { transform: scale(.86); opacity: .08; }
  50% { transform: scale(1.06); opacity: .22; }
}

@keyframes vitalLine {
  0%, 100% { transform: translateX(-1px); opacity: .72; }
  50% { transform: translateX(1px); opacity: 1; }
}

@keyframes bellNudge {
  0%, 78%, 100% { transform: rotate(0deg); }
  82% { transform: rotate(-8deg); }
  86% { transform: rotate(7deg); }
  90% { transform: rotate(-4deg); }
}

@keyframes leafSway {
  0%, 100% { opacity: .75; }
  50% { opacity: 1; }
}

@keyframes clockTick {
  to { transform: rotate(360deg); }
}

.top-bar-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.bed-monitor-entry {
  min-height: 40px;
  padding: 0 16px;
  border: 1px solid var(--care-border);
  border-radius: 999px;
  color: var(--care-text-strong);
  background: var(--care-surface-strong);
  font-size: 14px;
  font-weight: 900;
  cursor: pointer;
  box-shadow: 0 8px 20px rgba(34, 46, 97, 0.06);
  transition: transform .22s ease, box-shadow .22s ease, color .22s ease, background .22s ease, border-color .22s ease;
}

.bed-monitor-entry:hover,
.bed-monitor-entry.active {
  color: #ffffff;
  border-color: transparent;
  background: linear-gradient(135deg, #325bf2, #60a5fa);
  box-shadow: 0 12px 24px rgba(50, 91, 242, .22);
  transform: translateY(-1px);
}

.content-area {
  flex: 1;
  min-width: 0;
  padding: 20px;
  margin: 0 16px 16px;
}

@media (max-width: 920px) {
  .layout-container {
    display: block;
  }

  .sidebar {
    position: relative;
    width: 100%;
    height: auto;
  }

  .content-area {
    margin: 0;
    padding: 16px;
  }

  .top-bar {
    align-items: flex-start;
    flex-direction: column;
    gap: 12px;
    padding: 16px;
  }

  .top-bar-title {
    align-items: center;
  }

  .top-bar-actions {
    justify-content: flex-start;
    width: 100%;
  }
}

:global(.care-emergency-message-box) {
  border: 2px solid var(--care-danger, #ef4444);
  box-shadow: 0 24px 80px rgba(239, 68, 68, 0.34);
}

:global(.care-emergency-message-box .el-message-box__title) {
  color: var(--care-danger, #ef4444);
  font-size: 22px;
  font-weight: 900;
}

:global(.care-emergency-message-box .el-message-box__message) {
  color: var(--care-text, #0f172a);
  font-size: 16px;
  font-weight: 700;
  line-height: 1.75;
  white-space: pre-line;
}

:global(.care-emergency-message-box .el-button--primary) {
  background: var(--care-danger, #ef4444);
  border-color: var(--care-danger, #ef4444);
  font-weight: 900;
}
</style>

<style scoped>
.top-bar {
  background: linear-gradient(135deg, rgba(255,255,255,.92), rgba(238,250,250,.9));
  border-bottom: 1px solid rgba(15, 143, 133, 0.12);
}

.top-bar-title {
  display: flex;
  align-items: center;
  gap: 12px;
}

.top-bar-title strong {
  color: #0f172a;
}

.top-bar-subtitle {
  color: #64748b;
  font-size: 13px;
}
</style>
