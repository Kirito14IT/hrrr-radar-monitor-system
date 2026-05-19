"""
雷达信号深度学习模型库 - 精简版

该模块包含雷达相位信号处理和心率预测所需的Deep State Space模型定义。
"""

import numpy as np
import tensorflow as tf
from tensorflow.keras import backend as K
from tensorflow.keras.models import Model
from tensorflow.keras.layers import (
    Input, Conv1D, BatchNormalization, MaxPooling1D, GlobalAveragePooling1D,
    Dense, Dropout, LSTM, Bidirectional, GRU, Concatenate, Add, 
    Activation, Lambda, LayerNormalization
)


# ===================== Deep State Space Model =====================

def create_deep_state_space_model(input_shape, output_units=1, state_dim=32, 
                                rnn_units=64, emission_layers=2, dropout_rate=0.2):
    """
    深度状态空间模型，将传统状态空间模型与深度学习结合，适合建模有潜在状态的动态系统
    
    参数:
        input_shape: 输入数据形状
        output_units: 输出单元数量
        state_dim: 潜在状态维度
        rnn_units: RNN层的单元数
        emission_layers: 发射网络的层数
        dropout_rate: Dropout比率
        
    返回:
        编译好的Keras模型
    """
    inputs = Input(shape=input_shape)
    
    # 转换网络 - 将观测转换为潜在状态
    def create_transformation_network(x, state_dim):
        """将输入观测转换为潜在状态表示"""
        # 特征提取
        x = Conv1D(64, kernel_size=3, padding='same', activation='relu')(x)
        x = BatchNormalization()(x)
        x = MaxPooling1D(pool_size=2, padding='same')(x)
        
        x = Conv1D(32, kernel_size=3, padding='same', activation='relu')(x)
        x = BatchNormalization()(x)
        
        # 生成初始状态
        x = GRU(state_dim, return_sequences=True)(x)
        
        return x
    
    # 创建转换网络获取潜在状态序列
    states = create_transformation_network(inputs, state_dim)
    
    # 状态转移网络 - 建模状态的动态演化
    def state_transition_network(states):
        """建模状态的动态演化"""
        # 双向LSTM捕获状态转移的前向和后向依赖
        x = Bidirectional(LSTM(rnn_units, return_sequences=True))(states)
        x = Dropout(dropout_rate)(x)
        
        # 残差连接，确保梯度流动
        if states.shape[-1] != x.shape[-1]:
            states_transformed = Conv1D(x.shape[-1], kernel_size=1, padding='same')(states)
            states = states_transformed
            
        x = Add()([x, states])
        x = LayerNormalization()(x)
        
        return x
    
    # 应用状态转移网络
    dynamic_states = state_transition_network(states)
    
    # 发射网络 - 从状态生成观测（预测）
    def emission_network(states, layers, output_units):
        """从状态生成最终预测"""
        x = states
        
        # 多层处理
        for i in range(layers - 1):
            x = Dense(64, activation='relu')(x)
            x = Dropout(dropout_rate)(x)
            x = LayerNormalization()(x)
        
        # 取最后一个时间步
        x = Lambda(lambda x: x[:, -1, :])(x)
        
        # 生成最终输出
        predictions = Dense(output_units, activation='linear')(x)
        
        return predictions
    
    # 生成最终预测
    outputs = emission_network(dynamic_states, emission_layers, output_units)
    
    # 构建模型
    model = Model(inputs=inputs, outputs=outputs)
    
    # 编译模型
    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=1e-3),
        loss='mse',
        metrics=['mae']
    )
    
    return model