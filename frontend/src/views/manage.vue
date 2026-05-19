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
          background-color="transparent"
          text-color="#dbeafe"
          active-text-color="#ffffff"
        >
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
          <strong>模拟联调模式</strong>
          <small>Radar + Snore boards</small>
        </div>
      </div>
    </aside>

    <main class="main-content">
      <header class="top-bar">
        <div>
          <span class="top-kicker">HRRR Radar Monitor</span>
          <strong>{{ route.meta.title || '睡眠看护系统' }}</strong>
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

const route = useRoute()
const activePath = computed(() => route.path)
</script>

<style scoped>
.layout-container {
  display: flex;
  min-height: 100vh;
  background:
    radial-gradient(circle at 20% 5%, rgba(22, 183, 169, 0.16), transparent 28%),
    linear-gradient(135deg, #eaf7f6 0%, #eef8ff 100%);
}

.sidebar {
  position: sticky;
  top: 0;
  width: 280px;
  height: 100vh;
  display: flex;
  flex-direction: column;
  padding: 18px 14px;
  color: #e5f6ff;
  background:
    radial-gradient(circle at 50% 0%, rgba(56, 189, 248, 0.18), transparent 34%),
    linear-gradient(180deg, #071827 0%, #0b2a3e 52%, #07332f 100%);
  box-shadow: 10px 0 34px rgba(7, 24, 39, 0.18);
  z-index: 10;
}

.sidebar-header {
  display: grid;
  grid-template-columns: 58px 1fr;
  gap: 12px;
  align-items: center;
  padding: 12px 10px 22px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.logo {
  width: 58px;
  height: 58px;
  object-fit: contain;
  filter: drop-shadow(0 12px 24px rgba(56, 189, 248, 0.22));
}

.brand-copy {
  display: grid;
  gap: 3px;
}

.brand-copy strong {
  font-size: 18px;
}

.brand-copy span,
.sidebar-footer small,
.top-kicker {
  color: #9cc5d7;
  font-size: 12px;
}

.menu-container {
  flex: 1;
  padding-top: 18px;
}

.el-menu-vertical {
  border-right: none;
}

.el-menu-item {
  min-height: 52px;
  margin: 8px 0;
  border-radius: 16px;
  font-size: 15px;
  font-weight: 700;
  transition: transform 0.18s ease, background 0.18s ease, box-shadow 0.18s ease;
}

.el-menu-item:hover {
  transform: translateX(3px);
  background: rgba(255, 255, 255, 0.1) !important;
}

.el-menu-item.is-active {
  background: linear-gradient(135deg, rgba(22, 183, 169, 0.92), rgba(56, 189, 248, 0.82)) !important;
  box-shadow: 0 12px 28px rgba(22, 183, 169, 0.24);
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
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.1);
}

.status-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #22c55e;
  box-shadow: 0 0 16px #22c55e;
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
  margin: 12px 16px 0;
  padding: 0 22px;
  border: 1px solid rgba(15, 143, 133, 0.13);
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.78);
  box-shadow: var(--care-shadow-soft);
  backdrop-filter: blur(12px);
}

.top-bar div {
  display: grid;
  gap: 3px;
}

.top-bar strong {
  color: #12263a;
  font-size: 18px;
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
