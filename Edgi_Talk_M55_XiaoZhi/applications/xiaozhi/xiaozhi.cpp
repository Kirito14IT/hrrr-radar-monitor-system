/*
 * Copyright (c) 2006-2025, RT-Thread Development Team
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * Change Logs:
 * Date           Author       Notes
 * 2025-12-14     RT-Thread    First version
 */

#include "xiaozhi.h"
#include "wake_word/xiaozhi_wakeword.h"
#include "audio_capture_hub.h"
#include "../backend_target_config.h"
#include <lwip/apps/websocket_client.h>
#include <cJSON.h>
#include <netdev.h>
#include <webclient.h>
#include <wavplayer.h>
#include <string.h>
#include <stdio.h>

#define DBG_TAG "xz.ws"
#define DBG_LVL DBG_LOG
#include <rtdbg.h>

/* Configuration constants */
#define MAX_CLIENT_ID_LEN 40
#define MAX_MAC_ADDR_LEN 20
#define WEBSOCKET_RECONNECT_DELAY_MS 5000
#define WEBSOCKET_CONNECTION_TIMEOUT_MS 5000
#define NETWORK_CHECK_DELAY_MS 500
#define RETRY_DELAY_BASE_MS 1000
#define RETRY_DELAY_INCREMENT_MS 200
#define TTS_STOP_DELAY_MS 500
#define BUTTON_DEBOUNCE_MS 20
#define WAKEWORD_INIT_FLAG_RESET 0
#define TTS_SENTENCE_TIMEOUT_MS 6000
#define EMERGENCY_POST_TIMEOUT_MS 3000
#define EMERGENCY_REPORT_THREAD_STACK 4096
#define EMERGENCY_REPORT_THREAD_PRIORITY 18
#define EMERGENCY_SOURCE_DEFAULT "xiaozhi_voice_board"
#define EDGI_HEARTBEAT_INTERVAL_MS 5000
#define EDGI_HEARTBEAT_THREAD_STACK 4096
#define EDGI_HEARTBEAT_THREAD_PRIORITY 20

#ifndef DB_SEND_TARGET_IP
#define DB_SEND_TARGET_IP "192.168.0.102"
#endif

#ifndef DB_SEND_TARGET_PORT
#define DB_SEND_TARGET_PORT 8081
#endif

typedef struct
{
    char body[640];
} emergency_report_msg_t;

/* Global application state */
xiaozhi_app_t g_app =
    {
        .xiaozhi_tid = RT_NULL,
        .client_id = "af7ac552-9991-4b31-b660-683b210ae95f",
        .websocket_reconnect_flag = 0,
        .iot_initialized = 0,
        .last_reconnect_time = 0,
        .mac_address_string = {0},
        .client_id_string = {0},
        .ws = {0},
        .state = kDeviceStateUnknown,
        .operating_mode = kXzOperatingModeGuard,
        .button_event = RT_NULL,
        .wakeword_initialized_session = 0,
        .multi_turn_conversation_enabled = RT_TRUE,
        .tts_sentence_end_timer = RT_NULL,
        .tts_stop_workqueue = RT_NULL,
        .pending_listen_start = RT_FALSE,
        .pending_play_wake_sound = RT_FALSE};

static volatile rt_bool_t g_snore_guard_enabled = RT_FALSE;
static rt_thread_t g_edgi_heartbeat_tid = RT_NULL;
static volatile rt_bool_t g_edgi_heartbeat_running = RT_FALSE;
static void xz_prepare_voice_input(void);
static void xz_restore_idle_audio(void);
static int xz_apply_guard_mode(void);
static int xz_apply_dialogue_mode(rt_bool_t play_wake_sound);
static void xz_start_edgi_heartbeat(void);

#include "ui/xiaozhi_ui.h"
#include "iot/iot_c_api.h"
#include "mcp/mcp_api.h"

/* Wake word detection callback - optimized for quick response */
void xz_wakeword_detected_callback(const char *wake_word, float confidence)
{
    if (g_app.operating_mode != kXzOperatingModeDialogue)
    {
        LOG_I("Wake word ignored while guard mode is active");
        return;
    }

    LOG_D("Wake word detected: %s (confidence: %.2f%%)", wake_word, confidence * 100);

    /* Update UI to show wake word detection */
    xiaozhi_ui_chat_status("   唤醒");
    xiaozhi_ui_chat_output("我在，请说...");

    /* Play wake sound */
    xz_play_wake_sound();

    /* Handle interruption if currently speaking */
    if (g_app.state == kDeviceStateSpeaking)
    {
        LOG_D("Wake word detected during speaking - interrupting");
        xz_speaker(0);
        rt_bool_t in_listening = (g_app.state == kDeviceStateListening) || xz_mic_is_enabled();
        if (!in_listening && g_app.state != kDeviceStateSpeaking)
        {
            g_app.state = kDeviceStateIdle;
        }
    }
    else if (g_app.state == kDeviceStateListening)
    {
        LOG_D("Wake word detected during listening - restarting");
        /* Stop current listening session */
        xz_mic(0);
        ws_send_listen_stop(&g_app.ws.clnt, g_app.ws.session_id);
        g_app.state = kDeviceStateIdle;
    }

    /* Ensure we have a WebSocket connection */
    if (!g_app.ws.is_connected)
    {
        LOG_D("Wake word detected but not connected, initiating connection...");
        xiaozhi_ui_chat_status("   连接中");
        xiaozhi_ui_chat_output("正在连接...");
        g_app.pending_listen_start = RT_TRUE;
        g_app.pending_play_wake_sound = RT_FALSE;
        reconnect_websocket();

        /* Use a shorter wait time with periodic checks for better responsiveness */
        int wait_count = 0;
        while (!g_app.ws.is_connected && wait_count < 20) // Max 2 seconds
        {
            rt_thread_mdelay(100);
            wait_count++;
        }

        if (!g_app.ws.is_connected)
        {
            LOG_E("Failed to connect after wake word detection");
            xiaozhi_ui_chat_status("   连接失败");
            xiaozhi_ui_chat_output("请稍后再试");
            return;
        }
    }

    /* Ensure session is ready before starting listening */
    if (g_app.ws.session_id[0] == '\0')
    {
        LOG_D("Session not ready after wake word detection, deferring listen start");
        g_app.pending_listen_start = RT_TRUE;
        g_app.pending_play_wake_sound = RT_FALSE;
        if (xz_wakeword_is_enabled())
        {
            xz_wakeword_stop();
        }
        return;
    }

    /* Start listening mode */
    LOG_D("Starting conversation after wake word detection");
    g_app.state = kDeviceStateListening;
    g_app.pending_listen_start = RT_FALSE;
    g_app.pending_play_wake_sound = RT_FALSE;

    /* Pause wake-word inference during the cloud conversation. */
    if (xz_wakeword_is_enabled())
    {
        LOG_D("Pausing wake word detection during conversation");
        xz_wakeword_stop();
    }

    /* Snore detection keeps its independent audio-hub subscription. */
    xz_prepare_voice_input();

    /* Enable microphone */
    xz_mic(1);

    /* Send listen start message to server */
    if (ws_send_listen_start(&g_app.ws.clnt, g_app.ws.session_id, kListeningModeAutoStop))
    {
        /* Update UI */
        xiaozhi_ui_chat_status("   聆听中");
        xiaozhi_ui_chat_output("聆听中...");
    }
    else
    {
        LOG_W("Listen start failed after wake word detection");
        g_app.state = kDeviceStateIdle;
        xz_mic(0);
        xiaozhi_ui_chat_status("   就绪");
        xiaozhi_ui_chat_output("就绪");
        xz_restore_idle_audio();
    }
}

/* TTS sentence end timeout handler */
static void tts_sentence_end_timeout(void *parameter)
{
    uint32_t tick = rt_tick_get();
    LOG_D("TTS sentence end timeout at tick=%u, sending event to restart listening for multi-turn conversation", tick);

    /* Send event to button thread to handle the restart in non-ISR context */
    rt_err_t ev_ret = rt_event_send(g_app.button_event, TIMEOUT_EVENT);
    if (ev_ret != RT_EOK)
    {
        LOG_W("rt_event_send returned %d from timer callback", ev_ret);
    }
}

/* TTS stop delayed restart work function */
static void tts_stop_restart_listening(struct rt_work *work, void *work_data)
{
    if (g_app.operating_mode != kXzOperatingModeDialogue)
    {
        LOG_I("Skipping TTS restart outside dialogue mode");
        return;
    }

    LOG_D("TTS stop delayed restart: restarting listening mode");

    /* Multi-turn conversation: keep listening without restarting wake word detection */
    g_app.state = kDeviceStateListening;
    xz_prepare_voice_input();
    xz_mic(1);

    /* Try to send listen start */
    if (ws_send_listen_start(&g_app.ws.clnt, g_app.ws.session_id, kListeningModeAutoStop))
    {
        xiaozhi_ui_chat_status("   聆听中");
        xiaozhi_ui_chat_output("聆听中...");
    }
    else
    {
        LOG_W("Listen start failed in TTS stop delayed restart");
        /* Reset state if failed */
        g_app.state = kDeviceStateIdle;
        xz_mic(0);
        xiaozhi_ui_chat_status("   就绪");
        xz_restore_idle_audio();
        xiaozhi_ui_chat_output("就绪");
    }
}

/* Static work item for TTS stop restart */
static struct rt_work tts_stop_work;

/* Static timer for TTS stop delay */
static rt_timer_t tts_stop_delay_timer = RT_NULL;

/* TTS stop delay timer callback */
static void tts_stop_delay_timeout(void *parameter)
{
    LOG_D("TTS stop delay timeout, submitting work to restart listening");

    /* Submit work to restart listening */
    if (g_app.tts_stop_workqueue)
    {
        rt_workqueue_submit_work(g_app.tts_stop_workqueue, &tts_stop_work, 0);
    }
    else
    {
        LOG_W("Workqueue not available in timer callback");
        /* Fallback */
        tts_stop_restart_listening(&tts_stop_work, RT_NULL);
    }
}

/* State consistency check function */
static void ensure_state_consistency(void)
{
    /* If listening but disconnected, handle multi-turn logic */
    if (g_app.state == kDeviceStateListening && !g_app.ws.is_connected)
    {
        LOG_W("Inconsistent state detected: Listening but disconnected, fixing...\n");
        xz_mic(0);

        if (g_app.multi_turn_conversation_enabled)
        {
            /* Multi-turn: try reconnect instead of restarting wake word */
            LOG_D("Multi-turn conversation enabled, attempting to reconnect after disconnection");
            g_app.state = kDeviceStateIdle;
            xiaozhi_ui_chat_status("   连接中");
            xiaozhi_ui_chat_output("重新连接中...");
            reconnect_websocket();
        }
        else
        {
            /* Single-turn: reset to idle and restart wake word */
            g_app.state = kDeviceStateIdle;
            xiaozhi_ui_chat_status("   就绪");
            xiaozhi_ui_chat_output("就绪");

            xz_restore_idle_audio();
        }
    }

    /* If speaking but disconnected, reset too */
    if (g_app.state == kDeviceStateSpeaking && !g_app.ws.is_connected)
    {
        LOG_W("Inconsistent state detected: Speaking but disconnected, fixing...\n");
        xz_speaker(0);
        xz_mic(0);
        g_app.state = kDeviceStateUnknown;
        xiaozhi_ui_chat_status("   休眠中");
        xiaozhi_ui_chat_output("等待唤醒");

        xz_restore_idle_audio();
    }

    /* Optimize: if connected but state unknown, set to idle */
    if (g_app.state == kDeviceStateUnknown && g_app.ws.is_connected && g_app.ws.session_id[0] != '\0')
    {
        LOG_D("WebSocket connected with valid session, updating state to Idle\n");
        g_app.state = kDeviceStateIdle;
        xiaozhi_ui_chat_status("   就绪");
        xiaozhi_ui_chat_output("就绪");

        xz_restore_idle_audio();
    }
}

