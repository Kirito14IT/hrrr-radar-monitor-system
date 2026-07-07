<template>
  <div class="history-workspace care-page-shell">
    <section class="history-hero care-glass-card care-icon-card" data-icon="LOG">
      <div>
        <h1>历史数据</h1>
      </div>
    </section>

    <div v-if="!userID" class="login-empty care-glass-card care-icon-card" data-icon="LOCK">
      <h2>请先登录以查看数据</h2>
    </div>

    <template v-else>
      <section class="toolbar-card care-glass-card care-icon-card" data-icon="筛">
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
          <el-button type="success" :loading="store.aiLoading" @click="runAiAnalysisStream">
            AI 流式分析
          </el-button>
          <el-button @click="reset">重置</el-button>
        </div>
        <p v-if="store.error" class="inline-error">{{ store.error }}</p>
      </section>

      <section class="metric-grid">
        <article v-for="card in metricCards" :key="card.key" class="metric-card care-glass-card care-icon-card" :data-icon="card.icon">
          <span>{{ card.title }}</span>
          <strong>{{ card.value }}</strong>
        </article>
      </section>

      <section class="content-grid">
        <article class="table-card care-glass-card care-icon-card" data-icon="表">
          <div class="section-heading">
            <div>
              <h2>历史生命体征记录</h2>
            </div>
            <el-tag effect="plain" type="info">共 {{ store.total }} 条</el-tag>
          </div>

          <el-table
            v-loading="store.loading"
            :data="store.tableData"
            class="history-table"
            stripe
            empty-text="暂无历史数据，请先连接真实开发板并在实时页积累数据。"
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
            <el-table-column label="呼噜" min-width="150">
              <template #default="{ row }">
                <span class="vital-cell">
                  <el-tag size="small" :type="snoreTag(row).type">
                    {{ snoreTag(row).label }}
                  </el-tag>
                  <strong v-if="snoreTag(row).scoreText">{{ snoreTag(row).scoreText }}</strong>
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
      </section>

      <section class="ai-panel care-glass-card care-icon-card" data-icon="AI">
        <div class="section-heading compact">
          <div>
            <h2>AI / 本地健康分析</h2>
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

        <div v-if="store.aiLoading && !store.AiData" class="analysis-loading">
          <el-skeleton :rows="7" animated />
        </div>
        <div v-else-if="store.AiData" class="report-box">
          <div v-if="store.aiStreaming" class="stream-indicator">
            <span class="stream-dot"></span>
            <span>正在实时编译 DeepSeek 输出...</span>
          </div>
          <div class="report-md" v-html="compiledReport"></div>
        </div>
        <div v-else class="analysis-empty">
          <h3>尚未生成报告</h3>
          <el-button type="primary" :disabled="store.tableData.length === 0" @click="runAiAnalysisStream">
            生成报告
          </el-button>
        </div>

        <div v-if="store.aiError" class="retry-row">
          <span>{{ store.aiError }}</span>
          <el-button size="small" type="warning" @click="runAiAnalysisStream">重试</el-button>
        </div>
      </section>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { useUserStore } from '@/stores/userStore'
import { useHistoryAnalysisStore } from '@/stores/historyAnalysisStore'
import { useBedStore } from '@/stores/bedStore'

const userStore = useUserStore()
const store = useHistoryAnalysisStore()
const bedStore = useBedStore()

// Configure marked once: GitHub-flavoured markdown, line breaks preserved,
// HTML escaped by DOMPurify on the output side.
marked.setOptions({
  gfm: true,
  breaks: true,
  pedantic: false
})

const compiledReport = computed(() => {
  const text = store.AiData
  if (!text) return ''
  const html = marked.parse(text)
  return DOMPurify.sanitize(html, {
    USE_PROFILES: { html: true },
    ADD_ATTR: ['target', 'rel']
  })
})

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
const snoreCount = computed(() => store.tableData.filter(row => isSnoreDetected(row)).length)

const abnormalCount = computed(() => store.tableData.filter(row => {
  const heart = Number(row.bpm_rader)
  const breath = Number(row.bpm_finger)
  return (Number.isFinite(heart) && (heart < 55 || heart > 100)) ||
    (Number.isFinite(breath) && (breath < 10 || breath > 24))
}).length)

