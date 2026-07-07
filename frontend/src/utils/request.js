import axios from "axios";
import {ElMessage} from "element-plus";

const resolveDefaultApiBaseUrl = () => {
    const lanBackend = 'http://192.168.31.236:8081'
    if (typeof window === 'undefined') return lanBackend
    const host = window.location.hostname
    if (!host || host === 'localhost' || host === '127.0.0.1' || host === '::1') {
        return lanBackend
    }
    return `http://${host}:8081`
}

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || resolveDefaultApiBaseUrl()

const request = axios.create({
    baseURL: API_BASE_URL,
    timeout: 30000
})
// request 拦截器
// 可以自请求发送前对请求做一些处理
request.interceptors.request.use(
    config => {
        config.headers["Content-Type"] = "application/json;charset=utf-8";
        return config;
    },
    error => {
        return Promise.reject(error);
    }
);

// response 拦截器
// 可以在接口响应后统一处理结果
request.interceptors.response.use(
    response => {
        let res = response.data;
        // 兼容服务端返回的字符串数据
        if (typeof res === "string") {
            res = res ? JSON.parse(res) : res;
        }
        return res;
    },
    error => {
        if (error.response?.status === 404) {
            ElMessage.error('未找到请求接口');
        } else if (error.response?.status === 500) {
            ElMessage.error('系统异常, 请查看后端控制台');
        } else {
            console.error(error.message);
        }
        return Promise.reject(error);
    }
);

export default request;