/* Helper functions */
char *get_mac_address(void)
{
    struct netdev *netdev = netdev_get_by_name("w0");
    if (netdev == RT_NULL)
    {
        LOG_E("Cannot find netdev w0");
        return "";
    }

    if (netdev->hwaddr_len != 6)
    {
        LOG_E("Invalid MAC address length: %d", netdev->hwaddr_len);
        return "";
    }

    rt_snprintf(g_app.mac_address_string, sizeof(g_app.mac_address_string),
                "%02x:%02x:%02x:%02x:%02x:%02x",
                netdev->hwaddr[0], netdev->hwaddr[1], netdev->hwaddr[2],
                netdev->hwaddr[3], netdev->hwaddr[4], netdev->hwaddr[5]);
    return g_app.mac_address_string;
}

char *get_client_id(void)
{
    if (g_app.client_id_string[0] == '\0')
    {
        uint32_t tick = rt_tick_get();
        uint8_t hash_input[64];
        uint8_t hash_output[32];
        int input_len = rt_snprintf((char *)hash_input, sizeof(hash_input),
                                    "%s%u", g_app.client_id, tick);

        for (int i = 0; i < 32; i++)
        {
            hash_output[i] = (uint8_t)(hash_input[i % input_len] ^ (tick >> (i % 32)));
        }

        int j = 0;
        for (int i = 0; i < 16; i++)
        {
            if (i == 4 || i == 6 || i == 8 || i == 10)
            {
                g_app.client_id_string[j++] = '-';
            }
            g_app.client_id_string[j++] = "0123456789abcdef"[hash_output[i] >> 4];
            g_app.client_id_string[j++] = "0123456789abcdef"[hash_output[i] & 0xF];
        }
        g_app.client_id_string[j] = '\0';
        LOG_D("Generated Client ID: %s", g_app.client_id_string);
    }
    return g_app.client_id_string;
}

void xz_button_callback(void *arg)
{
    static rt_tick_t last_press_tick = 0;

    if (CYBSP_BTN_PRESSED == Cy_GPIO_Read(CYBSP_USER_BTN_PORT, CYBSP_USER_BTN_PIN))
    {
        const rt_tick_t now = rt_tick_get();
        if (last_press_tick != 0 &&
            (rt_tick_t)(now - last_press_tick) < rt_tick_from_millisecond(500))
        {
            return;
        }
        last_press_tick = now;
        rt_event_send(g_app.button_event, BUTTON_EVENT_PRESSED);
    }
#ifndef ExBoard_Voice
    else
    {
        rt_event_send(g_app.button_event, BUTTON_EVENT_RELEASED);
    }
#endif
}

void xz_event_thread_entry(void *param)
{
    rt_uint32_t evt;
    while (1)
    {
        rt_event_recv(g_app.button_event,
                      BUTTON_EVENT_PRESSED | BUTTON_EVENT_RELEASED | TIMEOUT_EVENT |
                          MODE_EVENT_GUARD | MODE_EVENT_DIALOGUE,
                      RT_EVENT_FLAG_OR | RT_EVENT_FLAG_CLEAR,
                      RT_WAITING_FOREVER, &evt);

        /* First ensure state consistency */
        ensure_state_consistency();

        if (evt & MODE_EVENT_GUARD)
        {
            (void)xz_apply_guard_mode();
            continue;
        }
        if (evt & MODE_EVENT_DIALOGUE)
        {
            (void)xz_apply_dialogue_mode(RT_TRUE);
            continue;
        }

        if (evt & BUTTON_EVENT_PRESSED)
        {
            if (g_app.operating_mode == kXzOperatingModeGuard)
            {
                (void)xz_apply_dialogue_mode(RT_TRUE);
                continue;
            }

            if (!g_app.ws.is_connected)
            {
                g_app.pending_listen_start = RT_TRUE;
                g_app.pending_play_wake_sound = RT_TRUE;

                /* Check if reconnecting */
                if (g_app.websocket_reconnect_flag == 1)
                {
                    LOG_D("Reconnection already in progress, ignoring button press\n");
                    xiaozhi_ui_chat_status("   连接中");
                    xiaozhi_ui_chat_output("仍在连接中...");
                    continue;
                }

                LOG_D("Device not connected, initiating wake up...\n");
                xiaozhi_ui_chat_status("   连接中");
                xiaozhi_ui_chat_output("正在连接小智...");
                reconnect_websocket();
            }
            else
            {
                /* WebSocket connected, can handle requests */
                /* If unknown state but connected, treat as idle */
                if (g_app.state == kDeviceStateSpeaking)
                {
                    LOG_D("Speaking aborted by user\n");
                    xz_speaker(0);
                }

                /* Press-to-talk: check if already listening */
                if (g_app.state != kDeviceStateListening)
                {
                    LOG_D("Starting listening mode - press once to talk\n");

                    g_app.pending_listen_start = RT_FALSE;
                    g_app.pending_play_wake_sound = RT_FALSE;

                    /* Play wake sound for button wake-up */
                    xz_play_wake_sound();

                    xiaozhi_ui_chat_status("   聆听中");
                    xiaozhi_ui_chat_output("聆听中...");
#ifdef LX_LITEGFX_VGLITE_ENABLE
                    extern void qday_show_emoji_by_rtt_info(int index);
                    qday_show_emoji_by_rtt_info(100);
#endif
                    /* Pause wake word detection during button-activated recording */
                    if (xz_wakeword_is_enabled())
                    {
                        LOG_D("Temporarily pausing wake word detection for button recording");
                        xz_wakeword_stop();
                    }

                    /* Use auto-stop mode, let system detect speech end */
                    xz_prepare_voice_input();
                    xz_mic(1);
                    if (!ws_send_listen_start(&g_app.ws.clnt, g_app.ws.session_id,
                                              kListeningModeAutoStop))
                    {
                        LOG_W("Listen start failed after user button press");
                        g_app.state = kDeviceStateIdle;
                        xz_mic(0);
                        xz_restore_idle_audio();
                    }
                }
                else
                {
                    LOG_D("Already in listening mode\n");
                }
            }
        }
        else if (evt & BUTTON_EVENT_RELEASED)
        {
            /* Press-to-talk: no need to stop on release, auto-handle */
            LOG_D("Button released - letting system auto-detect speech end\n");
        }
        else if (evt & TIMEOUT_EVENT)
        {
            /* Handle TTS sentence end timeout for multi-turn conversation */
            LOG_I("Processing TTS sentence end timeout event");

            /* Only restart listening if we're still in speaking state, multi-turn is enabled, and connected */
            if (g_app.operating_mode == kXzOperatingModeDialogue &&
                g_app.state == kDeviceStateSpeaking &&
                g_app.multi_turn_conversation_enabled && g_app.ws.is_connected)
            {
                g_app.state = kDeviceStateListening;
                xz_prepare_voice_input();
                xz_mic(1);

                /* Try to send listen start */
                if (ws_send_listen_start(&g_app.ws.clnt, g_app.ws.session_id, kListeningModeAutoStop))
                {
                    xiaozhi_ui_chat_status("   聆听中");
                    xiaozhi_ui_chat_output("聆听中...");
                    LOG_D("Listen start successful after sentence end timeout");
                }
                else
                {
                    LOG_W("Listen start failed after sentence end timeout");
                    /* Reset state if failed */
                    g_app.state = kDeviceStateIdle;
                    xz_mic(0);
                    xz_restore_idle_audio();
                }
            }
            else if (!g_app.ws.is_connected)
            {
                LOG_D("Skipping timeout restart - WebSocket disconnected");
            }
        }
    }
}

void xz_button_init(void)
{
    rt_pin_mode(BUTTON_PIN, PIN_MODE_INPUT_PULLUP);
    rt_pin_write(BUTTON_PIN, PIN_HIGH);
    g_app.button_event = rt_event_create("btn_evt", RT_IPC_FLAG_FIFO);
    RT_ASSERT(g_app.button_event != RT_NULL);

    rt_pin_attach_irq(BUTTON_PIN, PIN_IRQ_MODE_RISING_FALLING,
                      xz_button_callback, NULL);
    rt_pin_irq_enable(BUTTON_PIN, RT_TRUE);
    LOG_D("[Init] Button handler ready\n");
}

void xz_event_init(void)
{
    rt_thread_t tid = rt_thread_create("event_thread",
                                       xz_event_thread_entry,
                                       RT_NULL, 3 * 1024, 7, 10);
    RT_ASSERT(tid != RT_NULL);
    if (rt_thread_startup(tid) != RT_EOK)
    {
        LOG_E("Button thread startup failed\n");
        return;
    }
}

/* WebSocket communication functions */
rt_bool_t ws_send_listen_start(void *ws, char *session_id, enum ListeningMode mode)
{
    static const char *mode_str[] = {"auto_stop", "manual_stop", "always_on"};
    static char message[256];
    rt_snprintf(message, 256,
                "{\"session_id\":\"%s\",\"type\":\"listen\",\"state\":\"start\","
                "\"mode\":\"%s\"}",
                session_id, mode_str[mode]);

    if (g_app.ws.is_connected && g_app.ws.ws_write_mutex)
    {
        if (rt_mutex_take(g_app.ws.ws_write_mutex, RT_WAITING_NO) == RT_EOK)
        {
            if (g_app.ws.is_connected)
            {
                err_t result = wsock_write((wsock_state_t *)ws, message, strlen(message), OPCODE_TEXT);
                LOG_D("ws_send_listen_start result: %d\n", result);
                if (result == ERR_OK)
                {
                    /* Update state only on success, keep sync */
                    g_app.state = kDeviceStateListening;
                    LOG_D("State updated to Listening after successful send\n");
                    rt_mutex_release(g_app.ws.ws_write_mutex);
                    return RT_TRUE;
                }
                else
                {
                    LOG_E("Failed to send listen start message: %d\n", result);
                    if (result == ERR_CLSD || result == ERR_RST)
                    {
                        g_app.ws.is_connected = 0;
                    }
                    rt_mutex_release(g_app.ws.ws_write_mutex);
                    return RT_FALSE;
                }
            }
            rt_mutex_release(g_app.ws.ws_write_mutex);
            return RT_FALSE;
        }
        else
        {
            LOG_D("WebSocket write busy, cannot send listen start\n");
            return RT_FALSE;
        }
    }
    else
    {
        LOG_E("WebSocket not connected, cannot send listen start\n");
        return RT_FALSE;
    }
}