const metricCards = computed(() => [
  {
    key: 'rows',
    icon: 'NUM',
    title: '当前页样本',
    value: `${store.tableData.length}`,
    detail: `数据库总计 ${store.total} 条记录`
  },
  {
    key: 'heart',
    icon: 'HR',
    title: '平均心率',
    value: avgHeart.value === null ? '--' : `${avgHeart.value.toFixed(1)} BPM`,
    detail: heartValues.value.length ? '正常参考：55-100 BPM' : '等待有效心率样本'
  },
  {
    key: 'breath',
    icon: 'BR',
    title: '平均呼吸率',
    value: avgBreath.value === null ? '--' : `${avgBreath.value.toFixed(1)} RPM`,
    detail: breathValues.value.length ? '正常参考：10-24 RPM' : '等待有效呼吸样本'
  },
  {
    key: 'abnormal',
    icon: '!',
    title: '异常提示',
    value: `${abnormalCount.value}`,
    detail: abnormalCount.value ? '建议结合 AI 报告复核' : '当前页未见明显异常'
  },
  {
    key: 'snore',
    icon: 'SN',
    title: '呼噜记录',
    value: `${snoreCount.value}`,
    detail: snoreCount.value ? '当前页存在呼噜记录' : '当前页未记录呼噜'
  }
])

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

function isSnoreDetected(row) {
  return row?.snore_detected === true || row?.snore_detected === 1 || row?.snore_detected === '1'
}

function snoreTag(row) {
  const detected = isSnoreDetected(row)
  const score = Number(row?.snore_score)
  const scoreText = Number.isFinite(score) ? `${Math.round(score * 100)}%` : ''
  return {
    label: detected ? '有呼噜' : '无',
    type: detected ? 'danger' : 'success',
    scoreText: detected ? scoreText : ''
  }
}

function formatDateTime(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

async function load() {
  await store.loadHistory(userID.value, bedStore.selectedBedId)
}

async function runAiAnalysis() {
  await store.runAiAnalysis(userID.value, bedStore.selectedBedId)
}

async function runAiAnalysisStream() {
  await store.runAiAnalysisStream(userID.value, bedStore.selectedBedId)
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
  justify-content: flex-start;
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

.metric-card span {
  display: block;
  color: var(--care-muted);
  font-size: 13px;
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
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
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
  grid-template-columns: 1fr;
  gap: 18px;
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

.report-md {
  color: var(--care-text);
  line-height: 1.75;
  font-family: inherit;
  word-break: break-word;
}

.report-md :deep(h1),
.report-md :deep(h2),
.report-md :deep(h3),
.report-md :deep(h4) {
  margin: 1.1em 0 0.5em;
  line-height: 1.35;
  font-weight: 600;
  color: var(--care-text-strong);
}

.report-md :deep(h2) { font-size: 18px; }
.report-md :deep(h3) { font-size: 16px; }

.report-md :deep(p) {
  margin: 0 0 0.8em;
}

.report-md :deep(ul),
.report-md :deep(ol) {
  margin: 0 0 0.8em;
  padding-left: 1.4em;
}

.report-md :deep(li) {
  margin: 0.25em 0;
}

.report-md :deep(strong) {
  color: var(--care-text-strong);
  font-weight: 600;
}

.report-md :deep(code) {
  background: var(--care-surface-muted);
  border-radius: 4px;
  padding: 1px 5px;
  font-size: 0.92em;
}

.report-md :deep(blockquote) {
  margin: 0.4em 0 0.8em;
  padding: 4px 12px;
  border-left: 3px solid var(--care-primary-border);
  color: var(--care-muted);
  background: var(--care-surface-muted);
  border-radius: 0 8px 8px 0;
}

.report-md :deep(table) {
  border-collapse: collapse;
  margin: 0.6em 0;
  width: 100%;
}

.report-md :deep(th),
.report-md :deep(td) {
  border: 1px solid var(--care-border-soft);
  padding: 6px 10px;
  text-align: left;
}

.stream-indicator {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 4px 10px;
  margin-bottom: 12px;
  font-size: 12px;
  color: var(--care-primary-strong);
  background: var(--care-primary-soft);
  border: 1px solid var(--care-primary-border);
  border-radius: 999px;
}

.stream-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--care-primary);
  animation: stream-pulse 1.1s ease-in-out infinite;
}

@keyframes stream-pulse {
  0%, 100% { opacity: 0.35; transform: scale(0.85); }
  50% { opacity: 1; transform: scale(1.1); }
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
