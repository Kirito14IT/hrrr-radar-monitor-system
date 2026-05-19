<template>
  <div class="project-home care-page-shell">
    <section class="intro-hero care-glass-card">
      <div class="hero-copy">
        <div class="care-kicker">Final Project Overview</div>
        <h1>毫米波雷达睡眠看护与呼噜扰动监测系统</h1>
        <p>
          本项目面向卧室、养老看护和睡眠健康展示场景，使用毫米波雷达开发板与呼噜检测开发板两路传感器，
          在非接触条件下完成生命体征采集、呼噜扰动识别、睡眠稳定性分析和看护预警闭环。
        </p>
        <div class="hero-actions">
          <el-button type="primary" size="large" @click="go('/manage/heart_pic')">进入实时监测</el-button>
          <el-button size="large" @click="go('/manage/sleep_dashboard')">查看睡眠驾驶舱</el-button>
        </div>
      </div>

      <div class="system-visual" aria-label="系统双开发板数据流示意">
        <div class="sensor-node radar">
          <span>RADAR BOARD</span>
          <strong>毫米波雷达开发板</strong>
          <small>心率 / 呼吸率 / 距离 / 是否离床</small>
        </div>
        <div class="fusion-core">
          <span>EDGE + WEB APP</span>
          <strong>多源融合分析</strong>
          <small>时序对齐、风险评分、报告生成</small>
        </div>
        <div class="sensor-node acoustic">
          <span>ACOUSTIC BOARD</span>
          <strong>呼噜检测开发板</strong>
          <small>呼噜强度 / 音频片段 / 夜间扰动</small>
        </div>
      </div>
    </section>

    <section class="snapshot-grid">
      <article v-for="item in valueCards" :key="item.title" class="snapshot-card care-glass-card">
        <span>{{ item.index }}</span>
        <strong>{{ item.title }}</strong>
        <p>{{ item.desc }}</p>
      </article>
    </section>

    <section class="content-grid">
      <article class="story-card care-glass-card">
        <div class="section-title">
          <div>
            <div class="care-kicker">System Story</div>
            <h2>最终项目如何工作</h2>
          </div>
        </div>
        <div class="flow-steps">
          <div v-for="step in flowSteps" :key="step.title" class="flow-step">
            <span>{{ step.index }}</span>
            <div>
              <strong>{{ step.title }}</strong>
              <p>{{ step.desc }}</p>
            </div>
          </div>
        </div>
      </article>

      <article class="photo-card care-glass-card">
        <div class="section-title">
          <div>
            <div class="care-kicker">Hardware Photos</div>
            <h2>开发板实拍图</h2>
          </div>
        </div>
        <div class="photo-showcase">
          <figure
            v-for="photo in hardwarePhotos"
            :key="photo.title"
            class="hardware-photo"
            :class="photo.className"
          >
            <img :src="photo.src" :alt="photo.alt" loading="lazy" decoding="async" />
            <figcaption class="photo-caption">
              <span>{{ photo.tag }}</span>
              <strong>{{ photo.title }}</strong>
              <p>{{ photo.desc }}</p>
            </figcaption>
          </figure>
        </div>
      </article>
    </section>

    <section class="module-map care-glass-card">
      <div class="section-title">
        <div>
          <div class="care-kicker">Web App Modules</div>
          <h2>页面功能说明</h2>
        </div>
      </div>
      <div class="module-list">
        <button v-for="module in modules" :key="module.path" class="module-item" @click="go(module.path)">
          <span>{{ module.code }}</span>
          <div>
            <strong>{{ module.title }}</strong>
            <p>{{ module.desc }}</p>
          </div>
        </button>
      </div>
    </section>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'

const router = useRouter()

const valueCards = [
  {
    index: '01',
    title: '非接触生命体征',
    desc: '毫米波雷达在不佩戴设备的情况下感知胸腔微动，提取心率、呼吸率和目标距离。'
  },
  {
    index: '02',
    title: '呼噜扰动识别',
    desc: '呼噜检测开发板持续采集音频特征，输出呼噜强度、事件状态和可追溯音频片段。'
  },
  {
    index: '03',
    title: '睡眠看护闭环',
    desc: '系统将生命体征、呼噜、离床和设备状态融合成风险等级、动作队列和历史报告。'
  },
  {
    index: '04',
    title: '展示级 Web App',
    desc: '前端提供实时监测、睡眠驾驶舱、预警中心和历史 AI 分析，适合答辩或项目演示。'
  }
]

