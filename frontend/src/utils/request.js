import axios from "axios";
import {ElMessage} from "element-plus";

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8081'

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
