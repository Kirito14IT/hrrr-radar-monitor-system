<template>
  <div class="history-workspace care-page-shell">
    <section class="history-hero care-glass-card">
      <div>
        <div class="care-kicker">Historical Vitals Intelligence</div>
        <h1>历史数据与 AI 洞察</h1>
        <p>
          汇总雷达历史心率与呼吸率，保留跨页面 AI 分析过程，并将本地规则/DeepSeek 报告沉淀为可回看的健康摘要。
        </p>
      </div>
      <div class="hero-status" :class="analysisStatusClass">
        <span>{{ analysisStatusText }}</span>
        <strong>{{ store.aiLoading ? '生成中' : reportStateLabel }}</strong>
      </div>
    </section>

    <div v-if="!userID" class="login-empty care-glass-card">
      <h2>请先登录以查看数据</h2>
      <p>登录后可查询历史生命体征，并启动 AI / 本地健康分析。</p>
    </div>

    <template v-else>
      <section class="toolbar-card care-glass-card">
        <div class="field-block">
          <label for="history-date">日期筛选</label>
          <el-date-picker
            id="history-date"
            v-model="store.date"
            type="date"
            placeholder="请选择要查询的日期"
            value-format="YYYY/MM/DD"
            clearable
          />
        </div>
        <div class="toolbar-actions">
          <el-button type="primary" :loading="store.loading" @click="load">
            查询数据
          </el-button>
          <el-button type="success" :loading="store.aiLoading" @click="runAiAnalysis">
            AI 分析
          </el-button>
          <el-button @click="reset">重置</el-button>
        </div>
        <p v-if="store.error" class="inline-error">{{ store.error }}</p>
      </section>

      <section class="metric-grid">
        <article v-for="card in metricCards" :key="card.key" class="metric-card care-glass-card">
          <span>{{ card.title }}</span>
          <strong>{{ card.value }}</strong>
          <small>{{ card.detail }}</small>
        </article>
      </section>

      <section class="content-grid">
        <article class="table-card care-glass-card">
          <div class="section-heading">
            <div>
              <h2>历史生命体征记录</h2>
              <p>心率与呼吸率已标记偏低、正常、偏高，便于快速定位异常样本。</p>
            </div>
            <el-tag effect="plain" type="info">共 {{ store.total }} 条</el-tag>
          </div>

          <el-table
            v-loading="store.loading"
            :data="store.tableData"
            class="history-table"
            stripe
            empty-text="暂无历史数据，请先运行模拟板并在实时页积累数据。"
          >
            <el-table-column label="数据编号" prop="dataID" min-width="100" />
            <el-table-column label="用户编号" prop="userID" min-width="100" />
            <el-table-column label="日期" min-width="140">
              <template #default="{ row }">
                {{ row.year }}-{{ pad(row.month) }}-{{ pad(row.day) }}
              </template>
            </el-table-column>
            <el-table-column label="心率" min-width="150">
              <template #default="{ row }">
                <span class="vital-cell">
                  <strong>{{ formatNumber(row.bpm_rader) }}</strong>
                  <el-tag size="small" :type="heartTag(row.bpm_rader).type">
                    {{ heartTag(row.bpm_rader).label }}
                  </el-tag>
                </span>
              </template>
            </el-table-column>
            <el-table-column label="呼吸率" min-width="150">
              <template #default="{ row }">
                <span class="vital-cell">
                  <strong>{{ formatNumber(row.bpm_finger) }}</strong>
                  <el-tag size="small" :type="breathTag(row.bpm_finger).type">
                    {{ breathTag(row.bpm_finger).label }}
                  </el-tag>
                </span>
              </template>
            </el-table-column>
          </el-table>

          <div class="pagination-row">
            <el-pagination
              v-model:current-page="store.pageNum"
              v-model:page-size="store.pageSize"
              :page-sizes="[5, 10, 15, 20]"
              background
              layout="total, sizes, prev, pager, next, jumper"
              :total="store.total"
              @size-change="handleSizeChange"
              @current-change="load"
            />
          </div>
        </article>

        <aside class="ai-panel care-glass-card">
          <div class="section-heading compact">
            <div>
              <h2>AI / 本地健康分析</h2>
              <p>离开页面后分析仍会继续，返回本页可看到过程或结果。</p>
            </div>
          </div>

          <div class="provider-row">
            <span v-if="store.aiProvider" class="provider-badge" :class="{ fallback: store.aiFallback }">
              {{ store.aiProviderLabel }}
            </span>
            <span v-if="store.lastAnalyzedAt" class="time-badge">
              {{ formatDateTime(store.lastAnalyzedAt) }}
            </span>
          </div>

          <div v-if="store.aiLoading" class="analysis-loading">
            <el-skeleton :rows="7" animated />
            <p>正在生成分析报告。此过程已经移入 Pinia store，路由切换不会中断页面状态。</p>
          </div>
          <div v-else-if="store.AiData" class="report-box">
            <pre>{{ store.AiData }}</pre>
          </div>
          <div v-else class="analysis-empty">
            <h3>尚未生成报告</h3>
            <p>先查询历史记录，再点击“AI 分析”。未配置 DeepSeek key 时后端会自动返回本地规则分析。</p>
            <el-button type="primary" :disabled="store.tableData.length === 0" @click="runAiAnalysis">
              生成报告
            </el-button>
          </div>

          <div v-if="store.aiError" class="retry-row">
            <span>{{ store.aiError }}</span>
            <el-button size="small" type="warning" @click="runAiAnalysis">重试</el-button>
          </div>
        </aside>
      </section>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { useUserStore } from '@/stores/userStore'
