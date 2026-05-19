"""
信号分解算法库
包含用于雷达信号处理的关键信号分解算法
"""

import numpy as np
import warnings

# =========== 基础工具函数 ===========

def check_signal(x):
    """检查输入信号是否为一维numpy数组"""
    if not isinstance(x, np.ndarray):
        try:
            x = np.array(x)
        except:
            raise ValueError("输入信号必须可转换为numpy数组")
    
    if x.ndim > 1:
        if x.shape[1] == 1:  # 如果是列向量
            x = x.flatten()
        else:
            raise ValueError("输入信号必须为一维数组")
    
    return x


# =========== EMD 相关算法 ===========

def apply_eemd(signal, noise_width=0.05, ensemble_size=100, max_imf=None):
    """
    应用集合经验模态分解(EEMD)算法，通过添加白噪声和多次平均提高EMD的稳定性
    
    参数:
        signal: 一维信号数组
        noise_width: 添加的噪声振幅相对于信号标准差的比例，默认0.05
        ensemble_size: 集合大小(运行次数)，默认100
        max_imf: 最大IMF数量，None表示不限制
    
    返回:
        imfs: 包含所有IMF的数组，形状为(n_imfs, signal_length)
    
    示例:
        >>> imfs = apply_eemd(signal, noise_width=0.1, ensemble_size=50)
    
    依赖:
        需要安装PyEMD库: pip install EMD-signal
    """
    try:
        from PyEMD import EEMD
    except ImportError:
        raise ImportError("需要安装PyEMD库: pip install EMD-signal")
    
    signal = check_signal(signal)
    
    # 初始化EEMD对象
    eemd = EEMD()
    eemd.noise_seed(12345)  # 设置随机种子以确保结果可重复
    
    # 设置参数
    eemd.noise_width = noise_width
    eemd.trials = ensemble_size
    
    # 执行分解
    imfs = eemd(signal, max_imf=max_imf)
    
    return imfs


# =========== 小波相关算法 ===========

def apply_cwt(signal, scales=None, wavelet='morl', sampling_period=1.0):
    """
    应用连续小波变换(CWT)
    
    参数:
        signal: 一维信号数组
        scales: 尺度参数，默认为None(自动生成)
        wavelet: 小波类型，默认'morl'(Morlet小波)
        sampling_period: 采样周期，默认为1.0
    
    返回:
        coef: 小波系数数组，形状为(len(scales), len(signal))
        frequencies: 对应各尺度的频率
    
    示例:
        >>> coef, freqs = apply_cwt(signal, scales=np.arange(1, 128), wavelet='morl')
    
    依赖:
        需要安装pywavelets库: pip install PyWavelets
    """
    try:
        import pywt
    except ImportError:
        raise ImportError("需要安装pywavelets库: pip install PyWavelets")
    
    signal = check_signal(signal)
    
    # 自动生成尺度
    if scales is None:
        scales = np.arange(1, min(len(signal) // 2, 128))
    
    # 执行连续小波变换
    coef, freqs = pywt.cwt(signal, scales, wavelet, sampling_period)
    
    return coef, freqs
