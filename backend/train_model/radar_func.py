import numpy as np
from scipy import signal

def range_fft(data, window='hanning', zero_padding_factor=1):
    """
    对雷达数据执行距离FFT（在采样点维度）
    
    参数:
        data: 形状为(frames, antennas, chirps, samples)的雷达原始数据
        window: 窗函数类型，默认为hanning
        zero_padding_factor: 零填充因子，默认为1（不进行零填充）
    
    返回:
        距离FFT结果，形状为(frames, antennas, chirps, samples*zero_padding_factor)
    """
    frames, antennas, chirps, samples = data.shape
    
    # 应用窗函数
    if window.lower() == 'hanning' or window.lower() == 'hann':  # 同时接受hann和hanning
        win = np.hanning(samples)
    elif window.lower() == 'hamming':
        win = np.hamming(samples)
    elif window.lower() == 'blackman':
        win = np.blackman(samples)
    elif window.lower() == 'rectangular' or window.lower() == 'none':
        win = np.ones(samples)
    else:
        raise ValueError(f"不支持的窗函数类型: {window}")
    
    # 准备输出数组
    fft_size = samples * zero_padding_factor
    range_fft_data = np.zeros((frames, antennas, chirps, fft_size), dtype=complex)
    
    # 应用窗函数并执行FFT
    for f in range(frames):
        for a in range(antennas):
            for c in range(chirps):
                windowed_data = data[f, a, c, :] * win
                range_fft_data[f, a, c, :] = np.fft.fft(windowed_data, n=fft_size)
    
    return range_fft_data



def doppler_fft(range_fft_data, window='hanning', zero_padding_factor=1):
    """
    对距离FFT结果执行多普勒FFT（在chirp维度）
    
    参数:
        range_fft_data: 距离FFT结果，形状为(frames, antennas, chirps, range_bins)
        window: 窗函数类型，默认为hanning
        zero_padding_factor: 零填充因子，默认为1（不进行零填充）
    
    返回:
        距离-多普勒FFT结果，形状为(frames, antennas, chirps*zero_padding_factor, range_bins)
    """
    frames, antennas, chirps, range_bins = range_fft_data.shape
    
    # 应用窗函数
    if window.lower() == 'hanning' or window.lower() == 'hann':  # 同时接受hann和hanning
        win = np.hanning(chirps)
    elif window.lower() == 'hamming':
        win = np.hamming(chirps)
    elif window.lower() == 'blackman':
        win = np.blackman(chirps)
    elif window.lower() == 'rectangular' or window.lower() == 'none':
        win = np.ones(chirps)
    else:
        raise ValueError(f"不支持的窗函数类型: {window}")
    
    # 准备输出数组
    fft_size = chirps * zero_padding_factor
    doppler_fft_data = np.zeros((frames, antennas, fft_size, range_bins), dtype=complex)
    
    # 转置数据以便在chirp维度上执行FFT
    for f in range(frames):
        for a in range(antennas):
            for r in range(range_bins):
                windowed_data = range_fft_data[f, a, :, r] * win
                doppler_fft_data[f, a, :, r] = np.fft.fft(windowed_data, n=fft_size)
    
    return doppler_fft_data

def mti_filter(data, filter_order=2):
    """
    应用移动目标指示(MTI)滤波器，去除静态杂波
    使用均值相消法实现MTI
    
    参数:
        data: 形状为(frames, antennas, chirps, samples)的雷达原始数据
        filter_order: 保留参数（为兼容接口），在均值相消实现中不起作用
    
    返回:
        MTI处理后的数据，形状与输入相同
    """
    # 获取数据维度
    frames, antennas, chirps, samples = data.shape
    
    # 使用与原始数据相同类型的空数组初始化结果
    mti_data = np.zeros_like(data)
    
    # 分别处理每个天线和chirp，避免一次性分配大量内存
    for a in range(antennas):
        for c in range(chirps):
            for s in range(samples):
                # 提取当前处理的1D时间序列
                time_series = data[:, a, c, s]
                # 计算该时间序列的均值
                mean_val = np.mean(time_series)
                # 减去均值并存储结果
                mti_data[:, a, c, s] = time_series - mean_val
    
    return mti_data

