/******************************************************************************
 * File Name:   ble_radar_service.h
 *
 * Description: Lightweight BLE status service interface for the radar board.
 ******************************************************************************/

#ifndef BLE_RADAR_SERVICE_H_
#define BLE_RADAR_SERVICE_H_

#include <stdbool.h>
#include <stdint.h>

#define RADAR_BLE_SERVICE_UUID_TEXT        "9f5c1000-8d3b-4f4f-9b1a-6b0bd2d7c001"
#define RADAR_BLE_STATUS_CHAR_UUID_TEXT    "9f5c1001-8d3b-4f4f-9b1a-6b0bd2d7c001"
#define RADAR_BLE_CONTROL_CHAR_UUID_TEXT   "9f5c1002-8d3b-4f4f-9b1a-6b0bd2d7c001"

#define RADAR_BLE_STATUS_VERSION           (1u)

#define RADAR_BLE_FLAG_RADAR_ONLINE        (1u << 0)
#define RADAR_BLE_FLAG_PERSON_PRESENT      (1u << 2)
#define RADAR_BLE_FLAG_TX_ENABLED          (1u << 3)
#define RADAR_BLE_FLAG_HEART_VALID         (1u << 5)
#define RADAR_BLE_FLAG_BREATH_VALID        (1u << 6)
#define RADAR_BLE_FLAG_DISTANCE_VALID      (1u << 7)

typedef struct
{
    uint8_t version;
    uint8_t flags;
    int16_t heart_rate_x10;
    int16_t breath_rate_x10;
    uint16_t distance_mm;
    uint32_t sequence;
} __attribute__((packed)) radar_ble_status_packet_t;

void ble_radar_service_init(void);
void ble_radar_service_start_stack(void);
void ble_radar_service_note_frame_sent(void);
void ble_radar_service_update_vitals(bool valid,
                                     int16_t heart_rate_x10,
                                     int16_t breath_rate_x10,
                                     uint16_t distance_mm);
void ble_radar_service_set_tx_enabled(bool enabled);
bool ble_radar_service_tx_enabled(void);

#endif /* BLE_RADAR_SERVICE_H_ */
