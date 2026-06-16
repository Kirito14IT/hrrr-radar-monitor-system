/*
 * Copyright (c) 2006-2024, RT-Thread Development Team
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * Change Logs:
 * Date           Author       Notes
 * 2024-01-01     RT-Thread    First version
 */

#ifndef __XIAOZHI_UI_H__
#define __XIAOZHI_UI_H__

#include <rtthread.h>
#include <stdlib.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * UI Initialization and Synchronization
 */

/**
 * @brief Initialize UI subsystem
 *
 * This function creates the UI thread and initializes message queue.
 * Call wait_ui_ready() after this to ensure UI is fully initialized.
 */
void xiaozhi_ui_init(void);

/**
 * @brief Wait for UI initialization to complete
 * @param timeout Timeout in OS ticks, RT_WAITING_FOREVER for infinite wait
 * @return RT_EOK on success, -RT_ETIMEOUT on timeout
 */
rt_err_t xiaozhi_ui_wait_ready(rt_int32_t timeout);

/*
 * UI Update Functions
 */

/**
 * @brief Update chat status label
 * @param status Status string to display
 */
void xiaozhi_ui_set_status(const char *status);

/**
 * @brief Update chat output label
 * @param output Output string to display
 */
void xiaozhi_ui_set_output(const char *output);

/**
 * @brief Update snore detect screen result text (thread-safe)
 * @param detected True if snore detected
 * @param score Confidence score (0~1)
 */
void xiaozhi_ui_set_snore_result(bool detected, float score);

/**
 * @brief Show the complete snore inference state on the board.
 * @param model_positive True when the model score crosses its threshold
 * @param alert_triggered True when the local care alarm was triggered
 * @param alert_suppressed True when playback suppression blocked the alarm
 * @param score Model confidence score (0~1)
 */
void xiaozhi_ui_set_snore_inference(bool model_positive,
                                    bool alert_triggered,
                                    bool alert_suppressed,
                                    float score);

/**
 * @brief Update the main-screen snore guard button and state.
 */
void xiaozhi_ui_set_snore_guard_state(bool enabled);

/**
 * @brief Show the alarm ringing screen.
 */
void xiaozhi_ui_show_alarm_ring(void);
void xiaozhi_ui_hide_alarm_ring(void);
void xiaozhi_ui_refresh_alarm_clock(void);

/**
 * @brief Show the emergency state screen (thread-safe)
 * @param phrase Matched emergency phrase
 */
void xiaozhi_ui_show_emergency(const char *phrase);

/**
 * @brief Finish the emergency resolve operation (thread-safe)
 * @param success True when the backend accepted the resolution
 */
void xiaozhi_ui_set_emergency_resolution(bool success);

/**
 * @brief Enter snore detect screen and start detection (for voice command)
 *
 * 该接口等价于在主界面点击一次 `Snore detect` 按钮：
 * - 暂停小智语音流水线
 * - 切换到打鼾检测界面
 * - 启动连续打鼾检测线程
 */
void xiaozhi_ui_enter_snore_mode_from_voice(void);

/**
 * @brief Update emoji display
 * @param emoji Emoji name (e.g., "happy", "sad", "neutral")
 */
void xiaozhi_ui_set_emoji(const char *emoji);

/**
 * @brief Update ADC display label
 * @param adc_str ADC value string to display
 */
void xiaozhi_ui_set_adc(const char *adc_str);

/**
 * @brief Update idle environment line
 * @param temperature_c Temperature in Celsius
 * @param humidity_pct Relative humidity percentage
 * @param valid True if the reading is valid
 * @param status Short status text (for example: OK, STALE, SENSOR_ERROR)
 */
void xiaozhi_ui_set_environment(float temperature_c,
                                float humidity_pct,
                                bool valid,
                                const char *status);

/**
 * @brief Clear info label (label2)
 */
void xiaozhi_ui_clear_info(void);

/**
 * @brief Show AP config mode info on screen
 */
void xiaozhi_ui_show_ap_config(void);

/**
 * @brief Show connecting status (for auto-connect from saved config)
 */
void xiaozhi_ui_show_connecting(void);

/**
 * @brief Update battery level display
 * @param level Battery level (0-100)
 */
void xiaozhi_ui_update_battery(int level);

/**
 * @brief Update charging status display
 * @param is_charging True if charging, False otherwise
 */
void xiaozhi_ui_update_charging_status(bool is_charging);

/**
 * @brief Update BLE connection status icon
 * @param connected True if BLE is connected, False otherwise
 * @note Bluetooth functionality not implemented
 */
void xiaozhi_ui_update_ble_status(bool connected);

/* Legacy API Compatibility - Keep for backward compatibility */

/**
 * @brief Legacy function: Initialize UI subsystem
 * @deprecated Use xiaozhi_ui_init() instead
 */
void init_ui(void);

/**
 * @brief Legacy function: Wait for UI initialization
 * @deprecated Use xiaozhi_ui_wait_ready() instead
 */
rt_err_t wait_ui_ready(rt_int32_t timeout);

/**
 * @brief Legacy function: Clear info label
 * @deprecated Use xiaozhi_ui_clear_info() instead
 */
void clean_info(void);

/**
 * @brief Legacy function: Update chat status
 * @deprecated Use xiaozhi_ui_set_status() instead
 */
void xiaozhi_ui_chat_status(char *string);

/**
 * @brief Legacy function: Update chat output
 * @deprecated Use xiaozhi_ui_set_output() instead
 */
void xiaozhi_ui_chat_output(char *string);

/**
 * @brief Legacy function: Update emoji display
 * @deprecated Use xiaozhi_ui_set_emoji() instead
 */
void xiaozhi_ui_update_emoji(char *string);

/**
 * @brief Legacy function: Update ADC display
 * @deprecated Use xiaozhi_ui_set_adc() instead
 */
void xiaozhi_ui_update_adc(char *string);

#ifdef __cplusplus
}
#endif

#endif /* __XIAOZHI_UI_H__ */
