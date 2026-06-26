# AGENTS.md

本文件记录当前项目的关键信息、已知约定、排障结论和后续维护注意事项。后续智能体或开发者接手本仓库时，应优先阅读本文件，再改代码。

## 1. 项目概览

本项目是一个多端联动的睡眠/雷达看护系统，核心链路是：

```text
雷达板 UDP 数据
        ↓
Python 后端实时处理
        ↓
Vue 前端 / Android App 展示
        ↓
小智开发板提供守护、呼噜、关键词、对话等辅助能力
```

主要目录：

- `backend/`：Python 后端，负责 UDP 雷达数据接收、生命体征处理、HTTP API、用户数据、睡眠看护驾驶舱数据聚合。
- `frontend/`：Vue + Vite 前端，展示心率、呼吸、睡眠看护驾驶舱、预警中心等页面。
- `android_app/`：Android App，默认连接同一个后端 API。
- `radar_wifi/`：英飞凌雷达 WiFi 固件，负责连接 WiFi 并向后端 UDP 发送雷达帧。
- `Edgi_Talk_M55_XiaoZhi/`：小智 M55 工程，已加入守护模式/对话模式以及后端联动。
- `Edgi_Talk_M33_AHT20/`、`M33_AHT20/`：环境温湿度相关工程。
- `docs/`、`build_doc_assets/`：比赛文档、测试清单、报告生成脚本等。
- `DEMO_README.md`：比赛演示测试清单。
- `docs/competition_5min_ppt_outline.md`：约五分钟比赛 PPT 大纲。

## 2. 当前统一 IP 与端口约定

当前项目统一后端地址为：

```text
192.168.0.102:8081
```

雷达 UDP 数据目标：

```text
192.168.0.102:9988
```

后端监听：

```text
HTTP API: 0.0.0.0:8081
UDP 雷达: 0.0.0.0:9988
```

关键文件：

- `radar_wifi/source/udp_server.c`
  - `UDP_SERVER_IP_ADDRESS` 应为 `MAKE_IPV4_ADDRESS(192, 168, 0, 102)`
  - `UDP_SERVER_PORT` 为 `9988`
- `frontend/src/utils/request.js`
  - 默认 API 地址为 `http://192.168.0.102:8081`
  - 仍允许通过 `VITE_API_BASE_URL` 覆盖
- `android_app/app/src/main/java/com/radarcare/guardian/GuardianPrefs.kt`
  - Android 默认后端地址也是 `http://192.168.0.102:8081`
- `Edgi_Talk_M55_XiaoZhi/applications/backend_target_config.c`
  - 小智开发板默认后端为 `192.168.0.102:8081`

不要误改的地址：

- 配网门户 `192.168.169.1` 不属于后端地址，不要改。
- 开发板自身静态地址、历史测试脚本里的设备地址，不应因统一后端 IP 被机械替换。
- 后端仍应监听 `0.0.0.0:8081`，不要改成只监听 `192.168.0.102`。

## 3. 后端运行与重要行为

主后端入口：

```text
backend/realtime_radar_processing.py
```

常用启动命令示例：

```powershell
C:\Users\toward\anaconda3\envs\radar\python.exe backend\realtime_radar_processing.py --ip 雷达板IP --port 9988 --decomp-type cwt --api-port 8081
```

说明：

- `--port 9988` 是本机 UDP 监听端口。
- `--api-port 8081` 是 HTTP API 端口。
- `--ip 雷达板IP` 用于后端主动向雷达板发送 `{"radar_transmission":"enable"}` 控制包。
- 如果不知道雷达板 IP，可以先看雷达板串口中的 `IP Address Assigned: ...`。

重要 API：

- `GET /status`：系统和设备在线状态。
- `GET /sleep/overview?mode=live&seconds=1800`：睡眠看护驾驶舱聚合接口。
- `GET /target`、`GET /heartrate`、`GET /detailed`：实时数据接口。
- `POST /hardware/snore-heartbeat`：呼噜检测心跳。
- `POST /hardware/environment-heartbeat`：环境温湿度心跳。
- `POST /emergency`、`POST /emergency/resolve`：小智紧急语音事件。

后端已知修复：

- `/sleep/overview` 曾因 `last_radar_received_at` 字符串参与 float 计算导致 500，已改为使用内部时间戳并增强 `_seconds_since()` 兼容性。
- CORS 已允许：
  - `http://localhost:5173`
  - `http://127.0.0.1:5173`
  - `http://192.168.0.102:5173`
  - 以及 `localhost / 127.0.0.1 / 192.168.x.x` 的常见端口。