const flowSteps = [
  {
    index: 'Step 1',
    title: '双开发板采集',
    desc: '雷达板负责心率、呼吸率、目标距离和离床状态；呼噜板负责音频特征和呼噜事件。'
  },
  {
    index: 'Step 2',
    title: '边缘侧上报',
    desc: '两路数据按时间戳进入后端，统一为秒级时间轴，避免心率、呼吸率和呼噜强度错位。'
  },
  {
    index: 'Step 3',
    title: '融合分析',
    desc: '后端生成睡眠分期、扰动热力、设备状态、异常事件和本地/AI 健康分析报告。'
  },
  {
    index: 'Step 4',
    title: '看护决策',
    desc: 'Web App 将风险解释为可操作建议，例如检查床旁状态、确认板卡在线或观察呼吸波动。'
  }
]

const hardwarePhotos = [
  {
    tag: 'PHOTO A',
    title: '毫米波雷达开发板',
    desc: '用于非接触采集心率、呼吸率、目标距离与离床状态，是系统生命体征侧输入。',
    src: '/pic/hardware/hardware-radar-board.jpg',
    alt: '毫米波雷达开发板实拍图，包含雷达天线、接口和 RT-Thread 开发板标识',
    className: 'radar-board'
  },
  {
    tag: 'PHOTO B',
    title: '呼噜检测开发板',
    desc: '用于采集夜间呼噜扰动与音频事件，和雷达数据共同进入后端融合分析。',
    src: '/pic/hardware/snore-detect-board.jpg',
    alt: '呼噜检测 E84 Edgi Talk 开发板实拍图，屏幕显示 Snore detect 状态',
    className: 'snore-board'
  }
]

const modules = [
  {
    code: 'LIVE',
    title: '生命体征监测',
    path: '/manage/heart_pic',
    desc: '实时展示心率、呼吸率、呼噜强度、声浪监测、睡眠分期和健康摘要。'
  },
  {
    code: 'SLEEP',
    title: '睡眠看护驾驶舱',
    path: '/manage/sleep_dashboard',
    desc: '用睡眠质量评分、呼噜扰动地图和夜间事件流呈现整晚状态。'
  },
  {
    code: 'ALERT',
    title: '看护预警中心',
    path: '/manage/alert_center',
    desc: '把异常归因转成照护动作队列，适合夜间值守和演示说明。'
  },
  {
    code: 'DATA',
    title: '历史数据与 AI 洞察',
    path: '/manage/data',
    desc: '查询历史生命体征，生成本地规则或 DeepSeek 健康分析报告。'
  }
]

function go(path) {
  router.push(path)
}
</script>

<style scoped>
.project-home {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.intro-hero {
  display: grid;
  grid-template-columns: minmax(420px, 1fr) minmax(420px, 0.85fr);
  gap: 28px;
  align-items: center;
  padding: 30px;
  overflow: hidden;
}

.hero-copy h1 {
  max-width: 760px;
  margin: 10px 0 14px;
  font-size: clamp(34px, 4vw, 58px);
  line-height: 1.08;
  letter-spacing: -0.06em;
}

.hero-copy p {
  max-width: 760px;
  margin: 0;
  color: var(--care-muted);
  font-size: 17px;
  line-height: 1.8;
}

.hero-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 24px;
}

.system-visual {
  position: relative;
  display: grid;
  gap: 18px;
  padding: 20px;
  border-radius: 28px;
  background:
    radial-gradient(circle at 50% 44%, rgba(56, 189, 248, 0.28), transparent 26%),
    linear-gradient(145deg, rgba(7, 24, 39, 0.92), rgba(8, 51, 47, 0.88));
  box-shadow: inset 0 0 0 1px rgba(255,255,255,.08);
}

.system-visual::before {
  content: "";
  position: absolute;
  left: 14%;
  right: 14%;
  top: 50%;
  height: 2px;
  background: linear-gradient(90deg, transparent, rgba(56, 189, 248, 0.72), transparent);
}

.sensor-node,
.fusion-core {
  position: relative;
  z-index: 1;
  display: grid;
  gap: 6px;
  padding: 18px;
  border-radius: 22px;
  color: #e8fbff;
  border: 1px solid rgba(255, 255, 255, 0.13);
  background: rgba(255, 255, 255, 0.08);
  backdrop-filter: blur(10px);
}

.sensor-node span,
.fusion-core span {
  color: #8bdcf1;
  font-size: 11px;
  font-weight: 900;
  letter-spacing: 0.14em;
}

.sensor-node strong,
.fusion-core strong {
  font-size: 20px;
}

.sensor-node small,
.fusion-core small {
  color: #b7d8e5;
}

