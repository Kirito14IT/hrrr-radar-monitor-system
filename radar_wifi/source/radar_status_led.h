/******************************************************************************
 * File Name:   radar_status_led.h
 *
 * Description: Small LED indicators for radar transmission state.
 ******************************************************************************/

#ifndef RADAR_STATUS_LED_H_
#define RADAR_STATUS_LED_H_

#include <stdbool.h>

void radar_status_led_init(void);
void radar_status_led_set_transmitting(void);
void radar_status_led_set_paused(void);
void radar_status_led_set_idle(void);

#endif /* RADAR_STATUS_LED_H_ */
