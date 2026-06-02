// stores/themeStore.js
import { defineStore } from 'pinia'

const STORAGE_KEY = 'hrrr-radar-theme'

function readPersistedTheme() {
  try {
    const value = localStorage.getItem(STORAGE_KEY)
    if (value === 'light' || value === 'dark') return value
  } catch (error) {
    console.warn('读取本地主题失败:', error)
  }
  if (typeof window !== 'undefined' && window.matchMedia) {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  }
  return 'light'
}

function applyTheme(theme) {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  root.setAttribute('data-theme', theme)
  // 同步给 Element Plus / 第三方组件用作兼容
  root.classList.remove('dark', 'light')
  root.classList.add(theme === 'dark' ? 'dark' : 'light')
  // 给 meta 标签加 color-scheme，提示浏览器原生 UI 跟随
  const meta = document.querySelector('meta[name="color-scheme"]')
  if (meta) meta.setAttribute('content', theme === 'dark' ? 'dark' : 'light')
}

export const useThemeStore = defineStore('theme', {
  state: () => ({
    mode: readPersistedTheme() // 'light' | 'dark'
  }),
  getters: {
    isDark: (state) => state.mode === 'dark',
    isLight: (state) => state.mode === 'light'
  },
  actions: {
    setMode(next) {
      const target = next === 'dark' ? 'dark' : 'light'
      this.mode = target
      try {
        localStorage.setItem(STORAGE_KEY, target)
      } catch (error) {
        console.warn('持久化主题失败:', error)
      }
      applyTheme(target)
    },
    toggle() {
      this.setMode(this.mode === 'dark' ? 'light' : 'dark')
    },
    applyToDom() {
      applyTheme(this.mode)
    }
  },
  // pinia-plugin-persistedstate 兼容
  persist: {
    key: STORAGE_KEY,
    paths: ['mode']
  }
})
