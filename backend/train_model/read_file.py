import numpy as np
import pandas as pd

# 读取 .npy 文件
data = np.load('data.npy')
print("=== data.npy ===")
print("数据类型:", type(data))
print("数组形状:", data.shape)
print("数据类型 (dtype):", data.dtype)
print("前几个元素示例:\n", data.flat[:10] if data.size > 10 else data)  # 打印前10个元素（展平后）
print("\n")

# 读取 HR_ref.csv 文件
hr_ref = pd.read_csv('HR_ref.csv')
print("=== HR_ref.csv ===")
print("数据类型:", type(hr_ref))
print("DataFrame 形状:", hr_ref.shape)
print("列名:", list(hr_ref.columns))
print("前几行数据:")
print(hr_ref.head())