def cfar_detector(rd_matrix, guard_cells=2, reference_cells=4, pfa=1e-4, method='ca'):
    """
    恒虚警率(CFAR)检测器，用于信号探测
    
    参数:
        rd_matrix: 距离-多普勒矩阵 (2D数组)
        guard_cells: 保护单元数量
        reference_cells: 参考单元数量
        pfa: 虚警概率
        method: CFAR方法 ('ca'=均匀平均, 'os'=有序统计量, 'go'=最大值)
    
    返回:
        二值掩码指示目标位置
    """
    rows, cols = rd_matrix.shape
    # 功率谱
    power = np.abs(rd_matrix) ** 2
    
    # 计算阈值因子
    if method.lower() == 'ca':
        # Cell Averaging CFAR
        num_ref_cells = reference_cells * 4  # 四边参考单元总数
        threshold_factor = num_ref_cells * (pfa ** (-1/num_ref_cells) - 1)
    elif method.lower() == 'os':
        # Ordered Statistic CFAR
        threshold_factor = 1 / pfa
    elif method.lower() == 'go':
        # Greatest Of CFAR
        threshold_factor = (pfa ** (-1/(2*reference_cells)) - 1)
    else:
        raise ValueError(f"不支持的CFAR方法: {method}")
    
    # 初始化结果矩阵
    detections = np.zeros((rows, cols), dtype=bool)
    
    # 窗口大小
    window_size = guard_cells + reference_cells
    
    # 应用CFAR
    for i in range(window_size, rows - window_size):
        for j in range(window_size, cols - window_size):
            # 当前单元值
            cell = power[i, j]
            
            # 定义保护区域和参考区域
            top = power[i-window_size:i-guard_cells, j]
            bottom = power[i+guard_cells+1:i+window_size+1, j]
            left = power[i, j-window_size:j-guard_cells]
            right = power[i, j+guard_cells+1:j+window_size+1]
            
            # 合并参考单元
            reference = np.concatenate((top, bottom, left, right))
            
            # 计算阈值
            if method.lower() == 'ca':
                threshold = np.mean(reference) * threshold_factor
            elif method.lower() == 'os':
                # 使用排序后的第k个值
                k = int(len(reference) * 0.75)  # 通常使用75%位置的值
                threshold = np.sort(reference)[k] * threshold_factor
            elif method.lower() == 'go':
                # 左右、上下取最大值
                mean1 = max(np.mean(top), np.mean(bottom))
                mean2 = max(np.mean(left), np.mean(right))
                threshold = max(mean1, mean2) * threshold_factor
            
            # 检测
            if cell > threshold:
                detections[i, j] = True
    
    return detections

def extract_phase(radar_data, range_resolution, wavelength, verbose=False):
    """
    使用最大功率距离bin选择法提取目标相位。
    
    参数:
    radar_data: 2D numpy数组，形状为(num_frames, num_range_bins)，雷达距离谱数据
    range_resolution: float，距离分辨率（米/bin）
    wavelength: float，雷达波长（米）
    verbose: bool，是否打印目标信息，默认为False
    
    返回:
    phase_values: 1D numpy数组，目标的相位值
    target_bin: int，目标的距离bin索引
    """
    num_frames, num_range_bins = radar_data.shape
    
    # 设置最小和最大距离范围（米）
    min_range = 0.2  # 最小为0.2米
    max_range = 2.0  # 最大为2.0米
    
    # 转换为bin索引（确保不使用bin 0，它可能代表DC分量）
    min_bin = max(1, int(min_range / range_resolution))
    max_bin = min(num_range_bins - 1, int(max_range / range_resolution))
    
    # 计算距离范围内的平均功率
    if max_bin > min_bin:
        # 对整个时间序列计算每个距离bin的平均功率
        bin_power = np.mean(np.abs(radar_data[:, min_bin:max_bin+1])**2, axis=0)
        # 找到功率最强的bin作为目标bin
        target_bin = min_bin + np.argmax(bin_power)
    else:
        # 如果范围无效，则使用默认方法（整个距离范围内的最强回波）
        bin_power = np.mean(np.abs(radar_data)**2, axis=0)
        target_bin = np.argmax(bin_power)
    
    # 提取目标bin的时间序列
    target_signal = radar_data[:, target_bin]
    
    # 提取相位信息
    phase_values = np.angle(target_signal)
    
    # 只有当verbose为True时才打印
    if verbose:
        target_distance = target_bin * range_resolution
        print(f"检测到目标：距离bin = {target_bin}，距离 = {target_distance:.2f}米")
    
    return phase_values, target_bin 

