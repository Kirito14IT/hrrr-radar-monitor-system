import { defineStore } from 'pinia'
import request, { API_BASE_URL } from '@/utils/request'

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
  aiStreaming: false,
  aiProvider: '',
  aiProviderLabel: '',
  aiFallback: false,
  aiError: '',
  aiWarning: '',
  lastAnalyzedAt: '',
  lastAnalysisStatus: 'idle'
})

function normalizeStreamUrl(raw) {
  if (!raw) return ''
  return raw.replace(/\/+$/, '')
}

export const useHistoryAnalysisStore = defineStore('historyAnalysis', {
  state: defaultState,
  actions: {
    async loadHistory(userID, bedId) {
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
            userID,
            bed_id: bedId
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
        this.error = '历史数据接口暂时不可用，请确认真实后端服务正在运行。'
      } finally {
        this.loading = false
      }
    },

    /**
     * Streaming variant. POSTs to `/ai/analyze-vitals/stream`, consumes the SSE
     * deltas progressively, and assembles the final report into AiData. If the
     * backend reports a fallback (no DeepSeek chunks were emitted), it surfaces
     * `provider`, `warning`, and the fallback report instead.
     */
    async runAiAnalysisStream(userID, bedId) {
      if (!userID) {
        this.aiError = '请先登录后再进行 AI 分析'
        this.lastAnalysisStatus = 'failed'
        return null
      }

      if (this.tableData.length === 0) {
        this.AiData = '暂无数据，无法进行 AI 分析。请先启动雷达模拟板并积累历史数据。'
        this.aiProvider = 'local'
        this.aiProviderLabel = '暂无数据'
        this.aiFallback = true
        this.aiError = ''
        this.aiWarning = ''
        this.aiLoading = false
        this.aiStreaming = false
        this.lastAnalysisStatus = 'empty'
        this.lastAnalyzedAt = new Date().toISOString()
        return null
      }

      if (this.aiLoading && inFlightAnalysisPromise) {
        return inFlightAnalysisPromise
      }

      activeRequestToken += 1
      const requestToken = activeRequestToken
      const rows = JSON.parse(JSON.stringify(this.tableData))
      const selectedDate = this.date

      this.aiLoading = true
      this.aiStreaming = true
      this.AiData = ''
      this.aiProvider = ''
      this.aiProviderLabel = ''
      this.aiFallback = false
      this.aiError = ''
      this.aiWarning = ''
      this.lastAnalysisStatus = 'running'

      const streamUrl = `${normalizeStreamUrl(API_BASE_URL)}/ai/analyze-vitals/stream`

      const runStream = async () => {
        let response
        try {
          response = await fetch(streamUrl, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              Accept: 'text/event-stream'
            },
              body: JSON.stringify({ rows, date: selectedDate, userID, bed_id: bedId })
          })
        } catch (networkError) {
          if (requestToken !== activeRequestToken) return null
          this._failWith('AI 流式接口连接失败，请检查后端 / 网络。', networkError)
          return null
        }

        if (!response.ok || !response.body) {
          if (requestToken !== activeRequestToken) return null
          await this._consumeNonStreamFallback(response, { rows, date: selectedDate, userID, bed_id: bedId })
          return null
        }

        const reader = response.body.getReader()
        const decoder = new TextDecoder('utf-8')
        let buffer = ''
        let assembled = ''
        let terminal = null

        const handleFrame = (rawJson) => {
          if (requestToken !== activeRequestToken) return false
          let evt
          try {
            evt = JSON.parse(rawJson)
          } catch (parseErr) {
            return true // ignore malformed frame
          }
          if (evt.delta) {
            assembled += evt.delta
            this.AiData = assembled
          }
          if (evt.done) {
            terminal = evt
            // If the backend never emitted deltas, use the fallback report from
            // the terminal frame.
            if (!assembled && evt.report) {
              assembled = evt.report
              this.AiData = assembled
            }
            return false
          }
          return true
        }

        try {
          // eslint-disable-next-line no-constant-condition
          while (true) {
            const { value, done } = await reader.read()
            if (done) break
            buffer += decoder.decode(value, { stream: true })
            let boundary
            while ((boundary = buffer.indexOf('\n\n')) !== -1) {
              const frame = buffer.slice(0, boundary)
              buffer = buffer.slice(boundary + 2)
              if (!frame.startsWith('data:')) continue
              const payload = frame.slice(5).trim()
              if (!payload) continue
              if (!handleFrame(payload)) {
                try { await reader.cancel() } catch (_) { /* noop */ }
                break
              }
            }
            if (terminal) break
          }
        } catch (streamError) {
          if (requestToken === activeRequestToken) {
            console.warn('AI 流式读取中断，尝试 fallback:', streamError)
            // Mid-stream failure: keep what we already have but flag it.
            this.aiError = 'AI 流式响应中断，已尽量保留已收到的内容。'
            this.aiWarning = streamError?.message || String(streamError)
          }
        }

        if (requestToken !== activeRequestToken) {
          try { await reader.cancel() } catch (_) { /* noop */ }
          return null
        }

        if (terminal) {
          this._applyTerminal(terminal, assembled)
        } else {
          // Connection dropped without a terminal frame — best-effort finalise.
          this.aiProvider = this.aiProvider || 'deepseek'
          this.aiProviderLabel = this.aiProvider === 'deepseek'
            ? (this.aiProviderLabel || 'DeepSeek（流中断）')
            : (this.aiProviderLabel || '本地规则兜底')
          this.lastAnalyzedAt = new Date().toISOString()
          this.lastAnalysisStatus = assembled ? 'partial' : 'fallback'
        }
        return terminal || { assembled: this.AiData }
      }

      inFlightAnalysisPromise = runStream()
      try {
        return await inFlightAnalysisPromise
      } finally {
        if (requestToken === activeRequestToken) {
          this.aiLoading = false
          this.aiStreaming = false
          inFlightAnalysisPromise = null
        }
      }
    },

    /**
     * Original non-streaming call — kept for callers that still want a one-shot
     * response. Also used internally as a fallback if the SSE endpoint refuses
     * the stream (e.g. proxy returns 200 with empty body).
     */
    runAiAnalysis(userID, bedId) {
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
        this.aiWarning = ''
        this.aiLoading = false
        this.aiStreaming = false
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
      this.aiStreaming = false
      this.AiData = '正在生成分析报告，请稍候...'
      this.aiProvider = ''
      this.aiProviderLabel = ''
      this.aiFallback = false
      this.aiError = ''
      this.aiWarning = ''
      this.lastAnalysisStatus = 'running'

      inFlightAnalysisPromise = request.post('/ai/analyze-vitals', {
        rows,
        date: selectedDate,
        userID,
        bed_id: bedId
      }).then((response) => {
        if (requestToken !== activeRequestToken) return response
        this._applyTerminal(response, response.report || '')
        return response
      }).catch((error) => {
        if (requestToken !== activeRequestToken) return null
        console.error('AI 分析失败:', error)
        this._failWith('AI 分析接口暂时不可用。请确认真实后端服务正在运行；未配置 DeepSeek key 时，后端会自动使用本地规则兜底。', error)
        return null
      }).finally(() => {
        if (requestToken === activeRequestToken) {
          this.aiLoading = false
          this.aiStreaming = false
          inFlightAnalysisPromise = null
        }
      })

      return inFlightAnalysisPromise
    },

    /** Apply the final terminal frame (or non-stream response) to local state. */
    _applyTerminal(terminal, assembled) {
      this.AiData = assembled || terminal.report || ''
      this.aiProvider = terminal.provider || 'local'
      this.aiFallback = !!terminal.fallback
      this.aiProviderLabel = terminal.provider === 'deepseek'
        ? `DeepSeek：${terminal.model || 'deepseek-chat'}`
        : (terminal.warning || '本地规则兜底')
      this.aiWarning = terminal.warning || ''
      this.aiError = terminal.warning && terminal.fallback ? terminal.warning : this.aiError
      this.lastAnalysisStatus = terminal.fallback ? (this.AiData ? 'fallback' : 'failed') : 'done'
      this.lastAnalyzedAt = new Date().toISOString()
    },

    async _consumeNonStreamFallback(response, payload) {
      // The streaming endpoint returned a non-streamable response (HTTP error
      // or empty body). Try the legacy non-stream endpoint as a graceful fallback.
      try {
        const fallback = await request.post('/ai/analyze-vitals', payload)
        if (fallback && fallback.report) {
          this._applyTerminal(fallback, fallback.report)
          return
        }
      } catch (legacyError) {
        console.error('AI non-stream fallback also failed:', legacyError)
      }
      this._failWith(
        `AI 流式接口返回 ${response.status}，且非流式兜底也失败。`,
        new Error(`stream HTTP ${response.status}`)
      )
    },

    _failWith(message, error) {
      this.AiData = message
      this.aiProvider = 'local'
      this.aiProviderLabel = '请求失败'
      this.aiFallback = true
      this.aiError = 'AI 分析请求失败'
      this.aiWarning = error?.message || String(error)
      this.lastAnalysisStatus = 'failed'
      this.lastAnalyzedAt = new Date().toISOString()
    },

    resetHistory() {
      activeRequestToken += 1
      inFlightAnalysisPromise = null
      Object.assign(this, defaultState())
    }
  }
})
