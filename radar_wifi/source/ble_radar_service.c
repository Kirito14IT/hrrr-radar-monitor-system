/******************************************************************************
 * File Name:   ble_radar_service.c
 *
 * Description: RadarCare BLE service state. The default build keeps this module
 *              dependency-free; define ENABLE_RADAR_BLE after adding the
 *              Infineon BTStack GATT server dependencies to enable radio I/O.
 ******************************************************************************/

#include "ble_radar_service.h"

#include <inttypes.h>
#include <stdio.h>
#include <string.h>

#include "FreeRTOS.h"
#include "semphr.h"
#include "task.h"

#include "radar_task.h"

#if defined(ENABLE_RADAR_BLE)
#include "cybsp_bt_config.h"
#include "wiced_bt_adv_scan_common.h"
#include "wiced_bt_adv_scan_legacy.h"
#include "wiced_bt_cfg.h"
#include "wiced_bt_dev.h"
#include "wiced_bt_gatt.h"
#include "wiced_bt_stack.h"
#endif

#define RADAR_BLE_NOTIFY_PERIOD_MS     (1000u)
#define RADAR_BLE_UNKNOWN_DISTANCE_MM  (0u)

#if defined(ENABLE_RADAR_BLE)
#define RADAR_BLE_DEVICE_NAME_PREFIX   "RadarCare"
#define RADAR_BLE_DEVICE_NAME          "RadarCare-E84"
#define RADAR_BLE_MAX_CONN             (1u)
#define RADAR_BLE_MTU                  (65u)

#define HANDLE_GAP_SERVICE             (0x0001u)
#define HANDLE_GAP_DEVICE_NAME_DECL    (0x0002u)
#define HANDLE_GAP_DEVICE_NAME_VALUE   (0x0003u)
#define HANDLE_GAP_APPEARANCE_DECL     (0x0004u)
#define HANDLE_GAP_APPEARANCE_VALUE    (0x0005u)
#define HANDLE_GATT_SERVICE            (0x0010u)
#define HANDLE_RADAR_SERVICE           (0x0028u)
#define HANDLE_RADAR_STATUS_DECL       (0x0029u)
#define HANDLE_RADAR_STATUS_VALUE      (0x002au)
#define HANDLE_RADAR_STATUS_CCCD       (0x002bu)
#define HANDLE_RADAR_CONTROL_DECL      (0x002cu)
#define HANDLE_RADAR_CONTROL_VALUE     (0x002du)

#define UUID_RADAR_SERVICE_BYTES       0x01, 0xc0, 0xd7, 0xd2, 0x0b, 0x6b, 0x1a, 0x9b, 0x4f, 0x3b, 0x8d, 0x3b, 0x00, 0x10, 0x5c, 0x9f
#define UUID_RADAR_STATUS_BYTES        0x01, 0xc0, 0xd7, 0xd2, 0x0b, 0x6b, 0x1a, 0x9b, 0x4f, 0x3b, 0x8d, 0x3b, 0x01, 0x10, 0x5c, 0x9f
#define UUID_RADAR_CONTROL_BYTES       0x01, 0xc0, 0xd7, 0xd2, 0x0b, 0x6b, 0x1a, 0x9b, 0x4f, 0x3b, 0x8d, 0x3b, 0x02, 0x10, 0x5c, 0x9f
#endif

static SemaphoreHandle_t status_lock;
static radar_ble_status_packet_t status_packet = {
    .version = RADAR_BLE_STATUS_VERSION,
    .flags = RADAR_BLE_FLAG_TX_ENABLED,
    .heart_rate_x10 = 0,
    .breath_rate_x10 = 0,
    .distance_mm = RADAR_BLE_UNKNOWN_DISTANCE_MM,
    .sequence = 0,
};

static bool tx_enabled = true;

