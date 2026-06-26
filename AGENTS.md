# AGENTS.md

本文件记录当前项目的关键结构、运行约定、已完成改造、排障结论和后续维护注意事项。后续智能体或开发者接手本仓库时，应优先阅读本文件，再修改代码。

## 1. 项目概览

本项目是一个多端联动的睡眠/雷达看护系统，核心链路是：

```text
雷达板 UDP 数据
  -> Python 后端实时处理
  -> Vue 前端 / Android App 展示
  -> 小智 M55 开发板提供守护、关键词、呼噜、对话和紧急事件能力
```

主要目录：

- `backend/`：Python 后端，负责 UDP 雷达数据接收、生命体征处理、HTTP API、用户数据、睡眠看护事件聚合。
- `frontend/`：Vue + Vite 前端，展示心率、呼吸率、睡眠状态、环境、告警中心等页面。
- `android_app/`：Android App，默认连接同一个后端 API，并展示心率、呼吸率、温湿度、打鼾情况。
- `radar_wifi/`：英飞凌雷达 WiFi 固件，负责连接 WiFi 并向后端 UDP 发送雷达帧。
- `Edgi_Talk_M55_XiaoZhi/`：小智 M55 工程，已加入守护模式/对话模式、呼噜检测、关键词检测和后端联动。
- `Edgi_Talk_M33_AHT20/`、`M33_AHT20/`：温湿度环境采集相关工程。
- `docs/`：比赛文档、测试清单、PPT 大纲等。
- `build_doc_assets/`：报告/文档生成脚本与本地渲染素材。只应提交脚本和必要源文件，不应提交大批渲染缓存。
- `DEMO_README.md`：比赛演示测试清单。
- `docs/competition_5min_ppt_outline.md`：约五分钟 PPT 大纲。

## 2. 当前统一 IP 与端口约定

当前项目统一后端地址：

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
  - `UDP_SERVER_IP_ADDRESS` 应为 `MAKE_IPV4_ADDRESS(192, 168, 0, 102)`。
  - `UDP_SERVER_PORT` 为 `9988`。
- `frontend/src/utils/request.js`
  - 默认 API 地址为 `http://192.168.0.102:8081`。
  - 仍允许通过 `VITE_API_BASE_URL` 覆盖。
- `android_app/app/src/main/java/com/radarcare/guardian/GuardianPrefs.kt`
  - Android 默认后端地址为 `http://192.168.0.102:8081`。
- `Edgi_Talk_M55_XiaoZhi/applications/backend_target_config.c`
  - 小智开发板默认后端为 `192.168.0.102:8081`。

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
- 如果不知道雷达板 IP，先看雷达板串口中的 `IP Address Assigned: ...`。

重要 API：

- `GET /status`：系统和设备在线状态。
- `GET /sleep/overview?mode=live&seconds=1800`：睡眠看护聚合接口。
- `GET /target`、`GET /heartrate`、`GET /detailed`：实时数据接口。
- `POST /hardware/snore-heartbeat`：呼噜检测心跳。
- `POST /hardware/environment-heartbeat`：环境温湿度心跳。
- `POST /emergency`、`POST /emergency/resolve`：紧急事件接口。

已知后端修复：

- `/sleep/overview` 曾因 `last_radar_received_at` 字符串参与 float 计算导致 500，已增强 `_seconds_since()` 兼容性。
- CORS 已允许 `localhost:5173`、`127.0.0.1:5173`、`192.168.0.102:5173` 及局域网常见开发来源。
- Windows UDP 可能因 ICMP Port Unreachable 抛 `ConnectionResetError [WinError 10054]`，后端已做防护，避免主循环退出。
- 后端已增加雷达包过滤：只有符合固件格式的 UDP 数据帧才会被当作雷达数据，避免 JSON 控制包或广播包造成“假在线”。
- 模型推理曾因 `backend/trained_models/DeepStateSpace_CWT_best.keras` 加载/路径问题异常，已修复推理链路，并可输出心率、呼吸率。

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

而后端电脑在：

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

### 4.2 陀螺仪/运动门控已从雷达侧删除