void ws_send_listen_stop(void *ws, char *session_id)
{
    static char message[256];
    rt_snprintf(message, 256,
                "{\"session_id\":\"%s\",\"type\":\"listen\",\"state\":\"stop\"}",
                session_id);

    if (g_app.ws.is_connected && g_app.ws.ws_write_mutex)
    {
        if (rt_mutex_take(g_app.ws.ws_write_mutex, RT_WAITING_NO) == RT_EOK)
        {
            if (g_app.ws.is_connected)
            {
                err_t result = wsock_write((wsock_state_t *)ws, message, strlen(message), OPCODE_TEXT);
                LOG_D("ws_send_listen_stop result: %d\n", result);
                if (result == ERR_OK)
                {
                    /* Update state only on success, keep sync */
                    g_app.state = kDeviceStateIdle;
                    LOG_D("State updated to Idle after successful send\n");

                    xz_restore_idle_audio();
                }
                else
                {
                    LOG_E("Failed to send listen stop message: %d\n", result);
                    if (result == ERR_CLSD || result == ERR_RST)
                    {
                        g_app.ws.is_connected = 0;
                    }
                }
            }
            rt_mutex_release(g_app.ws.ws_write_mutex);
        }
        else
        {
            LOG_D("WebSocket write busy, cannot send listen stop\n");
        }
    }
    else
    {
        LOG_D("WebSocket not connected, cannot send listen stop\n");
        /* Even if disconnected, ensure correct state */
        g_app.state = kDeviceStateIdle;
    }
}

void ws_send_hello(void *ws)
{
    if (g_app.ws.is_connected && g_app.ws.ws_write_mutex)
    {
        if (rt_mutex_take(g_app.ws.ws_write_mutex, RT_WAITING_NO) == RT_EOK)
        {
            if (g_app.ws.is_connected)
            {
                wsock_write((wsock_state_t *)ws, HELLO_MESSAGE,
                            strlen(HELLO_MESSAGE), OPCODE_TEXT);
            }
            rt_mutex_release(g_app.ws.ws_write_mutex);
        }
    }
    else
    {
        // LOG_E("websocket is not connected\n");
    }
}

static const char *xz_find_emergency_phrase(const char *text)
{
    static const char *keywords[] = {
        "救命",
        "帮帮我",
        "需要帮助",
        "快来人",
        "我不舒服",
        "喘不过气",
        "胸口痛",
        "摔倒了",
        "头晕",
        "很难受",
    };

    if (!text)
    {
        return RT_NULL;
    }

    for (size_t i = 0; i < sizeof(keywords) / sizeof(keywords[0]); ++i)
    {
        if (strstr(text, keywords[i]) != RT_NULL)
        {
            return keywords[i];
        }
    }

    return RT_NULL;
}

static rt_thread_t g_emergency_alarm_tid = RT_NULL;
static rt_tick_t g_emergency_alarm_last_tick = 0;
static volatile rt_bool_t g_emergency_alarm_cancelled = RT_FALSE;
static volatile rt_bool_t g_emergency_resolve_in_progress = RT_FALSE;
static char g_active_emergency_source[64] = EMERGENCY_SOURCE_DEFAULT;
static rt_thread_t g_care_alarm_tid = RT_NULL;
static rt_tick_t g_care_alarm_last_tick = 0;
static rt_thread_t g_alarm_clock_tid = RT_NULL;
static volatile rt_bool_t g_alarm_clock_cancelled = RT_FALSE;

static void xz_care_alarm_thread(void *parameter)
{
    (void)parameter;
    const int previous_volume = wavplayer_volume_get();

    xz_speaker(0);
    audio_capture_hub_suppress_snore(RT_TRUE);
    wavplayer_volume_set(35);

    for (int repeat = 0; repeat < 2; ++repeat)
    {
        if (g_emergency_alarm_tid != RT_NULL)
        {
            break;
        }

        if (wavplayer_play((char *)"/webnet/ding.wav") != 0)
        {
            LOG_W("care alarm: failed to play alert sound");
            break;
        }

        const rt_tick_t deadline = rt_tick_get() + rt_tick_from_millisecond(2500);
        while (wavplayer_state_get() != PLAYER_STATE_STOPED &&
               (rt_int32_t)(deadline - rt_tick_get()) > 0)
        {
            if (g_emergency_alarm_tid != RT_NULL)
            {
                wavplayer_stop();
                break;
            }
            rt_thread_mdelay(20);
        }

        if (repeat == 0)
        {
            rt_thread_mdelay(1200);
        }
    }

    if (g_emergency_alarm_tid == RT_NULL)
    {
        wavplayer_volume_set(previous_volume);
    }
    audio_capture_hub_suppress_snore(RT_FALSE);
    LOG_I("care alarm: local audible reminder completed");
    g_care_alarm_tid = RT_NULL;
}

void xz_trigger_care_alarm(void)
{
    const rt_tick_t now = rt_tick_get();
    const rt_tick_t cooldown = rt_tick_from_millisecond(30000);

    if (g_emergency_alarm_tid != RT_NULL || g_care_alarm_tid != RT_NULL)
    {
        LOG_I("care alarm: another alarm is already playing");
        return;
    }
    if (g_care_alarm_last_tick != 0 &&
        (rt_tick_t)(now - g_care_alarm_last_tick) < cooldown)
    {
        LOG_I("care alarm: duplicate trigger ignored");
        return;
    }

    g_care_alarm_last_tick = now;
    g_care_alarm_tid = rt_thread_create(
        "carealm",
        xz_care_alarm_thread,
        RT_NULL,
        2048,
        18,
        10);
    if (g_care_alarm_tid == RT_NULL)
    {
        LOG_E("care alarm: thread create failed");
        return;
    }

    rt_thread_startup(g_care_alarm_tid);
}

static void xz_emergency_alarm_thread(void *parameter)
{
    (void)parameter;
    const int previous_volume = wavplayer_volume_get();

    xz_speaker(0);
    audio_capture_hub_suppress_snore(RT_TRUE);
    wavplayer_volume_set(90);

    for (int repeat = 0; repeat < 8; ++repeat)
    {
        if (g_emergency_alarm_cancelled)
        {
            break;
        }

        if (wavplayer_play((char *)"/webnet/ding.wav") != 0)
        {
            LOG_W("emergency alarm: failed to play alert sound");
            break;
        }

        const rt_tick_t deadline = rt_tick_get() + rt_tick_from_millisecond(2500);
        while (wavplayer_state_get() != PLAYER_STATE_STOPED &&
               (rt_int32_t)(deadline - rt_tick_get()) > 0)
        {
            if (g_emergency_alarm_cancelled)
            {
                wavplayer_stop();
                break;
            }
            rt_thread_mdelay(20);
        }
        rt_thread_mdelay(120);
    }

    wavplayer_volume_set(previous_volume);
    audio_capture_hub_suppress_snore(RT_FALSE);
    LOG_W("emergency alarm: local audible alert completed");
    g_emergency_alarm_tid = RT_NULL;
}

static void xz_trigger_emergency_alarm(void)
{
    const rt_tick_t now = rt_tick_get();
    const rt_tick_t cooldown = rt_tick_from_millisecond(8000);

    if (g_care_alarm_tid != RT_NULL)
    {
        wavplayer_stop();
    }
    if (g_emergency_alarm_tid != RT_NULL)
    {
        LOG_I("emergency alarm: already playing");
        return;
    }
    if (g_emergency_alarm_last_tick != 0 &&
        (rt_tick_t)(now - g_emergency_alarm_last_tick) < cooldown)
    {
        LOG_I("emergency alarm: duplicate trigger ignored");
        return;
    }

    g_emergency_alarm_last_tick = now;
    g_emergency_alarm_cancelled = RT_FALSE;
    g_emergency_alarm_tid = rt_thread_create(
        "sosalm",
        xz_emergency_alarm_thread,
        RT_NULL,
        2048,
        17,
        10);
    if (g_emergency_alarm_tid == RT_NULL)
    {
        LOG_E("emergency alarm: thread create failed");
        return;
    }

    rt_thread_startup(g_emergency_alarm_tid);
}

static void xz_alarm_clock_thread(void *parameter)
{
    (void)parameter;
    const int previous_volume = wavplayer_volume_get();

    xz_speaker(0);
    audio_capture_hub_suppress_snore(RT_TRUE);
    wavplayer_volume_set(96);
    for (int repeat = 0; repeat < 24 && !g_alarm_clock_cancelled; ++repeat)
    {
        if (wavplayer_play((char *)"/webnet/ding.wav") != 0)
        {
            LOG_W("alarm clock: failed to play alert sound");
            break;
        }

        const rt_tick_t deadline = rt_tick_get() + rt_tick_from_millisecond(2500);
        while (wavplayer_state_get() != PLAYER_STATE_STOPED &&
               (rt_int32_t)(deadline - rt_tick_get()) > 0)
        {
            if (g_alarm_clock_cancelled)
            {
                wavplayer_stop();
                break;
            }
            rt_thread_mdelay(20);
        }
        rt_thread_mdelay(250);
    }

    wavplayer_volume_set(previous_volume);
    audio_capture_hub_suppress_snore(RT_FALSE);
    g_alarm_clock_tid = RT_NULL;
    xiaozhi_ui_hide_alarm_ring();
}

void xz_trigger_alarm_clock(void)
{
    if (g_alarm_clock_tid != RT_NULL || g_emergency_alarm_tid != RT_NULL)
    {
        return;
    }

    g_alarm_clock_cancelled = RT_FALSE;
    g_alarm_clock_tid = rt_thread_create(
        "clockalm",
        xz_alarm_clock_thread,
        RT_NULL,
        1536,
        18,
        10);
    if (g_alarm_clock_tid != RT_NULL)
    {
        rt_thread_startup(g_alarm_clock_tid);
    }
}

void xz_stop_alarm_clock(void)
{
    g_alarm_clock_cancelled = RT_TRUE;
    if (g_alarm_clock_tid != RT_NULL)
    {
        wavplayer_stop();
    }
}

static void xz_json_escape(char *dst, size_t dst_size, const char *src)
{
    if (!dst || dst_size == 0)
    {
        return;
    }

    size_t out = 0;
    if (!src)
    {
        dst[0] = '\0';
        return;
    }

    for (size_t i = 0; src[i] != '\0' && out + 1 < dst_size; ++i)
    {
        unsigned char ch = (unsigned char)src[i];
        if ((ch == '"' || ch == '\\') && out + 2 < dst_size)
        {
            dst[out++] = '\\';
            dst[out++] = (char)ch;
        }
        else if (ch < 0x20)
        {
            dst[out++] = ' ';
        }
        else
        {
            dst[out++] = (char)ch;
        }
    }
    dst[out] = '\0';
}

static void xz_set_active_emergency_source(const char *source)
{
    const char *effective_source =
        (source && source[0]) ? source : EMERGENCY_SOURCE_DEFAULT;

    rt_strncpy(g_active_emergency_source,
               effective_source,
               sizeof(g_active_emergency_source) - 1);
    g_active_emergency_source[sizeof(g_active_emergency_source) - 1] = '\0';
}

