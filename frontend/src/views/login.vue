<template>
  <div class="auth-container">
    <button
      class="theme-toggle"
      :class="{ dark: theme.isDark }"
      :title="theme.isDark ? '切换为浅色' : '切换为深色'"
      @click="theme.toggle()"
      aria-label="切换主题"
    >
      <span class="toggle-track">
        <span class="toggle-thumb">
          <svg v-if="theme.isDark" class="toggle-icon" viewBox="0 0 24 24" aria-hidden="true">
            <path fill="currentColor" d="M21 12.79A9 9 0 1 1 11.21 3a7 7 0 0 0 9.79 9.79z" />
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

    <!-- Tab 切换：登录 / 注册 -->
    <div class="tab-container">
      <button
          :class="['tab-btn', { active: isLoginMode }]"
          @click="isLoginMode = true"
      >
        登录
      </button>
      <button
          :class="['tab-btn', { active: !isLoginMode }]"
          @click="isLoginMode = false"
      >
        注册
      </button>
      <div class="tab-indicator" :class="{ login: isLoginMode, register: !isLoginMode }"></div>
    </div>

    <!-- ========== 登录表单 ========== -->
    <div v-if="isLoginMode" class="form-container">
      <h2 class="form-title">欢迎回来</h2>
      <form @submit.prevent="handleLogin">
        <input
            v-model="loginForm.userName"
            type="text"
            placeholder="账号"
            class="input-field"
            required
        />
        <input
            v-model="loginForm.passWord"
            type="passWord"
            placeholder="密码"
            class="input-field"
            required
        />
        <button type="submit" class="submit-btn">登录</button>
      </form>
    </div>

    <!-- ========== 注册表单 ========== -->
    <div v-else class="form-container">
      <h2 class="form-title">创建账户</h2>
      <form @submit.prevent="handleRegister">
        <input
            v-model="registerForm.userName"
            type="text"
            placeholder="账号"
            class="input-field"
            required
        />
        <input
            v-model="registerForm.passWord"
            type="passWord"
            placeholder="密码"
            class="input-field"
            required
        />
        <input
            v-model="registerForm.email"
            type="email"
            placeholder="邮箱"
            class="input-field"
            required
        />
        <button type="submit" class="submit-btn">注册</button>
      </form>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/userStore' // 路径根据你项目调整
import { useThemeStore } from '@/stores/themeStore'
import request from '@/utils/request'

const router = useRouter()
const userStore = useUserStore()
const theme = useThemeStore()
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
        userName: res.userName,
        email: res.email
      }

      // ✅ 存入 Pinia 全局状态
      userStore.setUserInfo(user)

      alert(`登录成功！欢迎回来，${user.userName}`)
      router.replace('/manage/project_intro') // 跳转后，Auth 页面自然不再显示
    } else {
      alert(res.message || '登录失败')
    }
  } catch (err) {
    console.error('登录失败:', err)
    alert(err.response?.data?.message || '网络错误，请稍后再试')
  } finally {
    loading.value = false
  }
}

// 注册逻辑保持不变（可选：注册成功后不清空 store）
const handleRegister = async () => {
  if (loading.value) return
  loading.value = true
  try {
    const userData = {
      userName: registerForm.userName,
      passWord: registerForm.passWord,
      email: registerForm.email
    }
    const res = await request.post('/register', userData)
    const { code, status, message } = res

    if (code === 200 || status === 'success') {
      alert('注册成功！请登录')
      Object.keys(registerForm).forEach(key => {
        registerForm[key] = ''
      })
      isLoginMode.value = true
    } else {
      alert(message || '注册失败')
    }
  } catch (err) {
    console.error('注册失败:', err)
    alert(err.response?.data?.message || '注册失败，请稍后再试')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.auth-container {
  position: relative;
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: var(--care-page-gradient);
  color: var(--care-text);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, sans-serif;
  padding: 20px;
  box-sizing: border-box;
  transition: background 0.35s ease, color 0.35s ease;
}

.theme-toggle {
  position: absolute;
  top: 24px;
  right: 24px;
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

.tab-container {
  position: relative;
  display: flex;
  flex-direction: row;
  flex-wrap: nowrap;
  align-items: center;
  justify-content: flex-start;
  margin-bottom: 32px;
  background: transparent;
  border-radius: 24px;
  overflow: hidden;
  padding: 4px;
  background-color: var(--care-surface-muted);
  width: fit-content;
}

.tab-btn {
  position: relative;
  padding: 10px 24px;
  border: none;
  background: transparent;
  color: var(--care-muted);
  cursor: pointer;
  font-size: 16px;
  font-weight: 500;
  transition: color 0.2s ease;
  z-index: 1;
  min-width: 80px;
  height: 36px;
  line-height: 36px;
  text-align: center;
  box-sizing: border-box;
  display: inline-block;
  writing-mode: horizontal-tb !important;
  -webkit-writing-mode: horizontal-tb !important;
  -moz-writing-mode: horizontal-tb !important;
  direction: ltr !important;
  unicode-bidi: normal;
  white-space: nowrap;
  transform: rotate(0deg) !important;
}

.tab-btn.active {
  color: var(--care-primary);
}

/* 底部滑动指示条 */
.tab-indicator {
  position: absolute;
  bottom: 4px;
  left: 4px;
  height: calc(100% - 8px);
  border-radius: 20px;
  background: var(--care-surface-strong);
  box-shadow: var(--care-shadow-soft);
  transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1), background 0.3s ease;
  width: 80px;
  z-index: 0;
}

.tab-indicator.login {
  transform: translateX(0);
}

.tab-indicator.register {
  transform: translateX(80px);
}

.form-container {
  width: 100%;
  max-width: 400px;
  padding: 32px;
  background: var(--care-surface-strong);
  color: var(--care-text);
  border: 1px solid var(--care-border-soft);
  border-radius: 16px;
  box-shadow: var(--care-shadow);
  box-sizing: border-box;
  transition: background 0.35s ease, color 0.35s ease, border-color 0.35s ease, box-shadow 0.35s ease;
}

.form-title {
  text-align: center;
  margin-bottom: 28px;
  color: var(--care-text-strong);
  font-size: 24px;
  font-weight: 600;
}

.input-field {
  width: 100%;
  padding: 12px 16px;
  margin-bottom: 18px;
  border: 1px solid var(--care-border);
  border-radius: 10px;
  font-size: 16px;
  background-color: var(--care-surface-muted);
  color: var(--care-text);
  transition: all 0.25s ease;
  box-sizing: border-box;
}

.input-field:focus {
  outline: none;
  border-color: var(--care-primary);
  background-color: var(--care-surface-strong);
  box-shadow: 0 0 0 2px var(--care-primary-soft);
}

.submit-btn {
  width: 100%;
  padding: 12px;
  background-color: var(--care-primary);
  color: var(--care-text-on-primary);
  border: none;
  border-radius: 10px;
  font-size: 16px;
  font-weight: 500;
  cursor: pointer;
  transition: background-color 0.2s ease, transform 0.1s ease;
  margin-top: 8px;
}

.submit-btn:hover {
  background-color: var(--care-primary-strong);
}

.submit-btn:active {
  transform: scale(0.98);
}
</style>
