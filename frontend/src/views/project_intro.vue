<template>
  <div class="project-home care-page-shell">
    <section class="home-header">
      <div>
        <h1>睡眠看护系统</h1>
        <p>生命体征 · 呼噜识别 · 环境监测 · 紧急求助</p>
      </div>
      <div class="header-actions">
        <el-button type="primary" @click="go('/manage/heart_pic')">实时监测</el-button>
        <el-button @click="go('/manage/alert_center')">预警中心</el-button>
      </div>
    </section>

    <section class="module-grid" aria-label="功能入口">
      <button v-for="item in modules" :key="item.path" class="module-button" @click="go(item.path)">
        <span>{{ item.code }}</span>
        <strong>{{ item.title }}</strong>
      </button>
    </section>

    <section class="hardware-section">
      <div class="section-heading">
        <h2>设备组成</h2>
        <div class="flow">采集 <i></i> 分析 <i></i> 预警</div>
      </div>
      <div class="hardware-grid">
        <figure v-for="photo in hardwarePhotos" :key="photo.title">
          <img :src="photo.src" :alt="photo.alt" />
          <figcaption>
            <strong>{{ photo.title }}</strong>
            <span>{{ photo.tags }}</span>
          </figcaption>
        </figure>
      </div>
    </section>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'

const router = useRouter()

const modules = [
  { code: 'LIVE', title: '生命体征', path: '/manage/heart_pic' },
  { code: 'SLEEP', title: '睡眠驾驶舱', path: '/manage/sleep_dashboard' },
  { code: 'SOS', title: '看护预警', path: '/manage/alert_center' },
  { code: 'ENV', title: '环境分析', path: '/manage/environment_analysis' },
  { code: 'DATA', title: '历史数据', path: '/manage/data' }
]

const hardwarePhotos = [
  {
    title: '毫米波雷达开发板',
    tags: '心率 · 呼吸 · 距离',
    src: '/pic/hardware/hardware-radar-board.jpg',
    alt: '毫米波雷达开发板'
  },
  {
    title: 'Edgi E84 开发板',
    tags: '语音 · 呼噜 · 温湿度',
    src: '/pic/hardware/snore-detect-board.jpg',
    alt: 'Edgi E84 开发板'
  }
]

function go(path) {
  router.push(path)
}
</script>

<style scoped>
.project-home {
  display: grid;
  gap: 22px;
}

.home-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 10px 2px 4px;
}

.home-header h1 {
  margin: 0;
  color: var(--care-text-strong);
  font-size: 34px;
  letter-spacing: 0;
}

.home-header p {
  margin: 8px 0 0;
  color: var(--care-muted);
  font-size: 15px;
}

.header-actions {
  display: flex;
  gap: 10px;
}

.module-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(130px, 1fr));
  gap: 12px;
}

.module-button {
  min-height: 92px;
  display: grid;
  align-content: center;
  gap: 8px;
  padding: 16px;
  text-align: left;
  color: var(--care-text);
  background: var(--care-surface);
  border: 1px solid var(--care-border);
  border-radius: 8px;
  box-shadow: var(--care-shadow-soft);
  cursor: pointer;
}

.module-button:hover {
  border-color: var(--care-primary);
  transform: translateY(-2px);
}

.module-button span {
  color: var(--care-primary-strong);
  font-size: 12px;
  font-weight: 800;
}

.module-button strong {
  font-size: 17px;
}

.hardware-section {
  display: grid;
  gap: 14px;
}

.section-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.section-heading h2 {
  margin: 0;
  color: var(--care-text-strong);
  font-size: 22px;
}

.flow {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--care-muted);
  font-size: 13px;
}

.flow i {
  width: 24px;
  height: 1px;
  background: var(--care-border);
}

.hardware-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

figure {
  position: relative;
  min-height: 330px;
  margin: 0;
  overflow: hidden;
  border: 1px solid var(--care-border);
  border-radius: 8px;
  background: var(--care-surface-inverse);
}

figure img {
  width: 100%;
  height: 100%;
  min-height: 330px;
  display: block;
  object-fit: cover;
}

figcaption {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 18px;
  color: #fff;
  background: rgba(7, 24, 39, 0.82);
}

figcaption strong {
  font-size: 18px;
}

figcaption span {
  color: rgba(255, 255, 255, 0.76);
  font-size: 13px;
}

@media (max-width: 1080px) {
  .module-grid {
    grid-template-columns: repeat(3, minmax(130px, 1fr));
  }
}

@media (max-width: 760px) {
  .home-header,
  .section-heading,
  figcaption {
    align-items: flex-start;
    flex-direction: column;
  }

  .module-grid,
  .hardware-grid {
    grid-template-columns: 1fr;
  }

  figure,
  figure img {
    min-height: 240px;
  }
}
</style>
