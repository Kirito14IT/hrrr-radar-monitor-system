/******************************************************************************
 * File Name: wifi_config.h
 *
 * Description: This file contains the configuration macros required for the
 *              Wi-Fi connection.
 *
 * Related Document: See README.md
 *
 * ===========================================================================
 * Copyright (C) 2021 Infineon Technologies AG. All rights reserved.
 * ===========================================================================
 *
 * ===========================================================================
 * Infineon Technologies AG (INFINEON) is supplying this file for use
 * exclusively with Infineon's sensor products. This file can be freely
 * distributed within development tools and software supporting such
 * products.
 *
 * THIS SOFTWARE IS PROVIDED "AS IS".  NO WARRANTIES, WHETHER EXPRESS, IMPLIED
 * OR STATUTORY, INCLUDING, BUT NOT LIMITED TO, IMPLIED WARRANTIES OF
 * MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE APPLY TO THIS SOFTWARE.
 * INFINEON SHALL NOT, IN ANY CIRCUMSTANCES, BE LIABLE FOR DIRECT, INDIRECT,
 * INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES, FOR ANY REASON
 * WHATSOEVER.
 * ===========================================================================
 */

#ifndef WIFI_CONFIG_H_
#define WIFI_CONFIG_H_

#include "cy_wcm.h"

/*******************************************************************************
* Macros
********************************************************************************/
/* SSID of the Wi-Fi Access Point to which the MQTT client connects. */
#define WIFI_SSID                         "B502"

#define WIFI_PASSWORD                     "b5026666"

/* Security type of the Wi-Fi access point. See 'cy_wcm_security_t' structure
 * in "cy_wcm.h" for more details.
 */
#define WIFI_SECURITY                     CY_WCM_SECURITY_WPA2_AES_PSK

/* Maximum Wi-Fi re-connection limit. */
#define MAX_WIFI_CONN_RETRIES             (120u)

/* Wi-Fi re-connection time interval in milliseconds. */
#define WIFI_CONN_RETRY_INTERVAL_MS       (5000)

/* Backend UDP target for radar frames.
 * Keep radar network settings in this config file so every radar board can use
 * the same source code and only this config needs to be changed before build.
 */
#define MAKE_IPV4_ADDRESS(a, b, c, d)     ((((uint32_t) d) << 24) | \
                                          (((uint32_t) c) << 16) | \
                                          (((uint32_t) b) << 8) |\
                                          ((uint32_t) a))

#define RADAR_UDP_SERVER_IP_ADDRESS       MAKE_IPV4_ADDRESS(192, 168, 31, 236)
#define RADAR_UDP_SERVER_PORT             (9988)

/* Backward-compatible names for older code snippets/documentation. */
#define UDP_SERVER_IP_ADDRESS             RADAR_UDP_SERVER_IP_ADDRESS
#define UDP_SERVER_PORT                   RADAR_UDP_SERVER_PORT

#endif /* WIFI_CONFIG_H_ */
