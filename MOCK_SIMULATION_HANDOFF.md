# 无硬件模拟联调与前端分析增强交接说明

本文档用于给后续接手的同学快速了解：本轮在原项目基础上新增了什么能力、修改了哪些文件、如何启动验证、以及当前设计中的关键数据流。

## 1. 本轮改动目标

原项目依赖两块硬件：

1. 毫米波雷达开发板：负责发送雷达数据，后端计算心率、呼吸率、目标距离等。
2. 呼噜检测开发板：负责采集麦克风音频，并向后端上传呼噜相关数据。

由于当前没有真实开发板，本轮新增了完整的“无硬件模拟联调模式”：

- 用 Python 模拟后端 API。
- 用 Python 模拟毫米波雷达开发板持续发送数据。
- 用 Python 模拟呼噜检测开发板持续发送呼噜特征和音频片段。
- 前端可以实时展示心率、呼吸率、呼噜强度、设备在线状态、睡眠分期、呼噜关联分析。
- 历史数据页的 AI 分析改为后端代理 DeepSeek，不再把 API key 写在前端。

## 2. 当前推荐启动方式

需要 4 个终端。

### 终端 1：启动模拟后端

```powershell
cd C:\path\to\radar-monitor-system
& C:\path\to\Anaconda3\shell\condabin\conda-hook.ps1
conda activate radar
python backend\mock_hardware_api.py
```

默认监听：

```text
http://localhost:8081
```

### 终端 2：启动前端

```powershell
cd C:\path\to\radar-monitor-system\frontend
npm run dev
```

浏览器打开：

```text
http://localhost:5173/
```

### 终端 3：启动毫米波雷达模拟板

```powershell
cd C:\path\to\radar-monitor-system
& C:\path\to\Anaconda3\shell\condabin\conda-hook.ps1
conda activate radar
python backend\mock_device_sender.py --radar-board
```

作用：

- 每秒向后端发送心率、呼吸率、目标距离、相位波形。
- 关闭该终端约 5 秒后，前端会显示雷达板离线，心率/呼吸率变为 `--`，图表断线。

可选：同时发送原始 UDP 包：

```powershell
python backend\mock_device_sender.py --radar-board --send-udp
```

### 终端 4：启动呼噜检测模拟板

```powershell
cd C:\path\to\radar-monitor-system
& C:\path\to\Anaconda3\shell\condabin\conda-hook.ps1
conda activate radar
python backend\mock_device_sender.py --snore-board
```

作用：

- 每 1 秒发送一次呼噜特征：`snore_score`、`dbfs`、`snore_detected`。
- 每 10 秒上传一个 10 秒模拟音频片段到后端 `/audio`。
- 关闭该终端约 5 秒后，前端会显示呼噜板离线，呼噜声浪和呼噜强度图断线；但心率/呼吸率仍继续运行，因为它们来自雷达模拟板。

## 3. 主要新增/修改文件

### 3.1 `backend/mock_hardware_api.py`

新增的无硬件模拟后端，基于 FastAPI。

主要职责：

- 监听 `8081`。
- 提供前端兼容接口。
- 接收雷达模拟板数据。
- 接收呼噜检测模拟板特征和音频。
- 用 SQLite 保存用户和历史生命体征。
- 维护共享秒级时间轴。
- 提供 DeepSeek AI 分析代理和本地规则兜底。

关键接口：

```text
GET  /target
GET  /detailed
GET  /heartrate
GET  /status
GET  /timeline?seconds=180
POST /mock/radar-frame
POST /mock/snore-heartbeat
POST /audio
POST /login
POST /register
POST /save-vitals-with-user
GET  /heartdata/selectPage
POST /ai/analyze-vitals
POST /mock/scenario
```

重点说明：

- `/timeline` 是本轮核心接口。它把心率、呼吸率、呼噜强度放到同一秒级时间轴里。
- 雷达板离线后，`heart_rate` 和 `breath_rate` 会变成 `null`，前端图表断线，而不是显示假 `0`。
- 呼噜板离线后，`snore_level` 会变成 `null`，呼噜强度图断线。
- AI 分析接口使用 `asyncio.to_thread(...)` 调用 DeepSeek，避免阻塞 FastAPI 主事件循环，防止模拟板请求超时退出。

`/timeline` 单条数据示例：

```json
{
  "timestamp": "2026-05-19T02:03:13",
  "heart_rate": 74.95,
  "breath_rate": 20.29,
  "target_distance": 0.84,
  "snore_score": 0.895,
  "snore_dbfs": -13.67,
  "snore_level": 0.949,
  "snore_detected": true,
  "radar_online": true,
  "snore_online": true,
  "sleep_stage": "疑似呼噜扰动"
}
```

