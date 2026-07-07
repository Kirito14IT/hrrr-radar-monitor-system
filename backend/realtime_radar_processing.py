"""
    实时雷达数据处理
    基于UDP接收到的雷达原始数据进行处理，实现实时处理流程
"""
import os
import sys
import numpy as np
import struct
import time
import socket
import threading
import math
import wave
import hashlib
import asyncio
import urllib.error
import urllib.request
from collections import deque
from datetime import datetime
from pathlib import Path
from scipy import signal
from radar_func import range_fft, mti_filter, extract_phase

# 导入信号分解模块
from signal_decomposition import apply_cwt, apply_eemd
from apnea_fusion import breath_window_abnormal  # detect_suspected_apnea_events removed — too many false positives

# 导入存在检测模块
from presence_detection import RadarPresenceDetector

# 导入FastAPI相关模块
from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import uvicorn
from typing import Dict, Any, Optional
import json
import queue

# 导入数据库操作模块
from db import (
    DEFAULT_BED_ID,
    create_user,
    get_bed_by_id,
    get_user_by_username,
    list_bed_registry,
    query_heart_data_by_date,
    resolve_bed_id,
    save_vitals_with_user,
    verify_password,
)

# 确保当前目录在Python路径中，便于导入自定义模块
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

def _load_local_env_file(env_path):
    """Load backend/.env without adding a python-dotenv dependency."""
    try:
        path = Path(env_path)
        if not path.exists():
            return
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except Exception as exc:
        print(f"警告：读取本地环境配置失败：{exc}")

_load_local_env_file(Path(current_dir) / ".env")

curPath = os.path.abspath(os.path.dirname(__file__))
rootPath = os.path.split(curPath)[0]
sys.path.append(rootPath)
# 导入模型所需的自定义模块
try:
    import radar_dl_models
    print("成功导入radar_dl_models自定义模块")
except ImportError:
    print("警告：无法导入radar_dl_models模块，这可能导致模型加载或推理错误")
    print(f"Python搜索路径: {sys.path}")
    # 尝试查找radar_dl_models.py文件
    possible_locations = [
        os.path.join(current_dir, "radar_dl_models.py"),
        os.path.join(current_dir, "models", "radar_dl_models.py"),
        os.path.join(current_dir, "trained_models", "radar_dl_models.py")
    ]
    for loc in possible_locations:
        if os.path.exists(loc):
            print(f"找到radar_dl_models.py文件在: {loc}")
            # 添加其目录到Python路径
            sys.path.append(os.path.dirname(loc))
            try:
                import radar_dl_models
                print("第二次尝试导入radar_dl_models成功")
                break
            except ImportError:
                print(f"尝试从{loc}导入失败")

# 导入TensorFlow/Keras模型处理
try:
    import tensorflow as tf
    from tensorflow import keras
    try:
        import tf_keras as legacy_keras
        print("成功导入tf_keras旧模型兼容加载器")
    except ImportError:
        legacy_keras = None
    print("成功导入TensorFlow/Keras")
except ImportError:
    print("警告：无法导入TensorFlow/Keras，模型推理功能将被禁用")

# 导入雷达设置
try:
    from radar_settings import get_radar_params, get_param
    radar_params = get_radar_params()
    print("成功导入雷达参数配置")
except ImportError:
    print("警告：无法导入radar_settings，将使用默认参数")
    # 使用默认参数
    radar_params = {
        'frame_rate': 30,
        'frame_time': 0.0333,
        'wavelength': 0.00494,
        'range_resolution': 0.027,
    }

# 处理参数设置
FRAME_RATE = get_param('frame_rate')           # 雷达帧率
BUFFER_SIZE = 65539                            # UDP包缓冲区大小
RADAR_DATA_COMMAND = 1                         # 雷达固件数据帧命令字
RADAR_STATUS_COMMAND = 2                       # 雷达固件状态帧命令字
RADAR_DUMMY_BYTE = 0xFF                        # 雷达固件数据帧头 dummy byte

# 雷达参数设置
FFT_SIZE = 512                               # 距离FFT大小
WINDOW_TYPE = 'hann'                         # 窗口类型（汉宁窗）
RANGE_RESOLUTION = get_param('range_resolution')  # 距离分辨率，单位：米
WAVELENGTH = get_param('wavelength')           # 波长，单位：米
DISTANCE_RESOLUTION = get_param('range_resolution')  # 距离分辨率，单位：米

# 处理窗口设置
WINDOW_SIZE_SECONDS = 10  # 处理窗口为1秒
WINDOW_SIZE = int(WINDOW_SIZE_SECONDS * FRAME_RATE)  # 窗口大小（采样点数）
STEP_SIZE_SECONDS = 1      # 滑动步长为1秒
STEP_SIZE = int(STEP_SIZE_SECONDS * FRAME_RATE)  # 步长（采样点数）

# 信号分解参数
DECOMPOSE_SIGNAL = True    # 是否进行信号分解
DECOMP_TYPE = "cwt"        # 信号分解类型: "cwt" 或 "eemd"
CWT_SCALES = np.arange(1, 65)  # CWT尺度参数
CWT_WAVELET = 'morl'       # CWT小波类型
EEMD_NOISE_WIDTH = 0.05    # EEMD噪声幅度
EEMD_ENSEMBLE_SIZE = 50    # EEMD集合大小
EEMD_MAX_IMF = 5          # EEMD最大IMF数量

# 存在检测参数
ENABLE_PRESENCE_DETECTION = True              # 是否启用存在检测
PRESENCE_HISTORY_LENGTH = 5                   # 存在检测历史长度
PRESENCE_COUNT_THRESHOLD = 1                  # 存在检测计数阈值
PRESENCE_DISTANCE_MIN_M = 0.1                 # 目标有效距离下限；同时用于生命体征保活
PRESENCE_DISTANCE_MAX_M = 1.0                 # 目标有效距离上限；同时用于生命体征保活
PRESENCE_DISTANCE_STABILITY_SPAN_M = 0.12     # 最近目标距离最大-最小跨度不超过该值才算稳定
BOARD_TIMEOUT_SECONDS = 5.0                   # 开发板离线判定超时
ENVIRONMENT_BOARD_TIMEOUT_SECONDS = 15.0       # 温湿度板离线判定超时
SNORE_BOARD_TIMEOUT_SECONDS = 15.0             # 呼噜板离线判定超时（10 秒一包音频，宽松一些）
VOICE_BOARD_TIMEOUT_SECONDS = 30.0             # 语音事件到达后暂时标记小智语音链路在线
EDGI_BOARD_TIMEOUT_SECONDS = 60.0              # 任一 Edgi 模块心跳后的整板在线宽限期
VITALS_HOLD_SECONDS = 3.0                      # 短暂丢失生命体征时保留最近有效值
VITALS_LOST_PROCESS_COUNT = 3                  # 连续多少个处理窗口失败后才确认丢失
ENV_TEMPERATURE_OFFSET_C = 0                # AHT20 靠近开发板/WiFi 发热，统一显示温度校准偏移
ENV_TEMPERATURE_MIN_C = -20.0                  # 校准后温度保护下限
ENV_TEMPERATURE_MAX_C = 60.0                   # 校准后温度保护上限
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_TIMEOUT_SECONDS = float(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "25"))
DEEPSEEK_MAX_ANALYSIS_ROWS = int(os.getenv("DEEPSEEK_MAX_ANALYSIS_ROWS", "80"))
DEEPSEEK_MAX_TOKENS = int(os.getenv("DEEPSEEK_MAX_TOKENS", "1600"))
SNORE_SESSION_GRACE_SECONDS = 30.0             # 呼噜板按下 Snore detect 后保持在线的最长静默期
EMERGENCY_DEVICE_GRACE_SECONDS = 90.0          # 紧急报警播放期间，传感器短暂心跳抖动不判离线
TIMELINE_RETENTION_SECONDS = 7200             # 时间轴保留时长
SAMPLE_RATE = 16000                           # 呼噜板音频采样率
SAMPLE_WIDTH = 2                              # int16 PCM
NUM_CHANNELS = 2                              # 呼噜板音频双声道
SNORE_EVENT_HOLD_SECONDS = 180.0              # 呼噜事件状态保持时间
SNORE_SOUND_STOP_SECONDS = 6                # 模型确认的呼噜声音连续消失超过该时长，判定一次呼噜停止
SNORE_MIN_DURATION_FOR_ALARM = 30.0           # 呼噜至少持续该时长，停止后才允许触发呼吸下降报警
SNORE_STOP_ALARM_COOLDOWN_SECONDS = 20.0      # 呼噜停止+呼吸下降报警去抖，避免同一段声音重复报警
BREATH_DESCENT_WINDOW_SECONDS = 5.0           # 判断呼吸波形下降时使用的雷达相位窗口
BREATH_DESCENT_COMPARE_SECONDS = 2.5          # 比较窗口：最近 1s vs 前 1s
SNORE_PRESENCE_BYPASS_SECONDS = 10.0         # 呼噜声响起/刚消失后的存在性检测屏蔽窗口
NIGHT_ABSENCE_START_HOUR = 22                # 夜间离床监护开始小时
NIGHT_ABSENCE_END_HOUR = 6                   # 夜间离床监护结束小时
NIGHT_ABSENCE_ALARM_SECONDS = 3600.0         # 夜间连续未检测到在床超过 1 小时报警
NIGHT_ABSENCE_ALARM_COOLDOWN_SECONDS = 3600.0

def comfort_status_for(temperature_c, humidity_pct, sensor_ok=True, online=True):
    if not online:
        return "offline"
    if not sensor_ok:
        return "sensor_error"
    if temperature_c is None or humidity_pct is None:
        return "no_data"

    temp_status = None
    humidity_status = None
    critical = False

    if temperature_c < 15.0:
        temp_status = "cold"
        critical = True
    elif temperature_c < 18.0:
        temp_status = "cold"
    elif temperature_c > 32.0:
        temp_status = "hot"
        critical = True
    elif temperature_c > 28.0:
        temp_status = "hot"

    if humidity_pct < 30.0:
        humidity_status = "dry"
        critical = True
    elif humidity_pct < 40.0:
        humidity_status = "dry"
    elif humidity_pct > 80.0:
        humidity_status = "humid"
        critical = True
    elif humidity_pct > 70.0:
        humidity_status = "humid"

    parts = [part for part in (temp_status, humidity_status) if part]
    if not parts:
        return "comfortable"
    status = "_".join(parts)
    return f"{status}_critical" if critical else status


def estimate_breath_rate_fft_with_quality(phase_signal, fs=FRAME_RATE, breath_band=(0.1, 0.5)):
    """
    使用带通 + Welch 功率谱估计呼吸率，并返回质量分。

    旧版本直接取 FFT 最大峰，雷达轻微抖动、相位跳变或短窗噪声都会把峰值拉偏。
    这里增加去趋势、相位展开、谱峰信噪比和边界峰过滤，宁可返回 None，
    也不要把低质量结果当作真实呼吸率。
    """
    if phase_signal is None:
        return None, 0.0

    values = np.asarray(phase_signal, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) < max(64, int(fs * 8)):
        return None, 0.0

    values = np.unwrap(values)
    values = signal.detrend(values, type="linear")
    if np.std(values) < 1e-5:
        return None, 0.0

    try:
        sos = signal.butter(3, breath_band, btype="bandpass", fs=fs, output="sos")
        filtered = signal.sosfiltfilt(sos, values)
    except ValueError:
        filtered = values

    nperseg = min(len(filtered), max(128, int(fs * 16)))
    if nperseg < 64:
        return None, 0.0
    freqs, power = signal.welch(
        filtered,
        fs=fs,
        window="hann",
        nperseg=nperseg,
        noverlap=nperseg // 2,
        nfft=max(1024, 4 * nperseg),
        detrend=False,
        scaling="spectrum",
    )

    band_mask = (freqs >= breath_band[0]) & (freqs <= breath_band[1])
    if not np.any(band_mask):
        return None, 0.0
    band_freqs = freqs[band_mask]
    band_power = power[band_mask]
    if len(band_power) < 5 or float(np.max(band_power)) <= 1e-12:
        return None, 0.0

    peak_idx = int(np.argmax(band_power))
    peak_power = float(band_power[peak_idx])
    noise_floor = float(np.median(band_power) + 1e-12)
    snr = peak_power / noise_floor
    if snr < 3.0 or peak_idx in {0, len(band_power) - 1}:
        return None, min(0.45, snr / 6.0)

    # 抛物线插值，减少频率 bin 粗糙造成的跳动。
    left = float(band_power[peak_idx - 1])
    center = float(band_power[peak_idx])
    right = float(band_power[peak_idx + 1])
    denom = left - 2.0 * center + right
    offset = 0.0 if abs(denom) < 1e-12 else 0.5 * (left - right) / denom
    offset = max(-0.5, min(0.5, offset))
    step = float(band_freqs[1] - band_freqs[0]) if len(band_freqs) > 1 else 0.0
    peak_freq = float(band_freqs[peak_idx]) + offset * step

    # 如果主峰落在二倍频，而半频附近也有能量，取半频作为呼吸率。
    half_freq = peak_freq / 2.0
    if breath_band[0] <= half_freq <= breath_band[1]:
        half_idx = int(np.argmin(np.abs(band_freqs - half_freq)))
        if float(band_power[half_idx]) >= peak_power * 0.42:
            peak_freq = float(band_freqs[half_idx])
            peak_power = float(band_power[half_idx])

    breath_rate_bpm = peak_freq * 60.0
    if not 6.0 <= breath_rate_bpm <= 30.0:
        return None, 0.0

    dominance = peak_power / (float(np.sum(band_power)) + 1e-12)
    quality = min(1.0, 0.55 * min(1.0, snr / 10.0) + 0.45 * min(1.0, dominance * 6.0))
    if quality < 0.35:
        return None, quality
    return breath_rate_bpm, quality


def estimate_breath_rate_fft(phase_signal, fs=FRAME_RATE, breath_band=(0.1, 0.5)):
    breath_rate, _quality = estimate_breath_rate_fft_with_quality(phase_signal, fs, breath_band)
    return breath_rate


def estimate_breath_periodicity(phase_signal, fs=FRAME_RATE, breath_band=(0.1, 0.5)):
    """Estimate how clearly the radar phase signal contains periodic respiration."""
    if phase_signal is None:
        return 0.0
    values = np.asarray(phase_signal, dtype=float)
    values = values[np.isfinite(values)]
    if values.size < max(64, int(fs * 8)):
        return 0.0

    try:
        values = signal.detrend(values)
        if float(np.std(values)) <= 1e-9:
            return 0.0
        sos = signal.butter(3, breath_band, btype="bandpass", fs=fs, output="sos")
        filtered = signal.sosfiltfilt(sos, values)
        filtered = filtered - float(np.mean(filtered))
        std = float(np.std(filtered))
        if std <= 1e-9:
            return 0.0
        filtered = filtered / std

        corr = np.correlate(filtered, filtered, mode="full")[filtered.size - 1:]
        if corr.size < 2 or abs(float(corr[0])) <= 1e-12:
            return 0.0
        corr = corr / float(corr[0])

        min_lag = max(1, int(fs / breath_band[1]))
        max_lag = min(corr.size - 1, int(fs / breath_band[0]))
        if max_lag <= min_lag:
            return 0.0
        band_corr = corr[min_lag:max_lag + 1]
        if band_corr.size < 3:
            return 0.0

        peak = max(0.0, float(np.max(band_corr)))
        floor = max(0.0, float(np.median(band_corr)))
        prominence = max(0.0, peak - floor)
        periodicity = min(1.0, 0.72 * peak + 0.28 * min(1.0, prominence * 2.5))
        return round(max(0.0, periodicity), 3)
    except Exception:
        return 0.0


