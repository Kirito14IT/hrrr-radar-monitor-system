import { defineStore } from 'pinia'

const STORAGE_KEY = 'hrrr-radar-theme'
const FIXED_THEME = 'light'

function applyLightTheme() {
  if (typeof document === 'undefined') return

  const root = document.documentElement
  root.setAttribute('data-theme', FIXED_THEME)
  root.classList.remove('dark')
  root.classList.add('light')

  const meta = document.querySelector('meta[name="color-scheme"]')
  if (meta) meta.setAttribute('content', 'light')

  try {
    localStorage.setItem(STORAGE_KEY, FIXED_THEME)
  } catch (error) {
    console.warn('持久化浅色主题失败:', error)
  }
}

export const useThemeStore = defineStore('theme', {
  state: () => ({
    mode: FIXED_THEME
  }),
  getters: {
    isDark: () => false,
    isLight: () => true
  },
  actions: {
    setMode() {
      this.mode = FIXED_THEME
      applyLightTheme()
    },
    toggle() {
      this.setMode()
    },
    applyToDom() {
      this.mode = FIXED_THEME
      applyLightTheme()
    }
  },
  persist: {
    key: STORAGE_KEY,
    paths: ['mode']
  }
})
