// stores/userStore.js
import { defineStore } from 'pinia'

export const useUserStore = defineStore('user', {
    state: () => ({
        userInfo: null, // { userID, userName, email }
    }),
    actions: {
        setUserInfo(user) {
            this.userInfo = user
        },
        clearUserInfo() {
            this.userInfo = null
        },
        isLoggedIn() {
            return !!this.userInfo
        }
    },
    // 可选：启用持久化（刷新不丢失）
    persist: true
})