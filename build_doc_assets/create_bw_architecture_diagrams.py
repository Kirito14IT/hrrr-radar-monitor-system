from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


BASE = Path(r"D:\STUDY\hrrr-radar-monitor-system")
OUT = BASE / "build_doc_assets"

FONT_REGULAR = Path(r"C:\Windows\Fonts\msyh.ttc")
FONT_BOLD = Path(r"C:\Windows\Fonts\msyhbd.ttc")


def font(size, bold=False):
    path = FONT_BOLD if bold and FONT_BOLD.exists() else FONT_REGULAR
    return ImageFont.truetype(str(path), size)


def dashed_rect(draw, box, width=4, dash=14, gap=9, radius=0):
    x1, y1, x2, y2 = box
    if radius:
        draw.rounded_rectangle(box, radius=radius, outline="black", width=width)
        return
    for x in range(x1, x2, dash + gap):
        draw.line((x, y1, min(x + dash, x2), y1), fill="black", width=width)
        draw.line((x, y2, min(x + dash, x2), y2), fill="black", width=width)
    for y in range(y1, y2, dash + gap):
        draw.line((x1, y, x1, min(y + dash, y2)), fill="black", width=width)
        draw.line((x2, y, x2, min(y + dash, y2)), fill="black", width=width)


def text_box(draw, box, lines, title=None, title_size=38, body_size=31, width=4, radius=18):
    draw.rounded_rectangle(box, radius=radius, fill="white", outline="black", width=width)
    x1, y1, x2, y2 = box
    if title:
        title_font = font(title_size, True)
        body_font = font(body_size)
        title_bbox = draw.textbbox((0, 0), title, font=title_font)
        title_h = title_bbox[3] - title_bbox[1]
        body_items = lines if isinstance(lines, (list, tuple)) else [lines]
        body_heights = [draw.textbbox((0, 0), item, font=body_font)[3] for item in body_items]
        gap = 13
        total_h = title_h + gap + sum(body_heights) + gap * max(0, len(body_items) - 1)
        y = y1 + (y2 - y1 - total_h) / 2
        draw.text(((x1 + x2) / 2, y), title, font=title_font, fill="black", anchor="ma")
        y += title_h + gap
        for item in body_items:
            draw.text(((x1 + x2) / 2, y), item, font=body_font, fill="black", anchor="ma")
            y += draw.textbbox((0, 0), item, font=body_font)[3] + gap
    else:
        items = lines if isinstance(lines, (list, tuple)) else [lines]
        body_font = font(body_size)
        heights = [draw.textbbox((0, 0), item, font=body_font)[3] for item in items]
        gap = 12
        total_h = sum(heights) + gap * max(0, len(items) - 1)
        y = y1 + (y2 - y1 - total_h) / 2
        for item in items:
            draw.text(((x1 + x2) / 2, y), item, font=body_font, fill="black", anchor="ma")
            y += draw.textbbox((0, 0), item, font=body_font)[3] + gap


def line_label(draw, pos, text, size=27, anchor="mm"):
    fnt = font(size)
    bbox = draw.textbbox(pos, text, font=fnt, anchor=anchor)
    pad = 7
    draw.rectangle((bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad), fill="white")
    draw.text(pos, text, font=fnt, fill="black", anchor=anchor)