#if defined(ENABLE_RADAR_BLE)
static uint16_t ble_conn_id;
static bool ble_stack_ready;
static bool ble_stack_start_requested;
static bool ble_notifications_enabled;
static uint16_t ble_status_cccd;
static uint8_t ble_status_value[sizeof(radar_ble_status_packet_t)];
static const uint8_t ble_appearance[] =
{
    (uint8_t)(APPEARANCE_SENSOR_GENERIC & 0xffu),
    (uint8_t)((APPEARANCE_SENSOR_GENERIC >> 8) & 0xffu),
};

static const wiced_bt_cfg_ble_scan_settings_t radar_ble_scan_cfg =
{
    .scan_mode = BTM_BLE_SCAN_MODE_PASSIVE,
    .high_duty_scan_interval = WICED_BT_CFG_DEFAULT_HIGH_DUTY_SCAN_INTERVAL,
    .high_duty_scan_window = WICED_BT_CFG_DEFAULT_HIGH_DUTY_SCAN_WINDOW,
    .high_duty_scan_duration = 0,
    .low_duty_scan_interval = WICED_BT_CFG_DEFAULT_LOW_DUTY_SCAN_INTERVAL,
    .low_duty_scan_window = WICED_BT_CFG_DEFAULT_LOW_DUTY_SCAN_WINDOW,
    .low_duty_scan_duration = 0,
    .high_duty_conn_scan_interval = WICED_BT_CFG_DEFAULT_HIGH_DUTY_CONN_SCAN_INTERVAL,
    .high_duty_conn_scan_window = WICED_BT_CFG_DEFAULT_HIGH_DUTY_CONN_SCAN_WINDOW,
    .high_duty_conn_duration = 0,
    .low_duty_conn_scan_interval = WICED_BT_CFG_DEFAULT_LOW_DUTY_CONN_SCAN_INTERVAL,
    .low_duty_conn_scan_window = WICED_BT_CFG_DEFAULT_LOW_DUTY_CONN_SCAN_WINDOW,
    .low_duty_conn_duration = 0,
    .conn_min_interval = WICED_BT_CFG_DEFAULT_CONN_MIN_INTERVAL,
    .conn_max_interval = WICED_BT_CFG_DEFAULT_CONN_MAX_INTERVAL,
    .conn_latency = WICED_BT_CFG_DEFAULT_CONN_LATENCY,
    .conn_supervision_timeout = WICED_BT_CFG_DEFAULT_CONN_SUPERVISION_TIMEOUT,
};

static const wiced_bt_cfg_ble_advert_settings_t radar_ble_adv_cfg =
{
    .channel_map = BTM_BLE_DEFAULT_ADVERT_CHNL_MAP,
    .high_duty_min_interval = WICED_BT_CFG_DEFAULT_HIGH_DUTY_ADV_MIN_INTERVAL,
    .high_duty_max_interval = WICED_BT_CFG_DEFAULT_HIGH_DUTY_ADV_MAX_INTERVAL,
    .high_duty_duration = 0,
    .low_duty_min_interval = WICED_BT_CFG_DEFAULT_LOW_DUTY_ADV_MIN_INTERVAL,
    .low_duty_max_interval = WICED_BT_CFG_DEFAULT_LOW_DUTY_ADV_MAX_INTERVAL,
    .low_duty_duration = 0,
    .high_duty_directed_min_interval = WICED_BT_CFG_DEFAULT_HIGH_DUTY_DIRECTED_ADV_MIN_INTERVAL,
    .high_duty_directed_max_interval = WICED_BT_CFG_DEFAULT_HIGH_DUTY_DIRECTED_ADV_MAX_INTERVAL,
    .low_duty_directed_min_interval = WICED_BT_CFG_DEFAULT_LOW_DUTY_DIRECTED_ADV_MIN_INTERVAL,
    .low_duty_directed_max_interval = WICED_BT_CFG_DEFAULT_LOW_DUTY_DIRECTED_ADV_MAX_INTERVAL,
    .low_duty_directed_duration = 0,
    .high_duty_nonconn_min_interval = WICED_BT_CFG_DEFAULT_HIGH_DUTY_NONCONN_ADV_MIN_INTERVAL,
    .high_duty_nonconn_max_interval = WICED_BT_CFG_DEFAULT_HIGH_DUTY_NONCONN_ADV_MAX_INTERVAL,
    .high_duty_nonconn_duration = 0,
    .low_duty_nonconn_min_interval = WICED_BT_CFG_DEFAULT_LOW_DUTY_NONCONN_ADV_MIN_INTERVAL,
    .low_duty_nonconn_max_interval = WICED_BT_CFG_DEFAULT_LOW_DUTY_NONCONN_ADV_MAX_INTERVAL,
    .low_duty_nonconn_duration = 0,
};

