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
- `docs/`、`DEMO_README.md`：比赛文档、测试清单、PPT 大纲等。

## 2. 当前网络配置

当前后端电脑 IP：

```text
192.168.31.236
```

当前统一后端地址：

```text
192.168.31.236:8081
```

雷达 UDP 数据目标：

```text
192.168.31.236:9988
```

当前雷达 WiFi：

```text
SSID: B502
Password: b5026666
```

后端监听仍然是：

```text
HTTP API: 0.0.0.0:8081
UDP 雷达: 0.0.0.0:9988
```

不要误改：

- 配网门户 `192.168.169.1` 不属于后端地址，不要改。
- 后端不要改成只监听 `192.168.31.236`，应继续监听 `0.0.0.0`。
- 雷达板、M55、Android、前端浏览器都要能访问 `192.168.31.236`。

关键文件：

- `radar_wifi/configs/wifi_config.h`：雷达 WiFi SSID/密码，以及雷达 UDP 目标 `RADAR_UDP_SERVER_IP_ADDRESS` / `RADAR_UDP_SERVER_PORT`。
- `backend/config/bed_devices.json`：多床位设备绑定配置，包含 `bed_id`、床位信息、雷达板 `radar_ip`、小智/Edgi `edgi_device_id` / `edgi_source`。
- `radar_wifi/source/udp_server.c`：雷达 UDP 发送逻辑，目标地址实际读取 `wifi_config.h` 中的 `RADAR_UDP_SERVER_*` 配置。
- `frontend/src/utils/request.js`：默认 API `http://192.168.31.236:8081`，仍允许 `VITE_API_BASE_URL` 覆盖。
- `android_app/app/src/main/java/com/radarcare/guardian/GuardianPrefs.kt`：Android 默认后端地址。
- `Edgi_Talk_M55_XiaoZhi/applications/board_device_config.h`：小智/呼噜板编译期配置，包含后端地址、`bed_id`、`device_id`、各类 `source`，多块板烧录前优先改这里。
- `Edgi_Talk_M55_XiaoZhi/applications/backend_target_config.c`：小智后端地址和设备身份读取逻辑，默认使用 `board_device_config.h`，不再依赖串口写入。

### 2.1 每次调整配置必须同步的位置

以后只要换 WiFi、后端电脑 IP、端口、床位或设备身份，按下表逐项检查：

| 调整内容 | 必改文件/位置 | 当前值 | 改完后必须做 |
| --- | --- | --- | --- |
| 后端电脑 IP | `radar_wifi/configs/wifi_config.h` 的 `RADAR_UDP_SERVER_IP_ADDRESS` | `MAKE_IPV4_ADDRESS(192, 168, 31, 236)` | 重新编译并烧录雷达固件 |
| 雷达 WiFi | `radar_wifi/configs/wifi_config.h` 的 `WIFI_SSID` / `WIFI_PASSWORD` | `B502` / `b5026666` | 重新编译并烧录雷达固件 |
| 雷达 UDP 端口 | `radar_wifi/configs/wifi_config.h` 的 `RADAR_UDP_SERVER_PORT`；后端启动参数 `--port` | `9988` | 雷达重烧；后端用同端口启动 |
| 雷达发送逻辑 | `radar_wifi/source/udp_server.c` | 实际使用 `RADAR_UDP_SERVER_IP_ADDRESS` / `RADAR_UDP_SERVER_PORT` | 重新编译并烧录雷达固件 |
| 小智/呼噜板后端地址 | `Edgi_Talk_M55_XiaoZhi/applications/board_device_config.h` 的 `BOARD_BACKEND_HOST` / `BOARD_BACKEND_PORT` | `192.168.31.236` / `8081` | 重新编译并烧录 M55 |
| 小智/呼噜板床位身份 | `board_device_config.h` 的 `BOARD_BED_ID`、`BOARD_DEVICE_ID`、`BOARD_EDGI_SOURCE`、`BOARD_SNORE_SOURCE`、`BOARD_ENV_SOURCE` | 默认 `bed-001` / `xiaozhi-bed-001` | 每块板烧录前改成唯一值 |
| 是否允许 Flash 覆盖 M55 编译配置 | `board_device_config.h` 的 `BOARD_USE_FLASH_BACKEND_CONFIG` / `BOARD_USE_FLASH_DEVICE_CONFIG` | `0` / `0` | 保持 0 表示串口旧配置不会覆盖编译配置 |
| 后端床位/设备绑定 | `backend/config/bed_devices.json` | 真实床位 + 模拟床位 | 修改后重启后端，同步到 SQLite `bed_registry` |
| 前端默认 API | `frontend/src/utils/request.js` | `http://192.168.31.236:8081` | 重新启动 Vite 或重新构建 |
| Android 默认 API | `android_app/app/src/main/java/com/radarcare/guardian/GuardianPrefs.kt` 和 `MainActivity.kt` 输入提示 | `http://192.168.31.236:8081` | 重新构建安装；已安装 App 可能需清数据 |
| 后端 CORS | `backend/realtime_radar_processing.py`、`backend/realtime_radar_processing_9988.py` | 允许 `192.168.31.236:5173` 和局域网正则 | 修改后重启后端 |
| 文档/演示清单 | `AGENTS.md`、`DEMO_README.md`、`README.md`、`CODEX_DEV_README.md` | 当前 B502 / `192.168.31.236` | 改配置后同步，避免演示排障看错 |
| 比赛核心代码副本 | `code/` 下对应子目录 | 已同步到 `192.168.31.236` / `B502` | 如重新打包 `code/`，再复查一次 |

