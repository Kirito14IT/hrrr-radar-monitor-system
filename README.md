# 睡眠看护与雷达监测系统

本项目现在以真实硬件数据为主：雷达板通过 UDP 上传生命体征，Edgi Talk M55 上传呼噜、温湿度和紧急求助，前端与安卓监护人 App 从真实后端读取状态。

## 启动顺序

1. 启动真实后端：

   ```powershell
   cd D:\STUDY\hrrr-radar-monitor-system
   python backend\realtime_radar_processing.py
   ```

2. 启动前端：

   ```powershell
   cd D:\STUDY\hrrr-radar-monitor-system\frontend
   npm run dev
   ```

3. 配置 Edgi Talk M55 后端地址：

   ```text
   backend_cfg_set 192.168.31.236 8081
   backend_cfg_status
   ```

4. 雷达板、M55、安卓 App 和前端都连接到同一后端地址：

   ```text
   http://192.168.31.236:8081
   ```

## 真实硬件接口

M55 固件使用以下真实硬件接口上报数据：

- `POST /hardware/snore-session/start`
- `POST /hardware/snore-heartbeat`
- `POST /hardware/snore-session/stop`
- `POST /hardware/environment-heartbeat`
- `POST /emergency`
- `POST /emergency/resolve`

雷达板继续使用现有 UDP 链路，后端收到雷达数据后更新 `/status`、`/timeline` 和 `/sleep/overview`。

## 小智 M55 双模式

- **守护模式（上电默认）**：本地持续进行呼噜推理，同时通过小智云 `always_on` STT 检测“救命、帮帮我、需要帮助、快来人、我不舒服、喘不过气、胸口痛、摔倒了、头晕、很难受”。普通语句不会播放大模型回复；断网时呼噜检测继续，关键词状态显示离线。
- **对话模式**：暂停呼噜和求助词监测，切换后立即进入小智多轮对话，允许 STT、LLM 和 TTS。
- 主屏使用“守护模式 / 对话模式”双按钮切换；守护模式下按顶部用户键也可快速进入对话。

## 常用检查

```powershell
curl http://localhost:8081/status
curl "http://localhost:8081/sleep/overview?mode=live&seconds=1800"
```

手动验证环境心跳：

```powershell
curl -Method POST http://localhost:8081/hardware/environment-heartbeat -ContentType "application/json" -Body '{"temperature_c":24.5,"humidity_pct":52.0,"sensor_ok":true,"source":"manual_check"}'
```

手动验证呼噜心跳：

```powershell
curl -Method POST http://localhost:8081/hardware/snore-heartbeat -ContentType "application/json" -Body '{"snore_score":0.72,"snore_detected":true,"dbfs":-24.0,"source":"manual_check"}'
```

手动验证紧急求助：

```powershell
curl -Method POST http://localhost:8081/emergency -ContentType "application/json" -Body '{"source":"manual_check","phrase":"救命","transcript":"小智救命我需要帮助"}'
```

## 测试文档

完整测试清单见：

- `DEMO_README.md`（比赛演示与故障降级清单）
- `docs/competition_5min_ppt_outline.md`（五分钟 PPT 大纲）
- `docs/full_project_test_checklist.md`
- `docs/edgi_m55_imu_sos_real_test.md`

本系统用于课程设计和看护辅助展示，不作为医疗诊断或真实急救系统。