- Windows UDP 可能因 ICMP Port Unreachable 抛 `ConnectionResetError [WinError 10054]`，后端已防护，避免主循环退出。
- 后端已增加雷达包过滤：只有符合雷达固件格式的 UDP 数据帧才会被当成雷达数据，避免 JSON 控制包或广播包造成“假在线”。

数据库：

- `backend/db.py` 支持 MySQL，也支持 MySQL 不可用时自动 fallback 到 SQLite。
- 默认 SQLite 文件为 `backend/user_data.db`，已加入 `.gitignore`。

## 4. 雷达板固件现状

雷达固件目录：

```text
radar_wifi/
```

关键文件：

- `radar_wifi/configs/wifi_config.h`：WiFi SSID/密码。
- `radar_wifi/source/udp_server.c`：UDP 目标 IP/端口、WiFi 连接、控制命令接收。
- `radar_wifi/source/radar_task.c`：雷达采集和 UDP 数据发送。
- `radar_wifi/source/ble_radar_service.c/h`：雷达 BLE 状态/控制服务。

### 4.1 雷达 WiFi 排障结论

曾经串口显示：

```text
Successfully connected to Wi-Fi network 'chen'.
IP Address Assigned: 10.166.247.149
```

而电脑后端在：

```text
192.168.0.102
```

这说明雷达板和后端电脑不在同一局域网，后端无法稳定收到雷达 UDP。雷达板必须连接到与电脑同一网段的 2.4G WiFi，例如拿到 `192.168.0.xxx` 地址。

正确串口期望类似：

```text
Successfully connected to Wi-Fi network '...'
IP Address Assigned: 192.168.0.xxx
Socket bound to port: 9988
Radar data transmission is enabled
```

### 4.2 陀螺仪/运动门控已删除

用户要求删除雷达陀螺仪相关功能。当前已完成：

- 删除：
  - `radar_wifi/source/motion_gate.c`
  - `radar_wifi/source/motion_gate.h`
- `radar_task.c` 不再 include 或调用 `motion_gate`。
- 雷达帧不再因板子“未静止”而暂停。
- 不再生成 `board_still / motion_delta / sensor_ready` 状态包。
- BLE 状态包移除了 IMU/静止相关字段和 API：
  - `RADAR_BLE_FLAG_BOARD_STILL`
  - `RADAR_BLE_FLAG_IMU_READY`
  - `motion_delta`
  - `ble_radar_service_note_frame_blocked`
  - `ble_radar_service_update_motion`
- 后端保留兼容字段，但固定为：
  - `radar_board_stationary = true`
  - `radar_motion_reason = "disabled"`
  - `radar_motion_delta = null`
  - `radar_motion_sensor_ready = null`

后续不要再恢复 BMI270、IMU、motion gate、board still gating 等逻辑，除非用户明确要求。

### 4.3 雷达固件编译注意

曾尝试在当前 PowerShell/Modus shell 环境执行：

```powershell
make -j8
```

失败原因不是 C 代码错误，而是 ModusToolbox/MSYS 路径环境异常，例如把路径拼成：

```text
/d/STUDY/.../radar_wifi/C:/Users/toward/ModusToolbox/...
```

需要在正常 ModusToolbox 环境中编译、烧录。

## 5. 小智 M55 双模式改造

小智 M55 已做“双模式”：

### 守护模式

- 默认模式。
- 进行关键词检测和呼噜检测。
- 普通 LLM/TTS 对话被抑制。
- 离线呼噜检测仍可运行。
- 适合睡眠看护场景。

### 对话模式

- 可与小智大模型聊天。
- 进入对话模式时停止呼噜/关键词守护流程。
- 顶部用户按键可从守护模式进入对话模式。
- UI 中有守护/对话按钮和状态显示。

涉及文件包括：

- `Edgi_Talk_M55_XiaoZhi/applications/xiaozhi/xiaozhi.cpp`
- `Edgi_Talk_M55_XiaoZhi/applications/xiaozhi/xiaozhi.h`
- `Edgi_Talk_M55_XiaoZhi/applications/xiaozhi/wake_word/snore_detect.cpp`
- `Edgi_Talk_M55_XiaoZhi/applications/xiaozhi/ui/xiaozhi_ui.c`
- `Edgi_Talk_M55_XiaoZhi/applications/xiaozhi/ui/xiaozhi_ui.h`
- `Edgi_Talk_M55_XiaoZhi/applications/env_monitor_m55.c`
- `Edgi_Talk_M55_XiaoZhi/applications/backend_target_config.c`