注意：后端进程本身仍应监听 `0.0.0.0:8081` 和 `0.0.0.0:9988`，不要把监听地址改成固定 IP。固定 IP 只用于“其它设备连接到电脑”。

## 3. 后端运行

主入口：

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
- 修改后端代码后必须重启进程。

重要 API：

- `GET /status`
- `GET /sleep/overview?mode=live&seconds=1800`
- `GET /target`、`GET /heartrate`、`GET /detailed`
- `POST /hardware/snore-heartbeat`
- `POST /hardware/environment-heartbeat`
- `POST /emergency`、`POST /emergency/resolve`

## 4. 雷达板注意事项

雷达固件目录：`radar_wifi/`。

当前已删除雷达陀螺仪/运动门控逻辑，不要恢复 BMI270、IMU、motion gate、board still gating，除非用户明确要求。

修改雷达 WiFi、UDP 目标 IP 或端口后，必须重新编译并烧录雷达固件，否则板子仍使用旧固件。正确串口期望类似：

```text
Successfully connected to Wi-Fi network 'B502'
IP Address Assigned: 192.168.31.xxx
Socket bound to port: 9988
Radar data transmission is enabled
```

如果雷达 WiFi 连接成功但后端没有数据，优先确认：

1. 雷达板 IP 是否为 `192.168.31.xxx`，必须和后端电脑 `192.168.31.236` 在同一网段。
2. 后端电脑是否为 `192.168.31.236`。
3. Windows 当前 WLAN 网络是否为 Private。
4. 防火墙是否允许 TCP `8081` 和 UDP `9988`。
5. 雷达固件是否已重新烧录。
6. 串口是否出现 `Failed to send data to client`；若出现，说明雷达板端 UDP 发送失败，优先查板子实际 IP、目标 IP、网关/AP 隔离、防火墙和是否烧录了最新固件。

### 4.1 BLE 默认禁用（射频共存）

雷达固件 `radar_wifi/Makefile` 的 `ENABLE_RADAR_BLE` 默认已置 `0`，BLE 协议栈不再启动，BGT60TR13C 雷达独占 2.4GHz 射频。

历史根因（2026-07-04 排障）：BGT60TR13C 雷达与 WICED BLE 共用 2.4GHz 射频前端，BLE 协议栈 `BTM_ENABLED_EVT`（`Radar BLE: stack enabled`）回调后射频被 BLE 接管，雷达 GPIO 数据中断停止触发，`radar_task` 的 `ulTaskNotifyTake()` 永远等不到通知，UDP 数据流停在前约 140 帧、`/status.total_frames` 不再增长。

因此**不要默认把 `ENABLE_RADAR_BLE` 改回 1**。如确需 BLE 本地配置，可用 `ENABLE_RADAR_BLE=1` 临时构建，但必须重新评估射频共存时序，否则上述停帧问题会立即复现。

## 5. 小智 M55 现状

小智 M55 已做双模式：

- 守护模式：关键词检测、呼噜检测、紧急事件、环境/呼噜心跳上报。
- 对话模式：可与小智大模型聊天，切换模式会终止当前模式流程。

UI 文案：

- 在线：`守护模式在线`
- 离线：`守护模式离线`
- 屏幕已增加当前时间显示。

多套小智/Edgi E84 同时部署时，不再推荐串口配置。每块板烧录前直接修改：

```text
Edgi_Talk_M55_XiaoZhi/applications/board_device_config.h
```

关键字段：