class RealtimeRadarProcessor:
    """实时雷达数据处理器"""

    def __init__(self, server_ip='192.168.118.149', server_port=57345,
                 load_models=True, cwt_model_path=None, eemd_model_path=None,
                 api_enabled=True, api_port=8081):
        """
        初始化实时处理器

        参数:
        server_ip: 雷达设备的IP地址
        server_port: 雷达设备的端口号
        load_models: 是否加载预训练模型
        cwt_model_path: CWT预训练模型路径，默认为'trained_models/DeepStateSpace_CWT_best.keras'
        eemd_model_path: EEMD预训练模型路径，默认为'trained_models/DeepStateSpace_EEMD_best.keras'
        api_enabled: 是否启用FastAPI接口
        api_port: FastAPI服务器端口
        """
        self.server_ip = server_ip
        self.server_port = server_port
        self.socket = None
        self.running = False
        self.data_buffer = []  # 用于保存最近的原始数据
        self.processing_thread = None
        self.state_lock = threading.RLock()

        # 初始化存在检测器
        self.presence_detector = RadarPresenceDetector(
            history_length=PRESENCE_HISTORY_LENGTH,
            count_threshold=PRESENCE_COUNT_THRESHOLD,
            distance_min_m=PRESENCE_DISTANCE_MIN_M,
            distance_max_m=PRESENCE_DISTANCE_MAX_M,
            distance_stability_span_m=PRESENCE_DISTANCE_STABILITY_SPAN_M,
        )
        self.presence_detected = False
        self.presence_stable = False
        self.presence_bypassed_by_snore = False

        # API服务器设置
        self.api_enabled = api_enabled
        self.api_port = api_port
        self.api_thread = None
        self.app = None

        # 统计数据
        self.total_frames_received = 0      # 总接收帧数（不再重置）
        self.period_frames_received = 0     # 周期内接收帧数（每次报告后重置）
        self.total_frames_processed = 0
        self.period_frames_processed = 0    # 周期内处理帧数
        self.last_frame_number = 0
        self.processing_count = 0
        self.start_time = time.time()       # 程序启动时间
        self.last_status_time = time.time() # 上次状态报告时间
        self.frames_since_last_process = 0  # 自上次处理后累积的帧数 - 添加为类属性
        self.last_radar_received_time = None
        self.last_radar_received_at = None
        self.current_radar_bed_id = DEFAULT_BED_ID
        self.last_radar_status_time = None
        self.last_radar_status_at = None
        self.radar_board_stationary = True
        self.radar_motion_reason = "disabled"
        self.radar_motion_delta = None
        self.radar_motion_sensor_ready = None
        self.last_snore_heartbeat_time = None
        self.last_snore_heartbeat_at = None
        self.last_snore_bed_id = DEFAULT_BED_ID
        self.last_environment_heartbeat_time = None
        self.last_environment_heartbeat_at = None
        self.last_environment_bed_id = DEFAULT_BED_ID
        self.last_voice_received_time = None
        self.last_voice_received_at = None
        self.last_edgi_heartbeat_time = None
        self.last_edgi_heartbeat_at = None
        self.last_edgi_bed_id = DEFAULT_BED_ID
        self.external_bed_vitals = {}
        self.bed_device_state = {}
        self.raw_temperature_c = None
        self.temperature_c = None
        self.humidity_pct = None
        self.environment_sensor_ok = False
        self.last_audio_received_time = None
        self.last_audio_received_at = None
        self.snore_session_active = False
        self.snore_session_stopped = False
        self.snore_session_started_at = None
        self.snore_session_started_text = None
        self.snore_session_last_seen_at = None
        self.last_audio_file = None
        self.last_audio_seconds = 0.0
        self.last_audio_dbfs = None
        self.audio_upload_count = 0
        self.snore_score = 0.0
        self.snore_dbfs = None
        self.snore_detected = False
        self.snore_event_count = 0
        self.last_snore_time = None
        self.last_snore_at = None
        self.snore_sound_active = False
        self.snore_sound_started_time = None
        self.snore_sound_started_at = None
        self.last_snore_sound_time = None
        self.last_snore_sound_at = None
        self.last_snore_sound_stop_time = None
        self.last_snore_sound_stop_at = None
        self.last_snore_stop_alarm_time = None
        self.snore_stop_breath_alarm_count = 0
        self.last_snore_stop_fusion = None
        self.presence_absent_started_time = None
        self.presence_absent_started_at = None
        self.last_night_absence_alarm_time = None
        self.last_night_absence_alarm_at = None
        self.night_absence_debug = {
            "monitoring": False,
            "in_night_window": False,
            "absent": False,
            "absent_seconds": 0.0,
            "alarm_after_seconds": NIGHT_ABSENCE_ALARM_SECONDS,
            "reason": "init",
        }
        self.timeline = []
        self.emergency_events = []
        self.radar_debug = {
            "sample_format": "float16",
            "packet_len": 0,
            "payload_len": 0,
            "samples_per_frame": 0,
            "first_8_bytes_hex": "",
            "sample_min": None,
            "sample_max": None,
            "sample_mean": None,
            "sample_std": None,
            "target_bin": None,
            "target_distance": None,
            "presence_detected": False,
            "presence_signal": False,
            "presence_energy_stable": False,
            "presence_distance_stable": False,
            "presence_distance_span": None,
            "presence_distance": None,
            "presence_distance_min_m": PRESENCE_DISTANCE_MIN_M,
            "presence_distance_max_m": PRESENCE_DISTANCE_MAX_M,
            "presence_distance_stability_span_m": PRESENCE_DISTANCE_STABILITY_SPAN_M,
            "presence_detection_value": None,
            "presence_detection_threshold": 1.01,
            "presence_detection_bin": None,
            "presence_below_threshold": False,
            "presence_stable": False,
            "presence_bypassed_by_snore": False,
            "board_still": True,
            "motion_reason": "disabled",
            "motion_delta": None,
            "motion_sensor_ready": None,
        }

        # 结果存储
        self.phase_values = None            # 最近一次处理的相位值
        self.target_bin = None              # 最近一次处理的目标bin
        self.cwt_results = None             # 最近一次CWT分析结果
        self.eemd_results = None            # 最近一次EEMD分析结果
        self.model_prediction = None        # 最近一次模型预测结果
        self.heart_rate = None              # 最近一次心率预测值
        self.breath_rate= None              # 最近一次呼吸预测值
        self.breath_rate_quality = 0.0
        self.breath_periodicity = 0.0
        self._breath_rate_history = deque(maxlen=7)
        self._breath_rate_missing_count = 0
        self.last_valid_heart_rate = None
        self.last_valid_breath_rate = None
        self.last_valid_breath_quality = 0.0
        self.last_valid_vitals_time = None
        self.last_valid_vitals_at = None
        self.heart_rate_fresh = False
        self.breath_rate_fresh = False
        self.vitals_state = "lost"
        self.vitals_missing_count = 0
        # 模型加载
        self.cwt_model = None
        self.eemd_model = None
        self.enable_model_inference = load_models

        # 如果启用模型推理，尝试加载当前分解方法对应的模型
        if load_models:
            try:
                if 'keras' in globals():
                    # 设置默认模型路径
                    if cwt_model_path is None:
                        cwt_model_path = os.path.join(current_dir, 'trained_models', 'DeepStateSpace_CWT_best.h5')
                    else:
                        cwt_model_path = os.path.abspath(cwt_model_path)
                    if eemd_model_path is None:
                        eemd_model_path = os.path.join(current_dir, 'trained_models', 'DeepStateSpace_EEMD_best.h5')
                    else:
                        eemd_model_path = os.path.abspath(eemd_model_path)

                    # 根据当前分解方法加载对应模型
                    if DECOMP_TYPE == "cwt":
                        print(f"检查CWT模型: {cwt_model_path}")
                        model_loadable, model_skip_reason = self._model_file_loadable_by_keras(cwt_model_path)
                        if model_loadable:
                            print(f"加载CWT模型: {cwt_model_path}")
                            self.cwt_model = self._load_model_compat(cwt_model_path)
                            print(f"CWT模型加载成功: {self.cwt_model.name}")
                        else:
                            print(f"警告: CWT模型文件不存在 - {cwt_model_path}")
                            self.enable_model_inference = False
                    elif DECOMP_TYPE == "eemd":
                        print(f"检查EEMD模型: {eemd_model_path}")
                        model_loadable, model_skip_reason = self._model_file_loadable_by_keras(eemd_model_path)
                        if model_loadable:
                            print(f"加载EEMD模型: {eemd_model_path}")
                            self.eemd_model = self._load_model_compat(eemd_model_path)
                            print(f"EEMD模型加载成功: {self.eemd_model.name}")
                        else:
                            print(f"警告: EEMD模型文件不存在 - {eemd_model_path}")
                            self.enable_model_inference = False
                else:
                    print("警告：TensorFlow/Keras未导入，无法加载模型")
                    self.enable_model_inference = False
            except Exception as e:
                print(f"加载模型时出错: {e}")
                self.enable_model_inference = False

        # 如果启用API，初始化FastAPI应用
        if self.api_enabled:
            self._init_api()

    @staticmethod
    def _model_file_loadable_by_keras(path):
        """Validate model file before keras.load_model to avoid noisy startup tracebacks."""
        if not path or not os.path.isfile(path):
            return False, "model file not found"
        try:
            with open(path, "rb") as model_file:
                header = model_file.read(8)
        except OSError as exc:
            return False, f"model file is not readable: {exc}"

        lower_path = path.lower()
        if lower_path.endswith(".keras") and header == b"\x89HDF\r\n\x1a\n":
            return False, "model file is HDF5 content but uses .keras extension; rename/convert it to .h5 or export a Keras v3 .keras zip"
        return True, ""

    @staticmethod
    def _load_model_compat(path):
        """Load both Keras 3 models and legacy HDF5 models."""
        lower_path = path.lower()
        if lower_path.endswith(".h5"):
            if legacy_keras is not None:
                return legacy_keras.models.load_model(path, compile=False)
            return keras.models.load_model(path, compile=False)
        return keras.models.load_model(path)

    @staticmethod
    def _jsonable(value):
        """Convert numpy/scientific values to plain JSON-safe Python objects."""
        if isinstance(value, dict):
            return {str(key): RealtimeRadarProcessor._jsonable(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [RealtimeRadarProcessor._jsonable(item) for item in value]
        if hasattr(value, "tolist"):
            return RealtimeRadarProcessor._jsonable(value.tolist())
        if hasattr(value, "item"):
            try:
                return value.item()
            except (TypeError, ValueError):
                pass
        return value

    def _now_iso(self):
        """返回秒级ISO时间戳，供前端时间轴解析。"""
        return datetime.fromtimestamp(time.time()).isoformat(timespec="seconds")

    def _seconds_since(self, timestamp):
        if timestamp is None:
            return None
        if isinstance(timestamp, (int, float)):
            timestamp_seconds = float(timestamp)
        else:
            timestamp_text = str(timestamp).strip()
            if not timestamp_text:
                return None
            try:
                timestamp_seconds = float(timestamp_text)
            except ValueError:
                try:
                    timestamp_seconds = datetime.fromisoformat(timestamp_text.replace("Z", "+00:00")).timestamp()
                except (TypeError, ValueError):
                    return None
        return max(0.0, time.time() - timestamp_seconds)

    def _radar_board_online(self):
        times = [
            value for value in (
                self.last_radar_received_time,
                self.last_radar_status_time,
            )
            if value is not None
        ]
        age = self._seconds_since(max(times)) if times else None
        return bool(self.running and age is not None and age <= BOARD_TIMEOUT_SECONDS)

    def _radar_data_online(self):
        age = self._seconds_since(self.last_radar_received_time)
        return bool(
            self.running and
            age is not None and
            age <= BOARD_TIMEOUT_SECONDS
        )

    def _snore_board_online(self):
        # Snore detect 已按下 → 在 session 宽限期内一律视为在线
        if self.snore_session_active:
            last_seen = self.snore_session_last_seen_at
            if last_seen is not None and self._seconds_since(last_seen) <= SNORE_SESSION_GRACE_SECONDS:
                return True
            # session 内长时间没收到任何活动，自动结束 session
            self.snore_session_active = False

        # 用户已经按下 back（或者从未开始过 session 之前的旧路径），
        # 退回到真实呼噜心跳时间判断。/audio 只做原始音频存档，不再驱动呼噜状态。
        if self.snore_session_stopped:
            # 显式 back 后立刻离线，不再被 5/15 秒内的心跳“复活”
            return False

        heartbeat_age = self._seconds_since(self.last_snore_heartbeat_time)
        if (
            heartbeat_age is not None and
            heartbeat_age <= EMERGENCY_DEVICE_GRACE_SECONDS and
            self._emergency_device_grace_active()
        ):
            return True
        return bool(heartbeat_age is not None and heartbeat_age <= SNORE_BOARD_TIMEOUT_SECONDS)

    def _environment_board_online(self):
        age = self._seconds_since(self.last_environment_heartbeat_time)
        if (
            age is not None and
            age <= EMERGENCY_DEVICE_GRACE_SECONDS and
            self._emergency_device_grace_active()
        ):
            return True
        return bool(age is not None and age <= ENVIRONMENT_BOARD_TIMEOUT_SECONDS)

    def _voice_board_online(self):
        age = self._seconds_since(self.last_voice_received_time)
        return bool(age is not None and age <= VOICE_BOARD_TIMEOUT_SECONDS)

    def _edgi_board_online(self):
        age = self._seconds_since(self.last_edgi_heartbeat_time)
        return bool(age is not None and age <= EDGI_BOARD_TIMEOUT_SECONDS)

    def _active_emergency_event(self, bed_id=None):
        with self.state_lock:
            active = [
                event for event in self.emergency_events
                if event.get("status", "active") == "active"
                and event.get("severity", "critical") in {"warning", "critical"}
                and (bed_id is None or event.get("bed_id", DEFAULT_BED_ID) == bed_id)
            ]
        return max(
            active,
            key=lambda item: (
                self._severity_rank(item.get("severity")),
                item.get("timestamp", ""),
            ),
            default=None,
        )

    def _emergency_device_grace_active(self):
        edgi_age = self._seconds_since(self.last_edgi_heartbeat_time)
        return bool(
            edgi_age is not None and
            edgi_age <= EMERGENCY_DEVICE_GRACE_SECONDS and
            self._active_emergency_event() is not None
        )

    def _environment_snapshot(self):
        environment_age = self._seconds_since(self.last_environment_heartbeat_time)
        environment_board_online = self._environment_board_online()
        environment_online = bool(environment_board_online and self.environment_sensor_ok)
        raw_temperature = round(float(self.raw_temperature_c), 1) if environment_online and self.raw_temperature_c is not None else None
        temperature = round(float(self.temperature_c), 1) if environment_online and self.temperature_c is not None else None
        humidity = round(float(self.humidity_pct), 1) if environment_online and self.humidity_pct is not None else None
        return {
            "environment_board_online": environment_board_online,
            "environment_online": environment_online,
            "environment_sensor_ok": bool(self.environment_sensor_ok),
            "last_environment_heartbeat_at": self.last_environment_heartbeat_at,
            "environment_age_seconds": round(environment_age, 2) if environment_age is not None else None,
            "temperature_c": temperature,
            "raw_temperature_c": raw_temperature,
            "temperature_offset_c": ENV_TEMPERATURE_OFFSET_C,
            "humidity_pct": humidity,
            "comfort_status": comfort_status_for(
                temperature,
                humidity,
                sensor_ok=bool(self.environment_sensor_ok),
                online=environment_online,
            ),
        }

    def _resolve_runtime_bed_id(self, bed_id=None, radar_ip=None, device_id=None, source=None):
        try:
            return resolve_bed_id(
                bed_id=bed_id,
                radar_ip=radar_ip,
                device_id=device_id,
                source=source,
                default_bed_id=DEFAULT_BED_ID,
            )
        except Exception as exc:
            print(f"床位映射失败，使用默认床位: {exc}")
            return DEFAULT_BED_ID

    def _bed_metadata(self, bed_id=None):
        try:
            return get_bed_by_id(bed_id or DEFAULT_BED_ID) or {
                "bed_id": DEFAULT_BED_ID,
                "bed_label": "01床",
                "room": "护士站默认病房",
                "patient_name": "默认患者",
            }
        except Exception:
            return {
                "bed_id": bed_id or DEFAULT_BED_ID,
                "bed_label": "01床",
                "room": "护士站默认病房",
                "patient_name": "默认患者",
            }

    def _event_belongs_to_bed(self, event, bed_id):
        return (event or {}).get("bed_id", DEFAULT_BED_ID) == (bed_id or DEFAULT_BED_ID)

    def _bed_state(self, bed_id):
        return self.bed_device_state.setdefault(bed_id or DEFAULT_BED_ID, {})

    def _external_bed_vitals_online(self, bed_id, timeout=BOARD_TIMEOUT_SECONDS * 3):
        state = self.external_bed_vitals.get(bed_id or DEFAULT_BED_ID)
        if not state:
            return False
        age = self._seconds_since(state.get("received_time"))
        return bool(age is not None and age <= timeout)

    def _timeline_entry_from_external_vitals(self, bed_id, vitals):
        timestamp = vitals.get("timestamp") or self._now_iso()
        target_distance = vitals.get("target_distance")
        snore_state = self._bed_state(bed_id).get("snore") or {}
        env_state = self._bed_state(bed_id).get("environment") or {}
        snore_online = self._seconds_since(snore_state.get("received_time")) is not None and self._seconds_since(snore_state.get("received_time")) <= SNORE_BOARD_TIMEOUT_SECONDS
        env_online = self._seconds_since(env_state.get("received_time")) is not None and self._seconds_since(env_state.get("received_time")) <= ENVIRONMENT_BOARD_TIMEOUT_SECONDS
        return {
            "timestamp": timestamp,
            "bed_id": bed_id,
            "heart_rate": vitals.get("heart_rate"),
            "breath_rate": vitals.get("breath_rate"),
            "breath_quality": vitals.get("breath_quality", 0.86),
            "breath_periodicity": vitals.get("breath_periodicity", 0.82),
            "heart_rate_fresh": True,
            "breath_rate_fresh": True,
            "vitals_state": "fresh",
            "vitals_age_seconds": 0.0,
            "last_valid_vitals_at": timestamp,
            "target_distance": target_distance or 0.0,
            "target_bin": int((target_distance or 0.0) / RANGE_RESOLUTION) if target_distance else None,
            "radar_online": True,
            "radar_board_stationary": True,
            "presence_detected": True,
            "presence_signal": True,
            "presence_energy_stable": True,
            "presence_distance_stable": True,
            "presence_distance_span": 0.04,
            "presence_distance": target_distance,
            "presence_distance_min_m": PRESENCE_DISTANCE_MIN_M,
            "presence_distance_max_m": PRESENCE_DISTANCE_MAX_M,
            "presence_distance_stability_span_m": PRESENCE_DISTANCE_STABILITY_SPAN_M,
            "presence_detection_value": vitals.get("presence_detection_value", 1.2),
            "presence_detection_threshold": vitals.get("presence_detection_threshold", 1.01),
            "presence_detection_bin": vitals.get("presence_detection_bin"),
            "presence_below_threshold": bool(vitals.get("presence_below_threshold", False)),
            "presence_stable": True,
            "presence_bypassed_by_snore": bool(snore_state.get("snore_detected")),
            "snore_online": snore_online,
            "snore_score": snore_state.get("snore_score", 0.0) if snore_online else 0.0,
            "snore_dbfs": snore_state.get("snore_dbfs") if snore_online else None,
            "snore_level": snore_state.get("snore_level") if snore_online else None,
            "snore_detected": bool(snore_state.get("snore_detected")) if snore_online else False,
            "environment_online": env_online and bool(env_state.get("sensor_ok", True)),
            "environment_board_online": env_online,
            "temperature_c": env_state.get("temperature_c") if env_online else None,
            "raw_temperature_c": env_state.get("raw_temperature_c") if env_online else None,
            "temperature_offset_c": ENV_TEMPERATURE_OFFSET_C,
            "humidity_pct": env_state.get("humidity_pct") if env_online else None,
            "comfort_status": env_state.get("comfort_status", "offline") if env_online else "offline",
            "sleep_stage": "模拟/外部开发板实时监护",
        }

    def _append_external_timeline(self, bed_id, vitals):
        with self.state_lock:
            entry = self._timeline_entry_from_external_vitals(bed_id, vitals)
            self.timeline.append(entry)
            self._trim_timeline_unlocked()

    def _status_snapshot_for_bed(self, bed_id=None):
        resolved_bed_id = self._resolve_runtime_bed_id(bed_id=bed_id)
        status = self._status_snapshot()
        bed = self._bed_metadata(resolved_bed_id)
        active_emergency = self._active_emergency_event(resolved_bed_id)
        external_vitals = self.external_bed_vitals.get(resolved_bed_id)
        external_vitals_online = self._external_bed_vitals_online(resolved_bed_id)
        if resolved_bed_id != (self.current_radar_bed_id or DEFAULT_BED_ID):
            for key in (
                "radar_online",
                "radar_board_online",
                "heart_rate_fresh",
                "breath_rate_fresh",
                "presence_detected",
                "presence_stable",
            ):
                status[key] = False
            status.update({
                "heart_rate": None,
                "breath_rate": None,
                "target_distance": None,
                "target_bin": None,
                "vitals_state": "lost",
                "vitals_age_seconds": None,
            })
        if external_vitals_online and external_vitals:
            status.update({
                "radar_online": True,
                "radar_board_online": True,
                "heart_rate": external_vitals.get("heart_rate"),
                "breath_rate": external_vitals.get("breath_rate"),
                "heart_rate_fresh": True,
                "breath_rate_fresh": True,
                "vitals_state": "fresh",
                "vitals_age_seconds": round(self._seconds_since(external_vitals.get("received_time")) or 0.0, 2),
                "last_valid_vitals_at": external_vitals.get("timestamp"),
                "target_distance": external_vitals.get("target_distance"),
                "target_bin": int((external_vitals.get("target_distance") or 0.0) / RANGE_RESOLUTION) if external_vitals.get("target_distance") else None,
                "presence_detected": True,
                "presence_stable": True,
                "presence_signal": True,
                "presence_energy_stable": True,
                "presence_distance_stable": True,
                "presence_distance_span": 0.04,
                "presence_distance": external_vitals.get("target_distance"),
                "presence_detection_value": external_vitals.get("presence_detection_value", 1.2),
                "presence_detection_threshold": external_vitals.get("presence_detection_threshold", 1.01),
                "presence_detection_bin": external_vitals.get("presence_detection_bin"),
                "presence_below_threshold": bool(external_vitals.get("presence_below_threshold", False)),
                "last_radar_received_at": external_vitals.get("timestamp"),
                "radar_age_seconds": round(self._seconds_since(external_vitals.get("received_time")) or 0.0, 2),
            })
        if resolved_bed_id != (self.last_snore_bed_id or DEFAULT_BED_ID):
            status.update({
                "snore_board_online": False,
                "snore_monitoring": False,
                "snore_paused": False,
                "snore_score": 0.0,
                "snore_dbfs": None,
                "snore_level": None,
                "snore_detected": False,
            })
        bed_state = self._bed_state(resolved_bed_id)
        snore_state = bed_state.get("snore") or {}
        snore_age = self._seconds_since(snore_state.get("received_time"))
        if snore_age is not None and snore_age <= SNORE_BOARD_TIMEOUT_SECONDS:
            status.update({
                "snore_board_online": True,
                "snore_monitoring": True,
                "snore_paused": False,
                "snore_score": snore_state.get("snore_score", 0.0),
                "snore_dbfs": snore_state.get("snore_dbfs"),
                "snore_level": snore_state.get("snore_level"),
                "snore_detected": bool(snore_state.get("snore_detected")),
                "snore_age_seconds": round(snore_age, 2),
                "last_snore_heartbeat_at": snore_state.get("received_at"),
            })
        if resolved_bed_id != (self.last_environment_bed_id or DEFAULT_BED_ID):
            status.update({
                "environment_board_online": False,
                "environment_online": False,
                "temperature_c": None,
                "raw_temperature_c": None,
                "humidity_pct": None,
                "comfort_status": "offline",
            })
        env_state = bed_state.get("environment") or {}
        env_age = self._seconds_since(env_state.get("received_time"))
        if env_age is not None and env_age <= ENVIRONMENT_BOARD_TIMEOUT_SECONDS:
            status.update({
                "environment_board_online": True,
                "environment_online": bool(env_state.get("sensor_ok", True)),
                "environment_sensor_ok": bool(env_state.get("sensor_ok", True)),
                "temperature_c": env_state.get("temperature_c"),
                "raw_temperature_c": env_state.get("raw_temperature_c"),
                "humidity_pct": env_state.get("humidity_pct"),
                "comfort_status": env_state.get("comfort_status", "comfortable"),
                "environment_age_seconds": round(env_age, 2),
                "last_environment_heartbeat_at": env_state.get("received_at"),
            })
        if resolved_bed_id != (self.last_edgi_bed_id or DEFAULT_BED_ID):
            status.update({
                "edgi_board_online": False,
                "voice_board_online": False,
            })
        edgi_state = bed_state.get("edgi") or {}
        edgi_age = self._seconds_since(edgi_state.get("received_time"))
        if edgi_age is not None and edgi_age <= EDGI_BOARD_TIMEOUT_SECONDS:
            status.update({
                "edgi_board_online": True,
                "voice_board_online": True,
                "edgi_age_seconds": round(edgi_age, 2),
                "last_edgi_heartbeat_at": edgi_state.get("received_at"),
            })
        status.update({
            "bed_id": resolved_bed_id,
            "bed": bed,
            "bed_label": bed.get("bed_label"),
            "room": bed.get("room"),
            "patient_name": bed.get("patient_name"),
            "emergency_active": active_emergency is not None,
            "active_emergency": active_emergency,
        })
        return status

    def _risk_for_bed_status(self, status):
        if status.get("emergency_active"):
            event = status.get("active_emergency") or {}
            return "critical", event.get("title") or event.get("message") or "存在待处理紧急事件"
        if status.get("snore_detected"):
            return "warning", "检测到呼噜"
        if not status.get("radar_board_online") and not status.get("edgi_board_online"):
            return "offline", "床旁设备离线"
        if status.get("vitals_state") == "lost":
            return "warning", "暂未获取生命体征"
        return "normal", "监护正常"

    def _bed_summary(self, bed):
        bed_id = bed.get("bed_id") or DEFAULT_BED_ID
        status = self._status_snapshot_for_bed(bed_id)
        risk_level, primary_issue = self._risk_for_bed_status(status)
        online_devices = sum(
            1 for key in (
                "radar_board_online",
                "snore_board_online",
                "environment_board_online",
                "edgi_board_online",
            )
            if status.get(key)
        )
        return {
            "bed_id": bed_id,
            "bed_label": bed.get("bed_label"),
            "room": bed.get("room"),
            "patient_name": bed.get("patient_name"),
            "patient_gender": bed.get("patient_gender"),
            "patient_age": bed.get("patient_age"),
            "patient_note": bed.get("patient_note"),
            "risk_level": risk_level,
            "primary_issue": primary_issue,
            "online_devices": online_devices,
            "radar_board_online": bool(status.get("radar_board_online")),
            "edgi_board_online": bool(status.get("edgi_board_online")),
            "snore_board_online": bool(status.get("snore_board_online")),
            "environment_board_online": bool(status.get("environment_board_online")),
            "heart_rate": status.get("heart_rate"),
            "breath_rate": status.get("breath_rate"),
            "temperature_c": status.get("temperature_c"),
            "humidity_pct": status.get("humidity_pct"),
            "snore_detected": bool(status.get("snore_detected")),
            "snore_score": status.get("snore_score"),
            "emergency_active": bool(status.get("emergency_active")),
            "active_emergency": status.get("active_emergency"),
            "last_update": status.get("last_radar_received_at") or status.get("last_edgi_heartbeat_at") or status.get("timestamp"),
            "status": status,
        }

    def _all_bed_summaries(self):
        try:
            beds = list_bed_registry(active_only=True)
        except Exception as exc:
            print(f"读取床位注册表失败: {exc}")
            beds = [self._bed_metadata(DEFAULT_BED_ID)]
        summaries = [self._bed_summary(bed) for bed in beds]
        critical_count = sum(1 for item in summaries if item["risk_level"] == "critical")
        warning_count = sum(1 for item in summaries if item["risk_level"] == "warning")
        online_count = sum(1 for item in summaries if item["online_devices"] > 0)
        return {
            "code": 200,
            "status": "success",
            "beds": summaries,
            "summary": {
                "total": len(summaries),
                "online": online_count,
                "critical": critical_count,
                "warning": warning_count,
                "normal": sum(1 for item in summaries if item["risk_level"] == "normal"),
                "offline": sum(1 for item in summaries if item["risk_level"] == "offline"),
            },
            "timestamp": time.time(),
        }

    def _sleep_stage_for_latest(self, radar_online, heart_rate, breath_rate):
        if not radar_online:
            return "雷达离线"
        if self.snore_detected or self.snore_score >= 0.65:
            return "疑似呼噜扰动"
        if heart_rate is None or breath_rate is None:
            return "等待生命体征"
        if self.vitals_state == "recovering":
            return "信号恢复中"
        return "实时监测中"

    @staticmethod
    def _is_finite_number(value):
        return isinstance(value, (int, float)) and math.isfinite(float(value))

    @staticmethod
    def _calibrate_environment_temperature(raw_temperature_c):
        if raw_temperature_c is None:
            return None
        temperature = float(raw_temperature_c) + ENV_TEMPERATURE_OFFSET_C
        temperature = max(ENV_TEMPERATURE_MIN_C, min(ENV_TEMPERATURE_MAX_C, temperature))
        return round(temperature, 1)

    def _target_distance_value(self):
        return self.target_bin * RANGE_RESOLUTION if self.target_bin is not None else None

    def _target_usable_for_vitals(self):
        distance = self._target_distance_value()
        return distance is not None and PRESENCE_DISTANCE_MIN_M <= float(distance) <= PRESENCE_DISTANCE_MAX_M

    def _presence_debug_state(self):
        if hasattr(self.presence_detector, "get_debug_state"):
            return self.presence_detector.get_debug_state()
        return {
            "presence_signal": bool(self.presence_detected),
            "presence_energy_stable": bool(self.presence_stable),
            "presence_distance_stable": False,
            "presence_distance_span": None,
            "presence_distance": self._target_distance_value(),
            "presence_distance_min_m": PRESENCE_DISTANCE_MIN_M,
            "presence_distance_max_m": PRESENCE_DISTANCE_MAX_M,
            "presence_distance_stability_span_m": PRESENCE_DISTANCE_STABILITY_SPAN_M,
            "presence_detection_value": None,
            "presence_detection_threshold": 1.01,
            "presence_detection_bin": None,
            "presence_below_threshold": False,
            "presence_stable": bool(self.presence_stable),
        }

    def _valid_heart_value(self, value):
        return self._is_finite_number(value) and 35.0 <= float(value) <= 180.0

    def _valid_breath_value(self, value):
        return self._is_finite_number(value) and 4.0 <= float(value) <= 40.0

    def _vitals_hold_available(self, now=None):
        if not self._radar_board_online() or not self._target_usable_for_vitals():
            return False
        if self.last_valid_vitals_time is None:
            return False
        age = (time.time() if now is None else float(now)) - float(self.last_valid_vitals_time)
        return 0.0 <= age <= VITALS_HOLD_SECONDS

    def _refresh_valid_vitals_cache(self, now=None):
        now = time.time() if now is None else float(now)
        updated = False
        if self.heart_rate_fresh and self._valid_heart_value(self.heart_rate):
            self.last_valid_heart_rate = float(self.heart_rate)
            updated = True
        if self.breath_rate_fresh and self._valid_breath_value(self.breath_rate):
            self.last_valid_breath_rate = float(self.breath_rate)
            self.last_valid_breath_quality = max(0.0, min(1.0, float(self.breath_rate_quality or 0.0)))
            updated = True
        if updated:
            self.last_valid_vitals_time = now
            self.last_valid_vitals_at = datetime.fromtimestamp(now).isoformat(timespec="seconds")

    def _apply_vitals_hold_or_loss(self, now=None):
        now = time.time() if now is None else float(now)
        self.vitals_missing_count += 1
        self.heart_rate_fresh = False
        self.breath_rate_fresh = False
        if self._vitals_hold_available(now):
            if self.last_valid_heart_rate is not None:
                self.heart_rate = self.last_valid_heart_rate
            if self.last_valid_breath_rate is not None:
                self.breath_rate = self.last_valid_breath_rate
                self.breath_rate_quality = round(max(0.0, min(1.0, self.last_valid_breath_quality)) * 0.65, 3)
            self.vitals_state = "recovering"
            return
        self.heart_rate = None
        self.breath_rate = None
        self.breath_rate_quality = 0.0
        self.model_prediction = None
        self.vitals_state = "lost"

    def _finalize_vitals_window(self):
        heart_fresh = bool(self.heart_rate_fresh and self._valid_heart_value(self.heart_rate))
        breath_fresh = bool(self.breath_rate_fresh and self._valid_breath_value(self.breath_rate))
        self._refresh_valid_vitals_cache()
        if heart_fresh and breath_fresh:
            self.vitals_missing_count = 0
            self.vitals_state = "fresh"
            return
        if self._valid_heart_value(self.heart_rate) and self._valid_breath_value(self.breath_rate):
            # One of the values may be retained from the previous valid window.
            self._apply_vitals_hold_or_loss()
            self.heart_rate_fresh = heart_fresh
            self.breath_rate_fresh = breath_fresh
            return
        self._apply_vitals_hold_or_loss()
        self.heart_rate_fresh = heart_fresh and self.vitals_state != "lost"
        self.breath_rate_fresh = breath_fresh and self.vitals_state != "lost"

    def _vitals_age_seconds(self):
        if self.last_valid_vitals_time is None:
            return None
        return self._seconds_since(self.last_valid_vitals_time)

    def _update_breath_rate_estimate(self, raw_breath_rate, quality=0.0):
        """平滑雷达呼吸率，降低单窗 FFT 抖动对前端和事件规则的影响。"""
        if raw_breath_rate is None or not isinstance(raw_breath_rate, (int, float)):
            self._breath_rate_missing_count += 1
            self.breath_rate_fresh = False
            self.breath_rate_quality = round(max(0.0, float(self.breath_rate_quality or 0.0) * 0.75), 3)
            return self.breath_rate

        raw = float(raw_breath_rate)
        quality = max(0.0, min(1.0, float(quality or 0.0)))
        if not 6.0 <= raw <= 30.0:
            self._breath_rate_missing_count += 1
            self.breath_rate_fresh = False
            self.breath_rate_quality = round(max(0.0, float(self.breath_rate_quality or 0.0) * 0.75), 3)
            return self.breath_rate

        if self.breath_rate is not None:
            jump = abs(raw - float(self.breath_rate))
            if jump > 7.0 and quality < 0.70:
                self._breath_rate_missing_count += 1
                self.breath_rate_fresh = False
                return self.breath_rate

        self._breath_rate_missing_count = 0
        self._breath_rate_history.append(raw)
        median_rate = float(np.median(list(self._breath_rate_history)))
        if self.breath_rate is None:
            smoothed = median_rate
        else:
            alpha = 0.50 if quality >= 0.75 else 0.28
            smoothed = float(self.breath_rate) * (1.0 - alpha) + median_rate * alpha
        self.breath_rate = round(smoothed, 2)
        self.breath_rate_quality = round(quality, 3)
        self.breath_rate_fresh = True
        return self.breath_rate

    @staticmethod
    def _snore_level_from_dbfs(dbfs, score):
        if dbfs is None:
            return max(0.0, min(1.0, score)) if score > 0 else None
        return round(max(0.0, min(1.0, (float(dbfs) + 45.0) / 33.0)), 3)

    @staticmethod
    def _estimate_dbfs(raw_audio):
        if len(raw_audio) < 2:
            return None
        sample_count = len(raw_audio) // 2
        total = 0.0
        for idx in range(sample_count):
            sample = int.from_bytes(raw_audio[idx * 2:idx * 2 + 2], "little", signed=True)
            total += sample * sample
        rms = math.sqrt(total / sample_count)
        return round(20.0 * math.log10(rms / 32768.0 + 1e-9), 2)

    @staticmethod
    def _save_raw_audio_as_wav(raw_audio, output_file):
        with wave.open(str(output_file), "wb") as wav_file:
            wav_file.setnchannels(NUM_CHANNELS)
            wav_file.setsampwidth(SAMPLE_WIDTH)
            wav_file.setframerate(SAMPLE_RATE)
            wav_file.writeframes(raw_audio)
        return len(raw_audio) / float(SAMPLE_RATE * SAMPLE_WIDTH * NUM_CHANNELS)

    @staticmethod
    def _snore_sound_present(snore_detected, score, dbfs):
        """判定当前心跳是否为真实呼噜。

        这里故意只认小智/Edgi 模型上报的 snore_detected=True。
        snore_score 和 dbfs 仍用于展示与强度评估，但不能单独武装
        “呼噜停止 + 呼吸下降”融合报警，避免环境噪声导致误报。
        """
        return bool(snore_detected)

    def _snore_presence_bypass_active(self, now=None):
        """呼噜响起及停止确认窗口内关闭存在性检测，避免门控干扰融合报警。"""
        if self.snore_sound_active:
            return True
        try:
            current = float(now if now is not None else time.time())
        except (TypeError, ValueError):
            return False
        for mark in (self.last_snore_sound_time,):
            if mark is None:
                continue
            try:
                age = current - float(mark)
            except (TypeError, ValueError):
                continue
            if 0.0 <= age <= SNORE_PRESENCE_BYPASS_SECONDS:
                return True
        return False

    @staticmethod
    def _is_night_absence_window(timestamp=None):
        current = float(timestamp if timestamp is not None else time.time())
        hour = datetime.fromtimestamp(current).hour
        if NIGHT_ABSENCE_START_HOUR <= NIGHT_ABSENCE_END_HOUR:
            return NIGHT_ABSENCE_START_HOUR <= hour < NIGHT_ABSENCE_END_HOUR
        return hour >= NIGHT_ABSENCE_START_HOUR or hour < NIGHT_ABSENCE_END_HOUR

    def _record_night_absence_alarm(self, now, absent_seconds, presence_debug):
        bed_id = self.current_radar_bed_id or DEFAULT_BED_ID
        existing = next(
            (
                event for event in self.emergency_events
                if event.get("type") == "night_absence"
                and event.get("status", "active") == "active"
                and event.get("bed_id", DEFAULT_BED_ID) == bed_id
            ),
            None,
        )
        if existing is not None:
            return existing

        cooldown_age = self._seconds_since(self.last_night_absence_alarm_time)
        if cooldown_age is not None and cooldown_age < NIGHT_ABSENCE_ALARM_COOLDOWN_SECONDS:
            return None

        now_text = datetime.fromtimestamp(now).isoformat(timespec="seconds")
        started_at = self.presence_absent_started_at or now_text
        fingerprint_seed = f"night_absence:{bed_id}:{started_at[:13]}"
        fingerprint = "night_absence:" + hashlib.sha1(fingerprint_seed.encode("utf-8")).hexdigest()[:16]
        event = {
            "eventID": int(now * 1000),
            "userID": None,
            "bed_id": bed_id,
            "type": "night_absence",
            "severity": "critical",
            "title": "夜间疑似离床",
            "message": "夜间存在性检测连续超过 1 小时未检测到病人在床，请立即确认。",
            "timestamp": now_text,
            "source": "radar_presence",
            "score_delta": -28,
            "details": {
                "absent_started_at": started_at,
                "absent_seconds": round(float(absent_seconds), 1),
                "alarm_after_seconds": NIGHT_ABSENCE_ALARM_SECONDS,
                "night_window": f"{NIGHT_ABSENCE_START_HOUR:02d}:00-{NIGHT_ABSENCE_END_HOUR:02d}:00",
                "presence": dict(presence_debug or {}),
                "snore_presence_bypassed": bool(self.presence_bypassed_by_snore),
            },
            "fingerprint": fingerprint,
            "status": "active",
            "resolved_at": None,
            "resolution_note": None,
            "resolved_by": None,
        }
        if not any(item.get("fingerprint") == fingerprint for item in self.emergency_events):
            self.emergency_events.append(event)
            self.emergency_events = self.emergency_events[-120:]
        self.last_night_absence_alarm_time = now
        self.last_night_absence_alarm_at = now_text
        return event

    def _update_night_absence_monitor(self, now=None):
        current = float(now if now is not None else time.time())
        in_night = self._is_night_absence_window(current)
        radar_online = self._radar_board_online() or self._radar_data_online()
        presence_debug = self._presence_debug_state()
        snore_bypass = bool(self.presence_bypassed_by_snore or self._snore_presence_bypass_active(current))
        monitoring = bool(ENABLE_PRESENCE_DETECTION and radar_online and in_night and not snore_bypass)
        absent = bool(monitoring and not self.presence_stable)

        if absent:
            if self.presence_absent_started_time is None:
                self.presence_absent_started_time = current
                self.presence_absent_started_at = datetime.fromtimestamp(current).isoformat(timespec="seconds")
            absent_seconds = max(0.0, current - float(self.presence_absent_started_time))
            reason = "absent_counting"
            if absent_seconds >= NIGHT_ABSENCE_ALARM_SECONDS:
                self._record_night_absence_alarm(current, absent_seconds, presence_debug)
                reason = "alarm_active"
        else:
            absent_seconds = 0.0
            reason = "present"
            if not radar_online:
                reason = "radar_offline"
            elif not in_night:
                reason = "outside_night_window"
            elif snore_bypass:
                reason = "snore_presence_bypass"
            elif not ENABLE_PRESENCE_DETECTION:
                reason = "presence_disabled"
            self.presence_absent_started_time = None
            self.presence_absent_started_at = None

        self.night_absence_debug = {
            "monitoring": monitoring,
            "in_night_window": in_night,
            "absent": absent,
            "absent_started_at": self.presence_absent_started_at,
            "absent_seconds": round(float(absent_seconds), 2),
            "alarm_after_seconds": NIGHT_ABSENCE_ALARM_SECONDS,
            "last_alarm_at": self.last_night_absence_alarm_at,
            "reason": reason,
        }
        return self.night_absence_debug

    def _breath_signal_descent_snapshot(self):
        """返回当前雷达呼吸相位波形是否处于下降段。"""
        if self.phase_values is None:
            return {
                "descending": False,
                "reason": "no_phase_signal",
            }

        values = np.asarray(self.phase_values, dtype=float)
        values = values[np.isfinite(values)]
        min_points = int(max(FRAME_RATE * BREATH_DESCENT_WINDOW_SECONDS, FRAME_RATE))
        if values.size < min_points:
            return {
                "descending": False,
                "reason": "not_enough_phase_points",
                "points": int(values.size),
            }

        window_points = min(values.size, int(FRAME_RATE * BREATH_DESCENT_WINDOW_SECONDS))
        compare_points = max(3, int(FRAME_RATE * BREATH_DESCENT_COMPARE_SECONDS))
        if window_points < compare_points * 2:
            return {
                "descending": False,
                "reason": "not_enough_compare_points",
                "points": int(values.size),
            }

        segment = signal.detrend(values[-window_points:])
        try:
            sos = signal.butter(3, (0.1, 0.5), btype="bandpass", fs=FRAME_RATE, output="sos")
            segment = signal.sosfiltfilt(sos, segment)
        except ValueError:
            # 数据点不足以 filtfilt 时退回到去趋势后的相位波形。
            pass

        previous_mean = float(np.mean(segment[-compare_points * 2:-compare_points]))
        recent_mean = float(np.mean(segment[-compare_points:]))
        delta = recent_mean - previous_mean
        x = np.arange(segment.size, dtype=float)
        slope = float(np.polyfit(x, segment, 1)[0]) if segment.size >= 2 else 0.0
        noise = float(np.std(segment))
        threshold = max(1e-4, noise * 0.08)
        descending = bool(delta <= -threshold*0.7 or (delta < 0.0 and slope < 0.0))

        return {
            "descending": descending,
            "reason": "ok",
            "window_seconds": BREATH_DESCENT_WINDOW_SECONDS,
            "compare_seconds": BREATH_DESCENT_COMPARE_SECONDS,
            "previous_mean": round(previous_mean, 6),
            "recent_mean": round(recent_mean, 6),
            "delta": round(float(delta), 6),
            "slope": round(float(slope), 8),
            "threshold": round(float(threshold), 6),
            "breath_rate": float(self.breath_rate) if self.breath_rate is not None else None,
            "breath_quality": self.breath_rate_quality,
            "target_bin": int(self.target_bin) if self.target_bin is not None else None,
            "target_distance": float(self.target_bin * RANGE_RESOLUTION) if self.target_bin is not None else None,
        }

    def _presence_signal_below_threshold_snapshot(self):
        """Return whether the radar presence/breath energy ratio is below the presence threshold."""
        presence_debug = self._presence_debug_state()
        value = presence_debug.get("presence_detection_value")
        threshold = presence_debug.get("presence_detection_threshold")
        if not self._is_finite_number(value) or not self._is_finite_number(threshold):
            return {
                "below_threshold": False,
                "reason": "missing_presence_detection_value",
                "presence_detection_value": value,
                "presence_detection_threshold": threshold,
                "presence_detection_bin": presence_debug.get("presence_detection_bin"),
                "target_bin": int(self.target_bin) if self.target_bin is not None else None,
                "target_distance": float(self.target_bin * RANGE_RESOLUTION) if self.target_bin is not None else None,
            }

        below_threshold = float(value) < float(threshold)
        return {
            "below_threshold": bool(below_threshold),
            "reason": "ok",
            "presence_detection_value": round(float(value), 4),
            "presence_detection_threshold": round(float(threshold), 4),
            "presence_detection_bin": presence_debug.get("presence_detection_bin"),
            "presence_distance_stable": bool(presence_debug.get("presence_distance_stable")),
            "presence_distance_span": presence_debug.get("presence_distance_span"),
            "presence_bypassed_by_snore": bool(self.presence_bypassed_by_snore),
            "breath_rate": float(self.breath_rate) if self.breath_rate is not None else None,
            "breath_quality": self.breath_rate_quality,
            "breath_periodicity": self.breath_periodicity,
            "target_bin": int(self.target_bin) if self.target_bin is not None else None,
            "target_distance": float(self.target_bin * RANGE_RESOLUTION) if self.target_bin is not None else None,
        }

    def _record_snore_stop_breath_drop_alarm(self, stop_time, silence_seconds, score, dbfs, breath_snapshot, source):
        now_text = datetime.fromtimestamp(stop_time).isoformat(timespec="seconds")
        cooldown_age = self._seconds_since(self.last_snore_stop_alarm_time)
        if cooldown_age is not None and cooldown_age < SNORE_STOP_ALARM_COOLDOWN_SECONDS:
            return None

        minute_bucket = datetime.fromtimestamp(stop_time).strftime("%Y-%m-%dT%H:%M:%S")
        fingerprint_seed = (
            f"snore_stop_presence_threshold:{source}:{minute_bucket}:"
            f"{breath_snapshot.get('target_bin')}:{round(float(silence_seconds), 1)}:"
            f"{breath_snapshot.get('presence_detection_value')}:{breath_snapshot.get('presence_detection_threshold')}"
        )
        fingerprint = "snore_stop_breath_drop:" + hashlib.sha1(fingerprint_seed.encode("utf-8")).hexdigest()[:16]
        event = {
            "eventID": int(stop_time * 1000),
            "userID": None,
            "type": "snore_stop_breath_drop",
            "severity": "critical",
            "title": "疑似呼吸暂停",
            "message": f"检测到呼噜声音消失约 {silence_seconds:.1f} 秒，同时雷达呼吸/存在性信号跌破存在性检测阈值，建议立即观察。",
            "timestamp": now_text,
            "source": source or "real_snore_board",
            "score_delta": -24,
            "details": {
                "silence_seconds": round(float(silence_seconds), 2),
                "snore_score": round(float(score or 0.0), 3),
                "snore_dbfs": float(dbfs) if dbfs is not None else None,
                "last_snore_sound_at": self.last_snore_sound_at,
                "breath_signal": breath_snapshot,
            },
            "fingerprint": fingerprint,
            "status": "active",
            "resolved_at": None,
            "resolution_note": None,
            "resolved_by": None,
        }
        if not any(item.get("fingerprint") == fingerprint for item in self.emergency_events):
            self.emergency_events.append(event)
            self.emergency_events = self.emergency_events[-120:]
            self.snore_stop_breath_alarm_count += 1
            self.last_snore_stop_alarm_time = stop_time
        return event

    def _update_snore_sound_state(self, sound_present, now, score, dbfs, source):
        now_text = datetime.fromtimestamp(now).isoformat(timespec="seconds")
        event = None

        if sound_present:
            if not self.snore_sound_active:
                self.snore_sound_started_time = now
                self.snore_sound_started_at = now_text
            self.snore_sound_active = True
            self.last_snore_sound_time = now
            self.last_snore_sound_at = now_text
            self.last_snore_stop_fusion = {
                "state": "sound_present",
                "timestamp": now_text,
                "sound_present": True,
            }
            return event

        silence_seconds = self._seconds_since(self.last_snore_sound_time)
        should_stop = bool(
            self.snore_sound_active and
            silence_seconds is not None and
            silence_seconds >= SNORE_SOUND_STOP_SECONDS
        )
        if not should_stop:
            self.last_snore_stop_fusion = {
                "state": "waiting_for_silence",
                "timestamp": now_text,
                "sound_present": False,
                "silence_seconds": round(float(silence_seconds), 2) if silence_seconds is not None else None,
                "stop_threshold_seconds": SNORE_SOUND_STOP_SECONDS,
            }
            return event

        self.snore_sound_active = False
        self.last_snore_sound_stop_time = now
        self.last_snore_sound_stop_at = now_text
        breath_snapshot = self._presence_signal_below_threshold_snapshot()
        self.last_snore_stop_fusion = {
            "state": "stopped",
            "timestamp": now_text,
            "sound_present": False,
            "silence_seconds": round(float(silence_seconds), 2),
            "stop_threshold_seconds": SNORE_SOUND_STOP_SECONDS,
            "breath_signal_descending": False,
            "breath_signal_below_presence_threshold": bool(breath_snapshot.get("below_threshold")),
            "breath_signal": breath_snapshot,
        }

        if breath_snapshot.get("below_threshold"):
            snore_duration = self._seconds_since(self.snore_sound_started_time)
            if snore_duration is not None and snore_duration < SNORE_MIN_DURATION_FOR_ALARM:
                self.last_snore_stop_fusion["alarm_triggered"] = False
                self.last_snore_stop_fusion["alarm_skipped_reason"] = (
                    f"snore_too_short ({snore_duration:.1f}s < {SNORE_MIN_DURATION_FOR_ALARM:.0f}s)"
                )
                return event
            event = self._record_snore_stop_breath_drop_alarm(
                now,
                silence_seconds,
                score,
                dbfs,
                breath_snapshot,
                source,
            )
            self.last_snore_stop_fusion["alarm_triggered"] = event is not None
            if event is not None:
                print(
                    f">> 呼噜停止+存在性阈值跌破报警: silence={silence_seconds:.2f}s, "
                    f"presence={breath_snapshot.get('presence_detection_value')}, "
                    f"threshold={breath_snapshot.get('presence_detection_threshold')}"
                )
        else:
            self.last_snore_stop_fusion["alarm_triggered"] = False
        return event

    def _timeline_entry(self, timestamp=None):
        radar_online = self._radar_board_online()
        snore_online = self._snore_board_online()
        target_distance = self.target_bin * RANGE_RESOLUTION if self.target_bin is not None else 0.0
        heart_rate = float(self.heart_rate) if self.heart_rate is not None else None
        breath_rate = float(self.breath_rate) if self.breath_rate is not None else None
        vitals_age = self._vitals_age_seconds()
        snore_score = round(float(self.snore_score or 0.0), 3) if snore_online else 0.0
        snore_dbfs = self.snore_dbfs if snore_online else None
        snore_level = self._snore_level_from_dbfs(snore_dbfs, snore_score) if snore_online else None
        snore_detected = bool(self.snore_detected) if snore_online else False
        env = self._environment_snapshot()
        presence_debug = self._presence_debug_state()
        return {
            "timestamp": timestamp or self._now_iso(),
            "bed_id": self.current_radar_bed_id or DEFAULT_BED_ID,
            "heart_rate": heart_rate if radar_online else None,
            "breath_rate": breath_rate if radar_online else None,
            "breath_quality": self.breath_rate_quality if radar_online else 0.0,
            "breath_periodicity": self.breath_periodicity if radar_online else 0.0,
            "heart_rate_fresh": bool(self.heart_rate_fresh) if radar_online else False,
            "breath_rate_fresh": bool(self.breath_rate_fresh) if radar_online else False,
            "vitals_state": self.vitals_state if radar_online else "lost",
            "vitals_age_seconds": round(vitals_age, 2) if vitals_age is not None else None,
            "last_valid_vitals_at": self.last_valid_vitals_at,
            "target_distance": float(target_distance) if radar_online else 0.0,
            "target_bin": int(self.target_bin) if self.target_bin is not None else None,
            "radar_online": radar_online,
            "radar_board_stationary": bool(self.radar_board_stationary),
            "presence_detected": bool(self.presence_detected) if radar_online else False,
            "presence_signal": bool(presence_debug.get("presence_signal")) if radar_online else False,
            "presence_energy_stable": bool(presence_debug.get("presence_energy_stable")) if radar_online else False,
            "presence_distance_stable": bool(presence_debug.get("presence_distance_stable")) if radar_online else False,
            "presence_distance_span": presence_debug.get("presence_distance_span") if radar_online else None,
            "presence_distance": presence_debug.get("presence_distance") if radar_online else None,
            "presence_distance_min_m": PRESENCE_DISTANCE_MIN_M,
            "presence_distance_max_m": PRESENCE_DISTANCE_MAX_M,
            "presence_distance_stability_span_m": PRESENCE_DISTANCE_STABILITY_SPAN_M,
            "presence_detection_value": presence_debug.get("presence_detection_value") if radar_online else None,
            "presence_detection_threshold": presence_debug.get("presence_detection_threshold") if radar_online else None,
            "presence_detection_bin": presence_debug.get("presence_detection_bin") if radar_online else None,
            "presence_below_threshold": bool(presence_debug.get("presence_below_threshold")) if radar_online else False,
            "presence_stable": bool(self.presence_stable) if radar_online else False,
            "presence_bypassed_by_snore": bool(self.presence_bypassed_by_snore) if radar_online else False,
            "snore_online": snore_online,
            "snore_score": snore_score,
            "snore_dbfs": snore_dbfs,
            "snore_level": snore_level,
            "snore_detected": snore_detected,
            "environment_online": env["environment_online"],
            "environment_board_online": env["environment_board_online"],
            "temperature_c": env["temperature_c"],
            "raw_temperature_c": env["raw_temperature_c"],
            "temperature_offset_c": env["temperature_offset_c"],
            "humidity_pct": env["humidity_pct"],
            "comfort_status": env["comfort_status"],
            "sleep_stage": self._sleep_stage_for_latest(radar_online, heart_rate, breath_rate),
        }

    def _trim_timeline_unlocked(self):
        cutoff = time.time() - TIMELINE_RETENTION_SECONDS
        self.timeline = [
            row for row in self.timeline
            if self._parse_iso_seconds(row.get("timestamp")) >= cutoff
        ]

    @staticmethod
    def _parse_iso_seconds(value):
        if not value:
            return 0.0
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
        except ValueError:
            return 0.0

    def _upsert_timeline(self):
        with self.state_lock:
            entry = self._timeline_entry()
            if self.timeline and self.timeline[-1].get("timestamp") == entry["timestamp"]:
                self.timeline[-1] = entry
            else:
                self.timeline.append(entry)
            self._trim_timeline_unlocked()

    @staticmethod
    def _timeline_summary(rows):
        valid_hr = [row["heart_rate"] for row in rows if isinstance(row.get("heart_rate"), (int, float))]
        valid_br = [row["breath_rate"] for row in rows if isinstance(row.get("breath_rate"), (int, float))]
        snore_levels = [row["snore_level"] for row in rows if isinstance(row.get("snore_level"), (int, float))]
        snore_rows = [row for row in rows if row.get("snore_detected")]
        temperatures = [row["temperature_c"] for row in rows if isinstance(row.get("temperature_c"), (int, float))]
        humidities = [row["humidity_pct"] for row in rows if isinstance(row.get("humidity_pct"), (int, float))]
        latest = rows[-1] if rows else {}
        return {
            "points": len(rows),
            "valid_heart_points": len(valid_hr),
            "valid_breath_points": len(valid_br),
            "valid_environment_points": len(temperatures),
            "snore_event_count": len(snore_rows),
            "avg_snore_level": round(float(np.mean(snore_levels)), 3) if snore_levels else None,
            "latest_sleep_stage": latest.get("sleep_stage", "等待数据"),
            "latest_timestamp": latest.get("timestamp"),
            "avg_heart_rate": round(float(np.mean(valid_hr)), 2) if valid_hr else None,
            "avg_breath_rate": round(float(np.mean(valid_br)), 2) if valid_br else None,
            "avg_temperature_c": round(float(np.mean(temperatures)), 2) if temperatures else None,
            "avg_humidity_pct": round(float(np.mean(humidities)), 2) if humidities else None,
            "latest_comfort_status": latest.get("comfort_status", "offline"),
        }

    # ===== sleep overview 聚合辅助方法 =====

    @staticmethod
    def _numeric_values(rows, key):
        values = []
        for row in rows:
            value = row.get(key)
            if isinstance(value, (int, float)):
                values.append(float(value))
        return values

    @staticmethod
    def _average(values):
        return round(sum(values) / len(values), 3) if values else None

    @staticmethod
    def _standard_deviation(values):
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        return round(math.sqrt(variance), 3)

    @staticmethod
    def _minute_key(timestamp):
        return (timestamp or "")[:16]

    @staticmethod
    def _minute_label(timestamp):
        try:
            return datetime.fromisoformat(timestamp).strftime("%H:%M")
        except (ValueError, TypeError):
            return (timestamp or "")[-5:] or "--:--"

    @staticmethod
    def _severity_rank(severity):
        return {"info": 0, "normal": 1, "warning": 2, "critical": 3}.get(severity, 0)

    def _rows_between(self, rows, start_ts):
        return [
            row
            for row in rows
            if (self._parse_iso_seconds(row.get("timestamp", "")) or 0.0) >= start_ts
        ]

    def _record_emergency_event(self, payload):
        timestamp = payload.timestamp or self._now_iso()
        phrase = (payload.phrase or "").strip()
        transcript = (payload.transcript or "").strip()
        source = (payload.source or "xiaozhi_voice_board").strip() or "xiaozhi_voice_board"
        bed_id = self._resolve_runtime_bed_id(
            bed_id=getattr(payload, "bed_id", None),
            device_id=getattr(payload, "device_id", None),
            source=source,
        )
        display_text = transcript or phrase or "未提供文本"
        raw_type = (
            getattr(payload, "event_type", None) or
            getattr(payload, "type", None) or
            ""
        ).strip().lower()
        text_for_type = f"{raw_type} {source} {phrase} {transcript}".lower()
        is_fall = any(token in text_for_type for token in ("fall", "摇晃", "跌倒", "摔倒"))
        event_type = "board_fall" if is_fall else (raw_type or "emergency_voice")
        voice_type_aliases = {"voice", "sos", "help", "emergency", "emergency_help", "emergency_voice"}
        if event_type in voice_type_aliases:
            event_type = "emergency_voice"
        if event_type in {"fall", "emergency_fall", "device_fall", "board_drop"}:
            event_type = "board_fall"
        details = dict(payload.details or {})
        if event_type == "emergency_voice":
            voice_evidence = [
                phrase,
                transcript,
                (payload.title or "").strip(),
                (payload.message or "").strip(),
                str(details.get("phrase") or "").strip(),
                str(details.get("transcript") or "").strip(),
                str(details.get("message") or "").strip(),
            ]
            explicit_voice_type = raw_type in voice_type_aliases
            if not explicit_voice_type and not any(voice_evidence):
                with self.state_lock:
                    self.last_voice_received_time = time.time()
                    self.last_voice_received_at = timestamp
                    self.last_edgi_heartbeat_time = time.time()
                    self.last_edgi_heartbeat_at = timestamp
                    self.last_edgi_bed_id = bed_id
                return {
                    "status": "ignored",
                    "reason": "empty_emergency_voice",
                    "message": "Empty /emergency payload was treated as heartbeat only.",
                    "event_type": event_type,
                    "timestamp": timestamp,
                }

        default_title = "开发板摇晃报警" if event_type == "board_fall" else "语音紧急求助"
        default_message = (
            "开发板检测到疑似摇晃，请立即确认佩戴者和设备状态。"
            if event_type == "board_fall"
            else f"小智检测到求助语音：“{display_text}”"
        )
        severity = (payload.severity or "critical").strip().lower()
        if severity not in {"info", "normal", "warning", "critical"}:
            severity = "critical"
        details.update({
            "phrase": phrase or None,
            "transcript": transcript or None,
            "device_id": payload.device_id,
        })
        fingerprint_seed = f"{timestamp}:{source}:{event_type}:{phrase}:{transcript}:{payload.device_id or ''}:{payload.message or ''}"
        fingerprint = f"{event_type}:" + hashlib.sha1(fingerprint_seed.encode("utf-8")).hexdigest()[:16]
        event = {
            "eventID": int(time.time() * 1000),
            "userID": None,
            "bed_id": bed_id,
            "type": event_type,
            "severity": severity,
            "title": (payload.title or default_title).strip(),
            "message": (payload.message or default_message).strip(),
            "timestamp": timestamp,
            "source": source,
            "score_delta": -30,
            "details": details,
            "fingerprint": fingerprint,
            "status": "active",
            "resolved_at": None,
            "resolution_note": None,
            "resolved_by": None,
        }
        with self.state_lock:
            if not any(item.get("fingerprint") == fingerprint for item in self.emergency_events):
                self.emergency_events.append(event)
                self.emergency_events = self.emergency_events[-120:]
            self.last_voice_received_time = time.time()
            self.last_voice_received_at = timestamp
            self.last_edgi_heartbeat_time = time.time()
            self.last_edgi_heartbeat_at = timestamp
            self.last_edgi_bed_id = bed_id
        return {
            "status": "success",
            "event_id": event["eventID"],
            "event_type": event_type,
            "severity": severity,
            "timestamp": timestamp,
        }

    def _record_demo_apnea_event(self, payload):
        """Create a deterministic suspected-apnea event for competition demos.

        The production apnea fusion rule stays conservative to avoid false alarms.
        This endpoint only gives the demo operator a reliable way to exercise the
        same frontend/backend alarm path when the live breath-hold window misses.
        """
        now = time.time()
        timestamp = self._now_iso()
        source = (payload.source or "frontend_demo").strip() or "frontend_demo"
        bed_id = self._resolve_runtime_bed_id(bed_id=getattr(payload, "bed_id", None), source=source)
        duration = float(payload.duration_seconds or 8.0)
        duration = max(3.0, min(duration, 30.0))
        fingerprint_seed = f"demo_apnea:{source}:{int(now * 1000)}"
        fingerprint = "suspected_apnea_demo:" + hashlib.sha1(fingerprint_seed.encode("utf-8")).hexdigest()[:16]
        event = {
            "eventID": int(now * 1000),
            "userID": None,
            "bed_id": bed_id,
            "type": "suspected_apnea",
            "severity": "critical",
            "title": "疑似呼吸暂停",
            "message": "呼噜停止后出现人工确认的屏息/呼吸暂停风险，请立即观察。",
            "timestamp": timestamp,
            "source": source,
            "score_delta": -30,
            "details": {
                "demo": True,
                "trigger": "manual_demo",
                "duration_seconds": round(duration, 1),
                "confidence": 0.98,
                "note": (payload.note or "").strip() or None,
                "heart_rate": float(self.heart_rate) if self.heart_rate is not None else None,
                "breath_rate": float(self.breath_rate) if self.breath_rate is not None else None,
                "breath_quality": self.breath_rate_quality,
                "snore_detected": bool(self.snore_detected),
                "last_snore_sound_at": self.last_snore_sound_at,
                "target_bin": int(self.target_bin) if self.target_bin is not None else None,
                "target_distance": float(self.target_bin * RANGE_RESOLUTION) if self.target_bin is not None else None,
            },
            "fingerprint": fingerprint,
            "status": "active",
            "resolved_at": None,
            "resolution_note": None,
            "resolved_by": None,
        }
        with self.state_lock:
            self.emergency_events.append(event)
            self.emergency_events = self.emergency_events[-120:]
        return {
            "status": "success",
            "event_id": event["eventID"],
            "event_type": "suspected_apnea",
            "severity": "critical",
            "timestamp": timestamp,
        }

    def _resolve_emergency_event(self, payload):
        source = (payload.source or "xiaozhi_voice_board").strip() or "xiaozhi_voice_board"
        bed_id = self._resolve_runtime_bed_id(
            bed_id=getattr(payload, "bed_id", None),
            device_id=getattr(payload, "device_id", None),
            source=source,
        )
        resolved_at = self._now_iso()
        note = (payload.resolution_note or "已在开发板确认并解除紧急状态").strip()
        resolved_by = (payload.resolved_by or source).strip() or source

        with self.state_lock:
            candidates = [
                event
                for event in self.emergency_events
                if event.get("status", "active") == "active"
                and (
                    event.get("eventID") == payload.event_id
                    if payload.event_id is not None
                    else event.get("source") == source
                )
                and self._event_belongs_to_bed(event, bed_id)
            ]
            if not candidates:
                return {"status": "not_found", "message": "没有待处理的紧急事件"}
            event = max(candidates, key=lambda item: item.get("timestamp", ""))
            event["status"] = "resolved"
            event["resolved_at"] = resolved_at
            event["resolution_note"] = note
            event["resolved_by"] = resolved_by

        return {
            "status": "success",
            "event_id": event["eventID"],
            "event_status": "resolved",
            "resolved_at": resolved_at,
        }

    def _emergency_events_between(self, start_ts=None, bed_id=None):
        with self.state_lock:
            events = list(self.emergency_events)
        if bed_id is not None:
            events = [event for event in events if self._event_belongs_to_bed(event, bed_id)]
        if start_ts is None:
            return events
        return [
            event
            for event in events
            if (self._parse_iso_seconds(event.get("timestamp", "")) or 0.0) >= start_ts
            or event.get("status", "active") == "active"
        ]

    def _emergency_sync_snapshot(self, bed_id=None):
        resolved_bed_id = self._resolve_runtime_bed_id(bed_id=bed_id)
        active_event = self._active_emergency_event(resolved_bed_id)
        return {
            "status": "success",
            "bed_id": resolved_bed_id,
            "emergency_active": active_event is not None,
            "active_emergency": active_event,
            "event_id": active_event.get("eventID") if active_event else None,
            "event_type": active_event.get("type") if active_event else None,
            "event_status": active_event.get("status", "active") if active_event else "none",
            "title": active_event.get("title") if active_event else None,
            "message": active_event.get("message") if active_event else None,
            "source": active_event.get("source") if active_event else None,
            "timestamp": active_event.get("timestamp") if active_event else None,
            "server_time": self._now_iso(),
        }

    def _build_snore_heatmap(self, rows, events):
        """按分钟聚合呼噜强度 + 心率/呼吸变化，生成热力图。"""
        buckets: dict = {}
        for row in rows:
            key = self._minute_key(row.get("timestamp", ""))
            bucket = buckets.setdefault(
                key,
                {
                    "timestamp": f"{key}:00",
                    "label": self._minute_label(f"{key}:00"),
                    "snore_values": [],
                    "heart_values": [],
                    "breath_values": [],
                    "snore_events": 0,
                },
            )
            if isinstance(row.get("snore_level"), (int, float)):
                bucket["snore_values"].append(float(row["snore_level"]))
            if row.get("snore_detected"):
                bucket["snore_events"] += 1
            if isinstance(row.get("heart_rate"), (int, float)):
                bucket["heart_values"].append(float(row["heart_rate"]))
            if isinstance(row.get("breath_rate"), (int, float)):
                bucket["breath_values"].append(float(row["breath_rate"]))

        for event in events:
            if event.get("type") != "snore":
                continue
            key = self._minute_key(event.get("timestamp", ""))
            details = event.get("details") or {}
            bucket = buckets.setdefault(
                key,
                {
                    "timestamp": f"{key}:00",
                    "label": self._minute_label(f"{key}:00"),
                    "snore_values": [],
                    "heart_values": [],
                    "breath_values": [],
                    "snore_events": 0,
                },
            )
            level = details.get("snore_level")
            if isinstance(level, (int, float)):
                bucket["snore_values"].append(float(level))
            bucket["snore_events"] += 1

        result = []
        previous_hr = None
        previous_br = None
        for key in sorted(buckets):
            bucket = buckets[key]
            avg_snore = self._average(bucket["snore_values"]) or 0.0
            max_snore = max(bucket["snore_values"]) if bucket["snore_values"] else 0.0
            avg_hr = self._average(bucket["heart_values"])
            avg_br = self._average(bucket["breath_values"])
            heart_delta = round(avg_hr - previous_hr, 2) if (avg_hr is not None and previous_hr is not None) else None
            breath_delta = round(avg_br - previous_br, 2) if (avg_br is not None and previous_br is not None) else None
            if avg_hr is not None:
                previous_hr = avg_hr
            if avg_br is not None:
                previous_br = avg_br
            intensity = min(1.0, avg_snore * 0.82 + min(1.0, bucket["snore_events"] / 4.0) * 0.18)
            severity = "critical" if intensity >= 0.7 else "warning" if intensity >= 0.38 else "info"
            result.append(
                {
                    "timestamp": bucket["timestamp"],
                    "label": bucket["label"],
                    "avg_snore_level": round(avg_snore, 3),
                    "max_snore_level": round(max_snore, 3),
                    "snore_events": bucket["snore_events"],
                    "heart_delta": heart_delta,
                    "breath_delta": breath_delta,
                    "intensity": round(intensity, 3),
                    "severity": severity,
                }
            )
        return result[-90:]

    def _synthesize_sleep_events(self, rows):
        """从时间轴行中合成睡眠事件（与 realtime_radar_processing.py 的 record_sleep_events_locked 同等逻辑，
        但仅在内存中累积，不写 SQLite）。每个 (type, 分钟) 仅记录一次。"""
        events: list = []
        seen = set()
        radar_age = self._seconds_since(self.last_radar_received_time)
        environment_age = self._seconds_since(self.last_environment_heartbeat_time)
        edgi_age = self._seconds_since(self.last_edgi_heartbeat_time)
        edgi_online = self._edgi_board_online()

        def add(event_type, severity, title, message, timestamp, source, score_delta, details, fingerprint):
            if fingerprint in seen:
                return
            seen.add(fingerprint)
            events.append(
                {
                    "eventID": None,
                    "userID": None,
                    "type": event_type,
                    "severity": severity,
                    "title": title,
                    "message": message,
                    "timestamp": timestamp,
                    "source": source,
                    "score_delta": score_delta,
                    "details": details,
                }
            )

        previous_condition = "normal"
        for row in rows:
            timestamp = row.get("timestamp")
            if not timestamp:
                continue
            minute = self._minute_key(timestamp)
            heart_rate = row.get("heart_rate")
            breath_rate = row.get("breath_rate")
            snore_level = row.get("snore_level")
            comfort_status = row.get("comfort_status")
            target_distance = float(row.get("target_distance") or 0.0)
            radar_online_flag = bool(row.get("radar_online"))
            environment_online_flag = bool(row.get("environment_online"))
            environment_board_online = bool(row.get("environment_board_online"))
            radar_has_target = radar_online_flag and target_distance > 0

            condition = "normal"
            if not radar_online_flag:
                condition = "radar_offline"
                add(
                    "device_offline", "critical", "雷达板离线",
                    "毫米波雷达超过 5 秒未发送数据，心率和呼吸率会断线。",
                    timestamp, "radar_board", -18,
                    {"radar_age_seconds": radar_age},
                    f"device_offline:radar:{minute}",
                )
            elif not radar_has_target:
                condition = "no_person"
                add(
                    "no_person", "warning", "疑似离床 / 未检测到人体",
                    "雷达板在线，但目标距离为 0，当前未检测到稳定人体目标。",
                    timestamp, "radar_board", -14,
                    {"target_distance": target_distance},
                    f"no_person:{minute}",
                )

            if not edgi_online:
                if condition == "normal":
                    condition = "edgi_offline"
                add(
                    "device_offline", "warning", "Edgi E84 离线",
                    "开发板心跳中断，呼噜、语音与环境数据暂不可用。",
                    timestamp, "edgi_board", -10,
                    {"edgi_age_seconds": edgi_age},
                    f"device_offline:edgi:{minute}",
                )

            if edgi_online and environment_board_online and not environment_online_flag:
                if condition == "normal":
                    condition = "environment_sensor_error"
                add(
                    "sensor_error", "warning", "温湿度传感器异常",
                    "Edgi E84 在线，但 AHT20 当前没有提供有效读数。",
                    timestamp, "environment_board", -4,
                    {"environment_age_seconds": environment_age},
                    f"sensor_error:environment:{minute}",
                )
            elif comfort_status and comfort_status not in {"comfortable", "offline", "no_data", "sensor_error"}:
                severity = "critical" if str(comfort_status).endswith("_critical") else "warning"
                condition = "environment_uncomfortable"
                add(
                    "environment", severity, "睡眠环境不舒适",
                    f"当前温湿度状态为 {comfort_status}，建议检查房间温度、湿度或通风。",
                    timestamp, "environment_board",
                    -12 if severity == "critical" else -6,
                    {
                        "temperature_c": row.get("temperature_c"),
                        "humidity_pct": row.get("humidity_pct"),
                        "comfort_status": comfort_status,
                    },
                    f"environment:{minute}",
                )

            if isinstance(snore_level, (int, float)) and (row.get("snore_detected") or snore_level >= 0.62):
                severity = "critical" if snore_level >= 0.78 else "warning"
                condition = "snore"
                add(
                    "snore", severity, "呼噜扰动",
                    f"检测到呼噜强度约 {snore_level * 100:.0f}%，建议观察其对心率和呼吸的影响。",
                    timestamp, "snore_board",
                    -16 if severity == "critical" else -9,
                    {"snore_level": snore_level, "snore_score": row.get("snore_score"), "snore_dbfs": row.get("snore_dbfs")},
                    f"snore:{minute}",
                )

            if isinstance(heart_rate, (int, float)) and (heart_rate >= 100 or heart_rate < 55):
                condition = "vital_abnormal"
                add(
                    "heart_abnormal", "warning", "心率异常波动",
                    f"当前心率 {heart_rate:.1f} BPM，超出静息观察范围。",
                    timestamp, "radar_board", -10,
                    {"heart_rate": heart_rate},
                    f"heart_abnormal:{minute}",
                )

            breath_window = breath_window_abnormal(rows[-8:])
            if breath_window and row is rows[-1]:
                condition = "vital_abnormal"
                median_breath = breath_window["median_breath_rate"]
                add(
                    "breath_abnormal", "warning", "呼吸异常波动",
                    f"最近呼吸率中位数 {median_breath:.1f} RPM，持续超出静息观察范围。",
                    timestamp, "radar_board", -10,
                    {"breath_rate": breath_rate, **breath_window},
                    f"breath_abnormal:{minute}",
                )

            if condition == "normal" and previous_condition not in {"normal"}:
                add(
                    "recovered", "normal", "状态恢复",
                    "设备在线且生命体征回到稳定区间。",
                    timestamp, "realtime_api", 4,
                    {"previous_condition": previous_condition},
                    f"recovered:{minute}",
                )
            previous_condition = condition

        return events

    def _compute_sleep_score(self, rows, events):
        if not rows and not events:
            return {
                "score": 0,
                "label": "等待数据",
                "summary": "启动真实后端服务和两个真实开发板后，睡眠看护驾驶舱会开始生成评分。",
                "penalties": [],
            }

        heart_values = self._numeric_values(rows, "heart_rate")
        breath_values = self._numeric_values(rows, "breath_rate")
        snore_levels = self._numeric_values(rows, "snore_level")
        comfort_statuses = [row.get("comfort_status") for row in rows if row.get("comfort_status")]
        total_rows = max(len(rows), 1)
        radar_offline_ratio = sum(1 for row in rows if row.get("radar_online") is False) / total_rows if rows else 0.0
        uncomfortable_ratio = (
            sum(1 for status in comfort_statuses if status not in {"comfortable", "offline"}) / total_rows
            if rows else 0.0
        )
        no_person_ratio = (
            sum(1 for row in rows if row.get("radar_online") is False or float(row.get("target_distance") or 0) <= 0) / total_rows
            if rows else 0.0
        )
        snore_event_count = sum(1 for row in rows if row.get("snore_detected")) + sum(1 for event in events if event.get("type") == "snore")
        apnea_event_count = sum(1 for event in events if event.get("type") == "suspected_apnea")

        penalties = []
        if len(rows) < 10:
            penalties.append({"name": "数据不足", "value": 10, "reason": "有效时间轴少于 10 个点"})

        if heart_values:
            hr_std = self._standard_deviation(heart_values)
            penalty = min(16.0, hr_std * 1.8)
            if penalty >= 2:
                penalties.append({"name": "心率波动", "value": round(penalty, 1), "reason": f"心率标准差 {hr_std:.1f} BPM"})
        if breath_values:
            br_std = self._standard_deviation(breath_values)
            penalty = min(16.0, br_std * 3.2)
            if penalty >= 2:
                penalties.append({"name": "呼吸波动", "value": round(penalty, 1), "reason": f"呼吸率标准差 {br_std:.1f} RPM"})
        if snore_levels or snore_event_count:
            avg_snore = self._average(snore_levels) or 0.0
            penalty = min(28.0, avg_snore * 20.0 + snore_event_count * 0.6)
            if penalty >= 2:
                penalties.append({"name": "呼噜扰动", "value": round(penalty, 1), "reason": f"平均呼噜强度 {avg_snore * 100:.0f}%，事件点 {snore_event_count} 个"})
        if apnea_event_count:
            penalties.append({
                "name": "疑似呼吸暂停",
                "value": round(min(30.0, apnea_event_count * 12.0), 1),
                "reason": f"雷达与呼噜融合提示 {apnea_event_count} 次疑似暂停",
            })
        if radar_offline_ratio > 0:
            penalties.append({"name": "雷达掉线", "value": round(min(22.0, radar_offline_ratio * 34.0), 1), "reason": f"雷达断线占比 {radar_offline_ratio * 100:.0f}%"})
        if uncomfortable_ratio > 0:
            penalties.append({"name": "环境舒适度", "value": round(min(16.0, uncomfortable_ratio * 24.0), 1), "reason": f"温湿度不舒适占比 {uncomfortable_ratio * 100:.0f}%"})
        if no_person_ratio > 0.08:
            penalties.append({"name": "疑似离床", "value": round(min(24.0, no_person_ratio * 32.0), 1), "reason": f"未检测到人体占比 {no_person_ratio * 100:.0f}%"})

        score = max(0, min(100, round(100.0 - sum(float(item["value"]) for item in penalties))))
        event_severities = [
            event.get("severity", "info")
            for event in events
            if event.get("status", "active") == "active"
        ]
        worst_event = max(event_severities, key=self._severity_rank) if event_severities else "info"
        if radar_offline_ratio > 0.25 or worst_event == "critical":
            label = "设备异常" if radar_offline_ratio > 0.25 else ("疑似呼吸暂停" if apnea_event_count else "呼噜频繁")
        elif no_person_ratio > 0.12:
            label = "疑似离床"
        elif score >= 86:
            label = "稳定睡眠"
        elif score >= 68:
            label = "轻度扰动"
        else:
            label = "需要关注"

        main_reason = penalties[0]["reason"] if penalties else "当前窗口内心率、呼吸和呼噜数据整体平稳"
        return {
            "score": score,
            "label": label,
            "summary": main_reason,
            "penalties": penalties,
        }

    def _build_stability_cards(self, rows):
        heart_values = self._numeric_values(rows, "heart_rate")
        breath_values = self._numeric_values(rows, "breath_rate")
        snore_levels = self._numeric_values(rows, "snore_level")
        environment_rows = [row for row in rows if row.get("environment_online")]
        comfortable_rows = [row for row in environment_rows if row.get("comfort_status") == "comfortable"]
        temperatures = self._numeric_values(rows, "temperature_c")
        humidities = self._numeric_values(rows, "humidity_pct")
        return [
            {
                "key": "heart",
                "title": "心率稳定性",
                "value": round(max(0, 100 - self._standard_deviation(heart_values) * 8)) if heart_values else 0,
                "unit": "%",
                "detail": f"平均 {self._average(heart_values) or '--'} BPM，样本 {len(heart_values)}",
            },
            {
                "key": "breath",
                "title": "呼吸稳定性",
                "value": round(max(0, 100 - self._standard_deviation(breath_values) * 16)) if breath_values else 0,
                "unit": "%",
                "detail": f"平均 {self._average(breath_values) or '--'} RPM，样本 {len(breath_values)}",
            },
            {
                "key": "snore",
                "title": "呼噜安静度",
                "value": round(max(0, 100 - (self._average(snore_levels) or 0) * 100)) if snore_levels else 100,
                "unit": "%",
                "detail": f"平均强度 {round((self._average(snore_levels) or 0) * 100)}%，样本 {len(snore_levels)}",
            },
            {
                "key": "environment",
                "title": "环境舒适度",
                "value": round(len(comfortable_rows) / len(environment_rows) * 100) if environment_rows else 0,
                "unit": "%",
                "detail": f"温度 {self._average(temperatures) or '--'} C，湿度 {self._average(humidities) or '--'} %RH",
            },
        ]

    @staticmethod
    def _ai_pick_number(row, keys):
        for key in keys:
            value = row.get(key)
            if value in (None, ""):
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(number):
                return number
        return None

    def _deepseek_chat_url(self):
        base_url = os.getenv("DEEPSEEK_BASE_URL", DEEPSEEK_BASE_URL).strip().rstrip("/")
        if base_url.endswith("/chat/completions"):
            return base_url
        return f"{base_url}/chat/completions"

    def _rows_for_deepseek_analysis(self, rows):
        compact_rows = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            compact_rows.append({
                "timestamp": row.get("timestamp") or row.get("createTime") or row.get("time"),
                "heart_rate_bpm": self._ai_pick_number(row, ("heart_rate", "bpm_rader", "bpm_radar", "heartRate")),
                "breath_rate_rpm": self._ai_pick_number(row, ("breath_rate", "bpm_finger", "breathRate", "respiration_rate")),
                "temperature_c": self._ai_pick_number(row, ("temperature_c", "temperature")),
                "humidity_pct": self._ai_pick_number(row, ("humidity_pct", "humidity")),
                "snore_score": self._ai_pick_number(row, ("snore_score", "snoreScore")),
                "snore_detected": bool(row.get("snore_detected")) if row.get("snore_detected") is not None else None,
                "sleep_stage": row.get("sleep_stage"),
                "comfort_status": row.get("comfort_status"),
            })
        max_rows = max(10, int(os.getenv("DEEPSEEK_MAX_ANALYSIS_ROWS", str(DEEPSEEK_MAX_ANALYSIS_ROWS))))
        return compact_rows[-max_rows:]

    def _basic_ai_stats(self, rows):
        heart_values = []
        breath_values = []
        temperature_values = []
        humidity_values = []
        snore_rows = 0

        for row in rows or []:
            if not isinstance(row, dict):
                continue
            heart = self._ai_pick_number(row, ("heart_rate", "bpm_rader", "bpm_radar", "heartRate"))
            breath = self._ai_pick_number(row, ("breath_rate", "bpm_finger", "breathRate", "respiration_rate"))
            temperature = self._ai_pick_number(row, ("temperature_c", "temperature"))
            humidity = self._ai_pick_number(row, ("humidity_pct", "humidity"))
            if heart is not None:
                heart_values.append(heart)
            if breath is not None:
                breath_values.append(breath)
            if temperature is not None:
                temperature_values.append(temperature)
            if humidity is not None:
                humidity_values.append(humidity)
            if bool(row.get("snore_detected")) or float(row.get("snore_score") or 0.0) >= 0.5:
                snore_rows += 1

        return {
            "sample_count": len(rows or []),
            "heart_avg": round(self._average(heart_values), 2) if heart_values else None,
            "heart_min": round(min(heart_values), 2) if heart_values else None,
            "heart_max": round(max(heart_values), 2) if heart_values else None,
            "breath_avg": round(self._average(breath_values), 2) if breath_values else None,
            "breath_min": round(min(breath_values), 2) if breath_values else None,
            "breath_max": round(max(breath_values), 2) if breath_values else None,
            "temperature_avg": round(self._average(temperature_values), 2) if temperature_values else None,
            "humidity_avg": round(self._average(humidity_values), 2) if humidity_values else None,
            "snore_rows": snore_rows,
        }

    @staticmethod
    def _safe_deepseek_error(exc):
        text = str(exc) or exc.__class__.__name__
        if len(text) > 160:
            text = text[:160] + "..."
        api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        if api_key:
            text = text.replace(api_key, "[redacted]")
        return text

    def _call_deepseek_vitals_report(self, rows, date=None, user_id=None):
        api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        if not api_key:
            return None

        compact_rows = self._rows_for_deepseek_analysis(rows)
        if not compact_rows:
            return None

        model = os.getenv("DEEPSEEK_MODEL", DEEPSEEK_MODEL).strip() or DEEPSEEK_MODEL
        stats = self._basic_ai_stats(rows)
        scope_text = date or "当前筛选"
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是一个睡眠看护项目的历史数据分析助手。"
                        "请用中文输出，语气专业、简洁、适合比赛演示。"
                        "不要做医疗诊断，不要夸大风险；请提醒需要结合现场观察和设备状态复核。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "请基于以下睡眠看护历史数据生成约 300-500 字分析报告，"
                        "必须包含：1）总体概览；2）心率/呼吸率异常或稳定性；"
                        "3）呼噜与环境线索；4）看护建议；\n"
                        f"样本范围：{scope_text}；用户ID：{user_id or '未提供'}。\n"
                        f"统计摘要：{json.dumps(stats, ensure_ascii=False)}\n"
                        f"最近样本：{json.dumps(compact_rows, ensure_ascii=False)}"
                    ),
                },
            ],
            "temperature": 0.25,
            "max_tokens": max(
                256, int(os.getenv("DEEPSEEK_MAX_TOKENS", str(DEEPSEEK_MAX_TOKENS)))
            ),
            "stream": False,
        }

        request = urllib.request.Request(
            self._deepseek_chat_url(),
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        timeout = max(5.0, float(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", str(DEEPSEEK_TIMEOUT_SECONDS))))
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_body = response.read().decode("utf-8")
        result = json.loads(response_body)
        content = (
            (result.get("choices") or [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        if not content:
            raise RuntimeError("DeepSeek 未返回有效分析内容")
        return {
            "status": "success",
            "provider": "deepseek",
            "model": result.get("model") or model,
            "fallback": False,
            "report": content,
            "summary": content.splitlines()[0] if content else "",
            "sample_count": len(rows or []),
            "analyzed_rows": len(compact_rows),
            "userID": user_id,
            "generated_at": self._now_iso(),
        }

    def _stream_deepseek_vitals_report(self, rows, date=None, user_id=None):
        """Streaming variant of the DeepSeek call. Yields text deltas as they
        arrive from the upstream SSE. Raises on transport / HTTP / parse errors
        so the caller can decide whether to fall back to local rules.

        Each yielded value is a dict: {"delta": str, "model": str|None}.
        The final item is a sentinel with "done": True once the upstream closes
        or the stream ends naturally.
        """
        api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("DeepSeek API key is not configured")

        compact_rows = self._rows_for_deepseek_analysis(rows)
        if not compact_rows:
            raise RuntimeError("无可分析的历史样本")

        model = os.getenv("DEEPSEEK_MODEL", DEEPSEEK_MODEL).strip() or DEEPSEEK_MODEL
        stats = self._basic_ai_stats(rows)
        scope_text = date or "当前筛选"
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是一个睡眠看护项目的历史数据分析助手。"
                        "请用中文输出，语气专业、简洁、适合比赛演示。"
                        "不要做医疗诊断，不要夸大风险；请提醒需要结合现场观察和设备状态复核。"
                        "输出格式：使用 Markdown 标题、列表、粗体等结构化语法，方便前端编译展示。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "请基于以下睡眠看护历史数据生成约 600-1200 字的结构化分析报告，"
                        "必须包含 4 个章节：\n"
                        "## 总体概览\n"
                        "## 心率与呼吸率分析\n"
                        "## 呼噜与环境线索\n"
                        "## 看护建议\n"
                        f"样本范围：{scope_text}；用户ID：{user_id or '未提供'}。\n"
                        f"统计摘要：{json.dumps(stats, ensure_ascii=False)}\n"
                        f"最近样本：{json.dumps(compact_rows, ensure_ascii=False)}"
                    ),
                },
            ],
            "temperature": 0.25,
            "max_tokens": max(
                256, int(os.getenv("DEEPSEEK_MAX_TOKENS", str(DEEPSEEK_MAX_TOKENS)))
            ),
            "stream": True,
        }

        request = urllib.request.Request(
            self._deepseek_chat_url(),
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
            method="POST",
        )
        timeout = max(5.0, float(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", str(DEEPSEEK_TIMEOUT_SECONDS))))
        with urllib.request.urlopen(request, timeout=timeout) as response:
            saw_done = False
            emitted_any = False
            for raw_line in response:
                if not emitted_any:
                    emitted_any = True
                line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                if not line:
                    continue
                if not line.startswith("data:"):
                    continue
                data = line[len("data:"):].lstrip()
                if data == "[DONE]":
                    saw_done = True
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(f"DeepSeek 流式响应解析失败: {exc}") from exc
                choice = (chunk.get("choices") or [{}])[0]
                delta = choice.get("delta", {}).get("content") or ""
                if delta:
                    yield {"delta": delta, "model": chunk.get("model") or model}
            if not saw_done and not emitted_any:
                raise RuntimeError("DeepSeek 流式响应为空")

    def _build_ai_vitals_report(self, rows, date=None, user_id=None):
        try:
            deepseek_report = self._call_deepseek_vitals_report(rows, date=date, user_id=user_id)
            if deepseek_report:
                return deepseek_report
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
            deepseek_error = self._safe_deepseek_error(exc)
        except Exception as exc:
            deepseek_error = self._safe_deepseek_error(exc)
        else:
            deepseek_error = None

        rows = rows or []
        heart_values = []
        breath_values = []
        abnormal_rows = []

        for index, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                continue
            heart = self._ai_pick_number(row, ("heart_rate", "bpm_rader", "bpm_radar", "heartRate"))
            breath = self._ai_pick_number(row, ("breath_rate", "bpm_finger", "breathRate", "respiration_rate"))

            if heart is not None:
                heart_values.append(heart)
            if breath is not None:
                breath_values.append(breath)

            row_issues = []
            if heart is not None and (heart < 55 or heart > 100):
                row_issues.append(f"heart {heart:.1f} BPM")
            if breath is not None and (breath < 10 or breath > 24):
                row_issues.append(f"breath {breath:.1f} RPM")
            if row_issues:
                abnormal_rows.append((index, ", ".join(row_issues)))

        scope_text = date or "\u5f53\u524d\u7b5b\u9009"
        report_lines = [
            "\u672c\u5730\u5065\u5eb7\u5206\u6790\u62a5\u544a",
            f"\u6837\u672c\u8303\u56f4\uff1a{scope_text}\uff0c\u5f53\u524d\u9875\u5171 {len(rows)} \u6761\u8bb0\u5f55\u3002",
        ]

        if not heart_values and not breath_values:
            report_lines.extend([
                "\u672a\u8bfb\u53d6\u5230\u53ef\u7528\u7684\u5fc3\u7387\u6216\u547c\u5438\u7387\u6837\u672c\u3002",
                "\u8bf7\u5148\u786e\u8ba4\u540e\u7aef\u5df2\u7ecf\u6536\u5230\u771f\u5b9e\u96f7\u8fbe\u6570\u636e\uff0c\u7136\u540e\u91cd\u65b0\u751f\u6210\u62a5\u544a\u3002",
            ])
        else:
            if heart_values:
                report_lines.append(
                    f"\u5fc3\u7387\uff1a\u5e73\u5747 {self._average(heart_values):.1f} BPM\uff0c"
                    f"\u6700\u4f4e {min(heart_values):.1f}\uff0c\u6700\u9ad8 {max(heart_values):.1f}\u3002"
                )
            else:
                report_lines.append("\u5fc3\u7387\uff1a\u6682\u65e0\u6709\u6548\u6837\u672c\u3002")

            if breath_values:
                report_lines.append(
                    f"\u547c\u5438\u7387\uff1a\u5e73\u5747 {self._average(breath_values):.1f} RPM\uff0c"
                    f"\u6700\u4f4e {min(breath_values):.1f}\uff0c\u6700\u9ad8 {max(breath_values):.1f}\u3002"
                )
            else:
                report_lines.append("\u547c\u5438\u7387\uff1a\u6682\u65e0\u6709\u6548\u6837\u672c\u3002")

            if abnormal_rows:
                preview = "\uff1b".join(
                    f"#{index} {description}" for index, description in abnormal_rows[:5]
                )
                suffix = "\uff1b..." if len(abnormal_rows) > 5 else ""
                report_lines.append(
                    f"\u5f02\u5e38\u63d0\u793a\uff1a\u5171 {len(abnormal_rows)} \u6761\u8bb0\u5f55\u8d85\u51fa\u53c2\u8003\u8303\u56f4\uff08{preview}{suffix}\uff09\u3002"
                )
                report_lines.append(
                    "\u5efa\u8bae\uff1a\u7ed3\u5408\u5b9e\u65f6\u76d1\u6d4b\u3001\u96f7\u8fbe\u5728\u7ebf\u72b6\u6001\u548c\u5e8a\u65c1\u60c5\u51b5\u590d\u6838\uff1b"
                    "\u5982\u679c\u6301\u7eed\u504f\u79bb\uff0c\u4f18\u5148\u786e\u8ba4\u4f69\u6234/\u59ff\u6001\u3001\u73af\u5883\u5e72\u6270\u548c\u8bbe\u5907\u8fde\u63a5\u3002"
                )
            else:
                report_lines.append(
                    "\u7ed3\u8bba\uff1a\u5f53\u524d\u9875\u6837\u672c\u7684\u5fc3\u7387\u548c\u547c\u5438\u7387\u5747\u5728\u5e38\u7528\u53c2\u8003\u8303\u56f4\u5185\uff0c\u6682\u672a\u89c1\u660e\u663e\u5f02\u5e38\u3002"
                )

        return {
            "status": "success",
            "provider": "local",
            "model": "local-vitals-rules",
            "fallback": True,
            "warning": (
                f"DeepSeek 不可用，已本地规则兜底：{deepseek_error}"
                if deepseek_error else "\u672c\u5730\u89c4\u5219\u515c\u5e95"
            ),
            "report": "\n".join(report_lines),
            "summary": report_lines[-1] if report_lines else "",
            "sample_count": len(rows),
            "userID": user_id,
            "generated_at": self._now_iso(),
        }

    def _build_sleep_overview(self, rows, events, mode, seconds, date, user_id, devices=None):
        events = [
            event for event in events
            if not (
                event.get("type") == "device_offline"
                and event.get("source") in {"snore_board", "environment_board"}
            )
            and event.get("status", "active") == "active"
        ]
        events_sorted = sorted(events, key=lambda item: item.get("timestamp", ""), reverse=True)
        heatmap = self._build_snore_heatmap(rows, events_sorted)
        score = self._compute_sleep_score(rows, events_sorted)
        stats = self._timeline_summary(rows)
        worst = max(heatmap, key=lambda item: item["intensity"], default=None)
        return {
            "code": 200,
            "status": "success",
            "mode": mode,
            "seconds": seconds,
            "date": date,
            "userID": user_id,
            "generated_at": self._now_iso(),
            "score": score,
            "stats": {
                **stats,
                "event_count": len(events_sorted),
                "critical_event_count": sum(
                    1 for event in events_sorted
                    if event.get("severity") == "critical" and event.get("status", "active") == "active"
                ),
                "warning_event_count": sum(
                    1 for event in events_sorted
                    if event.get("severity") == "warning" and event.get("status", "active") == "active"
                ),
                "suspected_apnea_count": sum(
                    1 for event in events_sorted
                    if event.get("type") == "suspected_apnea" and event.get("status", "active") == "active"
                ),
            },
            "devices": devices or {},
            "heatmap": heatmap,
            "worst_disturbance": worst,
            "events": events_sorted[:120],
            "stability_cards": self._build_stability_cards(rows),
        }

    def _update_packet_debug(self, packet, frame_number):
        payload_len = max(0, len(packet) - 6)
        with self.state_lock:
            self.radar_debug.update({
                "sample_format": "float16",
                "packet_len": len(packet),
                "payload_len": payload_len,
                "samples_per_frame": payload_len // 2,
                "first_8_bytes_hex": packet[:8].hex(" "),
                "frame_number": int(frame_number),
                "last_received_at": self.last_radar_received_at,
            })

    def _update_sample_debug(self, packet, samples, target_bin=None, target_distance=None):
        finite_samples = np.asarray(samples, dtype=np.float32)
        finite_samples = finite_samples[np.isfinite(finite_samples)]
        if finite_samples.size:
            sample_min = float(np.min(finite_samples))
            sample_max = float(np.max(finite_samples))
            sample_mean = float(np.mean(finite_samples))
            sample_std = float(np.std(finite_samples))
        else:
            sample_min = sample_max = sample_mean = sample_std = None
        presence_debug = self._presence_debug_state()

        with self.state_lock:
            self.radar_debug.update({
                "sample_format": "float16",
                "packet_len": len(packet),
                "payload_len": max(0, len(packet) - 6),
                "samples_per_frame": len(samples),
                "first_8_bytes_hex": packet[:8].hex(" "),
                "sample_min": sample_min,
                "sample_max": sample_max,
                "sample_mean": sample_mean,
                "sample_std": sample_std,
                "target_bin": int(target_bin) if target_bin is not None else None,
                "target_distance": float(target_distance) if target_distance is not None else None,
                "breath_periodicity": float(self.breath_periodicity or 0.0),
                "presence_detected": bool(self.presence_detected),
                "presence_signal": bool(presence_debug.get("presence_signal")),
                "presence_energy_stable": bool(presence_debug.get("presence_energy_stable")),
                "presence_distance_stable": bool(presence_debug.get("presence_distance_stable")),
                "presence_distance_span": presence_debug.get("presence_distance_span"),
                "presence_distance": presence_debug.get("presence_distance"),
                "presence_distance_min_m": PRESENCE_DISTANCE_MIN_M,
                "presence_distance_max_m": PRESENCE_DISTANCE_MAX_M,
                "presence_distance_stability_span_m": PRESENCE_DISTANCE_STABILITY_SPAN_M,
                "presence_detection_value": presence_debug.get("presence_detection_value"),
                "presence_detection_threshold": presence_debug.get("presence_detection_threshold"),
                "presence_detection_bin": presence_debug.get("presence_detection_bin"),
                "presence_below_threshold": bool(presence_debug.get("presence_below_threshold")),
                "presence_stable": bool(self.presence_stable),
                "presence_bypassed_by_snore": bool(self.presence_bypassed_by_snore),
            })

    def _handle_radar_status_packet(self, packet):
        try:
            payload = packet[1:].decode("utf-8", errors="replace").strip("\x00\r\n ")
            status = json.loads(payload)
        except Exception as exc:
            with self.state_lock:
                self.radar_debug.update({
                    "status_packet_error": str(exc),
                    "status_packet_hex": packet[:80].hex(" "),
                })
            return

        now = time.time()
        now_text = self._now_iso()

        with self.state_lock:
            self.last_radar_status_time = now
            self.last_radar_status_at = now_text
            self.radar_board_stationary = True
            self.radar_motion_reason = "disabled"
            self.radar_motion_delta = None
            self.radar_motion_sensor_ready = None
            self.radar_debug.update({
                "status_packet": status,
                "last_status_at": now_text,
                "board_still": True,
                "motion_reason": "disabled",
                "motion_delta": None,
                "motion_sensor_ready": None,
            })

    def _is_valid_radar_data_packet(self, data):
        """只接受雷达固件定义的数据帧，避免 JSON 控制包/广播包污染在线状态。"""
        if len(data) < 8:
            return False
        if data[0] != RADAR_DATA_COMMAND or data[1] != RADAR_DUMMY_BYTE:
            return False
        payload_len = len(data) - 6
        return payload_len > 0 and payload_len % 2 == 0

    def _status_snapshot(self):
        radar_age = self._seconds_since(self.last_radar_received_time)
        radar_status_age = self._seconds_since(self.last_radar_status_time)
        snore_age = self._seconds_since(self.last_snore_heartbeat_time)
        voice_age = self._seconds_since(self.last_voice_received_time)
        radar_board_online = self._radar_board_online()
        radar_online = self._radar_data_online()
        snore_online = self._snore_board_online()
        env = self._environment_snapshot()
        active_emergency = self._active_emergency_event()
        vitals_age = self._vitals_age_seconds()
        snore_level = self._snore_level_from_dbfs(self.snore_dbfs, self.snore_score)
        presence_debug = self._presence_debug_state()
        return {
            "running": self.running,
            "radar_online": radar_online,
            "radar_board_online": radar_board_online,
            "radar_board_stationary": bool(self.radar_board_stationary),
            "radar_motion_reason": self.radar_motion_reason,
            "radar_motion_delta": self.radar_motion_delta,
            "radar_motion_sensor_ready": self.radar_motion_sensor_ready,
            "presence_detected": bool(self.presence_detected) if radar_board_online else False,
            "presence_signal": bool(presence_debug.get("presence_signal")) if radar_board_online else False,
            "presence_energy_stable": bool(presence_debug.get("presence_energy_stable")) if radar_board_online else False,
            "presence_distance_stable": bool(presence_debug.get("presence_distance_stable")) if radar_board_online else False,
            "presence_distance_span": presence_debug.get("presence_distance_span") if radar_board_online else None,
            "presence_distance": presence_debug.get("presence_distance") if radar_board_online else None,
            "presence_distance_min_m": PRESENCE_DISTANCE_MIN_M,
            "presence_distance_max_m": PRESENCE_DISTANCE_MAX_M,
            "presence_distance_stability_span_m": PRESENCE_DISTANCE_STABILITY_SPAN_M,
            "presence_detection_value": presence_debug.get("presence_detection_value") if radar_board_online else None,
            "presence_detection_threshold": presence_debug.get("presence_detection_threshold") if radar_board_online else None,
            "presence_detection_bin": presence_debug.get("presence_detection_bin") if radar_board_online else None,
            "presence_below_threshold": bool(presence_debug.get("presence_below_threshold")) if radar_board_online else False,
            "presence_stable": bool(self.presence_stable) if radar_board_online else False,
            "presence_bypassed_by_snore": bool(self.presence_bypassed_by_snore),
            "snore_board_online": snore_online,
            "snore_monitoring": bool(self.snore_session_active and snore_online),
            "snore_paused": bool(self.snore_session_stopped and self._edgi_board_online()),
            "environment_board_online": env["environment_board_online"],
            "environment_sensor_ok": env["environment_sensor_ok"],
            "voice_board_online": self._voice_board_online(),
            "edgi_board_online": self._edgi_board_online(),
            "snore_session_active": bool(self.snore_session_active),
            "snore_session_started_at": self.snore_session_started_text,
            "heart_rate": float(self.heart_rate) if radar_board_online and self.heart_rate is not None else None,
            "breath_rate": float(self.breath_rate) if radar_board_online and self.breath_rate is not None else None,
            "breath_quality": self.breath_rate_quality if radar_board_online else 0.0,
            "breath_periodicity": self.breath_periodicity if radar_board_online else 0.0,
            "heart_rate_fresh": bool(self.heart_rate_fresh) if radar_board_online else False,
            "breath_rate_fresh": bool(self.breath_rate_fresh) if radar_board_online else False,
            "vitals_state": self.vitals_state if radar_board_online else "lost",
            "vitals_missing_count": int(self.vitals_missing_count),
            "vitals_age_seconds": round(vitals_age, 2) if vitals_age is not None else None,
            "last_valid_vitals_at": self.last_valid_vitals_at,
            "target_distance": float(self.target_bin * RANGE_RESOLUTION) if self.target_bin is not None else None,
            "target_bin": int(self.target_bin) if self.target_bin is not None else None,
            "total_frames": self.total_frames_received,
            "processed_frames": self.processing_count,
            "uptime": time.time() - self.start_time,
            "last_frame": self.last_frame_number,
            "last_radar_frame_number": self.last_frame_number,
            "last_radar_received_at": self.last_radar_received_at,
            "last_radar_status_at": self.last_radar_status_at,
            "last_snore_heartbeat_at": self.last_snore_heartbeat_at,
            "last_environment_heartbeat_at": env["last_environment_heartbeat_at"],
            "last_voice_received_at": self.last_voice_received_at,
            "last_edgi_heartbeat_at": self.last_edgi_heartbeat_at,
            "radar_age_seconds": round(radar_age, 2) if radar_age is not None else None,
            "radar_status_age_seconds": round(radar_status_age, 2) if radar_status_age is not None else None,
            "snore_age_seconds": round(snore_age, 2) if snore_age is not None else None,
            "environment_age_seconds": env["environment_age_seconds"],
            "voice_age_seconds": round(voice_age, 2) if voice_age is not None else None,
            "edgi_age_seconds": self._seconds_since(self.last_edgi_heartbeat_time),
            "emergency_active": active_emergency is not None,
            "active_emergency": active_emergency,
            "audio_upload_count": self.audio_upload_count,
            "last_audio_received_at": self.last_audio_received_at,
            "last_audio_file": self.last_audio_file,
            "last_audio_seconds": self.last_audio_seconds,
            "last_audio_dbfs": self.last_audio_dbfs,
            "snore_score": round(float(self.snore_score or 0.0), 3) if snore_online else 0.0,
            "snore_dbfs": self.snore_dbfs if snore_online else None,
            "snore_level": snore_level if snore_online else None,
            "snore_detected": bool(self.snore_detected) if snore_online else False,
            "snore_event_count": self.snore_event_count,
            "last_snore_at": self.last_snore_at,
            "snore_sound_active": bool(self.snore_sound_active),
            "last_snore_sound_at": self.last_snore_sound_at,
            "last_snore_sound_stop_at": self.last_snore_sound_stop_at,
            "last_snore_stop_fusion": self.last_snore_stop_fusion,
            "snore_stop_breath_alarm_count": self.snore_stop_breath_alarm_count,
            "temperature_c": env["temperature_c"],
            "raw_temperature_c": env["raw_temperature_c"],
            "temperature_offset_c": env["temperature_offset_c"],
            "humidity_pct": env["humidity_pct"],
            "comfort_status": env["comfort_status"],
            "sleep_stage": self._sleep_stage_for_latest(
                radar_online,
                self.heart_rate,
                self.breath_rate,
            ),
            "night_absence_monitor": dict(self.night_absence_debug),
            "night_absence_monitoring": bool(self.night_absence_debug.get("monitoring")),
            "night_absence_absent_seconds": self.night_absence_debug.get("absent_seconds"),
            "night_absence_alarm_after_seconds": NIGHT_ABSENCE_ALARM_SECONDS,
            "timeline_points": len(self.timeline),
            "radar_debug": dict(self.radar_debug),
            "timestamp": time.time(),
        }

    def _init_api(self):
        """初始化FastAPI应用"""
        self.app = FastAPI(title="雷达心率监测API",
                          description="提供实时雷达心率监测数据的API接口",
                          version="1.0.0")
        from pydantic import BaseModel

        class VitalsData(BaseModel):
            userID: int
            bed_id: Optional[str] = None
            heart_rate: float
            breath_rate: float
            target_distance: float
            timestamp: Optional[str] = None  # ISO 8601 格式，如 "2025-12-07T18:30:00.000Z"
            snore_detected: Optional[bool] = False
            snore_score: Optional[float] = None
            snore_level: Optional[float] = None

        class UserRegister(BaseModel):
            userName: str
            passWord: str
            email: str

        class UserLogin(BaseModel):
            userName: str
            passWord: str

        class SnoreHeartbeat(BaseModel):
            bed_id: Optional[str] = None
            device_id: Optional[str] = None
            snore_score: float = 0.0
            snore_detected: bool = False
            dbfs: Optional[float] = None
            source: str = "real_snore_board"


        class EnvironmentHeartbeat(BaseModel):
            bed_id: Optional[str] = None
            device_id: Optional[str] = None
            temperature_c: float
            humidity_pct: float
            sensor_ok: bool = True
            source: str = "real_edgi_talk_m33_aht20"


        class EdgiHeartbeat(BaseModel):
            bed_id: Optional[str] = None
            device_id: Optional[str] = None
            source: str = "xiaozhi_board"
            mode: Optional[str] = None
            keyword_online: Optional[bool] = None
            snore_guard_enabled: Optional[bool] = None

        class SnoreSessionRequest(BaseModel):
            bed_id: Optional[str] = None
            device_id: Optional[str] = None
            source: str = "real_snore_board"

        class EmergencyRequest(BaseModel):
            bed_id: Optional[str] = None
            source: str = "xiaozhi_voice_board"
            event_type: Optional[str] = None
            type: Optional[str] = None
            title: Optional[str] = None
            message: Optional[str] = None
            severity: Optional[str] = None
            phrase: Optional[str] = None
            transcript: Optional[str] = None
            device_id: Optional[str] = None
            timestamp: Optional[str] = None
            details: Optional[Dict[str, Any]] = None


        class EmergencyResolveRequest(BaseModel):
            bed_id: Optional[str] = None
            event_id: Optional[int] = None
            source: str = "xiaozhi_voice_board"
            device_id: Optional[str] = None
            resolution_note: Optional[str] = None
            resolved_by: Optional[str] = None


        class DemoApneaRequest(BaseModel):
            bed_id: Optional[str] = None
            source: str = "frontend_demo"
            duration_seconds: float = 8.0
            note: Optional[str] = None



        class AiVitalsAnalysisRequest(BaseModel):
            rows: Optional[list] = None
            date: Optional[str] = None
            userID: Optional[int] = None
            bed_id: Optional[str] = None


        @self.app.post("/emergency")
        async def receive_emergency(payload: EmergencyRequest):
            return self._record_emergency_event(payload)


        def _fall_payload(payload: EmergencyRequest):
            update = {
                "event_type": "board_fall",
                "title": payload.title or "开发板摇晃报警",
                "message": payload.message or "开发板检测到疑似摇晃，请立即确认佩戴者和设备状态。",
                "severity": payload.severity or "critical",
            }
            if hasattr(payload, "model_copy"):
                return payload.model_copy(update=update)
            return payload.copy(update=update)


        @self.app.post("/emergency/fall")
        async def receive_fall_emergency(payload: EmergencyRequest):
            return self._record_emergency_event(_fall_payload(payload))


        @self.app.post("/hardware/fall")
        async def receive_hardware_fall(payload: EmergencyRequest):
            return self._record_emergency_event(_fall_payload(payload))


        @self.app.post("/beds/{bed_id}/emergency/resolve")
        async def resolve_bed_emergency(bed_id: str, payload: EmergencyResolveRequest):
            update = {"bed_id": bed_id}
            if hasattr(payload, "model_copy"):
                payload = payload.model_copy(update=update)
            else:
                payload = payload.copy(update=update)
            return self._resolve_emergency_event(payload)


        @self.app.post("/emergency/resolve")
        async def resolve_emergency(payload: EmergencyResolveRequest):
            return self._resolve_emergency_event(payload)

        @self.app.get("/hardware/emergency-sync")
        async def hardware_emergency_sync(bed_id: Optional[str] = None, source: Optional[str] = None, device_id: Optional[str] = None):
            resolved_bed_id = self._resolve_runtime_bed_id(
                bed_id=bed_id,
                device_id=device_id,
                source=source,
            )
            return self._emergency_sync_snapshot(resolved_bed_id)

        @self.app.get("/beds/{bed_id}/emergency-sync")
        async def bed_emergency_sync(bed_id: str):
            return self._emergency_sync_snapshot(bed_id)


        @self.app.post("/demo/apnea")
        async def trigger_demo_apnea(payload: DemoApneaRequest):
            return self._record_demo_apnea_event(payload)



        @self.app.post("/ai/analyze-vitals")
        async def analyze_vitals(payload: AiVitalsAnalysisRequest):
            return await asyncio.to_thread(
                self._build_ai_vitals_report,
                rows=payload.rows,
                date=payload.date,
                user_id=payload.userID,
            )


        @self.app.post("/ai/analyze-vitals/stream")
        async def analyze_vitals_stream(payload: AiVitalsAnalysisRequest):
            """Stream DeepSeek analysis deltas as Server-Sent Events.

            Each SSE frame is `data: {"delta": "...", "done": false, "model": "..."}`.
            The terminal frame is `data: {"delta": "", "done": true, ...}` carrying the
            final report metadata. If no DeepSeek chunk was emitted, the terminal frame
            contains the local-rules fallback report under `report` / `provider` /
            `fallback` / `warning`.
            """
            q: queue.Queue = queue.Queue()

            def stream_worker():
                try:
                    assembled = []
                    seen_model = None
                    for chunk in self._stream_deepseek_vitals_report(
                        rows=payload.rows, date=payload.date, user_id=payload.userID
                    ):
                        delta = chunk.get("delta") or ""
                        if delta:
                            assembled.append(delta)
                        if chunk.get("model"):
                            seen_model = chunk["model"]
                        q.put(("delta", delta, seen_model))
                    q.put(("done", "".join(assembled), seen_model))
                except Exception as exc:
                    q.put(("error", str(exc), None))

            threading.Thread(target=stream_worker, daemon=True).start()

            async def event_generator():
                loop = asyncio.get_running_loop()
                # Announce start so the client can flip loading state immediately.
                yield "data: " + json.dumps(
                    {"delta": "", "done": False, "stage": "start"}, ensure_ascii=False
                ) + "\n\n"

                saw_any_delta = False
                emitted_report = None
                emitted_provider = "deepseek"
                emitted_model = None
                emitted_fallback = False
                emitted_warning = None

                while True:
                    item = await loop.run_in_executor(None, q.get)
                    kind, payload_value, seen_model = item
                    if kind == "delta":
                        if payload_value:
                            saw_any_delta = True
                        if seen_model:
                            emitted_model = seen_model
                        yield "data: " + json.dumps(
                            {"delta": payload_value, "done": False, "model": seen_model},
                            ensure_ascii=False,
                        ) + "\n\n"
                    elif kind == "done":
                        emitted_report = payload_value or ""
                        if emitted_model is None:
                            emitted_model = (
                                os.getenv("DEEPSEEK_MODEL", DEEPSEEK_MODEL).strip()
                                or DEEPSEEK_MODEL
                            )
                        # If DeepSeek produced nothing usable, swap in the local-rules
                        # report so the client still has something to render.
                        if not saw_any_delta:
                            fallback = self._build_ai_vitals_report(
                                rows=payload.rows,
                                date=payload.date,
                                user_id=payload.userID,
                            )
                            emitted_report = fallback.get("report", "")
                            emitted_provider = fallback.get("provider", "local")
                            emitted_model = fallback.get("model", emitted_model)
                            emitted_fallback = True
                            emitted_warning = fallback.get("warning")
                        yield "data: " + json.dumps(
                            {
                                "delta": "",
                                "done": True,
                                "provider": emitted_provider,
                                "model": emitted_model,
                                "fallback": emitted_fallback,
                                "warning": emitted_warning,
                                "report": emitted_report,
                            },
                            ensure_ascii=False,
                        ) + "\n\n"
                        break
                    elif kind == "error":
                        # If the upstream threw before delivering any chunk, fall back
                        # to the local-rules builder so the UI can still render.
                        if not saw_any_delta:
                            try:
                                fallback = self._build_ai_vitals_report(
                                    rows=payload.rows,
                                    date=payload.date,
                                    user_id=payload.userID,
                                )
                            except Exception:
                                fallback = None
                            if fallback:
                                emitted_report = fallback.get("report", "")
                                emitted_provider = fallback.get("provider", "local")
                                emitted_model = fallback.get("model")
                                emitted_fallback = True
                                emitted_warning = (
                                    fallback.get("warning")
                                    or self._safe_deepseek_error(Exception(payload_value))
                                )
                            else:
                                emitted_report = ""
                                emitted_provider = "error"
                                emitted_fallback = True
                                emitted_warning = self._safe_deepseek_error(
                                    Exception(payload_value)
                                )
                        else:
                            # Mid-stream error: keep what we already have.
                            emitted_warning = self._safe_deepseek_error(
                                Exception(payload_value)
                            )
                        yield "data: " + json.dumps(
                            {
                                "delta": "",
                                "done": True,
                                "provider": emitted_provider,
                                "model": emitted_model,
                                "fallback": emitted_fallback,
                                "warning": emitted_warning,
                                "report": emitted_report,
                            },
                            ensure_ascii=False,
                        ) + "\n\n"
                        break

            return StreamingResponse(
                event_generator(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )


        @self.app.post("/register")
        async def register(user: UserRegister):
            """用户注册接口"""
            try:
                # 调用数据库函数创建用户
                user_id = create_user(user.userName, user.passWord, user.email)
                return {
                    "status": "success",
                    "message": "用户注册成功",
                    "user_id": user_id,
                    "userName": user.userName
                }
            except ValueError as ve:
                return {"status": "error", "message": str(ve)}
            except Exception as e:
                return {"status": "error", "message": f"注册失败: {str(e)}"}

        @self.app.post("/login")
        async def login(user: UserLogin):
            """用户登录接口（仅验证，无 token）"""
            db_user = get_user_by_username(user.userName)
            if not db_user:
                return {"status": "error", "message": "用户名不存在"}

            if not verify_password(user.passWord, db_user['passWord']):
                return {"status": "error", "message": "密码错误"}

            return {
                "status": "success",
                "message": "登录成功",
                "user_id": db_user['userID'],
                "userName": db_user['userName'],
                "email": db_user['email']
            }

        @self.app.post("/save-vitals-with-user")
        async def save_vitals_with_user_endpoint(data: VitalsData):
            """接收开发板/前端按真实结构上报的生命体征，并按床位保存。"""
            try:
                resolved_bed_id = self._resolve_runtime_bed_id(bed_id=data.bed_id)
                snore_score = data.snore_score
                snore_detected = bool(data.snore_detected)
                if snore_score is not None:
                    try:
                        snore_score = max(0.0, min(1.0, float(snore_score)))
                    except (TypeError, ValueError):
                        snore_score = None
                    if snore_score is not None and snore_score < 0.4:
                        snore_detected = False
                data_id = save_vitals_with_user(
                    user_id=data.userID,
                    bed_id=resolved_bed_id,
                    heart_rate=data.heart_rate,
                    breath_rate=data.breath_rate,
                    target_distance=data.target_distance,
                    timestamp_str=data.timestamp,
                    snore_detected=snore_detected,
                    snore_score=snore_score,
                    snore_level=data.snore_level,
                )
                received_time = time.time()
                timestamp = data.timestamp or datetime.fromtimestamp(received_time).isoformat(timespec="seconds")
                vitals = {
                    "heart_rate": float(data.heart_rate),
                    "breath_rate": float(data.breath_rate),
                    "target_distance": float(data.target_distance),
                    "timestamp": timestamp,
                    "received_time": received_time,
                    "snore_detected": snore_detected,
                    "snore_score": snore_score,
                    "snore_level": data.snore_level,
                }
                with self.state_lock:
                    self.external_bed_vitals[resolved_bed_id] = vitals
                self._append_external_timeline(resolved_bed_id, vitals)
                return {
                    "status": "success",
                    "message": "生命体征数据保存成功",
                    "dataID": data_id,
                    "bed_id": resolved_bed_id,
                }
            except Exception as e:
                return {
                    "status": "error",
                    "message": f"保存失败: {str(e)}"
                }

        # 添加CORS中间件
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=[
                "http://localhost:5173",
                "http://127.0.0.1:5173",
                "http://192.168.31.236:5173",
            ],
            allow_origin_regex=r"https?://(?:localhost|127\.0\.0\.1|192\.168\.\d{1,3}\.\d{1,3})(?::\d+)?",
            allow_credentials=True,
            allow_methods=["*"],  # 允许所有方法
            allow_headers=["*"],  # 允许所有头
        )


        @self.app.get("/")
        async def root():
            return {"message": "雷达心率监测API服务正在运行"}

        @self.app.get("/heartrate")
        async def get_heart_rate():
            """获取最新的心率值"""
            radar_board_online = self._radar_board_online()
            if radar_board_online and self.heart_rate is not None:
                return {"heart_rate": float(self.heart_rate),
                        "heart_rate_fresh": bool(self.heart_rate_fresh),
                        "vitals_state": self.vitals_state,
                        "vitals_age_seconds": self._vitals_age_seconds(),
                        "timestamp": time.time(),
                        "status": "ok"}
            else:
                return {"heart_rate": None,
                        "heart_rate_fresh": False,
                        "vitals_state": self.vitals_state if radar_board_online else "lost",
                        "vitals_age_seconds": self._vitals_age_seconds(),
                        "timestamp": time.time(),
                        "status": "no_data"}

        @self.app.get("/target")
        async def get_target_data():
            """同时获取目标距离和心率数据"""
            target_distance = self.target_bin * RANGE_RESOLUTION if self.target_bin is not None else None
            radar_board_online = self._radar_board_online()
            radar_online = self._radar_data_online()
            env = self._environment_snapshot()
            return {
                "heart_rate": float(self.heart_rate) if radar_board_online and self.heart_rate is not None else None,
                "breath_rate": float(self.breath_rate) if radar_board_online and self.breath_rate is not None else None,
                "heart_rate_fresh": bool(self.heart_rate_fresh) if radar_board_online else False,
                "breath_rate_fresh": bool(self.breath_rate_fresh) if radar_board_online else False,
                "vitals_state": self.vitals_state if radar_board_online else "lost",
                "vitals_age_seconds": self._vitals_age_seconds(),
                "last_valid_vitals_at": self.last_valid_vitals_at,
                "target_distance": float(target_distance) if target_distance is not None else None,
                "target_bin": int(self.target_bin) if self.target_bin is not None else None,
                "radar_online": radar_online,
                "radar_board_online": radar_board_online,
                "radar_board_stationary": bool(self.radar_board_stationary),
                "radar_motion_reason": self.radar_motion_reason,
                "radar_motion_delta": self.radar_motion_delta,
                "environment_board_online": env["environment_board_online"],
                "last_environment_heartbeat_at": env["last_environment_heartbeat_at"],
                "environment_age_seconds": env["environment_age_seconds"],
                "temperature_c": env["temperature_c"],
                "raw_temperature_c": env["raw_temperature_c"],
                "temperature_offset_c": env["temperature_offset_c"],
                "humidity_pct": env["humidity_pct"],
                "comfort_status": env["comfort_status"],
                "timestamp": time.time(),
                "status": "ok" if (radar_board_online and (self.heart_rate is not None or target_distance is not None)) else "no_data"
            }

        @self.app.get("/beds")
        async def list_beds():
            return self._all_bed_summaries()

        @self.app.get("/beds/{bed_id}/status")
        async def get_bed_status(bed_id: str):
            return self._status_snapshot_for_bed(bed_id)

        @self.app.get("/status")
        async def get_status(bed_id: Optional[str] = Query(None)):
            """获取系统状态信息"""
            return self._status_snapshot_for_bed(bed_id)

        @self.app.get("/debug/radar")
        async def get_radar_debug():
            """获取雷达UDP帧解析诊断信息"""
            return self._status_snapshot()["radar_debug"]

        @self.app.post("/hardware/edgi-heartbeat")
        async def receive_edgi_heartbeat(heartbeat: EdgiHeartbeat):
            """接收 Edgi/XiaoZhi 开发板基础在线心跳。"""
            bed_id = self._resolve_runtime_bed_id(
                bed_id=heartbeat.bed_id,
                device_id=heartbeat.device_id,
                source=heartbeat.source,
            )
            now = time.time()
            now_text = self._now_iso()
            with self.state_lock:
                self.last_edgi_heartbeat_time = now
                self.last_edgi_heartbeat_at = now_text
                self.last_edgi_bed_id = bed_id
                self._bed_state(bed_id)["edgi"] = {
                    "device_id": heartbeat.device_id,
                    "source": heartbeat.source,
                    "mode": heartbeat.mode,
                    "keyword_online": heartbeat.keyword_online,
                    "snore_guard_enabled": heartbeat.snore_guard_enabled,
                    "received_time": now,
                    "received_at": now_text,
                }
            if bed_id == (self.current_radar_bed_id or DEFAULT_BED_ID):
                self._upsert_timeline()
            return {
                "code": 200,
                "status": "success",
                "message": "Edgi heartbeat received",
                "bed_id": bed_id,
                "edgi_board_online": self._edgi_board_online(),
                "source": heartbeat.source,
                "mode": heartbeat.mode,
                "keyword_online": heartbeat.keyword_online,
                "snore_guard_enabled": heartbeat.snore_guard_enabled,
                "received_at": now_text,
            }

        @self.app.post("/hardware/snore-heartbeat")
        async def receive_snore_heartbeat(heartbeat: SnoreHeartbeat):
            """接收呼噜检测板每秒特征心跳。"""
            bed_id = self._resolve_runtime_bed_id(
                bed_id=heartbeat.bed_id,
                device_id=heartbeat.device_id,
                source=heartbeat.source,
            )
            score = max(0.0, min(1.0, float(heartbeat.snore_score)))
            dbfs = float(heartbeat.dbfs) if heartbeat.dbfs is not None else None
            sound_present = self._snore_sound_present(heartbeat.snore_detected, score, dbfs)
            now = time.time()
            now_text = self._now_iso()
            stop_alarm_event = None
            with self.state_lock:
                self.last_snore_heartbeat_time = now
                self.last_snore_heartbeat_at = now_text
                self.last_snore_bed_id = bed_id
                self.last_edgi_heartbeat_time = now
                self.last_edgi_heartbeat_at = now_text
                self.last_edgi_bed_id = bed_id
                self.snore_session_last_seen_at = now
                self.snore_score = round(score, 3)
                self._bed_state(bed_id)["snore"] = {
                    "device_id": heartbeat.device_id,
                    "source": heartbeat.source,
                    "snore_score": round(score, 3),
                    "snore_detected": bool(heartbeat.snore_detected),
                    "snore_dbfs": dbfs,
                    "snore_level": self._snore_level_from_dbfs(dbfs, score),
                    "received_time": now,
                    "received_at": now_text,
                }
                if dbfs is not None:
                    self.snore_dbfs = dbfs
                    self.last_audio_dbfs = dbfs
                if heartbeat.snore_detected:
                    self.snore_detected = True
                    self.snore_event_count += 1
                    self.last_snore_time = now
                    self.last_snore_at = now_text
                else:
                    recent_snore = self._seconds_since(self.last_snore_time)
                    self.snore_detected = recent_snore is not None and recent_snore <= SNORE_EVENT_HOLD_SECONDS
                stop_alarm_event = self._update_snore_sound_state(
                    sound_present,
                    now,
                    score,
                    dbfs,
                    heartbeat.source,
                )
                if stop_alarm_event is not None:
                    stop_alarm_event["bed_id"] = bed_id
            if bed_id == (self.current_radar_bed_id or DEFAULT_BED_ID):
                self._upsert_timeline()
            return {
                "code": 200,
                "status": "success",
                "message": "呼噜心跳已接收",
                "bed_id": bed_id,
                "snore_score": round(score, 3),
                "snore_dbfs": dbfs,
                "snore_level": self._snore_level_from_dbfs(dbfs, score),
                "snore_detected": self._status_snapshot_for_bed(bed_id)["snore_detected"],
                "sound_present": sound_present,
                "last_snore_stop_fusion": self.last_snore_stop_fusion,
                "alarm_triggered": stop_alarm_event is not None,
                "alarm_event": stop_alarm_event,
            }

        @self.app.post("/hardware/environment-heartbeat")
        async def receive_environment_heartbeat(heartbeat: EnvironmentHeartbeat):
            """接收 M55 从 M33 AHT20 共享内存读取后转发的温湿度心跳。"""
            bed_id = self._resolve_runtime_bed_id(
                bed_id=heartbeat.bed_id,
                device_id=heartbeat.device_id,
                source=heartbeat.source,
            )
            sensor_ok = bool(heartbeat.sensor_ok)
            raw_temperature = round(float(heartbeat.temperature_c), 1)
            temperature = self._calibrate_environment_temperature(raw_temperature)
            humidity = round(max(0.0, min(100.0, float(heartbeat.humidity_pct))), 1)
            comfort_status = comfort_status_for(temperature, humidity, sensor_ok=sensor_ok, online=sensor_ok)
            now = time.time()
            now_text = self._now_iso()
            with self.state_lock:
                self.last_environment_heartbeat_time = now
                self.last_environment_heartbeat_at = now_text
                self.last_environment_bed_id = bed_id
                self.last_edgi_heartbeat_time = now
                self.last_edgi_heartbeat_at = now_text
                self.last_edgi_bed_id = bed_id
                self.environment_sensor_ok = sensor_ok
                self.raw_temperature_c = raw_temperature if sensor_ok else None
                self.temperature_c = temperature if sensor_ok else None
                self.humidity_pct = humidity if sensor_ok else None
                self._bed_state(bed_id)["environment"] = {
                    "device_id": heartbeat.device_id,
                    "source": heartbeat.source,
                    "sensor_ok": sensor_ok,
                    "temperature_c": temperature if sensor_ok else None,
                    "raw_temperature_c": raw_temperature if sensor_ok else None,
                    "humidity_pct": humidity if sensor_ok else None,
                    "comfort_status": comfort_status,
                    "received_time": now,
                    "received_at": now_text,
                }
            if bed_id == (self.current_radar_bed_id or DEFAULT_BED_ID):
                self._upsert_timeline()
            return {
                "code": 200,
                "status": "success",
                "message": "温湿度心跳已接收",
                "bed_id": bed_id,
                "temperature_c": temperature if sensor_ok else None,
                "raw_temperature_c": raw_temperature if sensor_ok else None,
                "temperature_offset_c": ENV_TEMPERATURE_OFFSET_C,
                "humidity_pct": humidity if sensor_ok else None,
                "sensor_ok": sensor_ok,
                "comfort_status": comfort_status,
            }

        @self.app.post("/hardware/snore-session/start")
        async def start_snore_session(payload: Optional[SnoreSessionRequest] = None):
            payload = payload or SnoreSessionRequest()
            bed_id = self._resolve_runtime_bed_id(
                bed_id=payload.bed_id,
                device_id=payload.device_id,
                source=payload.source,
            )
            """呼噜检测板按下 Snore detect 时调用，前端从此刻开始一直显示在线。"""
            now = time.time()
            now_text = self._now_iso()
            with self.state_lock:
                self.snore_session_active = True
                self.snore_session_stopped = False
                self.snore_session_started_at = now
                self.snore_session_started_text = now_text
                self.snore_session_last_seen_at = now
                self.last_snore_heartbeat_time = now
                self.last_snore_heartbeat_at = now_text
                self.last_snore_bed_id = bed_id
                self.last_edgi_heartbeat_time = now
                self.last_edgi_heartbeat_at = now_text
                self.last_edgi_bed_id = bed_id
                self.snore_sound_active = False
                self.snore_sound_started_time = None
                self.snore_sound_started_at = None
                self.last_snore_sound_time = None
                self.last_snore_sound_at = None
                self.last_snore_sound_stop_time = None
                self.last_snore_sound_stop_at = None
                self.last_snore_stop_fusion = None
                self._bed_state(bed_id)["snore"] = {
                    "device_id": payload.device_id,
                    "source": payload.source,
                    "snore_score": 0.0,
                    "snore_detected": False,
                    "snore_dbfs": None,
                    "snore_level": None,
                    "session_active": True,
                    "received_time": now,
                    "received_at": now_text,
                }
            if bed_id == (self.current_radar_bed_id or DEFAULT_BED_ID):
                self._upsert_timeline()
            return {
                "code": 200,
                "status": "success",
                "message": "呼噜检测板 Snore detect 已按下",
                "bed_id": bed_id,
                "snore_board_online": self._snore_board_online(),
                "snore_monitoring": True,
                "snore_paused": False,
                "started_at": now_text,
            }

        @self.app.post("/hardware/snore-session/stop")
        async def stop_snore_session(payload: Optional[SnoreSessionRequest] = None):
            payload = payload or SnoreSessionRequest()
            bed_id = self._resolve_runtime_bed_id(
                bed_id=payload.bed_id,
                device_id=payload.device_id,
                source=payload.source,
            )
            """呼噜监测暂停时调用；Edgi E84 仍保持在线。"""
            now = time.time()
            now_text = self._now_iso()
            with self.state_lock:
                self.snore_session_active = False
                self.snore_session_stopped = True
                self.snore_session_last_seen_at = now
                self.last_edgi_heartbeat_time = now
                self.last_edgi_heartbeat_at = now_text
                self.last_edgi_bed_id = bed_id
                # 让“最近心跳/音频”不再被 5/15 秒窗口认作在线依据
                self.last_snore_heartbeat_time = None
                self.last_audio_received_time = None
                self.snore_sound_active = False
                self.snore_sound_started_time = None
                self.snore_sound_started_at = None
                self.last_snore_sound_time = None
                self.last_snore_sound_at = None
                self.last_snore_sound_stop_time = None
                self.last_snore_sound_stop_at = None
                self.last_snore_stop_fusion = None
                self._bed_state(bed_id)["snore"] = {
                    "device_id": payload.device_id,
                    "source": payload.source,
                    "snore_score": 0.0,
                    "snore_detected": False,
                    "snore_dbfs": None,
                    "snore_level": None,
                    "session_active": False,
                    "received_time": now,
                    "received_at": now_text,
                }
            if bed_id == (self.current_radar_bed_id or DEFAULT_BED_ID):
                self._upsert_timeline()
            return {
                "code": 200,
                "status": "success",
                "message": "呼噜监测已暂停",
                "snore_board_online": self._snore_board_online(),
                "snore_monitoring": False,
                "snore_paused": True,
            }

        @self.app.post("/audio")
        async def receive_audio(request: Request):
            """接收呼噜检测板上传的WAV或原始PCM音频。"""
            body = await request.body()
            if not body:
                return {"code": 400, "status": "error", "message": "没有收到音频数据"}

            audio_dir = Path(current_dir) / "audio_uploads"
            audio_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = audio_dir / f"received_audio_{timestamp}.wav"

            if body[:4] == b"RIFF":
                output_file.write_bytes(body)
                seconds = 0.0
                try:
                    with wave.open(str(output_file), "rb") as wav_file:
                        seconds = wav_file.getnframes() / float(wav_file.getframerate())
                except wave.Error:
                    seconds = len(body) / float(SAMPLE_RATE * SAMPLE_WIDTH * NUM_CHANNELS)
                raw_for_db = body[44:] if len(body) > 44 else body
            else:
                seconds = self._save_raw_audio_as_wav(body, output_file)
                raw_for_db = body

            dbfs = self._estimate_dbfs(raw_for_db)
            now = time.time()
            now_text = self._now_iso()

            with self.state_lock:
                self.audio_upload_count += 1
                self.last_audio_received_time = now
                self.last_audio_received_at = now_text
                self.snore_session_last_seen_at = now
                self.last_audio_file = str(output_file)
                self.last_audio_seconds = round(seconds, 2)
                self.last_audio_dbfs = dbfs
            self._upsert_timeline()

            return {
                "code": 200,
                "status": "success",
                "message": "音频已接收",
                "file": str(output_file),
                "seconds": round(seconds, 2),
                "dbfs": dbfs,
                "snore_score": round(float(self.snore_score or 0.0), 3),
                "snore_level": self._snore_level_from_dbfs(self.snore_dbfs, self.snore_score),
                "snore_detected": bool(self.snore_detected),
            }

        @self.app.get("/detailed")
        async def get_detailed_data():
            """获取详细的处理结果数据"""
            results = self.get_latest_results()
            results.update(self._environment_snapshot())
            # 移除大型数据结构以减少响应大小
            if "cwt_results" in results and results["cwt_results"]:
                results["cwt_results"] = {"available": True}
            if "eemd_results" in results and results["eemd_results"]:
                results["eemd_results"] = {"available": True}
            if "phase_values" in results and results["phase_values"] is not None:
                # 将numpy数组转换为列表
                results["phase_values"] = results["phase_values"].tolist() if hasattr(results["phase_values"], "tolist") else results["phase_values"]
            if "model_prediction" in results and results["model_prediction"]:
                prediction = dict(results["model_prediction"])
                result = prediction.get("result")
                if hasattr(result, "tolist"):
                    prediction["result"] = result.tolist()
                results["model_prediction"] = prediction
            return self._jsonable(results)

        @self.app.get("/beds/{bed_id}/timeline")
        @self.app.get("/timeline")
        async def get_timeline(
            seconds: int = Query(180, ge=10, le=1800),
            bed_id: Optional[str] = None,
        ):
            """获取前端生命体征时间轴。"""
            resolved_bed_id = self._resolve_runtime_bed_id(bed_id=bed_id)
            if resolved_bed_id == (self.current_radar_bed_id or DEFAULT_BED_ID):
                self._upsert_timeline()
            cutoff = time.time() - float(seconds)
            with self.state_lock:
                rows = [
                    row
                    for row in self.timeline
                    if self._parse_iso_seconds(row.get("timestamp")) >= cutoff
                ]
                rows = [
                    {**row, "bed_id": row.get("bed_id") or resolved_bed_id}
                    for row in rows
                    if (row.get("bed_id") or resolved_bed_id) == resolved_bed_id
                ]
                rows = json.loads(json.dumps(rows))
            return {
                "code": 200,
                "status": "success",
                "bed_id": resolved_bed_id,
                "seconds": seconds,
                "data": rows,
                "summary": self._timeline_summary(rows),
            }

        @self.app.get("/beds/{bed_id}/sleep/overview")
        @self.app.get("/sleep/overview")
        async def get_sleep_overview(
            mode: str = Query("live"),
            seconds: int = Query(1800, ge=60, le=7200),
            date: Optional[str] = Query(None),
            userID: Optional[int] = Query(None),
            bed_id: Optional[str] = None,
        ):
            """睡眠看护驾驶舱聚合接口。

            - live 模式：从 self.timeline 截取近 N 秒行 + 内存合成事件。
            - history 模式：优先按 date 过滤 self.timeline（如果该天还有数据）；
              否则空数据但返回正常结构（前端可降级显示）。
            """
            selected_mode = "history" if mode == "history" else "live"
            resolved_bed_id = self._resolve_runtime_bed_id(bed_id=bed_id)
            if resolved_bed_id == (self.current_radar_bed_id or DEFAULT_BED_ID):
                self._upsert_timeline()

            if selected_mode == "history":
                with self.state_lock:
                    snapshot = list(self.timeline)
                if date:
                    snapshot = [row for row in snapshot if (row.get("timestamp") or "").startswith(date)]
                snapshot = [
                    {**row, "bed_id": row.get("bed_id") or resolved_bed_id}
                    for row in snapshot
                    if (row.get("bed_id") or resolved_bed_id) == resolved_bed_id
                ]
                rows = json.loads(json.dumps(snapshot))
            else:
                cutoff = time.time() - float(seconds)
                cutoff_iso = datetime.fromtimestamp(cutoff).isoformat(timespec="seconds")
                with self.state_lock:
                    rows = self._rows_between(self.timeline, cutoff)
                    rows = [
                        {**row, "bed_id": row.get("bed_id") or resolved_bed_id}
                        for row in rows
                        if (row.get("bed_id") or resolved_bed_id) == resolved_bed_id
                    ]
                    rows = json.loads(json.dumps(rows))
                    env = self._environment_snapshot()
                    devices = {
                        "radar_board_online": self._radar_board_online(),
                        "radar_board_stationary": bool(self.radar_board_stationary),
                        "radar_motion_reason": self.radar_motion_reason,
                        "radar_motion_delta": self.radar_motion_delta,
                        "radar_motion_sensor_ready": self.radar_motion_sensor_ready,
                        "snore_board_online": self._snore_board_online(),
                        "snore_monitoring": bool(self.snore_session_active and self._snore_board_online()),
                        "snore_paused": bool(self.snore_session_stopped and self._edgi_board_online()),
                        "environment_board_online": env["environment_board_online"],
                        "environment_sensor_ok": env["environment_sensor_ok"],
                        "voice_board_online": self._voice_board_online(),
                        "edgi_board_online": self._edgi_board_online(),
                        "radar_age_seconds": self._seconds_since(self.last_radar_received_time),
                        "radar_status_age_seconds": self._seconds_since(self.last_radar_status_time),
                        "snore_age_seconds": self._seconds_since(self.last_snore_heartbeat_time),
                        "environment_age_seconds": env["environment_age_seconds"],
                        "voice_age_seconds": self._seconds_since(self.last_voice_received_time),
                        "edgi_age_seconds": self._seconds_since(self.last_edgi_heartbeat_time),
                        "audio_upload_count": self.audio_upload_count,
                        "last_audio_received_at": self.last_audio_received_at,
                        "last_environment_heartbeat_at": self.last_environment_heartbeat_at,
                        "temperature_c": env["temperature_c"],
                        "raw_temperature_c": env["raw_temperature_c"],
                        "temperature_offset_c": env["temperature_offset_c"],
                        "humidity_pct": env["humidity_pct"],
                        "comfort_status": env["comfort_status"],
                        "emergency_active": self._active_emergency_event(resolved_bed_id) is not None,
                    }
                events = self._synthesize_sleep_events(rows) + self._emergency_events_between(cutoff, resolved_bed_id)
                result = self._build_sleep_overview(rows, events, "live", seconds, date, userID, devices)
                result["bed_id"] = resolved_bed_id
                result["bed"] = self._bed_metadata(resolved_bed_id)
                return result

            with self.state_lock:
                env = self._environment_snapshot()
                devices = {
                    "radar_board_online": self._radar_board_online(),
                    "radar_board_stationary": bool(self.radar_board_stationary),
                    "radar_motion_reason": self.radar_motion_reason,
                    "radar_motion_delta": self.radar_motion_delta,
                    "radar_motion_sensor_ready": self.radar_motion_sensor_ready,
                    "snore_board_online": self._snore_board_online(),
                    "snore_monitoring": bool(self.snore_session_active and self._snore_board_online()),
                    "snore_paused": bool(self.snore_session_stopped and self._edgi_board_online()),
                    "environment_board_online": env["environment_board_online"],
                    "environment_sensor_ok": env["environment_sensor_ok"],
                    "voice_board_online": self._voice_board_online(),
                    "edgi_board_online": self._edgi_board_online(),
                    "radar_age_seconds": self._seconds_since(self.last_radar_received_time),
                    "radar_status_age_seconds": self._seconds_since(self.last_radar_status_time),
                    "snore_age_seconds": self._seconds_since(self.last_snore_heartbeat_time),
                    "environment_age_seconds": env["environment_age_seconds"],
                    "voice_age_seconds": self._seconds_since(self.last_voice_received_time),
                    "edgi_age_seconds": self._seconds_since(self.last_edgi_heartbeat_time),
                    "audio_upload_count": self.audio_upload_count,
                    "last_audio_received_at": self.last_audio_received_at,
                    "last_environment_heartbeat_at": self.last_environment_heartbeat_at,
                    "temperature_c": env["temperature_c"],
                    "raw_temperature_c": env["raw_temperature_c"],
                    "temperature_offset_c": env["temperature_offset_c"],
                    "humidity_pct": env["humidity_pct"],
                    "comfort_status": env["comfort_status"],
                    "emergency_active": self._active_emergency_event(resolved_bed_id) is not None,
                }
            events = self._synthesize_sleep_events(rows) + self._emergency_events_between(None, resolved_bed_id)
            result = self._build_sleep_overview(rows, events, "history", seconds, date, userID, devices)
            result["bed_id"] = resolved_bed_id
            result["bed"] = self._bed_metadata(resolved_bed_id)
            return result

        @self.app.get("/beds/{bed_id}/heartdata/selectPage")
        async def select_bed_heart_data_page(
                bed_id: str,
                pageNum: int = Query(1, ge=1),
                pageSize: int = Query(10, ge=1, le=100),
                date: str = Query(None),
                userID: int = Query(None),
        ):
            try:
                resolved_bed_id = self._resolve_runtime_bed_id(bed_id=bed_id)
                result = query_heart_data_by_date(
                    page_num=pageNum,
                    page_size=pageSize,
                    date_str=date,
                    user_id=userID,
                    bed_id=resolved_bed_id,
                )
                return {
                    "code": 200,
                    "msg": "success",
                    "bed_id": resolved_bed_id,
                    "data": result
                }
            except Exception as e:
                return {
                    "code": 500,
                    "msg": f"查询失败: {str(e)}",
                    "data": {"list": [], "total": 0}
                }

        @self.app.get("/heartdata/selectPage")
        async def select_heart_data_page(
                pageNum: int = Query(1, ge=1),
                pageSize: int = Query(10, ge=1, le=100),
                date: str = Query(None),
                userID: int = Query(None)  # 新增参数
        ):
            """分页查询心率数据，支持按日期和用户ID过滤"""
            try:
                result = query_heart_data_by_date(
                    page_num=pageNum,
                    page_size=pageSize,
                    date_str=date,
                    user_id=userID  # 传入用户ID
                )
                return {
                    "code": 200,
                    "msg": "success",
                    "data": result
                }
            except Exception as e:
                return {
                    "code": 500,
                    "msg": f"查询失败: {str(e)}",
                    "data": {"list": [], "total": 0}
                }

    def set_decomposition_params(self, enable=None, decomp_type=None, cwt_scales=None, cwt_wavelet=None,
                                eemd_noise=None, eemd_ensemble=None, eemd_max_imf=None):
        """设置信号分解参数

        参数:
            enable: 是否启用信号分解
            decomp_type: 信号分解类型: "cwt" 或 "eemd"
            cwt_scales: CWT尺度参数
            cwt_wavelet: CWT小波类型
            eemd_noise: EEMD噪声幅度
            eemd_ensemble: EEMD集合大小
            eemd_max_imf: EEMD最大IMF数量
        """
        global DECOMPOSE_SIGNAL, DECOMP_TYPE, CWT_SCALES, CWT_WAVELET, EEMD_NOISE_WIDTH, EEMD_ENSEMBLE_SIZE, EEMD_MAX_IMF

        if enable is not None:
            DECOMPOSE_SIGNAL = enable

        if decomp_type is not None:
            if decomp_type in ["cwt", "eemd"]:
                DECOMP_TYPE = decomp_type
            else:
                print(f"警告：不支持的分解类型 '{decomp_type}'，仅支持 'cwt' 或 'eemd'")

        if cwt_scales is not None:
            CWT_SCALES = cwt_scales

        if cwt_wavelet is not None:
            CWT_WAVELET = cwt_wavelet

        if eemd_noise is not None:
            EEMD_NOISE_WIDTH = eemd_noise

        if eemd_ensemble is not None:
            EEMD_ENSEMBLE_SIZE = eemd_ensemble

        if eemd_max_imf is not None:
            EEMD_MAX_IMF = eemd_max_imf

        print(f"信号分解参数更新: 启用={DECOMPOSE_SIGNAL}, 类型={DECOMP_TYPE}")
        if DECOMP_TYPE == "cwt":
            print(f"CWT参数: 波形={CWT_WAVELET}, 尺度={CWT_SCALES[-1]}")
        else:
            print(f"EEMD参数: 噪声={EEMD_NOISE_WIDTH}, 集合大小={EEMD_ENSEMBLE_SIZE}, IMF数量={EEMD_MAX_IMF}")

    def start(self):
        """启动雷达数据接收和处理"""
        self.running = True
        self.start_time = time.time()  # 重置启动时间
        self.last_status_time = time.time()
        self.frames_since_last_process = 0  # 重置帧计数器

        # 创建UDP套接字
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if hasattr(socket, "SIO_UDP_CONNRESET"):
            self.socket.ioctl(socket.SIO_UDP_CONNRESET, False)

        # 绑定套接字到本地端口
        self.socket.bind(("0.0.0.0", self.server_port))

        # 启动处理线程
        self.processing_thread = threading.Thread(target=self._process_data)
        self.processing_thread.daemon = True
        self.processing_thread.start()

        # 启动状态报告线程
        self.status_thread = threading.Thread(target=self._report_status)
        self.status_thread.daemon = True
        self.status_thread.start()

        # 如果启用API，启动API服务器
        if self.api_enabled and self.app:
            self.api_thread = threading.Thread(target=self._run_api_server)
            self.api_thread.daemon = True
            self.api_thread.start()
            print(f"API服务已启动在 http://0.0.0.0:{self.api_port}")

        print("================================================================================")
        print("实时雷达数据处理器启动")
        print("================================================================================")
        print(f"雷达连接: {self.server_ip}:{self.server_port} | 帧率: {FRAME_RATE}Hz | 样本数: {get_param('num_samples')}")
        print(f"窗口: {WINDOW_SIZE}帧/{WINDOW_SIZE_SECONDS}秒 | 步长: {STEP_SIZE}帧/{STEP_SIZE_SECONDS}秒")
        print(f"波长: {WAVELENGTH*1000:.2f}mm | 分辨率: {RANGE_RESOLUTION*100:.1f}cm")

        # 启动雷达数据传输
        print("启动雷达数据传输...")
        if self.server_ip and self.server_ip != "0.0.0.0":
            self.socket.sendto('{"radar_transmission":"enable"}'.encode(), (self.server_ip, self.server_port))

        # 开始接收数据
        try:
                while self.running:
                    # 接收一帧数据
                    try:
                        data, adr = self.socket.recvfrom(BUFFER_SIZE)
                    except ConnectionResetError as exc:
                        print(f"UDP receive warning: {exc}")
                        continue

                    if data and data[0] == RADAR_STATUS_COMMAND:
                        self._handle_radar_status_packet(data)
                        continue

                    if not self._is_valid_radar_data_packet(data):
                        continue

                    # 获取帧号
                    frame_number = int.from_bytes(data[2:6], 'little')

                    # 打印帧号（每30帧打印一次，即约每秒打印一次）
                    if self.total_frames_received % 30 == 0:
                    # 简化帧信息输出
                        print(f"帧接收: #{frame_number} | 总帧数: {self.total_frames_received+1} | 样本数: {len(data[6:]) // 2}")

                    # 更新统计信息
                    self.total_frames_received += 1
                    self.period_frames_received += 1
                    self.last_frame_number = frame_number
                    self.frames_since_last_process += 1  # 使用类属性记录新帧
                    self.last_radar_received_time = time.time()
                    self.last_radar_received_at = self._now_iso()
                    self.current_radar_bed_id = self._resolve_runtime_bed_id(
                        radar_ip=adr[0] if adr else None
                    )
                    self.radar_board_stationary = True
                    self.radar_motion_reason = "disabled"
                    self._update_packet_debug(data, frame_number)

                    # 将数据添加到缓冲区
                    self.data_buffer.append(data)

                    # 限制缓冲区大小
                    if len(self.data_buffer) > WINDOW_SIZE:
                        self.data_buffer.pop(0)

        except KeyboardInterrupt:
            print("用户中断，正在关闭...")
        finally:
            self.stop()

    def _run_api_server(self):
        """在单独的线程中运行FastAPI服务器"""
        try:
            uvicorn.run(self.app, host="0.0.0.0", port=self.api_port, log_level="info")
        except Exception as e:
            print(f"API服务器启动失败: {e}")

    def _report_status(self):
        """状态报告线程"""
        while self.running:
            # 每5秒打印一次详细状态信息
            time.sleep(5)

            # 计算数据率
            current_time = time.time()
            period_elapsed = current_time - self.last_status_time
            total_elapsed = current_time - self.start_time

            # 计算周期内的帧率
            period_frames_per_second = self.period_frames_received / period_elapsed if period_elapsed > 0 else 0

            # 计算总体平均帧率
            total_frames_per_second = self.total_frames_received / total_elapsed if total_elapsed > 0 else 0

            # 计算处理率
            period_processing_per_second = self.period_frames_processed / period_elapsed if period_elapsed > 0 else 0
            total_processing_per_second = self.processing_count / total_elapsed if total_elapsed > 0 else 0

            # 打印状态 - 精简版
            print("\n--- 状态报告 ---")
            print(f"运行: {total_elapsed:.1f}秒 | 帧率: {period_frames_per_second:.1f}/s (累计: {total_frames_per_second:.1f}/s)")
            print(f"处理: {self.processing_count}次 | 最近帧: #{self.last_frame_number} | 进度: {self.frames_since_last_process}/{STEP_SIZE}")
            print(f"缓冲区: {len(self.data_buffer)}/{WINDOW_SIZE}")
            if hasattr(self, 'target_bin') and self.target_bin is not None:
                target_distance = self.target_bin * RANGE_RESOLUTION
                print(f"目标: 距离 {target_distance:.2f}米 (bin{self.target_bin})")
            print("----------------")

            # 只重置周期计数器，保留总计数器
            self.period_frames_received = 0
            self.period_frames_processed = 0
            self.last_status_time = current_time

    def stop(self):
        """停止数据接收和处理"""
        self.running = False

        if self.socket:
            # 停止雷达数据传输
            if self.server_ip and self.server_ip != "0.0.0.0":
                self.socket.sendto('{"radar_transmission":"disable"}'.encode(), (self.server_ip, self.server_port))
            self.socket.close()
            self.socket = None

        print("实时雷达数据处理器已停止")

    def _process_data(self):
        """数据处理线程"""
        while self.running:
            # 只有当缓冲区满且累积了足够步长的新帧时才处理
            if len(self.data_buffer) < WINDOW_SIZE:
                time.sleep(0.1)
                continue

            # 检查是否累积了足够的新帧作为滑动步长
            if self.frames_since_last_process < STEP_SIZE and self.processing_count > 0:
                time.sleep(0.1)
                continue

            try:
                print(f"\n>> 开始处理: {len(self.data_buffer)}帧 | 累积帧数: {self.frames_since_last_process}")
                process_start_time = time.time()

                # 重置计数器
                self.frames_since_last_process = 0

                # 解析数据帧
                frames = []
                for frame_data in self.data_buffer:
                    # 跳过前6个字节（包含帧号信息）
                    radar_data = frame_data[6:]

                    # 解析雷达数据为float16实数；每个样本是2字节
                    num_samples = len(radar_data) // 2  # 2字节/样本
                    samples = np.frombuffer(radar_data[:num_samples * 2], dtype=np.float16).astype(np.float32)

                    frames.append(samples)

                # 将帧数据转换为numpy数组
                # 假设格式为 [frames, antennas, chirps, samples]
                # 这里我们假设只有一个天线和一个chirp，具体需要根据实际雷达配置调整
                num_frames = len(frames)
                samples_per_frame = len(frames[0])

                print(f"步骤1: 数据整形 [{num_frames} 帧, {samples_per_frame} 样本/帧]")

                # 重塑数据格式为 [frames, 1, 1, samples]
                radar_data_3d = np.zeros((num_frames, 1, 1, samples_per_frame), dtype=complex)
                for i, frame in enumerate(frames):
                    # 将实数数据转换为复数格式（实部为数据，虚部为0）
                    radar_data_3d[i, 0, 0, :] = frame + 0j

                # 步骤1: 距离FFT
                print(f">> 处理: FFT -> MTI滤波 -> 提取相位...")
                range_profile = range_fft(radar_data_3d, window=WINDOW_TYPE)

                # 步骤2: MTI滤波
                mti_filtered = mti_filter(range_profile)

                # 步骤3: 提取2D数据 (只选择第一根天线和第一个chirp)
                data_2d = mti_filtered[:, 0, 0, :]

                # 步骤4: 提取相位和目标bin
                phase_values, target_bin = extract_phase(data_2d, RANGE_RESOLUTION, WAVELENGTH, False)

                # 保存处理结果到实例变量
                self.phase_values = phase_values
                self.breath_periodicity = estimate_breath_periodicity(phase_values)
                self.target_bin = target_bin
                target_distance = target_bin * RANGE_RESOLUTION if target_bin is not None else None

                # 步骤5: 执行存在检测。呼噜声响起及停止确认窗口内临时关闭存在性检测，
                # 避免呼噜/疑似暂停场景下雷达分析被门控挡住。
                snore_presence_bypass = self._snore_presence_bypass_active()
                self.presence_bypassed_by_snore = snore_presence_bypass
                if snore_presence_bypass:
                    latest_frame_data = data_2d[-1:, :]
                    self.presence_detector.detect_presence(
                        latest_frame_data,
                        target_distance=target_distance,
                    )
                    raw_presence_debug = self._presence_debug_state()
                    self.presence_detected = True
                    self.presence_stable = True
                    self.presence_detector.last_debug = {
                        "presence_signal": True,
                        "presence_energy_stable": True,
                        "presence_distance_stable": True,
                        "presence_distance_span": 0.0,
                        "presence_distance": round(float(target_distance), 4) if target_distance is not None else None,
                        "presence_distance_min_m": PRESENCE_DISTANCE_MIN_M,
                        "presence_distance_max_m": PRESENCE_DISTANCE_MAX_M,
                        "presence_distance_stability_span_m": PRESENCE_DISTANCE_STABILITY_SPAN_M,
                        "presence_detection_value": raw_presence_debug.get("presence_detection_value"),
                        "presence_detection_threshold": raw_presence_debug.get("presence_detection_threshold"),
                        "presence_detection_bin": raw_presence_debug.get("presence_detection_bin"),
                        "presence_below_threshold": bool(raw_presence_debug.get("presence_below_threshold")),
                        "presence_stable": True,
                    }
                    print(">> 呼噜响起或刚停止，临时关闭存在性检测，直接执行雷达呼吸/模型分析")
                elif ENABLE_PRESENCE_DETECTION:
                    # 提取最新一帧的数据用于存在检测
                    latest_frame_data = data_2d[-1:, :]  # 取最后一帧
                    self.presence_detected, self.presence_stable = self.presence_detector.detect_presence(
                        latest_frame_data,
                        target_distance=target_distance,
                    )
                    presence_debug = self._presence_debug_state()
                    print(
                        f">> 存在检测: 原始={self.presence_detected}, "
                        f"能量稳定={presence_debug.get('presence_energy_stable')}, "
                        f"距离稳定={presence_debug.get('presence_distance_stable')}, "
                        f"最终={self.presence_stable}"
                    )
                else:
                    # 如果未启用存在检测，则默认认为有人存在
                    self.presence_detected = True
                    self.presence_stable = True
                    self.presence_bypassed_by_snore = False
                    self.presence_detector.last_debug = {
                        "presence_signal": True,
                        "presence_energy_stable": True,
                        "presence_distance_stable": True,
                        "presence_distance_span": 0.0,
                        "presence_distance": round(float(target_distance), 4) if target_distance is not None else None,
                        "presence_distance_min_m": PRESENCE_DISTANCE_MIN_M,
                        "presence_distance_max_m": PRESENCE_DISTANCE_MAX_M,
                        "presence_distance_stability_span_m": PRESENCE_DISTANCE_STABILITY_SPAN_M,
                        "presence_detection_value": None,
                        "presence_detection_threshold": 1.01,
                        "presence_detection_bin": None,
                        "presence_below_threshold": False,
                        "presence_stable": True,
                    }

                # 步骤6: 只有在检测到人存在时才执行信号分解和心率计算
                self._update_night_absence_monitor(process_start_time)

                if self.presence_stable and DECOMPOSE_SIGNAL:
                    print(f">> 检测到人体存在，执行信号分解: 类型={DECOMP_TYPE}...")

                    # 清空之前的结果
                    self.cwt_results = None
                    self.eemd_results = None
                    self.model_prediction = None  # 清空模型预测结果
                    self.heart_rate_fresh = False
                    self.breath_rate_fresh = False

                    # 应用CWT (连续小波变换)
                    if DECOMP_TYPE == "cwt":
                        try:
                            cwt_start = time.time()
                            # 使用提取的相位信号进行CWT分析
                            cwt_coeffs, cwt_freqs = apply_cwt(
                                phase_values,
                                scales=CWT_SCALES,
                                wavelet=CWT_WAVELET,
                                sampling_period=1.0/FRAME_RATE
                            )
                            cwt_time = time.time() - cwt_start
                            print(f">> CWT完成: 系数形状 {cwt_coeffs.shape}, 用时: {cwt_time*1000:.0f}ms")

                            # 计算CWT能量谱
                            cwt_power = np.abs(cwt_coeffs)**2

                            # 存储CWT结果
                            self.cwt_results = {
                                'coeffs': cwt_coeffs,
                                'freqs': cwt_freqs,
                                'power': cwt_power
                            }

                            # 如果启用了模型推理，使用CWT模型进行预测
                            if self.enable_model_inference and self.cwt_model is not None:
                                try:
                                    # 准备模型输入数据
                                    model_input = self.prepare_model_input(cwt_coeffs, "cwt")

                                    # 执行模型推理
                                    predict_start = time.time()
                                    prediction = self.cwt_model.predict(model_input, verbose=0)
                                    predict_time = time.time() - predict_start

                                    # 提取心率预测值 (假设模型输出的第一个值是心率)
                                    if prediction is not None and len(prediction) > 0:
                                        # 简单假设：预测值直接是心率
                                        self.heart_rate = float(prediction[0][0])
                                        self.heart_rate_fresh = self._valid_heart_value(self.heart_rate)
                                        raw_breath_rate, breath_quality = estimate_breath_rate_fft_with_quality(self.phase_values)
                                        self._update_breath_rate_estimate(raw_breath_rate, breath_quality)
                                    # 保存预测结果
                                    self.model_prediction = {
                                        'type': 'cwt',
                                        'result': prediction,
                                        'time': predict_time,
                                        'heart_rate': self.heart_rate,
                                        'breath_rate': self.breath_rate,
                                        'breath_quality': self.breath_rate_quality,
                                    }

                                    print(f">> 模型推理完成: 形状={prediction.shape}, 用时={predict_time*1000:.0f}ms")
                                except Exception as e:
                                    print(f"模型推理错误: {e}")

                        except Exception as e:
                            print(f"CWT分析出错: {e}")
                            self.cwt_results = None

                    # 应用EEMD (集合经验模态分解)
                    elif DECOMP_TYPE == "eemd":
                        try:
                            eemd_start = time.time()
                            # 使用提取的相位信号进行EEMD分析
                            imfs = apply_eemd(
                                phase_values,
                                noise_width=EEMD_NOISE_WIDTH,
                                ensemble_size=EEMD_ENSEMBLE_SIZE,
                                max_imf=EEMD_MAX_IMF
                            )
                            eemd_time = time.time() - eemd_start
                            print(f">> EEMD完成: IMF数量 {imfs.shape[0]}, 用时: {eemd_time*1000:.0f}ms")

                            # 存储EEMD结果
                            self.eemd_results = {
                                'imfs': imfs
                            }

                            # 如果启用了模型推理，使用EEMD模型进行预测
                            if self.enable_model_inference and self.eemd_model is not None:
                                try:
                                    # 准备模型输入数据
                                    model_input = self.prepare_model_input(imfs, "eemd")

                                    # 执行模型推理
                                    predict_start = time.time()
                                    prediction = self.eemd_model.predict(model_input, verbose=0)
                                    predict_time = time.time() - predict_start

                                    # 提取心率预测值 (假设模型输出的第一个值是心率)
                                    if prediction is not None and len(prediction) > 0:
                                        # 简单假设：预测值直接是心率
                                        self.heart_rate = float(prediction[0][0])
                                        self.heart_rate_fresh = self._valid_heart_value(self.heart_rate)
                                        raw_breath_rate, breath_quality = estimate_breath_rate_fft_with_quality(self.phase_values)
                                        self._update_breath_rate_estimate(raw_breath_rate, breath_quality)

                                    # 保存预测结果
                                    self.model_prediction = {
                                        'type': 'eemd',
                                        'result': prediction,
                                        'time': predict_time,
                                        'heart_rate': self.heart_rate,
                                        'breath_rate': self.breath_rate,
                                        'breath_quality': self.breath_rate_quality,
                                    }

                                    print(f">> 模型推理完成: 形状={prediction.shape}, 用时={predict_time*1000:.0f}ms")
                                except Exception as e:
                                    print(f"模型推理错误: {e}")

                        except Exception as e:
                            print(f"EEMD分析出错: {e}")
                            self.eemd_results = None
                    self._finalize_vitals_window()
                else:
                    if not self.presence_stable:
                        print(">> 未检测到人体存在，跳过信号分解和心率计算")
                    if not self.presence_stable:
                        self._apply_vitals_hold_or_loss()
                # 更新显示数据
                process_end_time = time.time()
                self._update_sample_debug(self.data_buffer[-1], frames[-1], target_bin, target_distance)

                if self.presence_stable and self.heart_rate is not None:
                    breath_str = f", 呼吸: {self.breath_rate:.1f} BPM" if self.breath_rate is not None else ""
                    print(f">> 心率预测: {self.heart_rate:.1f} BPM{breath_str}")

                # 更新统计
                self.processing_count += 1
                self.period_frames_processed += 1
                self._upsert_timeline()

            except Exception as e:
                print(f"处理数据时出错: {e}")
                import traceback
                traceback.print_exc()

    def prepare_model_input(self, data, data_type):
        """
        准备模型输入数据

        参数:
            data: 输入数据 (CWT系数或EEMD IMFs)
            data_type: 数据类型 'cwt' 或 'eemd'

        返回:
            适合模型输入的numpy数组
        """
        if data_type == "cwt":
            # CWT系数通常形状为 (scales, signal_length) 即 (64, 300)
            # 模型期望的输入形状为 (batch_size, signal_length, scales) 即 (None, 30, 64)
            # 需要转置并添加batch维度
            model_input = np.transpose(data)  # 转置后变为(300, 64)
            model_input = np.expand_dims(model_input, axis=0)  # 添加batch维度，变为(1, 30, 64)
            print(f"准备CWT模型输入: 形状={model_input.shape}")
            return model_input

        elif data_type == "eemd":
            # EEMD IMFs通常形状为 (n_imfs, signal_length)
            # 假设模型期望的输入形状为 (batch_size, signal_length, n_imfs)
            model_input = np.transpose(data)  # 转置后变为(signal_length, n_imfs)
            model_input = np.expand_dims(model_input, axis=0)  # 添加batch维度
            print(f"准备EEMD模型输入: 形状={model_input.shape}")
            return model_input

        else:
            raise ValueError(f"不支持的数据类型: {data_type}")

    # 获取处理结果的方法
    def get_latest_results(self):
        """获取最新的处理结果"""
        radar_board_online = self._radar_board_online()
        results = {
            'phase_values': self.phase_values,
            'target_bin': self.target_bin,
            'target_distance': self.target_bin * RANGE_RESOLUTION if self.target_bin is not None else None,
            'cwt_results': self.cwt_results,
            'eemd_results': self.eemd_results,
            'model_prediction': self.model_prediction,
            'heart_rate': self.heart_rate if radar_board_online else None,
            'breath_rate': self.breath_rate if radar_board_online else None,
            'breath_periodicity': self.breath_periodicity if radar_board_online else 0.0,
            'heart_rate_fresh': bool(self.heart_rate_fresh) if radar_board_online else False,
            'breath_rate_fresh': bool(self.breath_rate_fresh) if radar_board_online else False,
            'vitals_state': self.vitals_state if radar_board_online else "lost",
            'vitals_age_seconds': self._vitals_age_seconds(),
            'last_valid_vitals_at': self.last_valid_vitals_at,
            'processing_count': self.processing_count,
            'timestamp': time.time()
        }
        return results

if __name__ == '__main__':
    # 命令行参数处理
    import argparse

    parser = argparse.ArgumentParser(description='实时雷达数据处理器')
    parser.add_argument('--ip', type=str, default='0.0.0.0', help='雷达设备IP地址')
    parser.add_argument('--port', type=int, default=9988, help='雷达设备端口号')
    # 信号分解参数
    parser.add_argument('--decomp-type', type=str, choices=['cwt', 'eemd'], default=DECOMP_TYPE,
                        help=f'信号分解类型: cwt 或 eemd，默认: {DECOMP_TYPE}')
    parser.add_argument('--cwt-wavelet', type=str, default=CWT_WAVELET, help=f'CWT小波类型，默认：{CWT_WAVELET}')
    parser.add_argument('--cwt-scales', type=int, default=CWT_SCALES[-1], help=f'CWT尺度范围（1-指定值），默认：1-{CWT_SCALES[-1]}')
    parser.add_argument('--eemd-noise', type=float, default=EEMD_NOISE_WIDTH, help=f'EEMD噪声幅度，默认：{EEMD_NOISE_WIDTH}')
    parser.add_argument('--eemd-ensemble', type=int, default=EEMD_ENSEMBLE_SIZE, help=f'EEMD集合大小，默认：{EEMD_ENSEMBLE_SIZE}')
    parser.add_argument('--eemd-imf', type=int, default=EEMD_MAX_IMF, help=f'EEMD最大IMF数量，默认：{EEMD_MAX_IMF}')
    # 模型参数
    parser.add_argument('--no-model', action='store_true', help='禁用模型推理')
    parser.add_argument('--cwt-model', type=str, default=None, help='CWT模型路径')
    parser.add_argument('--eemd-model', type=str, default=None, help='EEMD模型路径')
    # API参数
    parser.add_argument('--no-api', action='store_true', help='禁用FastAPI接口')
    parser.add_argument('--api-port', type=int, default=8081, help='API服务器端口')
    # 存在检测参数
    parser.add_argument('--no-presence', action='store_true', help='禁用存在检测功能')
    parser.add_argument('--presence-history', type=int, default=PRESENCE_HISTORY_LENGTH, help=f'存在检测历史长度，默认：{PRESENCE_HISTORY_LENGTH}')
    parser.add_argument('--presence-threshold', type=int, default=PRESENCE_COUNT_THRESHOLD, help=f'存在检测计数阈值，默认：{PRESENCE_COUNT_THRESHOLD}')

    args = parser.parse_args()

    # 更新信号分解参数
    DECOMP_TYPE = args.decomp_type
    CWT_WAVELET = args.cwt_wavelet
    CWT_SCALES = np.arange(1, args.cwt_scales + 1)  # 根据用户输入的最大值生成尺度范围
    EEMD_NOISE_WIDTH = args.eemd_noise
    EEMD_ENSEMBLE_SIZE = args.eemd_ensemble
    EEMD_MAX_IMF = args.eemd_imf

    # 更新存在检测参数
    ENABLE_PRESENCE_DETECTION = not args.no_presence
    PRESENCE_HISTORY_LENGTH = args.presence_history
    PRESENCE_COUNT_THRESHOLD = args.presence_threshold

    # 创建并启动实时处理器
    processor = RealtimeRadarProcessor(
        server_ip=args.ip,
        server_port=args.port,
        load_models=not args.no_model,
        cwt_model_path=args.cwt_model,
        eemd_model_path=args.eemd_model,
        api_enabled=not args.no_api,
        api_port=args.api_port
    )

    print(f"信号分解功能: 已启用 (类型: {DECOMP_TYPE})")

    if DECOMP_TYPE == "cwt":
        print(f"CWT参数: 小波={CWT_WAVELET}, 尺度范围=1-{CWT_SCALES[-1]}")

    if DECOMP_TYPE == "eemd":
        print(f"EEMD参数: 噪声={EEMD_NOISE_WIDTH}, 集合大小={EEMD_ENSEMBLE_SIZE}, 最大IMF={EEMD_MAX_IMF}")

    # 打印存在检测状态
    if ENABLE_PRESENCE_DETECTION:
        print(f"存在检测: 已启用 (历史长度={PRESENCE_HISTORY_LENGTH}, 阈值={PRESENCE_COUNT_THRESHOLD})")
    else:
        print("存在检测: 未启用")

    # 打印模型状态
    if processor.enable_model_inference:
        print("模型推理: 已启用")
        if DECOMP_TYPE == "cwt":
            if processor.cwt_model:
                print(f"  - CWT模型已加载")
            else:
                print(f"  - CWT模型未加载")
        elif DECOMP_TYPE == "eemd":
            if processor.eemd_model:
                print(f"  - EEMD模型已加载")
            else:
                print(f"  - EEMD模型未加载")
    else:
        print("模型推理: 未启用")

    # 打印API状态
    if processor.api_enabled:
        print(f"API服务: 已启用 (端口: {processor.api_port})")
        print(f"  - 心率API: http://localhost:{processor.api_port}/heartrate")
        print(f"  - 目标数据API: http://localhost:{processor.api_port}/target")
        print(f"  - 状态API: http://localhost:{processor.api_port}/status")
    else:
        print("API服务: 未启用")

    try:
        processor.start()
    except KeyboardInterrupt:
        print("程序被用户中断")
    finally:
        processor.stop()