static int xz_post_json_to_backend(const char *path, const char *json_body)
{
    if (!path || !json_body)
    {
        return -1;
    }

    char backend_host[BACKEND_TARGET_HOST_LEN] = {0};
    int backend_port = DB_SEND_TARGET_PORT;
    backend_target_get(DB_SEND_TARGET_IP, DB_SEND_TARGET_PORT,
                       backend_host, sizeof(backend_host), &backend_port);

    char url[128];
    int url_len = snprintf(url, sizeof(url), "http://%s:%d%s", backend_host, backend_port, path);
    if (url_len <= 0 || url_len >= (int)sizeof(url))
    {
        LOG_W("backend: url too long for %s:%d path=%s",
              backend_host,
              backend_port,
              path);
        return -2;
    }

    const size_t body_len = strlen(json_body);
    struct webclient_session *session = webclient_session_create(256);
    if (!session)
    {
        return -3;
    }

    webclient_set_timeout(session, EMERGENCY_POST_TIMEOUT_MS);
    webclient_header_fields_add(session, "Content-Type: application/json\r\n");
    webclient_header_fields_add(session, "Content-Length: %u\r\n", (unsigned)body_len);

    LOG_I("backend: posting %u bytes to %s", (unsigned)body_len, url);
    int status = webclient_post(session, url, json_body, body_len);
    webclient_close(session);
    if (status < 200 || status >= 300)
    {
        LOG_W("backend: post %s failed, status=%d", url, status);
        return -4;
    }

    LOG_I("backend: post %s ok", path);
    return 0;
}

static void xz_edgi_heartbeat_thread(void *parameter)
{
    (void)parameter;
    LOG_I("edgi heartbeat: thread started (interval=%d ms)", EDGI_HEARTBEAT_INTERVAL_MS);

    while (g_edgi_heartbeat_running)
    {
        const rt_bool_t guard_mode =
            (g_app.operating_mode == kXzOperatingModeGuard) ? RT_TRUE : RT_FALSE;
        const rt_bool_t keyword_online =
            (g_app.ws.is_connected && g_app.ws.session_id[0] != '\0') ? RT_TRUE : RT_FALSE;
        const char *mode = guard_mode ? "guard" : "dialogue";

        char body[192];
        int body_len = snprintf(body,
                                sizeof(body),
                                "{\"source\":\"xiaozhi_board\","
                                "\"mode\":\"%s\","
                                "\"keyword_online\":%s,"
                                "\"snore_guard_enabled\":%s}",
                                mode,
                                keyword_online ? "true" : "false",
                                g_snore_guard_enabled ? "true" : "false");
        if (body_len > 0 && body_len < (int)sizeof(body))
        {
            if (xz_post_json_to_backend("/hardware/edgi-heartbeat", body) != 0)
            {
                LOG_W("edgi heartbeat: post failed");
            }
        }

        rt_thread_mdelay(EDGI_HEARTBEAT_INTERVAL_MS);
    }

    LOG_I("edgi heartbeat: thread exiting");
    g_edgi_heartbeat_tid = RT_NULL;
}

static void xz_start_edgi_heartbeat(void)
{
    if (g_edgi_heartbeat_running || g_edgi_heartbeat_tid)
    {
        return;
    }

    g_edgi_heartbeat_running = RT_TRUE;
    g_edgi_heartbeat_tid = rt_thread_create("edgi_hb",
                                            xz_edgi_heartbeat_thread,
                                            RT_NULL,
                                            EDGI_HEARTBEAT_THREAD_STACK,
                                            EDGI_HEARTBEAT_THREAD_PRIORITY,
                                            10);
    if (!g_edgi_heartbeat_tid)
    {
        g_edgi_heartbeat_running = RT_FALSE;
        LOG_E("edgi heartbeat: create thread failed");
        return;
    }

    rt_thread_startup(g_edgi_heartbeat_tid);
}

static void xz_emergency_report_thread(void *parameter)
{
    emergency_report_msg_t *msg = (emergency_report_msg_t *)parameter;

    if (!msg)
    {
        return;
    }

    if (xz_post_json_to_backend("/emergency", msg->body) != 0)
    {
        LOG_W("emergency: report failed");
    }

    rt_free(msg);
}

static void xz_report_emergency_event(const char *source,
                                      const char *phrase,
                                      const char *transcript)
{
    char escaped_source[64];
    char escaped_phrase[96];
    char escaped_transcript[384];
    char escaped_device[64];
    xz_json_escape(escaped_source, sizeof(escaped_source),
                   source ? source : EMERGENCY_SOURCE_DEFAULT);
    xz_json_escape(escaped_phrase, sizeof(escaped_phrase), phrase);
    xz_json_escape(escaped_transcript, sizeof(escaped_transcript), transcript);
    xz_json_escape(escaped_device, sizeof(escaped_device), get_client_id());

    char body[640];
    int body_len = snprintf(body, sizeof(body),
                            "{\"source\":\"%s\","
                            "\"phrase\":\"%s\","
                            "\"transcript\":\"%s\","
                            "\"device_id\":\"%s\"}",
                            escaped_source,
                            escaped_phrase,
                            escaped_transcript,
                            escaped_device);
    if (body_len <= 0 || body_len >= (int)sizeof(body))
    {
        LOG_W("emergency: body too long");
        return;
    }

    emergency_report_msg_t *msg = (emergency_report_msg_t *)rt_malloc(sizeof(emergency_report_msg_t));
    if (!msg)
    {
        LOG_W("emergency: alloc report message failed");
        return;
    }

    rt_strncpy(msg->body, body, sizeof(msg->body) - 1);
    msg->body[sizeof(msg->body) - 1] = '\0';

    rt_thread_t tid = rt_thread_create("sos_report",
                                      xz_emergency_report_thread,
                                      msg,
                                      EMERGENCY_REPORT_THREAD_STACK,
                                      EMERGENCY_REPORT_THREAD_PRIORITY,
                                      10);
    if (tid == RT_NULL)
    {
        LOG_W("emergency: report thread create failed");
        rt_free(msg);
        return;
    }

    rt_thread_startup(tid);
}

void xz_trigger_emergency_event(const char *source,
                                const char *phrase,
                                const char *transcript)
{
    const char *event_source =
        (source && source[0]) ? source : EMERGENCY_SOURCE_DEFAULT;
    const rt_bool_t is_imu_emergency =
        strcmp(event_source, "xiaozhi_imu_board") == 0;
    const char *display_phrase = phrase ? phrase : "检测到异常情况";
    const char *event_transcript = transcript ? transcript : display_phrase;
    if (is_imu_emergency)
    {
        display_phrase = "设备跌落";
        event_transcript = "IMU检测到开发板低重力或撞击，疑似设备被打翻";
    }

    xz_set_active_emergency_source(event_source);
    g_emergency_resolve_in_progress = RT_FALSE;
    LOG_W("emergency event triggered: source=%s phrase=%s",
          event_source,
          display_phrase);
    xiaozhi_ui_show_emergency(display_phrase);
    xz_trigger_emergency_alarm();
    xz_report_emergency_event(event_source, display_phrase, event_transcript);
}

static void xz_resolve_emergency_thread(void *parameter)
{
    (void)parameter;

    g_emergency_alarm_cancelled = RT_TRUE;
    if (g_emergency_alarm_tid != RT_NULL || wavplayer_state_get() != PLAYER_STATE_STOPED)
    {
        wavplayer_stop();
    }

    char escaped_source[64];
    xz_json_escape(escaped_source,
                   sizeof(escaped_source),
                   g_active_emergency_source[0] ? g_active_emergency_source : EMERGENCY_SOURCE_DEFAULT);

    char resolve_body[256];
    int body_len = snprintf(resolve_body,
                            sizeof(resolve_body),
                            "{\"source\":\"%s\","
                            "\"resolution_note\":\"已在开发板手动解除紧急状态\","
                            "\"resolved_by\":\"xiaozhi_board_manual_button\"}",
                            escaped_source);
    if (body_len <= 0 || body_len >= (int)sizeof(resolve_body))
    {
        LOG_W("emergency resolve: body too long");
        g_emergency_resolve_in_progress = RT_FALSE;
        xiaozhi_ui_set_emergency_resolution(false);
        return;
    }

    const int result = xz_post_json_to_backend("/emergency/resolve", resolve_body);
    g_emergency_resolve_in_progress = RT_FALSE;
    xiaozhi_ui_set_emergency_resolution(result == 0);
    xiaozhi_ui_set_operating_mode(
        g_app.operating_mode == kXzOperatingModeGuard,
        g_app.operating_mode == kXzOperatingModeGuard &&
            g_app.ws.is_connected && g_app.ws.session_id[0] != '\0');
}

void xz_resolve_emergency_from_board(void)
{
    if (g_emergency_resolve_in_progress)
    {
        LOG_I("emergency resolve: already in progress");
        return;
    }
    g_emergency_resolve_in_progress = RT_TRUE;
    g_emergency_alarm_cancelled = RT_TRUE;
    xiaozhi_ui_set_emergency_resolution(true);

    rt_thread_t tid = rt_thread_create(
        "sosresolve",
        xz_resolve_emergency_thread,
        RT_NULL,
        3072,
        18,
        10);
    if (tid == RT_NULL)
    {
        LOG_E("emergency resolve: thread create failed");
        g_emergency_resolve_in_progress = RT_FALSE;
        xiaozhi_ui_set_emergency_resolution(false);
        return;
    }
    rt_thread_startup(tid);
}

void xz_audio_send_using_websocket(uint8_t *data, int len)
{
    if (g_app.ws.is_connected)
    {
        // Get mutex to prevent concurrent writes
        if (g_app.ws.ws_write_mutex && rt_mutex_take(g_app.ws.ws_write_mutex, RT_WAITING_NO) == RT_EOK)
        {
            // Check connection again, prevent disconnect during lock wait
            if (g_app.ws.is_connected)
            {
                err_t err = wsock_write(&g_app.ws.clnt, (const char *)data, len, OPCODE_BINARY);
                if (err != ERR_OK)
                {
                    LOG_D("wsock_write failed: %d, connection may be closing\n", err);
                    // Write failed, mark connection as disconnected
                    if (err == ERR_CLSD || err == ERR_RST)
                    {
                        g_app.ws.is_connected = 0;
                    }
                }
            }
            rt_mutex_release(g_app.ws.ws_write_mutex);
        }
        else
        {
            // Cannot get lock or not initialized, skip this send
            LOG_D("WebSocket write busy, skip audio data\n");
        }
    }
}