```c
#define BOARD_BACKEND_HOST "192.168.31.236"
#define BOARD_BACKEND_PORT 8081
#define BOARD_BED_ID        "bed-001"
#define BOARD_DEVICE_ID     "xiaozhi-bed-001"
#define BOARD_EDGI_SOURCE   "xiaozhi_board_001"
#define BOARD_SNORE_SOURCE  "real_snore_board_001"
#define BOARD_ENV_SOURCE    "edgi_talk_m55_001"
```

第二块板示例：

```c
#define BOARD_BED_ID        "bed-002"
#define BOARD_DEVICE_ID     "xiaozhi-bed-002"
#define BOARD_EDGI_SOURCE   "xiaozhi_board_002"
#define BOARD_SNORE_SOURCE  "real_snore_board_002"
#define BOARD_ENV_SOURCE    "edgi_talk_m55_002"
```

`BOARD_USE_FLASH_BACKEND_CONFIG` 和 `BOARD_USE_FLASH_DEVICE_CONFIG` 默认均为 `0`，因此旧的 `/flash/backend_config.json`、`/flash/device_config.json` 不会覆盖编译期配置。如需恢复串口命令覆盖能力，才改成 `1`。

配置后，小智在线心跳、呼噜心跳、环境心跳、语音求救/摇晃等紧急事件，以及 emergency-sync 轮询都会带上 `bed_id` / `device_id` / `source`。

如 M55 仍连旧 WiFi，需要通过配网门户重新写入 WiFi，或清除旧网络配置。

## 5.1 多床位设备绑定配置

后端启动时会读取：

```text
backend/config/bed_devices.json
```

该文件是当前多设备归属的主配置。典型配置项：

```json
{
  "bed_id": "bed-002",
  "bed_label": "02床",
  "room": "护理房间",
  "patient_name": "测试患者02",
  "radar_ip": "192.168.0.121",
  "radar_port": 9988,
  "edgi_device_id": "xiaozhi-bed-002",
  "edgi_source": "xiaozhi_board_002"
}
```

映射规则：

- 雷达板：后端按 UDP 来源 IP 匹配 `bed_registry.radar_ip`。
- 小智/Edgi：优先按上报 JSON 中的 `bed_id` 归床；没有 `bed_id` 时按 `device_id` 匹配 `edgi_device_id`；再按 `source` 匹配 `edgi_source`。
- 旧设备不带身份字段时仍默认归到 `bed-001`。

修改 `backend/config/bed_devices.json` 后需要重启后端，后端会同步到 SQLite 的 `bed_registry` 表。修改雷达 `wifi_config.h` 后需要重新编译并烧录雷达固件。

## 6. 呼噜、报警、存在性检测

当前规则要点：

- 板端呼噜模型使用直接置信度判定版本，不使用“置信度累积衰减”版本。
- 呼噜阈值由 `snore_detect.cpp` 中 `kSnoreThreshold` 控制。
- 呼噜停止 1.5 秒以上才算停止。
- 呼噜停止后的融合报警不再使用“呼吸波形下降段”作为触发条件，改为雷达呼吸/存在性检测值跌破存在性检测阈值才报警。
- “呼噜停止 + 呼吸/存在性信号跌破阈值”必须先由小智/Edgi 明确上报 `snore_detected=true`，不能只靠噪声分数触发。
- 呼吸暂停报警要求目标距离稳定、呼噜上下文、呼吸周期性上下文，以及 `presence_detection_value < presence_detection_threshold` 共同满足。
- `/status`、`/timeline`、`/debug/radar` 会携带 `presence_detection_value`、`presence_detection_threshold`、`presence_detection_bin`、`presence_below_threshold`，用于排查呼吸暂停误报。
- 呼噜响起以及刚停止确认窗口内，存在性检测会临时绕过，避免冲突。
- 存在性检测加入目标距离稳定约束，有效距离当前按 0.1–1m 维护。

## 7. 前端与 Android

前端目录：`frontend/`。

```powershell
npm run build
```

当前前端生命体征页：

- `frontend/src/views/HeartRateMonitor.vue`：心率卡片带心脏图形和随心率变化的跳动动效。
- `frontend/src/views/BreathRateMonitor.vue`：呼吸率卡片带肺部图形和随呼吸率变化的扩张/收缩动效。
- `frontend/src/views/ward_big_screen.vue`：当床位 `risk_level=critical` 时，大屏会循环播放高音量蜂鸣并使用浏览器 Web Speech API 语音播报床位和异常原因。浏览器可能拦截自动播放，页面提供“启用报警声音”按钮，演示前应点击一次授权声音。

Android 目录：`android_app/`。

已安装的 Android App 可能缓存旧地址，需要在 App 内重新填写 `http://192.168.31.236:8081` 或清除应用数据。

