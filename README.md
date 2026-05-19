# 雷达生命体征监测系统：无开发板持续模拟联调版

这个项目现在可以在**没有毫米波雷达开发板、没有呼噜检测开发板**的情况下跑通完整演示。

模拟模式包含两块“虚拟开发板”：

1. **毫米波雷达模拟板**：持续发送心率、呼吸率、目标距离、相位波形。
2. **呼噜检测模拟板**：每秒发送呼噜特征，并每 10 秒上传一个 10 秒音频片段。

关闭某个模拟板终端，就等于把对应开发板关掉；前端大约 5 秒后会显示离线。

---

## 1. 预期效果

启动成功后，前端页面会显示：

- 雷达开发板在线/离线状态。
- 呼噜开发板在线/离线状态。
- 心率、呼吸率、呼噜强度三张曲线，使用同一条真实时间横坐标。
- 呼噜声浪条：会随着呼噜分数和音量 dBFS 实时变高变低。
- 雷达离线或无人时，曲线断开并显示 `--`，不会再用 `0` 假装真实数据。
- 睡眠分期：清醒/浅睡/深睡/疑似呼噜扰动。
- 呼噜-生命体征关联：观察呼噜事件前后心率、呼吸率变化。
- 实时健康摘要。
- 新增“睡眠看护驾驶舱”：深色夜间大屏，展示睡眠质量评分、呼噜扰动地图、夜间守护事件流。
- 历史数据页可点击“AI分析”；如果没有 DeepSeek key，会自动显示本地规则分析。

数据来源说明：

- **心率、呼吸率、距离**来自毫米波雷达模拟板。
- **呼噜分数、音量 dBFS、声浪条、呼噜事件、音频次数**来自呼噜检测模拟板。
- 所以只关闭呼噜模拟板时，呼吸监测继续运行是正常的。

---

## 2. Conda 环境

在 PowerShell 中进入项目根目录：

```powershell
cd C:\path\to\radar-monitor-system
```

激活你的 conda 环境：

```powershell
& C:\path\to\Anaconda3\shell\condabin\conda-hook.ps1
conda activate radar
```

看到前面出现 `(radar)` 就说明成功：

```text
(radar) PS C:\path\to\radar-monitor-system>
```

如果后端缺依赖：

```powershell
pip install -r backend\requirements.txt
```

如果前端缺依赖：

```powershell
cd frontend
npm install
cd ..
```

---

## 3. 推荐启动方式：4 个终端

### 终端 1：启动模拟后端

```powershell
cd C:\path\to\radar-monitor-system
& C:\path\to\Anaconda3\shell\condabin\conda-hook.ps1
conda activate radar
python backend\mock_hardware_api.py
```

正常输出类似：

```text
无硬件模拟后端已启动
本机访问: http://localhost:8081
局域网访问: http://你的当前IP:8081
```

这个窗口不要关。它负责：

- 给前端提供 API。
- 保存历史生命体征。
- 接收雷达模拟数据。
- 接收呼噜音频。
- 代理 DeepSeek AI 分析。

### 终端 2：启动前端

```powershell
cd C:\path\to\radar-monitor-system\frontend
npm run dev
```

正常输出类似：

```text
Local:   http://localhost:5173/
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

它会每秒向后端发送一帧模拟生命体征：

```text
[radar-board] frame=12 status=ok hr=71.8 br=19.7 dist=0.85m
```

关闭这个终端后，前端会显示：

- 雷达开发板离线。
- 心率和呼吸率变为 `--`。
- 心率/呼吸图表出现断线。

如果你还想同时发送原始 UDP 包：

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

默认行为：

- 每 1 秒发送一次呼噜特征：呼噜分数、音量、是否检测到呼噜。
- 每 10 秒上传一个 10 秒音频片段。

终端输出类似：

```text
[snore-board] heartbeat score=0.23 snore=False dbfs=-33.6
[audio] POST http://127.0.0.1:8081/audio bytes=640000 seconds=10.0
```

关闭这个终端后，前端会显示：

- 呼噜开发板离线。
- 音频上传次数不再增加。
- 心率和呼吸率仍然继续运行，因为它们来自雷达模拟板。

---

## 4. 注册、登录和查看页面

1. 打开 `http://localhost:5173/`。
2. 注册一个账号。
3. 登录。
4. 进入“生命体征监测”。

页面会自动开始刷新。按钮显示“停止监测”时，说明正在实时监测。

正常情况下你会看到：

- `雷达开发板：在线`
- `呼噜开发板：在线`
- 心率和呼吸率每秒/每两秒刷新。
- 横坐标显示真实时间，例如 `01:23:45`。
- “呼噜声浪监测”的条状声浪会随着呼噜强度跳动。
- 心率、呼吸率、呼噜强度三张图的横坐标时间完全一致。
- 睡眠分期和实时健康摘要会随数据变化。