static const wiced_bt_cfg_ble_t radar_ble_cfg =
{
    .ble_max_simultaneous_links = RADAR_BLE_MAX_CONN,
    .ble_max_rx_pdu_size = RADAR_BLE_MTU,
    .appearance = 0,
    .rpa_refresh_timeout = 0,
    .host_addr_resolution_db_size = 0,
    .p_ble_scan_cfg = &radar_ble_scan_cfg,
    .p_ble_advert_cfg = &radar_ble_adv_cfg,
    .default_ble_power_level = 0,
};

static const wiced_bt_cfg_gatt_t radar_gatt_cfg =
{
    .max_db_service_modules = 0,
    .max_eatt_bearers = 0,
};

static uint8_t radar_ble_device_name[] = RADAR_BLE_DEVICE_NAME;
static const wiced_bt_cfg_settings_t radar_bt_cfg =
{
    .device_name = radar_ble_device_name,
    .security_required = 0,
    .p_br_cfg = NULL,
    .p_ble_cfg = &radar_ble_cfg,
    .p_gatt_cfg = &radar_gatt_cfg,
    .p_isoc_cfg = NULL,
    .p_l2cap_app_cfg = NULL,
};

static const uint8_t radar_gatt_db[] =
{
    PRIMARY_SERVICE_UUID16(HANDLE_GAP_SERVICE, UUID_SERVICE_GAP),
    CHARACTERISTIC_UUID16(HANDLE_GAP_DEVICE_NAME_DECL,
                          HANDLE_GAP_DEVICE_NAME_VALUE,
                          GATT_UUID_GAP_DEVICE_NAME,
                          GATT_CHAR_PROPERTIES_BIT_READ,
                          GATTDB_PERM_READABLE),
    CHARACTERISTIC_UUID16(HANDLE_GAP_APPEARANCE_DECL,
                          HANDLE_GAP_APPEARANCE_VALUE,
                          GATT_UUID_GAP_ICON,
                          GATT_CHAR_PROPERTIES_BIT_READ,
                          GATTDB_PERM_READABLE),

    PRIMARY_SERVICE_UUID16(HANDLE_GATT_SERVICE, UUID_SERVICE_GATT),

    PRIMARY_SERVICE_UUID128(HANDLE_RADAR_SERVICE, UUID_RADAR_SERVICE_BYTES),
    CHARACTERISTIC_UUID128(HANDLE_RADAR_STATUS_DECL,
                           HANDLE_RADAR_STATUS_VALUE,
                           UUID_RADAR_STATUS_BYTES,
                           GATT_CHAR_PROPERTIES_BIT_READ | GATT_CHAR_PROPERTIES_BIT_NOTIFY,
                           GATTDB_PERM_READABLE),
    CHAR_DESCRIPTOR_UUID16_WRITABLE(HANDLE_RADAR_STATUS_CCCD,
                                    GATT_UUID_CHAR_CLIENT_CONFIG,
                                    GATTDB_PERM_READABLE | GATTDB_PERM_WRITE_REQ),
    CHARACTERISTIC_UUID128_WRITABLE(HANDLE_RADAR_CONTROL_DECL,
                                    HANDLE_RADAR_CONTROL_VALUE,
                                    UUID_RADAR_CONTROL_BYTES,
                                    GATT_CHAR_PROPERTIES_BIT_WRITE | GATT_CHAR_PROPERTIES_BIT_WRITE_NR,
                                    GATTDB_PERM_WRITE_REQ | GATTDB_PERM_WRITE_CMD),
};
#endif