err_t my_wsapp_fn(int code, char *buf, size_t len)
{
    switch (code)
    {
    case WS_CONNECT:
        LOG_D("websocket connected\n");
        if ((uint16_t)(uint32_t)buf == 101)
        {
            g_app.ws.is_connected = 1;
            rt_sem_release(g_app.ws.sem);
        }
        break;
    case WS_DISCONNECT:
        // Get write lock to ensure no ongoing writes
        if (g_app.ws.ws_write_mutex)
        {
            rt_mutex_take(g_app.ws.ws_write_mutex, RT_WAITING_FOREVER);
        }

        /* Ignore disconnect callback during reconnection to avoid state confusion */
        if (g_app.websocket_reconnect_flag == 1)
        {
            LOG_D("Ignore disconnect during reconnect\n");
            if (g_app.ws.ws_write_mutex)
            {
                rt_mutex_release(g_app.ws.ws_write_mutex);
            }
            break;
        }
        /* Ignore disconnect callback if already disconnected */
        if (!g_app.ws.is_connected)
        {
            LOG_D("Ignore disconnect when not connected\n");
            if (g_app.ws.ws_write_mutex)
            {
                rt_mutex_release(g_app.ws.ws_write_mutex);
            }
            break;
        }

        /* Stop mic and speaker on disconnect */
        if (g_app.state == kDeviceStateListening)
        {
            xz_mic(0);
            LOG_D("Stopped microphone recording due to disconnection\n");
        }
        else if (g_app.state == kDeviceStateSpeaking)
        {
            xz_speaker(0);
            LOG_D("Stopped speaker due to disconnection\n");
        }

        xz_mic(0);
        g_app.ws.is_connected = 0;
        g_app.state = kDeviceStateUnknown;

        /* Stop TTS sentence end timer if running */
        if (g_app.tts_sentence_end_timer)
        {
            rt_err_t stop_ret = rt_timer_stop(g_app.tts_sentence_end_timer);
            LOG_D("rt_timer_stop returned %d when stopping timer due to disconnection", stop_ret);
            if (stop_ret == RT_EOK)
            {
                LOG_D("Stopped TTS sentence end timer due to disconnection");
            }
        }

        if (g_app.operating_mode == kXzOperatingModeGuard)
        {
            xiaozhi_ui_set_operating_mode(true, false);
            xiaozhi_ui_chat_output("关键词离线，呼噜监测继续");
        }
        else
        {
            xiaozhi_ui_chat_status("   休眠中");
            xiaozhi_ui_chat_output("等待唤醒");
            xiaozhi_ui_update_emoji("sleepy");
        }
        LOG_I("WebSocket closed\n");

        /* Restore the configured idle audio owner. */
        if (g_app.operating_mode == kXzOperatingModeDialogue &&
            !xz_wakeword_is_enabled())
        {
            LOG_I("Starting wake word detection after disconnection");
            xz_wakeword_start();
        }

        /* Release write lock */
        if (g_app.ws.ws_write_mutex)
        {
            rt_mutex_release(g_app.ws.ws_write_mutex);
        }

        /* Clear reconnect timestamp for immediate retry */
        g_app.last_reconnect_time = 0;
        break;
    case WS_TEXT:
        Message_handle((const uint8_t *)buf, len);
        break;
    case WS_DATA:
        if (g_app.operating_mode == kXzOperatingModeDialogue)
        {
            xz_audio_downlink((uint8_t *)buf, len, NULL, 0);
        }
        break;
    default:
        LOG_E("Unknown error\n");
        break;
    }
    return 0;
}

void reconnect_websocket(void)
{
    err_t result;
    uint32_t retry = 10;
    uint32_t current_time = rt_tick_get();

    /* Prevent frequent reconnects: at least 5s since last */
    if (g_app.websocket_reconnect_flag == 1)
    {
        LOG_D("Reconnection already in progress, ignoring duplicate request\n");
        return;
    }

    if (current_time - g_app.last_reconnect_time < rt_tick_from_millisecond(WEBSOCKET_RECONNECT_DELAY_MS))
    {
        LOG_D("Reconnection too frequent, ignoring request\n");
        return;
    }

    g_app.last_reconnect_time = current_time;

    /* Set reconnect flag to ignore disconnect callbacks during reconnection */
    g_app.websocket_reconnect_flag = 1;

    while (retry-- > 0)
    {
        /* Check WebSocket TCP state, avoid reconnect at bad times */
        if (g_app.ws.clnt.pcb != RT_NULL)
        {
            LOG_D("WebSocket PCB exists, current state: %d\n", g_app.ws.clnt.pcb->state);

            /* Clean up only when state is abnormal */
            if (((struct tcp_pcb *)g_app.ws.clnt.pcb)->state != CLOSED && ((struct tcp_pcb *)g_app.ws.clnt.pcb)->state != CLOSE_WAIT)
            {
                LOG_I("Cleaning up WebSocket connection in state %d\n", g_app.ws.clnt.pcb->state);

                /* Reset connection flag first, avoid reconnect callback interference */
                g_app.ws.is_connected = 0;

                /* Try normal close */
                err_t close_result = wsock_close(&g_app.ws.clnt, WSOCK_RESULT_LOCAL_ABORT, ERR_OK);
                LOG_D("wsock_close result: %d\n", close_result);

                /* Give system time to clean up resources - reduced from 2000ms */
                rt_thread_mdelay(500);

                /* Check if closed successfully */
                if (g_app.ws.clnt.pcb != RT_NULL && ((struct tcp_pcb *)g_app.ws.clnt.pcb)->state != CLOSED)
                {
                    LOG_W("WebSocket PCB still exists after close, forcing cleanup\n");
                    /* Force cleanup - reduced delay */
                    rt_thread_mdelay(100);
                    memset(&g_app.ws.clnt, 0, sizeof(wsock_state_t));
                }
            }
        }

        /* Ensure connection state reset */
        g_app.ws.is_connected = 0;

        if (!g_app.ws.sem)
        {
            g_app.ws.sem = rt_sem_create("xz_ws", 0, RT_IPC_FLAG_FIFO);
        }
        else
        {
            /* Reset semaphore to avoid stale signals */
            while (rt_sem_trytake(g_app.ws.sem) == RT_EOK)
                ;
        }

        char *client_id = get_client_id();

        /* Ensure WebSocket struct fully cleaned */
        memset(&g_app.ws.clnt, 0, sizeof(wsock_state_t));

        wsock_init(&g_app.ws.clnt, 1, 1, my_wsapp_fn);
        result = wsock_connect(&g_app.ws.clnt, MAX_WSOCK_HDR_LEN,
                               XIAOZHI_HOST, XIAOZHI_WSPATH,
                               LWIP_IANA_PORT_HTTPS, XIAOZHI_TOKEN, NULL,
                               "Protocol-Version: 1\r\nDevice-Id: %s\r\nClient-Id: %s\r\n",
                               get_mac_address(), client_id);
        LOG_I("Web socket connection attempt %d: %d\n", 10 - retry, result);
        if (result == 0)
        {
            /* Use longer timeout, follow best practices */
            if (rt_sem_take(g_app.ws.sem, WEBSOCKET_CONNECTION_TIMEOUT_MS) == RT_EOK)
            {
                if (g_app.ws.is_connected)
                {
                    /* Reconnection successful, clear reconnect flag */
                    g_app.websocket_reconnect_flag = 0;
                    result = wsock_write(&g_app.ws.clnt, HELLO_MESSAGE,
                                         strlen(HELLO_MESSAGE), OPCODE_TEXT);
                    LOG_I("Web socket write %d\r\n", result);
                    if (result == ERR_OK)
                    {
                        LOG_I("WebSocket reconnection successful\n");
                        return;
                    }
                    else
                    {
                        LOG_E("Failed to send hello message: %d, retrying...\n", result);
                    }
                }
                else
                {
                    LOG_E("Web socket connection established but not properly initialized, retrying...\n");
                }
            }
            else
            {
                LOG_E("Web socket connection timeout after 50 seconds, retrying...\n");
            }
        }
        else
        {
            LOG_E("Web socket connect failed: %d, retry %d remaining...\n", result, retry);
        }

        /* Optimized retry interval - reduced for faster reconnection */
        uint32_t delay_ms = RETRY_DELAY_BASE_MS + (10 - retry) * RETRY_DELAY_INCREMENT_MS; // 1s-2.8s递增
        LOG_D("Waiting %d ms before next retry...\n", delay_ms);
        rt_thread_mdelay(delay_ms);
    }

    /* Reconnection failed, clear reconnect flag */
    g_app.websocket_reconnect_flag = 0;
    LOG_E("Web socket reconnect failed after all retries\n");

    // Reset state
    g_app.state = kDeviceStateUnknown;
    if (g_app.operating_mode == kXzOperatingModeGuard)
    {
        xiaozhi_ui_set_operating_mode(true, false);
        xiaozhi_ui_chat_output("关键词离线，呼噜监测继续");
    }
    else
    {
        xiaozhi_ui_chat_status("   连接失败");
        xiaozhi_ui_chat_output("请重试");
    }
}

void xz_ws_audio_init(void)
{
    static uint8_t init_flag = 1;
    if (init_flag)
    {
        xz_audio_decoder_encoder_open(1);
        xz_mic_init();
        xz_button_init();
        xz_event_init();
        xz_sound_init();

        /* Wake word detection will be initialized after WebSocket connection */
        LOG_I("Audio system initialized successfully");

        /* Create TTS sentence end timer once here to avoid race conditions
         * Timer is one-shot and will be started on sentence_end events */
        if (!g_app.tts_sentence_end_timer)
        {
            g_app.tts_sentence_end_timer = rt_timer_create("tts_end_timer",
                                                           tts_sentence_end_timeout,
                                                           RT_NULL,
                                                           rt_tick_from_millisecond(TTS_SENTENCE_TIMEOUT_MS),
                                                           RT_TIMER_FLAG_ONE_SHOT);
            if (g_app.tts_sentence_end_timer)
            {
                LOG_D("Created TTS sentence end timer (%d ms)", TTS_SENTENCE_TIMEOUT_MS);
            }
            else
            {
                LOG_E("Failed to create TTS sentence end timer");
            }
        }

        /* Create workqueue for TTS stop delayed restart */
        if (!g_app.tts_stop_workqueue)
        {
            g_app.tts_stop_workqueue = rt_workqueue_create("tts_stop_wq", 2048, RT_THREAD_PRIORITY_MAX - 1);
            if (g_app.tts_stop_workqueue)
            {
                LOG_D("Created TTS stop workqueue");
                /* Initialize the work item */
                rt_work_init(&tts_stop_work, tts_stop_restart_listening, RT_NULL);
            }
            else
            {
                LOG_E("Failed to create TTS stop workqueue");
            }
        }

        /* Create TTS stop delay timer */
        if (!tts_stop_delay_timer)
        {
            tts_stop_delay_timer = rt_timer_create("tts_stop_delay",
                                                   tts_stop_delay_timeout,
                                                   RT_NULL,
                                                   rt_tick_from_millisecond(TTS_STOP_DELAY_MS),
                                                   RT_TIMER_FLAG_ONE_SHOT);
            if (tts_stop_delay_timer)
            {
                LOG_D("Created TTS stop delay timer (%d ms)", TTS_STOP_DELAY_MS);
            }
            else
            {
                LOG_E("Failed to create TTS stop delay timer");
            }
        }

        init_flag = 0;
    }
}

