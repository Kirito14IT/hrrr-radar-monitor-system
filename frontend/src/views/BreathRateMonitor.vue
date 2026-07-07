<template>
  <div class="monitor-card" :class="{ active: isPresent && hasRate && vitalsState !== 'lost' }">
    <div class="monitor-header">
      <div class="lung-visual" :style="{ '--breath-duration': breathDuration }">
        <span class="lung-halo"></span>
        <svg class="lung-illustration" viewBox="0 0 72 72" aria-hidden="true">
          <path class="trachea" d="M36 8v19M36 27c-6 2-10 8-12 16M36 27c6 2 10 8 12 16" />
          <path
            class="lung left"
            d="M31 31c-7 2-15 10-17 21-1 7 2 12 7 12 7 0 12-9 12-20 0-5-.7-9-2-13Z"
          />
          <path
            class="lung right"
            d="M41 31c7 2 15 10 17 21 1 7-2 12-7 12-7 0-12-9-12-20 0-5 .7-9 2-13Z"
          />
        </svg>
      </div>
      <div>
        <span class="title">呼吸监测</span>
        <small>{{ statusText }}</small>
      </div>
    </div>

    <div class="data-row">
      <div class="value-group">
        <span class="value" :style="{ color: statusColor }">
          {{ isPresent && hasRate ? rate.toFixed(1) : '--' }}
        </span>
        <span class="unit">RPM</span>
      </div>
      <div class="status-tag" :style="{ backgroundColor: statusBg, color: statusColor }">
        {{ statusText }}
      </div>
    </div>

    <div class="scale-box">
      <div class="scale-track">
        <div class="scale-bar" :style="{ width: fillPercent + '%', backgroundColor: statusColor }"></div>
      </div>
      <div class="scale-labels"><span>0</span><span>20</span><span>40</span></div>
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
  if (props.rate < 10) return '偏慢'
  if (props.rate > 24) return '偏快'
  return '信号稳定'
})

const statusColor = computed(() => {
  if (!props.isPresent || props.vitalsState === 'lost' || !hasRate.value) return 'var(--care-muted)'
  if (recovering.value) return 'var(--care-warning)'
  if (props.rate < 10 || props.rate > 24) return 'var(--care-warning)'
  return 'var(--care-accent)'
})

const statusBg = computed(() => {
  if (!props.isPresent || props.vitalsState === 'lost' || !hasRate.value) return 'var(--care-surface-muted)'
  if (recovering.value || props.rate < 10 || props.rate > 24) return 'var(--care-warning-soft)'
  return 'var(--care-accent-soft)'
})

const fillPercent = computed(() => {
  if (!props.isPresent || props.vitalsState === 'lost' || !hasRate.value || props.rate === 0) return 0
  return Math.min((props.rate / 40) * 100, 100)
})

const breathDuration = computed(() => {
  if (!hasRate.value || props.rate <= 0) return '4s'
  return `${Math.max(2.0, Math.min(6.0, 60 / props.rate)).toFixed(2)}s`
})
</script>

<style scoped>
.monitor-card {
  width: 100%;
  height: 100%;
  box-sizing: border-box;
  background: linear-gradient(135deg, rgba(255, 255, 255, .96), rgba(239, 253, 255, .9));
  color: var(--care-text);
  border-radius: var(--care-radius-md);
  border: 1px solid var(--care-border-soft);
  padding: 16px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  transition: background .3s ease, border-color .3s ease, box-shadow .3s ease;
}

.monitor-card.active {
  box-shadow: 0 18px 42px rgba(14, 165, 233, .08);
}

.monitor-header {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 10px;
}

.lung-visual {
  position: relative;
  width: 58px;
  height: 58px;
  display: grid;
  place-items: center;
  color: var(--care-accent);
}

.lung-halo {
  position: absolute;
  inset: 4px;
  border-radius: 999px;
  background: var(--care-accent-soft);
  animation: lungHalo var(--breath-duration, 4s) ease-in-out infinite;
}

.lung-illustration {
  position: relative;
  z-index: 1;
  width: 48px;
  height: 48px;
  overflow: visible;
  filter: drop-shadow(0 8px 18px rgba(14, 165, 233, .2));
  animation: lungFloat var(--breath-duration, 4s) ease-in-out infinite;
}

.trachea {
  fill: none;
  stroke: currentColor;
  stroke-width: 4;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.lung {
  fill: color-mix(in srgb, currentColor 72%, white);
  stroke: currentColor;
  stroke-width: 2.5;
  transform-origin: 36px 44px;
  animation: lungExpand var(--breath-duration, 4s) ease-in-out infinite;
}

.title {
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

.data-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  margin-bottom: 15px;
}

.value {
  font-size: 38px;
  font-weight: 850;
  line-height: 1;
  letter-spacing: -.04em;
  transition: color .3s;
}

.unit {
  font-size: 14px;
  color: var(--care-muted);
  margin-left: 4px;
}

.status-tag {
  padding: 4px 9px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}

.scale-box { height: 30px; }
.scale-track { height: 6px; background: var(--care-surface-muted); border-radius: 3px; overflow: hidden; margin-bottom: 4px; }
.scale-bar { height: 100%; transition: width .5s ease; }
.scale-labels { display: flex; justify-content: space-between; font-size: 10px; color: var(--care-muted); }

@keyframes lungExpand {
  0%, 100% { transform: scaleX(.94) scaleY(.92); opacity: .82; }
  50% { transform: scaleX(1.06) scaleY(1.08); opacity: 1; }
}

@keyframes lungFloat {
  0%, 100% { transform: translateY(1px); }
  50% { transform: translateY(-2px); }
}

@keyframes lungHalo {
  0%, 100% { transform: scale(.88); opacity: .32; }
  50% { transform: scale(1.15); opacity: .14; }
}
</style>
