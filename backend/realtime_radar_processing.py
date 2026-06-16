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
from datetime import datetime
from pathlib import Path
from scipy import signal
from radar_func import range_fft, mti_filter, extract_phase

# 导入信号分解模块
from signal_decomposition import apply_cwt, apply_eemd

# 导入存在检测模块
from presence_detection import RadarPresenceDetector

# 导入FastAPI相关模块
from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from typing import Dict, Any, Optional
import json

# 导入数据库操作模块
from db import create_user, get_user_by_username, verify_password, save_vitals_with_user, query_heart_data_by_date

# 确保当前目录在Python路径中，便于导入自定义模块
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

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
PRESENCE_COUNT_THRESHOLD = 2                  # 存在检测计数阈值
BOARD_TIMEOUT_SECONDS = 5.0                   # 开发板离线判定超时
ENVIRONMENT_BOARD_TIMEOUT_SECONDS = 15.0       # 温湿度板离线判定超时
SNORE_BOARD_TIMEOUT_SECONDS = 15.0             # 呼噜板离线判定超时（10 秒一包音频，宽松一些）
VOICE_BOARD_TIMEOUT_SECONDS = 30.0             # 语音事件到达后暂时标记小智语音链路在线
EDGI_BOARD_TIMEOUT_SECONDS = 60.0              # 任一 Edgi 模块心跳后的整板在线宽限期
SNORE_SESSION_GRACE_SECONDS = 30.0             # 呼噜板按下 Snore detect 后保持在线的最长静默期
TIMELINE_RETENTION_SECONDS = 7200             # 时间轴保留时长
SAMPLE_RATE = 16000                           # 呼噜板音频采样率
SAMPLE_WIDTH = 2                              # int16 PCM
NUM_CHANNELS = 2                              # 呼噜板音频双声道
SNORE_EVENT_HOLD_SECONDS = 180.0              # 呼噜事件状态保持时间

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