def extract_phase_edacm(radar_data, range_resolution, wavelength, verbose=False):
    """
    使用增强差分交叉相乘(EDACM)方法提取目标相位。
    
    参数:
    radar_data: 2D numpy数组，形状为(num_frames, num_range_bins)，雷达距离谱数据
    range_resolution: float，距离分辨率（米/bin）
    wavelength: float，雷达波长（米）
    verbose: bool，是否打印目标信息，默认为False
    
    返回:
    phase_values: 1D numpy数组，EDACM方法恢复的相位值
    phase_diff: 1D numpy数组，相位差分结果，增强了心跳信号
    target_bin: int，目标的距离bin索引
    """
    num_frames, num_range_bins = radar_data.shape
    
    # 设置最小和最大距离范围（米）
    min_range = 0.2  # 最小为0.2米
    max_range = 2.0  # 最大为2.0米
    
    # 转换为bin索引（确保不使用bin 0，它可能代表DC分量）
    min_bin = max(1, int(min_range / range_resolution))
    max_bin = min(num_range_bins - 1, int(max_range / range_resolution))
    
    # 计算距离范围内的平均功率
    if max_bin > min_bin:
        # 对整个时间序列计算每个距离bin的平均功率
        bin_power = np.mean(np.abs(radar_data[:, min_bin:max_bin+1])**2, axis=0)
        # 找到功率最强的bin作为目标bin
        target_bin = min_bin + np.argmax(bin_power)
    else:
        # 如果范围无效，则使用默认方法（整个距离范围内的最强回波）
        bin_power = np.mean(np.abs(radar_data)**2, axis=0)
        target_bin = np.argmax(bin_power)
    
    # 提取目标bin的时间序列
    target_signal = radar_data[:, target_bin]
    
    # 解析实部和虚部
    real_part = np.real(target_signal)
    imag_part = np.imag(target_signal)
    
    # 计算角速度函数 (EDACM公式)
    # ω(j,m) = [R(k(j,m))·I'(k(j,m)) - R'(k(j,m))·I(k(j,m))] / [R²(k(j,m)) + I²(k(j,m))]
    # 其中I'和R'分别是I和R的时间导数，使用差分近似
    real_diff = np.diff(real_part, prepend=real_part[0])
    imag_diff = np.diff(imag_part, prepend=imag_part[0])
    
    # 计算分子：R(k)·I'(k) - R'(k)·I(k)
    numerator = real_part * imag_diff - real_diff * imag_part
    
    # 计算分母：R²(k) + I²(k)
    denominator = real_part**2 + imag_part**2
    
    # 防止除零，添加小量epsilon
    epsilon = 1e-10
    denominator = np.maximum(denominator, epsilon)
    
    # 计算角速度
    angular_velocity = numerator / denominator
    
    # 通过积分角速度恢复相位
    # 假设采样间隔Δt=1（可根据实际情况调整）
    delta_t = 1.0  
    
    # 积分操作：φ(j,m) = Σ[ω(j,n)·Δt]
    phase_values = np.cumsum(angular_velocity) * delta_t
    
    # 应用相位差分操作以增强心跳信号
    # φₚ(j,m) = φ(j,m) - φ(j,m-1)
    phase_diff = np.diff(phase_values, append=phase_values[-1])
    
    # 只有当verbose为True时才打印
    if verbose:
        target_distance = target_bin * range_resolution
        print(f"检测到目标：距离bin = {target_bin}，距离 = {target_distance:.2f}米")
    
    return phase_values, phase_diff, target_bin