extern "C" {

void xz_voice_suspend(void)
{
    /* Disable voice upload while leaving the shared capture hub running. */
    xz_mic(0);

    if (xz_wakeword_is_enabled())
    {
        xz_wakeword_stop();
    }

    LOG_I("voice: subscriber off, wakeword off");
}

void xz_voice_resume(void)
{
    if (g_app.operating_mode == kXzOperatingModeDialogue &&
        !xz_wakeword_is_enabled())
    {
        xz_wakeword_start();
    }

    LOG_I("voice: resumed (wakeword on)");
}

} /* extern "C" */

static void xz_cancel_conversation_timers(void)
{
    if (g_app.tts_sentence_end_timer)
    {
        rt_timer_stop(g_app.tts_sentence_end_timer);
    }
    if (tts_stop_delay_timer)
    {
        rt_timer_stop(tts_stop_delay_timer);
    }
}

static void xz_stop_active_cloud_audio(void)
{
    xz_cancel_conversation_timers();
    g_app.pending_listen_start = RT_FALSE;
    g_app.pending_play_wake_sound = RT_FALSE;

    if (g_app.ws.is_connected && g_app.ws.session_id[0] != '\0' &&
        (xz_mic_is_enabled() || g_app.state == kDeviceStateListening ||
         g_app.state == kDeviceStateSpeaking))
    {
        ws_send_listen_stop(&g_app.ws.clnt, g_app.ws.session_id);
    }

    xz_mic(0);
    xz_speaker(0);
    if (xz_wakeword_is_enabled())
    {
        xz_wakeword_stop();
    }
}

static int xz_apply_guard_mode(void)
{
    const rt_bool_t keyword_online =
        (g_app.ws.is_connected && g_app.ws.session_id[0] != '\0')
            ? RT_TRUE
            : RT_FALSE;

    LOG_I("Switching to guard mode");
    g_app.operating_mode = kXzOperatingModeGuard;
    g_app.multi_turn_conversation_enabled = RT_FALSE;
    xz_stop_active_cloud_audio();

    if (xz_set_snore_guard_enabled(RT_TRUE) != RT_EOK)
    {
        LOG_E("Guard mode: failed to start snore detection");
        xiaozhi_ui_set_operating_mode(true, false);
        return -RT_ERROR;
    }

    if (keyword_online)
    {
        g_app.state = kDeviceStateListening;
        xz_mic(1);
        if (!ws_send_listen_start(&g_app.ws.clnt,
                                  g_app.ws.session_id,
                                  kListeningModeAlwaysOn))
        {
            LOG_W("Guard mode: failed to start always-on keyword stream");
            xz_mic(0);
            g_app.state = kDeviceStateIdle;
            xiaozhi_ui_set_operating_mode(true, false);
            return -RT_ERROR;
        }
        LOG_I("Guard mode: snore and cloud keyword detection active");
    }
    else
    {
        g_app.state = kDeviceStateUnknown;
        LOG_W("Guard mode: keyword detection offline, snore detection remains active");
    }

    xiaozhi_ui_set_operating_mode(true, keyword_online ? true : false);
    return RT_EOK;
}

static int xz_apply_dialogue_mode(rt_bool_t play_wake_sound)
{
    LOG_I("Switching to dialogue mode");
    g_app.operating_mode = kXzOperatingModeDialogue;
    g_app.multi_turn_conversation_enabled = RT_TRUE;
    xz_stop_active_cloud_audio();
    (void)xz_set_snore_guard_enabled(RT_FALSE);
    xiaozhi_ui_set_operating_mode(false, false);

    if (!g_app.ws.is_connected || g_app.ws.session_id[0] == '\0')
    {
        g_app.pending_listen_start = RT_TRUE;
        g_app.pending_play_wake_sound = play_wake_sound;
        xiaozhi_ui_chat_status("   连接中");
        xiaozhi_ui_chat_output("正在连接小智...");
        reconnect_websocket();
        return RT_EOK;
    }

    if (play_wake_sound)
    {
        xz_play_wake_sound();
    }

    g_app.state = kDeviceStateListening;
    xz_prepare_voice_input();
    xz_mic(1);
    if (!ws_send_listen_start(&g_app.ws.clnt,
                              g_app.ws.session_id,
                              kListeningModeAutoStop))
    {
        LOG_W("Dialogue mode: listen start failed");
        g_app.state = kDeviceStateIdle;
        xz_mic(0);
        xz_restore_idle_audio();
        return -RT_ERROR;
    }

    xiaozhi_ui_chat_status("   聆听中");
    xiaozhi_ui_chat_output("聆听中...");
    return RT_EOK;
}

static void xz_prepare_voice_input(void)
{
    if (xz_wakeword_is_enabled())
    {
        xz_wakeword_stop();
    }
    LOG_I("audio hub: voice starting, snore subscriber unchanged");
}

static void xz_restore_idle_audio(void)
{
    xz_mic(0);

    if (g_app.operating_mode == kXzOperatingModeGuard)
    {
        if (g_app.ws.is_connected && g_app.ws.session_id[0] != '\0')
        {
            g_app.state = kDeviceStateListening;
            xz_mic(1);
            if (ws_send_listen_start(&g_app.ws.clnt,
                                     g_app.ws.session_id,
                                     kListeningModeAlwaysOn))
            {
                xiaozhi_ui_set_operating_mode(true, true);
                return;
            }
            xz_mic(0);
        }

        xiaozhi_ui_set_operating_mode(true, false);
        LOG_I("audio hub: guard snore active, keyword stream offline");
        return;
    }

    if (!xz_wakeword_is_enabled())
    {
        xz_wakeword_start();
    }
    xiaozhi_ui_set_snore_guard_state(g_snore_guard_enabled ? true : false);
    LOG_I("audio hub: idle wakeword restored, snore subscriber unchanged");
}

extern "C" {

int xz_request_operating_mode(enum XzOperatingMode mode)
{
    if (!g_app.button_event)
    {
        return -RT_ERROR;
    }

    const rt_uint32_t event =
        (mode == kXzOperatingModeGuard)
            ? MODE_EVENT_GUARD
            : MODE_EVENT_DIALOGUE;
    return rt_event_send(g_app.button_event, event);
}

enum XzOperatingMode xz_get_operating_mode(void)
{
    return g_app.operating_mode;
}

int xz_set_snore_guard_enabled(rt_bool_t enabled)
{
    if (enabled)
    {
        if (g_snore_guard_enabled && snore_detect_is_running())
        {
            xiaozhi_ui_set_snore_guard_state(true);
            return RT_EOK;
        }

        g_snore_guard_enabled = RT_TRUE;
        if (snore_detect_start() != RT_EOK)
        {
            g_snore_guard_enabled = RT_FALSE;
            xiaozhi_ui_set_snore_guard_state(false);
            return -RT_ERROR;
        }
    }
    else
    {
        g_snore_guard_enabled = RT_FALSE;
        snore_detect_stop();
    }

    xiaozhi_ui_set_snore_guard_state(g_snore_guard_enabled ? true : false);
    return RT_EOK;
}

rt_bool_t xz_is_snore_guard_enabled(void)
{
    return g_snore_guard_enabled;
}

} /* extern "C" */

/* IoT device management functions */
void send_iot_states(void)
{
    const char *state = iot_get_states_json();
    if (state == NULL)
    {
        LOG_E("Failed to get IoT states");
        return;
    }

    // Dynamically allocate buffer since state may be long
    int state_len = strlen(state);
    int msg_size = state_len + 256; // Extra space for session_id etc.
    char *msg = (char *)rt_malloc(msg_size);
    if (msg == NULL)
    {
        LOG_E("Failed to allocate memory for IoT states");
        return;
    }

    snprintf(msg, msg_size,
             "{\"session_id\":\"%s\",\"type\":\"iot\",\"update\":true,"
             "\"states\":%s}",
             g_app.ws.session_id, state);
    LOG_D("Sending IoT states:\n%s\n", msg);
    if (g_app.ws.is_connected)
    {
        wsock_write(&g_app.ws.clnt, msg, strlen(msg), OPCODE_TEXT);
    }
    else
    {
        LOG_W("websocket is not connected");
    }
    rt_free(msg);
}

void send_iot_descriptors(void)
{
    const char *desc = iot_get_descriptors_json();
    if (desc == NULL)
    {
        LOG_E("Failed to get IoT descriptors");
        return;
    }

    // Dynamically allocate buffer since descriptor may be long
    int desc_len = strlen(desc);
    int msg_size = desc_len + 256; // Extra space for session_id etc.
    char *msg = (char *)rt_malloc(msg_size);
    if (msg == NULL)
    {
        LOG_E("Failed to allocate memory for IoT descriptors");
        return;
    }

    snprintf(msg, msg_size,
             "{\"session_id\":\"%s\",\"type\":\"iot\",\"update\":true,"
             "\"descriptors\":%s}",
             g_app.ws.session_id, desc);
    LOG_D("Sending IoT descriptors:\n%s", msg);
    if (g_app.ws.is_connected)
    {
        wsock_write(&g_app.ws.clnt, msg, strlen(msg), OPCODE_TEXT);
    }
    else
    {
        LOG_W("websocket is not connected");
    }
    rt_free(msg);
}

/* Message processing functions */
char *my_json_string(cJSON *json, char *key)
{
    cJSON *item = cJSON_GetObjectItem(json, key);
    if (item && cJSON_IsString(item))
    {
        return item->valuestring;
    }
    return "";
}

