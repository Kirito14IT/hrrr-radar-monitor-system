<template>
  <div class="project-home">
    <section class="hero-section reveal-block">
      <div class="hero-copy">
        <span class="eyebrow">Radar Care · 多床位非接触看护系统</span>
        <h1>面向护理场景的连续生命体征与异常事件监视平台</h1>
        <p>
          系统融合毫米波雷达、边缘呼噜识别、环境采集与紧急事件上报，为医院、养老院和家庭照护场景提供实时床位监视、
          风险提醒、处理记录和历史分析能力。
        </p>
        <div class="hero-actions">
          <el-button type="primary" @click="go('/manage/nurse_station')">进入床位监视</el-button>
          <el-button plain @click="go('/ward-screen')">查看大屏</el-button>
        </div>
      </div>

      <div class="hero-dashboard" aria-label="系统能力摘要">
        <article v-for="item in heroStats" :key="item.label" class="stat-card care-icon-card" :data-icon="item.icon">
          <span>{{ item.code }}</span>
          <strong>{{ item.value }}</strong>
          <small>{{ item.label }}</small>
        </article>
      </div>
    </section>

    <section class="showcase-grid reveal-block" aria-label="核心能力">
      <article v-for="item in showcases" :key="item.title" class="showcase-card">
        <div class="line-icon">{{ item.icon }}</div>
        <h2>{{ item.title }}</h2>
        <p>{{ item.desc }}</p>
      </article>
    </section>

    <section class="system-flow reveal-block">
      <div class="section-heading">
        <span class="eyebrow">Workflow</span>
        <h2>从采集到处置的闭环流程</h2>
      </div>
      <div class="pipeline">
        <article v-for="step in pipelineSteps" :key="step.title" class="pipeline-step care-icon-card" :data-icon="step.icon">
          <span>{{ step.code }}</span>
          <strong>{{ step.title }}</strong>
          <small>{{ step.desc }}</small>
        </article>
      </div>
    </section>

    <section class="module-grid reveal-block" aria-label="功能入口">
      <button v-for="item in modules" :key="item.path" class="module-button care-icon-card" :data-icon="item.icon" @click="go(item.path)">
        <span>{{ item.code }}</span>
        <strong>{{ item.title }}</strong>
        <small>{{ item.desc }}</small>
      </button>
    </section>

    <section class="architecture-section reveal-block">
      <div class="section-heading">
        <span class="eyebrow">Architecture</span>
        <h2>多端硬件协同看护链路</h2>
      </div>
      <figure class="architecture-card">
        <img src="/pic/hardware/hardware-system-chest-radar.png" alt="雷达、小智、环境传感器与护理站大屏协同工作的系统总览图" />
        <figcaption>
          <strong>系统总览</strong>
          <span>雷达对准胸腔，小智与环境设备同步上报，护理端统一呈现床位状态。</span>
        </figcaption>
      </figure>
    </section>

    <section class="hardware-section reveal-block">
      <div class="section-heading">
        <span class="eyebrow">Devices</span>
        <h2>设备组成</h2>
      </div>
      <div class="hardware-grid">
        <figure v-for="photo in hardwarePhotos" :key="photo.title" :class="photo.className">
          <img :src="photo.src" :alt="photo.alt" />
          <figcaption>
            <strong>{{ photo.title }}</strong>
            <span>{{ photo.tags }}</span>
          </figcaption>
        </figure>
      </div>
    </section>

    <section class="product-strip reveal-block care-icon-card" data-icon="CARE">
      <div>
        <span class="eyebrow">Care Operation</span>
        <h2>让护理人员用一张屏掌握床位状态</h2>
        <p>
          当心率、呼吸、呼噜、环境或紧急事件出现异常时，系统会将风险集中到床位和预警中心，减少护理人员在多设备之间反复确认的成本。
        </p>
      </div>
      <el-button type="primary" @click="go('/manage/alert_center')">打开预警中心</el-button>
    </section>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'

const router = useRouter()

const heroStats = [
  { code: '01', icon: 'BED', value: '多床位', label: '统一看护视图' },
  { code: '02', icon: 'LIVE', value: '实时', label: '心率 / 呼吸 / 环境' },
  { code: '03', icon: 'LOG', value: '闭环', label: '告警确认与历史记录' }
]