import { useHistoryAnalysisStore } from '@/stores/historyAnalysisStore'

const userStore = useUserStore()
const store = useHistoryAnalysisStore()

const userID = computed(() => userStore.userInfo?.userID || userStore.userInfo?.user_id || null)

const numericValues = (key) => store.tableData
  .map(row => Number(row[key]))
  .filter(value => Number.isFinite(value))

const average = (values) => {
  if (values.length === 0) return null
  return values.reduce((sum, value) => sum + value, 0) / values.length
}

const heartValues = computed(() => numericValues('bpm_rader'))
const breathValues = computed(() => numericValues('bpm_finger'))
const avgHeart = computed(() => average(heartValues.value))
const avgBreath = computed(() => average(breathValues.value))

const abnormalCount = computed(() => store.tableData.filter(row => {
  const heart = Number(row.bpm_rader)
  const breath = Number(row.bpm_finger)
  return (Number.isFinite(heart) && (heart < 55 || heart > 100)) ||
    (Number.isFinite(breath) && (breath < 10 || breath > 24))
}).length)

const metricCards = computed(() => [
  {
    key: 'rows',
    title: '当前页样本',
    value: `${store.tableData.length}`,
    detail: `数据库总计 ${store.total} 条记录`
  },
  {
    key: 'heart',
    title: '平均心率',
    value: avgHeart.value === null ? '--' : `${avgHeart.value.toFixed(1)} BPM`,
    detail: heartValues.value.length ? '正常参考：55-100 BPM' : '等待有效心率样本'
  },
  {
    key: 'breath',
    title: '平均呼吸率',
    value: avgBreath.value === null ? '--' : `${avgBreath.value.toFixed(1)} RPM`,
    detail: breathValues.value.length ? '正常参考：10-24 RPM' : '等待有效呼吸样本'
  },
  {
    key: 'abnormal',
    title: '异常提示',
    value: `${abnormalCount.value}`,
    detail: abnormalCount.value ? '建议结合 AI 报告复核' : '当前页未见明显异常'
  }
])

const reportStateLabel = computed(() => {
  const map = {
    idle: '未分析',
    running: '生成中',
    done: '已完成',
    fallback: '本地兜底',
    failed: '请求失败',
    empty: '暂无数据'
  }
  return map[store.lastAnalysisStatus] || '未分析'
})

const analysisStatusText = computed(() => store.aiLoading ? '跨页面任务保持中' : '最近分析状态')
const analysisStatusClass = computed(() => ({
  running: store.aiLoading,
  fallback: store.aiFallback,
  failed: store.lastAnalysisStatus === 'failed'
}))

function pad(value) {
  return String(value ?? '--').padStart(2, '0')
}

function formatNumber(value) {
  const number = Number(value)
  return Number.isFinite(number) ? number.toFixed(1) : '--'
}

function vitalTag(value, low, high) {
  const number = Number(value)
  if (!Number.isFinite(number)) return { label: '无效', type: 'info' }
  if (number < low) return { label: '偏低', type: 'warning' }
  if (number > high) return { label: '偏高', type: 'danger' }
  return { label: '正常', type: 'success' }
}

