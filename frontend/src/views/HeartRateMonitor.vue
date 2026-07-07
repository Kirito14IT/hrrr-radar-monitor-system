<template>
  <div class="heart-rate-monitor" :class="{ active: isPresent && hasRate && vitalsState !== 'lost' }">
    <div class="monitor-header">
      <div class="heart-visual" :style="{ '--beat-duration': beatDuration }">
        <span class="heart-halo"></span>
        <svg class="heart-illustration" viewBox="0 0 64 64" aria-hidden="true">
          <path
            d="M32 56s-4.7-3.1-9.9-7.7C12.1 39.4 6 33.7 6 23.7 6 15.8 12.1 10 19.9 10c4.6 0 9 2.2 12.1 5.8C35.1 12.2 39.5 10 44.1 10 51.9 10 58 15.8 58 23.7c0 10-6.1 15.7-16.1 24.6C36.7 52.9 32 56 32 56Z"
            fill="currentColor"
          />
          <path
            d="M13 32h8l4-8 7 17 5-13h6l3-6 4 10h4"
            fill="none"
            stroke="rgba(255,255,255,.9)"
            stroke-width="3"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
      </div>
      <div>
        <span class="title-text">心率监测</span>
        <small>{{ statusText }}</small>
      </div>
    </div>

    <div class="heart-rate-data">
      <div class="rate-display">
        <span class="rate-value" :style="{ color: statusColor }">
          {{ isPresent && hasRate ? rate.toFixed(1) : '--' }}
        </span>
        <span class="rate-unit">BPM</span>
      </div>
      <div class="status-indicator" :class="statusClass" :style="{ color: statusColor }">
        {{ statusText }}
      </div>
    </div>

    <div class="heart-rate-scale">
      <div class="scale-container">
        <div class="scale-fill" :style="{ width: fillPercentage + '%', backgroundColor: statusColor }"></div>
      </div>
      <div class="scale-marks"><span>60</span><span>80</span><span>100</span><span>120</span></div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  rate: { type: Number, default: null },
  isPresent: { type: Boolean, default: true },
  vitalsState: { type: String, default: 'fresh' }
})

const hasRate = computed(() => typeof props.rate === 'number' && Number.isFinite(props.rate))
const recovering = computed(() => props.vitalsState === 'recovering' && props.isPresent && hasRate.value)

const statusText = computed(() => {
  if (!props.isPresent || props.vitalsState === 'lost' || !hasRate.value) return '暂无生命体征'
  if (recovering.value) return '信号恢复中'
  if (props.rate < 60) return '偏慢'
  if (props.rate < 100) return '信号稳定'
  return '偏快'
})

const statusColor = computed(() => {
  if (!props.isPresent || props.vitalsState === 'lost' || !hasRate.value) return 'var(--care-muted)'
  if (recovering.value) return 'var(--care-warning)'
  if (props.rate < 60) return 'var(--care-warning)'
  if (props.rate < 100) return 'var(--care-success)'
  return 'var(--care-danger)'
})

const statusClass = computed(() => {
  if (!props.isPresent || props.vitalsState === 'lost' || !hasRate.value) return 'abnormal-text'
  if (recovering.value || props.rate < 60) return 'status-slow'
  if (props.rate < 100) return 'status-normal'
  return 'status-fast'
})

const fillPercentage = computed(() => {
  if (!props.isPresent || props.vitalsState === 'lost' || !hasRate.value || props.rate === 0) return 0
  return Math.max(0, Math.min(((props.rate - 60) / 60) * 100, 100))
})

const beatDuration = computed(() => {
  if (!hasRate.value || props.rate <= 0) return '1.2s'
  return `${Math.max(0.48, Math.min(1.4, 60 / props.rate)).toFixed(2)}s`
})
</script>

<style scoped>
.heart-rate-monitor {
  width: 100%;
  height: 100%;
  box-sizing: border-box;
  background: linear-gradient(135deg, rgba(255, 255, 255, .96), rgba(255, 245, 246, .88));
  color: var(--care-text);
  border-radius: var(--care-radius-md);
  border: 1px solid var(--care-border-soft);
  padding: 16px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  transition: background .3s ease, border-color .3s ease, box-shadow .3s ease;
}

.heart-rate-monitor.active {
  box-shadow: 0 18px 42px rgba(239, 68, 68, .08);
}

.monitor-header {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 10px;
}

.heart-visual {
  position: relative;
  width: 58px;
  height: 58px;
  display: grid;
  place-items: center;
  color: var(--care-danger);
}

.heart-halo {
  position: absolute;
  inset: 4px;
  border-radius: 999px;
  background: var(--care-danger-soft);
  animation: heartPulse var(--beat-duration, 1s) ease-in-out infinite;
}

.heart-illustration {
  position: relative;
  z-index: 1;
  width: 42px;
  height: 42px;
  filter: drop-shadow(0 8px 18px rgba(239, 68, 68, .28));
  animation: heartBeat var(--beat-duration, 1s) ease-in-out infinite;
}

.title-text {
  display: block;
  font-size: 16px;
  font-weight: 800;
  color: var(--care-text-strong);
}

.monitor-header small {
  display: block;
  margin-top: 3px;
  font-size: 12px;
  color: var(--care-muted);
}

.heart-rate-data {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  margin-bottom: 15px;
}

.rate-value {
  font-size: 38px;
  font-weight: 850;
  line-height: 1;
  letter-spacing: -.04em;
}

.rate-unit {
  font-size: 14px;
  color: var(--care-muted);
  margin-left: 4px;
}

.status-indicator {
  padding: 4px 9px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}

.status-normal { background: var(--care-success-soft); }
.status-slow { background: var(--care-warning-soft); }
.status-fast { background: var(--care-danger-soft); }
.abnormal-text { background: var(--care-surface-muted); }

.heart-rate-scale { position: relative; height: 30px; }
.scale-container { height: 6px; background: var(--care-surface-muted); border-radius: 3px; overflow: hidden; }
.scale-fill { height: 100%; border-radius: 3px; transition: width .5s ease; }
.scale-marks { display: flex; justify-content: space-between; margin-top: 4px; font-size: 10px; color: var(--care-muted); }

@keyframes heartBeat {
  0%, 100% { transform: scale(1); }
  18% { transform: scale(1.12); }
  32% { transform: scale(.98); }
  48% { transform: scale(1.06); }
}

@keyframes heartPulse {
  0%, 100% { transform: scale(.92); opacity: .46; }
  45% { transform: scale(1.14); opacity: .18; }
}
</style>