def arrow(draw, points, width=5, head=18, label=None, label_pos=None, both=False, label_size=27):
    draw.line(points, fill="black", width=width, joint="curve")

    def add_head(start, end):
        import math

        x1, y1 = start
        x2, y2 = end
        angle = math.atan2(y2 - y1, x2 - x1)
        left = (
            x2 - head * math.cos(angle - math.pi / 6),
            y2 - head * math.sin(angle - math.pi / 6),
        )
        right = (
            x2 - head * math.cos(angle + math.pi / 6),
            y2 - head * math.sin(angle + math.pi / 6),
        )
        draw.polygon((end, left, right), fill="black")

    add_head(points[-2], points[-1])
    if both:
        add_head(points[1], points[0])
    if label:
        line_label(draw, label_pos or points[len(points) // 2], label, size=label_size)


def group_title(draw, x, y, text, size=42):
    draw.text((x, y), text, font=font(size, True), fill="black", anchor="la")


def canvas(title, width=2600, height=1750):
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.text((width // 2, 38), title, font=font(58, True), fill="black", anchor="ma")
    return image, draw


def create_hardware_diagram():
    image, d = canvas("多模态非接触式睡眠监测系统硬件连接总框图")

    edgi = (60, 145, 1290, 1080)
    radar = (1350, 145, 2540, 1080)
    dashed_rect(d, edgi, width=4, dash=16, gap=10)
    dashed_rect(d, radar, width=4, dash=16, gap=10)
    group_title(d, 90, 165, "设备一：Edgi Talk / PSoC Edge E84")
    group_title(d, 1380, 165, "设备二：毫米波雷达板 / CY8CKIT-062S2-AI")

    # Edgi Talk hardware resources.
    mic = (100, 300, 390, 420)
    imu = (100, 485, 390, 615)
    aht = (100, 735, 390, 865)
    display = (100, 905, 390, 1030)
    m55 = (505, 275, 835, 535)
    m33 = (505, 700, 835, 880)
    shared = (900, 665, 1195, 815)
    wifi = (900, 285, 1195, 455)
    speaker = (900, 885, 1195, 1015)

    text_box(d, mic, ["双通道 PDM 麦克风", "16 kHz PCM"], body_size=31)
    text_box(d, imu, ["LSM6DS3 系列 IMU", "地址 0x6A / 0x6B"], body_size=30)
    text_box(d, aht, ["AHT20 温湿度", "3.3 V"], body_size=31)
    text_box(d, display, ["MIPI-DSI LCD", "电容触摸屏"], body_size=30)
    text_box(d, m55, ["Cortex-M55 + NPU/DSP", "RT-Thread", "语音 / 呼噜 / SOS / UI"], title="主处理核", title_size=37, body_size=29)
    text_box(d, m33, ["RT-Thread", "AHT20 采样任务"], title="Cortex-M33", title_size=36, body_size=30)
    text_box(d, shared, ["温度 / 湿度 / 状态", "序号与时间戳"], title="共享内存", title_size=35, body_size=27)
    text_box(d, wifi, ["802.11 WLAN", "HTTP / WebSocket"], title="AIROC Wi-Fi", title_size=35, body_size=28)
    text_box(d, speaker, ["sound0", "TTS / 报警 / 闹钟"], title="扬声器", title_size=34, body_size=27)

    arrow(d, [(390, 360), (505, 360)], label="PDM", label_pos=(447, 330), label_size=25)
    arrow(d, [(390, 550), (455, 550), (455, 470), (505, 470)], label="I2C0/1", label_pos=(447, 515), label_size=24)
    arrow(d, [(390, 800), (505, 800)], label="I2C1", label_pos=(447, 770), label_size=24)
    arrow(d, [(835, 790), (900, 740)], label="共享 RAM", label_pos=(870, 710), label_size=23)
    arrow(d, [(900, 690), (865, 690), (865, 515), (835, 515)], label="核间数据", label_pos=(865, 610), label_size=23)
    arrow(d, [(505, 490), (445, 490), (445, 970), (390, 970)], label="MIPI-DSI / Touch", label_pos=(445, 910), label_size=23)
    arrow(d, [(835, 375), (900, 375)])
    arrow(d, [(835, 500), (875, 500), (875, 950), (900, 950)], label="音频设备", label_pos=(875, 855), label_size=23)

    # Radar board hardware resources.
    bgt = (1390, 300, 1690, 455)
    bmi = (1390, 565, 1690, 710)
    psoc6 = (1810, 300, 2150, 600)
    rwifi = (2240, 300, 2500, 470)
    led = (2240, 630, 2500, 760)
    text_box(d, bgt, ["BGT60TR13C", "58.5–63 GHz", "1TX / 1RX"], title="毫米波雷达", title_size=34, body_size=28)
    text_box(d, bmi, ["BMI270", "0x68 / 0x69"], title="板载 IMU", title_size=34, body_size=29)
    text_box(d, psoc6, ["FreeRTOS", "雷达帧采集", "传输与状态控制"], title="PSoC 6", title_size=38, body_size=30)
    text_box(d, rwifi, ["802.11 WLAN", "BLE GATT（可选）"], title="AIROC Wi-Fi / BLE", title_size=31, body_size=27)
    text_box(d, led, ["发送 / 暂停 / 空闲"], title="用户 LED", title_size=33, body_size=28)
    arrow(d, [(1690, 375), (1810, 375)], label="SPI 25 MHz + IRQ", label_pos=(1750, 330), label_size=23)
    arrow(d, [(1690, 635), (1760, 635), (1760, 520), (1810, 520)], label="I2C", label_pos=(1750, 600), label_size=23)
    arrow(d, [(2150, 390), (2240, 390)])
    arrow(d, [(2150, 540), (2200, 540), (2200, 695), (2240, 695)], label="GPIO", label_pos=(2205, 605))

    # Backend, cloud, and user terminals.
    cloud = (90, 1220, 660, 1580)
    backend = (800, 1160, 1760, 1620)
    terminals = (1900, 1160, 2510, 1620)
    text_box(d, cloud, ["WebSocket 网关", "ASR 语音识别", "对话模型 / TTS"], title="小智云端语音服务", title_size=38, body_size=31)
    text_box(d, backend, ["UDP 雷达帧接收与生命体征估计", "HTTP 硬件心跳与 SOS 接收", "雷达+呼噜融合 / 事件与状态 API"], title="边缘计算机：FastAPI 后端", title_size=39, body_size=31)
    text_box(d, terminals, ["Vue Web 驾驶舱", "Android 监护人 App", "展示 / 通知 / 处理解除"], title="用户终端", title_size=40, body_size=31)

    # External links leave from group boundaries so they do not cross internal hardware boxes.
    arrow(d, [(1080, 1080), (1080, 1160)], label="Wi-Fi / HTTP JSON", label_pos=(1080, 1120), label_size=22)
    line_label(d, (760, 1095), "硬件心跳、呼噜、SOS", size=21)
    arrow(d, [(350, 1080), (350, 1220)], both=True, label="Wi-Fi / WebSocket", label_pos=(350, 1125), label_size=22)
    line_label(d, (350, 1170), "Opus、STT、TTS", size=21)
    arrow(d, [(1630, 1080), (1630, 1160)], both=True, label="Wi-Fi / UDP 9988", label_pos=(1630, 1120), label_size=22)
    line_label(d, (1840, 1095), "雷达帧、启停控制", size=21)
    arrow(d, [(1760, 1390), (1900, 1390)], both=True, label="HTTP REST / JSON", label_pos=(1830, 1355), label_size=22)
    arrow(d, [(2300, 1080), (2300, 1160)], both=True, label="BLE GATT（近场可选）", label_pos=(2300, 1120), label_size=21)

    d.text((1300, 1695), "实线箭头表示当前主要数据链路；双向箭头表示控制与状态回传。", font=font(28), fill="black", anchor="mm")
    path = OUT / "diagram_hardware_connections_bw.png"
    image.save(path, dpi=(300, 300), optimize=True)
    return path


def create_software_diagram():
    image, d = canvas("多模态睡眠看护系统端—边—云软件架构")

    end_group = (50, 145, 1240, 1710)
    edge_group = (1280, 145, 2070, 1710)
    cloud_group = (2110, 145, 2550, 1045)
    dashed_rect(d, end_group, width=4, dash=16, gap=10)
    dashed_rect(d, edge_group, width=4, dash=16, gap=10)
    dashed_rect(d, cloud_group, width=4, dash=16, gap=10)
    group_title(d, 80, 165, "端：嵌入式设备与用户终端")
    group_title(d, 1310, 165, "边：本地计算机 / FastAPI")
    group_title(d, 2140, 165, "云：小智语音服务")

    # Endpoint software blocks.
    m33 = (90, 250, 480, 440)
    shared = (560, 250, 920, 440)
    env_reader = (990, 250, 1200, 440)
    text_box(d, m33, ["AHT20 初始化", "2 s 周期采样", "有效性检查"], title="M33 / RT-Thread", title_size=33, body_size=27)
    text_box(d, shared, ["温湿度 / 状态", "序号 / 时间戳"], title="共享内存", title_size=34, body_size=28)
    text_box(d, env_reader, ["读取环境数据", "更新 UI / 上报"], title="M55 环境任务", title_size=28, body_size=25)
    arrow(d, [(480, 345), (560, 345)])
    arrow(d, [(920, 345), (990, 345)])

    m55_tasks = (80, 500, 1210, 1080)
    dashed_rect(d, m55_tasks, width=3, dash=12, gap=8)
    group_title(d, 105, 515, "Edgi Talk M55 / RT-Thread 任务与状态机", size=36)
    audio = (110, 610, 430, 755)
    voice = (470, 610, 790, 755)
    snore = (830, 610, 1170, 755)
    imu = (110, 830, 430, 980)
    ui = (470, 830, 790, 980)
    report = (830, 830, 1170, 980)
    text_box(d, audio, ["唯一打开 mic0", "PCM 环形缓冲分发"], title="共享音频采集中心", title_size=28, body_size=25)
    text_box(d, voice, ["唤醒词 / 用户按键", "Opus 上传 / STT / TTS"], title="小智语音任务", title_size=30, body_size=25)
    text_box(d, snore, ["2 s 滑窗", "INT8 Conv2D 推理", "分数 / dBFS"], title="呼噜检测任务", title_size=30, body_size=25)
    text_box(d, imu, ["I2C 读取 LSM6DS3", "自由落体 / 摇晃判断"], title="IMU 监测任务", title_size=30, body_size=25)
    text_box(d, ui, ["主页 / SOS / 解除", "闹钟 / 报警 / 推理结果"], title="LVGL UI 状态机", title_size=30, body_size=25)
    text_box(d, report, ["Wi-Fi 管理 / Flash 配置", "hardware/* / emergency"], title="网络上报任务", title_size=30, body_size=25)
    arrow(d, [(430, 682), (470, 682)])
    arrow(d, [(430, 715), (450, 715), (450, 790), (1000, 790), (1000, 755)])
    arrow(d, [(430, 905), (470, 905)])
    arrow(d, [(790, 905), (830, 905)])
    arrow(d, [(650, 755), (650, 830)])
    arrow(d, [(1095, 755), (1095, 830)])

    radar_tasks = (80, 1130, 1210, 1465)
    dashed_rect(d, radar_tasks, width=3, dash=12, gap=8)
    group_title(d, 105, 1145, "雷达板 / FreeRTOS 任务", size=36)
    udp = (105, 1245, 345, 1385)
    radar_task = (390, 1245, 650, 1385)
    config = (695, 1245, 930, 1385)
    motion = (975, 1245, 1185, 1385)
    text_box(d, udp, ["Wi-Fi 连接", "UDP 9988 收发"], title="udp_server", title_size=27, body_size=24)
    text_box(d, radar_task, ["SPI+IRQ 采帧", "队列发布"], title="radar_task", title_size=27, body_size=24)
    text_box(d, config, ["JSON 启停命令", "雷达配置"], title="config_task", title_size=27, body_size=24)
    text_box(d, motion, ["BMI270", "BLE / LED"], title="状态任务", title_size=27, body_size=24)
    arrow(d, [(345, 1315), (390, 1315)], both=True)
    arrow(d, [(650, 1315), (695, 1315)], both=True)
    arrow(d, [(930, 1315), (975, 1315)], both=True)

    web = (120, 1530, 570, 1665)
    app = (690, 1530, 1140, 1665)
    text_box(d, web, ["驾驶舱 / 预警中心 / 环境分析"], title="Vue Web", title_size=33, body_size=26)
    text_box(d, app, ["后台轮询 / 本地通知 / 处理解除"], title="Android 监护人 App", title_size=31, body_size=25)

    # Edge software blocks.
    udp_rx = (1320, 255, 1645, 400)
    http_rx = (1695, 255, 2025, 400)
    radar_algo = (1320, 500, 1645, 670)
    device_state = (1695, 500, 2025, 670)
    fusion = (1320, 785, 1645, 955)
    events = (1695, 785, 2025, 955)
    api = (1410, 1080, 1935, 1260)
    storage = (1410, 1390, 1935, 1570)
    text_box(d, udp_rx, ["雷达原始帧", "启停控制回传"], title="UDP 接收服务", title_size=31, body_size=27)
    text_box(d, http_rx, ["呼噜 / 环境心跳", "SOS / 解除"], title="HTTP 硬件接口", title_size=31, body_size=27)
    text_box(d, radar_algo, ["距离门控 / 信号滤波", "心率 / 呼吸率估计"], title="雷达生命体征处理", title_size=31, body_size=27)
    text_box(d, device_state, ["在线 age_seconds", "设备 / 环境 / 时间线"], title="统一运行状态层", title_size=31, body_size=27)
    text_box(d, fusion, ["低呼吸连续窗口", "呼噜 / dBFS 证据", "置信度与去重"], title="雷达+呼噜融合", title_size=31, body_size=26)
    text_box(d, events, ["sleep_events", "active / resolved", "warning / critical"], title="事件与告警中心", title_size=31, body_size=26)
    text_box(d, api, ["/status  /timeline  /sleep/overview", "/emergency  /emergency/resolve"], title="FastAPI REST 接口", title_size=32, body_size=27)
    text_box(d, storage, ["实时 timeline", "事件详情与处理记录", "历史数据扩展"], title="状态与历史存储", title_size=32, body_size=27)
    arrow(d, [(1480, 400), (1480, 500)])
    arrow(d, [(1860, 400), (1860, 500)])
    arrow(d, [(1480, 670), (1480, 785)])
    arrow(d, [(1860, 670), (1860, 785)])
    arrow(d, [(1645, 870), (1695, 870)])
    arrow(d, [(1860, 955), (1860, 1015), (1670, 1015), (1670, 1080)])
    arrow(d, [(1670, 1260), (1670, 1390)], both=True)

    # Cloud software blocks.
    ws = (2150, 250, 2510, 400)
    asr = (2150, 485, 2510, 625)
    llm = (2150, 710, 2510, 850)
    tts = (2150, 930, 2510, 1030)
    text_box(d, ws, ["设备鉴权", "实时音频会话"], title="WebSocket 网关", title_size=30, body_size=26)
    text_box(d, asr, ["语音转文字", "返回 STT"], title="ASR", title_size=34, body_size=27)
    text_box(d, llm, ["对话理解", "紧急话术响应"], title="对话模型", title_size=32, body_size=27)
    text_box(d, tts, ["语音合成 / 音频流"], title="TTS", title_size=32, body_size=26)
    arrow(d, [(2330, 400), (2330, 485)])
    arrow(d, [(2330, 625), (2330, 710)])
    arrow(d, [(2330, 850), (2330, 930)])

    # Cross-zone flows.
    arrow(d, [(1170, 905), (1245, 905), (1245, 240), (1860, 240), (1860, 255)], label="Wi-Fi / HTTP JSON", label_pos=(1530, 235), label_size=22)
    arrow(d, [(1185, 1315), (1265, 1315), (1265, 330), (1320, 330)], both=True, label="Wi-Fi / UDP 9988", label_pos=(1275, 1180), label_size=22)
    # Voice traffic is routed above all groups to avoid crossing edge-processing boxes.
    arrow(
        d,
        [(790, 650), (810, 650), (810, 580), (1220, 580), (1220, 120), (2330, 120), (2330, 250)],
        both=True,
        label="Wi-Fi / WebSocket / Opus",
        label_pos=(1880, 120),
        label_size=22,
    )
    # REST responses and handling commands are routed below the radar task group.
    arrow(d, [(1410, 1170), (1245, 1170), (1245, 1490), (915, 1490), (915, 1530)], both=True, label="REST / JSON", label_pos=(1250, 1415), label_size=22)
    arrow(d, [(1245, 1490), (345, 1490), (345, 1530)], both=True)

    path = OUT / "diagram_edge_cloud_software_bw.png"
    image.save(path, dpi=(300, 300), optimize=True)
    return path


if __name__ == "__main__":
    print(create_hardware_diagram())
    print(create_software_diagram())
