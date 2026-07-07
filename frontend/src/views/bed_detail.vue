<template>
  <div class="bed-detail care-page-shell">
    <section class="bed-hero care-glass-card care-icon-card" :class="bed?.risk_level" data-icon="BED">
      <div>
        <button class="back-btn" @click="router.push('/manage/nurse_station')">返回监视台</button>
        <p class="eyebrow">{{ bed?.room || '护理房间' }}</p>
        <h1>{{ bed?.bed_label || bedStore.selectedBedLabel }} · {{ bed?.patient_name || '未登记患者' }}</h1>
        <p>这些按钮会控制独立的开发板模拟端；模拟端再通过真实接口向后端上报数据。</p>
      </div>
      <div class="risk-panel">
        <span>{{ riskLabel(bed?.risk_level) }}</span>
        <strong>{{ bed?.primary_issue || '监护正常' }}</strong>
      </div>
    </section>

    <section class="quick-grid">
      <article class="quick-card care-glass-card care-icon-card" data-icon="HR">
        <span>心率</span>
        <strong>{{ formatValue(bed?.heart_rate, 'BPM') }}</strong>
      </article>
      <article class="quick-card care-glass-card care-icon-card" data-icon="BR">
        <span>呼吸</span>
        <strong>{{ formatValue(bed?.breath_rate, 'RPM') }}</strong>
      </article>
      <article class="quick-card care-glass-card care-icon-card" data-icon="ENV">
        <span>温湿度</span>
        <strong>{{ formatEnv(bed) }}</strong>
      </article>
      <article class="quick-card care-glass-card care-icon-card" data-icon="SN">
        <span>呼噜</span>
        <strong>{{ bed?.snore_detected ? '检测中' : '正常' }}</strong>
      </article>
    </section>

    <section v-if="isSimBed" class="demo-panel care-glass-card care-icon-card" data-icon="SIM">
      <div>
        <p class="eyebrow">Demo Controls</p>
        <h2>模拟开发板场景</h2>
        <p>这些按钮会控制独立的开发板模拟端；模拟端再通过真实接口向后端上报数据。</p>
      </div>
      <div class="demo-actions">
        <button
          v-for="item in demoScenarios"
          :key="item.scenario"
          :class="{ active: currentScenario === item.scenario, danger: item.danger }"
          :disabled="scenarioLoading"
          @click="setScenario(item.scenario)"
        >
          {{ item.label }}
        </button>
      </div>
    </section>

    <section class="action-grid">
      <button class="care-icon-card" data-icon="HR" @click="go('/manage/heart_pic')">实时生命体征</button>
      <button class="care-icon-card" data-icon="BR" @click="go('/manage/sleep_dashboard')">睡眠看护</button>
      <button class="care-icon-card" data-icon="ENV" @click="go('/manage/environment_analysis')">环境数据</button>
      <button class="danger care-icon-card" data-icon="SOS" @click="go('/manage/alert_center')">告警处理</button>
      <button class="care-icon-card" data-icon="LOG" @click="go('/manage/data')">历史记录</button>
    </section>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { useBedStore } from '@/stores/bedStore'

const route = useRoute()
const router = useRouter()
const bedStore = useBedStore()
let timer = null
const scenarioLoading = ref(false)
const currentScenario = ref('normal')
const simBoardBaseUrl = (import.meta.env.VITE_SIM_BOARD_BASE_URL || 'http://127.0.0.1:8092').replace(/\/$/, '')

const bed = computed(() => bedStore.selectedBed)
const isSimBed = computed(() => bedStore.selectedBedId === 'bed-sim-001' || bed.value?.status?.simulated)
const demoScenarios = [
  { label: '正常监护', scenario: 'normal' },
  { label: '模拟呼噜', scenario: 'snore' },
  { label: '模拟呼吸暂停', scenario: 'apnea', danger: true },
  { label: '呼噜停止异常', scenario: 'snore_stop_breath_drop', danger: true },
  { label: '模拟温度过高', scenario: 'temp_high', danger: true },
  { label: '模拟温度过低', scenario: 'temp_low', danger: true },
  { label: '夜间离床', scenario: 'night_absence', danger: true },
  { label: '模拟语音求救', scenario: 'emergency_voice', danger: true },
  { label: '模拟摇晃', scenario: 'board_fall', danger: true },
  { label: '模拟离线', scenario: 'offline' }
]

function riskLabel(level) {
  return {
    critical: '待处理紧急事件',
    warning: '需要关注',
    offline: '设备离线',
    normal: '状态稳定'
  }[level] || '状态稳定'
}

function formatValue(value, unit) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '--'
  return `${Number(value).toFixed(0)} ${unit}`
}

