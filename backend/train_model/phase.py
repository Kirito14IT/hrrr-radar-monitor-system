import os
import sys
import numpy as np
from radar_func import range_fft, mti_filter, extract_phase

# 雷达参数
FRAME_RATE = 30  # Hz
RANGE_RESOLUTION = 0.027
WAVELENGTH = 0.00494
WINDOW_TYPE = 'hann'

# 处理参数（1秒窗口，无重叠）
WINDOW_SIZE_SECONDS = 10
STEP_SIZE_SECONDS = 1
WINDOW_SIZE = int(WINDOW_SIZE_SECONDS * FRAME_RATE)   # 300
STEP_SIZE = int(STEP_SIZE_SECONDS * FRAME_RATE)       # 30

def main():
    radar_root = r'D:\STUDY\BGT60TR13C_Dataset\Radar_Data'
    hr_ref_root = r'D:\STUDY\BGT60TR13C_Dataset\HR_Ref_Data'

    all_phase_signals = []  # 存储所有窗口的相位信号 (N, 30)

    # 遍历 Radar_Data 下所有 .npy 文件
    for root, dirs, files in os.walk(radar_root):
        for file in files:
            if file == 'radar_raw_data.npy':
                radar_file_path = os.path.join(root, file)

                # 构造对应的 HR_ref.csv 路径
                rel_path = os.path.relpath(root, radar_root)
                hr_ref_file = os.path.join(hr_ref_root, rel_path, 'HR_ref.csv')

                if not os.path.exists(hr_ref_file):
                    print(f"⚠️ 警告：找不到对应标签文件 {hr_ref_file}，跳过 {radar_file_path}")
                    continue

                print(f"\n{'=' * 60}")
                print(f"正在处理: {radar_file_path}")

                try:
                    radar_data = np.load(radar_file_path, mmap_mode='r')  # (N, 3, 16, 512)
                except Exception as e:
                    print(f"❌ 加载雷达数据失败: {e}")
                    continue

                total_frames = radar_data.shape[0]
                print(f"  -> 总帧数: {total_frames}")

                start_idx = 0
                window_count = 0

                while start_idx + WINDOW_SIZE <= total_frames:
                    # 1. 提取窗口数据
                    window_data = radar_data[start_idx:start_idx + WINDOW_SIZE]  # (30, 3, 16, 512)

                    # 2. 取单通道 (antenna=0, chirp=0) → (30, 512)
                    single_ch_2d = window_data[:, 0, 0, :]

                    # 3. 转为复数（若为实数）
                    if not np.iscomplexobj(single_ch_2d):
                        single_ch_2d = single_ch_2d.astype(np.float32) + 0j

                    # 4. 重塑为 4D 以兼容后续函数
                    single_ch_4d = single_ch_2d[:, np.newaxis, np.newaxis, :]  # (30, 1, 1, 512)

                    # 5. Range FFT
                    range_profile_4d = range_fft(single_ch_4d, window=WINDOW_TYPE)

                    # 6. MTI 滤波
                    mti_filtered_4d = mti_filter(range_profile_4d)

                    # 7. 转回 2D (T, R)
                    data_2d = mti_filtered_4d[:, 0, 0, :]  # (30, 512)

                    # 8. 提取相位信号
                    phase_values, target_bin = extract_phase(data_2d, RANGE_RESOLUTION, WAVELENGTH)

                    # 9. 保存相位信号（长度应为 30）
                    if len(phase_values) == WINDOW_SIZE:
                        all_phase_signals.append(phase_values.copy())
                        window_count += 1
                    else:
                        print(f"  -> ⚠️ 窗口 {window_count} 相位长度异常: {len(phase_values)}")

                    start_idx += STEP_SIZE

                print(f"  -> 本文件生成相位窗口数: {window_count}")

    # === 保存相位信号 ===
    output_dir = "train_model"
    os.makedirs(output_dir, exist_ok=True)

    if all_phase_signals:
        phase_array = np.array(all_phase_signals)  # shape: (N_windows, 30)
        save_path = os.path.join(output_dir, "phase_signals.npy")
        np.save(save_path, phase_array)
        print(f"\n✅ 成功保存相位信号至: {save_path}")
        print(f"📊 最终形状: {phase_array.shape} (窗口数 × 30)")
    else:
        print("\n❌ 未收集到任何有效相位信号！")

if __name__ == "__main__":
    main()