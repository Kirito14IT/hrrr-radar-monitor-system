import os
import sys
import numpy as np
import time
from scipy.signal import butter, filtfilt

# 添加当前目录到路径
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

from radar_func import range_fft, mti_filter, extract_phase
from signal_decomposition import apply_cwt, apply_eemd

# 雷达参数
FRAME_RATE = 30  # Hz
RANGE_RESOLUTION = 0.027
WAVELENGTH = 0.00494
WINDOW_TYPE = 'hann'
FFT_SIZE = 512

# 处理参数
WINDOW_SIZE_SECONDS = 1
STEP_SIZE_SECONDS = 1
WINDOW_SIZE = int(WINDOW_SIZE_SECONDS * FRAME_RATE)   # 30
STEP_SIZE = int(STEP_SIZE_SECONDS * FRAME_RATE)       # 30

# 信号分解设置
DECOMPOSE_SIGNAL = True
DECOMP_TYPE = "cwt"  # or "eemd"
CWT_SCALES = np.arange(1, 65)
CWT_WAVELET = 'morl'
EEMD_NOISE_WIDTH = 0.05
EEMD_ENSEMBLE_SIZE = 50
EEMD_MAX_IMF = 5

# === 新增：生理信号频段定义（Hz）===
HR_BAND = [0.8, 4.0]      # 心跳：48–240 bpm
RR_BAND = [0.1, 0.5]      # 呼吸：6–30 rpm

def butter_bandpass(lowcut, highcut, fs, order=4):
    nyq = 0.5 * fs
    low = lowcut / nyq
    high = highcut / nyq
    b, a = butter(order, [low, high], btype='band')
    return b, a

def bandpass_filter(data, lowcut, highcut, fs, order=4):
    b, a = butter_bandpass(lowcut, highcut, fs, order=order)
    y = filtfilt(b, a, data, axis=0)  # 零相位滤波
    return y

def prepare_model_input(data, data_type):
    if data_type == "cwt":
        model_input = np.transpose(data)  # (scales, T) -> (T, scales)
        return np.expand_dims(model_input, axis=0)  # (1, T, scales)
    elif data_type == "eemd":
        model_input = np.transpose(data)  # (imfs, T) -> (T, imfs)
        return np.expand_dims(model_input, axis=0)
    else:
        raise ValueError("Unknown data type")