.fusion-core {
  margin: 0 38px;
  text-align: center;
  background: linear-gradient(135deg, rgba(22, 183, 169, 0.42), rgba(56, 189, 248, 0.25));
}

.snapshot-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(180px, 1fr));
  gap: 14px;
}

.snapshot-card {
  padding: 18px;
}

.snapshot-card span,
.flow-step span,
.module-item > span,
.photo-caption span {
  color: var(--care-primary-strong);
  font-size: 12px;
  font-weight: 900;
  letter-spacing: 0.12em;
}

.snapshot-card strong {
  display: block;
  margin: 10px 0 8px;
  font-size: 19px;
}

.snapshot-card p,
.flow-step p,
.module-item p {
  margin: 0;
  color: var(--care-muted);
  line-height: 1.65;
}

.content-grid {
  display: grid;
  grid-template-columns: minmax(420px, 1fr) minmax(360px, 0.8fr);
  gap: 18px;
}

.story-card,
.photo-card,
.module-map {
  padding: 22px;
}

.section-title {
  margin-bottom: 18px;
}

.section-title h2 {
  margin: 8px 0 0;
  font-size: 26px;
}

.flow-steps,
.photo-showcase,
.module-list {
  display: grid;
  gap: 12px;
}

.flow-step {
  display: grid;
  grid-template-columns: 86px 1fr;
  gap: 14px;
  padding: 16px;
  border-radius: 18px;
  background: rgba(255,255,255,.62);
  border: 1px solid rgba(15, 143, 133, 0.12);
}

.flow-step strong {
  display: block;
  margin-bottom: 5px;
}

.hardware-photo {
  position: relative;
  min-height: clamp(210px, 17vw, 260px);
  margin: 0;
  overflow: hidden;
  border-radius: 24px;
  background: #071827;
  border: 1px solid rgba(15, 143, 133, 0.18);
  box-shadow: var(--care-shadow-soft);
  isolation: isolate;
}

.hardware-photo img {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  display: block;
  object-fit: cover;
  transform: scale(1.01);
  transition: transform 0.24s ease;
}

.hardware-photo:hover img {
  transform: scale(1.045);
}

.hardware-photo::after {
  content: "";
  position: absolute;
  inset: 0;
  z-index: 1;
  background:
    linear-gradient(180deg, rgba(7, 24, 39, 0.05) 0%, rgba(7, 24, 39, 0.12) 36%, rgba(7, 24, 39, 0.84) 100%),
    radial-gradient(circle at 16% 18%, rgba(56, 189, 248, 0.18), transparent 38%);
}

.radar-board img {
  object-position: 50% 54%;
}

.snore-board img {
  object-position: 50% 48%;
}

.photo-caption {
  position: absolute;
  left: 18px;
  right: 18px;
  bottom: 18px;
  z-index: 2;
  display: grid;
  gap: 7px;
  color: #f8fdff;
}

.photo-caption span {
  width: fit-content;
  padding: 5px 8px;
  border-radius: 999px;
  color: #dffcff;
  background: rgba(7, 24, 39, 0.62);
  border: 1px solid rgba(255, 255, 255, 0.16);
  backdrop-filter: blur(8px);
}

.photo-caption strong {
  font-size: 20px;
  text-shadow: 0 2px 14px rgba(0, 0, 0, 0.28);
}

.photo-caption p {
  max-width: 620px;
  margin: 0;
  color: rgba(232, 251, 255, 0.82);
  line-height: 1.55;
}

.module-list {
  grid-template-columns: repeat(4, minmax(180px, 1fr));
}

.module-item {
  display: grid;
  gap: 9px;
  min-height: 150px;
  padding: 17px;
  text-align: left;
  border: 1px solid rgba(15, 143, 133, 0.14);
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.68);
  box-shadow: var(--care-shadow-soft);
  cursor: pointer;
  transition: transform 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;
}

.module-item:hover {
  transform: translateY(-3px);
  border-color: rgba(15, 143, 133, 0.34);
  box-shadow: var(--care-shadow);
}

.module-item strong {
  display: block;
  margin-bottom: 6px;
  color: var(--care-text);
}

@media (max-width: 1280px) {
  .intro-hero,
  .content-grid,
  .snapshot-grid,
  .module-list {
    grid-template-columns: 1fr 1fr;
  }
}

@media (max-width: 760px) {
  .project-home {
    padding: 16px;
  }

  .intro-hero,
  .content-grid,
  .snapshot-grid,
  .module-list {
    grid-template-columns: 1fr;
  }

  .flow-step {
    grid-template-columns: 1fr;
  }

  .fusion-core {
    margin: 0;
  }
}
</style>
