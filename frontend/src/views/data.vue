<template>
  <div class="history-page">
    <div v-if="!userID" class="empty-tip">
      请先登录以查看数据
    </div>

    <div v-else>
      <el-card class="toolbar">
        <el-date-picker
          v-model="data.date"
          type="date"
          placeholder="请选择要查询的日期"
          value-format="YYYY/MM/DD"
        />
        <el-button type="warning" @click="load">查询</el-button>
        <el-button type="primary" :loading="data.aiLoading" @click="AiAnalysis">AI分析</el-button>
        <el-button type="success" @click="reset">重置</el-button>
      </el-card>

      <el-card>
        <el-table :data="data.tableData" class="history-table" stripe>
          <el-table-column label="数据编号" prop="dataID" />
          <el-table-column label="用户编号" prop="userID" />
          <el-table-column label="年" prop="year" />
          <el-table-column label="月" prop="month" />
          <el-table-column label="日" prop="day" />
          <el-table-column label="心率" prop="bpm_rader" />
          <el-table-column label="呼吸率" prop="bpm_finger" />
        </el-table>

        <div class="pagination-row">
          <el-pagination
            @size-change="load"
            @current-change="load"
            v-model:current-page="data.pageNum"
            v-model:page-size="data.pageSize"
            :page-sizes="[5, 10, 15, 20]"
            background
            layout="total, sizes, prev, pager, next, jumper"
            :total="data.total"
          />
        </div>
      </el-card>

      <el-card class="ai-card">
        <div class="ai-header">
          <span>AI / 本地健康分析</span>
          <span v-if="data.aiProvider" class="ai-provider" :class="{ fallback: data.aiFallback }">
            {{ data.aiProviderLabel }}
          </span>
        </div>
        <pre class="ai-report">{{ data.AiData || '点击“AI分析”后，这里会显示 DeepSeek 或本地规则生成的报告。' }}</pre>
      </el-card>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useUserStore } from '@/stores/userStore'
import request from '@/utils/request'

const userStore = useUserStore()
const userID = ref(userStore.userInfo?.userID || null)

const data = reactive({
  date: '',
  tableData: [],
  pageNum: 1,
  pageSize: 10,
  total: 0,
  AiData: '',
  aiLoading: false,
  aiProvider: '',
  aiProviderLabel: '',
  aiFallback: false
})

const load = async () => {
  if (!userID.value) {
    alert('请先登录')
    return
  }

  try {
    const response = await request.get('/heartdata/selectPage', {
      params: {
        pageNum: data.pageNum,
        pageSize: data.pageSize,
        date: data.date,
        userID: userID.value
      }
    })

    if (response.code === 200) {
      data.tableData = response.data.list
      data.total = response.data.total
    } else {
      console.error('查询失败:', response.msg)
    }
  } catch (error) {
    console.error('请求失败:', error)
  }
}

const AiAnalysis = async () => {
  if (data.tableData.length === 0) {
    data.AiData = '暂无数据，无法进行 AI 分析。请先启动雷达模拟板并积累历史数据。'
    data.aiProvider = 'local'
    data.aiProviderLabel = '暂无数据'
    data.aiFallback = true
    return
  }

  data.aiLoading = true
  data.AiData = '正在生成分析报告，请稍候...'
  data.aiProvider = ''
  data.aiProviderLabel = ''
  data.aiFallback = false

  try {
    const response = await request.post('/ai/analyze-vitals', {
      rows: data.tableData,
      date: data.date,
      userID: userID.value
    })

    data.AiData = response.report || 'AI 未返回有效内容。'
    data.aiProvider = response.provider || 'local'
    data.aiFallback = !!response.fallback
    data.aiProviderLabel = response.provider === 'deepseek'
      ? `DeepSeek：${response.model || 'deepseek-v4-flash'}`
      : (response.warning || '本地规则兜底')
  } catch (error) {
    console.error('AI 分析失败:', error)
    data.AiData = 'AI 分析接口暂时不可用。请确认模拟后端正在运行；未配置 DeepSeek key 时，后端会自动使用本地规则兜底。'
    data.aiProvider = 'local'
    data.aiProviderLabel = '请求失败'
    data.aiFallback = true
  } finally {
    data.aiLoading = false
  }
}

const reset = () => {
  data.date = ''
  data.pageNum = 1
  data.pageSize = 10
  data.tableData = []
  data.total = 0
  data.AiData = ''
  data.aiProvider = ''
  data.aiProviderLabel = ''
  data.aiFallback = false
}

onMounted(load)
</script>

<style scoped>
.history-page { width: 100%; }
.empty-tip { text-align: center; padding: 20px; color: red; }
.toolbar { margin-bottom: 12px; }
.toolbar :deep(.el-card__body) { display: flex; gap: 16px; align-items: center; flex-wrap: wrap; }
.history-table { width: 100%; }
.pagination-row { margin-top: 10px; }
.ai-card { margin-top: 12px; }
.ai-header { display: flex; align-items: center; gap: 10px; font-weight: 700; margin-bottom: 10px; }
.ai-provider { font-size: 12px; color: #237804; background: #e6f7ed; border: 1px solid #b7eb8f; border-radius: 999px; padding: 3px 9px; font-weight: 400; }
.ai-provider.fallback { color: #ad6800; background: #fff7e6; border-color: #ffd591; }
.ai-report { white-space: pre-wrap; line-height: 1.7; color: #333; font-family: inherit; margin: 0; }
</style>
