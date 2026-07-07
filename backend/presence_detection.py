import numpy as np
from scipy import signal

class PresenceAntiPeekingAlgo:
    """
    雷达存在检测和防窥视算法
    可用于检测特定距离范围内是否有人体存在
    """
    def __init__(self, alpha_fast=0.8, alpha_slow=0.02, threshold=1.01):
        """
        初始化存在检测算法
        
        参数:
            alpha_fast: 快速平均滤波器系数 (0-1之间)
            alpha_slow: 慢速平均滤波器系数 (0-1之间)
            threshold: 检测阈值，信号超过此阈值视为检测到人体。
                       原默认值 1.2；先前降至 1.02，本次继续降至 1.01，
                       提高弱目标/远距离目标的存在检测灵敏度。
        """
        self.alpha_fast = alpha_fast
        self.alpha_slow = alpha_slow
        self.threshold = threshold
        self.fast_avg = None
        self.slow_avg = None
        self.initialized = False

    def calculate(self, radar_data, range_bin):
        """
        计算特定距离bin是否有人体存在
        
        参数:
            radar_data: 雷达数据，形状为 (chirps, samples)
            range_bin: 要检测的距离bin索引
            
        返回:
            (presence_detected, detection_value): 是否检测到人体及检测值
        """
        if radar_data is None:
            return False, 0
            
        # 提取特定距离bin的数据
        range_data = radar_data[:, range_bin]
        
        # 计算信号能量（使用更灵敏的计算方法）
        energy = np.mean(np.abs(range_data)**2)  # 使用平方来增强信号差异
        
        # 初始化平均值
        if not self.initialized or self.fast_avg is None:
            self.fast_avg = energy
            self.slow_avg = energy
            self.initialized = True
            return False, 0
            
        # 更新快速和慢速平均值
        self.fast_avg = self.alpha_fast * energy + (1 - self.alpha_fast) * self.fast_avg
        self.slow_avg = self.alpha_slow * energy + (1 - self.alpha_slow) * self.slow_avg
        
        # 计算检测值
        detection_value = self.fast_avg / (self.slow_avg + 1e-10)  # 防止除零
        
        # 判断是否检测到人体
        presence_detected = detection_value > self.threshold
        
        return presence_detected, detection_value