def estimate_breath_rate_fft(phase_signal, fs=FRAME_RATE, breath_band=(0.1, 0.5)):
    """
    使用 FFT + 带通 + 质心法峰值检测估计呼吸率
    """
    if phase_signal is None or len(phase_signal) < 10:
        return None

    N = len(phase_signal)
    if N % 2 != 0:
        phase_signal = phase_signal[:-1]
        N -= 1

    # 窗函数
    windowed = phase_signal * np.hanning(N)

    # 零填充（提高插值精度）
    N_fft = max(1024, 8 * N)
    fft_vals = np.fft.rfft(windowed, n=N_fft)
    freqs = np.fft.rfftfreq(N_fft, d=1.0 / fs)
    magnitude = np.abs(fft_vals)

    # 找呼吸频段范围
    low_idx = np.searchsorted(freqs, breath_band[0])
    high_idx = np.searchsorted(freqs, breath_band[1])
    if high_idx <= low_idx:
        return None

    # 呼吸频段的幅度谱
    band_magnitude = magnitude[low_idx:high_idx]
    band_freqs = freqs[low_idx:high_idx]

    # 找到最大峰值
    peak_idx_in_band = np.argmax(band_magnitude)
    if peak_idx_in_band == 0 or peak_idx_in_band == len(band_magnitude) - 1:
        # 如果峰值在边界，直接用原始频率
        peak_freq = band_freqs[peak_idx_in_band]
    else:
        # 使用质心法在峰值周围一个小邻域内求重心
        # 取峰值前后各 2 个点（可根据需要调整）
        neighborhood_size = 2
        start = max(0, peak_idx_in_band - neighborhood_size)
        end = min(len(band_magnitude), peak_idx_in_band + neighborhood_size + 1)

        # 局部幅度和频率
        local_mag = band_magnitude[start:end]
        local_freqs = band_freqs[start:end]

        # 质心法：频率 = Σ(mag * freq) / Σ(mag)
        weighted_sum = np.sum(local_mag * local_freqs)
        mag_sum = np.sum(local_mag)
        if mag_sum > 1e-12:
            peak_freq = weighted_sum / mag_sum
        else:
            peak_freq = band_freqs[peak_idx_in_band]

    breath_rate_bpm = peak_freq * 60.0

    # 合理性检查
    if 6.1 <= breath_rate_bpm <= 30:
        return breath_rate_bpm
    else:
        return 0

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
            count_threshold=PRESENCE_COUNT_THRESHOLD
        )
        self.presence_detected = False
        self.presence_stable = False

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
        self.last_snore_heartbeat_time = None
        self.last_snore_heartbeat_at = None
        self.last_environment_heartbeat_time = None
        self.last_environment_heartbeat_at = None
        self.last_voice_received_time = None
        self.last_voice_received_at = None
        self.last_edgi_heartbeat_time = None
        self.last_edgi_heartbeat_at = None
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
            "presence_stable": False,
        }

        # 结果存储
        self.phase_values = None            # 最近一次处理的相位值
        self.target_bin = None              # 最近一次处理的目标bin
        self.cwt_results = None             # 最近一次CWT分析结果
        self.eemd_results = None            # 最近一次EEMD分析结果
        self.model_prediction = None        # 最近一次模型预测结果
        self.heart_rate = None              # 最近一次心率预测值
        self.breath_rate= None              # 最近一次呼吸预测值
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
                        cwt_model_path = os.path.join(current_dir, 'trained_models', 'DeepStateSpace_CWT_best.keras')
                    else:
                        cwt_model_path = os.path.abspath(cwt_model_path)
                    if eemd_model_path is None:
                        eemd_model_path = os.path.join(current_dir, 'trained_models', 'DeepStateSpace_EEMD_best.keras')
                    else:
                        eemd_model_path = os.path.abspath(eemd_model_path)

                    # 根据当前分解方法加载对应模型
                    if DECOMP_TYPE == "cwt":
                        print(f"检查CWT模型: {cwt_model_path}")
                        if os.path.exists(cwt_model_path):
                            print(f"加载CWT模型: {cwt_model_path}")
                            self.cwt_model = keras.models.load_model(cwt_model_path)
                            print(f"CWT模型加载成功: {self.cwt_model.name}")
                        else:
                            print(f"警告: CWT模型文件不存在 - {cwt_model_path}")
                    elif DECOMP_TYPE == "eemd":
                        print(f"检查EEMD模型: {eemd_model_path}")
                        if os.path.exists(eemd_model_path):
                            print(f"加载EEMD模型: {eemd_model_path}")
                            self.eemd_model = keras.models.load_model(eemd_model_path)
                            print(f"EEMD模型加载成功: {self.eemd_model.name}")
                        else:
                            print(f"警告: EEMD模型文件不存在 - {eemd_model_path}")
                else:
                    print("警告：TensorFlow/Keras未导入，无法加载模型")
                    self.enable_model_inference = False
            except Exception as e:
                print(f"加载模型时出错: {e}")
                self.enable_model_inference = False
                import traceback
                traceback.print_exc()

        # 如果启用API，初始化FastAPI应用
        if self.api_enabled:
            self._init_api()

    def _now_iso(self):
        """返回秒级ISO时间戳，供前端时间轴解析。"""
        return datetime.fromtimestamp(time.time()).isoformat(timespec="seconds")

    def _seconds_since(self, timestamp):
        if timestamp is None:
            return None
        return max(0.0, time.time() - timestamp)

    def _radar_board_online(self):
        age = self._seconds_since(self.last_radar_received_time)
        return bool(self.running and age is not None and age <= BOARD_TIMEOUT_SECONDS)

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
        return bool(heartbeat_age is not None and heartbeat_age <= SNORE_BOARD_TIMEOUT_SECONDS)

    def _environment_board_online(self):
        age = self._seconds_since(self.last_environment_heartbeat_time)
        return bool(age is not None and age <= ENVIRONMENT_BOARD_TIMEOUT_SECONDS)

    def _voice_board_online(self):
        age = self._seconds_since(self.last_voice_received_time)
        return bool(age is not None and age <= VOICE_BOARD_TIMEOUT_SECONDS)

    def _edgi_board_online(self):
        age = self._seconds_since(self.last_edgi_heartbeat_time)
        return bool(age is not None and age <= EDGI_BOARD_TIMEOUT_SECONDS)

    def _active_emergency_event(self):
        with self.state_lock:
            active = [
                event for event in self.emergency_events
                if event.get("type") == "emergency_voice"
                and event.get("status", "active") == "active"
            ]
        return max(active, key=lambda item: item.get("timestamp", ""), default=None)

    def _environment_snapshot(self):
        environment_age = self._seconds_since(self.last_environment_heartbeat_time)
        environment_board_online = self._environment_board_online()
        environment_online = bool(environment_board_online and self.environment_sensor_ok)
        temperature = round(float(self.temperature_c), 1) if environment_online and self.temperature_c is not None else None
        humidity = round(float(self.humidity_pct), 1) if environment_online and self.humidity_pct is not None else None
        return {
            "environment_board_online": environment_board_online,
            "environment_online": environment_online,
            "environment_sensor_ok": bool(self.environment_sensor_ok),
            "last_environment_heartbeat_at": self.last_environment_heartbeat_at,
            "environment_age_seconds": round(environment_age, 2) if environment_age is not None else None,
            "temperature_c": temperature,
            "humidity_pct": humidity,
            "comfort_status": comfort_status_for(
                temperature,
                humidity,
                sensor_ok=bool(self.environment_sensor_ok),
                online=environment_online,
            ),
        }

    def _sleep_stage_for_latest(self, radar_online, heart_rate, breath_rate):
        if not radar_online:
            return "雷达离线"
        if self.snore_detected or self.snore_score >= 0.65:
            return "疑似呼噜扰动"
        if heart_rate is None or breath_rate is None:
            return "等待生命体征"
        return "实时监测中"

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

    def _timeline_entry(self, timestamp=None):
        radar_online = self._radar_board_online()
        snore_online = self._snore_board_online()
        target_distance = self.target_bin * RANGE_RESOLUTION if self.target_bin is not None else 0.0
        heart_rate = float(self.heart_rate) if self.heart_rate is not None else None
        breath_rate = float(self.breath_rate) if self.breath_rate is not None else None
        snore_score = round(float(self.snore_score or 0.0), 3) if snore_online else 0.0
        snore_dbfs = self.snore_dbfs if snore_online else None
        snore_level = self._snore_level_from_dbfs(snore_dbfs, snore_score) if snore_online else None
        snore_detected = bool(self.snore_detected) if snore_online else False
        env = self._environment_snapshot()
        return {
            "timestamp": timestamp or self._now_iso(),
            "heart_rate": heart_rate if radar_online else None,
            "breath_rate": breath_rate if radar_online else None,
            "target_distance": float(target_distance) if radar_online else 0.0,
            "target_bin": int(self.target_bin) if self.target_bin is not None else None,
            "radar_online": radar_online,
            "snore_online": snore_online,
            "snore_score": snore_score,
            "snore_dbfs": snore_dbfs,
            "snore_level": snore_level,
            "snore_detected": snore_detected,
            "environment_online": env["environment_online"],
            "environment_board_online": env["environment_board_online"],
            "temperature_c": env["temperature_c"],
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

    # ===== sleep overview 辅助方法（移植自 mock_hardware_api.py） =====

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
        display_text = transcript or phrase or "未提供文本"
        fingerprint_seed = f"{timestamp}:{source}:{phrase}:{transcript}:{payload.device_id or ''}"
        fingerprint = "emergency_voice:" + hashlib.sha1(fingerprint_seed.encode("utf-8")).hexdigest()[:16]
        event = {
            "eventID": int(time.time() * 1000),
            "userID": None,
            "type": "emergency_voice",
            "severity": "critical",
            "title": "语音紧急求助",
            "message": f"小智检测到求助语音：“{display_text}”",
            "timestamp": timestamp,
            "source": source,
            "score_delta": -30,
            "details": {
                "phrase": phrase or None,
                "transcript": transcript or None,
                "device_id": payload.device_id,
            },
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
        return {
            "status": "success",
            "event_id": event["eventID"],
            "event_type": "emergency_voice",
            "severity": "critical",
            "timestamp": timestamp,
        }

    def _resolve_emergency_event(self, payload):
        source = (payload.source or "xiaozhi_voice_board").strip() or "xiaozhi_voice_board"
        resolved_at = self._now_iso()
        note = (payload.resolution_note or "已在开发板确认并解除紧急状态").strip()
        resolved_by = (payload.resolved_by or source).strip() or source

        with self.state_lock:
            candidates = [
                event
                for event in self.emergency_events
                if event.get("type") == "emergency_voice"
                and event.get("status", "active") == "active"
                and (
                    event.get("eventID") == payload.event_id
                    if payload.event_id is not None
                    else event.get("source") == source
                )
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

    def _emergency_events_between(self, start_ts=None):
        with self.state_lock:
            events = list(self.emergency_events)
        if start_ts is None:
            return events
        return [
            event
            for event in events
            if (self._parse_iso_seconds(event.get("timestamp", "")) or 0.0) >= start_ts
            or event.get("status", "active") == "active"
        ]

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
        """从时间轴行中合成睡眠事件（与 mock_hardware_api.py 的 record_sleep_events_locked 同等逻辑，
        但仅在内存中累积，不写 SQLite）。每个 (type, 分钟) 仅记录一次。"""
        events: list = []
        seen = set()
        radar_age = self._seconds_since(self.last_radar_received_at)
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

            if isinstance(breath_rate, (int, float)) and (breath_rate >= 24 or breath_rate < 10):
                condition = "vital_abnormal"
                add(
                    "breath_abnormal", "warning", "呼吸异常波动",
                    f"当前呼吸率 {breath_rate:.1f} RPM，超出静息观察范围。",
                    timestamp, "radar_board", -10,
                    {"breath_rate": breath_rate},
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
                "summary": "启动模拟后端和两个模拟开发板后，睡眠看护驾驶舱会开始生成评分。",
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
            label = "设备异常" if radar_offline_ratio > 0.25 else "呼噜频繁"
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

    def _build_sleep_overview(self, rows, events, mode, seconds, date, user_id, devices=None):
        events = [
            event for event in events
            if not (
                event.get("type") == "device_offline"
                and event.get("source") in {"snore_board", "environment_board"}
            )
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
                "presence_detected": bool(self.presence_detected),
                "presence_stable": bool(self.presence_stable),
            })

    def _status_snapshot(self):
        radar_age = self._seconds_since(self.last_radar_received_time)
        snore_age = self._seconds_since(self.last_snore_heartbeat_time)
        voice_age = self._seconds_since(self.last_voice_received_time)
        radar_online = self._radar_board_online()
        snore_online = self._snore_board_online()
        env = self._environment_snapshot()
        active_emergency = self._active_emergency_event()
        snore_level = self._snore_level_from_dbfs(self.snore_dbfs, self.snore_score)
        return {
            "running": self.running,
            "radar_online": radar_online,
            "radar_board_online": radar_online,
            "snore_board_online": snore_online,
            "snore_monitoring": bool(self.snore_session_active and snore_online),
            "snore_paused": bool(self.snore_session_stopped and self._edgi_board_online()),
            "environment_board_online": env["environment_board_online"],
            "environment_sensor_ok": env["environment_sensor_ok"],
            "voice_board_online": self._voice_board_online(),
            "edgi_board_online": self._edgi_board_online(),
            "snore_session_active": bool(self.snore_session_active),
            "snore_session_started_at": self.snore_session_started_text,
            "heart_rate": float(self.heart_rate) if self.heart_rate is not None else None,
            "breath_rate": float(self.breath_rate) if self.breath_rate is not None else None,
            "target_distance": float(self.target_bin * RANGE_RESOLUTION) if self.target_bin is not None else None,
            "target_bin": int(self.target_bin) if self.target_bin is not None else None,
            "total_frames": self.total_frames_received,
            "processed_frames": self.processing_count,
            "uptime": time.time() - self.start_time,
            "last_frame": self.last_frame_number,
            "last_radar_frame_number": self.last_frame_number,
            "last_radar_received_at": self.last_radar_received_at,
            "last_snore_heartbeat_at": self.last_snore_heartbeat_at,
            "last_environment_heartbeat_at": env["last_environment_heartbeat_at"],
            "last_voice_received_at": self.last_voice_received_at,
            "last_edgi_heartbeat_at": self.last_edgi_heartbeat_at,
            "radar_age_seconds": round(radar_age, 2) if radar_age is not None else None,
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
            "temperature_c": env["temperature_c"],
            "humidity_pct": env["humidity_pct"],
            "comfort_status": env["comfort_status"],
            "sleep_stage": self._sleep_stage_for_latest(
                radar_online,
                self.heart_rate,
                self.breath_rate,
            ),
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
            heart_rate: float
            breath_rate: float
            target_distance: float
            timestamp: Optional[str] = None  # ISO 8601 格式，如 "2025-12-07T18:30:00.000Z"

        class UserRegister(BaseModel):
            userName: str
            passWord: str
            email: str

        class UserLogin(BaseModel):
            userName: str
            passWord: str

        class SnoreHeartbeat(BaseModel):
            snore_score: float = 0.0
            snore_detected: bool = False
            dbfs: Optional[float] = None
            source: str = "real_snore_board"


        class EnvironmentHeartbeat(BaseModel):
            temperature_c: float
            humidity_pct: float
            sensor_ok: bool = True
            source: str = "real_edgi_talk_m33_aht20"


        class EmergencyRequest(BaseModel):
            source: str = "xiaozhi_voice_board"
            phrase: Optional[str] = None
            transcript: Optional[str] = None
            device_id: Optional[str] = None
            timestamp: Optional[str] = None


        class EmergencyResolveRequest(BaseModel):
            event_id: Optional[int] = None
            source: str = "xiaozhi_voice_board"
            resolution_note: Optional[str] = None
            resolved_by: Optional[str] = None


        @self.app.post("/emergency")
        async def receive_emergency(payload: EmergencyRequest):
            return self._record_emergency_event(payload)


        @self.app.post("/emergency/resolve")
        async def resolve_emergency(payload: EmergencyResolveRequest):
            return self._resolve_emergency_event(payload)


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
            """接收前端发送的带用户ID的生命体征数据并保存到数据库"""
            try:
                # 调用数据库函数保存数据
                data_id = save_vitals_with_user(
                    user_id=data.userID,
                    heart_rate=data.heart_rate,
                    breath_rate=data.breath_rate,
                    target_distance=data.target_distance,
                    timestamp_str=data.timestamp
                )
                return {
                    "status": "success",
                    "message": "生命体征数据保存成功",
                    "dataID": data_id
                }
            except Exception as e:
                return {
                    "status": "error",
                    "message": f"保存失败: {str(e)}"
                }

        # 添加CORS中间件
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],  # 允许所有来源
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
            if self.heart_rate is not None:
                return {"heart_rate": float(self.heart_rate),
                        "timestamp": time.time(),
                        "status": "ok"}
            else:
                return {"heart_rate": None,
                        "timestamp": time.time(),
                        "status": "no_data"}

        @self.app.get("/target")
        async def get_target_data():
            """同时获取目标距离和心率数据"""
            target_distance = self.target_bin * RANGE_RESOLUTION if self.target_bin is not None else None
            radar_online = self._radar_board_online()
            env = self._environment_snapshot()
            return {
                "heart_rate": float(self.heart_rate) if self.heart_rate is not None else None,
                "breath_rate": float(self.breath_rate) if self.breath_rate is not None else None,
                "target_distance": float(target_distance) if target_distance is not None else None,
                "target_bin": int(self.target_bin) if self.target_bin is not None else None,
                "radar_online": radar_online,
                "radar_board_online": radar_online,
                "environment_board_online": env["environment_board_online"],
                "last_environment_heartbeat_at": env["last_environment_heartbeat_at"],
                "environment_age_seconds": env["environment_age_seconds"],
                "temperature_c": env["temperature_c"],
                "humidity_pct": env["humidity_pct"],
                "comfort_status": env["comfort_status"],
                "timestamp": time.time(),
                "status": "ok" if (self.heart_rate is not None or target_distance is not None) else "no_data"
            }

        @self.app.get("/status")
        async def get_status():
            """获取系统状态信息"""
            return self._status_snapshot()

        @self.app.get("/debug/radar")
        async def get_radar_debug():
            """获取雷达UDP帧解析诊断信息"""
            return self._status_snapshot()["radar_debug"]

        @self.app.post("/mock/snore-heartbeat")
        async def receive_snore_heartbeat(heartbeat: SnoreHeartbeat):
            """接收呼噜检测板每秒特征心跳。"""
            score = max(0.0, min(1.0, float(heartbeat.snore_score)))
            now = time.time()
            now_text = self._now_iso()
            with self.state_lock:
                self.last_snore_heartbeat_time = now
                self.last_snore_heartbeat_at = now_text
                self.last_edgi_heartbeat_time = now
                self.last_edgi_heartbeat_at = now_text
                self.snore_session_last_seen_at = now
                self.snore_score = round(score, 3)
                if heartbeat.dbfs is not None:
                    self.snore_dbfs = float(heartbeat.dbfs)
                    self.last_audio_dbfs = float(heartbeat.dbfs)
                if heartbeat.snore_detected:
                    self.snore_detected = True
                    self.snore_event_count += 1
                    self.last_snore_time = now
                    self.last_snore_at = now_text
                else:
                    recent_snore = self._seconds_since(self.last_snore_time)
                    self.snore_detected = recent_snore is not None and recent_snore <= SNORE_EVENT_HOLD_SECONDS
            self._upsert_timeline()
            return {
                "code": 200,
                "status": "success",
                "message": "呼噜心跳已接收",
                "snore_score": round(score, 3),
                "snore_dbfs": heartbeat.dbfs,
                "snore_level": self._snore_level_from_dbfs(heartbeat.dbfs, score),
                "snore_detected": self._status_snapshot()["snore_detected"],
            }

        @self.app.post("/mock/environment-heartbeat")
        async def receive_environment_heartbeat(heartbeat: EnvironmentHeartbeat):
            """接收 M55 从 M33 AHT20 共享内存读取后转发的温湿度心跳。"""
            sensor_ok = bool(heartbeat.sensor_ok)
            temperature = round(float(heartbeat.temperature_c), 1)
            humidity = round(max(0.0, min(100.0, float(heartbeat.humidity_pct))), 1)
            comfort_status = comfort_status_for(temperature, humidity, sensor_ok=sensor_ok, online=sensor_ok)
            now = time.time()
            now_text = self._now_iso()
            with self.state_lock:
                self.last_environment_heartbeat_time = now
                self.last_environment_heartbeat_at = now_text
                self.last_edgi_heartbeat_time = now
                self.last_edgi_heartbeat_at = now_text
                self.environment_sensor_ok = sensor_ok
                self.temperature_c = temperature if sensor_ok else None
                self.humidity_pct = humidity if sensor_ok else None
            self._upsert_timeline()
            return {
                "code": 200,
                "status": "success",
                "message": "温湿度心跳已接收",
                "temperature_c": temperature if sensor_ok else None,
                "humidity_pct": humidity if sensor_ok else None,
                "sensor_ok": sensor_ok,
                "comfort_status": comfort_status,
            }

        @self.app.post("/mock/snore-session/start")
        async def start_snore_session():
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
                self.last_edgi_heartbeat_time = now
                self.last_edgi_heartbeat_at = now_text
            self._upsert_timeline()
            return {
                "code": 200,
                "status": "success",
                "message": "呼噜检测板 Snore detect 已按下",
                "snore_board_online": self._snore_board_online(),
                "snore_monitoring": True,
                "snore_paused": False,
                "started_at": now_text,
            }

        @self.app.post("/mock/snore-session/stop")
        async def stop_snore_session():
            """呼噜监测暂停时调用；Edgi E84 仍保持在线。"""
            now = time.time()
            now_text = self._now_iso()
            with self.state_lock:
                self.snore_session_active = False
                self.snore_session_stopped = True
                self.snore_session_last_seen_at = now
                self.last_edgi_heartbeat_time = now
                self.last_edgi_heartbeat_at = now_text
                # 让“最近心跳/音频”不再被 5/15 秒窗口认作在线依据
                self.last_snore_heartbeat_time = None
                self.last_audio_received_time = None
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

            audio_dir = Path(current_dir) / "mock_audio_uploads"
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
            return results

        @self.app.get("/timeline")
        async def get_timeline(seconds: int = Query(180, ge=10, le=1800)):
            """获取前端生命体征时间轴。"""
            self._upsert_timeline()
            cutoff = time.time() - float(seconds)
            with self.state_lock:
                rows = [
                    row
                    for row in self.timeline
                    if self._parse_iso_seconds(row.get("timestamp")) >= cutoff
                ]
                rows = json.loads(json.dumps(rows))
            return {
                "code": 200,
                "status": "success",
                "seconds": seconds,
                "data": rows,
                "summary": self._timeline_summary(rows),
            }

        @self.app.get("/sleep/overview")
        async def get_sleep_overview(
            mode: str = Query("live"),
            seconds: int = Query(1800, ge=60, le=7200),
            date: Optional[str] = Query(None),
            userID: Optional[int] = Query(None),
        ):
            """睡眠看护驾驶舱聚合接口（移植自 mock_hardware_api.py）。

            - live 模式：从 self.timeline 截取近 N 秒行 + 内存合成事件。
            - history 模式：优先按 date 过滤 self.timeline（如果该天还有数据）；
              否则空数据但返回正常结构（前端可降级显示）。
            """
            selected_mode = "history" if mode == "history" else "live"
            self._upsert_timeline()

            if selected_mode == "history":
                with self.state_lock:
                    snapshot = list(self.timeline)
                if date:
                    snapshot = [row for row in snapshot if (row.get("timestamp") or "").startswith(date)]
                rows = json.loads(json.dumps(snapshot))
            else:
                cutoff = time.time() - float(seconds)
                cutoff_iso = datetime.fromtimestamp(cutoff).isoformat(timespec="seconds")
                with self.state_lock:
                    rows = self._rows_between(self.timeline, cutoff)
                    rows = json.loads(json.dumps(rows))
                    devices = {
                        "radar_board_online": self._radar_board_online(),
                        "snore_board_online": self._snore_board_online(),
                        "snore_monitoring": bool(self.snore_session_active and self._snore_board_online()),
                        "snore_paused": bool(self.snore_session_stopped and self._edgi_board_online()),
                        "environment_board_online": self._environment_snapshot()["environment_board_online"],
                        "environment_sensor_ok": self._environment_snapshot()["environment_sensor_ok"],
                        "voice_board_online": self._voice_board_online(),
                        "edgi_board_online": self._edgi_board_online(),
                        "radar_age_seconds": self._seconds_since(self.last_radar_received_at),
                        "snore_age_seconds": self._seconds_since(self.last_snore_heartbeat_at),
                        "environment_age_seconds": self._environment_snapshot()["environment_age_seconds"],
                        "voice_age_seconds": self._seconds_since(self.last_voice_received_time),
                        "edgi_age_seconds": self._seconds_since(self.last_edgi_heartbeat_time),
                        "audio_upload_count": self.audio_upload_count,
                        "last_audio_received_at": self.last_audio_received_at,
                        "last_environment_heartbeat_at": self.last_environment_heartbeat_at,
                        "temperature_c": self._environment_snapshot()["temperature_c"],
                        "humidity_pct": self._environment_snapshot()["humidity_pct"],
                        "comfort_status": self._environment_snapshot()["comfort_status"],
                        "emergency_active": self._active_emergency_event() is not None,
                    }
                events = self._synthesize_sleep_events(rows) + self._emergency_events_between(cutoff)
                return self._build_sleep_overview(rows, events, "live", seconds, date, userID, devices)

            with self.state_lock:
                env = self._environment_snapshot()
                devices = {
                    "radar_board_online": self._radar_board_online(),
                    "snore_board_online": self._snore_board_online(),
                    "snore_monitoring": bool(self.snore_session_active and self._snore_board_online()),
                    "snore_paused": bool(self.snore_session_stopped and self._edgi_board_online()),
                    "environment_board_online": env["environment_board_online"],
                    "environment_sensor_ok": env["environment_sensor_ok"],
                    "voice_board_online": self._voice_board_online(),
                    "edgi_board_online": self._edgi_board_online(),
                    "radar_age_seconds": self._seconds_since(self.last_radar_received_at),
                    "snore_age_seconds": self._seconds_since(self.last_snore_heartbeat_at),
                    "environment_age_seconds": env["environment_age_seconds"],
                    "voice_age_seconds": self._seconds_since(self.last_voice_received_time),
                    "edgi_age_seconds": self._seconds_since(self.last_edgi_heartbeat_time),
                    "audio_upload_count": self.audio_upload_count,
                    "last_audio_received_at": self.last_audio_received_at,
                    "last_environment_heartbeat_at": self.last_environment_heartbeat_at,
                    "temperature_c": env["temperature_c"],
                    "humidity_pct": env["humidity_pct"],
                    "comfort_status": env["comfort_status"],
                    "emergency_active": self._active_emergency_event() is not None,
                }
            events = self._synthesize_sleep_events(rows) + self._emergency_events_between()
            return self._build_sleep_overview(rows, events, "history", seconds, date, userID, devices)

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
        # self.socket.sendto('{"radar_transmission":"enable"}'.encode(), (self.server_ip, self.server_port))

        # 开始接收数据
        try:
                while self.running:
                    # 接收一帧数据
                    data, adr = self.socket.recvfrom(BUFFER_SIZE)

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
                self.target_bin = target_bin

                # 步骤5: 执行存在检测
                if ENABLE_PRESENCE_DETECTION:
                    # 提取最新一帧的数据用于存在检测
                    latest_frame_data = data_2d[-1:, :]  # 取最后一帧
                    self.presence_detected, self.presence_stable = self.presence_detector.detect_presence(latest_frame_data)
                    print(f">> 存在检测: 原始={self.presence_detected}, 稳定={self.presence_stable}")
                else:
                    # 如果未启用存在检测，则默认认为有人存在
                    self.presence_detected = True
                    self.presence_stable = True

                # 步骤6: 只有在检测到人存在时才执行信号分解和心率计算
                if self.presence_stable and DECOMPOSE_SIGNAL:
                    print(f">> 检测到人体存在，执行信号分解: 类型={DECOMP_TYPE}...")

                    # 清空之前的结果
                    self.cwt_results = None
                    self.eemd_results = None
                    self.model_prediction = None  # 清空模型预测结果
                    self.heart_rate = None  # 清空心率预测

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
                                        self.breath_rate = estimate_breath_rate_fft(self.phase_values)
                                    # 保存预测结果
                                    self.model_prediction = {
                                        'type': 'cwt',
                                        'result': prediction,
                                        'time': predict_time,
                                        'heart_rate': self.heart_rate
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

                                    # 保存预测结果
                                    self.model_prediction = {
                                        'type': 'eemd',
                                        'result': prediction,
                                        'time': predict_time,
                                        'heart_rate': self.heart_rate
                                    }

                                    print(f">> 模型推理完成: 形状={prediction.shape}, 用时={predict_time*1000:.0f}ms")
                                except Exception as e:
                                    print(f"模型推理错误: {e}")

                        except Exception as e:
                            print(f"EEMD分析出错: {e}")
                            self.eemd_results = None
                else:
                    if not self.presence_stable:
                        print(">> 未检测到人体存在，跳过信号分解和心率计算")
                    # 如果未检测到人，清空心率结果
                    if not self.presence_stable:
                        self.heart_rate = None
                        self.model_prediction = None
                        self.breath_rate = None
                # 更新显示数据
                target_distance = target_bin * RANGE_RESOLUTION
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
        results = {
            'phase_values': self.phase_values,
            'target_bin': self.target_bin,
            'target_distance': self.target_bin * RANGE_RESOLUTION if self.target_bin is not None else None,
            'cwt_results': self.cwt_results,
            'eemd_results': self.eemd_results,
            'model_prediction': self.model_prediction,
            'heart_rate': self.heart_rate,
            'breath_rate': self.breath_rate,
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
