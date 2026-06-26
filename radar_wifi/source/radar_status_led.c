/******************************************************************************
 * File Name:   radar_status_led.c
 *
 * Description: Uses the board user LEDs to show radar transmission state.
 ******************************************************************************/

#include "radar_status_led.h"

#include "cybsp.h"
#include "cyhal.h"

#if defined(CYBSP_USER_LED1)
#define RADAR_TX_LED       CYBSP_USER_LED1
#else
#define RADAR_TX_LED       CYBSP_USER_LED
#endif

#if defined(CYBSP_USER_LED2)
#define RADAR_PAUSE_LED    CYBSP_USER_LED2
#else
#define RADAR_PAUSE_LED    CYBSP_USER_LED
#endif

static bool led_initialized = false;

static void write_leds(uint32_t tx_state, uint32_t pause_state)
{
    if (!led_initialized)
    {
        return;
    }

#if defined(CYBSP_USER_LED2)
    cyhal_gpio_write(RADAR_TX_LED, tx_state);
    cyhal_gpio_write(RADAR_PAUSE_LED, pause_state);
#else
    cyhal_gpio_write(RADAR_TX_LED,
                     (tx_state == CYBSP_LED_STATE_ON || pause_state == CYBSP_LED_STATE_ON) ?
                     CYBSP_LED_STATE_ON : CYBSP_LED_STATE_OFF);
#endif
}

void radar_status_led_init(void)
{
    if (led_initialized)
    {
        return;
    }

    (void)cyhal_gpio_init(RADAR_TX_LED, CYHAL_GPIO_DIR_OUTPUT, CYHAL_GPIO_DRIVE_STRONG, CYBSP_LED_STATE_OFF);

#if defined(CYBSP_USER_LED2)
    (void)cyhal_gpio_init(RADAR_PAUSE_LED, CYHAL_GPIO_DIR_OUTPUT, CYHAL_GPIO_DRIVE_STRONG, CYBSP_LED_STATE_OFF);
#endif

    led_initialized = true;
    radar_status_led_set_idle();
}

void radar_status_led_set_transmitting(void)
{
    write_leds(CYBSP_LED_STATE_ON, CYBSP_LED_STATE_OFF);
}

void radar_status_led_set_paused(void)
{
    write_leds(CYBSP_LED_STATE_OFF, CYBSP_LED_STATE_ON);
}

void radar_status_led_set_idle(void)
{
    write_leds(CYBSP_LED_STATE_OFF, CYBSP_LED_STATE_OFF);
}