class RadarPresenceDetector:
    """
    雷达存在检测器
    整合了存在检测算法，提供稳定的人体存在检测功能
    """
    def __init__(
        self,
        history_length=5,
        count_threshold=2,
        distance_min_m=0.1,
        distance_max_m=1.0,
        distance_stability_span_m=0.12,
        distance_history_length=None,
    ):
        """
        初始化雷达存在检测器
        
        参数:
            history_length: 历史记录长度，用于稳定性判断
            count_threshold: 连续检测阈值，需要连续检测到的次数
        """
        self.presence_algorithm = PresenceAntiPeekingAlgo()
        self.presence_signal = False
        self.presence_energy_stable = False
        self.presence_distance_stable = False
        self.presence_distance_span = None
        self.presence_distance = None
        self.presence_detection_value = None
        self.presence_detection_threshold = float(self.presence_algorithm.threshold)
        self.presence_detection_bin = None
        self.presence_stable = False
        self.presence_history = []
        self.presence_history_length = history_length
        self.presence_count_threshold = count_threshold
        self.distance_min_m = float(distance_min_m)
        self.distance_max_m = float(distance_max_m)
        self.distance_stability_span_m = float(distance_stability_span_m)
        self.distance_history_length = int(distance_history_length or history_length)
        self.distance_history = []
        self.last_debug = {
            "presence_signal": False,
            "presence_energy_stable": False,
            "presence_distance_stable": False,
            "presence_distance_span": None,
            "presence_distance": None,
            "presence_distance_min_m": self.distance_min_m,
            "presence_distance_max_m": self.distance_max_m,
            "presence_distance_stability_span_m": self.distance_stability_span_m,
            "presence_detection_value": None,
            "presence_detection_threshold": self.presence_detection_threshold,
            "presence_detection_bin": None,
            "presence_below_threshold": False,
            "presence_stable": False,
        }

    def _update_distance_stability(self, target_distance=None):
        self.presence_distance = None
        distance_valid = False
        if target_distance is not None:
            try:
                distance = float(target_distance)
                distance_valid = (
                    np.isfinite(distance) and
                    self.distance_min_m <= distance <= self.distance_max_m
                )
            except (TypeError, ValueError):
                distance = None
        else:
            distance = None

        self.distance_history.append(distance if distance_valid else None)
        if len(self.distance_history) > self.distance_history_length:
            self.distance_history.pop(0)

        valid_distances = [
            float(value)
            for value in self.distance_history
            if value is not None and np.isfinite(float(value))
        ]
        self.presence_distance = distance if distance_valid else None
        if len(valid_distances) < self.distance_history_length:
            self.presence_distance_span = None
            self.presence_distance_stable = False
            return

        span = max(valid_distances) - min(valid_distances)
        self.presence_distance_span = float(span)
        self.presence_distance_stable = span <= self.distance_stability_span_m
        
    def detect_presence(self, radar_data, target_distance=None):
        """
        检测雷达数据中是否有人体存在
        
        参数:
            radar_data: 雷达数据，形状为 (chirps, samples)
            
        返回:
            target_distance: 当前目标距离，单位米。最终存在性要求目标距离在有效范围内且稳定。

        返回:
            (presence_signal, presence_stable): 原始能量检测结果和融合距离稳定后的稳定结果
        """
        # 执行存在检测
        self.presence_signal = False
        self.presence_signal = False
        self.presence_detection_value = None
        self.presence_detection_bin = None
        if radar_data is not None:
            # 检查更多的距离bin，增强检测可靠性
            range_bin_start = 3  # 起始距离bin（更靠近）
            range_bin_group = 5  # 检测的距离bin组数（增加组数）
            range_bin_step = 4   # bin组之间的步长（减小步长）
            range_bin_start = 3
            range_bin_group = 5
            range_bin_step = 4
            presence_group = []
            detection_values = []
            detection_bins = []
            
            for i in range(range_bin_group):
                current_bin = range_bin_start + i * range_bin_step
                detection_result, detection_value = self.presence_algorithm.calculate(radar_data, current_bin)
                presence_group.append(detection_result)
                detection_values.append(detection_value)
                detection_bins.append(current_bin)
                
            # 任一距离检测到即为存在
            self.presence_signal = any(presence_group)
            
            # 如果检测到信号，记录最强的检测值（调试用）
            if self.presence_signal and len(detection_values) > 0:
                max_value = max(detection_values)
                max_index = detection_values.index(max_value)
                max_bin = range_bin_start + max_index * range_bin_step
            finite_pairs = []
            for bin_index, value in zip(detection_bins, detection_values):
                try:
                    numeric_value = float(value)
                except (TypeError, ValueError):
                    continue
                if np.isfinite(numeric_value):
                    finite_pairs.append((bin_index, numeric_value))
            if finite_pairs:
                max_bin, max_value = max(finite_pairs, key=lambda item: item[1])
                self.presence_detection_value = float(max_value)
                self.presence_detection_bin = int(max_bin)
                # print(f"最强检测: bin={max_bin}, 值={max_value:.2f}")
        
        # 存在检测历史记录处理
        self.presence_history.append(self.presence_signal)
        self.presence_history.append(self.presence_signal)
        if len(self.presence_history) > self.presence_history_length:
            self.presence_history.pop(0)
        
        # 稳定性判断 - 连续多次检测到才算真正存在
        presence_count = sum(self.presence_history)
        self.presence_energy_stable = presence_count >= self.presence_count_threshold
        self._update_distance_stability(target_distance)
        self.presence_stable = self.presence_energy_stable and self.presence_distance_stable
        self.presence_detection_threshold = float(self.presence_algorithm.threshold)
        presence_below_threshold = (
            self.presence_detection_value is not None and
            self.presence_detection_value < self.presence_detection_threshold
        )
        self.last_debug = {
            "presence_signal": bool(self.presence_signal),
            "presence_energy_stable": bool(self.presence_energy_stable),
            "presence_distance_stable": bool(self.presence_distance_stable),
            "presence_distance_span": (
                round(float(self.presence_distance_span), 4)
                if self.presence_distance_span is not None else None
            ),
            "presence_distance": (
                round(float(self.presence_distance), 4)
                if self.presence_distance is not None else None
            ),
            "presence_distance_min_m": self.distance_min_m,
            "presence_distance_max_m": self.distance_max_m,
            "presence_distance_stability_span_m": self.distance_stability_span_m,
            "presence_detection_value": (
                round(float(self.presence_detection_value), 4)
                if self.presence_detection_value is not None else None
            ),
            "presence_detection_threshold": round(float(self.presence_detection_threshold), 4),
            "presence_detection_bin": self.presence_detection_bin,
            "presence_below_threshold": bool(presence_below_threshold),
            "presence_stable": bool(self.presence_stable),
        }
        
        return self.presence_signal, self.presence_stable

    def get_debug_state(self):
        return dict(self.last_debug)
        
    def get_distance_profile(self, radar_data, num_distance_bins=50):
        """
        获取距离剖面图数据，用于可视化不同距离的检测结果
        
        参数:
            radar_data: 雷达数据，形状为 (chirps, samples)
            num_distance_bins: 要分析的距离bin数量
            
        返回:
            distance_values: 各距离bin的检测值列表
        """
        if radar_data is None:
            return [0] * num_distance_bins
            
        distance_values = []
        for i in range(num_distance_bins):
            _, detection_value = self.presence_algorithm.calculate(radar_data, i)
            distance_values.append(detection_value)
            
        return distance_values


# 使用示例
def demo_presence_detection():
    """
    存在检测模块使用示例
    """
    # 创建存在检测器实例
    detector = RadarPresenceDetector(history_length=5, count_threshold=2)
    
    # 模拟雷达数据 (实际应用中应替换为真实雷达数据)
    # 假设数据形状为 (chirps, samples) = (32, 256)
    chirps, samples = 32, 256
    
    # 模拟无人场景
    no_person_data = np.random.normal(0, 0.1, (chirps, samples))
    
    # 模拟有人场景 (在距离bin 15处添加较强信号)
    person_data = np.random.normal(0, 0.1, (chirps, samples))
    person_data[:, 15:20] = person_data[:, 15:20] * 5 + 0.5
    
    # 检测示例
    print("无人场景检测:")
    for i in range(10):
        # 添加随机噪声使每次数据略有不同
        data = no_person_data + np.random.normal(0, 0.05, (chirps, samples))
        signal, stable = detector.detect_presence(data)
        print(f"帧 {i+1}: 原始信号={signal}, 稳定结果={stable}")
    
    print("\n有人场景检测:")
    for i in range(10):
        # 添加随机噪声使每次数据略有不同
        data = person_data + np.random.normal(0, 0.05, (chirps, samples))
        signal, stable = detector.detect_presence(data)
        print(f"帧 {i+1}: 原始信号={signal}, 稳定结果={stable}")


if __name__ == "__main__":
    # 运行演示
    demo_presence_detection() 
