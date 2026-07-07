# Edgi Talk M55 IMU 摇晃 SOS 真实环境运行与测试

本文用于验证：Edgi Talk M55 检测到低重力、撞击或被打翻时，会进入 SOS 紧急状态，播放报警声，屏幕显示解除按钮，并同步上报真实后端。

## 1. 电脑端准备

1. 确认电脑和开发板在同一 Wi-Fi 下，电脑 IPv4 为 `192.168.0.101`。
2. 启动真实后端：

   ```powershell
   cd D:\STUDY\hrrr-radar-monitor-system
   python backend\realtime_radar_processing.py
   ```

3. 启动前端：

   ```powershell
   cd D:\STUDY\hrrr-radar-monitor-system\frontend
   npm run dev
   ```

4. 打开睡眠驾驶舱或看护预警中心，确认后端可访问。

## 2. 开发板准备

1. 编译并烧录 `Edgi_Talk_M55_XiaoZhi` 最新固件。
2. 串口进入 `msh` 后配置后端：

   ```text
   backend_cfg_set 192.168.0.101 8081
   backend_cfg_status
   ```

3. 确认 Wi-Fi 正常连接。
4. 确认 IMU 监测状态：

   ```text
   imu_fall_status
   ```

## 3. 快速命令测试

先用命令触发，不需要真的摔板子：

```text
imu_fall_test
```

预期现象：

- 串口出现 `emergency event triggered: source=xiaozhi_imu_board`。
- 开发板屏幕进入 SOS 界面，显示“设备摇晃”或对应紧急原因。
- 开发板播放紧急报警声。
- 屏幕出现“解除紧急状态”按钮。
- 后端 `/sleep/overview` 的 `events` 中出现 `emergency_voice`、`critical` 事件，`source` 为 `xiaozhi_imu_board`。
- 前端预警中心显示紧急事件。

点击开发板屏幕上的“解除紧急状态”按钮后：

- 本地报警停止。
- 屏幕返回主页。
- 开发板向 `/emergency/resolve` 上报处理结果。
- 前端 active emergency 消失或变为已处理。

## 4. 真实动作测试

为避免损坏硬件，不要从高处摔板子。推荐：

1. 用手托住板子，快速做短促下落再接住，模拟低重力。
2. 或将板子从很低高度放倒到软垫上，模拟被打翻。
3. 每次触发后等待至少 60 秒，让 IMU 摇晃检测重新 armed。

触发成功后的现象应与 `imu_fall_test` 一致。

## 5. 相关真实接口

M55 当前真实数据上报路径：

- 呼噜开始：`POST /hardware/snore-session/start`
- 呼噜心跳：`POST /hardware/snore-heartbeat`
- 呼噜暂停：`POST /hardware/snore-session/stop`
- 温湿度心跳：`POST /hardware/environment-heartbeat`
- 紧急事件：`POST /emergency`
- 解除紧急：`POST /emergency/resolve`

旧的模拟上报路径已不作为正式接口使用；如果固件仍访问模拟路径，需要重新烧录最新固件。