### 3.2 `backend/mock_device_sender.py`

新增/增强的模拟开发板发送器。

支持模式：

```powershell
python backend\mock_device_sender.py --radar-board
python backend\mock_device_sender.py --snore-board
python backend\mock_device_sender.py --audio
python backend\mock_device_sender.py --radar-udp
python backend\mock_device_sender.py --demo
```

本轮关键增强：

- `--radar-board` 持续发送模拟心率/呼吸率/距离/相位。
- `--snore-board` 每秒发送呼噜特征，每 10 秒上传 10 秒音频片段。
- 心率和呼吸率保留“同一个人的强相关性”，但使用不同频率、相位、恢复速度，避免两条曲线看起来像复制粘贴。
- 网络异常捕获范围扩大到 `TimeoutError`、`HTTPError`、`URLError`、`OSError`、`ConnectionError`，后端短暂卡顿时只打印重试，不退出进程。

### 3.3 `frontend/src/views/heart_pic.vue`

实时生命体征页面。

本轮新增/改动：

- 心率图和呼吸图使用 `/timeline` 同一组 timestamp。
- 新增第三张图：**呼噜强度趋势 (Snore Level)**。
- 新增“呼噜声浪监测”模块：
  - 条状声浪会随着 `snore_level / snore_score / dbfs` 实时变化。
  - 呼噜事件发生时颜色和高度更明显。
- 新增/增强三类分析卡片：
  - 睡眠分期
  - 呼噜-生命体征关联
  - 实时健康摘要
- 页面文案明确说明数据来源：
  - 心率、呼吸率、距离来自毫米波雷达模拟板。
  - 呼噜强度、音频、呼噜事件来自呼噜检测模拟板。

重要行为：

- 关闭呼噜终端：呼噜板离线、呼噜图断线；心率/呼吸率继续。
- 关闭雷达终端：心率/呼吸率变 `--`、图表断线；如果呼噜板仍在线，声浪仍可显示。

### 3.4 `frontend/src/views/data.vue`

历史数据页面。

本轮修改：

- 移除前端硬编码的 SiliconFlow API 地址和 API key。
- “AI分析”按钮改为调用后端：

```text
POST /ai/analyze-vitals
```

- 后端未配置 DeepSeek key 时，页面显示本地规则分析，不再直接报 403。
- DeepSeek 网络不可用时，也会显示本地规则兜底报告。

### 3.5 `backend/.env.example`

新增 DeepSeek 配置示例：

```env
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_API_KEY=请把你的DeepSeek_API_Key填到这里
```

实际使用时复制一份：

```powershell
copy backend\.env.example backend\.env
```

然后在 `backend\.env` 中填入真实 key。

### 3.6 `backend/.gitignore`

新增忽略项：

```text
mock_monitor.db
mock_audio_uploads/
received_audio_*.wav
.env
```

目的：

- 不提交 SQLite 测试数据库。
- 不提交模拟音频上传文件。
- 不提交 DeepSeek API key。

### 3.7 `README.md`

已重写为小白启动教程。

包含：

- 4 终端启动方式。
- 当前无硬件模拟模式说明。
- DeepSeek key 填写位置。
- 三图时间对齐说明。
- 呼噜声浪条预期效果。
- 关闭不同模拟板终端后的预期现象。
- 常见问题。

## 4. 当前核心数据流

### 4.1 雷达数据流

```text
mock_device_sender.py --radar-board
        |
        | POST /mock/radar-frame
        v
mock_hardware_api.py
        |
        | 更新 heart_rate / breath_rate / target_distance / phase_values
        | 写入 timeline
        v
frontend heart_pic.vue
        |
        | GET /timeline
        v
心率图 + 呼吸图 + 监测卡片
```

### 4.2 呼噜数据流

```text
mock_device_sender.py --snore-board
        |
        | 每秒 POST /mock/snore-heartbeat
        | 每10秒 POST /audio
        v
mock_hardware_api.py
        |
        | 更新 snore_score / snore_dbfs / snore_level / snore_detected
        | 写入 timeline
        v
frontend heart_pic.vue
        |
        | GET /timeline + GET /status
        v
声浪条 + 呼噜强度趋势图 + 呼噜事件卡片
```

### 4.3 AI 分析数据流

```text
frontend data.vue
        |
        | POST /ai/analyze-vitals
        v
mock_hardware_api.py
        |
        | 如果 backend/.env 有 DEEPSEEK_API_KEY -> 调 DeepSeek
        | 如果没有 key 或调用失败 -> 本地规则分析
        v
frontend data.vue 展示报告
```