const showcases = [
  {
    icon: 'HR',
    title: '非接触生命体征',
    desc: '毫米波雷达持续输出心率、呼吸率与目标距离，减少佩戴式设备对休息状态的干扰。'
  },
  {
    icon: 'BR',
    title: '呼吸与呼噜融合',
    desc: '边缘端识别呼噜状态，后端结合雷达呼吸和存在性信号，降低单一信号造成的误报。'
  },
  {
    icon: 'SOS',
    title: '紧急事件处置',
    desc: '支持语音求助、疑似呼吸暂停、板端摇晃等事件提醒，并保留处理人和处理说明。'
  }
]

const pipelineSteps = [
  { code: '采集', icon: 'IN', title: '多端数据接入', desc: '雷达、小智/Edgi、环境传感器持续上报。' },
  { code: '融合', icon: 'API', title: '后端实时处理', desc: '按床位隔离状态，聚合生命体征、声音和环境。' },
  { code: '提醒', icon: 'SOS', title: '异常集中呈现', desc: '风险事件进入护士站、床位详情和预警中心。' },
  { code: '沉淀', icon: 'LOG', title: '历史分析记录', desc: '保留生命体征、呼噜、环境和处理记录。' }
]

const modules = [
  { code: 'LIVE', icon: 'HR', title: '生命体征', desc: '心率、呼吸率与雷达状态', path: '/manage/heart_pic' },
  { code: 'SLEEP', icon: 'BR', title: '睡眠看护', desc: '睡眠评分与事件趋势', path: '/manage/sleep_dashboard' },
  { code: 'ALERT', icon: 'SOS', title: '预警中心', desc: '待处理事件与风险策略', path: '/manage/alert_center' },
  { code: 'ENV', icon: 'ENV', title: '环境分析', desc: '温湿度与环境声级', path: '/manage/environment_analysis' },
  { code: 'DATA', icon: 'LOG', title: '历史数据', desc: '记录查询与分析报告', path: '/manage/data' }
]

const hardwarePhotos = [
  {
    title: '毫米波雷达开发板',
    tags: '心率 · 呼吸 · 距离',
    src: '/pic/hardware/hardware-radar-board.jpg',
    alt: '毫米波雷达开发板'
  },
  {
    title: 'Edgi E84 / 小智开发板',
    tags: '语音 · 呼噜 · 环境',
    src: '/pic/hardware/snore-detect-board.jpg',
    alt: 'Edgi E84 小智开发板'
  }
]

function go(path) {
  router.push(path)
}
</script>

<style scoped>
.project-home {
  --intro-bg: #f8f9fa;
  --intro-panel: rgba(255, 255, 255, .86);
  --intro-text: #1a1a1a;
  --intro-body: #666;
  --intro-muted: #999;
  --intro-line: rgba(0, 0, 0, .07);
  --intro-accent: #116e8a;
  --intro-accent-soft: rgba(17, 110, 138, .08);
  min-height: calc(100vh - 84px);
  margin: -20px;
  padding: clamp(32px, 5vw, 72px);
  display: grid;
  gap: clamp(28px, 4vw, 52px);
  color: var(--intro-text);
  background:
    radial-gradient(circle at 12% 8%, rgba(17, 110, 138, .06), transparent 26%),
    linear-gradient(180deg, #ffffff 0%, var(--intro-bg) 100%);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, "PingFang SC", "Microsoft YaHei", sans-serif;
}

.hero-section,
.system-flow,
.product-strip {
  width: min(1180px, 100%);
  margin: 0 auto;
}

.hero-section {
  min-height: 520px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 380px;
  align-items: center;
  gap: clamp(32px, 6vw, 80px);
  padding: clamp(28px, 5vw, 64px);
  border: 1px solid var(--intro-line);
  border-radius: 28px;
  background: var(--intro-panel);
  box-shadow: 0 8px 30px rgba(0, 0, 0, .05);
  backdrop-filter: blur(12px);
}

.hero-copy {
  max-width: 760px;
}

.eyebrow {
  display: inline-flex;
  margin-bottom: 18px;
  color: var(--intro-accent);
  font-size: 12px;
  font-weight: 800;
  letter-spacing: .14em;
  text-transform: uppercase;
}

.hero-copy h1 {
  max-width: 720px;
  margin: 0;
  color: var(--intro-text);
  font-size: clamp(36px, 5vw, 54px);
  line-height: 1.08;
  letter-spacing: -.045em;
  font-weight: 850;
}

.hero-copy p,
.showcase-card p,
.pipeline-step small,
.module-button small,
.product-strip p {
  max-width: 72ch;
  margin: 18px 0 0;
  color: var(--intro-body);
  font-size: 16px;
  line-height: 1.75;
}

.hero-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 32px;
}

