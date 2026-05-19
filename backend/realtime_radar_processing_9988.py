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
from scipy import signal
from radar_func import range_fft, mti_filter, extract_phase



# 导入信号分解模块
from signal_decomposition import apply_cwt, apply_eemd

# 导入存在检测模块
from presence_detection import RadarPresenceDetector

# 导入FastAPI相关模块
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from typing import Dict, Any, Optional
import json


# 确保当前目录在Python路径中，便于导入自定义模块
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

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
WINDOW_SIZE_SECONDS = 10   # 处理窗口为10秒
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

db_enabled=False


class RealtimeRadarProcessor:
    """实时雷达数据处理器"""
    
    def __init__(self, server_ip='192.168.10.169', server_port=57345,
                 load_models=True, cwt_model_path=None, eemd_model_path=None,
                 api_enabled=True, api_port=8000):
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
        
        # 初始化存在检测器
        self.presence_detector = RadarPresenceDetector(
            history_length=PRESENCE_HISTORY_LENGTH, 
            count_threshold=PRESENCE_COUNT_THRESHOLD
        )
        self.presence_detected = False
        self.presence_stable = False

        self.db_enabled = db_enabled
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
        
        # 结果存储
        self.phase_values = None            # 最近一次处理的相位值
        self.target_bin = None              # 最近一次处理的目标bin
        self.cwt_results = None             # 最近一次CWT分析结果
        self.eemd_results = None            # 最近一次EEMD分析结果
        self.model_prediction = None        # 最近一次模型预测结果
        self.heart_rate = None              # 最近一次心率预测值
        
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
                        cwt_model_path = os.path.join('trained_models', 'DeepStateSpace_CWT_best.keras')
                    if eemd_model_path is None:
                        eemd_model_path = os.path.join('trained_models', 'DeepStateSpace_EEMD_best.keras')
                    
                    # 根据当前分解方法加载对应模型
                    if DECOMP_TYPE == "cwt":
                        if os.path.exists(cwt_model_path):
                            print(f"加载CWT模型: {cwt_model_path}")
                            self.cwt_model = keras.models.load_model(cwt_model_path)
                            print(f"CWT模型加载成功: {self.cwt_model.name}")
                        else:
                            print(f"警告: CWT模型文件不存在 - {cwt_model_path}")
                    elif DECOMP_TYPE == "eemd":
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
        # 如果启用数据库，初始化数据库
        # if self.db_enabled:
        #     # 数据库连接
        #     self.db = MySQLHelper(
        #         host='localhost',
        #         user='root',
        #         password='123456',
        #         database='user_data'
        #     )
        #     self._init_db()

    def _init_api(self):
        """初始化FastAPI应用"""
        self.app = FastAPI(title="雷达心率监测API", 
                          description="提供实时雷达心率监测数据的API接口",
                          version="1.0.0")
        
        # 添加CORS中间件
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],  # 允许所有来源
            allow_credentials=True,
            allow_methods=["*"],  # 允许所有方法
            allow_headers=["*"],  # 允许所有头
        )
        
        # 定义API路由
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
            return {
                "heart_rate": float(self.heart_rate) if self.heart_rate is not None else None,
                "target_distance": float(target_distance) if target_distance is not None else None,
                "target_bin": int(self.target_bin) if self.target_bin is not None else None,
                "timestamp": time.time(),
                "status": "ok" if (self.heart_rate is not None or target_distance is not None) else "no_data"
            }
        
        @self.app.get("/status")
        async def get_status():
            """获取系统状态信息"""
            return {
                "running": self.running,
                "total_frames": self.total_frames_received,
                "processed_frames": self.processing_count,
                "uptime": time.time() - self.start_time,
                "last_frame": self.last_frame_number,
                "timestamp": time.time()
            }
        
        @self.app.get("/detailed")
        async def get_detailed_data():
            """获取详细的处理结果数据"""
            results = self.get_latest_results()
            # 移除大型数据结构以减少响应大小
            if "cwt_results" in results and results["cwt_results"]:
                results["cwt_results"] = {"available": True}
            if "eemd_results" in results and results["eemd_results"]:
                results["eemd_results"] = {"available": True}
            if "phase_values" in results and results["phase_values"] is not None:
                # 将numpy数组转换为列表
                results["phase_values"] = results["phase_values"].tolist() if hasattr(results["phase_values"], "tolist") else results["phase_values"]
            return results
        
        print(f"API服务初始化完成，等待启动在端口 {self.api_port}")

    def _init_db(self):
        if self.heart_rate is not None:
            self.db.insert('user_info', {'name': 'Alice', 'age': 30})

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
                    
                    # 解析雷达数据为float16实数
                    # 每个样本是2字节的float16实数
                    num_samples = len(radar_data) // 2  # 2字节/样本
                    samples = np.zeros(num_samples, dtype=np.float32)  # 转换为float32处理
                    
                    for i in range(num_samples):
                        # 从字节数据读取float16值并转换为float32
                        # 注意：np.frombuffer和struct.unpack都可以用，这里用struct以保持代码一致性
                        sample_bytes = radar_data[i*2:(i+1)*2]
                        # 使用numpy的方法处理float16数据
                        samples[i] = np.frombuffer(sample_bytes, dtype=np.float16)[0]
                    
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
                                    
                                    # 保存预测结果
                                    self.model_prediction = {
                                        'type': 'cwt',
                                        'result': prediction,
                                        'time': predict_time,
                                        'heart_rate': self.heart_rate
                                    }
                                    
                                    print(f">> 模型推理完成: 形状={prediction.shape}, 用时={predict_time*1000:.0f}ms")
                                    print(f">> 预测心率: {self.heart_rate:.1f} BPM")
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
                                    print(f">> 预测心率: {self.heart_rate:.1f} BPM")
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
                
                # 更新显示数据
                target_distance = target_bin * RANGE_RESOLUTION
                process_end_time = time.time()
                
                print(f">> 结果: 目标距离 {target_distance:.2f}米 (bin{target_bin}) | 用时: {(process_end_time - process_start_time)*1000:.0f}ms")
                if self.presence_stable and self.heart_rate is not None:
                    print(f">> 心率预测: {self.heart_rate:.1f} BPM")
                
                # 更新统计
                self.processing_count += 1
                self.period_frames_processed += 1
                
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
            # 模型期望的输入形状为 (batch_size, signal_length, scales) 即 (None, 300, 64)
            # 需要转置并添加batch维度
            model_input = np.transpose(data)  # 转置后变为(300, 64)
            model_input = np.expand_dims(model_input, axis=0)  # 添加batch维度，变为(1, 300, 64)
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
            'processing_count': self.processing_count,
            'timestamp': time.time()
        }
        return results

if __name__ == '__main__':
    # 命令行参数处理
    import argparse
    
    parser = argparse.ArgumentParser(description='实时雷达数据处理器')
    parser.add_argument('--ip', type=str, default='192.168.118.143', help='雷达设备IP地址')
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
    parser.add_argument('--api-port', type=int, default=8000, help='API服务器端口')
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
