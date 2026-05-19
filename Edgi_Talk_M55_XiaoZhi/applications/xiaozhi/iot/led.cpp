/*
 * Copyright (c) 2006-2024, RT-Thread Development Team
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * Change Logs:
 * Date           Author       Notes
 * 2024-01-01     RT-Thread    First version - LED IoT device
 */

#include "thing.h"
#include <rtthread.h>
#include <rtdevice.h>
#include "drv_gpio.h"

#define TAG "LED"

namespace iot
{
    // LED GPIO - P16_5(蓝), P16_6(绿), P16_7(红)
    #define LED_PIN_B   GET_PIN(16, 5)
    #define LED_PIN_G   GET_PIN(16, 6)
    #define LED_PIN_R   GET_PIN(16, 7)
    #define LED_ACTIVE_LOW 0

    static inline rt_base_t led_level(rt_bool_t on)
    {
        if (LED_ACTIVE_LOW)
            return on ? PIN_LOW : PIN_HIGH;
        return on ? PIN_HIGH : PIN_LOW;
    }

    class Led : public Thing
    {
    public:
        Led() : Thing("Led", "LED")
        {
            InitLedGpio();

            // 单一控制方法 - color: red/green/blue/all/off, 也支持 red_off/green_off/blue_off
            methods_.AddMethod("SetLed", "Set LED", ParameterList({
                Parameter("color", "red/green/blue/all/off/red_off/green_off/blue_off", kValueTypeString, true)
            }), [this](const ParameterList &p) {
                std::string color = p["color"].string();
                if (color == "red") {
                    rt_pin_write(LED_PIN_R, led_level(RT_TRUE));
                } else if (color == "red_off") {
                    rt_pin_write(LED_PIN_R, led_level(RT_FALSE));
                } else if (color == "green") {
                    rt_pin_write(LED_PIN_G, led_level(RT_TRUE));
                } else if (color == "green_off") {
                    rt_pin_write(LED_PIN_G, led_level(RT_FALSE));
                } else if (color == "blue") {
                    rt_pin_write(LED_PIN_B, led_level(RT_TRUE));
                } else if (color == "blue_off") {
                    rt_pin_write(LED_PIN_B, led_level(RT_FALSE));
                } else if (color == "all") {
                    rt_pin_write(LED_PIN_R, led_level(RT_TRUE));
                    rt_pin_write(LED_PIN_G, led_level(RT_TRUE));
                    rt_pin_write(LED_PIN_B, led_level(RT_TRUE));
                } else { // off
                    rt_pin_write(LED_PIN_R, led_level(RT_FALSE));
                    rt_pin_write(LED_PIN_G, led_level(RT_FALSE));
                    rt_pin_write(LED_PIN_B, led_level(RT_FALSE));
                }
                rt_kprintf("[%s] color=%s\n", TAG, color.c_str());
            });
        }

    private:
        void InitLedGpio(void)
        {
            rt_pin_mode(LED_PIN_R, PIN_MODE_OUTPUT);
            rt_pin_mode(LED_PIN_G, PIN_MODE_OUTPUT);
            rt_pin_mode(LED_PIN_B, PIN_MODE_OUTPUT);
            rt_pin_write(LED_PIN_R, led_level(RT_FALSE));
            rt_pin_write(LED_PIN_G, led_level(RT_FALSE));
            rt_pin_write(LED_PIN_B, led_level(RT_FALSE));
            rt_kprintf("[%s] GPIO init\n", TAG);
        }
    };

} // namespace iot

DECLARE_THING(Led);
