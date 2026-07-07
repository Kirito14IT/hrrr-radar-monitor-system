<template>
  <div class="auth-page">
    <section class="auth-shell" aria-label="护理监护系统登录">
      <div class="auth-intro">
        <div class="brand-mark">
          <img src="@/assets/logo.svg" alt="Radar Care" />
          <span>Radar Care</span>
        </div>
        <h1>智慧床位护理监护平台</h1>
        <p>
          面向医院与疗养院护理人员，统一查看床位状态、生命体征、呼噜风险和紧急事件。
        </p>

        <div class="intro-grid">
          <div class="intro-card care-icon-card" data-icon="BED">
            <strong>多床位</strong>
            <span>集中监视床位状态</span>
          </div>
          <div class="intro-card care-icon-card" data-icon="SOS">
            <strong>实时告警</strong>
            <span>异常事件及时提醒</span>
          </div>
          <div class="intro-card care-icon-card" data-icon="HR">
            <strong>生命体征</strong>
            <span>心率 / 呼吸 / 环境联动</span>
          </div>
        </div>
      </div>

      <div class="auth-card care-icon-card" data-icon="ID">
        <div class="auth-card-header">
          <span class="eyebrow">NURSE STATION</span>
          <h2>{{ isLoginMode ? '护理人员登录' : '创建护理账号' }}</h2>
          <p>{{ isLoginMode ? '登录后进入床位监视台' : '注册后即可加入护理监护平台' }}</p>
        </div>

        <div class="tab-container" role="tablist" aria-label="登录注册切换">
          <button
            type="button"
            :class="['tab-btn', { active: isLoginMode }]"
            role="tab"
            :aria-selected="isLoginMode"
            @click="isLoginMode = true"
          >
            登录
          </button>
          <button
            type="button"
            :class="['tab-btn', { active: !isLoginMode }]"
            role="tab"
            :aria-selected="!isLoginMode"
            @click="isLoginMode = false"
          >
            注册
          </button>
        </div>

        <form v-if="isLoginMode" class="auth-form" @submit.prevent="handleLogin">
          <label>
            <span>账号</span>
            <input v-model.trim="loginForm.userName" type="text" placeholder="请输入账号" required />
          </label>
          <label>
            <span>密码</span>
            <input v-model="loginForm.passWord" type="password" placeholder="请输入密码" required />
          </label>
          <button type="submit" class="submit-btn" :disabled="loading">
            {{ loading ? '正在登录...' : '进入护理监视台' }}
          </button>
        </form>

        <form v-else class="auth-form" @submit.prevent="handleRegister">
          <label>
            <span>账号</span>
            <input v-model.trim="registerForm.userName" type="text" placeholder="设置登录账号" required />
          </label>
          <label>
            <span>密码</span>
            <input v-model="registerForm.passWord" type="password" placeholder="设置登录密码" required />
          </label>
          <label>
            <span>邮箱</span>
            <input v-model.trim="registerForm.email" type="email" placeholder="用于接收系统通知" required />
          </label>
          <button type="submit" class="submit-btn" :disabled="loading">
            {{ loading ? '正在注册...' : '创建账号' }}
          </button>
        </form>
      </div>
    </section>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/userStore'
import request from '@/utils/request'

const router = useRouter()
const userStore = useUserStore()
const isLoginMode = ref(true)
const loading = ref(false)

const loginForm = reactive({
  userName: '',
  passWord: ''
})

const registerForm = reactive({
  userName: '',
  passWord: '',
  email: ''
})

const handleLogin = async () => {
  if (loading.value) return
  loading.value = true
  try {
    const res = await request.post('/login', {
      userName: loginForm.userName,
      passWord: loginForm.passWord
    })

    if (res.status === 'success' || res.code === 200) {
      const user = {
        userID: res.user_id,
        userName: res.userName || loginForm.userName,
        email: res.email
      }
      userStore.setUserInfo(user)
      ElMessage.success(`登录成功，欢迎回来，${user.userName}`)
      router.replace('/manage/project_intro')
    } else {
      ElMessage.error(res.message || '登录失败')
    }
  } catch (err) {
    console.error('登录失败:', err)
    ElMessage.error(err.response?.data?.message || '无法连接后端服务，请确认 8081 端口已启动')
  } finally {
    loading.value = false
  }
}

