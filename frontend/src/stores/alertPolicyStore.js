import { defineStore } from 'pinia'

const defaultPolicy = () => ({
  heartLow: 55,
  heartHigh: 100,
  breathLow: 10,
  breathHigh: 24,
  snoreThreshold: 55,
  offlineSeconds: 8,
  acknowledgedKeys: []
})

export const useAlertPolicyStore = defineStore('alertPolicy', {
  state: defaultPolicy,
  actions: {
    acknowledge(key) {
      if (!this.acknowledgedKeys.includes(key)) {
        this.acknowledgedKeys.push(key)
      }
    },
    clearAcknowledged() {
      this.acknowledgedKeys = []
    },
    resetPolicy() {
      const acknowledgedKeys = this.acknowledgedKeys
      Object.assign(this, defaultPolicy())
      this.acknowledgedKeys = acknowledgedKeys
    }
  },
  persist: true
})