function formatEnv(item) {
  const temp = item?.temperature_c
  const hum = item?.humidity_pct
  if (temp === null || temp === undefined || hum === null || hum === undefined) return '--'
  return `${Number(temp).toFixed(1)}℃ / ${Number(hum).toFixed(0)}%`
}

function go(path) {
  router.push({ path, query: { bed_id: bedStore.selectedBedId } })
}

async function setScenario(scenario) {
  scenarioLoading.value = true
  try {
    const response = await fetch(`${simBoardBaseUrl}/scenario`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scenario })
    })
    if (!response.ok) throw new Error(`sim board http ${response.status}`)
    currentScenario.value = scenario
    await bedStore.loadBeds()
    ElMessage.success('模拟开发板场景已切换')
  } catch (error) {
    console.error('switch demo scenario failed:', error)
    ElMessage.error('模拟开发板未连接，请先启动：python tools\\simulated_bed_board.py --backend http://127.0.0.1:8081')
  } finally {
    scenarioLoading.value = false
  }
}


onMounted(() => {
  bedStore.setSelectedBed(route.params.bedId)
  bedStore.loadBeds()
  timer = window.setInterval(() => bedStore.loadBeds(), 3000)
})

onBeforeUnmount(() => {
  if (timer) window.clearInterval(timer)
})
</script>

<style scoped>
.bed-detail {
  display: grid;
  gap: 18px;
}

.bed-hero {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 22px;
  padding: 28px;
}

.back-btn {
  border: 0;
  border-radius: 999px;
  padding: 8px 14px;
  color: #0f8f85;
  background: #e0f7f4;
  font-weight: 800;
  cursor: pointer;
}

.eyebrow {
  margin: 14px 0 6px;
  color: #0f9f82;
  font-weight: 800;
}

.bed-hero h1 {
  margin: 0;
  color: #0f172a;
  font-size: 34px;
}

.bed-hero p {
  color: #64748b;
}

.risk-panel {
  min-width: 220px;
  border-radius: 20px;
  padding: 18px;
  background: #f8fafc;
  border: 1px solid rgba(15, 143, 133, 0.14);
}

.risk-panel span {
  color: #64748b;
}

.risk-panel strong {
  display: block;
  color: #0f172a;
  margin-top: 10px;
  font-size: 22px;
}

.critical .risk-panel {
  background: #fff1f2;
  border-color: rgba(220, 38, 38, 0.28);
}

.critical .risk-panel strong {
  color: #dc2626;
}

.quick-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 14px;
}

.quick-card {
  padding: 18px;
}

.quick-card span {
  color: #64748b;
}

.quick-card strong {
  display: block;
  margin-top: 8px;
  color: #0f172a;
  font-size: 26px;
}

.demo-panel {
  display: grid;
  grid-template-columns: minmax(220px, 0.8fr) minmax(360px, 1.4fr);
  gap: 18px;
  align-items: center;
  padding: 22px;
  background:
    radial-gradient(circle at 8% 20%, rgba(56, 189, 248, 0.18), transparent 34%),
    rgba(255, 255, 255, 0.9);
}

.demo-panel h2 {
  margin: 0;
  color: #0f172a;
}

.demo-panel p {
  color: #64748b;
}

.demo-actions {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: 10px;
}

.demo-actions button {
  min-height: 52px;
  border: 1px solid rgba(15, 143, 133, 0.16);
  border-radius: 16px;
  color: #0f172a;
  background: #ffffff;
  font-weight: 900;
  cursor: pointer;
  transition: transform 0.2s ease, background 0.2s ease, color 0.2s ease;
}

.demo-actions button:hover {
  transform: translateY(-2px);
}

.demo-actions button.active {
  color: #ffffff;
  background: linear-gradient(135deg, #0f9f82, #38bdf8);
}

.demo-actions button.danger.active {
  background: linear-gradient(135deg, #dc2626, #fb7185);
}

.demo-actions button:disabled {
  cursor: wait;
  opacity: 0.7;
}

.action-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 14px;
}

.action-grid button {
  min-height: 82px;
  border: 0;
  border-radius: 22px;
  background: linear-gradient(135deg, #ffffff, #eefafa);
  color: #0f172a;
  font-size: 18px;
  font-weight: 900;
  box-shadow: 0 10px 28px rgba(15, 59, 72, 0.09);
  cursor: pointer;
  transition: transform 0.2s ease;
}

.action-grid button:hover {
  transform: translateY(-3px);
}

.action-grid .danger {
  color: #dc2626;
  background: linear-gradient(135deg, #fff, #fff1f2);
}
</style>