static void status_lock_take(void)
{
    if (status_lock != NULL)
    {
        (void)xSemaphoreTake(status_lock, portMAX_DELAY);
    }
}

static void status_lock_give(void)
{
    if (status_lock != NULL)
    {
        (void)xSemaphoreGive(status_lock);
    }
}

static radar_ble_status_packet_t status_snapshot(void)
{
    radar_ble_status_packet_t snapshot;
    status_lock_take();
    snapshot = status_packet;
    status_lock_give();
    return snapshot;
}

#if defined(ENABLE_RADAR_BLE)
static void ble_apply_control_command(const uint8_t *data, uint16_t length);

static void ble_status_to_bytes(const radar_ble_status_packet_t *packet, uint8_t *out)
{
    out[0] = packet->version;
    out[1] = packet->flags;
    out[2] = (uint8_t)(packet->heart_rate_x10 & 0xff);
    out[3] = (uint8_t)((packet->heart_rate_x10 >> 8) & 0xff);
    out[4] = (uint8_t)(packet->breath_rate_x10 & 0xff);
    out[5] = (uint8_t)((packet->breath_rate_x10 >> 8) & 0xff);
    out[6] = (uint8_t)(packet->distance_mm & 0xff);
    out[7] = (uint8_t)((packet->distance_mm >> 8) & 0xff);
    out[8] = (uint8_t)(packet->sequence & 0xffu);
    out[9] = (uint8_t)((packet->sequence >> 8) & 0xffu);
    out[10] = (uint8_t)((packet->sequence >> 16) & 0xffu);
    out[11] = (uint8_t)((packet->sequence >> 24) & 0xffu);
}

static void ble_start_advertising(void)
{
    static uint8_t adv_flags = BTM_BLE_GENERAL_DISCOVERABLE_FLAG | BTM_BLE_BREDR_NOT_SUPPORTED;
    static uint8_t service_uuid[] = { UUID_RADAR_SERVICE_BYTES };
    static uint8_t device_name[] = RADAR_BLE_DEVICE_NAME;

    wiced_bt_ble_advert_elem_t adv_data[] =
    {
        {
            .advert_type = BTM_BLE_ADVERT_TYPE_FLAG,
            .len = sizeof(adv_flags),
            .p_data = &adv_flags,
        },
        {
            .advert_type = BTM_BLE_ADVERT_TYPE_128SRV_COMPLETE,
            .len = sizeof(service_uuid),
            .p_data = service_uuid,
        },
    };
    wiced_bt_ble_advert_elem_t scan_rsp_data[] =
    {
        {
            .advert_type = BTM_BLE_ADVERT_TYPE_NAME_COMPLETE,
            .len = sizeof(device_name) - 1u,
            .p_data = device_name,
        },
    };

    wiced_result_t result = wiced_bt_ble_set_raw_advertisement_data(
        (uint8_t)(sizeof(adv_data) / sizeof(adv_data[0])),
        adv_data);
    printf("Radar BLE: set adv data result=%u\r\n", (unsigned)result);

    result = wiced_bt_ble_set_raw_scan_response_data(
        (uint8_t)(sizeof(scan_rsp_data) / sizeof(scan_rsp_data[0])),
        scan_rsp_data);
    printf("Radar BLE: set scan rsp result=%u\r\n", (unsigned)result);

    result = wiced_bt_start_advertisements(BTM_BLE_ADVERT_UNDIRECTED_HIGH, 0, NULL);
    printf("Radar BLE: advertising start result=%u name=%s\r\n", (unsigned)result, RADAR_BLE_DEVICE_NAME);
}

