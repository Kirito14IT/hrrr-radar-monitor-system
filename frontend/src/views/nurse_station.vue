<template>
  <div class="nurse-station care-page-shell">
    <section class="station-hero care-glass-card care-icon-card" data-icon="BED">
      <div>
        <p class="eyebrow">Care Monitoring Console</p>
        <h1>床位监视屏</h1>
        <p>集中查看每个床位的生命体征、设备在线状态和待处理异常事件。</p>
      </div>
      <div class="hero-stats">
        <div><span>总床位</span><strong>{{ summary.total }}</strong></div>
        <div><span>设备在线</span><strong>{{ summary.online }}</strong></div>
        <div class="danger"><span>待处理</span><strong>{{ summary.critical }}</strong></div>
        <button class="screen-entry" @click="router.push('/ward-screen')">进入监护大屏</button>
      </div>
    </section>

    <section v-if="bedStore.error" class="station-error care-glass-card care-icon-card" data-icon="!">
      {{ bedStore.error }}
    </section>

    <section class="bed-grid">
      <article
        v-for="bed in beds"
        :key="bed.bed_id"
        class="bed-card care-glass-card care-icon-card"
        data-icon="BED"
        :class="[isTempAbnormal(bed) && bed.risk_level === 'normal' ? 'warning' : bed.risk_level, { selected: bed.bed_id === bedStore.selectedBedId }]"
        @click="openBed(bed)"
      >
        <div class="bed-card-top">
          <div>
            <span class="room">{{ bed.room || '护理房间' }}</span>
            <h2>{{ bed.bed_label || bed.bed_id }}</h2>
          </div>
          <div class="badge-stack">
            <span v-if="isSimBed(bed)" class="sim-badge">模拟</span>
            <span class="risk-badge">{{ isTempAbnormal(bed) && bed.risk_level === 'normal' ? '关注' : riskLabel(bed.risk_level) }}</span>
          </div>
        </div>

        <div class="patient-row">
          <strong>{{ bed.patient_name || '未登记患者' }}</strong>
          <span>{{ patientMeta(bed) }}</span>
        </div>

        <div class="vital-grid">
          <div>
            <span>心率</span>
            <strong>{{ formatValue(bed.heart_rate, 'BPM') }}</strong>
          </div>
          <div>
            <span>呼吸</span>
            <strong>{{ formatValue(bed.breath_rate, 'RPM') }}</strong>
          </div>
          <div :class="{ 'temp-abnormal': isTempAbnormal(bed) }">
            <span>温度</span>
            <strong>{{ formatValue(bed.temperature_c, '℃') }}</strong>
          </div>
          <div>
            <span>湿度</span>
            <strong>{{ formatValue(bed.humidity_pct, '%') }}</strong>
          </div>
        </div>

        <div class="device-row">
          <span :class="{ on: bed.radar_board_online }">雷达</span>
          <span :class="{ on: bed.edgi_board_online }">小智</span>
          <span :class="{ on: bed.snore_board_online }">呼噜</span>
          <span :class="{ on: bed.environment_board_online }">环境</span>
        </div>

        <div class="issue-row">
          <i :class="{ warning: isTempAbnormal(bed) }"></i>
          <span>{{ tempIssueText(bed) || bed.primary_issue || '监护正常' }}</span>
        </div>
      </article>
    </section>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useBedStore } from '@/stores/bedStore'
import { useAlertPolicyStore } from '@/stores/alertPolicyStore'

const router = useRouter()
const bedStore = useBedStore()
const alertPolicy = useAlertPolicyStore()
let timer = null

const beds = computed(() => bedStore.beds)
const summary = computed(() => bedStore.summary)

function riskLabel(level) {
  return {
    critical: '紧急',
    warning: '关注',
    offline: '离线',
    normal: '正常'
  }[level] || '正常'
}

function isSimBed(bed) {
  return bed?.bed_id === 'bed-sim-001' || bed?.status?.simulated
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

function patientMeta(bed) {
  const parts = [bed.patient_gender, bed.patient_age ? `${bed.patient_age}岁` : ''].filter(Boolean)
  return parts.join(' / ') || '持续监护'
}

function formatValue(value, unit) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '--'
  return `${Number(value).toFixed(unit === '℃' ? 1 : 0)} ${unit}`
}

function openBed(bed) {
  bedStore.setSelectedBed(bed.bed_id)
  router.push(`/manage/bed/${bed.bed_id}`)
}

onMounted(() => {
  bedStore.loadBeds()
  timer = window.setInterval(() => bedStore.loadBeds(), 3000)
})

onBeforeUnmount(() => {
  if (timer) window.clearInterval(timer)
})
</script>

<style scoped>
.nurse-station {
  display: grid;
  gap: 18px;
}

