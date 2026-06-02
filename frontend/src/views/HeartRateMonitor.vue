<template>
  <div class="heart-rate-monitor">
    <div class="monitor-header">
      <svg class="heart-icon" viewBox="0 0 24 24" fill="currentColor"><path d="M12,21.35L10.55,20.03C5.4,15.36 2,12.27 2,8.5C2,5.41 4.42,3 7.5,3C9.24,3 10.91,3.81 12,5.08C13.09,3.81 14.76,3 16.5,3C19.58,3 22,5.41 22,8.5C22,12.27 18.6,15.36 13.45,20.03L12,21.35Z" /></svg>
      <span class="title-text">心率监测</span>
    </div>

    <div class="monitor-subtitle">实时心率数据</div>

    <div class="heart-rate-data">
      <div class="rate-display">
        <span class="rate-value" :style="{color: statusColor}">
          {{ isPresent && hasRate ? rate.toFixed(2) : '--' }}
        </span>
        <span class="rate-unit">BPM</span>
      </div>

      <div class="status-indicator" :class="statusClass" :style="{color: statusColor}">
        {{ statusText }}
      </div>
    </div>

    <div class="heart-rate-scale">
      <div class="scale-container">
        <div class="scale-fill" :style="{width: fillPercentage + '%', backgroundColor: statusColor}"></div>
      </div>
      <div class="scale-marks"><span>60</span><span>80</span><span>100</span><span>120</span></div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue';

const props = defineProps({
  rate: { type: Number, default: null },
  isPresent: { type: Boolean, default: true }
});

const hasRate = computed(() => typeof props.rate === 'number' && Number.isFinite(props.rate));

const statusText = computed(() => {
  if (!props.isPresent || !hasRate.value) return '未检测到生命体征';
  if (props.rate === 0) return '过缓';
  if (props.rate < 60) return '过缓';
  if (props.rate < 100) return '正常';
  return '过快';
});

const statusColor = computed(() => {
  if (!props.isPresent || !hasRate.value) return 'var(--care-muted)';
  if (props.rate === 0) return 'var(--care-warning)';
  if (props.rate < 60) return 'var(--care-warning)';
  if (props.rate < 100) return 'var(--care-success)';
  return 'var(--care-danger)';
});

const statusClass = computed(() => {
  if (!props.isPresent || !hasRate.value) return 'abnormal-text';
  if (props.rate < 60) return 'status-slow';
  if (props.rate < 100) return 'status-normal';
  return 'status-fast';
});

const fillPercentage = computed(() => {
  if (!props.isPresent || !hasRate.value || props.rate === 0) return 0;
  return Math.min(((props.rate - 60) / 60) * 100, 100);
});
</script>

<style scoped>
.heart-rate-monitor {
  width: 100%;
  height: 100%;
  box-sizing: border-box;
  background: var(--care-surface-strong);
  color: var(--care-text);
  border-radius: var(--care-radius-md);
  border: 1px solid var(--care-border-soft);
  padding: 16px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  transition: background 0.3s ease, color 0.3s ease, border-color 0.3s ease;
}
.monitor-header {
  background: var(--care-danger-soft);
  padding: 8px 12px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  margin-bottom: 10px;
}
.heart-icon {
  width: 18px;
  height: 18px;
  color: var(--care-danger);
  margin-right: 8px;
}
.title-text {
  font-size: 16px;
  font-weight: bold;
  color: var(--care-text-strong);
}
.monitor-subtitle {
  font-size: 12px;
  color: var(--care-muted);
  margin-bottom: 10px;
}
.heart-rate-data {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  margin-bottom: 15px;
}

/* ✅ 修改：稍微缩小字号以容纳 .00 */
.rate-value { font-size: 36px; font-weight: bold; line-height: 1; }

.rate-unit { font-size: 14px; color: var(--care-muted); margin-left: 4px; }
.status-indicator { padding: 4px 8px; border-radius: 12px; font-size: 12px; font-weight: bold; white-space: nowrap; }
.status-normal { background: var(--care-success-soft); }
.status-slow { background: var(--care-warning-soft); }
.status-fast { background: var(--care-danger-soft); }
.abnormal-text { background: var(--care-surface-muted); }
.heart-rate-scale { position: relative; height: 30px; }
.scale-container { height: 6px; background: var(--care-surface-muted); border-radius: 3px; overflow: hidden; }
.scale-fill { height: 100%; border-radius: 3px; transition: width 0.5s ease; }
.scale-marks { display: flex; justify-content: space-between; margin-top: 4px; font-size: 10px; color: var(--care-muted); }
</style>