.hero-actions :deep(.el-button),
.product-strip :deep(.el-button) {
  min-width: 132px;
  border-radius: 999px !important;
  transition: transform .35s cubic-bezier(.25, .46, .45, .94), box-shadow .35s cubic-bezier(.25, .46, .45, .94);
}

.hero-actions :deep(.el-button:hover),
.product-strip :deep(.el-button:hover) {
  transform: scale(1.02);
  box-shadow: 0 8px 30px rgba(0, 0, 0, .08) !important;
}

.hero-dashboard {
  display: grid;
  gap: 14px;
}

.stat-card {
  min-height: 118px;
  padding: 22px;
  display: grid;
  align-content: center;
  gap: 8px;
  border: 1px solid var(--intro-line);
  border-radius: 22px;
  background: rgba(255, 255, 255, .72);
  box-shadow: 0 8px 30px rgba(0, 0, 0, .04);
  transition: transform .35s cubic-bezier(.25, .46, .45, .94), box-shadow .35s cubic-bezier(.25, .46, .45, .94);
}

.stat-card:hover,
.showcase-card:hover,
.module-button:hover,
figure:hover {
  transform: scale(1.02);
  box-shadow: 0 14px 38px rgba(0, 0, 0, .075);
}

.stat-card span,
.pipeline-step span,
.module-button span {
  color: var(--intro-accent);
  font-size: 12px;
  font-weight: 800;
  letter-spacing: .08em;
}

.stat-card strong {
  color: var(--intro-text);
  font-size: 36px;
  line-height: 1;
  letter-spacing: -.03em;
}

.stat-card small {
  color: var(--intro-muted);
  font-size: 14px;
}

.showcase-grid,
.module-grid,
.architecture-section,
.hardware-section {
  width: min(1180px, 100%);
  margin: 0 auto;
}

.showcase-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 18px;
}

.showcase-card {
  padding: 28px;
  border: 1px solid var(--intro-line);
  border-radius: 24px;
  background: #fff;
  box-shadow: 0 8px 30px rgba(0, 0, 0, .045);
  transition: transform .35s cubic-bezier(.25, .46, .45, .94), box-shadow .35s cubic-bezier(.25, .46, .45, .94);
}

.line-icon {
  width: 46px;
  height: 46px;
  display: grid;
  place-items: center;
  margin-bottom: 22px;
  border: 1px solid rgba(17, 110, 138, .24);
  border-radius: 16px;
  color: var(--intro-accent);
  background: var(--intro-accent-soft);
  font-size: 13px;
  font-weight: 900;
}

.showcase-card h2,
.section-heading h2,
.product-strip h2 {
  margin: 0;
  color: var(--intro-text);
  font-size: 24px;
  line-height: 1.25;
  letter-spacing: -.02em;
}

.system-flow {
  padding: 34px;
  border: 1px solid var(--intro-line);
  border-radius: 28px;
  background: #fff;
}

.section-heading {
  display: grid;
  gap: 2px;
  margin-bottom: 24px;
}

.pipeline {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  border: 1px solid var(--intro-line);
  border-radius: 22px;
  overflow: hidden;
}

.pipeline-step {
  min-height: 150px;
  padding: 24px;
  display: grid;
  align-content: start;
  gap: 10px;
  background: #fff;
  border-right: 1px solid var(--intro-line);
}

.pipeline-step:last-child {
  border-right: 0;
}

.pipeline-step strong {
  color: var(--intro-text);
  font-size: 18px;
}

.module-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 14px;
}

