#!/usr/bin/env python3
"""


2.1 Spectrum Analysis Methods (频谱分析方法):
    - FFT-BPF-Peak: FFT + 带通滤波 + 峰值检测
    - DE-Spectrum: 差分增强 + 频谱分析

2.2 Nonstationary Decomposition Methods (非平稳分解方法):
    - EEMD-Corr-Peak: EEMD + 相关性选择 + 峰值检测
    - SWT-Scale-Peak: 静态小波变换 + 尺度选择 + 峰值检测

2.3 Deep Learning Methods (深度学习方法):
    - LSTM-HR: LSTM网络
    - 1D-CNN-HR: 1D卷积神经网络
"""

import numpy as np
import scipy.signal as signal
from scipy.fft import fft, fftfreq
from scipy.signal import find_peaks, correlate, welch
import pywt
try:
    from PyEMD.EEMD import EEMD
    from PyEMD.EMD import EMD
    PYEMD_AVAILABLE = True
except ImportError:
    print("⚠️ PyEMD未安装，EEMD方法将使用替代实现")
    PYEMD_AVAILABLE = False

try:
    from improved_cnn_hr_method import ImprovedCNNHRMethod
    CNN_METHOD_AVAILABLE = True
except ImportError:
    print("⚠️ 改进CNN方法未找到，将使用简化实现")
    CNN_METHOD_AVAILABLE = False
    EEMD = None
    EMD = None
import tensorflow as tf