void Message_handle(const uint8_t *data, uint16_t len)
{
    cJSON *root = cJSON_Parse((const char *)data);
    if (!root)
    {
        LOG_E("Error before: [%s]\n", cJSON_GetErrorPtr());
        return;
    }

    char *type = my_json_string(root, "type");

    if (g_app.operating_mode == kXzOperatingModeGuard &&
        (strcmp(type, "tts") == 0 || strcmp(type, "llm") == 0))
    {
        /* Guard mode uses the cloud only as an STT source. Never let normal
         * speech produce an audible or visual LLM response. */
        xz_speaker(0);
        LOG_D("Guard mode ignored cloud %s output", type);
        cJSON_Delete(root);
        return;
    }

    if (strcmp(type, "hello") == 0)
    {
        char *session_id = cJSON_GetObjectItem(root, "session_id")->valuestring;
        cJSON *audio_param = cJSON_GetObjectItem(root, "audio_params");
        g_app.ws.sample_rate = cJSON_GetObjectItem(audio_param, "sample_rate")->valueint;
        g_app.ws.frame_duration = cJSON_GetObjectItem(audio_param, "frame_duration")->valueint;
        strncpy(g_app.ws.session_id, session_id, 9);
        rt_bool_t in_listening = (g_app.state == kDeviceStateListening) || xz_mic_is_enabled();
        if (!in_listening && g_app.state != kDeviceStateSpeaking)
        {
            g_app.state = kDeviceStateIdle;
        }
        xz_ws_audio_init();

        /* Initialize only on first connection */
        if (!g_app.iot_initialized)
        {
            LOG_I("Initializing IoT devices for first time\n");
            extern void iot_initialize(void);
            iot_initialize();
            g_app.iot_initialized = 1;
        }
        else
        {
            LOG_D("IoT already initialized, skipping repeated initialization\n");
        }

        /* Resend device info after each reconnect */
        send_iot_descriptors();
        send_iot_states();
        rt_bool_t pending_listen = g_app.pending_listen_start;
        if (g_app.operating_mode == kXzOperatingModeDialogue &&
            !pending_listen && !in_listening)
        {
            xiaozhi_ui_chat_status("   待命中");
            xiaozhi_ui_chat_output(" ");
            xiaozhi_ui_update_emoji("neutral");
            LOG_I("Waiting...\n");
        }
        else
        {
            LOG_I("Pending wake-up detected on hello, preparing to listen\n");
        }

        /* Initialize wake word detection once */
        if (!g_app.wakeword_initialized_session)
        {
            LOG_I("Initializing wake word detection...");
            if (xz_wakeword_init() == 0)
            {
                g_app.wakeword_initialized_session = 1;

                /* Start detection only if no pending listen */
                if (g_app.operating_mode == kXzOperatingModeDialogue &&
                    !pending_listen && !in_listening)
                {
                    if (xz_wakeword_start() == 0)
                    {
                        LOG_D("Wake word detection started successfully");
                    }
                    else
                    {
                        LOG_E("Failed to start wake word detection");
                    }
                }
            }
            else
            {
                LOG_E("Failed to initialize wake word detection");
            }
        }
        else
        {
            if (g_app.operating_mode == kXzOperatingModeDialogue && pending_listen)
            {
                if (xz_wakeword_is_enabled())
                {
                    LOG_D("Stopping wake word detection before pending listen start");
                    xz_wakeword_stop();
                }
            }
            else
            {
                /* Just ensure wake word is running */
                if (g_app.operating_mode == kXzOperatingModeDialogue &&
                    !xz_wakeword_is_enabled() && !in_listening)
                {
                    LOG_D("Restarting wake word detection");
                    xz_wakeword_start();
                }
            }
        }

        if (g_app.operating_mode == kXzOperatingModeGuard)
        {
            (void)xz_apply_guard_mode();
        }
        else if (pending_listen)
        {
            if (g_app.state == kDeviceStateListening || g_app.state == kDeviceStateSpeaking)
            {
                g_app.pending_listen_start = RT_FALSE;
                g_app.pending_play_wake_sound = RT_FALSE;
                return;
            }

            g_app.pending_listen_start = RT_FALSE;

            if (g_app.pending_play_wake_sound)
            {
                xz_play_wake_sound();
            }
            g_app.pending_play_wake_sound = RT_FALSE;

            if (xz_wakeword_is_enabled())
            {
                xz_wakeword_stop();
            }

            g_app.state = kDeviceStateListening;
            xz_prepare_voice_input();
            xz_mic(1);
            if (ws_send_listen_start(&g_app.ws.clnt, g_app.ws.session_id, kListeningModeAutoStop))
            {
                xiaozhi_ui_chat_status("   聆听中");
                xiaozhi_ui_chat_output("聆听中...");
            }
            else
            {
                LOG_W("Listen start failed after hello, falling back to idle");
                g_app.state = kDeviceStateIdle;
                xz_mic(0);
                xiaozhi_ui_chat_status("   就绪");
                xiaozhi_ui_chat_output("就绪");
                xz_restore_idle_audio();
            }
        }
    }
    else if (strcmp(type, "goodbye") == 0)
    {
        xz_mic(0);
        g_app.state = kDeviceStateUnknown;
        LOG_I("session ended\n");

        g_app.wakeword_initialized_session = 0;
        if (g_app.operating_mode == kXzOperatingModeGuard)
        {
            g_app.ws.session_id[0] = '\0';
            xiaozhi_ui_set_operating_mode(true, false);
            xiaozhi_ui_chat_output("关键词离线，呼噜监测继续");
        }
        else
        {
            xiaozhi_ui_chat_status("   休眠中");
            xiaozhi_ui_chat_output("等待唤醒");
            xiaozhi_ui_update_emoji("sleepy");
            xz_restore_idle_audio();
        }
    }
    else if (strcmp(type, "tts") == 0)
    {
        char *state = my_json_string(root, "state");
        if (strcmp(state, "start") == 0)
        {
            if (g_app.state == kDeviceStateIdle || g_app.state == kDeviceStateListening)
            {
                /* Ensure mic off before TTS starts */
                if (g_app.state == kDeviceStateListening)
                {
                    xz_mic(0);
                }

                g_app.state = kDeviceStateSpeaking;
                xiaozhi_ui_chat_status("   说话中");
                xz_speaker(1);
                LOG_D("State transitioned to Speaking, microphone stopped\n");
            }
            else
            {
                LOG_D("Already in Speaking state, ignoring duplicate start\n");
            }
        }
        else if (strcmp(state, "stop") == 0)
        {
            /* Stop the sentence end timer if it's running */
            if (g_app.tts_sentence_end_timer)
            {
                rt_timer_stop(g_app.tts_sentence_end_timer);
                LOG_D("Stopped TTS sentence end timer on TTS stop");
            }

            g_app.state = kDeviceStateIdle;
            xz_speaker(0);

            /* Ensure microphone is closed when conversation ends */
            if (xz_mic_is_enabled())
            {
                xz_mic(0);
            }

            /* Microphone recording should have been stopped already */
            LOG_D("TTS stopped: mic enabled=%d, wakeword enabled=%d",
                  xz_mic_is_enabled(), xz_wakeword_is_enabled());

            xiaozhi_ui_chat_status("   就绪");
            xiaozhi_ui_chat_output("就绪");
            LOG_D("TTS stopped, state reset to Idle\n");

#ifdef LX_LITEGFX_VGLITE_ENABLE
            qday_show_emoji_by_rtt_info(12);
#endif
            /* Check if multi-turn conversation is enabled */
            if (g_app.multi_turn_conversation_enabled)
            {
                /* Multi-turn conversation: start delay timer to restart listening after audio finishes */
                if (tts_stop_delay_timer)
                {
                    LOG_D("Starting TTS stop delay timer (%d ms)", TTS_STOP_DELAY_MS);
                    rt_timer_start(tts_stop_delay_timer);
                }
                else
                {
                    LOG_W("Delay timer not available, restarting listening immediately");
                    /* Fallback: restart immediately */
                    g_app.state = kDeviceStateListening;
                    xz_prepare_voice_input();
                    xz_mic(1);
                    if (ws_send_listen_start(&g_app.ws.clnt, g_app.ws.session_id, kListeningModeAutoStop))
                    {
                        xiaozhi_ui_chat_status("   聆听中");
                        xiaozhi_ui_chat_output("聆听中...");
                    }
                    else
                    {
                        LOG_W("Listen start failed in TTS stop handler");
                        g_app.state = kDeviceStateIdle;
                        xz_mic(0);
                        xiaozhi_ui_chat_status("   就绪");
                        xiaozhi_ui_chat_output("就绪");
                        xz_restore_idle_audio();
                    }
                }
            }
            else
            {
                xz_restore_idle_audio();
            }
        }
        else if (strcmp(state, "sentence_start") == 0)
        {
            LOG_I("tts:%s", my_json_string(root, "text"));
            xiaozhi_ui_chat_output(my_json_string(root, "text"));
        }
        else if (strcmp(state, "sentence_end") == 0)
        {
            /* sentence_end indicates the end of a sentence */
            LOG_D("TTS sentence ended");

            /* For multi-turn conversation, start a timeout timer to restart listening after sentence end */
            if (g_app.multi_turn_conversation_enabled && g_app.state == kDeviceStateSpeaking)
            {
                /* Use the pre-created timer: stop then start to reset timeout */
                if (g_app.tts_sentence_end_timer)
                {
                    rt_err_t stop_ret = rt_timer_stop(g_app.tts_sentence_end_timer);
                    if (stop_ret != RT_EOK)
                    {
                        LOG_W("rt_timer_stop returned %d when resetting TTS timer", stop_ret);
                    }
                    rt_err_t start_ret = rt_timer_start(g_app.tts_sentence_end_timer);
                    if (start_ret == RT_EOK)
                    {
                        LOG_D("Started TTS sentence end timer (%d ms), stop_ret=%d start_ret=%d", TTS_SENTENCE_TIMEOUT_MS, stop_ret, start_ret);
                    }
                    else
                    {
                        LOG_E("Failed to start existing TTS sentence end timer, start_ret=%d", start_ret);
                    }
                }
                else
                {
                    /* Fallback: try to create and start the timer if it wasn't created earlier */
                    g_app.tts_sentence_end_timer = rt_timer_create("tts_end_timer",
                                                                   tts_sentence_end_timeout,
                                                                   RT_NULL,
                                                                   rt_tick_from_millisecond(TTS_SENTENCE_TIMEOUT_MS),
                                                                   RT_TIMER_FLAG_ONE_SHOT);
                    if (g_app.tts_sentence_end_timer && rt_timer_start(g_app.tts_sentence_end_timer) == RT_EOK)
                    {
                        LOG_D("Created and started fallback TTS sentence end timer (%d ms)", TTS_SENTENCE_TIMEOUT_MS);
                    }
                    else
                    {
                        LOG_E("Failed to create/start fallback TTS sentence end timer");
                    }
                }
            }
        }
        else
        {
            LOG_E("Unknown tts state: %s\n", state);
        }
    }
    else if (strcmp(type, "llm") == 0)
    {
        LOG_I("llm emotion: %s", cJSON_GetObjectItem(root, "emotion")->valuestring);
        xiaozhi_ui_update_emoji(
            cJSON_GetObjectItem(root, "emotion")->valuestring);
    }
    else if (strcmp(type, "stt") == 0)
    {
        cJSON *text_item = cJSON_GetObjectItem(root, "text");
        const char *text = (text_item && cJSON_IsString(text_item)) ? text_item->valuestring : RT_NULL;
        LOG_I("stt:%s", text ? text : "(null)");

        if (g_app.operating_mode == kXzOperatingModeGuard)
        {
            const char *emergency_phrase = xz_find_emergency_phrase(text);
            const rt_tick_t now = rt_tick_get();
            const rt_tick_t cooldown = rt_tick_from_millisecond(8000);
            const rt_bool_t duplicate =
                g_emergency_alarm_tid != RT_NULL ||
                (g_emergency_alarm_last_tick != 0 &&
                 (rt_tick_t)(now - g_emergency_alarm_last_tick) < cooldown);

            if (emergency_phrase && !duplicate)
            {
                LOG_W("guard keyword detected: %s", emergency_phrase);
                xz_trigger_emergency_event("xiaozhi_voice_board",
                                           emergency_phrase,
                                           text);
            }
            else if (emergency_phrase)
            {
                LOG_I("guard keyword duplicate ignored: %s", emergency_phrase);
            }
        }

        if (g_app.operating_mode == kXzOperatingModeDialogue &&
            text && strstr(text, "打开打鼾检测") != RT_NULL)
        {
            LOG_I("stt command: open snore detector via voice");
            xiaozhi_ui_enter_snore_mode_from_voice();
        }
    }
    else if (strcmp(type, "iot") == 0)
    {
        LOG_D("iot command");
        cJSON *commands = cJSON_GetObjectItem(root, "commands");
        for (int i = 0; i < cJSON_GetArraySize(commands); i++)
        {
            cJSON *cmd = cJSON_GetArrayItem(commands, i);
            char *cmd_str = cJSON_PrintUnformatted(cmd);
            if (cmd_str)
            {
                iot_invoke((uint8_t *)cmd_str, strlen(cmd_str));
                send_iot_states();
                cJSON_free(cmd_str);
            }
        }
    }
    else if (strcmp(type, "mcp") == 0)
    {
        LOG_D("mcp command");
        cJSON *payload = cJSON_GetObjectItem(root, "payload");
        if (payload && cJSON_IsObject(payload))
        {
            // extern void McpServer_ParseMessage(const char *message);
            char *payload_str = cJSON_PrintUnformatted(payload);
            if (payload_str)
            {
                McpServer_ParseMessage(payload_str);
                cJSON_free(payload_str);
            }
        }
    }
    else if (strcmp(type, "error") == 0)
    {
        cJSON *message = cJSON_GetObjectItem(root, "message");
        if (message && cJSON_IsString(message))
        {
            LOG_E("Server error: %s\n", message->valuestring);
        }
        else
        {
            LOG_E("Server returned error\n");
        }
    }
    else
    {
        LOG_E("Unknown type: %s\n", type);
    }
    cJSON_Delete(root);
}