.module-button {
  min-height: 150px;
  padding: 22px;
  display: grid;
  align-content: start;
  gap: 10px;
  text-align: left;
  border: 1px solid var(--intro-line);
  border-radius: 20px;
  color: var(--intro-text);
  background: #fff;
  box-shadow: 0 8px 30px rgba(0, 0, 0, .045);
  cursor: pointer;
  transition: transform .35s cubic-bezier(.25, .46, .45, .94), box-shadow .35s cubic-bezier(.25, .46, .45, .94), border-color .35s ease;
}

.module-button:hover {
  border-color: rgba(17, 110, 138, .28);
}

.module-button strong {
  color: var(--intro-text);
  font-size: 20px;
}

.module-button small {
  margin: 0;
  color: var(--intro-muted);
  font-size: 14px;
}

.hardware-section {
  display: grid;
  gap: 4px;
}

.architecture-section {
  display: grid;
  gap: 4px;
}

.architecture-card {
  min-height: clamp(360px, 42vw, 560px);
  background: #f3f6fb;
}

.architecture-card img {
  min-height: clamp(360px, 42vw, 560px);
}

.architecture-card figcaption {
  max-width: 640px;
  right: auto;
  flex-direction: column;
  gap: 6px;
  color: #222e61;
  background: rgba(255, 255, 255, .78);
  border-color: rgba(223, 229, 240, .85);
}

.architecture-card figcaption span {
  color: #6c768f;
  line-height: 1.7;
}

.hardware-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
}

figure {
  position: relative;
  min-height: 280px;
  margin: 0;
  overflow: hidden;
  border: 1px solid var(--intro-line);
  border-radius: 24px;
  background: #111;
  box-shadow: 0 8px 30px rgba(0, 0, 0, .05);
  transition: transform .35s cubic-bezier(.25, .46, .45, .94), box-shadow .35s cubic-bezier(.25, .46, .45, .94);
}

figure img {
  width: 100%;
  height: 100%;
  min-height: 280px;
  display: block;
  object-fit: cover;
  filter: saturate(.82) contrast(1.02);
}

.radar-device-card img {
  object-position: 42% 62%;
}

figcaption {
  position: absolute;
  left: 18px;
  right: 18px;
  bottom: 18px;
  display: flex;
  justify-content: space-between;
  gap: 18px;
  padding: 16px 18px;
  border: 1px solid rgba(255, 255, 255, .18);
  border-radius: 18px;
  color: #fff;
  background: rgba(0, 0, 0, .48);
  backdrop-filter: blur(12px);
}

figcaption strong {
  font-size: 18px;
}

figcaption span {
  color: rgba(255, 255, 255, .72);
  font-size: 13px;
}

.product-strip {
  padding: 36px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 32px;
  border: 1px solid var(--intro-line);
  border-radius: 28px;
  background:
    radial-gradient(circle at 88% 18%, rgba(50, 91, 242, .08), transparent 28%),
    linear-gradient(135deg, rgba(255, 255, 255, .96), rgba(248, 250, 255, .98));
  box-shadow: 0 8px 30px rgba(34, 46, 97, .06);
}

.product-strip .eyebrow {
  color: #325bf2;
}

.product-strip h2 {
  color: #222e61;
}

.product-strip p {
  color: #6c768f;
}

.reveal-block {
  animation: introReveal both;
  animation-duration: 1ms;
  animation-timeline: view();
  animation-range: entry 0% cover 28%;
}

@keyframes introReveal {
  from {
    opacity: .24;
    transform: translateY(24px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@supports not (animation-timeline: view()) {
  .reveal-block {
    animation: none;
  }
}

@media (max-width: 1120px) {
  .hero-section,
  .showcase-grid,
  .pipeline,
  .module-grid,
  .hardware-grid,
  .product-strip {
    grid-template-columns: 1fr 1fr;
  }

  .hero-section,
  .product-strip {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .project-home {
    padding: 24px;
  }

  .hero-section,
  .showcase-grid,
  .pipeline,
  .module-grid,
  .hardware-grid,
  .product-strip {
    grid-template-columns: 1fr;
  }

  .pipeline-step {
    border-right: 0;
    border-bottom: 1px solid var(--intro-line);
  }

  .pipeline-step:last-child {
    border-bottom: 0;
  }

  figcaption {
    flex-direction: column;
  }
}
</style>