class ThreeClassMethods:
    """三类心率检测方法实现类"""

    def __init__(self, fs=30.0):
        """
        初始化

        参数:
            fs: 采样频率 (Hz)
        """
        self.fs = fs
        self.hr_freq_range = (0.8, 2.5)  # 心率频率范围 (Hz)，对应48-150 BPM

    # ========== 2.1 Spectrum Analysis Methods ==========
    
    def fft_bpf_peak_method(self, phase_signal):
        """
        改进的方法1: FFT + 带通滤波 + 峰值检测 (FFT-BPF-Peak)
        完整流程：增强预处理 → 自适应滤波 → 高分辨率频谱分析 → 智能峰值检测 → 生理约束验证

        参数:
            phase_signal: 相位信号，形状为 (N,) 或 (batch_size, N)

        返回:
            heart_rates: 心率估计值 (BPM)
        """
        if phase_signal.ndim == 1:
            phase_signal = phase_signal.reshape(1, -1)

        heart_rates = []

        for signal_sample in phase_signal:
            try:
                # 1. 增强的信号预处理
                signal_sample = self._enhanced_preprocessing_fft(signal_sample)

                # 2. 粗略心率估计用于自适应滤波
                rough_hr = self._rough_hr_estimate_fft(signal_sample)

                # 3. 自适应多级滤波
                filtered_signal = self._adaptive_filtering_fft(signal_sample, rough_hr)

                # 4. 高分辨率频谱分析
                heart_rate = self._high_resolution_spectrum_analysis_fft(filtered_signal)

                # 5. 生理约束验证和后处理
                heart_rate = self._physiological_validation_fft(heart_rate, signal_sample)

                heart_rates.append(heart_rate)

            except Exception as e:
                print(f"FFT-BPF-Peak方法出错: {e}")
                heart_rates.append(75.0)

        return np.array(heart_rates)

    def _enhanced_preprocessing_fft(self, signal_sample):
        """增强的FFT预处理"""
        # 1. 去除直流分量
        signal_sample = signal_sample - np.mean(signal_sample)

        # 2. 去除线性趋势
        signal_sample = signal.detrend(signal_sample, type='linear')

        # 3. 异常值检测和处理
        signal_sample = self._outlier_removal_fft(signal_sample)

        # 4. 自适应标准化
        if np.std(signal_sample) > 1e-6:
            signal_sample = signal_sample / np.std(signal_sample)

        return signal_sample

    def _outlier_removal_fft(self, signal_sample):
        """异常值检测和处理"""
        # 使用3-sigma规则检测异常值
        mean_val = np.mean(signal_sample)
        std_val = np.std(signal_sample)
        threshold = 3 * std_val

        # 标记异常值
        outliers = np.abs(signal_sample - mean_val) > threshold

        if np.any(outliers):
            # 使用中值滤波处理异常值
            from scipy.signal import medfilt
            signal_sample = medfilt(signal_sample, kernel_size=5)

        return signal_sample

    def _rough_hr_estimate_fft(self, signal_sample):
        """粗略心率估计"""
        try:
            # 使用简单的FFT进行粗略估计
            fft_vals = np.abs(fft(signal_sample))
            freqs = fftfreq(len(signal_sample), 1/self.fs)

            pos_mask = (freqs > 0.5) & (freqs < 3.0)
            if np.any(pos_mask):
                freqs_pos = freqs[pos_mask]
                fft_pos = fft_vals[pos_mask]
                peak_idx = np.argmax(fft_pos)
                return freqs_pos[peak_idx] * 60
        except:
            pass
        return 75.0

    def _adaptive_filtering_fft(self, signal_sample, rough_hr):
        """自适应多级滤波"""
        nyquist = self.fs / 2

        # 1. 根据粗略心率调整滤波器参数
        if rough_hr < 70:
            # 低心率：更窄的频带，更高的阶数
            low_freq, high_freq = 0.6, 2.0
            filter_order = 8
        elif rough_hr < 90:
            # 中等心率：标准频带
            low_freq, high_freq = 0.8, 2.5
            filter_order = 6
        else:
            # 高心率：更宽的频带
            low_freq, high_freq = 0.8, 3.0
            filter_order = 4

        # 2. 第一级：宽带预滤波
        try:
            b1, a1 = signal.butter(4, [0.5/nyquist, 4.0/nyquist], btype='band')
            filtered_1 = signal.filtfilt(b1, a1, signal_sample)
        except:
            filtered_1 = signal_sample

        # 3. 第二级：精确带通滤波
        try:
            b2, a2 = signal.butter(filter_order, [low_freq/nyquist, high_freq/nyquist], btype='band')
            filtered_2 = signal.filtfilt(b2, a2, filtered_1)
        except:
            filtered_2 = filtered_1

        # 4. 第三级：陷波滤波器去除工频干扰
        if self.fs > 100:  # 只有在高采样率时才应用
            for notch_freq in [50, 60]:  # 50Hz和60Hz工频
                if notch_freq < nyquist:
                    try:
                        b_notch, a_notch = signal.iirnotch(notch_freq/nyquist, Q=30)
                        filtered_2 = signal.filtfilt(b_notch, a_notch, filtered_2)
                    except:
                        pass

        return filtered_2

    def _high_resolution_spectrum_analysis_fft(self, signal_sample):
        """高分辨率频谱分析"""
        try:
            # 1. 使用Welch方法估计功率谱密度
            freqs, psd = welch(signal_sample, fs=self.fs,
                              nperseg=min(len(signal_sample), 256),
                              noverlap=128,
                              nfft=max(2048, len(signal_sample)*2),
                              window='blackman')

            # 2. 在心率频率范围内寻找峰值
            freq_mask = (freqs >= self.hr_freq_range[0]) & (freqs <= self.hr_freq_range[1])

            if not np.any(freq_mask):
                return 75.0

            hr_freqs = freqs[freq_mask]
            hr_psd = psd[freq_mask]

            # 3. 智能峰值检测
            peak_freq = self._intelligent_peak_detection_fft(hr_freqs, hr_psd)

            return peak_freq * 60  # 转换为BPM

        except Exception as e:
            print(f"频谱分析出错: {e}")
            return 75.0


    def _intelligent_peak_detection_fft(self, freqs, psd):
        """智能峰值检测"""
        # 1. 平滑功率谱
        from scipy.ndimage import gaussian_filter1d
        psd_smooth = gaussian_filter1d(psd, sigma=1.5)

        # 2. 计算自适应阈值
        psd_mean = np.mean(psd_smooth)
        psd_std = np.std(psd_smooth)

        # 使用多个阈值策略
        thresholds = [
            psd_mean + 2 * psd_std,  # 统计阈值
            np.max(psd_smooth) * 0.3,  # 相对阈值
            np.percentile(psd_smooth, 85)  # 百分位阈值
        ]

        best_peak_freq = None
        max_prominence = 0

        for threshold in thresholds:
            # 寻找峰值
            peaks, properties = find_peaks(psd_smooth,
                                         height=threshold,
                                         distance=max(1, len(psd_smooth) // 20),
                                         prominence=psd_std * 0.5)

            if len(peaks) > 0:
                # 选择最突出的峰值
                prominences = properties.get('prominences', np.ones(len(peaks)))
                best_idx = np.argmax(prominences)

                if prominences[best_idx] > max_prominence:
                    max_prominence = prominences[best_idx]
                    best_peak_freq = freqs[peaks[best_idx]]

        # 如果没有找到合适的峰值，使用能量重心
        if best_peak_freq is None:
            best_peak_freq = np.sum(freqs * psd_smooth) / np.sum(psd_smooth)

        return best_peak_freq

    def _physiological_validation_fft(self, hr_estimate, original_signal):
        """生理约束验证"""
        # 1. 基本范围检查
        if hr_estimate < 45 or hr_estimate > 150:
            # 如果超出范围，尝试重新估计
            hr_estimate = self._fallback_estimation_fft(original_signal)

        # 2. 谐波检查
        if hr_estimate > 120:  # 如果心率过高，检查是否为谐波
            half_hr = hr_estimate / 2
            if 50 <= half_hr <= 100:  # 如果一半心率在合理范围内
                hr_estimate = half_hr

        # 3. 信号质量检查
        signal_quality = self._assess_signal_quality_fft(original_signal)
        if signal_quality < 0.3:  # 信号质量差
            # 降低置信度，向默认值回归
            hr_estimate = 0.7 * hr_estimate + 0.3 * 75.0

        return np.clip(hr_estimate, 45, 150)

    def _fallback_estimation_fft(self, signal_sample):
        """备用心率估计方法"""
        try:
            # 使用自相关方法
            autocorr = np.correlate(signal_sample, signal_sample, mode='full')
            autocorr = autocorr[len(autocorr)//2:]

            # 寻找第一个显著的峰值
            min_lag = int(self.fs * 0.4)  # 对应150 BPM
            max_lag = int(self.fs * 1.3)  # 对应45 BPM

            if max_lag < len(autocorr):
                search_range = autocorr[min_lag:max_lag]
                if len(search_range) > 0:
                    peak_lag = min_lag + np.argmax(search_range)
                    return 60 * self.fs / peak_lag
        except:
            pass
        return 75.0

    def _assess_signal_quality_fft(self, signal_sample):
        """评估信号质量"""
        try:
            # 1. 频谱集中度
            freqs, psd = welch(signal_sample, fs=self.fs)
            hr_mask = (freqs >= 0.8) & (freqs <= 2.5)

            if np.any(hr_mask):
                hr_power = np.sum(psd[hr_mask])
                total_power = np.sum(psd)
                spectral_concentration = hr_power / (total_power + 1e-10)
            else:
                spectral_concentration = 0.0

            # 2. 综合质量评分
            quality_score = min(1.0, spectral_concentration * 2)
            return quality_score
        except:
            return 0.5  # 中等质量

    def low_hr_optimized_fft_method(self, phase_signal):
        """
        低心率优化的FFT方法
        专门针对低心率区间(55-70 BPM)的优化版本
        """
        if phase_signal.ndim == 1:
            phase_signal = phase_signal.reshape(1, -1)

        heart_rates = []

        for signal_sample in phase_signal:
            try:
                # 1. 信号预处理
                signal_sample = signal_sample - np.mean(signal_sample)
                signal_sample = signal.detrend(signal_sample, type='linear')

                # 2. 粗略心率估计
                rough_hr = self._rough_hr_estimate_single(signal_sample)

                # 3. 根据粗略估计选择滤波器参数
                if rough_hr < 70:
                    # 低心率区间：使用更窄的频带和更高阶滤波器
                    low_freq, high_freq = 0.6, 2.0  # 36-120 BPM
                    filter_order = 8
                elif rough_hr < 85:
                    # 中等心率区间
                    low_freq, high_freq = 0.8, 2.5  # 48-150 BPM
                    filter_order = 6
                else:
                    # 高心率区间
                    low_freq, high_freq = 0.8, 3.0  # 48-180 BPM
                    filter_order = 4

                # 4. 自适应带通滤波
                nyquist = self.fs / 2
                low = low_freq / nyquist
                high = high_freq / nyquist

                b, a = signal.butter(filter_order, [low, high], btype='band')
                filtered_signal = signal.filtfilt(b, a, signal_sample)

                # 5. 使用Hann窗减少频谱泄漏
                window = signal.windows.hann(len(filtered_signal))
                windowed_signal = filtered_signal * window

                # 6. FFT分析
                fft_vals = np.abs(fft(windowed_signal))
                freqs = fftfreq(len(windowed_signal), 1/self.fs)

                # 7. 心率频率范围分析
                hr_mask = (freqs > 0) & (freqs >= low_freq) & (freqs <= high_freq)
                hr_freqs = freqs[hr_mask]
                hr_fft = fft_vals[hr_mask]

                if len(hr_fft) > 0:
                    # 8. 找到峰值频率
                    peak_idx = np.argmax(hr_fft)
                    peak_freq = hr_freqs[peak_idx]
                    heart_rate = peak_freq * 60

                    # 9. 对低心率进行Welch方法二次验证
                    if heart_rate < 75:
                        freqs_welch, psd = signal.welch(
                            filtered_signal,
                            fs=self.fs,
                            nperseg=min(128, len(filtered_signal)//2)
                        )
                        hr_mask_welch = (freqs_welch >= low_freq) & (freqs_welch <= high_freq)
                        hr_freqs_welch = freqs_welch[hr_mask_welch]
                        hr_psd = psd[hr_mask_welch]

                        if len(hr_psd) > 0:
                            peak_idx_welch = np.argmax(hr_psd)
                            heart_rate_welch = hr_freqs_welch[peak_idx_welch] * 60

                            # 如果两种方法结果相近，取平均值
                            if abs(heart_rate - heart_rate_welch) < 10:
                                heart_rate = (heart_rate + heart_rate_welch) / 2
                            else:
                                # 选择功率更强的结果
                                if hr_psd[peak_idx_welch] > hr_fft[peak_idx]:
                                    heart_rate = heart_rate_welch

                    # 10. 合理性检查
                    heart_rate = np.clip(heart_rate, 45, 150)

                else:
                    heart_rate = 75.0

            except Exception as e:
                print(f"低心率优化FFT方法出错: {e}")
                heart_rate = 75.0

            heart_rates.append(heart_rate)

        return np.array(heart_rates)

    def _rough_hr_estimate_single(self, signal_sample):
        """单个信号的粗略心率估计"""
        try:
            # 使用宽带滤波器进行粗略估计
            nyquist = self.fs / 2
            b, a = signal.butter(4, [0.5/nyquist, 3.0/nyquist], btype='band')
            filtered_signal = signal.filtfilt(b, a, signal_sample)

            fft_vals = np.abs(fft(filtered_signal))
            freqs = fftfreq(len(filtered_signal), 1/self.fs)

            pos_mask = (freqs > 0.5) & (freqs < 3.0)
            freqs = freqs[pos_mask]
            fft_vals = fft_vals[pos_mask]

            if len(fft_vals) > 0:
                peak_idx = np.argmax(fft_vals)
                return freqs[peak_idx] * 60
        except:
            pass

        return 75.0  # 默认值

    def welch_optimized_method(self, phase_signal):
        """
        Welch优化方法 - 专门针对低心率优化
        基于分析发现Welch方法在低心率区间表现最佳
        """
        if phase_signal.ndim == 1:
            phase_signal = phase_signal.reshape(1, -1)

        heart_rates = []

        for signal_sample in phase_signal:
            try:
                # 1. 信号预处理
                signal_sample = signal_sample - np.mean(signal_sample)
                signal_sample = signal.detrend(signal_sample, type='linear')

                # 2. 信号质量评估
                snr = self._calculate_snr_simple(signal_sample)

                # 3. 自适应参数选择
                if snr > 0.3:  # 相对高质量信号
                    freq_range = (0.6, 2.2)
                    filter_order = 6
                    nperseg_factor = 4
                elif snr > 0.15:  # 中等质量信号
                    freq_range = (0.7, 2.0)
                    filter_order = 8
                    nperseg_factor = 3
                else:  # 低质量信号
                    freq_range = (0.8, 1.8)
                    filter_order = 10
                    nperseg_factor = 2

                # 4. 自适应带通滤波
                nyquist = self.fs / 2
                low, high = freq_range
                b, a = signal.butter(filter_order, [low/nyquist, high/nyquist], btype='band')
                filtered_signal = signal.filtfilt(b, a, signal_sample)

                # 5. Welch功率谱密度估计
                nperseg = min(len(filtered_signal)//nperseg_factor, 256)
                nperseg = max(nperseg, 32)  # 确保最小窗口大小

                from scipy.signal import welch
                freqs, psd = welch(
                    filtered_signal,
                    fs=self.fs,
                    window='blackman',  # 使用Blackman窗减少频谱泄漏
                    nperseg=nperseg,
                    noverlap=nperseg//2,
                    detrend='linear'
                )

                # 6. 心率频率范围分析
                hr_mask = (freqs >= low) & (freqs <= high)
                hr_freqs = freqs[hr_mask]
                hr_psd = psd[hr_mask]

                if len(hr_psd) > 0:
                    # 7. 功率谱平滑
                    from scipy.ndimage import gaussian_filter1d
                    hr_psd_smooth = gaussian_filter1d(hr_psd, sigma=1.0)

                    # 8. 智能峰值检测
                    # 计算动态阈值
                    mean_psd = np.mean(hr_psd_smooth)
                    std_psd = np.std(hr_psd_smooth)
                    max_psd = np.max(hr_psd_smooth)

                    # 使用更保守的阈值策略
                    threshold = max(
                        mean_psd + 1.5 * std_psd,  # 统计阈值
                        max_psd * 0.2  # 相对阈值
                    )

                    # 寻找峰值
                    peaks, properties = find_peaks(
                        hr_psd_smooth,
                        height=threshold,
                        distance=max(1, int(0.05 * len(hr_psd_smooth))),  # 最小峰值距离
                        prominence=std_psd * 0.5
                    )

                    if len(peaks) > 0:
                        # 选择最显著的峰值
                        peak_scores = hr_psd_smooth[peaks]
                        if 'prominences' in properties:
                            peak_scores *= properties['prominences']

                        best_peak_idx = peaks[np.argmax(peak_scores)]
                        peak_freq = hr_freqs[best_peak_idx]
                    else:
                        # 如果没有找到峰值，使用最大值位置
                        peak_idx = np.argmax(hr_psd_smooth)
                        peak_freq = hr_freqs[peak_idx]

                    # 9. 转换为BPM
                    heart_rate = peak_freq * 60

                    # 10. 合理性检查和后处理
                    heart_rate = self._post_process_hr_simple(heart_rate, signal_sample)

                else:
                    heart_rate = 75.0  # 默认心率

            except Exception as e:
                print(f"Welch优化方法出错: {e}")
                heart_rate = 75.0

            heart_rates.append(heart_rate)

        return np.array(heart_rates)

    def _calculate_snr_simple(self, signal_data):
        """简单信噪比计算"""
        try:
            # 心率信号频带
            nyquist = self.fs / 2
            b, a = signal.butter(4, [0.6/nyquist, 2.5/nyquist], btype='band')
            signal_component = signal.filtfilt(b, a, signal_data)

            # 噪声
            noise_component = signal_data - signal_component

            signal_power = np.var(signal_component)
            noise_power = np.var(noise_component)

            return signal_power / noise_power if noise_power > 0 else 0
        except:
            return 0.1

    def _post_process_hr_simple(self, heart_rate, signal_sample):
        """简单心率后处理"""
        # 1. 基本范围约束
        heart_rate = np.clip(heart_rate, 45, 150)

        # 2. 谐波检查
        if heart_rate > 120:
            # 检查是否为二次谐波
            half_hr = heart_rate / 2
            if 50 <= half_hr <= 100:
                heart_rate = half_hr

        return heart_rate

    def de_spectrum_method(self, phase_signal):
        """
        方法2: 差分增强 + 频谱分析 (DE-Spectrum)
        完整流程：相位提取 → 差分增强 → FFT变换 → 谐波抑制 → 峰值检测 → 心率值

        参数:
            phase_signal: 相位信号，形状为 (N,) 或 (batch_size, N)

        返回:
            heart_rates: 心率估计值 (BPM)
        """
        if phase_signal.ndim == 1:
            phase_signal = phase_signal.reshape(1, -1)

        heart_rates = []

        for signal_sample in phase_signal:
            # 1. 去除直流分量
            signal_sample = signal_sample - np.mean(signal_sample)

            # 2. 差分增强处理
            # 一阶差分：突出快速变化（心跳）
            diff1 = np.diff(signal_sample)
            # 二阶差分：进一步增强心跳特征
            diff2 = np.diff(diff1)

            # 选择最优差分信号（基于信号能量）
            energy1 = np.var(diff1)
            energy2 = np.var(diff2)

            if energy2 > energy1 * 0.5:  # 二阶差分有足够能量
                enhanced_signal = diff2
            else:
                enhanced_signal = diff1

            # 3. 对差分增强后的信号进行FFT
            # 补零到原始长度
            if len(enhanced_signal) < len(signal_sample):
                enhanced_signal = np.pad(enhanced_signal,
                                       (0, len(signal_sample) - len(enhanced_signal)),
                                       'constant')

            # 应用窗函数
            windowed_signal = enhanced_signal * np.hanning(len(enhanced_signal))

            # FFT变换
            fft_result = fft(windowed_signal)
            freqs = fftfreq(len(windowed_signal), 1/self.fs)

            # 4. 频域分析
            positive_freqs = freqs[:len(freqs)//2]
            magnitude = np.abs(fft_result[:len(fft_result)//2])

            # 5. 谐波抑制：识别并抑制呼吸谐波
            # 呼吸频率通常在0.2-0.5 Hz
            resp_freq_mask = (positive_freqs >= 0.2) & (positive_freqs <= 0.5)
            if np.any(resp_freq_mask):
                resp_magnitudes = magnitude[resp_freq_mask]
                resp_freqs = positive_freqs[resp_freq_mask]

                if len(resp_magnitudes) > 0:
                    # 找到呼吸主频率
                    resp_peak_idx = np.argmax(resp_magnitudes)
                    resp_freq = resp_freqs[resp_peak_idx]

                    # 抑制呼吸谐波（2倍、3倍频率）
                    for harmonic in [2, 3]:
                        harmonic_freq = resp_freq * harmonic
                        harmonic_mask = np.abs(positive_freqs - harmonic_freq) < 0.1
                        magnitude[harmonic_mask] *= 0.3  # 衰减谐波

            # 6. 心率频段峰值检测
            freq_mask = (positive_freqs >= self.hr_freq_range[0]) & (positive_freqs <= self.hr_freq_range[1])

            if np.any(freq_mask):
                hr_freqs = positive_freqs[freq_mask]
                hr_magnitudes = magnitude[freq_mask]

                # 峰值检测
                peaks, properties = find_peaks(hr_magnitudes,
                                             height=np.max(hr_magnitudes) * 0.2,
                                             distance=int(0.1 * self.fs))  # 最小峰值间距

                if len(peaks) > 0:
                    # 选择最高峰值
                    best_peak_idx = peaks[np.argmax(hr_magnitudes[peaks])]
                    peak_freq = hr_freqs[best_peak_idx]
                else:
                    # 备选方案：最大值
                    peak_idx = np.argmax(hr_magnitudes)
                    peak_freq = hr_freqs[peak_idx]

                # 转换为BPM
                heart_rate = peak_freq * 60
                heart_rate = np.clip(heart_rate, 48, 120)
            else:
                heart_rate = 75.0  # 默认心率

            heart_rates.append(heart_rate)

        return np.array(heart_rates)

    # ========== 2.2 Nonstationary Decomposition Methods ==========
    
    def eemd_corr_peak_method(self, phase_signal):
        """
        改进的方法3: EEMD + 智能IMF选择 + 多域融合 (EEMD-Corr-Peak)
        完整流程：增强预处理 → 稳定分解 → 智能IMF选择 → 多域心率估计 → 生理约束验证

        参数:
            phase_signal: 相位信号，形状为 (N,) 或 (batch_size, N)

        返回:
            heart_rates: 心率估计值 (BPM)
        """
        if phase_signal.ndim == 1:
            phase_signal = phase_signal.reshape(1, -1)

        heart_rates = []

        for signal_sample in phase_signal:
            try:
                # 1. 增强的信号预处理
                processed_signal = self._enhanced_preprocessing_eemd(signal_sample)

                # 2. 稳定的多尺度分解
                imfs = self._stable_decomposition_eemd(processed_signal)

                # 3. 智能IMF选择和融合
                reconstructed_signal = self._intelligent_imf_selection_eemd(imfs, processed_signal)

                # 4. 多域心率估计
                hr_estimate = self._multi_domain_hr_estimation_eemd(reconstructed_signal)

                # 5. 生理约束验证
                hr_estimate = self._physiological_validation_eemd(hr_estimate, signal_sample)

                heart_rates.append(hr_estimate)

            except Exception as e:
                print(f"EEMD-Corr-Peak方法出错: {e}")
                heart_rates.append(75.0)

        return np.array(heart_rates)

    def _enhanced_preprocessing_eemd(self, signal_sample):
        """增强的EEMD预处理"""
        # 1. 去除直流分量
        signal_sample = signal_sample - np.mean(signal_sample)

        # 2. 去除线性趋势
        signal_sample = signal.detrend(signal_sample, type='linear')

        # 3. 异常值检测和处理
        signal_sample = self._outlier_removal_eemd(signal_sample)

        # 4. 自适应标准化
        if np.std(signal_sample) > 1e-6:
            signal_sample = signal_sample / np.std(signal_sample)

        return signal_sample

    def _outlier_removal_eemd(self, signal_sample):
        """异常值检测和处理"""
        # 使用3-sigma规则检测异常值
        mean_val = np.mean(signal_sample)
        std_val = np.std(signal_sample)
        threshold = 3 * std_val

        # 标记异常值
        outliers = np.abs(signal_sample - mean_val) > threshold

        if np.any(outliers):
            # 使用中值滤波处理异常值
            from scipy.signal import medfilt
            signal_sample = medfilt(signal_sample, kernel_size=5)

        return signal_sample

    def _stable_decomposition_eemd(self, signal_sample):
        """稳定的多尺度信号分解"""
        if PYEMD_AVAILABLE:
            try:
                # 使用EEMD进行稳定分解
                eemd = EEMD()
                eemd.noise_width = 0.005  # 减少噪声幅度
                eemd.trials = 50  # 减少试验次数提高速度
                imfs = eemd.eemd(signal_sample)
                return imfs
            except:
                pass

        # 使用改进的滤波器组分解作为替代
        return self._improved_filter_bank_decomposition_eemd(signal_sample)

    def _improved_filter_bank_decomposition_eemd(self, signal_sample):
        """改进的滤波器组分解"""
        imfs = []
        nyquist = self.fs / 2

        # 定义多个频段，模拟IMF
        freq_bands = [
            (0.1, 0.5),   # 极低频分量
            (0.5, 1.2),   # 低频分量
            (1.2, 2.8),   # 心率主频段
            (2.8, 6.0),   # 高频分量
            (6.0, min(12.0, nyquist-0.1))  # 噪声分量
        ]

        for low, high in freq_bands:
            if high >= nyquist:
                high = nyquist - 0.1
            if low >= high:
                continue

            try:
                # 设计带通滤波器
                b, a = signal.butter(4, [low/nyquist, high/nyquist], btype='band')
                imf = signal.filtfilt(b, a, signal_sample)
                imfs.append(imf)
            except:
                continue

        # 添加残差分量
        if len(imfs) > 0:
            residual = signal_sample - np.sum(imfs, axis=0)
            imfs.append(residual)

        return np.array(imfs) if len(imfs) > 0 else np.array([signal_sample])


    def _intelligent_imf_selection_eemd(self, imfs, original_signal):
        """智能IMF选择和融合"""
        if len(imfs) == 0:
            return original_signal

        # 1. 计算每个IMF的特征
        imf_features = []
        for i, imf in enumerate(imfs):
            features = self._calculate_imf_features_eemd(imf)
            features['index'] = i
            imf_features.append(features)

        # 2. 基于多个准则选择IMF
        selected_imfs = []

        for features in imf_features:
            # 频率准则：IMF主频率在心率范围内
            if (features['dominant_freq'] >= 0.6 and
                features['dominant_freq'] <= 3.0):
                selected_imfs.append(features['index'])
                continue

            # 能量准则：IMF包含足够的能量
            if features['energy_ratio'] > 0.05:
                selected_imfs.append(features['index'])
                continue

            # 相关性准则：与原信号相关性高
            if features['correlation'] > 0.3:
                selected_imfs.append(features['index'])

        # 3. 如果没有选中任何IMF，选择能量最大的几个
        if len(selected_imfs) == 0:
            energies = [f['energy_ratio'] for f in imf_features]
            selected_imfs = [np.argmax(energies)]

        # 4. 加权融合选中的IMF
        if len(selected_imfs) == 1:
            return imfs[selected_imfs[0]]
        else:
            weights = []
            for idx in selected_imfs:
                weight = imf_features[idx]['correlation'] * imf_features[idx]['energy_ratio']
                weights.append(weight)

            weights = np.array(weights)
            weights = weights / np.sum(weights)  # 归一化

            reconstructed = np.zeros_like(original_signal)
            for i, idx in enumerate(selected_imfs):
                reconstructed += weights[i] * imfs[idx]

            return reconstructed

    def _calculate_imf_features_eemd(self, imf):
        """计算IMF特征"""
        features = {}

        # 1. 主频率
        try:
            freqs, psd = welch(imf, fs=self.fs, nperseg=min(len(imf), 128))
            features['dominant_freq'] = freqs[np.argmax(psd)]
        except:
            features['dominant_freq'] = 0.0

        # 2. 能量比例
        features['energy_ratio'] = np.var(imf) / (np.var(imf) + 1e-10)

        # 3. 与原信号的相关性（这里用自相关代替）
        try:
            autocorr = np.correlate(imf, imf, mode='full')
            features['correlation'] = np.max(autocorr) / (np.linalg.norm(imf)**2 + 1e-10)
        except:
            features['correlation'] = 0.0

        return features

    def _multi_domain_hr_estimation_eemd(self, signal_sample):
        """多域心率估计"""
        estimates = []

        # 1. 频域估计
        freq_estimate = self._frequency_domain_estimation_eemd(signal_sample)
        estimates.append(freq_estimate)

        # 2. 时域估计
        time_estimate = self._time_domain_estimation_eemd(signal_sample)
        estimates.append(time_estimate)

        # 3. 时频域估计
        tf_estimate = self._time_frequency_estimation_eemd(signal_sample)
        estimates.append(tf_estimate)

        # 4. 融合多个估计
        estimates = [e for e in estimates if 45 <= e <= 150]  # 过滤不合理的估计

        if len(estimates) == 0:
            return 75.0
        elif len(estimates) == 1:
            return estimates[0]
        else:
            # 使用中位数作为最终估计
            return np.median(estimates)

    def fft_bpf_peak_method_long_term(self, phase_signal):
        """
        简化但有效的FFT长时监测方法

        主要改进:
        1. 信号质量自适应滤波
        2. 简单的时间平滑
        3. 生理约束
        """
        if phase_signal.ndim == 1:
            phase_signal = phase_signal.reshape(1, -1)

        heart_rates = []
        history_buffer = []

        for signal_sample in phase_signal:
            try:
                # 1. 信号质量自适应滤波
                filtered_signal, snr = self._adaptive_filtering_based_on_quality(signal_sample)

                # 2. 基础FFT预测
                base_hr = self._single_fft_prediction(filtered_signal)

                # 3. 简单的时间平滑
                if len(history_buffer) > 0:
                    smoothed_hr = self._simple_temporal_smoothing(base_hr, history_buffer)
                else:
                    smoothed_hr = base_hr

                # 4. 生理约束
                final_hr = np.clip(smoothed_hr, 45, 150)

                heart_rates.append(final_hr)
                history_buffer.append(final_hr)

                # 保持历史缓存大小
                if len(history_buffer) > 10:
                    history_buffer.pop(0)

            except Exception as e:
                print(f"长时FFT方法出错: {e}")
                # 使用历史平均或默认值
                if len(history_buffer) > 0:
                    heart_rates.append(np.mean(history_buffer[-3:]))
                else:
                    heart_rates.append(75.0)

        return np.array(heart_rates)

    def eemd_corr_peak_method_long_term(self, phase_signal):
        """
        简化但有效的EEMD长时监测方法

        主要改进:
        1. 信号质量自适应处理
        2. 简单的时间平滑
        3. 生理约束
        """
        if phase_signal.ndim == 1:
            phase_signal = phase_signal.reshape(1, -1)

        heart_rates = []
        history_buffer = []

        for signal_sample in phase_signal:
            try:
                # 1. 信号质量评估
                _, snr = self._adaptive_filtering_based_on_quality(signal_sample)

                # 2. 基于质量选择处理策略
                if snr > 3:  # 高质量，使用EEMD
                    base_hr = self._single_eemd_prediction(signal_sample, [])
                else:  # 低质量，使用更稳定的滤波器组
                    base_hr = self._single_fft_prediction(signal_sample)

                # 3. 简单的时间平滑（EEMD允许更大变化）
                if len(history_buffer) > 0:
                    smoothed_hr = self._simple_temporal_smoothing(base_hr, history_buffer, max_change_rate=15)
                else:
                    smoothed_hr = base_hr

                # 4. 生理约束
                final_hr = np.clip(smoothed_hr, 45, 150)

                heart_rates.append(final_hr)
                history_buffer.append(final_hr)

                # 保持历史缓存大小
                if len(history_buffer) > 8:
                    history_buffer.pop(0)

            except Exception as e:
                print(f"长时EEMD方法出错: {e}")
                if len(history_buffer) > 0:
                    heart_rates.append(np.mean(history_buffer[-2:]))
                else:
                    heart_rates.append(75.0)

        return np.array(heart_rates)

    def _single_fft_prediction(self, signal_sample):
        """单个信号的FFT预测"""
        # 使用改进的FFT方法进行单次预测
        processed_signal = self._enhanced_preprocessing_fft(signal_sample)
        rough_hr = self._rough_hr_estimate_fft(signal_sample)
        filtered_signal = self._adaptive_filtering_fft(processed_signal, rough_hr)
        hr_estimate = self._high_resolution_spectrum_analysis_fft(filtered_signal)
        return self._physiological_validation_fft(hr_estimate, signal_sample)

    def _single_eemd_prediction(self, signal_sample, imf_history):
        """单个信号的EEMD预测"""
        processed_signal = self._enhanced_preprocessing_eemd(signal_sample)
        imfs = self._stable_decomposition_eemd(processed_signal)
        reconstructed_signal = self._intelligent_imf_selection_eemd(imfs, processed_signal)
        hr_estimate = self._multi_domain_hr_estimation_eemd(reconstructed_signal)
        return self._physiological_validation_eemd(hr_estimate, signal_sample)

    def _predict_next_hr(self, history_buffer):
        """基于历史数据预测下一个心率值"""
        if len(history_buffer) < 3:
            return 75.0

        # 简单的线性趋势预测
        recent_values = np.array(history_buffer[-5:])
        if len(recent_values) >= 3:
            # 使用最小二乘法拟合趋势
            x = np.arange(len(recent_values))
            coeffs = np.polyfit(x, recent_values, 1)
            predicted = coeffs[0] * len(recent_values) + coeffs[1]
            return np.clip(predicted, 45, 150)
        else:
            return np.mean(recent_values)

    def _calculate_adaptive_alpha(self, history_buffer, current_hr):
        """计算自适应平滑系数"""
        if len(history_buffer) < 5:
            return 0.3  # 默认值

        # 基于历史变异性调整平滑系数
        recent_std = np.std(history_buffer[-10:])

        if recent_std < 2:  # 稳定期
            return 0.2  # 更多平滑
        elif recent_std < 5:  # 中等变化
            return 0.3  # 适中平滑
        else:  # 高变化期
            return 0.5  # 较少平滑

    def _analyze_trend(self, recent_values):
        """分析心率趋势"""
        if len(recent_values) < 3:
            return 0

        # 计算线性趋势斜率
        x = np.arange(len(recent_values))
        coeffs = np.polyfit(x, recent_values, 1)
        return coeffs[0]  # 斜率

    def _apply_trend_correction(self, current_hr, trend):
        """应用趋势修正"""
        # 如果趋势过于陡峭，进行修正
        if abs(trend) > 2:  # 每步变化超过2 BPM
            # 限制变化幅度
            correction_factor = 0.5
            corrected_trend = trend * correction_factor
            return current_hr + corrected_trend
        return current_hr

    def _assess_signal_quality_realtime(self, signal_sample, history_buffer):
        """实时信号质量评估"""
        try:
            # 1. 频谱集中度
            freqs, psd = welch(signal_sample, fs=self.fs, nperseg=min(len(signal_sample), 128))
            hr_mask = (freqs >= 0.8) & (freqs <= 2.5)

            if np.any(hr_mask):
                hr_power = np.sum(psd[hr_mask])
                total_power = np.sum(psd)
                spectral_concentration = hr_power / (total_power + 1e-10)
            else:
                spectral_concentration = 0.0

            # 2. 信噪比估计
            signal_power = np.var(signal_sample)
            noise_power = np.var(signal_sample - signal.medfilt(signal_sample, 5))
            snr = signal_power / (noise_power + 1e-10)
            snr_normalized = min(1.0, snr / 10.0)  # 归一化到0-1

            # 3. 时间一致性（如果有历史数据）
            if len(history_buffer) >= 3:
                recent_std = np.std(history_buffer[-3:])
                temporal_consistency = max(0.0, 1.0 - recent_std / 20.0)  # 20 BPM为最大可接受变异
            else:
                temporal_consistency = 0.5  # 默认中等

            # 综合质量评分
            quality_score = (spectral_concentration * 0.4 +
                           snr_normalized * 0.3 +
                           temporal_consistency * 0.3)

            return np.clip(quality_score, 0.0, 1.0)
        except:
            return 0.5  # 默认中等质量

    def _adaptive_parameter_adjustment(self, signal_quality):
        """基于信号质量调整参数"""
        if signal_quality > 0.8:  # 高质量
            return {
                'filter_order': 4,
                'threshold_factor': 1.0,
                'smoothing_factor': 0.1
            }
        elif signal_quality > 0.5:  # 中等质量
            return {
                'filter_order': 6,
                'threshold_factor': 1.5,
                'smoothing_factor': 0.2
            }
        else:  # 低质量
            return {
                'filter_order': 8,
                'threshold_factor': 2.0,
                'smoothing_factor': 0.3
            }

    def _quality_driven_fft_prediction(self, signal_sample, params):
        """质量驱动的FFT预测"""
        # 使用调整后的参数进行FFT预测
        processed_signal = self._enhanced_preprocessing_fft(signal_sample)

        # 自适应滤波
        nyquist = self.fs / 2
        filter_order = params['filter_order']

        try:
            b, a = signal.butter(filter_order, [0.8/nyquist, 2.5/nyquist], btype='band')
            filtered_signal = signal.filtfilt(b, a, processed_signal)
        except:
            filtered_signal = processed_signal

        # 高分辨率频谱分析
        hr_estimate = self._high_resolution_spectrum_analysis_fft(filtered_signal)

        return hr_estimate

    def _multi_scale_temporal_constraint(self, current_hr, history_buffer):
        """多尺度时间连续性约束"""
        constraints = []

        # 1. 短时约束（最近3个值）
        if len(history_buffer) >= 3:
            recent_avg = np.mean(history_buffer[-3:])
            short_term_constraint = 0.7 * current_hr + 0.3 * recent_avg
            constraints.append(short_term_constraint)

        # 2. 中时约束（最近30个值，约1分钟）
        if len(history_buffer) >= 30:
            medium_avg = np.mean(history_buffer[-30:])
            medium_term_constraint = 0.9 * current_hr + 0.1 * medium_avg
            constraints.append(medium_term_constraint)

        # 3. 长时约束（最近150个值，约5分钟）
        if len(history_buffer) >= 150:
            long_avg = np.mean(history_buffer[-150:])
            long_term_constraint = 0.95 * current_hr + 0.05 * long_avg
            constraints.append(long_term_constraint)

        if len(constraints) == 0:
            return current_hr
        elif len(constraints) == 1:
            return constraints[0]
        else:
            # 加权平均多个约束
            weights = [0.6, 0.3, 0.1][:len(constraints)]
            weights = np.array(weights) / np.sum(weights)
            return np.average(constraints, weights=weights)

    def _physiological_reasonableness_check(self, current_hr, history_buffer):
        """生理合理性验证"""
        if len(history_buffer) == 0:
            return current_hr

        last_hr = history_buffer[-1]

        # 1. 变化率限制（每2秒最大变化）
        max_change_per_2s = 5.0  # 5 BPM per 2 seconds

        if abs(current_hr - last_hr) > max_change_per_2s:
            if current_hr > last_hr:
                current_hr = last_hr + max_change_per_2s
            else:
                current_hr = last_hr - max_change_per_2s

        # 2. 统计异常检测
        if len(history_buffer) >= 10:
            recent_mean = np.mean(history_buffer[-10:])
            recent_std = np.std(history_buffer[-10:])

            # 3-sigma规则
            if abs(current_hr - recent_mean) > 3 * recent_std:
                # 使用2-sigma边界
                if current_hr > recent_mean:
                    current_hr = recent_mean + 2 * recent_std
                else:
                    current_hr = recent_mean - 2 * recent_std

        return current_hr

    def _adaptive_recalibration(self, history_buffer):
        """自适应重校准"""
        if len(history_buffer) < 50:
            return 0.0

        # 计算最近50个值的趋势
        recent_values = np.array(history_buffer[-50:])
        x = np.arange(len(recent_values))

        try:
            # 线性回归检测系统偏差
            coeffs = np.polyfit(x, recent_values, 1)
            trend = coeffs[0]  # 斜率

            # 如果有显著趋势，计算偏差校正
            if abs(trend) > 0.1:  # 每个时间步0.1 BPM的趋势
                # 预测未来的偏差
                future_bias = trend * 25  # 预测未来25步的偏差
                return future_bias * 0.1  # 轻度校正
        except:
            pass

        return 0.0

    def _adaptive_filtering_based_on_quality(self, signal_sample):
        """基于信号质量的自适应滤波"""
        try:
            # 1. 评估信号质量
            signal_power = np.var(signal_sample)
            noise_level = np.var(signal_sample - signal.medfilt(signal_sample, 5))
            snr = signal_power / (noise_level + 1e-10)

            # 2. 根据SNR调整滤波强度
            if snr > 5:  # 高质量
                filter_order = 4
                freq_range = [0.8, 2.5]
            elif snr > 2:  # 中等质量
                filter_order = 6
                freq_range = [0.9, 2.3]  # 稍微收窄频带
            else:  # 低质量
                filter_order = 8
                freq_range = [1.0, 2.0]  # 显著收窄频带

            # 3. 应用自适应滤波
            nyquist = self.fs / 2
            b, a = signal.butter(filter_order, [f/nyquist for f in freq_range], btype='band')
            filtered_signal = signal.filtfilt(b, a, signal_sample)

            return filtered_signal, snr
        except:
            # 如果滤波失败，返回原信号
            return signal_sample, 1.0

    def _simple_temporal_smoothing(self, current_prediction, history_buffer, max_change_rate=10):
        """简单的时间平滑"""
        if len(history_buffer) == 0:
            return current_prediction

        last_prediction = history_buffer[-1]

        # 限制变化率（每2秒最大变化）
        max_change = max_change_rate * (2/60)  # 转换为2秒间隔

        if abs(current_prediction - last_prediction) > max_change:
            if current_prediction > last_prediction:
                smoothed = last_prediction + max_change
            else:
                smoothed = last_prediction - max_change
        else:
            smoothed = current_prediction

        # 轻度指数平滑
        alpha = 0.7  # 平滑因子
        final_prediction = alpha * smoothed + (1 - alpha) * last_prediction

        return final_prediction

    def _adaptive_eemd_prediction(self, signal_sample, signal_quality, imf_quality_buffer):
        """自适应EEMD预测"""
        try:
            # 1. 基于质量选择分解策略
            if signal_quality > 0.7:
                # 高质量：使用标准EEMD
                imfs = self._stable_decomposition_eemd(signal_sample)
            elif signal_quality > 0.4:
                # 中等质量：使用更稳定的参数
                imfs = self._conservative_decomposition_eemd(signal_sample)
            else:
                # 低质量：使用滤波器组替代
                imfs = self._improved_filter_bank_decomposition_eemd(signal_sample)

            # 2. 智能IMF选择
            reconstructed_signal = self._intelligent_imf_selection_eemd(imfs, signal_sample)

            # 3. 多域心率估计
            hr_estimate = self._multi_domain_hr_estimation_eemd(reconstructed_signal)

            return hr_estimate

        except Exception as e:
            print(f"自适应EEMD预测出错: {e}")
            return 75.0

    def _conservative_decomposition_eemd(self, signal_sample):
        """保守的EEMD分解（用于中等质量信号）"""
        if PYEMD_AVAILABLE:
            try:
                eemd = EEMD()
                eemd.noise_width = 0.002  # 更小的噪声
                eemd.trials = 30  # 更少的试验次数
                imfs = eemd.eemd(signal_sample)
                return imfs
            except:
                pass

        # 备用方案
        return self._improved_filter_bank_decomposition_eemd(signal_sample)

    def _multi_domain_validation(self, base_hr, signal_sample, history_buffer):
        """多域验证"""
        validations = []

        # 1. 频域验证
        freq_hr = self._frequency_domain_estimation_eemd(signal_sample)
        if 45 <= freq_hr <= 150:
            validations.append(freq_hr)

        # 2. 时域验证
        time_hr = self._time_domain_estimation_eemd(signal_sample)
        if 45 <= time_hr <= 150:
            validations.append(time_hr)

        # 3. 历史一致性验证
        if len(history_buffer) >= 5:
            recent_avg = np.mean(history_buffer[-5:])
            if abs(base_hr - recent_avg) < 15:  # 与历史一致
                validations.append(base_hr)

        # 4. 融合验证结果
        if len(validations) == 0:
            return base_hr
        elif len(validations) == 1:
            return validations[0]
        else:
            # 使用中位数减少异常值影响
            return np.median(validations)

    def _eemd_temporal_constraint(self, current_hr, history_buffer):
        """EEMD时间连续性约束"""
        if len(history_buffer) == 0:
            return current_hr

        # 1. 计算历史变异性
        if len(history_buffer) >= 10:
            recent_std = np.std(history_buffer[-10:])
        else:
            recent_std = np.std(history_buffer)

        # 2. 基于变异性调整约束强度
        if recent_std < 3:  # 稳定期
            constraint_strength = 0.3
        elif recent_std < 8:  # 中等变化
            constraint_strength = 0.2
        else:  # 高变化期
            constraint_strength = 0.1

        # 3. 应用约束
        recent_avg = np.mean(history_buffer[-min(5, len(history_buffer)):])
        constrained_hr = (1 - constraint_strength) * current_hr + constraint_strength * recent_avg

        # 4. 变化率限制
        last_hr = history_buffer[-1]
        max_change = 8.0  # EEMD允许更大的变化

        if abs(constrained_hr - last_hr) > max_change:
            if constrained_hr > last_hr:
                constrained_hr = last_hr + max_change
            else:
                constrained_hr = last_hr - max_change

        return constrained_hr

    def _frequency_domain_estimation_eemd(self, signal_sample):
        """频域心率估计"""
        try:
            freqs, psd = welch(signal_sample, fs=self.fs, nperseg=min(len(signal_sample), 256))
            freq_mask = (freqs >= 0.8) & (freqs <= 2.5)

            if np.any(freq_mask):
                hr_freqs = freqs[freq_mask]
                hr_psd = psd[freq_mask]
                peak_freq = hr_freqs[np.argmax(hr_psd)]
                return peak_freq * 60
        except:
            pass
        return 75.0

    def _time_domain_estimation_eemd(self, signal_sample):
        """时域心率估计"""
        try:
            # 寻找峰值
            peaks, _ = find_peaks(signal_sample,
                                distance=int(self.fs * 0.4),  # 最小间距0.4秒
                                height=np.std(signal_sample) * 0.5)

            if len(peaks) > 1:
                # 计算平均心率
                intervals = np.diff(peaks) / self.fs  # 转换为秒
                avg_interval = np.median(intervals)
                return 60 / avg_interval
        except:
            pass
        return 75.0

    def _time_frequency_estimation_eemd(self, signal_sample):
        """时频域心率估计"""
        try:
            # 使用短时傅里叶变换
            from scipy.signal import stft
            f, t, Zxx = stft(signal_sample, fs=self.fs, nperseg=64, noverlap=32)

            # 在心率频率范围内寻找最强的频率分量
            freq_mask = (f >= 0.8) & (f <= 2.5)
            if np.any(freq_mask):
                hr_freqs = f[freq_mask]
                hr_stft = np.abs(Zxx[freq_mask, :])

                # 计算每个频率的平均能量
                avg_energy = np.mean(hr_stft, axis=1)
                peak_freq = hr_freqs[np.argmax(avg_energy)]
                return peak_freq * 60
        except:
            pass
        return 75.0

    def _physiological_validation_eemd(self, hr_estimate, original_signal):
        """生理约束验证"""
        # 1. 基本范围检查
        if hr_estimate < 45 or hr_estimate > 150:
            # 如果超出范围，尝试重新估计
            hr_estimate = self._fallback_estimation_eemd(original_signal)

        # 2. 信号质量检查
        signal_quality = self._assess_signal_quality_eemd(original_signal)
        if signal_quality < 0.3:  # 信号质量差
            # 降低置信度，向默认值回归
            hr_estimate = 0.7 * hr_estimate + 0.3 * 75.0

        return np.clip(hr_estimate, 45, 150)

    def _fallback_estimation_eemd(self, signal_sample):
        """备用心率估计方法"""
        try:
            # 使用简单的自相关方法
            autocorr = np.correlate(signal_sample, signal_sample, mode='full')
            autocorr = autocorr[len(autocorr)//2:]

            # 寻找第一个显著的峰值
            min_lag = int(self.fs * 0.4)  # 对应150 BPM
            max_lag = int(self.fs * 1.3)  # 对应45 BPM

            if max_lag < len(autocorr):
                search_range = autocorr[min_lag:max_lag]
                if len(search_range) > 0:
                    peak_lag = min_lag + np.argmax(search_range)
                    return 60 * self.fs / peak_lag
        except:
            pass
        return 75.0

    def _assess_signal_quality_eemd(self, signal_sample):
        """评估信号质量"""
        try:
            # 频谱集中度
            freqs, psd = welch(signal_sample, fs=self.fs)
            hr_mask = (freqs >= 0.8) & (freqs <= 2.5)

            if np.any(hr_mask):
                hr_power = np.sum(psd[hr_mask])
                total_power = np.sum(psd)
                spectral_concentration = hr_power / (total_power + 1e-10)
            else:
                spectral_concentration = 0.0

            # 综合质量评分
            quality_score = min(1.0, spectral_concentration * 2)
            return quality_score
        except:
            return 0.5  # 中等质量

    def swt_scale_peak_method(self, phase_signal):
        """
        方法4: 静态小波变换 + 尺度选择 + 峰值检测 (SWT-Scale-Peak)
        完整流程：相位提取 → 静态小波变换 → 心率相关尺度选择 → 重构信号 → 峰值检测 → 心率值

        参数:
            phase_signal: 相位信号，形状为 (N,) 或 (batch_size, N)

        返回:
            heart_rates: 心率估计值 (BPM)
        """
        if phase_signal.ndim == 1:
            phase_signal = phase_signal.reshape(1, -1)

        heart_rates = []

        for signal_sample in phase_signal:
            try:
                # 1. 去除直流分量
                signal_sample = signal_sample - np.mean(signal_sample)

                # 2. 静态小波变换 (SWT)
                wavelet = 'db4'  # Daubechies 4小波
                # 根据信号长度自动确定最大分解层数
                max_levels = pywt.swt_max_level(len(signal_sample))
                levels = min(4, max_levels)  # 使用较小的层数避免过度分解

                # 执行SWT分解
                coeffs = pywt.swt(signal_sample, wavelet, level=levels)

                # 3. 心率相关尺度选择
                # 计算每个尺度对应的频率范围
                selected_coeffs = []

                for level, (cA, cD) in enumerate(coeffs):
                    # 计算该层对应的频率范围
                    freq_max = self.fs / (2 ** (level + 1))
                    freq_min = self.fs / (2 ** (level + 2))

                    # 检查是否与心率频率范围重叠
                    if (freq_min <= self.hr_freq_range[1] and freq_max >= self.hr_freq_range[0]):
                        # 该尺度包含心率信息
                        selected_coeffs.append((cA, cD))

                # 4. 重构信号
                if len(selected_coeffs) > 0:
                    # 使用选中的系数重构信号
                    # 创建零填充的系数列表
                    reconstructed_coeffs = []

                    for level in range(levels):
                        if level < len(selected_coeffs):
                            reconstructed_coeffs.append(selected_coeffs[level])
                        else:
                            # 零填充未选中的尺度
                            cA_shape = coeffs[level][0].shape
                            cD_shape = coeffs[level][1].shape
                            reconstructed_coeffs.append((np.zeros(cA_shape), np.zeros(cD_shape)))

                    # 逆SWT变换
                    reconstructed_signal = pywt.iswt(reconstructed_coeffs, wavelet)

                    # 确保长度一致
                    if len(reconstructed_signal) > len(signal_sample):
                        reconstructed_signal = reconstructed_signal[:len(signal_sample)]
                    elif len(reconstructed_signal) < len(signal_sample):
                        reconstructed_signal = np.pad(reconstructed_signal,
                                                    (0, len(signal_sample) - len(reconstructed_signal)),
                                                    'constant')
                else:
                    # 如果没有合适的尺度，使用原信号
                    reconstructed_signal = signal_sample

                # 5. 对重构信号进行峰值检测
                # 带通滤波增强心率信号
                nyquist = self.fs / 2
                low_freq = self.hr_freq_range[0] / nyquist
                high_freq = self.hr_freq_range[1] / nyquist

                b, a = signal.butter(4, [low_freq, high_freq], btype='band')
                filtered_signal = signal.filtfilt(b, a, reconstructed_signal)

                # 时域峰值检测
                # 自适应阈值
                signal_std = np.std(filtered_signal)
                threshold = signal_std * 0.6

                peaks, _ = find_peaks(filtered_signal,
                                    height=threshold,
                                    distance=int(self.fs * 0.4))  # 最小间距0.4秒

                if len(peaks) > 1:
                    # 计算心率
                    intervals = np.diff(peaks) / self.fs
                    # 过滤异常间隔
                    valid_intervals = intervals[(intervals >= 0.5) & (intervals <= 1.25)]  # 48-120 BPM

                    if len(valid_intervals) > 0:
                        avg_interval = np.median(valid_intervals)
                        heart_rate = 60 / avg_interval
                        heart_rate = np.clip(heart_rate, 48, 120)
                    else:
                        heart_rate = 75.0
                else:
                    # 备选方案：频域分析
                    fft_result = fft(filtered_signal)
                    freqs = fftfreq(len(filtered_signal), 1/self.fs)
                    positive_freqs = freqs[:len(freqs)//2]
                    magnitude = np.abs(fft_result[:len(fft_result)//2])

                    freq_mask = (positive_freqs >= self.hr_freq_range[0]) & (positive_freqs <= self.hr_freq_range[1])
                    if np.any(freq_mask):
                        hr_freqs = positive_freqs[freq_mask]
                        hr_magnitudes = magnitude[freq_mask]
                        peak_freq = hr_freqs[np.argmax(hr_magnitudes)]
                        heart_rate = peak_freq * 60
                        heart_rate = np.clip(heart_rate, 48, 120)
                    else:
                        heart_rate = 75.0

            except Exception as e:
                print(f"SWT分解失败: {e}")
                heart_rate = 75.0  # 默认心率

            heart_rates.append(heart_rate)

        return np.array(heart_rates)

    # ========== 2.3 Deep Learning Methods ==========
    


    def create_lstm_hr_model(self, input_shape=(300, 7)):
        """
        方法5: LSTM网络 (LSTM-HR)
        完整流程：特征提取 → 滑动窗口 → LSTM网络 → 全连接层 → 心率值
        """
        model = tf.keras.Sequential([
            tf.keras.layers.LSTM(128, return_sequences=True, input_shape=input_shape),
            tf.keras.layers.Dropout(0.3),
            tf.keras.layers.LSTM(64, return_sequences=True),
            tf.keras.layers.Dropout(0.3),
            tf.keras.layers.LSTM(32, return_sequences=False),
            tf.keras.layers.Dropout(0.2),
            tf.keras.layers.Dense(64, activation='relu'),
            tf.keras.layers.Dense(32, activation='relu'),
            tf.keras.layers.Dense(1)
        ])

        model.compile(
            optimizer=tf.keras.optimizers.Adam(learning_rate=0.001),
            loss=tf.keras.losses.Huber(delta=1.0),
            metrics=['mae']
        )

        return model

    def create_1d_cnn_hr_model(self, input_shape=(300, 7)):
        """
        方法6: 1D卷积神经网络 (1D-CNN-HR)
        完整流程：特征提取 → 滑动窗口 → 1D卷积层 → 池化层 → 全连接层 → 心率值
        """
        model = tf.keras.Sequential([
            # 第一层卷积：提取局部特征
            tf.keras.layers.Conv1D(64, kernel_size=5, activation='relu', input_shape=input_shape),
            tf.keras.layers.BatchNormalization(),
            tf.keras.layers.MaxPooling1D(pool_size=2),
            tf.keras.layers.Dropout(0.2),

            # 第二层卷积：提取更复杂特征
            tf.keras.layers.Conv1D(128, kernel_size=3, activation='relu'),
            tf.keras.layers.BatchNormalization(),
            tf.keras.layers.MaxPooling1D(pool_size=2),
            tf.keras.layers.Dropout(0.2),

            # 第三层卷积：高级特征提取
            tf.keras.layers.Conv1D(64, kernel_size=3, activation='relu'),
            tf.keras.layers.BatchNormalization(),
            tf.keras.layers.MaxPooling1D(pool_size=2),
            tf.keras.layers.Dropout(0.2),

            # 全局平均池化
            tf.keras.layers.GlobalAveragePooling1D(),

            # 全连接层
            tf.keras.layers.Dense(128, activation='relu'),
            tf.keras.layers.Dropout(0.3),
            tf.keras.layers.Dense(64, activation='relu'),
            tf.keras.layers.Dropout(0.2),
            tf.keras.layers.Dense(1)
        ])

        model.compile(
            optimizer=tf.keras.optimizers.Adam(learning_rate=0.001),
            loss=tf.keras.losses.Huber(delta=1.0),
            metrics=['mae']
        )

        return model

    def _simple_decomposition(self, signal_input):
        """
        简单的滤波器组分解，作为EEMD的替代方案

        参数:
            signal_input: 输入信号

        返回:
            imfs: 类似IMF的分解结果
        """
        # 创建不同频段的滤波器
        imfs = []

        try:
            # 高频分量 (2-8 Hz)
            sos_high = signal.butter(4, [2, 8], btype='band', fs=self.fs, output='sos')
            imf_high = signal.sosfilt(sos_high, signal_input)
            imfs.append(imf_high)

            # 心率频段 (0.8-2.5 Hz)
            sos_hr = signal.butter(4, [0.8, 2.5], btype='band', fs=self.fs, output='sos')
            imf_hr = signal.sosfilt(sos_hr, signal_input)
            imfs.append(imf_hr)

            # 低频分量 (0.1-0.8 Hz)
            sos_low = signal.butter(4, [0.1, 0.8], btype='band', fs=self.fs, output='sos')
            imf_low = signal.sosfilt(sos_low, signal_input)
            imfs.append(imf_low)

            # 极低频分量 (0.01-0.1 Hz)
            sos_vlow = signal.butter(4, [0.01, 0.1], btype='band', fs=self.fs, output='sos')
            imf_vlow = signal.sosfilt(sos_vlow, signal_input)
            imfs.append(imf_vlow)

        except Exception as e:
            print(f"滤波器组分解失败: {e}")
            # 如果滤波器组也失败，返回原信号的简单分解
            imfs = [signal_input, signal_input * 0.5, signal_input * 0.25, signal_input * 0.1]

        return np.array(imfs)

    def _improved_decomposition(self, signal_input):
        """
        改进的信号分解方法
        使用多尺度滤波器组和自适应频段选择
        """
        imfs = []

        # 自适应频段选择：基于信号的频谱特征
        fft_signal = np.fft.fft(signal_input)
        freqs = np.fft.fftfreq(len(signal_input), 1/self.fs)
        psd = np.abs(fft_signal)**2

        # 找到主要能量集中的频段
        positive_freqs = freqs[:len(freqs)//2]
        positive_psd = psd[:len(psd)//2]

        # 计算累积能量分布
        cumulative_energy = np.cumsum(positive_psd)
        total_energy = cumulative_energy[-1]

        # 定义自适应频段
        freq_bands = []
        energy_thresholds = [0.1, 0.3, 0.6, 0.8, 0.95]  # 能量累积阈值

        prev_freq = 0.1
        for threshold in energy_thresholds:
            target_energy = threshold * total_energy
            idx = np.searchsorted(cumulative_energy, target_energy)
            if idx < len(positive_freqs):
                next_freq = min(positive_freqs[idx], 8.0)  # 限制最高频率
                if next_freq > prev_freq:
                    freq_bands.append((prev_freq, next_freq))
                    prev_freq = next_freq

        # 如果自适应频段太少，使用默认频段
        if len(freq_bands) < 3:
            freq_bands = [
                (0.1, 0.8),   # 低频分量
                (0.8, 2.5),   # 心率主频段
                (2.5, 6.0),   # 高频分量
                (6.0, 12.0)   # 噪声分量
            ]

        try:
            for low, high in freq_bands:
                # 确保频率范围有效
                if high > self.fs / 2:
                    high = self.fs / 2 - 0.1
                if low >= high:
                    continue

                # 设计更高阶的滤波器以获得更好的频率选择性
                sos = signal.butter(6, [low, high], btype='band', fs=self.fs, output='sos')
                filtered = signal.sosfilt(sos, signal_input)

                # 只保留有意义的IMF（能量足够大）
                if np.var(filtered) > 0.01 * np.var(signal_input):
                    imfs.append(filtered)

        except Exception as e:
            print(f"改进分解失败: {e}")
            return self._simple_decomposition(signal_input)

        # 确保至少有一些IMF
        if len(imfs) == 0:
            return self._simple_decomposition(signal_input)

        return np.array(imfs)

class ThreeClassMethodsEvaluator:
    """三类方法评估器"""

    def __init__(self, fs=30.0):
        self.methods = ThreeClassMethods(fs)
        self.fs = fs
        
    def evaluate_spectrum_methods(self, phase_signals, true_hr, use_long_term_optimization=False):
        """
        评估频谱分析方法 (2种)

        参数:
            phase_signals: 相位信号数组，形状为 (batch_size, signal_length)
            true_hr: 真实心率值，形状为 (batch_size,)
            use_long_term_optimization: 是否使用长时监测优化

        返回:
            results: 包含方法结果的字典
        """
        results = {}

        # 方法1: FFT + 带通滤波 + 峰值检测
        print("   评估 FFT-BPF-Peak 方法...")
        if use_long_term_optimization:
            fft_predictions = self.methods.fft_bpf_peak_method_long_term(phase_signals)
        else:
            fft_predictions = self.methods.fft_bpf_peak_method(phase_signals)
        results['FFT-BPF-Peak'] = {
            'predictions': fft_predictions,
            'mae': np.mean(np.abs(true_hr - fft_predictions)),
            'mse': np.mean((true_hr - fft_predictions)**2),
            'mre': np.mean(np.abs(true_hr - fft_predictions) / true_hr) * 100,
            'prediction_accuracy': np.sum(np.abs(true_hr - fft_predictions) <= 3) / len(true_hr) * 100
        }

        # 方法2: 差分增强 + 频谱分析
        print("   评估 DE-Spectrum 方法...")
        de_predictions = self.methods.de_spectrum_method(phase_signals)
        results['DE-Spectrum'] = {
            'predictions': de_predictions,
            'mae': np.mean(np.abs(true_hr - de_predictions)),
            'mse': np.mean((true_hr - de_predictions)**2),
            'mre': np.mean(np.abs(true_hr - de_predictions) / true_hr) * 100,
            'prediction_accuracy': np.sum(np.abs(true_hr - de_predictions) <= 3) / len(true_hr) * 100
        }

        # 方法3: 低心率优化FFT方法
        print("   评估 Low-HR-Optimized-FFT 方法...")
        low_hr_predictions = self.methods.low_hr_optimized_fft_method(phase_signals)
        results['Low-HR-Optimized-FFT'] = {
            'predictions': low_hr_predictions,
            'mae': np.mean(np.abs(true_hr - low_hr_predictions)),
            'mse': np.mean((true_hr - low_hr_predictions)**2),
            'mre': np.mean(np.abs(true_hr - low_hr_predictions) / true_hr) * 100,
            'prediction_accuracy': np.sum(np.abs(true_hr - low_hr_predictions) <= 3) / len(true_hr) * 100
        }

        # 方法4: Welch优化方法
        print("   评估 Welch-Optimized 方法...")
        welch_predictions = self.methods.welch_optimized_method(phase_signals)
        results['Welch-Optimized'] = {
            'predictions': welch_predictions,
            'mae': np.mean(np.abs(true_hr - welch_predictions)),
            'mse': np.mean((true_hr - welch_predictions)**2),
            'mre': np.mean(np.abs(true_hr - welch_predictions) / true_hr) * 100,
            'prediction_accuracy': np.sum(np.abs(true_hr - welch_predictions) <= 3) / len(true_hr) * 100
        }

        return results

    def evaluate_decomposition_methods(self, phase_signals, true_hr, use_long_term_optimization=False):
        """
        评估非平稳分解方法 (2种)

        参数:
            phase_signals: 相位信号数组，形状为 (batch_size, signal_length)
            true_hr: 真实心率值，形状为 (batch_size,)
            use_long_term_optimization: 是否使用长时监测优化

        返回:
            results: 包含方法结果的字典
        """
        results = {}

        # 方法3: EEMD + 相关性选择 + 峰值检测
        print("   评估 EEMD-Corr-Peak 方法...")
        if use_long_term_optimization:
            eemd_predictions = self.methods.eemd_corr_peak_method_long_term(phase_signals)
        else:
            eemd_predictions = self.methods.eemd_corr_peak_method(phase_signals)
        results['EEMD-Corr-Peak'] = {
            'predictions': eemd_predictions,
            'mae': np.mean(np.abs(true_hr - eemd_predictions)),
            'mse': np.mean((true_hr - eemd_predictions)**2),
            'mre': np.mean(np.abs(true_hr - eemd_predictions) / true_hr) * 100,
            'prediction_accuracy': np.sum(np.abs(true_hr - eemd_predictions) <= 3) / len(true_hr) * 100
        }

        # 方法4: 静态小波变换 + 尺度选择 + 峰值检测
        print("   评估 SWT-Scale-Peak 方法...")
        swt_predictions = self.methods.swt_scale_peak_method(phase_signals)
        results['SWT-Scale-Peak'] = {
            'predictions': swt_predictions,
            'mae': np.mean(np.abs(true_hr - swt_predictions)),
            'mse': np.mean((true_hr - swt_predictions)**2),
            'mre': np.mean(np.abs(true_hr - swt_predictions) / true_hr) * 100,
            'prediction_accuracy': np.sum(np.abs(true_hr - swt_predictions) <= 3) / len(true_hr) * 100
        }

        return results

    def evaluate_all_traditional_methods(self, phase_signals, true_hr):
        """
        评估所有传统方法（频谱分析 + 非平稳分解）

        参数:
            phase_signals: 相位信号数组，形状为 (batch_size, signal_length)
            true_hr: 真实心率值，形状为 (batch_size,)

        返回:
            results: 包含所有传统方法结果的字典
        """
        results = {}

        # 评估频谱分析方法
        spectrum_results = self.evaluate_spectrum_methods(phase_signals, true_hr)
        results.update(spectrum_results)

        # 评估非平稳分解方法
        decomposition_results = self.evaluate_decomposition_methods(phase_signals, true_hr)
        results.update(decomposition_results)

        return results

def test_three_class_methods():
    """测试三类方法"""
    print("🧪 测试三类心率检测方法...")
    print("   2.1 频谱分析方法: FFT-BPF-Peak, DE-Spectrum")
    print("   2.2 非平稳分解方法: EEMD-Corr-Peak, SWT-Scale-Peak")
    print("   2.3 深度学习方法: LSTM-HR, 1D-CNN-HR")

    # 生成测试信号
    fs = 30.0
    t = np.linspace(0, 10, int(10 * fs))

    # 模拟心率信号 (75 BPM = 1.25 Hz)
    hr_freq = 1.25
    heart_signal = np.sin(2 * np.pi * hr_freq * t)

    # 添加呼吸干扰 (15 BPM = 0.25 Hz)
    resp_freq = 0.25
    resp_signal = 0.3 * np.sin(2 * np.pi * resp_freq * t)

    # 添加随机噪声
    noise = np.random.normal(0, 0.1, len(heart_signal))

    # 合成复合信号
    composite_signal = heart_signal + resp_signal + noise

    # 测试传统方法
    evaluator = ThreeClassMethodsEvaluator(fs)

    # 单个信号测试
    test_signals = composite_signal.reshape(1, -1)
    true_hr = np.array([75.0])

    # 测试传统方法
    traditional_results = evaluator.evaluate_all_traditional_methods(test_signals, true_hr)

    print("\n📊 传统方法测试结果:")
    print(f"   真实心率: {true_hr[0]:.1f} BPM")
    print("   " + "-" * 50)

    # 按类别显示结果
    spectrum_methods = ['FFT-BPF-Peak', 'DE-Spectrum']
    decomposition_methods = ['EEMD-Corr-Peak', 'SWT-Scale-Peak']

    print("   📈 频谱分析方法:")
    for method_name in spectrum_methods:
        if method_name in traditional_results:
            method_results = traditional_results[method_name]
            error = abs(method_results['predictions'][0] - true_hr[0])
            print(f"      {method_name}:")
            print(f"         预测心率: {method_results['predictions'][0]:.1f} BPM")
            print(f"         绝对误差: {error:.1f} BPM")
            print(f"         MAE: {method_results['mae']:.2f} BPM")

    print("\n   🌊 非平稳分解方法:")
    for method_name in decomposition_methods:
        if method_name in traditional_results:
            method_results = traditional_results[method_name]
            error = abs(method_results['predictions'][0] - true_hr[0])
            print(f"      {method_name}:")
            print(f"         预测心率: {method_results['predictions'][0]:.1f} BPM")
            print(f"         绝对误差: {error:.1f} BPM")
            print(f"         MAE: {method_results['mae']:.2f} BPM")

    print("\n   🧠 深度学习方法:")
    print("      (需要训练数据，此处仅创建模型结构)")

    # 创建深度学习模型
    lstm_model = evaluator.methods.create_lstm_hr_model()
    cnn_model = evaluator.methods.create_1d_cnn_hr_model()

    print(f"      LSTM-HR模型参数量: {lstm_model.count_params():,}")
    print(f"      1D-CNN-HR模型参数量: {cnn_model.count_params():,}")

    return traditional_results

if __name__ == "__main__":
    test_three_class_methods()