.station-hero {
  min-height: 150px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 28px;
  background:
    radial-gradient(circle at 8% 15%, rgba(22, 183, 169, 0.18), transparent 34%),
    linear-gradient(135deg, #ffffff, #eefafa);
}

.eyebrow {
  margin: 0 0 8px;
  color: #0f9f82;
  font-size: 13px;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.station-hero h1 {
  margin: 0;
  color: #0f172a;
  font-size: 38px;
}

.station-hero p {
  color: #64748b;
}

.hero-stats {
  display: flex;
  align-items: stretch;
  gap: 12px;
}

.hero-stats div {
  min-width: 104px;
  padding: 16px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.82);
  border: 1px solid rgba(22, 183, 169, 0.14);
}

.hero-stats span {
  display: block;
  color: #64748b;
  margin-bottom: 8px;
}

.hero-stats strong {
  color: #0f172a;
  font-size: 30px;
}

.hero-stats .danger strong {
  color: #dc2626;
}

.screen-entry {
  border: 0;
  border-radius: 18px;
  padding: 0 20px;
  color: #ffffff;
  background: linear-gradient(135deg, #0f9f82, #0284c7);
  font-weight: 900;
  cursor: pointer;
  box-shadow: 0 16px 34px rgba(14, 116, 144, 0.22);
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.screen-entry:hover {
  transform: translateY(-2px);
  box-shadow: 0 20px 42px rgba(14, 116, 144, 0.28);
}

.station-error {
  padding: 16px;
  color: #dc2626;
}

.bed-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(290px, 1fr));
  gap: 18px;
}

.bed-card {
  position: relative;
  overflow: hidden;
  padding: 20px;
  cursor: pointer;
  border: 1px solid rgba(15, 143, 133, 0.16);
  transition: transform 0.22s ease, box-shadow 0.22s ease, border-color 0.22s ease;
}

.bed-card::before {
  content: '';
  position: absolute;
  inset: auto -20% -42% -20%;
  height: 110px;
  background: radial-gradient(circle, rgba(22, 183, 169, 0.16), transparent 68%);
  animation: breatheGlow 3.2s ease-in-out infinite;
}

.bed-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 18px 50px rgba(15, 59, 72, 0.13);
}

.bed-card.selected {
  border-color: #0f9f82;
}

.bed-card.critical {
  border-color: rgba(220, 38, 38, 0.7);
  box-shadow: 0 0 0 1px rgba(220, 38, 38, 0.12), 0 18px 48px rgba(220, 38, 38, 0.12);
}

.bed-card.critical::before {
  background: radial-gradient(circle, rgba(220, 38, 38, 0.2), transparent 68%);
  animation-duration: 1.15s;
}

.bed-card.warning {
  border-color: rgba(217, 119, 6, 0.55);
}

.bed-card.offline {
  filter: saturate(0.72);
  opacity: 0.78;
}

.bed-card-top,
.patient-row,
.device-row,
.issue-row {
  position: relative;
  z-index: 1;
}

.bed-card-top {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.room {
  color: #64748b;
  font-size: 13px;
}

.bed-card h2 {
  margin: 4px 0 0;
  color: #0f172a;
  font-size: 30px;
}

.risk-badge {
  align-self: flex-start;
  border-radius: 999px;
  padding: 6px 12px;
  background: #e0f7f4;
  color: #0f8f85;
  font-weight: 800;
}

.badge-stack {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 8px;
}

.sim-badge {
  border-radius: 999px;
  padding: 5px 10px;
  color: #0369a1;
  background: #e0f2fe;
  font-size: 12px;
  font-weight: 900;
  letter-spacing: 0.08em;
}

.critical .risk-badge {
  background: #fee2e2;
  color: #dc2626;
}

.warning .risk-badge {
  background: #fef3c7;
  color: #b45309;
}

.offline .risk-badge {
  background: #e2e8f0;
  color: #64748b;
}

.patient-row {
  margin: 16px 0;
}

.patient-row strong,
.patient-row span {
  display: block;
}

.patient-row strong {
  color: #102333;
  font-size: 18px;
}

.patient-row span {
  color: #64748b;
  margin-top: 4px;
}

.vital-grid {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
}

.vital-grid div {
  padding: 12px;
  border-radius: 14px;
  background: rgba(248, 250, 252, 0.78);
}

.vital-grid span {
  color: #64748b;
  font-size: 12px;
}

.vital-grid strong {
  display: block;
  margin-top: 6px;
  color: #0f172a;
  font-size: 17px;
}

.temp-abnormal strong {
  color: #d97706;
  font-weight: 900;
}

.temp-abnormal span {
  color: #d97706;
}

.device-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 14px;
}

.device-row span {
  border-radius: 999px;
  padding: 5px 10px;
  background: #e2e8f0;
  color: #64748b;
  font-size: 12px;
  font-weight: 700;
}

.device-row span.on {
  background: #d1fae5;
  color: #047857;
}

.issue-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 16px;
  color: #475569;
}

.issue-row i {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #16a34a;
}

.critical .issue-row i { background: #dc2626; }
.warning .issue-row i { background: #d97706; }
.issue-row i.warning { background: #d97706; }
.offline .issue-row i { background: #94a3b8; }

@keyframes breatheGlow {
  0%, 100% { transform: scale(0.96); opacity: 0.62; }
  50% { transform: scale(1.06); opacity: 1; }
}
</style>
