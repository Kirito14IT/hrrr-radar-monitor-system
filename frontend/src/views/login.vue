<template>
  <div class="auth-container">
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
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background-color: #fafafa;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, sans-serif;
  padding: 20px;
  box-sizing: border-box;
}

.tab-container {
  position: relative;
  display: flex;
  margin-bottom: 32px;
  background: transparent;
  border-radius: 24px;
  overflow: hidden;
  padding: 4px;
  background-color: #f0f2f5;
  width: fit-content;
}

.tab-btn {
  position: relative;
  padding: 10px 24px;
  border: none;
  background: transparent;
  color: #666;
  cursor: pointer;
  font-size: 16px;
  font-weight: 500;
  transition: color 0.2s ease;
  z-index: 1;
}

.tab-btn.active {
  color: #1a73e8;
}

/* 底部滑动指示条 */
.tab-indicator {
  position: absolute;
  bottom: 4px;
  height: 28px;
  border-radius: 20px;
  background: white;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.08);
  transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  width: calc(50% - 4px);
}

.tab-indicator.login {
  transform: translateX(0);
}

.tab-indicator.register {
  transform: translateX(100%);
}

.form-container {
  width: 100%;
  max-width: 400px;
  padding: 32px;
  background: white;
  border-radius: 16px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.06);
  box-sizing: border-box;
}

.form-title {
  text-align: center;
  margin-bottom: 28px;
  color: #1a1a1a;
  font-size: 24px;
  font-weight: 600;
}

.input-field {
  width: 100%;
  padding: 12px 16px;
  margin-bottom: 18px;
  border: 1px solid #ddd;
  border-radius: 10px;
  font-size: 16px;
  background-color: #fafafa;
  transition: all 0.25s ease;
  box-sizing: border-box;
}

.input-field:focus {
  outline: none;
  border-color: #1a73e8;
  background-color: white;
  box-shadow: 0 0 0 2px rgba(26, 115, 232, 0.15);
}

.submit-btn {
  width: 100%;
  padding: 12px;
  background-color: #1a73e8;
  color: white;
  border: none;
  border-radius: 10px;
  font-size: 16px;
  font-weight: 500;
  cursor: pointer;
  transition: background-color 0.2s ease, transform 0.1s ease;
  margin-top: 8px;
}

.submit-btn:hover {
  background-color: #1765c4;
}

.submit-btn:active {
  transform: scale(0.98);
}
</style>