static wiced_bt_gatt_status_t ble_send_read_rsp(wiced_bt_gatt_attribute_request_t *request,
                                                const uint8_t *data,
                                                uint16_t length)
{
    uint16_t offset;

    if ((request == NULL) || (data == NULL))
    {
        return WICED_BT_GATT_INVALID_HANDLE;
    }

    offset = request->data.read_req.offset;
    if (offset > length)
    {
        (void)wiced_bt_gatt_server_send_error_rsp(request->conn_id,
                                                 request->opcode,
                                                 request->data.read_req.handle,
                                                 WICED_BT_GATT_INVALID_OFFSET);
        return WICED_BT_GATT_HANDLED;
    }

    (void)wiced_bt_gatt_server_send_read_handle_rsp(request->conn_id,
                                                    request->opcode,
                                                    (uint16_t)(length - offset),
                                                    (uint8_t *)(data + offset),
                                                    NULL);
    return WICED_BT_GATT_HANDLED;
}

static wiced_bt_gatt_status_t ble_handle_attribute_request(wiced_bt_gatt_attribute_request_t *request)
{
    if (request == NULL)
    {
        return WICED_BT_GATT_INVALID_HANDLE;
    }

    printf("Radar BLE: attr req opcode=0x%02x conn_id=%u len=%u\r\n",
           (unsigned)request->opcode,
           (unsigned)request->conn_id,
           (unsigned)request->len_requested);

    if (request->opcode == GATT_REQ_MTU)
    {
        printf("Radar BLE: mtu req remote=%u local=%u\r\n",
               (unsigned)request->data.remote_mtu,
               (unsigned)RADAR_BLE_MTU);
        (void)wiced_bt_gatt_server_send_mtu_rsp(request->conn_id,
                                               request->data.remote_mtu,
                                               RADAR_BLE_MTU);
        return WICED_BT_GATT_HANDLED;
    }

    if (((request->opcode == GATT_REQ_READ) || (request->opcode == GATT_REQ_READ_BLOB)) &&
        (request->data.read_req.handle == HANDLE_GAP_DEVICE_NAME_VALUE))
    {
        return ble_send_read_rsp(request,
                                 (const uint8_t *)RADAR_BLE_DEVICE_NAME,
                                 (uint16_t)(sizeof(RADAR_BLE_DEVICE_NAME) - 1u));
    }

    if (((request->opcode == GATT_REQ_READ) || (request->opcode == GATT_REQ_READ_BLOB)) &&
        (request->data.read_req.handle == HANDLE_GAP_APPEARANCE_VALUE))
    {
        return ble_send_read_rsp(request, ble_appearance, sizeof(ble_appearance));
    }

    if (((request->opcode == GATT_REQ_READ) || (request->opcode == GATT_REQ_READ_BLOB)) &&
        (request->data.read_req.handle == HANDLE_RADAR_STATUS_VALUE))
    {
        radar_ble_status_packet_t snapshot = status_snapshot();
        ble_status_to_bytes(&snapshot, ble_status_value);
        return ble_send_read_rsp(request, ble_status_value, sizeof(ble_status_value));
    }

    if (((request->opcode == GATT_REQ_READ) || (request->opcode == GATT_REQ_READ_BLOB)) &&
        (request->data.read_req.handle == HANDLE_RADAR_STATUS_CCCD))
    {
        uint8_t cccd[2] =
        {
            (uint8_t)(ble_status_cccd & 0xffu),
            (uint8_t)((ble_status_cccd >> 8) & 0xffu),
        };
        return ble_send_read_rsp(request, cccd, sizeof(cccd));
    }

    if ((request->opcode == GATT_REQ_WRITE) || (request->opcode == GATT_CMD_WRITE))
    {
        const wiced_bt_gatt_write_req_t *write = &request->data.write_req;
        if (write->handle == HANDLE_RADAR_STATUS_CCCD)
        {
            if (write->val_len >= 2u)
            {
                ble_status_cccd = (uint16_t)write->p_val[0] | ((uint16_t)write->p_val[1] << 8);
                ble_notifications_enabled = (ble_status_cccd & GATT_CLIENT_CONFIG_NOTIFICATION) != 0u;
            }
        }
        else if (write->handle == HANDLE_RADAR_CONTROL_VALUE)
        {
            ble_apply_control_command(write->p_val, write->val_len);
        }

        if (request->opcode == GATT_REQ_WRITE)
        {
            (void)wiced_bt_gatt_server_send_write_rsp(request->conn_id, request->opcode, write->handle);
            return WICED_BT_GATT_HANDLED;
        }

        return WICED_BT_GATT_SUCCESS;
    }

    printf("Radar BLE: unhandled attr req opcode=0x%02x\r\n", (unsigned)request->opcode);
    return WICED_BT_GATT_SUCCESS;
}

