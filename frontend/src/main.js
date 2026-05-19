// main.js
import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import { createPinia } from 'pinia'
import piniaPluginPersistedstate from 'pinia-plugin-persistedstate'

// Element Plus
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import zhCn from 'element-plus/es/locale/lang/zh-cn'

// Element Plus Icons
import * as ElementPlusIconsVue from '@element-plus/icons-vue'

// 全局样式
import '@/assets/global.css'

// 创建应用实例（只创建一次！）
const app = createApp(App)

// 创建并配置 Pinia
const pinia = createPinia()
pinia.use(piniaPluginPersistedstate)
app.use(pinia)

// 使用路由
app.use(router)

// 使用 Element Plus（带中文）
app.use(ElementPlus, {
    locale: zhCn
})

// 注册所有图标组件
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
    app.component(key, component)
}

// 挂载（只挂载一次！）
app.mount('#app')