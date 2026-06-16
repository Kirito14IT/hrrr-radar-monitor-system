/*
 * Copyright (c) 2006-2024, RT-Thread Development Team
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * Change Logs:
 * Date           Author       Notes
 * 2024-01-01     RT-Thread    First version
 */

#include <rtthread.h>
#include <rtdevice.h>
#include <board.h>
#include "imu_fall_monitor.h"
#include "alarm_clock.h"

/*****************************************************************************
 * Macro Definitions
 *****************************************************************************/
#define DBG_TAG    "main"
#define DBG_LVL    DBG_INFO
#include <rtdbg.h>

/* LED Pin */
#define LED_PIN_GREEN       GET_PIN(16, 6)

/* UI initialization timeout (ms) */
#define UI_INIT_TIMEOUT_MS  5000

/*****************************************************************************
 * External Function Declarations
 *****************************************************************************/
extern void xiaozhi_ui_init(void);
extern rt_err_t xiaozhi_ui_wait_ready(rt_int32_t timeout);
extern void wifi_manager_init(void);
extern int env_monitor_init(void);

/*****************************************************************************
 * Main Entry
 *****************************************************************************/

int main(void)
{
    LOG_I("Cortex-M55 started");

    /* Initialize UI subsystem */
    xiaozhi_ui_init();

    /* Wait for UI initialization to complete */
    if (xiaozhi_ui_wait_ready(rt_tick_from_millisecond(UI_INIT_TIMEOUT_MS)) != RT_EOK)
    {
        LOG_W("UI initialization timeout");
    }

    /* Start environment monitor before WiFi so idle UI can show sensor state. */
    env_monitor_init();

    /* Initialize WiFi manager */
    wifi_manager_init();

    if (alarm_clock_init() != RT_EOK)
    {
        LOG_W("Alarm clock unavailable");
    }

    /* Detect a board free fall as a non-verbal emergency signal when fitted. */
#ifdef BSP_USING_LSM6DS3
    if (imu_fall_monitor_init() != RT_EOK)
    {
        LOG_W("IMU free-fall monitor unavailable");
    }
#else
    LOG_I("IMU free-fall monitor disabled (BSP_USING_LSM6DS3 is not set)");
#endif

    return 0;
}
