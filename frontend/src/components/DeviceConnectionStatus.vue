<template>
  <div class="device-connection-status" aria-label="设备连接状态">
    <span class="status-chip" :class="radarClass"><i></i>雷达板 {{ radarText }}</span>
    <span class="status-chip" :class="edgiClass"><i></i>Edgi E84 {{ edgiText }}</span>
    <span class="status-chip" :class="environmentClass"><i></i>温湿度 {{ environmentText }}</span>
    <span class="status-chip" :class="snoreClass"><i></i>呼噜 {{ snoreText }}</span>
    <span v-if="state.emergency_active" class="status-chip danger"><i></i>紧急中</span>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive } from 'vue'
import request from '@/utils/request'

const state = reactive({
  radar_board_online: false,
  radar_board_stationary: true,
  edgi_board_online: false,
  environment_board_online: false,
  snore_board_online: false,
  voice_board_online: false,
  snore_monitoring: false,
  snore_paused: false,
  snore_detected: false,
  emergency_active: false,
  temperature_c: null,
  humidity_pct: null
})

let timer = null

const isFiniteNumber = value => typeof value === 'number' && Number.isFinite(value)
const radarUnstable = computed(() => Boolean(state.radar_board_online && state.radar_board_stationary === false))
const edgiOnline = computed(() => Boolean(
  state.edgi_board_online ||
  state.environment_board_online ||
  state.snore_board_online ||
  state.voice_board_online
))

const radarText = computed(() => {
  if (!state.radar_board_online) return '离线'
  return radarUnstable.value ? '未静止' : '在线'
})

const edgiText = computed(() => {
  if (!edgiOnline.value) return '离线'
  if (state.emergency_active) return '紧急'
  return '在线'
})

const environmentText = computed(() => {
  if (!state.environment_board_online) return '离线'
  const temp = isFiniteNumber(state.temperature_c) ? `${state.temperature_c.toFixed(1)}℃` : '--℃'
  const humidity = isFiniteNumber(state.humidity_pct) ? `${Math.round(state.humidity_pct)}%` : '--%'
  return `${temp}/${humidity}`
})

const snoreText = computed(() => {
  if (!state.snore_board_online && !state.snore_monitoring) return '离线'
  if (state.snore_detected) return '检测到'
  if (state.snore_paused) return '暂停'
  return '监测中'
})

const radarClass = computed(() => ({
  online: state.radar_board_online && !radarUnstable.value,
  warning: radarUnstable.value,
  offline: !state.radar_board_online
}))

const edgiClass = computed(() => ({
  online: edgiOnline.value && !state.emergency_active,
  warning: state.emergency_active,
  offline: !edgiOnline.value
}))

const environmentClass = computed(() => ({
  online: state.environment_board_online,
  offline: !state.environment_board_online
}))

const snoreClass = computed(() => ({
  online: (state.snore_board_online || state.snore_monitoring) && !state.snore_detected,
  warning: state.snore_detected,
  offline: !state.snore_board_online && !state.snore_monitoring
}))

const fetchStatus = async () => {
  try {
    const data = await request.get('/status')
    Object.assign(state, data || {})
  } catch (error) {
    Object.assign(state, {
      radar_board_online: false,
      edgi_board_online: false,
      environment_board_online: false,
      snore_board_online: false,
      voice_board_online: false,
      snore_monitoring: false,
      emergency_active: false
    })
  }
}

onMounted(() => {
  fetchStatus()
  timer = window.setInterval(fetchStatus, 3000)
})

onBeforeUnmount(() => {
  if (timer) window.clearInterval(timer)
})
</script>

<style scoped>
.device-connection-status {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}

.status-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 28px;
  padding: 4px 10px;
  border: 1px solid var(--care-border);
  border-radius: 999px;
  background: var(--care-surface-strong);
  color: var(--care-muted);
  font-size: 12px;
  font-weight: 800;
  white-space: nowrap;
}

.status-chip i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
  box-shadow: 0 0 10px currentColor;
}

.status-chip.online {
  color: var(--care-success);
  border-color: var(--care-success);
  background: var(--care-success-soft);
}

.status-chip.warning {
  color: var(--care-warning);
  border-color: var(--care-warning);
  background: var(--care-warning-soft);
}

.status-chip.danger {
  color: #fff;
  border-color: var(--care-danger);
  background: var(--care-danger);
}

.status-chip.offline {
  color: var(--care-muted);
  opacity: 0.78;
}

@media (max-width: 1180px) {
  .device-connection-status {
    justify-content: flex-start;
    width: 100%;
  }
}
</style>
