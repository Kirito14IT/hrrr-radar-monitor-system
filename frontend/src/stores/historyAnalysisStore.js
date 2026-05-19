import { defineStore } from 'pinia'
import request from '@/utils/request'

let inFlightAnalysisPromise = null
let activeRequestToken = 0

const defaultState = () => ({
  date: '',
  tableData: [],
  pageNum: 1,
  pageSize: 10,
  total: 0,
  loading: false,
  error: '',
  AiData: '',
  aiLoading: false,
  aiProvider: '',
  aiProviderLabel: '',
  aiFallback: false,
  aiError: '',
  lastAnalyzedAt: '',
  lastAnalysisStatus: 'idle'
})

export const useHistoryAnalysisStore = defineStore('historyAnalysis', {
  state: defaultState,
  actions: {
    async loadHistory(userID) {
      if (!userID) {
        this.error = '请先登录以查看历史数据'
        return
      }

      this.loading = true
      this.error = ''
      try {
        const response = await request.get('/heartdata/selectPage', {
          params: {
            pageNum: this.pageNum,
            pageSize: this.pageSize,
            date: this.date,
            userID
          }
        })

        if (response.code === 200) {
          this.tableData = response.data?.list || []
          this.total = response.data?.total || 0
        } else {
          this.error = response.msg || response.message || '历史数据查询失败'
        }
      } catch (error) {
        console.error('历史数据请求失败:', error)
        this.error = '历史数据接口暂时不可用，请确认模拟后端正在运行。'
      } finally {
        this.loading = false
      }
    },

    runAiAnalysis(userID) {
      if (!userID) {
        this.aiError = '请先登录后再进行 AI 分析'
        this.lastAnalysisStatus = 'failed'
        return Promise.resolve(null)
      }

      if (this.tableData.length === 0) {
        this.AiData = '暂无数据，无法进行 AI 分析。请先启动雷达模拟板并积累历史数据。'
        this.aiProvider = 'local'
        this.aiProviderLabel = '暂无数据'
        this.aiFallback = true
        this.aiError = ''
        this.aiLoading = false
        this.lastAnalysisStatus = 'empty'
        this.lastAnalyzedAt = new Date().toISOString()
        return Promise.resolve(null)
      }

      if (this.aiLoading && inFlightAnalysisPromise) {
        return inFlightAnalysisPromise
      }

      activeRequestToken += 1
      const requestToken = activeRequestToken
      const rows = JSON.parse(JSON.stringify(this.tableData))
      const selectedDate = this.date

      this.aiLoading = true
      this.AiData = '正在生成分析报告，请稍候...'
      this.aiProvider = ''
      this.aiProviderLabel = ''
      this.aiFallback = false
      this.aiError = ''
      this.lastAnalysisStatus = 'running'

      inFlightAnalysisPromise = request.post('/ai/analyze-vitals', {
        rows,
        date: selectedDate,
        userID
      }).then((response) => {
        if (requestToken !== activeRequestToken) return response

        this.AiData = response.report || 'AI 未返回有效内容。'
        this.aiProvider = response.provider || 'local'
        this.aiFallback = !!response.fallback
        this.aiProviderLabel = response.provider === 'deepseek'
          ? `DeepSeek：${response.model || 'deepseek-v4-flash'}`
          : (response.warning || '本地规则兜底')
        this.aiError = ''
        this.lastAnalysisStatus = response.fallback ? 'fallback' : 'done'
        this.lastAnalyzedAt = new Date().toISOString()
        return response
      }).catch((error) => {
        if (requestToken !== activeRequestToken) return null

        console.error('AI 分析失败:', error)
        this.AiData = 'AI 分析接口暂时不可用。请确认模拟后端正在运行；未配置 DeepSeek key 时，后端会自动使用本地规则兜底。'
        this.aiProvider = 'local'
        this.aiProviderLabel = '请求失败'
        this.aiFallback = true
        this.aiError = 'AI 分析请求失败'
        this.lastAnalysisStatus = 'failed'
        this.lastAnalyzedAt = new Date().toISOString()
        return null
      }).finally(() => {
        if (requestToken === activeRequestToken) {
          this.aiLoading = false
          inFlightAnalysisPromise = null
        }
      })

      return inFlightAnalysisPromise
    },

    resetHistory() {
      activeRequestToken += 1
      inFlightAnalysisPromise = null
      Object.assign(this, defaultState())
    }
  }
})