static wiced_bt_gatt_status_t ble_gatt_callback(wiced_bt_gatt_evt_t event,
                                                wiced_bt_gatt_event_data_t *event_data)
{
    switch (event)
    {
        case GATT_CONNECTION_STATUS_EVT:
            if ((event_data != NULL) && event_data->connection_status.connected)
            {
                ble_conn_id = event_data->connection_status.conn_id;
                printf("Radar BLE: connected conn_id=%u transport=%u role=%u\r\n",
                       (unsigned)ble_conn_id,
                       (unsigned)event_data->connection_status.transport,
                       (unsigned)event_data->connection_status.link_role);
            }
            else
            {
                unsigned reason = (event_data != NULL) ?
                                  (unsigned)event_data->connection_status.reason : 0u;
                ble_conn_id = 0;
                ble_notifications_enabled = false;
                ble_status_cccd = 0;
                printf("Radar BLE: disconnected reason=%u, restart advertising\r\n", reason);
                ble_start_advertising();
            }
            break;

        case GATT_ATTRIBUTE_REQUEST_EVT:
            return ble_handle_attribute_request(&event_data->attribute_request);

        case GATT_CONGESTION_EVT:
            printf("Radar BLE: congestion=%u\r\n",
                   (event_data != NULL) ? (unsigned)event_data->congestion.congested : 0u);
            break;

        default:
            break;
    }

    return WICED_BT_GATT_SUCCESS;
}

static wiced_result_t ble_management_callback(wiced_bt_management_evt_t event,
                                              wiced_bt_management_evt_data_t *event_data)
{
    (void)event_data;

    if (event == BTM_ENABLED_EVT)
    {
        wiced_bt_gatt_status_t gatt_result;

        printf("Radar BLE: stack enabled\r\n");
        ble_stack_ready = true;
        gatt_result = wiced_bt_gatt_register(ble_gatt_callback);
        printf("Radar BLE: gatt register result=%u\r\n", (unsigned)gatt_result);
        gatt_result = wiced_bt_gatt_db_init(radar_gatt_db, sizeof(radar_gatt_db), NULL);
        printf("Radar BLE: gatt db init result=%u\r\n", (unsigned)gatt_result);
        ble_start_advertising();
    }

    return WICED_BT_SUCCESS;
}

static void ble_stack_start(void)
{
    if (ble_stack_start_requested)
    {
        return;
    }

    ble_stack_start_requested = true;
    printf("Radar BLE: platform config init\r\n");
    cybt_platform_config_init(&cybsp_bt_platform_cfg);
    printf("Radar BLE: dynamic memory required=%ld bytes\r\n",
           (long)wiced_bt_stack_get_dynamic_memory_size_for_config(&radar_bt_cfg));
    wiced_result_t result = wiced_bt_stack_init(ble_management_callback, &radar_bt_cfg);
    printf("Radar BLE: stack init result=%u\r\n", (unsigned)result);
    if (result != WICED_BT_SUCCESS)
    {
        ble_stack_start_requested = false;
    }
}

static void ble_notify_status(const radar_ble_status_packet_t *packet)
{
    if (!ble_stack_ready || !ble_notifications_enabled || (ble_conn_id == 0u) || (packet == NULL))
    {
        return;
    }

    ble_status_to_bytes(packet, ble_status_value);
    (void)wiced_bt_gatt_server_send_notification(ble_conn_id,
                                                 HANDLE_RADAR_STATUS_VALUE,
                                                 sizeof(ble_status_value),
                                                 ble_status_value,
                                                 NULL);
}

