import os
import sys
import numpy as np
import time

# 添加当前目录到路径
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)


from radar_func import range_fft, mti_filter, extract_phase
from signal_decomposition import apply_cwt, apply_eemd

# 雷达参数（与实时系统一致）
FRAME_RATE = 30
RANGE_RESOLUTION = 0.027  # 米
WAVELENGTH = 0.00494      # 米
WINDOW_TYPE = 'hann'
FFT_SIZE = 512

# 处理参数
WINDOW_SIZE_SECONDS = 1
STEP_SIZE_SECONDS = 1
WINDOW_SIZE = int(WINDOW_SIZE_SECONDS * FRAME_RATE)   # 300
STEP_SIZE = int(STEP_SIZE_SECONDS * FRAME_RATE)       # 30

# 信号分解设置
DECOMPOSE_SIGNAL = True  # ⚠️ 现在必须为 True 才会生成数据
DECOMP_TYPE = "cwt"      # or "eemd"
CWT_SCALES = np.arange(1, 65)
CWT_WAVELET = 'morl'
EEMD_NOISE_WIDTH = 0.05
EEMD_ENSEMBLE_SIZE = 50
EEMD_MAX_IMF = 5

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
    # === 1. 读取大 .npy 文件 ===(216000, 3, 16, 512)
    file_path = r'D:\STUDY\BGT60TR13C_Dataset\Radar_Data\Long_duration\radar_raw_data.npy'
    print(f"正在加载 {file_path} ...")
    radar_data = np.load(file_path, mmap_mode='r')  # shape: (216000, 3, 16, 512)
    total_frames = radar_data.shape[0]
    print(f"数据加载完成，总帧数: {total_frames}, shape: {radar_data.shape}")

    model_inputs = []  # 用于收集所有 model_input

    # === 2. 滑动窗口处理（无存在检测）===
    start_idx = 0
    window_id = 0

    while start_idx + WINDOW_SIZE <= total_frames:
        print(f"\n>>> 处理窗口 {window_id}: 帧 [{start_idx}, {start_idx + WINDOW_SIZE})")
        window_data = radar_data[start_idx:start_idx + WINDOW_SIZE]  # (300, 3, 16, 512)

        # Step 1: Range FFT
        range_profile = range_fft(window_data, window=WINDOW_TYPE)

        # Step 2: MTI 滤波
        mti_filtered = mti_filter(range_profile)

        # Step 3: 提取相位（固定使用天线0、通道0）
        data_2d = mti_filtered[:, 0, 0, :]  # (300, 512)
        phase_values, target_bin = extract_phase(data_2d, RANGE_RESOLUTION, WAVELENGTH)

        # ✅ 直接处理：只要 DECOMPOSE_SIGNAL 为 True 就分解
        if DECOMPOSE_SIGNAL:
            try:
                if DECOMP_TYPE == "cwt":
                    cwt_coeffs, _ = apply_cwt(
                        phase_values,
                        scales=CWT_SCALES,
                        wavelet=CWT_WAVELET,
                        sampling_period=1.0 / FRAME_RATE
                    )
                    model_input = prepare_model_input(cwt_coeffs, "cwt")  # (1, T, scales)

                elif DECOMP_TYPE == "eemd":
                    imfs = apply_eemd(
                        phase_values,
                        noise_width=EEMD_NOISE_WIDTH,
                        ensemble_size=EEMD_ENSEMBLE_SIZE,
                        max_imf=EEMD_MAX_IMF
                    )
                    model_input = prepare_model_input(imfs, "eemd")  # (1, T, imfs)

                else:
                    model_input = None

                if model_input is not None:
                    model_inputs.append(model_input)
                    print(f"  -> ✅ 保存 model_input，shape: {model_input.shape}")
                else:
                    print("  -> ⚠️ 未生成有效 model_input")

            except Exception as e:
                print(f"  -> ❌ 处理出错: {e}")
                continue

        else:
            print("  -> ⚠️ 跳过：信号分解未启用")

        start_idx += STEP_SIZE
        window_id += 1

    # === 3. 保存结果 ===
    if model_inputs:
        X = np.concatenate(model_inputs, axis=0)  # (N, T, F)
        print(f"\n📊 最终数据集形状: {X.shape}")
        print(f"   示例 X[0] 的前5个时间步前3个特征:\n{X[0, :5, :3]}")

        np.save("train_model/data.npy", X)
        print(f"\n💾 预处理数据已保存至: data.npy")
    else:
        print("\n❌ 未收集到任何有效的 model_input 数据！")

if __name__ == "__main__":
    main()