def main():
    radar_root = r'D:\STUDY\BGT60TR13C_Dataset\Radar_Data'
    hr_ref_root = r'D:\STUDY\BGT60TR13C_Dataset\HR_Ref_Data'

    all_model_inputs_hr = []
    all_model_inputs_rr = []

    # 遍历 Radar_Data 下所有 .npy 文件
    for root, dirs, files in os.walk(radar_root):
        for file in files:
            if file == 'radar_raw_data.npy':
                radar_file_path = os.path.join(root, file)

                # 构造对应的 HR_ref.csv 路径
                rel_path = os.path.relpath(root, radar_root)  # e.g., "Participant1\\0.3m"
                hr_ref_file = os.path.join(hr_ref_root, rel_path, 'HR_ref.csv')

                if not os.path.exists(hr_ref_file):
                    print(f"⚠️ 警告：找不到对应标签文件 {hr_ref_file}，跳过 {radar_file_path}")
                    continue

                print(f"\n{'=' * 60}")
                print(f"正在处理: {radar_file_path}")
                print(f"对应标签: {hr_ref_file}")

                # 加载雷达数据
                try:
                    radar_data = np.load(radar_file_path, mmap_mode='r')  # shape: (N, 3, 16, 512)
                except Exception as e:
                    print(f"❌ 加载雷达数据失败: {e}")
                    continue

                total_frames = radar_data.shape[0]
                print(f"  -> 数据加载完成，总帧数: {total_frames}, shape: {radar_data.shape}")

                model_inputs_hr = []
                model_inputs_rr = []

                start_idx = 0
                window_id = 0

                while start_idx + WINDOW_SIZE <= total_frames:
                    # 1. 读取原始窗口数据（保持原始类型，假设是实数）
                    window_data = radar_data[start_idx:start_idx + WINDOW_SIZE]  # (30, 3, 16, 512)

                    # 2. 提取单通道：antenna=0, chirp=0 → (30, 512)
                    single_ch_2d = window_data[:, 0, 0, :]  # 注意：这里用索引，不是切片，得到 (T, R)

                    # 3. 【关键修改】将实数单通道转为复数（虚部=0）
                    if not np.iscomplexobj(single_ch_2d):
                        single_ch_2d = single_ch_2d.astype(np.float32) + 0j  # 转为 complex64

                    # 4. 重塑为 4D 格式 (T, 1, 1, R) 以兼容 range_fft 和 mti_filter
                    single_ch_4d = single_ch_2d[:, np.newaxis, np.newaxis, :]  # (30, 1, 1, 512)

                    # 5. Range FFT
                    range_profile_4d = range_fft(single_ch_4d, window=WINDOW_TYPE)  # (30, 1, 1, 512)

                    # 6. MTI 滤波
                    mti_filtered_4d = mti_filter(range_profile_4d)  # (30, 1, 1, 512)

                    # 7. 转为 2D 供相位提取: (T, R)
                    data_2d = mti_filtered_4d[:, 0, 0, :]  # (30, 512)

                    # 8. 提取相位信号
                    phase_values, target_bin = extract_phase(data_2d, RANGE_RESOLUTION, WAVELENGTH)

                    if DECOMPOSE_SIGNAL:
                        try:
                            # 带通滤波分离 HR 和 RR
                            phase_hr = bandpass_filter(phase_values, HR_BAND[0], HR_BAND[1], fs=FRAME_RATE)
                            phase_rr = bandpass_filter(phase_values, RR_BAND[0], RR_BAND[1], fs=FRAME_RATE)

                            # --- 处理 HR 信号 ---
                            if DECOMP_TYPE == "cwt":
                                cwt_hr, _ = apply_cwt(
                                    phase_hr,
                                    scales=CWT_SCALES,
                                    wavelet=CWT_WAVELET,
                                    sampling_period=1.0 / FRAME_RATE
                                )
                                model_input_hr = prepare_model_input(cwt_hr, "cwt")
                            elif DECOMP_TYPE == "eemd":
                                imfs_hr = apply_eemd(
                                    phase_hr,
                                    noise_width=EEMD_NOISE_WIDTH,
                                    ensemble_size=EEMD_ENSEMBLE_SIZE,
                                    max_imf=EEMD_MAX_IMF
                                )
                                model_input_hr = prepare_model_input(imfs_hr, "eemd")
                            else:
                                model_input_hr = None

                            # --- 处理 RR 信号 ---
                            if DECOMP_TYPE == "cwt":
                                cwt_rr, _ = apply_cwt(
                                    phase_rr,
                                    scales=CWT_SCALES,
                                    wavelet=CWT_WAVELET,
                                    sampling_period=1.0 / FRAME_RATE
                                )
                                model_input_rr = prepare_model_input(cwt_rr, "cwt")
                            elif DECOMP_TYPE == "eemd":
                                imfs_rr = apply_eemd(
                                    phase_rr,
                                    noise_width=EEMD_NOISE_WIDTH,
                                    ensemble_size=EEMD_ENSEMBLE_SIZE,
                                    max_imf=EEMD_MAX_IMF
                                )
                                model_input_rr = prepare_model_input(imfs_rr, "eemd")
                            else:
                                model_input_rr = None

                            if model_input_hr is not None:
                                model_inputs_hr.append(model_input_hr)
                            if model_input_rr is not None:
                                model_inputs_rr.append(model_input_rr)

                        except Exception as e:
                            print(f"  -> ❌ 窗口 {window_id} 处理出错: {e}")
                            import traceback
                            traceback.print_exc()
                            continue

                    start_idx += STEP_SIZE
                    window_id += 1

                # 累积到全局列表
                if model_inputs_hr:
                    all_model_inputs_hr.extend(model_inputs_hr)
                if model_inputs_rr:
                    all_model_inputs_rr.extend(model_inputs_rr)

                print(f"  -> 本文件生成 HR 窗口数: {len(model_inputs_hr)}, RR 窗口数: {len(model_inputs_rr)}")

    # === 保存最终合并的数据集 ===
    output_dir = "train_model"
    os.makedirs(output_dir, exist_ok=True)

    if all_model_inputs_hr:
        X_hr = np.concatenate(all_model_inputs_hr, axis=0)
        print(f"\n📊 合并后 HR 数据集形状: {X_hr.shape}")
        np.save(os.path.join(output_dir, "data_hr.npy"), X_hr)
        print(f"💾 HR 数据已保存至: {output_dir}/data_hr.npy")
    else:
        print("\n❌ 未生成任何 HR 数据！")

    if all_model_inputs_rr:
        X_rr = np.concatenate(all_model_inputs_rr, axis=0)
        print(f"\n📊 合并后 RR 数据集形状: {X_rr.shape}")
        np.save(os.path.join(output_dir, "data_rr.npy"), X_rr)
        print(f"💾 RR 数据已保存至: {output_dir}/data_rr.npy")
    else:
        print("\n❌ 未生成任何 RR 数据！")

if __name__ == "__main__":
    main()