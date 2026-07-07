# 睡眠看护与雷达监测系统——比赛测试与演示清单

> 当前后端电脑地址：`192.168.31.236`；后端 HTTP：`8081`；雷达 UDP：`9988`；前端开发端口：`5173`；雷达 WiFi：`B502`。

## 1. 演示目标

在五分钟内展示完整产品闭环：雷达无接触生命体征、Edgi Talk 守护模式、呼噜/环境/紧急事件上报、后端融合分析、Web 驾驶舱与 Android App 展示。

## 2. 设备与网络检查

| 设备 | 当前配置 | 检查项 |
| --- | --- | --- |
| 后端电脑 | `192.168.31.236` | 防火墙允许 TCP `8081` 和 UDP `9988` |
| Web 前端 | `http://localhost:5173` | 能访问 `192.168.31.236:8081` |
| Edgi Talk / 小智 | `192.168.31.236:8081` | `backend_cfg_status` 显示正确 |
| 雷达板 | WiFi `B502`，UDP `192.168.31.236:9988` | 已重新烧录当前固件 |
| Android App | `http://192.168.31.236:8081` | 能开始监听并显示数据 |

M55 如仍保存旧后端，烧录后执行：

```text
backend_cfg_set 192.168.31.236 8081
```

## 3. 后端启动与接口检查

```powershell
C:\Users\toward\anaconda3\envs\radar\python.exe backend\realtime_radar_processing.py --ip 雷达板IP --port 9988 --decomp-type cwt --api-port 8081
Invoke-RestMethod http://192.168.31.236:8081/status
Invoke-RestMethod "http://192.168.31.236:8081/sleep/overview?mode=live&seconds=1800"
```

`/status` 重点看：

- `radar_board_online`
- `radar_online`
- `total_frames`
- `edgi_board_online`
- `environment_board_online`
- `snore_board_online`

## 4. 演示流程

1. 打开 Web 前端，进入首页和实时监测页。
2. 展示雷达生命体征：心率、呼吸率、趋势图。
3. 展示环境：温度、湿度、声音/舒适度。
4. 展示小智守护模式：屏幕显示守护模式在线、呼噜状态和当前时间。
5. 播放/模拟呼噜，观察呼噜分数和前端状态。
6. 触发紧急事件：语音求救或开发板摇晃，确认前端弹窗。
7. 在告警中心填写处理人和说明，确认解除事件。
8. 切换到小智对话模式，演示与大模型聊天。
9. 打开 Android App，确认心率、呼吸率、温湿度、打鼾情况同步显示。

## 5. 快速降级方案

| 问题 | 可能原因 | 处理 |
| --- | --- | --- |
| Edgi Talk 数据不上报 | Flash 中仍保存旧 IP | 执行 `backend_cfg_set 192.168.31.236 8081` |
| 雷达板 WiFi 成功但后端无数据 | UDP 目标、网段、防火墙或未烧录 | 检查 `192.168.31.236:9988`、Private 网络、防火墙、重新烧录 |
| 前端请求失败 | 后端未启动或 CORS/地址不一致 | 访问 `http://192.168.31.236:8081/status` 确认 |
| Android 不刷新 | App 缓存旧地址 | 重新填写地址或清除应用数据 |

## 6. 手工接口模拟

环境心跳：

```powershell
$body = '{"temperature_c":26.0,"humidity_pct":55,"sensor_ok":true}'
Invoke-RestMethod -Method Post -Uri http://192.168.31.236:8081/hardware/environment-heartbeat -ContentType "application/json" -Body $body
```

呼噜心跳：

```powershell
$body = '{"snore_detected":true,"snore_score":0.8,"dbfs":-20,"session_active":true}'
Invoke-RestMethod -Method Post -Uri http://192.168.31.236:8081/hardware/snore-heartbeat -ContentType "application/json" -Body $body
```

紧急事件：

```powershell
$body = '{"type":"emergency_voice","message":"求助语音","source":"小智语音开发板"}'
Invoke-RestMethod -Method Post -Uri http://192.168.31.236:8081/emergency -ContentType "application/json" -Body $body
```
