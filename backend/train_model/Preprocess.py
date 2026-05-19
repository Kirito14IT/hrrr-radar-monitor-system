import os
import sys
import numpy as np
import time
from scipy.signal import butter, filtfilt

# 添加当前目录到路径
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

# 假设 radar_func.py 中包含 range_fft 和 mti_filter
from radar_func import range_fft, mti_filter, extract_phase
from signal_decomposition import apply_cwt, apply_eemd

# ======================
# 配置参数
# ======================

# 雷达参数
FRAME_RATE = 30  # Hz
RANGE_RESOLUTION = 0.027  # 米
WAVELENGTH = 0.00494  # 米
WINDOW_TYPE = 'hann'
FFT_SIZE = 512

# 处理窗口（1秒）
WINDOW_SIZE_SECONDS = 1
STEP_SIZE_SECONDS = 1
WINDOW_SIZE = int(WINDOW_SIZE_SECONDS * FRAME_RATE)  # 30
STEP_SIZE = int(STEP_SIZE_SECONDS * FRAME_RATE)  # 30

# 信号分解设置
DECOMPOSE_SIGNAL = True
DECOMP_TYPE = "cwt"  # 可选 "eemd"
CWT_SCALES = np.arange(1, 65)
CWT_WAVELET = 'morl'
EEMD_NOISE_WIDTH = 0.05
EEMD_ENSEMBLE_SIZE = 50
EEMD_MAX_IMF = 5

# 生理频段（Hz）
HR_BAND = [0.8, 4.0]  # 心跳：48–240 bpm
RR_BAND = [0.1, 0.5]  # 呼吸：6–30 rpm


# ======================
# 工具函数
# ======================

def butter_bandpass(lowcut, highcut, fs, order=4):
    nyq = 0.5 * fs
    low = lowcut / nyq
    high = highcut / nyq
    b, a = butter(order, [low, high], btype='band')
    return b, a


def bandpass_filter(data, lowcut, highcut, fs, order=4):
    b, a = butter_bandpass(lowcut, highcut, fs, order=order)
    y = filtfilt(b, a, data, axis=0)
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


# ======================
# 主函数
# ======================

def main():
    file_path = r'D:\STUDY\BGT60TR13C_Dataset\Radar_Data\Long_duration\radar_raw_data.npy'
    print(f"正在加载 {file_path} ...")
    radar_data = np.load(file_path, mmap_mode='r')  # shape: (216000, 3, 16, 512)
    total_frames = radar_data.shape[0]
    print(f"数据加载完成，总帧数: {total_frames}")

    model_inputs_hr = []
    model_inputs_rr = []

    start_idx = 0
    window_id = 0

    while start_idx + WINDOW_SIZE <= total_frames:
        print(f"\n>>> 处理窗口 {window_id}: 帧 [{start_idx}, {start_idx + WINDOW_SIZE})")

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
        print(f"  -> 提取相位成功，target bin: {target_bin}, length: {len(phase_values)}")

        # ... 后续信号分解、保存等逻辑保持不变 ...

        if DECOMPOSE_SIGNAL:
            try:
                # 7. 带通滤波分离 HR 和 RR
                phase_hr = bandpass_filter(phase_values, HR_BAND[0], HR_BAND[1], fs=FRAME_RATE)
                phase_rr = bandpass_filter(phase_values, RR_BAND[0], RR_BAND[1], fs=FRAME_RATE)

                # --- HR 分解 ---
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

                # --- RR 分解 ---
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

                # 8. 收集有效输入
                if model_input_hr is not None:
                    model_inputs_hr.append(model_input_hr)
                if model_input_rr is not None:
                    model_inputs_rr.append(model_input_rr)

                print(f"  -> ✅ HR input shape: {model_input_hr.shape if model_input_hr is not None else 'None'}")
                print(f"  -> ✅ RR input shape: {model_input_rr.shape if model_input_rr is not None else 'None'}")

            except Exception as e:
                print(f"  -> ❌ 处理出错: {e}")
                import traceback
                traceback.print_exc()
                continue

        start_idx += STEP_SIZE
        window_id += 1

    # ======================
    # 保存结果
    # ======================
    output_dir = "train_model"
    os.makedirs(output_dir, exist_ok=True)

    if model_inputs_hr:
        X_hr = np.concatenate(model_inputs_hr, axis=0)  # (N, T, F)
        np.save(os.path.join(output_dir, "data_hr.npy"), X_hr)
        print(f"\n✅ HR 数据已保存: shape={X_hr.shape} → {output_dir}/data_hr.npy")
    else:
        print("\n❌ 未生成任何 HR 数据！")

    if model_inputs_rr:
        X_rr = np.concatenate(model_inputs_rr, axis=0)
        np.save(os.path.join(output_dir, "data_rr.npy"), X_rr)
        print(f"\n✅ RR 数据已保存: shape={X_rr.shape} → {output_dir}/data_rr.npy")
    else:
        print("\n❌ 未生成任何 RR 数据！")


if __name__ == "__main__":
    main()