M55 编译曾通过：

```powershell
scons -Q -j8
```

运行时注意：

- M55 Flash 中旧配置会覆盖新编译默认值。
- 烧录后如仍连接旧后端，执行：

```text
backend_cfg_set 192.168.0.102 8081
```

## 6. 前端与 Android

前端：

- 目录：`frontend/`
- 构建命令：

```powershell
npm run build
```

当前构建已通过。

注意：

- Vite 开发服务器通常是 `http://localhost:5173`。
- 默认 API 指向 `http://192.168.0.102:8081`。
- 可通过 `VITE_API_BASE_URL` 覆盖。
- 与雷达陀螺仪相关的前端默认状态已改为 `disabled`，不应再显示“雷达板未静止”。

Android：

- 目录：`android_app/`
- 已将默认后端地址和输入提示改为 `http://192.168.0.102:8081`。
- 已安装的 App 可能缓存旧地址，需要在 App 内重新填写或清除应用数据。

## 7. 比赛演示资料

已新增/维护：

- `DEMO_README.md`：测试比赛演示清单。
- `docs/competition_5min_ppt_outline.md`：约五分钟 PPT 大纲。
- 根 `README.md` 已链接这些材料。

演示前建议检查：

1. 后端 API：`http://192.168.0.102:8081/status`
2. 前端页面是否能登录、读取状态。
3. 雷达板串口是否显示拿到 `192.168.0.xxx`。
4. `/status` 中：
   - `radar_board_online: true`
   - `radar_online: true`
   - `total_frames` 持续增长
5. 小智守护模式/对话模式切换是否正常。
6. 呼噜、环境、紧急事件接口是否可用。

## 8. 常见问题与快速定位

### 8.1 前端 CORS 报错

浏览器 CORS 报错不一定是 CORS 本身。曾经 `/login` 的真实原因是后端 500，而 500 又来自本机 MySQL 未运行。当前后端已支持 SQLite fallback。

排查顺序：

1. 直接请求后端接口，看 HTTP 状态码。
2. 看后端日志。
3. 再看 CORS 配置。

### 8.2 雷达 WiFi 显示连接成功但后端没数据

优先看串口：

```text
IP Address Assigned: ...
```

如果不是 `192.168.0.xxx`，基本就是网络错位。让雷达板和后端电脑连接同一个 2.4G 局域网。

再看后端：

```powershell
Invoke-RestMethod http://127.0.0.1:8081/status
```

重点字段：

- `radar_board_online`
- `radar_online`
- `total_frames`
- `last_radar_received_at`
- `radar_age_seconds`

### 8.3 后端短暂假在线

曾经广播 `{"radar_transmission":"enable"}` 会被后端误当雷达帧。现在已通过包头校验修复。不要删除 `_is_valid_radar_data_packet()`。

### 8.4 雷达目标 IP 改动后必须重新烧录

修改 `radar_wifi/source/udp_server.c` 后，需要重新编译并烧录雷达固件，否则板子仍使用旧目标。

## 9. 开发维护约定

- 搜索优先用 `rg`。
- 本仓库已有大量历史/用户改动，未明确要求不要随意 commit、reset 或清理。
- 不要使用破坏性 git 命令，例如 `git reset --hard`。
- 编辑文件优先用补丁方式，避免覆盖用户已有改动。
- 雷达固件和小智固件改动后，必须提醒用户重新编译并烧录。
- 后端改动后，必须重启后端进程才会生效。
- 前端改动后，开发服务器可能需要重启或重新构建。

## 10. 当前验证记录

最近验证过：

- `python -m py_compile backend/realtime_radar_processing.py backend/realtime_radar_processing_9988.py`：通过。
- `frontend` 下 `npm run build`：通过。
- 雷达固件源码扫描：已无 `motion_gate / BMI270 / IMU / board_not_still / accel_delta` 等引用。
- 雷达固件 `make -j8`：当前机器 ModusToolbox/MSYS 路径环境异常，未进入 C 编译阶段。

## 11. 重要提醒

当前项目最容易出问题的不是算法，而是“网络是否真在同一个局域网”：

- 后端电脑 IP 必须是设备可达的地址。
- 雷达板、M55、Android、前端浏览器都要指向同一个后端。
- 雷达板 WiFi 成功不代表后端可达；一定看分配到的 IP 网段。

如果只记一条：雷达板串口拿到 `192.168.0.xxx`，后端是 `192.168.0.102`，UDP 目标是 `192.168.0.102:9988`，这条链路才是对的。
