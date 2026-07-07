<template>
  <div class="ward-status-bar">
    <div class="ward-clock">
      <span>护理台</span>
      <strong>{{ timeText }}</strong>
    </div>
    <div class="ward-stat">
      <span>床位</span>
      <strong>{{ bedStore.summary.total }}</strong>
    </div>
    <div class="ward-stat online">
      <span>在线</span>
      <strong>{{ bedStore.summary.online }}</strong>
    </div>
    <div class="ward-stat warning">
      <span>关注</span>
      <strong>{{ bedStore.summary.warning }}</strong>
    </div>
    <div class="ward-stat danger" :class="{ pulse: bedStore.summary.critical > 0 }">
      <span>紧急</span>
      <strong>{{ bedStore.summary.critical }}</strong>
    </div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useBedStore } from '@/stores/bedStore'

const bedStore = useBedStore()
const timeText = ref('')
let timer = null

function updateTime() {
  timeText.value = new Date().toLocaleString('zh-CN', {
    hour12: false,
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })
}

onMounted(() => {
  updateTime()
  bedStore.loadBeds()
  timer = window.setInterval(() => {
    updateTime()
    bedStore.loadBeds()
  }, 3000)
})

onBeforeUnmount(() => {
  if (timer) window.clearInterval(timer)
})
</script>

<style scoped>
.ward-status-bar {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}

.ward-clock,
.ward-stat {
  min-width: 74px;
  border: 1px solid rgba(21, 128, 128, 0.16);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.78);
  padding: 8px 12px;
  box-shadow: 0 8px 22px rgba(15, 59, 72, 0.08);
}

.ward-clock {
  min-width: 150px;
}

.ward-clock span,
.ward-stat span {
  display: block;
  color: #64748b;
  font-size: 12px;
  line-height: 1;
  margin-bottom: 4px;
}

.ward-clock strong,
.ward-stat strong {
  color: #0f172a;
  font-size: 18px;
  line-height: 1.1;
}

.ward-stat.online strong { color: #0f9f82; }
.ward-stat.warning strong { color: #d97706; }
.ward-stat.danger strong { color: #dc2626; }

.pulse {
  animation: alarmPulse 1.25s ease-in-out infinite;
}

@keyframes alarmPulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(220, 38, 38, 0.22); }
  50% { box-shadow: 0 0 0 8px rgba(220, 38, 38, 0.06); }
}
</style>