static void ble_apply_control_command(const uint8_t *data, uint16_t length)
{
    if (data == NULL || length == 0u)
    {
        return;
    }

    if (length == 1u)
    {
        if (data[0] == 0x01u)
        {
            ble_radar_service_set_tx_enabled(false);
            (void)radar_start(false);
        }
        else if (data[0] == 0x02u)
        {
            ble_radar_service_set_tx_enabled(true);
            (void)radar_start(true);
        }
        return;
    }

    if ((length >= 8u) && (memcmp(data, "pause_tx", 8u) == 0))
    {
        ble_radar_service_set_tx_enabled(false);
        (void)radar_start(false);
    }
    else if ((length >= 9u) && (memcmp(data, "resume_tx", 9u) == 0))
    {
        ble_radar_service_set_tx_enabled(true);
        (void)radar_start(true);
    }
}
#else
static void ble_notify_status(const radar_ble_status_packet_t *packet)
{
    (void)packet;
}
#endif

static void ble_radar_status_task(void *arg)
{
    (void)arg;

    for (;;)
    {
        radar_ble_status_packet_t snapshot = status_snapshot();
        ble_notify_status(&snapshot);
        vTaskDelay(pdMS_TO_TICKS(RADAR_BLE_NOTIFY_PERIOD_MS));
    }
}

void ble_radar_service_init(void)
{
    if (status_lock == NULL)
    {
        status_lock = xSemaphoreCreateMutex();
    }

#if defined(ENABLE_RADAR_BLE)
    printf("Radar BLE: service enabled (%s)\r\n", RADAR_BLE_SERVICE_UUID_TEXT);
#else
    printf("Radar BLE: service scaffold loaded; define ENABLE_RADAR_BLE after adding BTStack dependencies\r\n");
#endif

    (void)xTaskCreate(ble_radar_status_task,
                      "radar_ble",
                      configMINIMAL_STACK_SIZE * 2u,
                      NULL,
                      2u,
                      NULL);
}

void ble_radar_service_start_stack(void)
{
#if defined(ENABLE_RADAR_BLE)
    ble_stack_start();
#endif
}

void ble_radar_service_note_frame_sent(void)
{
    status_lock_take();
    status_packet.flags |= RADAR_BLE_FLAG_RADAR_ONLINE | RADAR_BLE_FLAG_PERSON_PRESENT;
    if (tx_enabled)
    {
        status_packet.flags |= RADAR_BLE_FLAG_TX_ENABLED;
    }
    status_packet.sequence++;
    status_lock_give();
}

void ble_radar_service_update_vitals(bool valid,
                                     int16_t heart_rate_x10,
                                     int16_t breath_rate_x10,
                                     uint16_t distance_mm)
{
    status_lock_take();
    if (valid)
    {
        status_packet.flags |= RADAR_BLE_FLAG_HEART_VALID |
                               RADAR_BLE_FLAG_BREATH_VALID |
                               RADAR_BLE_FLAG_DISTANCE_VALID;
        status_packet.heart_rate_x10 = heart_rate_x10;
        status_packet.breath_rate_x10 = breath_rate_x10;
        status_packet.distance_mm = distance_mm;
    }
    else
    {
        status_packet.flags &= (uint8_t)~(RADAR_BLE_FLAG_HEART_VALID |
                                          RADAR_BLE_FLAG_BREATH_VALID |
                                          RADAR_BLE_FLAG_DISTANCE_VALID);
        status_packet.heart_rate_x10 = 0;
        status_packet.breath_rate_x10 = 0;
        status_packet.distance_mm = RADAR_BLE_UNKNOWN_DISTANCE_MM;
    }
    status_packet.sequence++;
    status_lock_give();
}

void ble_radar_service_set_tx_enabled(bool enabled)
{
    tx_enabled = enabled;
    status_lock_take();
    if (enabled)
    {
        status_packet.flags |= RADAR_BLE_FLAG_TX_ENABLED;
    }
    else
    {
        status_packet.flags &= (uint8_t)~RADAR_BLE_FLAG_TX_ENABLED;
    }
    status_packet.sequence++;
    status_lock_give();
}

bool ble_radar_service_tx_enabled(void)
{
    return tx_enabled;
}
