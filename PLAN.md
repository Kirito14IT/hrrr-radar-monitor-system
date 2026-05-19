# 无硬件模拟联调实施计划（使用 conda 环境 `radar`）

## Summary

在当前项目内实现“无开发板演示模式”：用模拟后端和模拟设备发送器跑通雷达数据、呼噜音频 HTTP 上传、前端实时展示和历史数据保存。所有 Python 命令默认在 conda 环境 `radar` 下运行。

## Key Changes

- 新增 `backend/mock_hardware_api.py`

  - FastAPI 服务监听 `8081`。
  - 兼容前端接口：`/target`、`/detailed`、`/heartrate`、`/status`、`/login`、`/register`、`/save-vitals-with-user`、`/heartdata/selectPage`、`/audio`。
  - 用 SQLite 自动保存用户和历史生命体征，避免配置 MySQL。
  - 模拟心率、呼吸率、目标距离、相位波形、无人状态、异常状态、呼噜音频接收状态。
- 新增 `backend/mock_device_sender.py`

  - 模拟毫米波雷达 UDP 数据包：发送到 `localhost:9988`，包格式对齐 `radar_wifi/source/radar_task.c`。
  - 模拟呼噜检测板 HTTP 上传音频：向 `http://localhost:8081/audio` 发送 10 秒 PCM/WAV 数据。
  - 支持一键 demo 模式，用于前端展示动态变化。
- 前端修复

  - 统一 API 基址为 `http://localhost:8081`，支持 `.env` 中 `VITE_API_BASE_URL` 覆盖。
  - 修复 `request.js` 当前默认 `8000` 与页面硬编码 `8081` 不一致。
  - 修复呼吸波形页面从错误接口读取 `phase_values` 的问题。
  - 增加简洁设备状态展示：雷达模拟在线、最近音频上传、最近呼噜事件。
- 重写 `README.md`

  - 中文小白启动教程。
  - 明确 conda 启动方式：
    ```powershell
    E:\Users\wzh26\Anaconda3\shell\condabin\conda-hook.ps1
    conda activate radar
    ```
  - 说明启动顺序、预期效果、端口、IP 改变时怎么处理、常见报错。

## Test Plan

- Python 静态检查：

  ```powershell
  conda activate radar
  python -m py_compile backend\mock_hardware_api.py backend\mock_device_sender.py
  ```
- 后端 API 验证：

  ```powershell
  python backend\mock_hardware_api.py
  ```

  检查：

  - `http://localhost:8081/status`
  - `http://localhost:8081/target`
  - `http://localhost:8081/detailed`
- 模拟设备验证：

  ```powershell
  python backend\mock_device_sender.py --audio
  python backend\mock_device_sender.py --demo
  ```
- 前端验证：

  ```powershell
  cd frontend
  npm run build
  npm run dev
  ```

  浏览器打开 Vite 地址，注册/登录后点击“开始实时监测”，确认心率、呼吸、距离、波形和音频上传状态正常变化。

## Assumptions

- 默认先做“可演示、可测试、无硬件可跑通”的模拟模式。
- 不破坏真实 `backend/realtime_radar_processing.py`，只保证模拟接口与它的前端 API 兼容。
- 当前工作区已有大量未跟踪/删除状态，实施时只改本任务相关文件，不回滚无关文件。




# 无硬件持续模拟与分析增强计划

## Summary

将当前演示模式升级为“真实双开发板持续联调体验”：雷达板持续产生心率/呼吸/距离，呼噜板持续产生呼噜特征并分块上传音频；前端使用共享真实时间轴对齐心率和呼吸率，离线时断线而不是显示 0；历史页 AI 分析改为后端代理 DeepSeek，并新增睡眠分期、呼噜关联、健康报告 3 个演示功能。

## Key Changes