Android App 已移除蓝牙直连雷达板的全部功能（`RadarBleClient.kt` 已删除、`MainActivity` 蓝牙 UI/状态/通知/权限全部清理、Manifest 蓝牙权限与 `connectedDevice` 前台服务类型已删），改为纯后端轮询架构。保留功能：`GuardianMonitorService` 每 5 秒拉 `/sleep/overview` + `/status`，`/status` 的 `target_distance` 现已采集到 `BackendLiveData.targetDistanceMeters` 并在目标距离卡片显示。不要再恢复 `RadarBleClient.kt` 或蓝牙权限，因为雷达板固件 BLE 已默认禁用（见 4.1）。

## 7.1 模拟床位与独立模拟开发板

模拟床位只在后端 `bed_registry` 中注册为 `bed-sim-001 / 模拟01床`，后端不再内置生成模拟生命体征、呼噜、温湿度或紧急事件。

模拟数据必须由独立开发板模拟端上报：

```powershell
python tools\simulated_bed_board.py --backend http://127.0.0.1:8081
```

默认模拟端控制地址：

```text
http://127.0.0.1:8092
```

前端模拟床位详情页的场景按钮会调用模拟端 `/scenario`，模拟端再通过真实接口上报到后端：

- `/hardware/edgi-heartbeat`
- `/hardware/environment-heartbeat`
- `/hardware/snore-heartbeat`
- `/save-vitals-with-user`
- `/emergency`
- `/beds/{bed_id}/emergency/resolve`

如需改模拟端控制地址，可设置前端环境变量 `VITE_SIM_BOARD_BASE_URL`。不要恢复后端 `/demo/bed-sim/*` 这类内置模拟接口。

模拟端注意事项：

- `tools/simulated_bed_board.py` 在非离线状态下会持续上报温度、湿度和背景声级 `dbfs`，环境分析页依赖这些字段完整展示模拟睡眠环境。
- `snore` / `apnea` 场景会把 `dbfs` 提高为呼噜声级；`normal` 场景也应保留较低背景声级，不能改回 `None`。

## 8. 演示前检查

1. 后端 API：`http://192.168.31.236:8081/status`
2. 前端页面能登录并读取状态。
3. 雷达板串口拿到 `192.168.31.xxx`。
4. `/status` 中 `radar_board_online=true`、`radar_online=true`、`total_frames` 持续增长。
5. 小智守护模式/对话模式切换正常。
6. 呼噜、环境、紧急事件接口可用。
7. Android App 显示心率、呼吸率、温湿度和打鼾情况。

## 9. Git 与维护约定

- 搜索优先用 `rg`。
- 不要使用 `git reset --hard` 等破坏性命令。
- 修改文件优先用补丁方式，避免覆盖用户已有改动。
- 雷达固件和小智固件改动后，必须提醒用户重新编译并烧录。
- 后端改动后，必须重启后端进程才会生效。
- 前端改动后，开发服务器可能需要重启或重新构建。

## 10. 最重要提醒

当前网络基准是：雷达板、M55、Android、前端浏览器都指向后端 `192.168.31.236:8081`；雷达 UDP 目标是 `192.168.31.236:9988`；雷达 WiFi 为 `B502`。

## 11. 当前进度与最近排障记录

更新时间：2026-07-04。

- 已将主项目和 `code/` 核心代码副本的网络配置同步到：
  - 后端 HTTP：`192.168.31.236:8081`
  - 雷达 UDP：`192.168.31.236:9988`
  - 雷达 WiFi：`B502` / `b5026666`
- 已确认后端当前正在运行：
  - TCP `0.0.0.0:8081` 正在监听。
  - UDP `0.0.0.0:9988` 正在监听。
  - 本机 `http://127.0.0.1:8081/status` 和局域网 `http://192.168.31.236:8081/status` 均可访问。
- 已确认 Windows 当前 WLAN 网络类型已由用户用管理员 PowerShell 切为 `Private`，并已添加入站规则：
  - `Radar UDP 9988`：UDP `9988`，Inbound Allow，Private/Public。
  - `Radar Backend TCP 8081`：TCP `8081`，Inbound Allow，Private/Public。
- 已用本机假雷达 UDP 包验证后端接收链路：向 `127.0.0.1:9988` 发送 1030 字节合法雷达包后，`/status.total_frames` 从 `0` 增长到 `1`，`radar_debug.packet_len=1030`，`samples_per_frame=512`。这说明后端 UDP 接收、包过滤和状态更新逻辑正常。
- 当前 `/status` 显示前端离线的真实原因不是前端 API 不通，而是后端没有收到真实设备数据：
  - `radar_board_online=false`
  - `edgi_board_online=false`
  - `snore_board_online=false`
  - `environment_board_online=false`
  - 真实雷达数据到达前 `total_frames=0`；本机假包测试可使其增长，不能代表真实雷达已在线。
  - `last_radar_received_at=null`
