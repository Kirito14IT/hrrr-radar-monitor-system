import { createRouter, createWebHistory } from 'vue-router'
import Login from '../views/login.vue'
import manage from "../views/manage.vue"
import data from "../views/data.vue";
import heart_pic from "../views/heart_pic.vue";
import login from "../views/login.vue";
import breath_pic from "../views/breath_pic.vue"; // <--- 引入新页面
import sleep_dashboard from "../views/sleep_dashboard.vue";

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [

    {path: '/', redirect: '/login'},

    {
      path:'/manage',
      component: manage,
      children:[
        {
          path: 'data',
          name: 'data',
          meta: { title: 'data' },
          component: data,
        },
        {
          path: 'heart_pic',
          name: 'heart_pic',
          meta: { title: 'heart_pic' },
          component: heart_pic,
        },
        {
          path: 'sleep_dashboard',
          name: 'sleep_dashboard',
          meta: { title: '睡眠看护驾驶舱' },
          component: sleep_dashboard,
        },
        // --- 新增路由 ---
        {
          path: 'breath_pic',
          name: 'breath_pic',
          meta: { title: '呼吸监测' },
          component: breath_pic,
        },
      ]
    },
    {path:'/login', component: login}
  ],
})

export default router