用户要求删除雷达陀螺仪相关功能。当前已完成：

- 删除：
  - `radar_wifi/source/motion_gate.c`
  - `radar_wifi/source/motion_gate.h`
- `radar_task.c` 不再 include 或调用 `motion_gate`。
- 雷达帧不再因板子“未静止”而暂停。
- 不再生成 `board_still / motion_delta / sensor_ready` 状态包。
- BLE 状态包移除 IMU/静止相关字段和 API：
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

曾在当前 PowerShell/Modus shell 环境执行：

```powershell
make -j8
```

失败原因不是 C 代码错误，而是 ModusToolbox/MSYS 路径环境异常，例如把路径拼成：

```text
/d/STUDY/.../radar_wifi/C:/Users/toward/ModusToolbox/...
```

需要在正常 ModusToolbox 环境中编译、烧录。

修改雷达目标 IP 或 UDP 逻辑后必须重新编译并烧录雷达固件，否则板子仍使用旧固件。

## 5. 小智 M55 双模式改造

小智 M55 已做“双模式”：

### 5.1 守护模式

- 默认模式。
- 进行关键词检测和呼噜检测。
- 普通 LLM/TTS 对话被抑制。
- 离线呼噜检测仍可运行。
- 适合睡眠看护场景。
- UI 文案：
  - 在线：`守护模式在线`
  - 离线：`守护模式离线`
- 屏幕已增加当前时间显示。

### 5.2 对话模式

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
- 烧录后如果仍连接旧后端，执行：

```text
backend_cfg_set 192.168.0.102 8081
```

## 6. 呼噜、报警、存在性检测

当前业务规则：

- 呼噜持续时认为处于呼噜事件中。
- 后续要求已改为：呼噜声音消失 1.5 秒以上才算停止。
- 呼噜停止时，如果雷达呼吸信号正好处于下降趋势，则触发报警。
- 当呼噜响起时，关闭/绕过存在性检测，避免存在性检测误干扰呼噜告警逻辑。
- 存在性检测阈值已调低约 15%，对应 `backend/presence_detection.py` 中阈值从约 `1.2` 调到约 `1.02`。

注意：

- 修改后端报警/融合逻辑后必须重启后端进程。
- 修改 M55 呼噜检测逻辑后必须重新编译并烧录 M55。

## 7. 前端与 Android

### 7.1 前端

目录：

```text
frontend/
```

构建命令：

```powershell
npm run build
```

当前要点：

- Vite 开发服务器通常是 `http://localhost:5173`。
- 默认 API 指向 `http://192.168.0.102:8081`。
- 可通过 `VITE_API_BASE_URL` 覆盖。
- 与雷达陀螺仪相关的前端默认状态已改为 `disabled`，不应再显示“雷达板未静止”。

### 7.2 Android

目录：

```text
android_app/
```

当前要点：

- 默认后端地址和输入提示均为 `http://192.168.0.102:8081`。
- App 需要显示：
  - 心率
  - 呼吸率
  - 温湿度
  - 打鼾情况
- 已安装的 App 可能缓存旧地址，需要在 App 内重新填写或清除应用数据。
- 曾经手工生成过 debug APK，路径在本地构建目录中；构建产物不应提交到 Git。

## 8. 比赛演示资料

已新增/维护：

- `DEMO_README.md`：测试比赛演示清单。
- `docs/competition_5min_ppt_outline.md`：约五分钟 PPT 大纲。
- 根 `README.md` 已链接相关资料。

演示前建议检查：

1. 后端 API：`http://192.168.0.102:8081/status`
2. 前端页面是否能登录并读取状态。
3. 雷达板串口是否显示拿到 `192.168.0.xxx`。
4. `/status` 中：
   - `radar_board_online: true`
   - `radar_online: true`
   - `total_frames` 持续增长
5. 小智守护模式/对话模式切换是否正常。
6. 呼噜、环境、紧急事件接口是否可用。
7. Android App 是否显示心率、呼吸率、温湿度和打鼾情况。

## 9. 常见问题与快速定位