- **时间对齐与数据来源**

  - 后端维护一个共享时间轴缓冲区，按 1 秒时间桶保存：`timestamp`、`heart_rate`、`breath_rate`、`target_distance`、`snore_score`、`snore_detected`、`radar_online`、`snore_online`、`sleep_stage`。
  - 新增/调整实时接口：`GET /timeline?seconds=180`，前端心率和呼吸图都从同一批 timestamp 渲染。
  - 雷达终端关闭后，心率/呼吸变为 `null` 并断线；呼噜终端关闭后，只影响呼噜状态，不影响雷达呼吸率。
  - 页面明确标注：心率/呼吸/距离来自毫米波雷达模拟板；呼噜分数/音频来自呼噜检测模拟板。
- **呼噜板持续发送模型**

  - `--snore-board` 默认每 1 秒发送一次轻量特征：呼噜分数、音量 dBFS、是否检测到呼噜。
  - 默认每 10 秒上传一个 10 秒音频片段，模拟“持续采集、分块上报”。
  - 关闭呼噜板终端后，约 5 秒内前端显示呼噜板离线，音频次数停止增加。
- **前端功能增强**

  - 实时页图表改为显示真实时间横坐标，心率/呼吸率严格按同一时间轴对齐。
  - 新增 3 个卡片/面板：
    1. 睡眠分期：清醒/浅睡/深睡/疑似呼噜扰动，基于心率、呼吸率、目标存在、呼噜分数的启发式规则。
    2. 呼噜-生命体征关联：展示最近呼噜事件前后心率/呼吸率变化。
    3. 实时健康摘要：本地规则生成状态解释；历史页 AI 可用时调用 DeepSeek 生成报告。
  - 图表离线/无人时显示断点和状态文案，不再用 0 伪装成真实生理数据。
- **DeepSeek AI 分析**

  - 移除前端硬编码 SiliconFlow 地址和 API key。
  - 后端新增 `POST /ai/analyze-vitals`，使用 OpenAI-compatible DeepSeek API：
    - `DEEPSEEK_BASE_URL=https://api.deepseek.com`
    - `DEEPSEEK_MODEL=deepseek-v4-flash`
    - `DEEPSEEK_API_KEY=你自己的key`
  - 新增 `backend\.env.example`；用户实际填写 `backend\.env`，并加入 `.gitignore`，避免 key 提交或暴露到浏览器。
  - 如果未配置 key 或网络调用失败，前端显示本地规则分析报告，不再直接报 403。

## Test Plan

- Python 静态检查：

  ```powershell
  python -m py_compile backend\mock_hardware_api.py backend\mock_device_sender.py
  ```
- 后端接口验证：

  - 启动后端临时端口。
  - 启动 `--radar-board --run-seconds 5`，确认 `/timeline` 有心率、呼吸率、共同 timestamp。
  - 启动 `--snore-board --run-seconds 12`，确认呼噜分数每秒更新，音频上传约 10 秒一次。
  - 停止呼噜板，确认呼噜离线但雷达呼吸率继续。
  - 停止雷达板，确认心率/呼吸断线而不是继续显示 0。
- 前端验证：

  ```powershell
  cd frontend
  npm run build
  ```

  - 打开实时页，确认横坐标显示时间。
  - 确认两张图同一时间点对齐。
  - 确认睡眠分期、呼噜关联、实时摘要随数据变化。
- AI 验证：

  - 未填写 `backend\.env` 时，历史页 AI 分析显示本地报告。
  - 填写 `DEEPSEEK_API_KEY` 后，历史页 AI 分析调用 DeepSeek，失败时显示清晰错误和本地兜底。
- README 验证：

  - 按 README 的 4 终端步骤启动。
  - 按 README 的“关闭某个模拟板终端”步骤观察离线效果。
  - 按 README 说明填写 DeepSeek key。

## Assumptions

- 采用你选择的默认方案：呼噜板“每秒特征 + 每 10 秒 10 秒音频片段”，心率/呼吸使用共享真实时间轴，新增三项功能全部实现。
- 心率和呼吸率均来自毫米波雷达模拟板；呼噜检测板不产生呼吸率，只产生呼噜相关数据。
- AI key 只放在 `backend\.env`，不放前端、不写入 README 明文、不提交到 Git。
- 本次仍只完善无硬件模拟联调模式，不改真实硬件处理脚本的核心算法。
