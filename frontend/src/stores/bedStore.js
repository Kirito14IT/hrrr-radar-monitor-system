import { defineStore } from 'pinia'
import request from '@/utils/request'

export const DEFAULT_BED_ID = 'bed-001'

export const useBedStore = defineStore('bedStore', {
  state: () => ({
    selectedBedId: localStorage.getItem('selectedBedId') || DEFAULT_BED_ID,
    beds: [],
    summary: {
      total: 0,
      online: 0,
      critical: 0,
      warning: 0,
      normal: 0,
      offline: 0
    },
    loading: false,
    error: '',
    lastUpdatedAt: ''
  }),
  getters: {
    selectedBed(state) {
      return state.beds.find(item => item.bed_id === state.selectedBedId) || state.beds[0] || null
    },
    selectedBedLabel() {
      return this.selectedBed?.bed_label || '01床'
    }
  },
  actions: {
    setSelectedBed(bedId) {
      const next = bedId || DEFAULT_BED_ID
      this.selectedBedId = next
      localStorage.setItem('selectedBedId', next)
    },
    async loadBeds() {
      this.loading = true
      this.error = ''
      try {
        const response = await request.get('/beds')
        this.beds = Array.isArray(response?.beds) ? response.beds : []
        this.summary = response?.summary || this.summary
        if (!this.beds.some(item => item.bed_id === this.selectedBedId)) {
          this.setSelectedBed(this.beds[0]?.bed_id || DEFAULT_BED_ID)
        }
        this.lastUpdatedAt = new Date().toISOString()
      } catch (error) {
        console.warn('load beds failed:', error)
        this.error = '无法连接床位监护接口'
      } finally {
        this.loading = false
      }
    },
    bedApi(path = '') {
      const suffix = path.startsWith('/') ? path : `/${path}`
      return `/beds/${this.selectedBedId}${suffix}`
    },
    requestParams(extra = {}) {
      return {
        ...extra,
        bed_id: this.selectedBedId
      }
    }
  }
})
