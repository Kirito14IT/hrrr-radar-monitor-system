# 全项目真实数据测试清单

默认电脑后端地址：`192.168.0.102:8081`。开发板、前端和安卓手机都应连接到这个地址。

## 1. 基础启动与构建

- [ ] 真实后端可启动：`python backend\realtime_radar_processing.py`
- [ ] 前端可启动：`cd frontend && npm run dev`
- [ ] 前端可构建：`cd frontend && npm run build`
- [ ] 后端测试通过：`pytest tests`
- [ ] 小智 M55 固件可编译：`cd Edgi_Talk_M55_XiaoZhi && scons -Q -j8`
- [ ] 雷达板固件可编译：`cd radar_wifi && make build`
- [ ] 安卓 App 可用 Android Studio 打开并构建 APK
- [ ] 电脑防火墙允许局域网访问 `8081` 端口

## 2. 后端接口与真实数据闭环

- [ ] `GET /status` 返回后端状态
- [ ] `GET /sleep/overview?mode=live&seconds=1800` 返回驾驶舱数据
- [ ] `GET /timeline` 返回心率、呼吸率、呼噜和环境趋势
- [ ] `POST /hardware/snore-session/start` 可标记呼噜守护开始
- [ ] `POST /hardware/snore-heartbeat` 可更新呼噜分数、分贝和检测状态
- [ ] `POST /hardware/snore-session/stop` 可标记呼噜守护暂停
- [ ] `POST /hardware/environment-heartbeat` 可更新温度、湿度和环境板在线状态
- [ ] `POST /emergency` 可创建 `critical` 紧急事件
- [ ] `POST /emergency/resolve` 可解除紧急事件
- [ ] `/sleep/overview` 中能看到 `events`、`devices`、`environment`、`active_emergency`
- [ ] 雷达低呼吸 + 呼噜证据时可生成 `suspected_apnea`
- [ ] 人不在床、雷达离线或雷达未静止时不生成疑似呼吸暂停事件

## 3. 前端页面

- [ ] `/login` 登录页可进入系统
- [ ] `/manage/project_intro` 首页简洁，无小字堆叠
- [ ] `/manage/sleep_dashboard` 显示实时生命体征、事件流和设备状态
- [ ] `/manage/alert_center` 显示最高风险事件、趋势图和处理动作
- [ ] `/manage/environment_analysis` 显示温度、湿度、分贝、评分、建议和温湿度折线图
- [ ] `/manage/heart_pic` 显示心率趋势和当前值
- [ ] `/manage/breath_pic` 显示呼吸率趋势和当前值
- [ ] `/manage/data` 可分页查看历史记录
- [ ] 所有页面刷新后仍能从真实后端恢复状态
- [ ] 紧急事件出现时前端置顶红色告警
- [ ] 点击前端紧急处理/解除按钮后，后端 active emergency 消失

## 4. Edgi Talk M55

- [ ] `backend_cfg_status` 显示目标为 `192.168.0.102:8081`
- [ ] 如有旧 IP，执行 `backend_cfg_set 192.168.0.102 8081`
- [ ] Wi-Fi 配置可保存，重启后自动连接
- [ ] `/flash` 可写，`flash_test` 连续写读删通过
- [ ] 屏幕主页显示正常，中文按钮不乱码
- [ ] 左侧按钮连续快速点击不会锁死
- [ ] 上电默认显示“守护模式”，呼噜检测启动；联网后显示“关键词在线”
- [ ] 守护模式下普通谈话不会播放或显示大模型回复
- [ ] 守护模式下说“救命 / 需要帮助 / 喘不过气 / 胸口痛 / 摔倒了”触发 SOS、本地报警和 `/emergency`
- [ ] 连续 STT 分片命中同一求助词时，8 秒冷却内不会重复上报
- [ ] SOS 页面显示触发原因和“解除紧急状态”按钮
- [ ] 点击开发板 SOS 解除后，报警停止、返回主页、前端同步解除
- [ ] `imu_fall_status` 能看到 IMU 状态
- [ ] `imu_fall_test` 触发“设备跌落”SOS
- [ ] IMU 触发后也播放报警声并出现 SOS 解除按钮
- [ ] 点击“对话模式”后呼噜会话停止，并立即进入“聆听中”收到 STT 和 TTS
- [ ] 对话模式下求助词不触发守护告警，多轮对话正常
- [ ] 点击“守护模式”或在对话中说“打开打鼾检测”后，对话/TTS 停止且守护恢复
- [ ] 守护模式断网时呼噜推理继续、关键词显示离线；重连后 `always_on` 监听恢复
- [ ] 守护模式下按顶部用户键可快速切到对话模式
- [ ] 呼噜检测命中时后端收到 `/hardware/snore-heartbeat`
- [ ] 环境监测能通过 `/hardware/environment-heartbeat` 上报温湿度
- [ ] 闹钟到点后出现响铃界面，点击关闭后停止并返回主页
- [ ] 连续运行 2 小时无内存耗尽、线程断言或麦克风抢占错误

## 5. 雷达板

- [ ] 雷达板连接 Wi-Fi 成功，串口打印 IP
- [ ] 后端发送 `{"radar_transmission":"enable"}` 后雷达开始传输
- [ ] UDP 数据持续发送到真实后端
- [ ] 心率、呼吸率、距离在后端和前端更新
- [ ] 人离开床后目标距离归零或标记无人
- [ ] 雷达离线超过超时时间后前端显示离线
- [ ] 雷达状态通过 LED 指示清楚

## 6. 安卓监护人 App

- [ ] APK 可安装到安卓手机
- [ ] 首次打开可填写 `http://192.168.0.102:8081`
- [ ] 点击开始监听后显示“监听中”
- [ ] 后端离线时 App 显示离线但不崩溃
- [ ] 触发“小智救命”后 5 秒内收到手机通知
- [ ] 触发 IMU 跌落后 5 秒内收到手机通知
- [ ] 触发疑似呼吸暂停后收到手机通知
- [ ] 同一个事件不会反复弹重复通知
- [ ] 点击 App 内“已处理”后调用 `/emergency/resolve`

## 7. 关键联动

- [ ] M55 说“救命” -> 开发板 SOS -> 后端事件 -> 前端告警 -> 安卓通知 -> 解除后同步消失
- [ ] M55 被打翻 -> IMU SOS -> 后端事件 -> 前端告警 -> 安卓通知 -> App 处理
- [ ] 呼噜增强 + 雷达呼吸低于阈值约 10 秒 -> 后端生成疑似呼吸暂停 -> 前端和 App 告警
- [ ] 呼噜单独出现时，只显示呼噜风险，不生成呼吸暂停
- [ ] 雷达单点呼吸异常时，不生成呼吸暂停
- [ ] 后端重启后，前端和 App 能恢复连接
- [ ] 开发板断电重启后，Wi-Fi、后端 IP 和闹钟配置仍保留
