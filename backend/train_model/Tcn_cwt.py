import os
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.metrics import r2_score, median_absolute_error
from scipy.stats import pearsonr
import tensorflow as tf
from tcn import TCN


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
            # 确保只取 HR 和 RR 列
            labels = df[['HR (bpm)', 'RR (bpm)']].values  # shape: (T, 2)
            all_labels.append(labels)

# 拼接所有标签
all_labels = np.concatenate(all_labels, axis=0)  # shape: (N_total, 2)
print("Total labels loaded:", all_labels.shape)

# -----------------------------
# 2. 加载 HR 和 RR 输入数据
# -----------------------------
data_dir = "train_model"
X_hr = np.load(os.path.join(data_dir, "data_hr.npy"))  # (N, 30, 64)
X_rr = np.load(os.path.join(data_dir, "data_rr.npy"))  # (N, 30, 64)

N_hr = X_hr.shape[0]
N_rr = X_rr.shape[0]
N_labels = all_labels.shape[0]

assert N_hr == N_rr == N_labels, f"样本数量不一致！HR: {N_hr}, RR: {N_rr}, Labels: {N_labels}"

y_hr = all_labels[:, 0]  # (N,)
y_rr = all_labels[:, 1]  # (N,)

print("HR data shape:", X_hr.shape, "HR labels shape:", y_hr.shape)
print("RR data shape:", X_rr.shape, "RR labels shape:", y_rr.shape)

# -----------------------------
# 3. 划分训练/测试集（保持索引一致）
# -----------------------------
indices = np.arange(N_labels)
train_idx, test_idx = train_test_split(indices, test_size=0.2, random_state=42, shuffle=True)

X_hr_train, X_hr_test = X_hr[train_idx], X_hr[test_idx]
X_rr_train, X_rr_test = X_rr[train_idx], X_rr[test_idx]
y_hr_train, y_hr_test = y_hr[train_idx], y_hr[test_idx]
y_rr_train, y_rr_test = y_rr[train_idx], y_rr[test_idx]


# -----------------------------
# 4. 构建单输出 TCN 模型
# -----------------------------
def build_single_output_tcn(input_shape):
    inputs = tf.keras.layers.Input(shape=input_shape)
    tcn_out = TCN(
        nb_filters=64,
        kernel_size=3,
        nb_stacks=1,
        dilations=[1, 2, 4, 8],
        padding='causal',
        use_skip_connections=True,
        dropout_rate=0.2,
        return_sequences=False
    )(inputs)
    outputs = tf.keras.layers.Dense(1)(tcn_out)  # 单输出
    model = tf.keras.Model(inputs, outputs)
    model.compile(optimizer='adam', loss='mse', metrics=['mae'])
    return model


# -----------------------------
# 5. 训练 HR 模型
# -----------------------------
print("\n🚀 Training HR Model...")
model_hr = build_single_output_tcn((30, 64))
BATCH_SIZE = 32
train_ds_hr = tf.data.Dataset.from_tensor_slices((X_hr_train, y_hr_train)).shuffle(1000).batch(BATCH_SIZE)
test_ds_hr = tf.data.Dataset.from_tensor_slices((X_hr_test, y_hr_test)).batch(BATCH_SIZE)

history_hr = model_hr.fit(train_ds_hr, epochs=100, validation_data=test_ds_hr)

# 保存 HR 模型
try:
    model_hr.save('radar_tcn_cwt_hr.keras')
except:
    model_hr.save_weights('radar_tcn_cwt_hr.weights.h5')

# -----------------------------
# 6. 训练 RR 模型
# -----------------------------
print("\n🚀 Training RR Model...")
model_rr = build_single_output_tcn((30, 64))
train_ds_rr = tf.data.Dataset.from_tensor_slices((X_rr_train, y_rr_train)).shuffle(1000).batch(BATCH_SIZE)
test_ds_rr = tf.data.Dataset.from_tensor_slices((X_rr_test, y_rr_test)).batch(BATCH_SIZE)

history_rr = model_rr.fit(train_ds_rr, epochs=100, validation_data=test_ds_rr)

# 保存 RR 模型
try:
    model_rr.save('radar_tcn_cwt_rr.keras')
except:
    model_rr.save_weights('radar_tcn_cwt_rr.weights.h5')

# -----------------------------
# 7. 预测
# -----------------------------
print("\n🔍 Predicting on test set...")
y_hr_pred = model_hr.predict(X_hr_test, batch_size=BATCH_SIZE).flatten()
y_rr_pred = model_rr.predict(X_rr_test, batch_size=BATCH_SIZE).flatten()


# -----------------------------
# 8. 评估函数（复用）
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
# 9. 打印结果
# -----------------------------
metrics_hr = evaluate_task(y_hr_test, y_hr_pred, "HR")
metrics_rr = evaluate_task(y_rr_test, y_rr_pred, "RR")

print("\n" + "=" * 80)
print("📊 FINAL EVALUATION METRICS (Test Set)")
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
print(f"Total Parameters per Model: {model_hr.count_params():,}")

# MFLOPs (optional)
mflops = None
try:
    from keras_flops import get_flops

    flops = get_flops(model_hr, batch_size=1)
    mflops = flops / 1e6
    print(f"Estimated MFLOPs (per sample): {mflops:.2f}")
except Exception as e:
    print("MFLOPs: Skipped (TCN custom layer issue)")

print("\n✅ Evaluation completed.")