const handleRegister = async () => {
  if (loading.value) return
  loading.value = true
  try {
    const res = await request.post('/register', {
      userName: registerForm.userName,
      passWord: registerForm.passWord,
      email: registerForm.email
    })

    if (res.code === 200 || res.status === 'success') {
      ElMessage.success('注册成功，请登录')
      Object.keys(registerForm).forEach(key => {
        registerForm[key] = ''
      })
      isLoginMode.value = true
    } else {
      ElMessage.error(res.message || '注册失败')
    }
  } catch (err) {
    console.error('注册失败:', err)
    ElMessage.error(err.response?.data?.message || '注册失败，请稍后再试')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.auth-page {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 32px;
  color: var(--care-text);
  background:
    radial-gradient(circle at 12% 12%, rgba(26, 188, 156, 0.14), transparent 30%),
    radial-gradient(circle at 88% 18%, rgba(96, 165, 250, 0.16), transparent 32%),
    linear-gradient(135deg, #f7fbfb 0%, #eef8f7 54%, #f3f7ff 100%);
  box-sizing: border-box;
}

.auth-shell {
  width: min(1080px, 100%);
  display: grid;
  grid-template-columns: minmax(0, 1.08fr) minmax(360px, 0.82fr);
  gap: 28px;
  align-items: stretch;
}

.auth-intro,
.auth-card {
  border: 1px solid rgba(172, 196, 205, 0.72);
  border-radius: 30px;
  background: rgba(255, 255, 255, 0.88);
  box-shadow: 0 24px 60px rgba(58, 94, 112, 0.14);
  backdrop-filter: blur(14px);
}

.auth-intro {
  position: relative;
  overflow: hidden;
  padding: 42px;
  min-height: 520px;
}

.auth-intro::after {
  content: '';
  position: absolute;
  right: -90px;
  bottom: -120px;
  width: 360px;
  height: 360px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(26, 188, 156, 0.2), rgba(96, 165, 250, 0.06) 58%, transparent 70%);
}

.brand-mark {
  display: inline-flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  border-radius: 999px;
  background: #f3fbfa;
  border: 1px solid #d9eeea;
  color: #0f766e;
  font-weight: 800;
}

.brand-mark img {
  width: 30px;
  height: 30px;
}

.auth-intro h1 {
  max-width: 520px;
  margin: 58px 0 18px;
  font-size: clamp(36px, 5vw, 58px);
  line-height: 1.06;
  color: #0f2537;
  letter-spacing: -0.04em;
}

.auth-intro p {
  max-width: 520px;
  margin: 0;
  color: #557084;
  font-size: 18px;
  line-height: 1.8;
}

.intro-grid {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  margin-top: 58px;
}

.intro-card {
  min-height: 96px;
  padding: 18px;
  border-radius: 20px;
  background: linear-gradient(180deg, #ffffff 0%, #f6fbfb 100%);
  border: 1px solid #dfecef;
  box-shadow: 0 12px 28px rgba(31, 78, 101, 0.08);
}

.intro-card strong {
  display: block;
  color: #123047;
  font-size: 20px;
  margin-bottom: 8px;
}

.intro-card span {
  color: #64798a;
  font-size: 14px;
  line-height: 1.5;
}

.auth-card {
  padding: 36px;
}

.auth-card-header {
  margin-bottom: 24px;
}

.eyebrow {
  display: inline-flex;
  color: #0f9488;
  font-size: 12px;
  font-weight: 900;
  letter-spacing: 0.16em;
}

.auth-card h2 {
  margin: 12px 0 8px;
  color: #10283c;
  font-size: 30px;
  line-height: 1.2;
}

.auth-card p {
  margin: 0;
  color: #6a7f90;
}

.tab-container {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
  padding: 6px;
  margin-bottom: 24px;
  border-radius: 18px;
  background: #eef7f7;
}

.tab-btn {
  height: 44px;
  border: 0;
  border-radius: 14px;
  color: #60778a;
  background: transparent;
  font-size: 16px;
  font-weight: 800;
  cursor: pointer;
  transition: all 0.2s ease;
}

.tab-btn.active {
  color: #0f766e;
  background: #ffffff;
  box-shadow: 0 10px 24px rgba(31, 78, 101, 0.1);
}

.auth-form {
  display: grid;
  gap: 18px;
}

.auth-form label {
  display: grid;
  gap: 8px;
  color: #425c70;
  font-size: 14px;
  font-weight: 800;
}

.auth-form input {
  height: 48px;
  padding: 0 15px;
  border: 1px solid #d6e5e9;
  border-radius: 14px;
  outline: none;
  background: #fbfefe;
  color: #0f2537;
  font-size: 15px;
  transition: all 0.2s ease;
}

.auth-form input:focus {
  border-color: #1abc9c;
  box-shadow: 0 0 0 4px rgba(26, 188, 156, 0.14);
}

.submit-btn {
  height: 50px;
  margin-top: 4px;
  border: 0;
  border-radius: 16px;
  color: #ffffff;
  background: linear-gradient(135deg, #17b69f, #2b8ee8);
  box-shadow: 0 16px 32px rgba(26, 188, 156, 0.22);
  font-size: 16px;
  font-weight: 900;
  cursor: pointer;
  transition: transform 0.2s ease, box-shadow 0.2s ease, opacity 0.2s ease;
}

.submit-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 20px 38px rgba(26, 188, 156, 0.28);
}

.submit-btn:disabled {
  cursor: not-allowed;
  opacity: 0.68;
}

@media (max-width: 900px) {
  .auth-shell {
    grid-template-columns: 1fr;
  }

  .auth-intro {
    min-height: auto;
  }
}

@media (max-width: 640px) {
  .auth-page {
    padding: 18px;
  }

  .auth-intro,
  .auth-card {
    padding: 24px;
    border-radius: 24px;
  }

  .intro-grid {
    grid-template-columns: 1fr;
    margin-top: 32px;
  }
}
</style>
