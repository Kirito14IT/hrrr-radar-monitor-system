import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import time
import math
import random
import threading
import numpy as np

# 初始化 FastAPI
app = FastAPI(title="雷达模拟器", description="为前端开发提供的假数据服务")

# 允许跨域 (CORS)，这样你的 Vue 就能访问了
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 模拟的全局状态
state = {
    "heart_rate": 75.0,
    "target_distance": 0.8,
    "target_bin": 30,
    "breath_rate": 18.0,  # <--- 新增这行
    "phase_values": [],
    "running": True,
    "start_time": time.time(),
    "frame_count": 0
}


# 后台线程：不断生成变化的假数据
# 文件: radar-monitor-system/backend/mock_server.py

# 文件路径: radar-monitor-system/backend/mock_server.py

# ... (前面的代码不变) ...

# 修改 generate_fake_data 函数
def generate_fake_data():
    t = 0
    while True:
        t += 0.1

        # 将时间分段，模拟三种状态 (cycle 在 0-400 之间循环, 约40秒一轮)
        cycle = int(t * 10) % 400

        if cycle > 350:
            # === 场景3: 无人 (显示“未检测到生命体征”) ===
            state["target_distance"] = 0.0  # 距离为 0，代表无人
            state["heart_rate"] = 0.0
            state["breath_rate"] = 0.0
            # 无人时的杂波
            state["phase_values"] = np.random.normal(0, 0.05, 100).tolist()

        elif cycle > 300:
            # === 场景2: 有人但数值为0 (显示“过缓”) ===
            state["target_distance"] = 0.8  # 距离正常！(说明有人)
            state["heart_rate"] = 0.0  # 但心率是 0
            state["breath_rate"] = 0.0  # 呼吸是 0
            # 有人时的波形 (正弦波)
            state["phase_values"] = np.sin(np.linspace(t, t + 4 * np.pi, 100)).tolist()

        else:
            # === 场景1: 正常监测 ===
            state["target_distance"] = 0.8 + 0.05 * math.sin(t * 0.1)
            state["heart_rate"] = 75 + 5 * math.sin(t * 0.5) + random.uniform(-1, 1)
            state["breath_rate"] = 18 + 3 * math.sin(t * 0.2) + random.uniform(-0.5, 0.5)

            wave_t = np.linspace(t, t + 4 * np.pi, 100)
            state["phase_values"] = (np.sin(wave_t) * 1.5 + np.random.normal(0, 0.1, 100)).tolist()

        state["frame_count"] += 1
        time.sleep(0.1)





# 启动后台造数线程
threading.Thread(target=generate_fake_data, daemon=True).start()


# --- 接口定义 (保持与真实后端一致) ---

@app.get("/")
async def root():
    return {"message": "这是模拟雷达服务器"}


@app.get("/heartrate")
async def get_heart_rate():
    return {
        "heart_rate": round(state["heart_rate"], 1),
        "timestamp": time.time(),
        "status": "ok"
    }


@app.get("/target")
async def get_target_data():
    return {
        "heart_rate": round(state["heart_rate"], 1),
        "target_distance": round(state["target_distance"], 2),
        "target_bin": state["target_bin"],
        "timestamp": time.time(),
        "status": "ok"
    }


@app.get("/detailed")
async def get_detailed_data():
    return {
        "phase_values": state["phase_values"],  # 这是一个数组，前端拿去画折线图
        "target_distance": state["target_distance"],
        "heart_rate": state["heart_rate"],
        "breath_rate": state["breath_rate"],  # <--- 新增这行
        "timestamp": time.time()
    }


@app.get("/status")
async def get_status():
    return {
        "running": True,
        "uptime": time.time() - state["start_time"],
        "processed_frames": state["frame_count"]
    }


if __name__ == "__main__":
    print("启动模拟服务器: http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)
