import os
import sys
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.metrics import r2_score, median_absolute_error
from scipy.stats import pearsonr

# -----------------------------
# 直接导入传统方法（要求：usrbin.txt 已重命名为 radar_methods.py）
# -----------------------------
from traditional_methods import ThreeClassMethods  # ← 关键修改：直接 import

# -----------------------------
# 自定义 MRE（Mean Relative Error）函数
# -----------------------------
def mean_relative_error(y_true, y_pred, epsilon=1e-8):
    return np.mean(np.abs(y_true - y_pred) / (np.abs(y_true) + epsilon))

# -----------------------------
# 1. 加载所有标签（HR 和 RR）
# -----------------------------
hr_ref_root = r'D:\STUDY\BGT60TR13C_Dataset\HR_Ref_Data'
all_labels = []

for root, dirs, files in os.walk(hr_ref_root):
    for file in files:
        if file == 'HR_ref.csv':
            csv_path = os.path.join(root, file)
            df = pd.read_csv(csv_path)
            labels = df[['HR (bpm)', 'RR (bpm)']].values
            all_labels.append(labels)

all_labels = np.concatenate(all_labels, axis=0)
print("Total labels loaded:", all_labels.shape)

# -----------------------------
# 2. 加载相位信号（每个窗口 30 帧）
# -----------------------------
data_dir = "train_model"
phase_signals = np.load(os.path.join(data_dir, "phase_signals.npy"))  # shape: (N, 30)

N_signals = phase_signals.shape[0]
N_labels = all_labels.shape[0]

assert N_signals == N_labels, f"样本数量不一致！Signals: {N_signals}, Labels: {N_labels}"

y_hr_true = all_labels[:, 0]  # (N,)
y_rr_true = all_labels[:, 1]  # (N,)

print("Phase signals shape:", phase_signals.shape)

# -----------------------------
# 3. 划分测试集（传统方法无需训练，仅划分用于公平比较）
# -----------------------------
indices = np.arange(N_labels)
_, test_idx = train_test_split(indices, test_size=0.2, random_state=42, shuffle=True)

phase_test = phase_signals[test_idx]
y_hr_test = y_hr_true[test_idx]
y_rr_test = y_rr_true[test_idx]

# -----------------------------
# 4. 使用传统方法预测 HR 和 RR
# -----------------------------
print("\n🔍 Applying traditional methods on test set...")

# 初始化方法类（采样率 30 Hz）
methods = ThreeClassMethods(fs=30.0)

# 心率预测：使用 Welch 优化方法（抗噪性好）
y_hr_pred = methods.welch_optimized_method(phase_test)

# 呼吸率预测：使用 FFT + 带通滤波 + 峰值检测，但切换到呼吸频段 [0.1, 0.5] Hz
original_hr_range = methods.hr_freq_range
methods.hr_freq_range = (0.1, 0.5)  # 呼吸频段：6–30 BPM
y_rr_pred = methods.fft_bpf_peak_method(phase_test)
methods.hr_freq_range = original_hr_range  # 恢复原始设置

# -----------------------------
# 5. 评估函数（与原深度学习代码一致）
# -----------------------------
def evaluate_task(y_true, y_pred, task_name):
    mse = np.mean((y_true - y_pred) ** 2)
    mae = np.mean(np.abs(y_true - y_pred))
    medae = median_absolute_error(y_true, y_pred)
    mre = mean_relative_error(y_true, y_pred) * 100
    r, _ = pearsonr(y_true, y_pred)
    r2 = r2_score(y_true, y_pred)

    diff = y_pred - y_true
    bias = np.mean(diff)
    loa = 1.96 * np.std(diff)

    if task_name == "HR":
        acc = np.mean(np.abs(diff) <= 3.0) * 100  # ±3 bpm
    else:
        acc = np.mean(np.abs(diff) <= 2.0) * 100  # ±2 rpm

    return {
        'MSE': mse,
        'MAE': mae,
        'MedAE': medae,
        'MRE (%)': mre,
        'Pearson r': r,
        'R²': r2,
        'Bias ± LoA': f"{bias:+.2f}±{loa:.2f}",
        'Acc@Tol (%)': acc
    }

# -----------------------------
# 6. 计算并打印评估指标
# -----------------------------
metrics_hr = evaluate_task(y_hr_test, y_hr_pred, "HR")
metrics_rr = evaluate_task(y_rr_test, y_rr_pred, "RR")

print("\n" + "=" * 80)
print("📊 FINAL EVALUATION METRICS (Traditional Methods, Test Set)")
print("=" * 80)
print(f"{'Metric':<20} {'HR (bpm)':>15} {'RR (bpm)':>15}")
print("-" * 80)

for key in ['MSE', 'MAE', 'MedAE', 'MRE (%)']:
    print(f"{key:<20} {metrics_hr[key]:>15.2f} {metrics_rr[key]:>15.2f}")

print(f"{'Pearson r':<20} {metrics_hr['Pearson r']:>15.3f} {metrics_rr['Pearson r']:>15.3f}")
print(f"{'R²':<20} {metrics_hr['R²']:>15.3f} {metrics_rr['R²']:>15.3f}")
print(f"{'Bias ± LoA':<20} {metrics_hr['Bias ± LoA']:>15} {metrics_rr['Bias ± LoA']:>15}")
print(f"{'Acc@Tol (%)':<20} {metrics_hr['Acc@Tol (%)']:>14.1f}% {metrics_rr['Acc@Tol (%)']:>14.1f}%")

print("=" * 80)
print("✅ Traditional signal processing evaluation completed.")