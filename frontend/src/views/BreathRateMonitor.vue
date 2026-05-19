<template>
  <div class="monitor-card">
    <div class="monitor-header">
      <svg class="icon" viewBox="0 0 24 24" fill="currentColor"><path d="M12,2C7.03,2 3,6.03 3,11C3,16.55 7.85,22 12,22C16.15,22 21,16.55 21,11C21,6.03 16.97,2 12,2M12,20C8.95,20 5,15.53 5,11C5,7.13 8.13,4 12,4C15.87,4 19,7.13 19,11C19,15.53 15.05,20 12,20Z" /></svg>
      <span class="title">呼吸监测</span>
    </div>

    <div class="subtitle">实时呼吸频率</div>

    <div class="data-row">
      <div class="value-group">
        <span class="value" :style="{color: statusColor}">
          {{ isPresent && hasRate ? rate.toFixed(2) : '--' }}
        </span>
        <span class="unit">RPM</span>
      </div>
      <div class="status-tag" :style="{backgroundColor: statusBg, color: statusColor}">
        {{ statusText }}
      </div>
    </div>

    <div class="scale-box">
      <div class="scale-track">
        <div class="scale-bar" :style="{width: fillPercent + '%', backgroundColor: statusColor}"></div>
      </div>
      <div class="scale-labels"><span>0</span><span>20</span><span>40</span></div>
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
  if (props.rate < 10) return '过缓';
  if (props.rate > 24) return '急促';
  return '正常';
});

const statusColor = computed(() => {
  if (!props.isPresent || !hasRate.value) return '#999999';
  if (props.rate === 0) return '#faad14';
  if (props.rate < 10 || props.rate > 24) return '#faad14';
  return '#1890ff';
});

const statusBg = computed(() => {
  if (!props.isPresent || !hasRate.value) return '#f5f5f5';
  if (props.rate === 0 || props.rate < 10 || props.rate > 24) return '#fff7e6';
  return '#e6f7ff';
});

const fillPercent = computed(() => {
  if (!props.isPresent || !hasRate.value || props.rate === 0) return 0;
  return Math.min((props.rate / 40) * 100, 100);
});
</script>

<style scoped>
.monitor-card { width: 100%; height: 100%; box-sizing: border-box; background: #fff; border-radius: 12px; border: 1px solid #f0f0f0; padding: 16px; display: flex; flex-direction: column; justify-content: space-between; }
.monitor-header { display: flex; align-items: center; background: #e6f7ff; padding: 8px 12px; border-radius: 8px; margin-bottom: 10px; }
.icon { width: 18px; height: 18px; margin-right: 8px; color: #1890ff; }
.title { font-size: 16px; font-weight: bold; color: #333; }
.subtitle { font-size: 12px; color: #999; margin-bottom: 10px; }
.data-row { display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: 15px; }

/* ✅ 修改：字号调整为 36px */
.value { font-size: 36px; font-weight: bold; line-height: 1; transition: color 0.3s; }

.unit { font-size: 14px; color: #999; margin-left: 4px; }
.status-tag { padding: 4px 8px; border-radius: 12px; font-size: 12px; font-weight: 600; white-space: nowrap; }
.scale-box { height: 30px; }
.scale-track { height: 6px; background: #f5f5f5; border-radius: 3px; overflow: hidden; margin-bottom: 4px; }
.scale-bar { height: 100%; transition: width 0.5s ease; }
.scale-labels { display: flex; justify-content: space-between; font-size: 10px; color: #ccc; }
</style>