### 睡眠看护驾驶舱

左侧菜单点击“睡眠看护驾驶舱”，可以看到一个独立的深色夜间大屏：

- `Sleep Quality Score`：0-100 分睡眠质量评分。
- 呼噜扰动地图：按分钟显示呼噜强度热力条，颜色越偏橙红表示扰动越强。
- 夜间守护事件流：记录呼噜事件、疑似离床、心率/呼吸异常、设备离线和恢复正常。
- 底部稳定性卡片：心率稳定性、呼吸稳定性、呼噜安静度。
- 页面支持“实时看护 / 历史回放”切换；历史事件会保存到后端 SQLite 的 `sleep_events` 表。

---

## 5. DeepSeek AI 分析配置

历史数据页的“AI分析”现在不再把 API key 写在前端，而是由后端代理调用 DeepSeek。

复制示例配置：

```powershell
copy backend\.env.example backend\.env
```

打开：

```text
C:\path\to\radar-monitor-system\backend\.env
```

填写你的 key：

```env
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_API_KEY=你的DeepSeek_API_Key
```

然后重启终端 1 的模拟后端。

说明：

- `backend\.env` 已经加入 `.gitignore`，不会提交。
- 如果不填 key，点击“AI分析”也不会报 403，会显示本地规则分析。
- 如果 DeepSeek 网络不可达，也会自动退回本地规则分析。
- 点击“AI分析”不会让两个模拟开发板终端退出；如果后端暂时忙，模拟板会打印重试提示并继续运行。

---

## 6. 可选命令

只上传一次 10 秒呼噜音频：

```powershell
python backend\mock_device_sender.py --audio
```

只发送一段雷达 UDP 原始包：

```powershell
python backend\mock_device_sender.py --radar-udp
```

一键演示 30 秒：

```powershell
python backend\mock_device_sender.py --demo
```

---

## 7. 手动验证清单

### 验证雷达模拟板

1. 启动终端 1、2、3。
2. 前端应显示雷达在线。
3. 心率和呼吸曲线应出现真实时间横坐标。
4. 关闭终端 3。
5. 等待约 5 秒，前端应显示雷达离线，心率/呼吸变 `--`。

### 验证呼噜模拟板

1. 启动终端 4。
2. 前端应显示呼噜板在线。
3. “呼噜声浪监测”的条状声浪应每秒跳动。
4. “呼噜强度趋势”应和心率/呼吸图显示相同的时间横坐标。
5. 等待约 10 秒，音频次数增加。
6. 关闭终端 4。
7. 等待约 5 秒，呼噜板离线，呼噜强度图断线，但心率/呼吸继续运行。

### 验证历史页和 AI

1. 登录后保持雷达板运行 30 秒以上。
2. 点击左侧“历史数据”。
3. 点击“查询”。
4. 表格应出现数据。
5. 点击“AI分析”。
6. 未配置 key 时显示本地规则报告；配置 key 并重启后端后，显示 DeepSeek 报告。
7. 点击 AI 分析期间，终端 3 和终端 4 不应退出；最多只会短暂打印网络重试提示。

---

## 8. 常见问题

### 前端显示离线

确认终端 1、3、4 都还在运行。

### 心率/呼吸是 `--`

说明雷达模拟板没运行、离线，或当前模拟场景是无人状态。

### 关闭呼噜终端后呼吸还在跑，是不是 bug？

不是。呼吸率来自毫米波雷达模拟板，呼噜板只负责呼噜特征和音频。

### 为什么要三张图共享时间轴？

因为这三类数据都描述同一个人的同一段时间。心率和呼吸率来自雷达，呼噜强度来自呼噜检测板，但后端会把它们按秒放进同一个时间轴，前端用同一批 timestamp 画三张图。这样你可以看出某个呼噜事件发生时，心率和呼吸率是否同步变化。

### 为什么心率和呼吸率不是完全一样的形状？

它们应该强相关，但不应该是复制粘贴。模拟器会让异常、无人、呼噜扰动这些大事件在同一时间发生，但心率和呼吸率使用不同频率、相位和恢复速度，所以视觉形状会有差异。

### AI 分析显示本地规则

通常是因为没有填写 `backend\.env`，或 DeepSeek key/网络不可用。先按第 5 节配置并重启后端。

### 本机 IP 变了怎么办？

本机浏览器访问仍然用：

```text
http://localhost:5173/
```

如果另一台电脑访问你的后端，需要把前端环境变量改成新 IP，例如：

```powershell
$env:VITE_API_BASE_URL="http://你的新IP:8081"
npm run dev
```