function heartTag(value) {
  return vitalTag(value, 55, 100)
}

function breathTag(value) {
  return vitalTag(value, 10, 24)
}

function formatDateTime(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

async function load() {
  await store.loadHistory(userID.value)
}

async function runAiAnalysis() {
  await store.runAiAnalysis(userID.value)
}

function handleSizeChange() {
  store.pageNum = 1
  load()
}

function reset() {
  store.resetHistory()
}

onMounted(() => {
  if (userID.value) load()
})
</script>

<style scoped>
.history-workspace {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.history-hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 26px;
}

.history-hero h1 {
  margin: 8px 0 10px;
  font-size: 34px;
  letter-spacing: -0.03em;
}

.history-hero p,
.section-heading p,
.analysis-empty p,
.analysis-loading p {
  margin: 0;
  color: var(--care-muted);
  line-height: 1.7;
}

.hero-status {
  min-width: 168px;
  border-radius: 18px;
  padding: 14px 16px;
  color: var(--care-primary-strong);
  background: var(--care-primary-soft);
  border: 1px solid var(--care-primary-border);
}

.hero-status span,
.metric-card span {
  display: block;
  color: var(--care-muted);
  font-size: 13px;
}

.hero-status strong {
  display: block;
  margin-top: 6px;
  font-size: 22px;
  color: inherit;
}

.hero-status.running {
  color: var(--care-link);
  background: var(--care-accent-soft);
}

.hero-status.fallback {
  color: var(--care-warning);
  background: var(--care-warning-soft);
}

.hero-status.failed {
  color: var(--care-danger);
  background: var(--care-danger-soft);
}

.login-empty {
  padding: 32px;
  text-align: center;
}

.toolbar-card {
  display: flex;
  align-items: flex-end;
  gap: 18px;
  padding: 18px;
  flex-wrap: wrap;
}

.field-block {
  display: grid;
  gap: 8px;
}

.field-block label {
  color: var(--care-muted);
  font-size: 13px;
  font-weight: 700;
}

.toolbar-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.inline-error {
  flex-basis: 100%;
  margin: 0;
  color: var(--care-danger);
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(160px, 1fr));
  gap: 14px;
}

.metric-card {
  padding: 18px;
}

.metric-card strong {
  display: block;
  margin: 10px 0 6px;
  font-size: 28px;
}

.metric-card small {
  color: var(--care-muted);
}

.content-grid {
  display: grid;
  grid-template-columns: minmax(560px, 1.35fr) minmax(340px, 0.65fr);
  gap: 18px;
  align-items: start;
}

.table-card,
.ai-panel {
  padding: 20px;
}

.section-heading {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  margin-bottom: 18px;
}

.section-heading.compact {
  margin-bottom: 12px;
}

.section-heading h2 {
  margin: 0 0 6px;
  font-size: 22px;
}

.history-table {
  width: 100%;
}

.vital-cell {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.pagination-row {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.provider-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}

.provider-badge,
.time-badge {
  border-radius: 999px;
  padding: 5px 10px;
  font-size: 12px;
  color: var(--care-primary-strong);
  background: var(--care-primary-soft);
  border: 1px solid var(--care-primary-border);
}

.provider-badge.fallback {
  color: var(--care-warning);
  background: var(--care-warning-soft);
  border-color: var(--care-warning);
}

.time-badge {
  color: var(--care-muted);
  background: var(--care-surface-muted);
  border-color: var(--care-border-soft);
}

.analysis-loading,
.analysis-empty,
.report-box {
  border-radius: 18px;
  padding: 18px;
  background: var(--care-surface-2);
  border: 1px solid var(--care-border-soft);
}

.analysis-empty h3 {
  margin: 0 0 8px;
}

.analysis-empty .el-button {
  margin-top: 14px;
}

.report-box pre {
  margin: 0;
  white-space: pre-wrap;
  color: var(--care-text);
  line-height: 1.75;
  font-family: inherit;
}

.retry-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-top: 12px;
  color: var(--care-danger);
}

@media (max-width: 1180px) {
  .metric-grid,
  .content-grid {
    grid-template-columns: 1fr;
  }

  .history-hero {
    align-items: flex-start;
    flex-direction: column;
  }
}

@media (max-width: 720px) {
  .history-workspace {
    padding: 16px;
  }

  .toolbar-card,
  .toolbar-actions,
  .pagination-row {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
