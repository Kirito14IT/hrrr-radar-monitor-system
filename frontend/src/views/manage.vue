<template>
  <div class="layout-container">
    <!-- 左侧导航 -->
    <div class="sidebar">
      <!-- 头部 Logo 区 -->
      <div class="sidebar-header">
        <img src="@/assets/logo.svg" alt="Logo" class="logo" />
      </div>

      <!-- 菜单区域 -->
      <div class="menu-container">
        <el-menu
            router
            :default-active="router.currentRoute.value.path"
            class="el-menu-vertical"
            background-color="transparent"
            text-color="#333"
            active-text-color="#2e7d32"
        >
          <el-menu-item index="/manage/heart_pic">
            <img src="@/assets/leftmenu/widgetview.svg" class="menu-icon" />生命体征监测
          </el-menu-item>
          <el-menu-item index="/manage/sleep_dashboard">
            <img src="@/assets/leftmenu/workbench.svg" class="menu-icon" />睡眠看护驾驶舱
          </el-menu-item>
          <el-menu-item index="/manage/data">
            <img src="@/assets/leftmenu/management.svg" class="menu-icon" />历史数据
          </el-menu-item>
        </el-menu>
      </div>
    </div>

    <!-- 右侧内容区 -->
    <div class="main-content">
      <!-- 顶部状态栏（可选） -->
      <div class="top-bar"></div>

      <!-- 路由视图 -->
      <div class="content-area">
        <RouterView />
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from "vue";
import router from "@/router/index.js";

// （保留原有逻辑，仅用于演示）
const a = ref(1);
const b = ref("for better job");
const data = reactive({
  id: router.currentRoute.value.query,
  a: 123,
  b: "better job",
  name: "佩奇",
  arr: [1, 2, 3],
});
</script>

<style scoped>
.layout-container {
  display: flex;
  min-height: 100vh;
  background-color: #f9fbf9; /* 极浅绿背景 */
}

/* ========== 左侧边栏 ========== */
.sidebar {
  width: 260px;
  background: linear-gradient(to bottom, #e8f5e9, #c8e6c9); /* 浅绿渐变 */
  display: flex;
  flex-direction: column;
  box-shadow: 2px 0 8px rgba(0, 0, 0, 0.08);
}

.sidebar-header {
  height: 120px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  border-bottom: 1px solid #b2dfdb;
}

.logo {
  max-width: 100%;
  height: auto;
}

.menu-container {
  flex: 1;
  padding: 12px 0;
}

.el-menu-vertical {
  border-right: none;
}

.el-menu-item {
  margin: 6px 12px;
  border-radius: 8px;
  height: 48px;
  line-height: 48px;
  font-size: 16px;
  color: #2e7d32;
  transition: all 0.2s ease;
}

.el-menu-item:hover {
  background-color: rgba(46, 125, 50, 0.1);
}

.el-menu-item.is-active {
  background-color: #a5d6a7 !important;
  font-weight: 600;
}

.menu-icon {
  width: 18px;
  height: 18px;
  margin-right: 12px;
  vertical-align: middle;
}

/* ========== 右侧主内容区 ========== */
.main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.top-bar {
  height: 48px;
  background-color: #dcedc8; /* 柔和浅绿 */
  margin: 8px 12px;
  border-radius: 6px;
}

.content-area {
  flex: 1;
  padding: 20px;
  background-color: #ffffff;
  margin: 0 12px 12px 12px;
  border-radius: 12px;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.05);
}
</style>