- 已读取 COM5 串口，看到雷达板日志片段：

```text
Failed to send data to client. Error: 136970259
```

用户随后提供的完整雷达板重启日志显示：

```text
Successfully connected to Wi-Fi network 'B502'.
IP Address Assigned: 192.168.31.180
Socket bound to port: 9988
Command received from udp client {"radar_transmission":"enable"}
Radar data transmission is enabled
```

这说明雷达板已连到正确 WiFi，板端 IP 为 `192.168.31.180`。当前仍离线时，问题重点从“后端/前端问题”转为“真实雷达板数据包没有到达电脑”：

1. 雷达板 enable 后是否真的持续发送数据帧尚需确认；当前成功发送日志 `Data with length:... sent to udp client` 在源码里被注释，串口不一定会打印。
2. 若串口出现 `Failed to send data to client`，说明板端 UDP `sendto` 失败，继续查 AP 隔离、目标 IP/端口和固件是否为最新烧录。
3. 若板端无失败日志但后端仍无帧，建议临时打开雷达固件 `udp_server.c` 中成功发送日志，重新编译烧录，确认 `bytes_sent` 是否持续为 1030 左右。

补充：固件 `radar_wifi/source/udp_server.c` 的 `radar_init()` 会在启动后自己向 `radar_config_queue` 塞入 `{"radar_transmission":"enable"}`，因此串口 `Command received from udp client {"radar_transmission":"enable"}` 不一定代表后端发来的命令；最终是否连通仍以后端 `/status.total_frames` 是否增长、`last_radar_received_at` 是否更新为准。

下一步应优先重启雷达板并完整观察串口启动日志，确认：

1. 是否显示 `Successfully connected to Wi-Fi network 'B502'`。
2. `IP Address Assigned` 是否为 `192.168.31.xxx`。
3. 是否显示 `Data with length:... sent to udp client`，而不是 `Failed to send data to client`。
4. 若仍失败，先检查 Windows 防火墙是否允许 UDP `9988`，以及 B502 路由器是否开启 AP/client isolation。

### 11.1 2026-07-04 BLE 射频冲突排障与修复

现象：雷达板烧录最新固件后 WiFi/IP/socket/enable 全部正常，后端 `/status.total_frames` 仍长期为 0，`radar_online=false`。

关键证据：
- 临时打开 `radar_wifi/source/udp_server.c:201` 的发送成功日志重烧，串口持续打印 `Data with length:1030 sent to udp client`，但仅持续约 140 帧。
- 这 140 帧到达后端（`total_frames` 从 0 跳到 140），但随后不再增长，`radar_age_seconds` 持续变大。
- 串口时序：发完约 140 帧后，恰好在 `Radar BLE: stack enabled`（`BTM_ENABLED_EVT` 回调）打印之后，**再无任何 `sent` 输出**。

根因：BGT60TR13C 雷达传感器与 WICED BLE 协议栈共用 2.4GHz 射频前端。BLE `wiced_bt_stack_init()` 完成并把射频切换到 BLE 时序后，雷达 GPIO 数据中断停止触发，`radar_task` 的 `ulTaskNotifyTake()` 永远等不到通知，FIFO 不再被读取，UDP 发送队列枯竭。板子不报错，`sendto` 也无关——根本没数据可发。前 140 帧是 BLE 协议栈异步初始化完成前雷达独占射频发的。

修复：把 `radar_wifi/Makefile` 和 `code/radar_wifi/Makefile` 的 `ENABLE_RADAR_BLE?=1` 改为 `?=0`，BLE 协议栈不再启动，雷达独占射频，数据流恢复。保留 `?=` 形式便于日后用 `ENABLE_RADAR_BLE=1` 临时构建。

同步：Android App 移除蓝牙直连部分（`RadarBleClient.kt` 删除、`MainActivity` 清理、Manifest 蓝牙权限与 `connectedDevice` 前台服务类型删除、`android_app/README.md` 改为纯后端轮询说明）。App 改为纯后端轮询，目标距离卡片改为从 `/status.target_distance` 采集。

验证：重新编译并烧录雷达固件后，串口不应再出现 `Radar BLE: stack enabled` 等行；`Data with length:1030 sent to udp client` 持续打印且不会在某时刻停掉；后端 `/status.total_frames` 持续增长（约 30 帧/秒），`radar_online` 变 true，`heart_rate` / `breath_rate` 出现有效数值。