### 9.1 前端 CORS 报错

浏览器 CORS 报错不一定是 CORS 本身。曾经 `/login` 的真实原因是后端 500，而 500 又来自本地 MySQL 未运行。当前后端已支持 SQLite fallback。

排查顺序：

1. 直接请求后端接口，看 HTTP 状态码。
2. 看后端日志。
3. 再看 CORS 配置。

### 9.2 雷达 WiFi 显示连接成功但后端没有数据

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

### 9.3 后端短暂假在线

曾经广播 `{"radar_transmission":"enable"}` 会被后端误当雷达帧。现在已通过包头校验修复。不要删除 `_is_valid_radar_data_packet()`。

### 9.4 Windows 网络必须切到 Private

如果雷达板已在同网段但 UDP 仍收不到，检查 Windows 当前 WLAN 网络是否为 Private。Public 网络配置下防火墙可能拦截局域网入站 UDP/HTTP。

## 10. GitHub 与版本库状态

当前远端：

```text
https://github.com/Kirito14IT/hrrr-radar-monitor-system.git
```

当前主分支：

```text
main
```

最近一次已推送提交：

```text
ab109a0 chore: update project demo and device integration
```

推送经验：

- 当前环境里 `gh` 命令不可用，因此没有创建 PR。
- 普通 `git push origin main` 曾多次出现 GitHub HTTPS `HTTP 502`。
- 最终使用以下命令推送成功：

```powershell
git push --no-thin origin main
```

`.gitignore` 已补充：

- `~$*.docx`：忽略 Word 临时锁文件。
- `mtb_shared/`：忽略 ModusToolbox 本地依赖缓存。
- `build_doc_assets/chrome_screenshot_profile/`
- `build_doc_assets/rendered*/`
- `build_doc_assets/__pycache__/`
- `build_doc_assets/*_render.pdf`
- `build_doc_assets/*_temp.docx`
- `build_doc_assets/competition_submission_render*.pdf`
- `build_doc_assets/competition_submission_temp.docx`

不要提交：

- `build_doc_assets/` 下的大量截图、PDF、渲染目录、浏览器缓存。
- `docs/~$*.docx` 这类 Word 临时锁文件。
- `radar_wifi/error.txt`。
- `mtb_shared/` 本地依赖缓存。
- Android/M55/雷达固件构建产物。

## 11. 开发维护约定

- 搜索优先用 `rg`。
- 本仓库已有大量用户改动，未明确要求不要随意 commit、reset 或清理。
- 不要使用破坏性 git 命令，例如 `git reset --hard`。
- 修改文件优先用补丁方式，避免覆盖用户已有改动。
- 雷达固件和小智固件改动后，必须提醒用户重新编译并烧录。
- 后端改动后，必须重启后端进程才会生效。
- 前端改动后，开发服务器可能需要重启或重新构建。
- 推送到 GitHub 前，先看 `git status -sb`，确认没有临时文件/生成物混入。

## 12. 当前验证记录

最近验证过：

- `python -m py_compile backend/realtime_radar_processing.py backend/realtime_radar_processing_9988.py`：通过。
- `frontend` 中 `npm run build`：通过。
- M55 中 `scons -Q -j8`：通过。
- 雷达固件源码扫描：已无 `motion_gate / BMI270 / IMU / board_not_still / accel_delta` 等引用。
- 雷达固件 `make -j8`：当前机器 ModusToolbox/MSYS 路径环境异常，未进入 C 编译阶段。
- GitHub 推送：`git push --no-thin origin main` 成功。

## 13. 最重要提醒

当前项目最容易出问题的不是算法，而是“网络是否真在同一个局域网”：

- 后端电脑 IP 必须是设备可达的地址。
- 雷达板、M55、Android、前端浏览器都要指向同一个后端。
- 雷达板 WiFi 成功不代表后端可达；一定要看分配到的 IP 网段。

如果只记一条：雷达板串口拿到 `192.168.0.xxx`，后端是 `192.168.0.102`，UDP 目标是 `192.168.0.102:9988`，这条链路才是对的。