## 5. 设计决策说明

### 5.1 呼吸率到底来自哪个开发板？

当前设定：

```text
呼吸率来自毫米波雷达模拟板。
```

呼噜检测板不产生呼吸率，只产生：

- 呼噜分数
- 音量 dBFS
- 呼噜事件
- 音频片段上传

所以只关闭呼噜模拟板后，呼吸率继续跑是正确行为。

### 5.2 为什么要三路时间对齐？

心率、呼吸率、呼噜强度描述的是同一个人的同一段时间。

虽然它们来自两个模拟开发板，但后端会把它们按秒合并到同一个 `/timeline` 中，前端三张图使用同一批 `timestamp`，这样可以观察：

- 呼噜事件发生时心率是否上升。
- 呼噜事件发生时呼吸率是否变化。
- 雷达/呼噜任一设备离线时，对应曲线是否断线。

### 5.3 为什么心率和呼吸率仍然相关？

因为它们模拟的是同一个人，异常、无人、呼噜扰动等大事件应当同步。

但它们不应该完全一样，所以当前模拟器做了：

- 大事件时间点同步。
- 心率和呼吸率使用不同频率。
- 心率和呼吸率使用不同相位。
- 心率和呼吸率使用不同恢复速度。

## 6. DeepSeek 配置说明

不要把 key 写在前端。

正确做法：

```powershell
copy backend\.env.example backend\.env
```

编辑：

```text
C:\path\to\radar-monitor-system\backend\.env
```

填入：

```env
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_API_KEY=你的DeepSeek_API_Key
```

然后重启后端：

```powershell
python backend\mock_hardware_api.py
```

如果没有配置 key：

- 历史页点击“AI分析”不会报 403。
- 后端会返回本地规则分析。

## 7. 已做过的验证

### 7.1 Python 静态检查

```powershell
python -m py_compile backend\mock_hardware_api.py backend\mock_device_sender.py
```

已通过。

### 7.2 前端构建

```powershell
cd frontend
npm run build
```

已通过。

说明：Vite 会提示 chunk 大于 500 kB，这是体积警告，不是构建失败。

### 7.3 后端联调验证

已验证：

- `/timeline` 同时包含心率、呼吸率、呼噜字段。
- 呼噜板离线后：
  - `snore_online = false`
  - `snore_level = null`
  - 雷达仍在线时 `breath_rate` 继续存在。
- 雷达板离线后：
  - `heart_rate = null`
  - `breath_rate = null`
  - 呼噜板仍在线时 `snore_level` 继续存在。
- AI 分析调用期间：
  - 雷达模拟板进程保持运行。
  - 呼噜模拟板进程保持运行。
  - 不会因为后端 AI 请求阻塞而退出。

## 8. 手动验收建议

### 8.1 验证三图时间对齐

1. 启动后端、前端、雷达模拟板、呼噜模拟板。
2. 打开实时页。
3. 查看三张图：
   - 心率趋势
   - 呼吸趋势
   - 呼噜强度趋势
4. 三张图底部时间标签应一致。

### 8.2 验证呼噜声浪条

1. 保持呼噜模拟板运行。
2. 观察“呼噜声浪监测”。
3. 声浪条应每秒跳动。
4. 呼噜事件发生时，声浪条应更高、更亮。

### 8.3 验证关闭呼噜模拟板

1. 关闭终端 4。
2. 等待约 5 秒。
3. 预期：
   - 呼噜开发板显示离线。
   - 呼噜强度图断线。
   - 心率和呼吸率继续运行。

### 8.4 验证关闭雷达模拟板

1. 关闭终端 3。
2. 等待约 5 秒。
3. 预期：
   - 雷达开发板显示离线。
   - 心率/呼吸率显示 `--`。
   - 心率/呼吸图断线。
   - 如果呼噜模拟板仍在线，声浪条和呼噜强度图继续显示。

### 8.5 验证 AI 分析

1. 保持两个模拟板运行。
2. 去历史数据页。
3. 点击“查询”。
4. 点击“AI分析”。
5. 预期：
   - 页面显示 DeepSeek 或本地规则分析报告。
   - 终端 3 和终端 4 不应退出。

## 9. 注意事项

- 当前是模拟演示模式，不代表真实医学诊断。
- 没有改真实 `backend/realtime_radar_processing.py` 的核心算法。
- 没有改真实开发板 C/C++ 代码的数据协议。
- 当前项目工作区本来存在很多无关删除/未跟踪文件，本轮只围绕无硬件模拟联调和前端展示做了相关改动。
- 如果后续要接真实硬件，建议保留这些模拟接口作为开发/演示/回归测试模式。


