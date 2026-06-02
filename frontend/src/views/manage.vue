<template>
  <div class="layout-container">
    <aside class="sidebar" aria-label="主导航">
      <div class="sidebar-header">
        <img src="@/assets/logo.svg" alt="睡眠看护系统 Logo" class="logo" />
        <div class="brand-copy">
          <strong>Radar Care</strong>
          <span>生命体征监测</span>
        </div>
      </div>

      <nav class="menu-container">
        <el-menu
          router
          :default-active="activePath"
          class="el-menu-vertical"
          :background-color="menuBg"
          :text-color="menuText"
          :active-text-color="menuActive"
        >
          <el-menu-item index="/manage/project_intro">
            <img src="@/assets/leftmenu/知识库.svg" alt="" class="menu-icon" />
            <span>项目首页</span>
          </el-menu-item>
          <el-menu-item index="/manage/heart_pic">
            <img src="@/assets/leftmenu/widgetview.svg" alt="" class="menu-icon" />
            <span>生命体征监测</span>
          </el-menu-item>
          <el-menu-item index="/manage/sleep_dashboard">
            <img src="@/assets/leftmenu/workbench.svg" alt="" class="menu-icon" />
            <span>睡眠看护驾驶舱</span>
          </el-menu-item>
          <el-menu-item index="/manage/alert_center">
            <img src="@/assets/leftmenu/datamana.svg" alt="" class="menu-icon" />
            <span>看护预警中心</span>
          </el-menu-item>
          <el-menu-item index="/manage/data">
            <img src="@/assets/leftmenu/management.svg" alt="" class="menu-icon" />
            <span>历史数据</span>
          </el-menu-item>
        </el-menu>
      </nav>

      <div class="sidebar-footer">
        <span class="status-dot"></span>
        <div>
          <strong>双板融合看护</strong>
          <small>Radar + Acoustic sensors</small>
        </div>
      </div>
    </aside>

    <main class="main-content">
      <header class="top-bar">
        <div class="top-bar-title">
          <span class="top-kicker">HRRR Radar Monitor</span>
          <strong>{{ route.meta.title || '睡眠看护系统' }}</strong>
        </div>
        <div class="top-bar-actions">
          <span class="theme-label">{{ theme.isDark ? '深色模式' : '浅色模式' }}</span>
          <button
            class="theme-toggle"
            :class="{ dark: theme.isDark }"
            role="switch"
            :aria-checked="theme.isDark"
            :title="theme.isDark ? '切换为浅色' : '切换为深色'"
            @click="theme.toggle()"
          >
            <span class="toggle-track">
              <span class="toggle-thumb">
                <svg v-if="theme.isDark" class="toggle-icon" viewBox="0 0 24 24" aria-hidden="true">
                  <path
                    fill="currentColor"
                    d="M21 12.79A9 9 0 1 1 11.21 3a7 7 0 0 0 9.79 9.79z"
                  />
                </svg>
                <svg v-else class="toggle-icon" viewBox="0 0 24 24" aria-hidden="true">
                  <path
                    fill="currentColor"
                    d="M12 4V2m0 20v-2m8-8h2M2 12h2m13.66-5.66l1.42-1.42M4.92 19.08l1.42-1.42m0-11.32L4.92 4.92m14.16 14.16l-1.42-1.42M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10z"
                    stroke="currentColor"
                    stroke-width="1.6"
                    stroke-linecap="round"
                  />
                </svg>
              </span>
            </span>
          </button>
        </div>
      </header>

      <section class="content-area">
        <RouterView />
      </section>
    </main>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useThemeStore } from '@/stores/themeStore'

const route = useRoute()
const activePath = computed(() => route.path)
const theme = useThemeStore()

// 浅色时使用深色侧栏，深色时使用亮一档的侧栏，整体保持一致观感
const menuBg = computed(() => 'transparent')
const menuText = computed(() => 'var(--care-sidebar-text)')
const menuActive = computed(() => 'var(--care-sidebar-text-active)')
</script>

<style scoped>
.layout-container {
  display: flex;
  min-height: 100vh;
  background: var(--care-page-gradient);
  color: var(--care-text);
  transition: background 0.35s ease, color 0.35s ease;
}

.sidebar {
  position: sticky;
  top: 0;
  width: 280px;
  height: 100vh;
  display: flex;
  flex-direction: column;
  padding: 18px 14px;
  color: var(--care-sidebar-text);
  background: var(--care-sidebar-bg);
  box-shadow: 10px 0 34px var(--care-shadow-color, rgba(7, 24, 39, 0.18));
  z-index: 10;
  border-right: 1px solid var(--care-border-soft);
  transition: background 0.35s ease, color 0.35s ease, box-shadow 0.35s ease;
}