/* Network utility functions */
void svr_found_callback(const char *name, const ip_addr_t *ipaddr, void *callback_arg)
{
    if (ipaddr != NULL)
    {
        LOG_D("DNS lookup succeeded, IP: %s\n", ipaddr_ntoa(ipaddr));
    }
}

int check_internet_access(void)
{
    const char *hostname = XIAOZHI_HOST;
    ip_addr_t addr = {0};
    err_t err = dns_gethostbyname(hostname, &addr, svr_found_callback, NULL);
    return (err == ERR_OK || err == ERR_INPROGRESS) ? 1 : 0;
}

char *get_xiaozhi_ws(void)
{
    char *buffer = RT_NULL;
    int resp_status;
    struct webclient_session *session = RT_NULL;
    char *xiaozhi_url = RT_NULL;
    int content_length = -1, bytes_read = 0, content_pos = 0;

    if (!check_internet_access())
    {
        return buffer;
    }

    int size = strlen(OTA_VERSION) + MAX_CLIENT_ID_LEN +
               MAX_MAC_ADDR_LEN * 2 + 16;
    char *ota_formatted = (char *)rt_malloc(size);
    if (!ota_formatted)
    {
        goto __exit;
    }

    rt_snprintf(ota_formatted, size, OTA_VERSION, get_mac_address(),
                get_client_id(), get_mac_address());
    xiaozhi_url = (char *)rt_calloc(1, GET_URL_LEN_MAX);
    if (!xiaozhi_url)
    {
        LOG_E("No memory for xiaozhi_url!\n");
        goto __exit;
    }

    rt_snprintf(xiaozhi_url, GET_URL_LEN_MAX, GET_URI, XIAOZHI_HOST);
    session = webclient_session_create(1024);
    if (!session)
    {
        LOG_E("No memory for get header!\n");
        goto __exit;
    }

    webclient_header_fields_add(session, "Device-Id: %s \r\n", get_mac_address());
    webclient_header_fields_add(session, "Client-Id: %s \r\n", get_client_id());
    webclient_header_fields_add(session, "Content-Type: application/json \r\n");
    webclient_header_fields_add(session, "Content-length: %d \r\n",
                                strlen(ota_formatted));

    if ((resp_status = webclient_post(session, xiaozhi_url, ota_formatted,
                                      strlen(ota_formatted))) != 200)
    {
        LOG_E("webclient Post request failed, response(%d) error.\n", resp_status);
    }

    buffer = (char *)rt_calloc(1, GET_RESP_BUFSZ);
    if (!buffer)
    {
        LOG_E("No memory for data receive buffer!\n");
        goto __exit;
    }

    content_length = webclient_content_length_get(session);
    if (content_length > 0)
    {
        do
        {
            bytes_read = webclient_read(session, buffer + content_pos,
                                        content_length - content_pos > GET_RESP_BUFSZ
                                            ? GET_RESP_BUFSZ
                                            : content_length - content_pos);
            if (bytes_read <= 0)
            {
                break;
            }
            content_pos += bytes_read;
        } while (content_pos < content_length);
    }
    else
    {
        rt_free(buffer);
        buffer = NULL;
    }

__exit:
    if (xiaozhi_url)
        rt_free(xiaozhi_url);
    if (session)
        webclient_close(session);
    if (ota_formatted)
        rt_free(ota_formatted);
    return buffer;
}

int http_xiaozhi_data_parse_ws(char *json_data)
{
    cJSON *root = cJSON_Parse(json_data);
    if (!root)
    {
        LOG_E("Error before: [%s]\n", cJSON_GetErrorPtr());
        return -1;
    }

    xiaozhi_ws_connect();
    cJSON_Delete(root);
    return 0;
}

void xiaozhi_ws_connect(void)
{
    err_t err;
    uint32_t retry = 10;

    while (retry-- > 0)
    {
        /* Check network connection status */
        if (!check_internet_access())
        {
            LOG_I("Waiting internet ready... (%d retries remaining)\n", retry);
            xiaozhi_ui_chat_status("   等待网络");
            xiaozhi_ui_chat_output("检查网络连接...");
            rt_thread_mdelay(500); /* Reduced network check delay */
            continue;
        }

        /* Ensure WebSocket in correct state */
        if (g_app.ws.clnt.pcb != RT_NULL && ((struct tcp_pcb *)g_app.ws.clnt.pcb)->state != CLOSED)
        {
            LOG_D("Cleaning up existing WebSocket connection\n");
            wsock_close(&g_app.ws.clnt, WSOCK_RESULT_LOCAL_ABORT, ERR_OK);
            rt_thread_mdelay(200); /* Reduced cleanup delay */
        }

        if (!g_app.ws.sem)
        {
            g_app.ws.sem = rt_sem_create("xz_ws", 0, RT_IPC_FLAG_FIFO);
        }

        // Create WebSocket write mutex
        if (!g_app.ws.ws_write_mutex)
        {
            g_app.ws.ws_write_mutex = rt_mutex_create("xz_ws_write", RT_IPC_FLAG_FIFO);
            if (!g_app.ws.ws_write_mutex)
            {
                LOG_E("Failed to create WebSocket write mutex\n");
                continue;
            }
        }

        wsock_init(&g_app.ws.clnt, 1, 1, my_wsapp_fn);
        char *client_id = get_client_id();
        err = wsock_connect(&g_app.ws.clnt, MAX_WSOCK_HDR_LEN,
                            XIAOZHI_HOST, XIAOZHI_WSPATH,
                            LWIP_IANA_PORT_HTTPS, XIAOZHI_TOKEN, NULL,
                            "Protocol-Version: 1\r\nDevice-Id: %s\r\nClient-Id: %s\r\n",
                            get_mac_address(), client_id);
        LOG_I("Web socket connection attempt %d: %d\n", 10 - retry, err);

        if (err == 0)
        {
            /* Connection successful, wait for handshake */
            if (rt_sem_take(g_app.ws.sem, WEBSOCKET_CONNECTION_TIMEOUT_MS) == RT_EOK)
            {
                LOG_I("WebSocket handshake completed, connected=%d\n", g_app.ws.is_connected);
                if (g_app.ws.is_connected)
                {
                    err = wsock_write(&g_app.ws.clnt, HELLO_MESSAGE,
                                      strlen(HELLO_MESSAGE), OPCODE_TEXT);
                    if (err == ERR_OK)
                    {
                        LOG_I("Initial WebSocket connection established successfully\n");
                        return;
                    }
                    else
                    {
                        LOG_E("Failed to send hello message: %d\n", err);
                    }
                }
                else
                {
                    LOG_E("WebSocket connected but not properly initialized\n");
                }
            }
            else
            {
                LOG_E("WebSocket connection timeout after 50 seconds\n");
            }
        }
        else
        {
            LOG_E("WebSocket connection failed: %d, %d retries remaining\n", err, retry);
        }

        /* Connection failed, update UI status */
        if (retry > 0)
        {
            xiaozhi_ui_chat_status("   连接失败");
            char retry_msg[64];
            rt_snprintf(retry_msg, sizeof(retry_msg), "Retrying... (%d)", 10 - retry);
            xiaozhi_ui_chat_output(retry_msg);
            rt_thread_mdelay(1000); /* Reduced retry delay for better responsiveness */
        }
    }

    /* All retries failed */
    LOG_E("WebSocket connection failed after all attempts\n");
    if (g_app.operating_mode == kXzOperatingModeGuard)
    {
        xiaozhi_ui_set_operating_mode(true, false);
        xiaozhi_ui_chat_output("关键词离线，呼噜监测继续");
    }
    else
    {
        xiaozhi_ui_chat_status("   连接失败");
        xiaozhi_ui_chat_output("请检查网络并重试");
    }
}

/* Application entry point */
void xiaozhi_entry(void *p)
{
    char *my_ota_version;

    /* Bring up the shared microphone before cloud access so local snore
     * monitoring remains available when the Internet is unavailable. */
    xz_ws_audio_init();
    xz_start_edgi_heartbeat();
    (void)xz_apply_guard_mode();

    while (1)
    {
        my_ota_version = get_xiaozhi_ws();
        if (my_ota_version)
        {
            http_xiaozhi_data_parse_ws(my_ota_version);
            rt_free(my_ota_version);
            break;
        }
        else
        {
            LOG_E("Waiting internet... \n");
            rt_thread_mdelay(1000);
        }
    }
}

int ws_xiaozhi_init(void)
{
    g_app.xiaozhi_tid = rt_thread_create("xiaozhi_thread", xiaozhi_entry,
                                         (void *)0x01, 1024 * 30, 15, 5);
    if (!g_app.xiaozhi_tid)
    {
        LOG_E("[%s] Create failed!\n", __FUNCTION__);
        return -RT_ENOMEM;
    }

    if (rt_thread_startup(g_app.xiaozhi_tid) != RT_EOK)
    {
        LOG_E("[%s] Startup failed!\n", __FUNCTION__);
        return -RT_ERROR;
    }

    LOG_I("[%s] Created successfully\n", __FUNCTION__);
    return RT_EOK;
}

/* Multi-turn conversation control functions */
void xz_enable_multi_turn_conversation(rt_bool_t enable)
{
    g_app.multi_turn_conversation_enabled = enable;
    LOG_I("Multi-turn conversation %s", enable ? "enabled" : "disabled");
}

rt_bool_t xz_is_multi_turn_conversation_enabled(void)
{
    return g_app.multi_turn_conversation_enabled;
}

/* Audio notification functions */
void xz_play_power_on_sound(void)
{
    LOG_I("Playing power-on sound");
    audio_capture_hub_suppress_snore_for(5000);
    if (wavplayer_play("/webnet/power_on.wav") != 0)
    {
        LOG_W("Failed to play power-on sound");
    }
}

void xz_play_wake_sound(void)
{
    LOG_D("Playing wake sound");
    audio_capture_hub_suppress_snore_for(3000);
    if (wavplayer_play("/webnet/ding.wav") != 0)
    {
        LOG_W("Failed to play wake sound");
    }
}
