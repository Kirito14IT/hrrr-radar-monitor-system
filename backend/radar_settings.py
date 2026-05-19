"""
BGT60TR13C 雷达参数设置模块

此模块包含BGT60TR13C雷达的所有配置参数和计算参数，
项目中所有需要使用雷达参数的模块都应当从此处导入参数。
"""

import json
import os

# 基础常数
SPEED_OF_LIGHT = 3e8  # 光速 (m/s)

# 基本雷达参数
RADAR_PARAMS = {
    # 基本硬件参数
    'start_freq': 58e9,           # 起始频率 58 GHz
    'end_freq': 63.5e9,           # 终止频率 63.5 GHz
    'bandwidth': 5.5e9,           # 带宽 5.5 GHz
    'sample_rate': 2e6,           # 采样率 2 MHz
    'chirp_time': 0.0004,         # 调频时间 0.4 ms
    'frame_time': 0.0333,         # 帧重复时间 33.3 ms (≈30Hz)
    'num_samples': 512,           # 每chirp采样点数
    'num_chirps': 1,             # 每帧chirp数
    'rx_antennas': 1,             # 接收天线数量
    'tx_antennas': 1,             # 发射天线数量
    'hp_cutoff': 20e3,            # 高通滤波器截止频率 20 kHz
    'aaf_cutoff': 500e3,          # 抗混叠滤波器截止频率 500 kHz
    
    # 计算参数
    'sweep_slope': 5.5e9 / 0.0004,                       # 调频斜率 1.375e13 Hz/s
    'center_freq': (58e9 + 63.5e9) / 2,                  # 中心频率 60.75 GHz
    'wavelength': SPEED_OF_LIGHT / ((58e9 + 63.5e9) / 2),# 波长 4.94 mm
    'range_resolution': SPEED_OF_LIGHT / (2 * 5.5e9),    # 距离分辨率 2.7 cm
    'max_range': 2e6 * SPEED_OF_LIGHT / (2 * (5.5e9 / 0.0004)),  # 最大不模糊距离
    'velocity_resolution': 0.771,                        # 速度分辨率 0.771 m/s
    'max_velocity': 6.175,                               # 最大不模糊速度 6.175 m/s
    'min_velocity': 0.049,                               # 最小可检测速度 0.049 m/s
    'frame_rate': 30,                                    # 帧率 30 Hz
    'frequency_resolution': 2e6 / 512,                   # 频率分辨率 3.90625 kHz
    'doppler_shift_range': 2.5e3,                        # 多普勒频移范围 ±2.5 kHz
}

# 尝试从配置文件加载参数（如果存在）
def load_params_from_json(config_file='radar_settings/BGT60TR13C_settings_20250423-163757.json'):
    """
    从JSON配置文件加载参数
    
    参数:
        config_file: 配置文件路径
    
    返回:
        更新后的参数字典
    """
    params = RADAR_PARAMS.copy()
    
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r') as f:
                config = json.load(f)
                
            # 从配置文件提取参数
            device_config = config['device_config']['fmcw_single_shape']
            
            # 更新基本参数
            params['start_freq'] = device_config['start_frequency_Hz']
            params['end_freq'] = device_config['end_frequency_Hz']
            params['bandwidth'] = device_config['end_frequency_Hz'] - device_config['start_frequency_Hz']
            params['sample_rate'] = device_config['sample_rate_Hz']
            params['chirp_time'] = device_config['chirp_repetition_time_s']
            params['frame_time'] = device_config['frame_repetition_time_s']
            params['num_samples'] = device_config['num_samples_per_chirp']
            params['num_chirps'] = device_config['num_chirps_per_frame']
            params['rx_antennas'] = len(device_config.get('rx_antennas', [1, 2, 3]))
            params['tx_antennas'] = len(device_config.get('tx_antennas', [1]))
            params['hp_cutoff'] = device_config.get('hp_cutoff_Hz', 20000)
            params['aaf_cutoff'] = device_config.get('aaf_cutoff_Hz', 500000)
            
            # 重新计算派生参数
            params['sweep_slope'] = params['bandwidth'] / params['chirp_time']
            params['center_freq'] = (params['start_freq'] + params['end_freq']) / 2
            params['wavelength'] = SPEED_OF_LIGHT / params['center_freq']
            params['range_resolution'] = SPEED_OF_LIGHT / (2 * params['bandwidth'])
            params['max_range'] = params['sample_rate'] * SPEED_OF_LIGHT / (2 * params['sweep_slope'])
            params['velocity_resolution'] = params['wavelength'] / (2 * params['num_chirps'] * params['chirp_time'])
            params['max_velocity'] = params['wavelength'] / (4 * params['chirp_time'])
            params['min_velocity'] = params['hp_cutoff'] * SPEED_OF_LIGHT / (2 * params['center_freq'])
            params['frame_rate'] = 1 / params['frame_time']
            params['frequency_resolution'] = params['sample_rate'] / params['num_samples']
            params['doppler_shift_range'] = params['max_velocity'] * 2 * params['center_freq'] / SPEED_OF_LIGHT
            
            # 应用任何修改后的参数，保持一致性
            params['velocity_resolution'] = 0.771  # 固定使用计算值
            params['max_velocity'] = 6.175  # 固定使用计算值
            
            print("从配置文件加载了雷达参数")
        except Exception as e:
            print(f"从配置文件加载参数时出错: {e}，使用默认参数")
    
    return params

# 初始化雷达参数
radar_params = load_params_from_json()

# 方便导入的函数
def get_radar_params():
    """获取雷达参数字典"""
    return radar_params

# 直接访问单个参数的便捷函数
def get_param(param_name):
    """获取指定的雷达参数"""
    return radar_params.get(param_name) 