.sidebar-header {
  display: grid;
  grid-template-columns: 58px 1fr;
  gap: 12px;
  align-items: center;
  padding: 12px 10px 22px;
  border-bottom: 1px solid var(--care-sidebar-divider);
}

.logo {
  width: 58px;
  height: 58px;
  object-fit: contain;
  filter: drop-shadow(0 12px 24px var(--care-accent-soft));
}

.brand-copy {
  display: grid;
  gap: 3px;
}

.brand-copy strong {
  font-size: 18px;
  color: var(--care-sidebar-text-strong);
}

.brand-copy span,
.sidebar-footer small,
.top-kicker {
  color: var(--care-sidebar-muted);
  font-size: 12px;
}

.menu-container {
  flex: 1;
  padding-top: 18px;
}

.el-menu-vertical {
  border-right: none;
  background: transparent;
}

.el-menu-item {
  min-height: 52px;
  margin: 8px 0;
  border-radius: 16px;
  font-size: 15px;
  font-weight: 700;
  color: var(--care-sidebar-text);
  background: transparent !important;
  transition: transform 0.18s ease, background 0.18s ease, box-shadow 0.18s ease, color 0.18s ease;
}

.el-menu-item:hover {
  transform: translateX(3px);
  background: var(--care-sidebar-hover) !important;
  color: var(--care-sidebar-text-active) !important;
}

.el-menu-item.is-active {
  background: var(--care-sidebar-active) !important;
  color: var(--care-sidebar-text-active) !important;
  box-shadow: 0 12px 28px var(--care-accent-soft);
}

.menu-icon {
  width: 19px;
  height: 19px;
  margin-right: 12px;
  filter: brightness(0) invert(1);
  opacity: 0.88;
}

.sidebar-footer {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: auto;
  padding: 14px;
  border-radius: 18px;
  background: var(--care-sidebar-footer-bg);
  border: 1px solid var(--care-sidebar-divider);
  color: var(--care-sidebar-text);
}

.status-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--care-success);
  box-shadow: 0 0 16px var(--care-success);
}

.main-content {
  min-width: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
}

.top-bar {
  min-height: 64px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 12px 16px 0;
  padding: 0 22px;
  border: 1px solid var(--care-border);
  border-radius: 22px;
  background: var(--care-surface);
  box-shadow: var(--care-shadow-soft);
  backdrop-filter: blur(12px);
  transition: background 0.35s ease, border-color 0.35s ease, box-shadow 0.35s ease;
}

.top-bar-title {
  display: grid;
  gap: 3px;
}

.top-bar strong {
  color: var(--care-text-strong);
  font-size: 18px;
}

.top-bar-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.theme-label {
  font-size: 12px;
  font-weight: 700;
  color: var(--care-muted);
  letter-spacing: 0.04em;
}

.theme-toggle {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 60px;
  height: 32px;
  padding: 0;
  border: 1px solid var(--care-border);
  border-radius: 999px;
  background: var(--care-surface-strong);
  cursor: pointer;
  transition: background 0.3s ease, border-color 0.3s ease, box-shadow 0.3s ease;
}

.theme-toggle:hover {
  border-color: var(--care-primary-border);
  box-shadow: 0 0 12px var(--care-primary-soft);
}

.theme-toggle .toggle-track {
  position: relative;
  width: 100%;
  height: 100%;
}

.theme-toggle .toggle-thumb {
  position: absolute;
  top: 50%;
  left: 4px;
  transform: translateY(-50%);
  width: 24px;
  height: 24px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: linear-gradient(135deg, var(--care-primary), var(--care-accent));
  color: var(--care-text-on-primary);
  box-shadow: 0 2px 8px var(--care-primary-soft);
  transition: left 0.3s ease, background 0.3s ease, color 0.3s ease;
}

.theme-toggle.dark .toggle-thumb {
  left: 32px;
  background: linear-gradient(135deg, var(--care-warning), var(--care-accent));
}

.toggle-icon {
  width: 14px;
  height: 14px;
}

.content-area {
  flex: 1;
  min-width: 0;
  padding: 20px;
  margin: 0 16px 16px;
}

@media (max-width: 920px) {
  .layout-container {
    display: block;
  }

  .sidebar {
    position: relative;
    width: 100%;
    height: auto;
  }

  .content-area {
    margin: 0;
    padding: 16px;
  }
}
</style>
