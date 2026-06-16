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
#include <string.h>
#include <stdlib.h>
#include <stdio.h>
#include <lvgl.h>
#include "xiaozhi_ui.h"
#include "xiaozhi.h"
#include "alarm_clock.h"

/*****************************************************************************
 * Macro Definitions
 *****************************************************************************/
#define DBG_TAG    "xz.ui"
#define DBG_LVL    DBG_INFO
#include <rtdbg.h>

#define EMOJI_NUM           18
#define UI_MSG_DATA_SIZE    128
#define UI_MSG_POOL_SIZE    10
#define UI_THREAD_STACK     (1024 * 10)
#define UI_THREAD_PRIORITY  25
#define UI_THREAD_TICK      10

/* Screen resolution specific definitions */
#define SCREEN_WIDTH        800
#define SCREEN_HEIGHT       512
#define BASE_WIDTH          390
#define BASE_HEIGHT         450
#define SCALE_DPX(val)      LV_DPX((val) * g_scale)

/* Animation and timing */
#define ANIM_TIMEOUT        300
#define IDLE_TIME_LIMIT     20000

/* Layout constants */
#define HEADER_HEIGHT       40
#define BATTERY_OUTLINE_W   58
#define BATTERY_OUTLINE_H   33

/*****************************************************************************
 * Type Definitions
 *****************************************************************************/
typedef enum
{
    UI_CMD_SET_STATUS = 0,
    UI_CMD_SET_OUTPUT,
    UI_CMD_SET_SNORE_RESULT,
    UI_CMD_SET_SNORE_GUARD,
    UI_CMD_SHOW_EMERGENCY,
    UI_CMD_SET_EMERGENCY_RESOLUTION,
    UI_CMD_SHOW_ALARM_RING,
    UI_CMD_HIDE_ALARM_RING,
    UI_CMD_REFRESH_ALARM,
    UI_CMD_SET_EMOJI,
    UI_CMD_SET_ADC,
    UI_CMD_SET_ENVIRONMENT,
    UI_CMD_CLEAR_INFO,
    UI_CMD_SHOW_AP_INFO,
    UI_CMD_SHOW_CONNECTING,
    UI_CMD_UPDATE_BATTERY,
    UI_CMD_UPDATE_CHARGE_STATUS
    /* UI_CMD_UPDATE_BLE_STATUS - Bluetooth not used */
} ui_cmd_t;

typedef struct
{
    ui_cmd_t cmd;
    char data[UI_MSG_DATA_SIZE];
} ui_msg_t;

/* Container status flags */
#define CONT_IDLE           0x01
#define CONT_HIDDEN         0x02
#define CONT_DEFAULT_STATUS (CONT_IDLE | CONT_HIDDEN)

/*****************************************************************************
 * External Declarations
 *****************************************************************************/
/* Emoji images */
/* Status icons - Bluetooth not used */
/* extern const lv_image_dsc_t ble; */
/* extern const lv_image_dsc_t ble_close; */

/* Font data */
extern const unsigned char xiaozhi_font[];
extern const int xiaozhi_font_size;

/* Display port */
extern void lv_port_disp_init(void);

/*****************************************************************************
 * Static Variables
 *****************************************************************************/
/* Synchronization */
static struct rt_semaphore s_ui_init_sem;
static struct rt_messagequeue s_ui_mq;
static char s_mq_pool[UI_MSG_POOL_SIZE * sizeof(ui_msg_t)];

/* Scale factor for different screen sizes */
static float g_scale = 1.0f;

/* Container and animation */
static lv_obj_t *s_cont = NULL;
/* static uint8_t s_cont_status = CONT_DEFAULT_STATUS; */ /* Reserved for future use */
/* static uint32_t s_anim_tick = 0; */                    /* Reserved for future use */

/* LVGL objects - Main Screen */
static lv_obj_t *s_label_status;    /* Status label */
static lv_obj_t *s_label_info;      /* Info label */
static lv_obj_t *s_label_adc;       /* ADC label */
static lv_obj_t *s_label_output;    /* Output label */
static lv_obj_t *s_emoji_container;
static lv_obj_t *s_main_container;
static lv_obj_t *s_header_row;
static lv_obj_t *s_img_container;

/* Battery and status */
static lv_obj_t *s_battery_fill = NULL;
static lv_obj_t *s_battery_label = NULL;
/* static lv_obj_t *s_img_ble = NULL; */ /* Bluetooth not used */
static int s_battery_level = 100;

/* LVGL styles */
static lv_style_t s_style_30;
static lv_style_t s_style_24;
static lv_style_t s_style_20;

/* Emoji resources */
static const char *s_emoji_names[EMOJI_NUM] =
{
    "neutral", "happy", "laughing", "funny", "sad", "angry",
    "crying", "loving", "sleepy", "surprised", "shocked",
    "thinking", "winking", "cool", "relaxed", "delicious",
    "kissy", "confident"
};

/* Snore detection screen state */
static rt_bool_t s_snore_mode = RT_FALSE;
static rt_bool_t s_network_overlay_active = RT_FALSE;
static lv_obj_t *s_main_screen = RT_NULL;
static lv_obj_t *s_snore_screen = RT_NULL;
static lv_obj_t *s_snore_label_title = RT_NULL;
static lv_obj_t *s_snore_label_result = RT_NULL;
static lv_obj_t *s_snore_label_score = RT_NULL;
static lv_obj_t *s_snore_panel = RT_NULL;
static lv_obj_t *s_btn_snore = RT_NULL;
static lv_obj_t *s_lbl_snore = RT_NULL;
static lv_obj_t *s_snore_inference_badge = RT_NULL;
static lv_obj_t *s_snore_inference_label = RT_NULL;
static lv_obj_t *s_snore_canvas = RT_NULL;
static lv_obj_t *s_emergency_screen = RT_NULL;
static lv_obj_t *s_emergency_phrase = RT_NULL;
static lv_obj_t *s_emergency_hint = RT_NULL;
static lv_obj_t *s_emergency_resolve_btn = RT_NULL;
static lv_obj_t *s_emergency_resolve_label = RT_NULL;
static lv_obj_t *s_alarm_screen = RT_NULL;
static lv_obj_t *s_alarm_time_label = RT_NULL;
static lv_obj_t *s_alarm_toggle_label = RT_NULL;
static lv_obj_t *s_alarm_action_label = RT_NULL;
static lv_obj_t *s_alarm_ring_screen = RT_NULL;
static lv_obj_t *s_alarm_ring_time_label = RT_NULL;
static lv_obj_t *s_alarm_ring_dismiss_btn = RT_NULL;
static lv_obj_t *s_alarm_ring_dismiss_label = RT_NULL;
static lv_obj_t *s_btn_alarm = RT_NULL;
static lv_obj_t *s_lbl_alarm = RT_NULL;
static alarm_clock_config_t s_alarm_edit = {RT_FALSE, 7, 0};
static rt_bool_t s_alarm_ringing = RT_FALSE;

static void snore_back_btn_event_cb(lv_event_t *e);
static void snore_build_screen(void);
static void emergency_build_screen(void);
static void alarm_build_screen(void);
static void alarm_ring_build_screen(void);

/* Canvas buffer for the snore illustration (ARGB8888). */
static uint8_t s_snore_canvas_buf[360 * 240 * 4] rt_section(".m33_m55_shared_hyperram");

static inline void snore_canvas_px(lv_obj_t *canvas, int w, int h, int x, int y, lv_color_t col)
{
    if (!canvas)
        return;
    if (x < 0 || y < 0 || x >= w || y >= h)
        return;
    lv_canvas_set_px(canvas, x, y, col, LV_OPA_COVER);
}

static void snore_draw_sleep_pixelart(lv_obj_t *canvas)
{
    if (!canvas)
        return;

    const int W = 360;
    const int H = 240;
    lv_canvas_set_buffer(canvas, s_snore_canvas_buf, W, H, LV_COLOR_FORMAT_ARGB8888);
    lv_canvas_fill_bg(canvas, lv_color_black(), LV_OPA_TRANSP);

    const lv_color_t outline = lv_color_hex(0x142033);
    const lv_color_t bed = lv_color_hex(0x5477A8);
    const lv_color_t blanket = lv_color_hex(0x66C2B0);
    const lv_color_t pillow = lv_color_hex(0xE8F1F8);
    const lv_color_t skin = lv_color_hex(0xF2B49B);
    const lv_color_t hair = lv_color_hex(0x39495E);
    const lv_color_t sound = lv_color_hex(0xFFB347);
    const lv_color_t sleep = lv_color_hex(0x8CB8FF);
    const int S = 6;
    const int ox = 48;
    const int oy = 12;

    #define PX(xx,yy,col) do { \
        for(int sy=0; sy<S; sy++) for(int sx=0; sx<S; sx++) \
            snore_canvas_px(canvas, W, H, (ox + (xx)*S + sx), (oy + (yy)*S + sy), (col)); \
    } while(0)

    #define RECT(x0,y0,x1,y1,col) do { \
        for(int yy=(y0); yy<=(y1); yy++) for(int xx=(x0); xx<=(x1); xx++) PX(xx,yy,(col)); \
    } while(0)

    /* Bed frame, mattress and pillow. */
    RECT(3, 25, 43, 33, bed);
    RECT(3, 33, 46, 35, outline);
    RECT(5, 36, 7, 38, outline);
    RECT(42, 36, 44, 38, outline);
    RECT(5, 21, 16, 27, pillow);

    /* Sleeping person facing right. */
    RECT(12, 18, 20, 26, hair);
    RECT(15, 19, 23, 26, skin);
    RECT(14, 18, 20, 19, hair);
    PX(21, 22, outline);
    PX(23, 24, outline);
    RECT(20, 25, 22, 26, skin);

    /* Blanket and body. */
    RECT(20, 26, 42, 32, blanket);
    RECT(24, 24, 39, 25, blanket);
    for (int x = 20; x <= 42; x++) PX(x, 32, outline);

    /* Snore sound waves near the mouth. */
    PX(26, 23, sound); PX(27, 22, sound); PX(27, 24, sound);
    PX(29, 21, sound); PX(30, 20, sound); PX(30, 24, sound); PX(29, 25, sound);
    PX(33, 19, sound); PX(34, 18, sound); PX(34, 26, sound); PX(33, 27, sound);

    /* ZZZ sleep symbol. */
    RECT(31, 4, 37, 5, sleep); RECT(35, 6, 36, 6, sleep); RECT(33, 7, 34, 7, sleep);
    RECT(31, 8, 37, 9, sleep);
    RECT(39, 0, 45, 1, sleep); RECT(43, 2, 44, 2, sleep); RECT(41, 3, 42, 3, sleep);
    RECT(39, 4, 45, 5, sleep);

    #undef PX
    #undef RECT
}

/*****************************************************************************
 * Private Functions
 *****************************************************************************/

/**
 * @brief Calculate scale factor for different screen resolutions
 * @return Scale factor
 */
static float get_scale_factor(void)
{
    lv_disp_t *disp = lv_disp_get_default();
    lv_coord_t scr_width = lv_disp_get_hor_res(disp);
    lv_coord_t scr_height = lv_disp_get_ver_res(disp);

    float scale_x = (float)scr_width / BASE_WIDTH;
    float scale_y = (float)scr_height / BASE_HEIGHT;

    return (scale_x < scale_y) ? scale_x : scale_y;
}

/**
 * @brief Update battery display
 * @param level Battery level (0-100)
 */
static void update_battery_display(int level)
{
    s_battery_level = level;

    if (s_battery_fill)
    {
        int width = (BATTERY_OUTLINE_W - 4) * level / 100;
        if (width < 2 && level > 0) width = 2;
        lv_obj_set_width(s_battery_fill, width);

        if (level <= 20)
        {
            lv_obj_set_style_bg_color(s_battery_fill, lv_color_hex(0xff0000), LV_PART_MAIN | LV_STATE_DEFAULT);
        }
        else
        {
            lv_obj_set_style_bg_color(s_battery_fill, lv_color_hex(0x00ff00), LV_PART_MAIN | LV_STATE_DEFAULT);
        }
    }

    if (s_battery_label)
    {
        lv_label_set_text_fmt(s_battery_label, "%d%%", level);
    }
}





/**
 * @brief Switch container animation
 * @param hidden Whether to hide container
 * @note This function is reserved for future use
 */
static void switch_cont_anim(bool hidden) __attribute__((unused));
static void switch_cont_anim(bool hidden)
{
    if (!s_cont) return;

    lv_anim_t a;
    lv_anim_init(&a);
    lv_anim_set_var(&a, s_cont);
    lv_anim_del(s_cont, NULL);

    if (hidden)
    {
        lv_anim_set_values(&a, lv_obj_get_y(s_cont), -lv_obj_get_height(s_cont));
    }
    else
    {
        lv_anim_set_values(&a, lv_obj_get_y(s_cont), 0);
    }
    lv_anim_set_duration(&a, 200);
    lv_anim_set_exec_cb(&a, (lv_anim_exec_xcb_t)lv_obj_set_y);
    lv_anim_start(&a);
}

/**
 * @brief Snore detect button event callback
 */
static void snore_btn_event_cb(lv_event_t *e)
{
    static rt_tick_t last_click_tick = 0;
    lv_event_code_t code = lv_event_get_code(e);
    if (code != LV_EVENT_CLICKED)
    {
        return;
    }

    const rt_tick_t now = rt_tick_get();
    if (last_click_tick != 0 &&
        (rt_tick_t)(now - last_click_tick) < rt_tick_from_millisecond(700))
    {
        return;
    }
    last_click_tick = now;

    (void)xz_set_snore_guard_enabled(s_snore_mode ? RT_FALSE : RT_TRUE);
}

void xiaozhi_ui_enter_snore_mode_from_voice(void)
{
    if (s_snore_mode)
        return;

    if (!s_snore_screen)
    {
        snore_build_screen();
    }
    if (s_snore_screen)
    {
        lv_screen_load(s_snore_screen);
    }

    if (xz_set_snore_guard_enabled(RT_TRUE) == RT_EOK)
    {
        if (s_snore_label_result)
            lv_label_set_text(s_snore_label_result, "Listening...");
        if (s_snore_label_score)
            lv_label_set_text(s_snore_label_score, "-");
    }
    else
    {
        if (s_main_screen)
            lv_screen_load(s_main_screen);
    }
}

static void snore_back_btn_event_cb(lv_event_t *e)
{
    lv_event_code_t code = lv_event_get_code(e);
    if (code != LV_EVENT_CLICKED)
        return;

    if (s_snore_mode)
    {
        (void)xz_set_snore_guard_enabled(RT_FALSE);
    }

    if (s_main_screen)
        lv_screen_load(s_main_screen);
}

static void snore_build_screen(void)
{
    s_snore_screen = lv_obj_create(NULL);
    lv_obj_clear_flag(s_snore_screen, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_bg_color(s_snore_screen, lv_color_hex(0x0A0D12), LV_PART_MAIN | LV_STATE_DEFAULT);

    /* Center panel (outer frame) */
    s_snore_panel = lv_obj_create(s_snore_screen);
    lv_obj_remove_flag(s_snore_panel, LV_OBJ_FLAG_SCROLLABLE);
    /* 稍微缩小一点并完全居中，避免右侧被裁剪 */
    lv_obj_set_size(s_snore_panel, LV_PCT(90), LV_PCT(86));
    lv_obj_center(s_snore_panel);
    lv_obj_set_style_bg_color(s_snore_panel, lv_color_hex(0x101722), LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_set_style_bg_opa(s_snore_panel, LV_OPA_COVER, LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_set_style_radius(s_snore_panel, SCALE_DPX(18), LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_set_style_border_width(s_snore_panel, 2, LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_set_style_border_color(s_snore_panel, lv_color_hex(0x2B3A55), LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_set_style_pad_all(s_snore_panel, SCALE_DPX(18), LV_PART_MAIN | LV_STATE_DEFAULT);

    /* Title */
    s_snore_label_title = lv_label_create(s_snore_panel);
    lv_label_set_text(s_snore_label_title, "Snore detector");
    lv_obj_add_style(s_snore_label_title, &s_style_30, 0);
    lv_obj_set_width(s_snore_label_title, LV_PCT(100));
    lv_obj_set_style_text_align(s_snore_label_title, LV_TEXT_ALIGN_CENTER, LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_align(s_snore_label_title, LV_ALIGN_TOP_MID, 0, 0);

    /* Sleeping-person snore illustration, shown only when snoring is detected. */
    s_snore_canvas = lv_canvas_create(s_snore_panel);
    lv_obj_set_size(s_snore_canvas, SCALE_DPX(360), SCALE_DPX(240));
    lv_obj_align(s_snore_canvas, LV_ALIGN_TOP_MID, 0, SCALE_DPX(55));
    snore_draw_sleep_pixelart(s_snore_canvas);
    lv_obj_add_flag(s_snore_canvas, LV_OBJ_FLAG_HIDDEN);

    /* Result */
    s_snore_label_result = lv_label_create(s_snore_panel);
    lv_label_set_text(s_snore_label_result, "Listening...");
    lv_obj_add_style(s_snore_label_result, &s_style_30, 0);
    lv_obj_set_style_text_color(s_snore_label_result, lv_color_hex(0xffffff), LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_set_width(s_snore_label_result, LV_PCT(100));
    lv_obj_set_style_text_align(s_snore_label_result, LV_TEXT_ALIGN_CENTER, LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_align_to(s_snore_label_result, s_snore_canvas, LV_ALIGN_OUT_BOTTOM_MID, 0, SCALE_DPX(10));

    /* Score */
    s_snore_label_score = lv_label_create(s_snore_panel);
    lv_label_set_text(s_snore_label_score, "-");
    lv_obj_add_style(s_snore_label_score, &s_style_24, 0);
    lv_obj_set_style_text_color(s_snore_label_score, lv_color_hex(0xC7D2FE), LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_set_width(s_snore_label_score, LV_PCT(100));
    lv_obj_set_style_text_align(s_snore_label_score, LV_TEXT_ALIGN_CENTER, LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_align_to(s_snore_label_score, s_snore_label_result, LV_ALIGN_OUT_BOTTOM_MID, 0, SCALE_DPX(6));

    /* Back button */
    lv_obj_t *btn_back = lv_button_create(s_snore_panel);
    lv_obj_set_size(btn_back, SCALE_DPX(180), SCALE_DPX(54));
    lv_obj_align(btn_back, LV_ALIGN_BOTTOM_MID, 0, 0);
    lv_obj_add_event_cb(btn_back, snore_back_btn_event_cb, LV_EVENT_ALL, NULL);
    lv_obj_set_style_radius(btn_back, SCALE_DPX(14), LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_set_style_bg_color(btn_back, lv_color_hex(0x1F2A44), LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_set_style_bg_opa(btn_back, LV_OPA_COVER, LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_set_style_border_width(btn_back, 1, LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_set_style_border_color(btn_back, lv_color_hex(0x3B82F6), LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_t *lbl_back = lv_label_create(btn_back);
    lv_label_set_text(lbl_back, "Back");
    lv_obj_add_style(lbl_back, &s_style_24, 0);
    lv_obj_center(lbl_back);
}

static void emergency_resolve_btn_event_cb(lv_event_t *e)
{
    if (lv_event_get_code(e) != LV_EVENT_CLICKED)
        return;

    if (s_emergency_resolve_btn)
        lv_obj_add_state(s_emergency_resolve_btn, LV_STATE_DISABLED);
    if (s_emergency_resolve_label)
        lv_label_set_text(s_emergency_resolve_label, "正在解除...");
    if (s_emergency_hint)
        lv_label_set_text(s_emergency_hint, "正在同步看护中心，请稍候");

    xz_resolve_emergency_from_board();
}

static void emergency_build_screen(void)
{
    s_emergency_screen = lv_obj_create(NULL);
    lv_obj_clear_flag(s_emergency_screen, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_bg_color(s_emergency_screen, lv_color_hex(0x16090B), 0);

    lv_obj_t *accent = lv_obj_create(s_emergency_screen);
    lv_obj_clear_flag(accent, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_size(accent, LV_PCT(100), SCALE_DPX(14));
    lv_obj_align(accent, LV_ALIGN_TOP_MID, 0, 0);
    lv_obj_set_style_bg_color(accent, lv_color_hex(0xEF4444), 0);
    lv_obj_set_style_border_width(accent, 0, 0);
    lv_obj_set_style_radius(accent, 0, 0);

    lv_obj_t *badge = lv_label_create(s_emergency_screen);
    lv_label_set_text(badge, "SOS");
    lv_obj_add_style(badge, &s_style_30, 0);
    lv_obj_set_style_text_color(badge, lv_color_hex(0xFF6B6B), 0);
    lv_obj_align(badge, LV_ALIGN_TOP_MID, 0, SCALE_DPX(58));

    lv_obj_t *title = lv_label_create(s_emergency_screen);
    lv_label_set_text(title, "紧急求助已触发");
    lv_obj_add_style(title, &s_style_30, 0);
    lv_obj_set_width(title, LV_PCT(90));
    lv_obj_align(title, LV_ALIGN_TOP_MID, 0, SCALE_DPX(120));

    s_emergency_phrase = lv_label_create(s_emergency_screen);
    lv_label_set_text(s_emergency_phrase, "检测到求助语音");
    lv_obj_add_style(s_emergency_phrase, &s_style_24, 0);
    lv_obj_set_width(s_emergency_phrase, LV_PCT(88));
    lv_obj_set_style_text_color(s_emergency_phrase, lv_color_hex(0xFFD4D4), 0);
    lv_obj_align(s_emergency_phrase, LV_ALIGN_TOP_MID, 0, SCALE_DPX(190));

    s_emergency_hint = lv_label_create(s_emergency_screen);
    lv_label_set_text(s_emergency_hint, "请先确认人员安全，再解除紧急状态");
    lv_obj_add_style(s_emergency_hint, &s_style_20, 0);
    lv_obj_set_width(s_emergency_hint, LV_PCT(90));
    lv_obj_set_style_text_color(s_emergency_hint, lv_color_hex(0xD8B4B8), 0);
    lv_obj_align(s_emergency_hint, LV_ALIGN_TOP_MID, 0, SCALE_DPX(255));

    s_emergency_resolve_btn = lv_button_create(s_emergency_screen);
    lv_obj_set_size(s_emergency_resolve_btn, SCALE_DPX(310), SCALE_DPX(68));
    lv_obj_align(s_emergency_resolve_btn, LV_ALIGN_BOTTOM_MID, 0, -SCALE_DPX(55));
    lv_obj_set_style_bg_color(s_emergency_resolve_btn, lv_color_hex(0xF8FAFC), 0);
    lv_obj_set_style_radius(s_emergency_resolve_btn, SCALE_DPX(12), 0);
    lv_obj_add_event_cb(s_emergency_resolve_btn, emergency_resolve_btn_event_cb, LV_EVENT_ALL, NULL);

    s_emergency_resolve_label = lv_label_create(s_emergency_resolve_btn);
    lv_label_set_text(s_emergency_resolve_label, "解除紧急状态");
    lv_obj_add_style(s_emergency_resolve_label, &s_style_24, 0);
    lv_obj_set_style_text_color(s_emergency_resolve_label, lv_color_hex(0x7F1D1D), 0);
    lv_obj_center(s_emergency_resolve_label);
}

static void alarm_refresh_labels(void)
{
    if (s_alarm_time_label)
        lv_label_set_text_fmt(s_alarm_time_label, "%02d:%02d",
                              s_alarm_edit.hour, s_alarm_edit.minute);
    if (s_alarm_toggle_label)
        lv_label_set_text(s_alarm_toggle_label, s_alarm_edit.enabled ? "已启用" : "已关闭");
    if (s_lbl_alarm)
        lv_label_set_text_fmt(s_lbl_alarm, "闹钟 %02d:%02d",
                              s_alarm_edit.hour, s_alarm_edit.minute);
}

static void alarm_open_event_cb(lv_event_t *e)
{
    if (lv_event_get_code(e) != LV_EVENT_CLICKED)
        return;
    alarm_clock_get(&s_alarm_edit);
    s_alarm_ringing = RT_FALSE;
    if (!s_alarm_screen)
        alarm_build_screen();
    alarm_refresh_labels();
    if (s_alarm_action_label)
        lv_label_set_text(s_alarm_action_label, "保存并返回");
    if (s_alarm_screen)
        lv_screen_load(s_alarm_screen);
}

static void alarm_adjust_event_cb(lv_event_t *e)
{
    if (lv_event_get_code(e) != LV_EVENT_CLICKED)
        return;
    int change = (int)(rt_base_t)lv_event_get_user_data(e);
    if (change == -60 || change == 60)
        s_alarm_edit.hour = (s_alarm_edit.hour + (change / 60) + 24) % 24;
    else
        s_alarm_edit.minute = (s_alarm_edit.minute + change + 60) % 60;
    alarm_refresh_labels();
}

static void alarm_toggle_event_cb(lv_event_t *e)
{
    if (lv_event_get_code(e) != LV_EVENT_CLICKED)
        return;
    s_alarm_edit.enabled = s_alarm_edit.enabled ? RT_FALSE : RT_TRUE;
    alarm_refresh_labels();
}

static void alarm_action_event_cb(lv_event_t *e)
{
    if (lv_event_get_code(e) != LV_EVENT_CLICKED)
        return;

    (void)alarm_clock_set(&s_alarm_edit);
    if (s_main_screen)
        lv_screen_load(s_main_screen);
}

static void alarm_ring_dismiss_event_cb(lv_event_t *e)
{
    if (lv_event_get_code(e) != LV_EVENT_CLICKED || !s_alarm_ringing)
        return;

    s_alarm_ringing = RT_FALSE;
    if (s_alarm_ring_dismiss_btn)
        lv_obj_add_state(s_alarm_ring_dismiss_btn, LV_STATE_DISABLED);
    if (s_alarm_ring_dismiss_label)
        lv_label_set_text(s_alarm_ring_dismiss_label, "正在关闭...");

    alarm_clock_dismiss();
    if (s_main_screen)
        lv_screen_load(s_main_screen);
}

static lv_obj_t *alarm_create_button(lv_obj_t *parent,
                                     const char *text,
                                     lv_event_cb_t callback,
                                     void *user_data)
{
    lv_obj_t *button = lv_button_create(parent);
    lv_obj_set_size(button, SCALE_DPX(115), SCALE_DPX(58));
    lv_obj_add_event_cb(button, callback, LV_EVENT_ALL, user_data);
    lv_obj_set_style_radius(button, SCALE_DPX(10), 0);
    lv_obj_t *label = lv_label_create(button);
    lv_label_set_text(label, text);
    lv_obj_add_style(label, &s_style_24, 0);
    lv_obj_center(label);
    return button;
}

static void alarm_build_screen(void)
{
    s_alarm_screen = lv_obj_create(NULL);
    lv_obj_clear_flag(s_alarm_screen, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_bg_color(s_alarm_screen, lv_color_hex(0x071018), 0);

    lv_obj_t *title = lv_label_create(s_alarm_screen);
    lv_label_set_text(title, "每日闹钟");
    lv_obj_add_style(title, &s_style_30, 0);
    lv_obj_align(title, LV_ALIGN_TOP_MID, 0, SCALE_DPX(42));

    s_alarm_time_label = lv_label_create(s_alarm_screen);
    lv_label_set_text(s_alarm_time_label, "07:00");
    lv_obj_add_style(s_alarm_time_label, &s_style_30, 0);
    lv_obj_set_style_text_color(s_alarm_time_label, lv_color_hex(0x7DD3FC), 0);
    lv_obj_align(s_alarm_time_label, LV_ALIGN_TOP_MID, 0, SCALE_DPX(105));

    lv_obj_t *hour_down = alarm_create_button(s_alarm_screen, "- 时",
                                               alarm_adjust_event_cb, (void *)(rt_base_t)-60);
    lv_obj_align(hour_down, LV_ALIGN_CENTER, -SCALE_DPX(190), -SCALE_DPX(25));
    lv_obj_t *hour_up = alarm_create_button(s_alarm_screen, "+ 时",
                                             alarm_adjust_event_cb, (void *)(rt_base_t)60);
    lv_obj_align(hour_up, LV_ALIGN_CENTER, -SCALE_DPX(62), -SCALE_DPX(25));
    lv_obj_t *minute_down = alarm_create_button(s_alarm_screen, "- 分",
                                                 alarm_adjust_event_cb, (void *)(rt_base_t)-5);
    lv_obj_align(minute_down, LV_ALIGN_CENTER, SCALE_DPX(66), -SCALE_DPX(25));
    lv_obj_t *minute_up = alarm_create_button(s_alarm_screen, "+ 分",
                                               alarm_adjust_event_cb, (void *)(rt_base_t)5);
    lv_obj_align(minute_up, LV_ALIGN_CENTER, SCALE_DPX(194), -SCALE_DPX(25));

    lv_obj_t *toggle = lv_button_create(s_alarm_screen);
    lv_obj_set_size(toggle, SCALE_DPX(190), SCALE_DPX(58));
    lv_obj_align(toggle, LV_ALIGN_CENTER, 0, SCALE_DPX(55));
    lv_obj_add_event_cb(toggle, alarm_toggle_event_cb, LV_EVENT_ALL, NULL);
    s_alarm_toggle_label = lv_label_create(toggle);
    lv_label_set_text(s_alarm_toggle_label, "已关闭");
    lv_obj_add_style(s_alarm_toggle_label, &s_style_24, 0);
    lv_obj_center(s_alarm_toggle_label);

    lv_obj_t *action = lv_button_create(s_alarm_screen);
    lv_obj_set_size(action, SCALE_DPX(280), SCALE_DPX(62));
    lv_obj_align(action, LV_ALIGN_BOTTOM_MID, 0, -SCALE_DPX(45));
    lv_obj_add_event_cb(action, alarm_action_event_cb, LV_EVENT_ALL, NULL);
    s_alarm_action_label = lv_label_create(action);
    lv_label_set_text(s_alarm_action_label, "保存并返回");
    lv_obj_add_style(s_alarm_action_label, &s_style_24, 0);
    lv_obj_center(s_alarm_action_label);
}

static void alarm_ring_build_screen(void)
{
    s_alarm_ring_screen = lv_obj_create(NULL);
    lv_obj_clear_flag(s_alarm_ring_screen, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_bg_color(s_alarm_ring_screen, lv_color_hex(0x071018), 0);

    lv_obj_t *accent = lv_obj_create(s_alarm_ring_screen);
    lv_obj_remove_flag(accent, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_size(accent, LV_PCT(100), SCALE_DPX(12));
    lv_obj_align(accent, LV_ALIGN_TOP_MID, 0, 0);
    lv_obj_set_style_bg_color(accent, lv_color_hex(0xF59E0B), 0);
    lv_obj_set_style_border_width(accent, 0, 0);
    lv_obj_set_style_radius(accent, 0, 0);

    lv_obj_t *badge = lv_label_create(s_alarm_ring_screen);
    lv_label_set_text(badge, "ALARM");
    lv_obj_add_style(badge, &s_style_24, 0);
    lv_obj_set_style_text_color(badge, lv_color_hex(0xFBBF24), 0);
    lv_obj_align(badge, LV_ALIGN_TOP_MID, 0, SCALE_DPX(46));

    lv_obj_t *title = lv_label_create(s_alarm_ring_screen);
    lv_label_set_text(title, "闹钟响了");
    lv_obj_add_style(title, &s_style_30, 0);
    lv_obj_set_style_text_color(title, lv_color_hex(0xFFFFFF), 0);
    lv_obj_align(title, LV_ALIGN_TOP_MID, 0, SCALE_DPX(100));

    s_alarm_ring_time_label = lv_label_create(s_alarm_ring_screen);
    lv_label_set_text(s_alarm_ring_time_label, "07:00");
    lv_obj_add_style(s_alarm_ring_time_label, &s_style_30, 0);
    lv_obj_set_style_text_color(s_alarm_ring_time_label,
                                lv_color_hex(0x7DD3FC), 0);
    lv_obj_align(s_alarm_ring_time_label, LV_ALIGN_CENTER,
                 0, -SCALE_DPX(28));

    lv_obj_t *hint = lv_label_create(s_alarm_ring_screen);
    lv_label_set_text(hint, "点击下方按钮停止闹钟");
    lv_obj_add_style(hint, &s_style_20, 0);
    lv_obj_set_style_text_color(hint, lv_color_hex(0xCBD5E1), 0);
    lv_obj_align(hint, LV_ALIGN_CENTER, 0, SCALE_DPX(45));

    s_alarm_ring_dismiss_btn = lv_button_create(s_alarm_ring_screen);
    lv_obj_set_size(s_alarm_ring_dismiss_btn,
                    SCALE_DPX(330), SCALE_DPX(76));
    lv_obj_align(s_alarm_ring_dismiss_btn, LV_ALIGN_BOTTOM_MID,
                 0, -SCALE_DPX(42));
    lv_obj_set_style_bg_color(s_alarm_ring_dismiss_btn,
                              lv_color_hex(0xF59E0B), 0);
    lv_obj_set_style_radius(s_alarm_ring_dismiss_btn, SCALE_DPX(12), 0);
    lv_obj_add_event_cb(s_alarm_ring_dismiss_btn,
                        alarm_ring_dismiss_event_cb,
                        LV_EVENT_ALL, NULL);

    s_alarm_ring_dismiss_label = lv_label_create(s_alarm_ring_dismiss_btn);
    lv_label_set_text(s_alarm_ring_dismiss_label, "关闭闹钟");
    lv_obj_add_style(s_alarm_ring_dismiss_label, &s_style_24, 0);
    lv_obj_set_style_text_color(s_alarm_ring_dismiss_label,
                                lv_color_hex(0x111827), 0);
    lv_obj_center(s_alarm_ring_dismiss_label);
}

/**
 * @brief Initialize LVGL UI objects
 * @return RT_EOK on success
 */
static rt_err_t ui_objects_init(void)
{
    lv_obj_t *screen = lv_screen_active();
    s_main_screen = screen;
    lv_coord_t scr_width = lv_disp_get_hor_res(NULL);
    lv_coord_t scr_height = lv_disp_get_ver_res(NULL);

    /* Calculate scale factor */
    g_scale = get_scale_factor();

    /* Configure screen */
    lv_obj_clear_flag(screen, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_bg_color(screen, lv_color_hex(0x000000), LV_PART_MAIN | LV_STATE_DEFAULT);

    /* Create main container - Flex Column layout */

        extern lv_obj_t * lv_example_virtual3d_animated_emoji(lv_obj_t * p_container) ;
    s_emoji_container = lv_example_virtual3d_animated_emoji(screen) ;
    /* Header row container */
    s_header_row = lv_obj_create(screen);
    lv_obj_remove_flag(s_header_row, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_size(s_header_row, scr_width, SCALE_DPX(HEADER_HEIGHT));

    /* Clear header_row's padding and margin */
    lv_obj_set_style_pad_all(s_header_row, 0, LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_set_style_margin_all(s_header_row, 0, LV_PART_MAIN | LV_STATE_DEFAULT);
    /* Set header_row's background transparent and border width to 0 */
    lv_obj_set_style_bg_opa(s_header_row, LV_OPA_0, LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_set_style_border_width(s_header_row, 0, LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_set_flex_flow(s_header_row, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(s_header_row, LV_FLEX_ALIGN_SPACE_BETWEEN,
                          LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);

    /* Left spacer */
    lv_obj_t *spacer_left = lv_obj_create(s_header_row);
    lv_obj_remove_flag(spacer_left, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_bg_opa(spacer_left, LV_OPA_0, LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_set_style_border_width(spacer_left, 0, LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_set_size(spacer_left, SCALE_DPX(40), LV_SIZE_CONTENT);

    /* BLE status icon - removed */
    /* s_img_ble = lv_img_create(s_header_row); */
    /* lv_img_set_src(s_img_ble, &ble_close); */
    /* lv_obj_set_size(s_img_ble, SCALE_DPX(24), SCALE_DPX(24)); */
    /* lv_img_set_zoom(s_img_ble, (int)(LV_SCALE_NONE * g_scale)); */

    /* Status label - centered */
    s_label_status = lv_label_create(s_header_row);
    lv_label_set_long_mode(s_label_status, LV_LABEL_LONG_WRAP);
    lv_obj_add_style(s_label_status, &s_style_24, 0);
    lv_obj_set_width(s_label_status, LV_PCT(60));
    lv_obj_set_style_text_color(s_label_status, lv_color_hex(0xffffff), LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_set_style_text_align(s_label_status, LV_TEXT_ALIGN_CENTER, LV_PART_MAIN | LV_STATE_DEFAULT);

    /* Battery container */
    lv_obj_t *battery_outline = lv_obj_create(s_header_row);
    lv_obj_set_style_border_width(battery_outline, 2, LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_set_style_pad_all(battery_outline, 0, LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_set_style_radius(battery_outline, 8, LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_clear_flag(battery_outline, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_text_color(s_label_status, lv_color_hex(0xffffff), LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_set_size(battery_outline, BATTERY_OUTLINE_W * g_scale, BATTERY_OUTLINE_H * g_scale);

    /* Battery fill */
    s_battery_fill = lv_obj_create(battery_outline);
    lv_obj_set_style_outline_width(s_battery_fill, 0, LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_set_style_outline_pad(s_battery_fill, 0, LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_set_style_border_width(s_battery_fill, 0, LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_set_style_bg_color(s_battery_fill, lv_color_hex(0x00ff00), LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_set_size(s_battery_fill, BATTERY_OUTLINE_W * g_scale - 4, BATTERY_OUTLINE_H * g_scale - 4);
    lv_obj_set_style_border_width(s_battery_fill, 0, LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_set_style_radius(s_battery_fill, 8, LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_align(s_battery_fill, LV_ALIGN_LEFT_MID, 0, 0);
    lv_obj_set_style_text_color(s_battery_fill, lv_color_hex(0xffffff), LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_clear_flag(s_battery_fill, LV_OBJ_FLAG_SCROLLABLE);

    /* Battery label */
    s_battery_label = lv_label_create(battery_outline);
    lv_obj_add_style(s_battery_label, &s_style_20, 0);
    lv_label_set_text_fmt(s_battery_label, "%d%%", s_battery_level);
    lv_obj_set_style_text_color(s_battery_label, lv_color_hex(0xffffff), LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_align(s_battery_label, LV_ALIGN_CENTER, 0, 0);

    /* Right spacer */
    lv_obj_t *spacer_right = lv_obj_create(s_header_row);
    lv_obj_remove_flag(spacer_right, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_bg_opa(spacer_right, LV_OPA_0, LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_set_style_border_width(spacer_right, 0, LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_set_size(spacer_right, SCALE_DPX(40), LV_SIZE_CONTENT);

    /* Image container for emoji */
    s_img_container = lv_obj_create(s_main_container);
    lv_obj_remove_flag(s_img_container, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_size(s_img_container, scr_width, scr_height * 0.5);
    lv_obj_set_style_bg_opa(s_img_container, LV_OPA_0, LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_set_style_border_width(s_img_container, 0, LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_set_style_pad_all(s_img_container, 0, LV_PART_MAIN | LV_STATE_DEFAULT);

    /* Create emoji objects - centered in img_container */
    /* Text container for output */
    lv_obj_t *text_container = lv_obj_create(screen);
    lv_obj_align(text_container, LV_ALIGN_BOTTOM_MID, 0, 0);
    lv_obj_remove_flag(text_container, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_size(text_container, scr_width, scr_height * 0.2);
    lv_obj_set_style_bg_opa(text_container, LV_OPA_0, LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_set_style_border_width(text_container, 0, LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_set_style_text_color(text_container, lv_color_hex(0xffffff), LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_set_style_pad_all(text_container, SCALE_DPX(20), LV_PART_MAIN | LV_STATE_DEFAULT);

    /* Output label */
    s_label_output = lv_label_create(text_container);
    lv_label_set_long_mode(s_label_output, LV_LABEL_LONG_WRAP);
    lv_obj_add_style(s_label_output, &s_style_20, 0);
    lv_obj_set_width(s_label_output, LV_PCT(90));
    lv_obj_set_style_text_align(s_label_output, LV_TEXT_ALIGN_CENTER, LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_set_style_text_color(s_label_output, lv_color_hex(0xffffff), LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_align(s_label_output, LV_ALIGN_TOP_MID, 0, 0);

    /* Info label */
    s_label_info = lv_label_create(text_container);
    lv_label_set_long_mode(s_label_info, LV_LABEL_LONG_WRAP);
    lv_obj_add_style(s_label_info, &s_style_20, 0);
    lv_obj_set_width(s_label_info, LV_PCT(90));
    lv_obj_set_style_text_align(s_label_info, LV_TEXT_ALIGN_CENTER, LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_set_style_text_color(s_label_info, lv_color_hex(0xffffff), LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_align(s_label_info, LV_ALIGN_BOTTOM_MID, 0, 0);

    /* Snore detect button (main screen) */
    s_btn_snore = lv_button_create(screen);
    lv_obj_set_size(s_btn_snore, SCALE_DPX(200), SCALE_DPX(56));
    lv_obj_align(s_btn_snore, LV_ALIGN_CENTER, -SCALE_DPX(110), SCALE_DPX(120));
    lv_obj_add_event_cb(s_btn_snore, snore_btn_event_cb, LV_EVENT_ALL, NULL);

    s_lbl_snore = lv_label_create(s_btn_snore);
    lv_obj_add_style(s_lbl_snore, &s_style_20, 0);
    lv_label_set_text(s_lbl_snore, "启动呼噜监测");
    lv_obj_center(s_lbl_snore);

    /* Compact live inference result. It remains visible while the main
     * screen is active, including when snore guard was auto-started. */
    s_snore_inference_badge = lv_obj_create(screen);
    lv_obj_remove_flag(s_snore_inference_badge, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_size(s_snore_inference_badge,
                    SCALE_DPX(300), SCALE_DPX(42));
    lv_obj_align(s_snore_inference_badge, LV_ALIGN_CENTER,
                 0, SCALE_DPX(66));
    lv_obj_set_style_radius(s_snore_inference_badge, SCALE_DPX(8),
                            LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_set_style_bg_color(s_snore_inference_badge,
                              lv_color_hex(0x172033),
                              LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_set_style_bg_opa(s_snore_inference_badge, LV_OPA_COVER,
                            LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_set_style_border_width(s_snore_inference_badge, 1,
                                  LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_set_style_border_color(s_snore_inference_badge,
                                  lv_color_hex(0x3B4A68),
                                  LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_set_style_pad_all(s_snore_inference_badge, 0,
                             LV_PART_MAIN | LV_STATE_DEFAULT);

    s_snore_inference_label = lv_label_create(s_snore_inference_badge);
    lv_obj_add_style(s_snore_inference_label, &s_style_20, 0);
    lv_label_set_text(s_snore_inference_label, "SNORE  --  PAUSED");
    lv_obj_set_width(s_snore_inference_label, LV_PCT(100));
    lv_obj_set_style_text_align(s_snore_inference_label,
                                LV_TEXT_ALIGN_CENTER,
                                LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_center(s_snore_inference_label);

    s_btn_alarm = lv_button_create(screen);
    lv_obj_set_size(s_btn_alarm, SCALE_DPX(190), SCALE_DPX(56));
    lv_obj_align(s_btn_alarm, LV_ALIGN_CENTER, SCALE_DPX(110), SCALE_DPX(120));
    lv_obj_add_event_cb(s_btn_alarm, alarm_open_event_cb, LV_EVENT_ALL, NULL);
    s_lbl_alarm = lv_label_create(s_btn_alarm);
    lv_obj_add_style(s_lbl_alarm, &s_style_20, 0);
    alarm_clock_get(&s_alarm_edit);
    lv_label_set_text_fmt(s_lbl_alarm, "闹钟 %02d:%02d",
                          s_alarm_edit.hour, s_alarm_edit.minute);
    lv_obj_center(s_lbl_alarm);

    /* ADC label - positioned in top right */
    s_label_adc = lv_label_create(screen);
    lv_obj_add_style(s_label_adc, &s_style_30, 0);
    lv_obj_set_style_text_color(s_label_adc, lv_color_hex(0x333333), LV_PART_MAIN | LV_STATE_DEFAULT); /* Dark gray for better contrast */
    lv_obj_align(s_label_adc, LV_ALIGN_TOP_RIGHT, -SCALE_DPX(20), SCALE_DPX(20));

    return RT_EOK;
}

/**
 * @brief Send UI message to queue
 * @param cmd Command type
 * @param data Data string (can be NULL)
 * @param default_data Default value if data is NULL
 */
static void ui_send_message(ui_cmd_t cmd, const char *data, const char *default_data)
{
    ui_msg_t msg;

    msg.cmd = cmd;
    if (data != RT_NULL)
    {
        rt_strncpy(msg.data, data, sizeof(msg.data) - 1);
    }
    else if (default_data != RT_NULL)
    {
        rt_strncpy(msg.data, default_data, sizeof(msg.data) - 1);
    }
    else
    {
        msg.data[0] = '\0';
    }
    msg.data[sizeof(msg.data) - 1] = '\0';

    rt_mq_send(&s_ui_mq, &msg, sizeof(msg));
}

/**
 * @brief Find emoji index by name
 * @param name Emoji name
 * @return Index if found, -1 otherwise
 */
static int ui_find_emoji_index(const char *name)
{
    for (int i = 0; i < EMOJI_NUM; i++)
    {
        if (rt_strcmp(name, s_emoji_names[i]) == 0)
        {
            return i;
        }
    }
    return -1;
}

/**
 * @brief Show specified emoji, hide others
 * @param index Emoji index to show
 */
static void ui_show_emoji(int index)
{
    qday_show_emoji_by_rtt_info(index);
}

/**
 * @brief Process UI message
 * @param msg Message to process
 */
static void ui_process_message(const ui_msg_t *msg)
{
    switch (msg->cmd)
    {
    case UI_CMD_SET_STATUS:
        if (s_label_status)
        {
            lv_label_set_text(s_label_status, msg->data);
        }
        break;

    case UI_CMD_SET_OUTPUT:
        if (s_label_output)
        {
            lv_label_set_text(s_label_output, msg->data);
        }
        break;

    case UI_CMD_SET_SNORE_RESULT:
        {
            /* data: model_positive,alert_triggered,suppressed,score */
            int model_positive = 0;
            int alert_triggered = 0;
            int suppressed = 0;
            float score = 0.0f;
            int fields = sscanf(msg->data, "%d,%d,%d,%f",
                                &model_positive, &alert_triggered,
                                &suppressed, &score);

            /* Accept the old "detected,score" format for compatibility. */
            if (fields < 4)
            {
                model_positive = 0;
                score = 0.0f;
                sscanf(msg->data, "%d,%f", &model_positive, &score);
                alert_triggered = model_positive;
                suppressed = 0;
            }

            if (s_snore_inference_label)
            {
                char summary[48];
                const int percent = (int)(score * 100.0f + 0.5f);
                const char *state = model_positive
                    ? (suppressed ? "MUTED"
                                  : (alert_triggered ? "ALARM"
                                                     : "DETECTED"))
                    : "NORMAL";
                rt_snprintf(summary, sizeof(summary),
                            "SNORE  %d%%  %s", percent, state);
                lv_label_set_text(s_snore_inference_label, summary);
                lv_obj_set_style_text_color(
                    s_snore_inference_label,
                    model_positive
                        ? (suppressed ? lv_color_hex(0xFBBF24)
                                      : lv_color_hex(0xFF5C5C))
                        : lv_color_hex(0x67E8A5),
                    LV_PART_MAIN | LV_STATE_DEFAULT);
            }

            if (s_snore_inference_badge)
            {
                lv_obj_set_style_border_color(
                    s_snore_inference_badge,
                    model_positive
                        ? (suppressed ? lv_color_hex(0xF59E0B)
                                      : lv_color_hex(0xEF4444))
                        : lv_color_hex(0x22C55E),
                    LV_PART_MAIN | LV_STATE_DEFAULT);
            }

            if (!s_snore_label_result)
                break;

            if (model_positive)
            {
                lv_label_set_text(s_snore_label_result,
                                  suppressed
                                      ? "SNORE DETECTED - MUTED"
                                      : (alert_triggered
                                             ? "SNORE ALARM"
                                             : "SNORE DETECTED"));
                lv_obj_set_style_text_color(
                    s_snore_label_result,
                    suppressed ? lv_color_hex(0xFBBF24)
                               : lv_color_hex(0xff4040),
                    LV_PART_MAIN | LV_STATE_DEFAULT);
                if (s_snore_canvas)
                    lv_obj_clear_flag(s_snore_canvas, LV_OBJ_FLAG_HIDDEN);
            }
            else
            {
                lv_label_set_text(s_snore_label_result, "NO SNORE");
                lv_obj_set_style_text_color(s_snore_label_result, lv_color_hex(0x888888), LV_PART_MAIN | LV_STATE_DEFAULT);
                if (s_snore_canvas)
                    lv_obj_add_flag(s_snore_canvas, LV_OBJ_FLAG_HIDDEN);
            }
            if (s_snore_label_score)
            {
                char tmp[32];
                rt_snprintf(tmp, sizeof(tmp), "score: %.2f", score);
                lv_label_set_text(s_snore_label_score, tmp);
                lv_obj_set_style_text_color(s_snore_label_score,
                                            model_positive ? lv_color_hex(0xffffff) : lv_color_hex(0x888888),
                                            LV_PART_MAIN | LV_STATE_DEFAULT);
            }
        }
        break;

    case UI_CMD_SET_SNORE_GUARD:
        s_snore_mode = strcmp(msg->data, "enabled") == 0 ? RT_TRUE : RT_FALSE;
        if (s_lbl_snore)
            lv_label_set_text(s_lbl_snore, s_snore_mode ? "暂停呼噜监测" : "继续呼噜监测");
        if (s_label_status)
            lv_label_set_text(s_label_status, s_snore_mode ? "呼噜守护中" : "小智语音就绪");
        if (s_snore_inference_label)
        {
            lv_label_set_text(s_snore_inference_label,
                              s_snore_mode
                                  ? "SNORE  --  ANALYZING"
                                  : "SNORE  --  PAUSED");
            lv_obj_set_style_text_color(
                s_snore_inference_label,
                s_snore_mode ? lv_color_hex(0x93C5FD)
                             : lv_color_hex(0x94A3B8),
                LV_PART_MAIN | LV_STATE_DEFAULT);
        }
        if (s_snore_inference_badge)
        {
            lv_obj_set_style_border_color(
                s_snore_inference_badge,
                s_snore_mode ? lv_color_hex(0x3B82F6)
                             : lv_color_hex(0x3B4A68),
                LV_PART_MAIN | LV_STATE_DEFAULT);
        }
        break;

    case UI_CMD_SHOW_EMERGENCY:
        if (!s_emergency_screen)
            emergency_build_screen();
        if (s_emergency_phrase)
            lv_label_set_text_fmt(s_emergency_phrase, "检测到：%s", msg->data[0] ? msg->data : "求助语音");
        if (s_emergency_hint)
            lv_label_set_text(s_emergency_hint, "请先确认人员安全，再解除紧急状态");
        if (s_emergency_resolve_label)
            lv_label_set_text(s_emergency_resolve_label, "解除紧急状态");
        if (s_emergency_resolve_btn)
            lv_obj_remove_state(s_emergency_resolve_btn, LV_STATE_DISABLED);
        if (s_emergency_screen)
            lv_screen_load(s_emergency_screen);
        break;

    case UI_CMD_SET_EMERGENCY_RESOLUTION:
        if (s_main_screen)
            lv_screen_load(s_main_screen);
        if (strcmp(msg->data, "success") == 0)
        {
            if (s_label_status)
                lv_label_set_text(s_label_status, "紧急状态已解除");
            if (s_label_output)
                lv_label_set_text(s_label_output, "看护中心已记录处理结果");
        }
        else
        {
            if (s_label_status)
                lv_label_set_text(s_label_status, "本地紧急状态已解除");
            if (s_label_output)
                lv_label_set_text(s_label_output, "看护中心同步失败");
        }
        break;

    case UI_CMD_SHOW_ALARM_RING:
        alarm_clock_get(&s_alarm_edit);
        s_alarm_ringing = RT_TRUE;
        if (!s_alarm_ring_screen)
            alarm_ring_build_screen();
        if (s_alarm_ring_time_label)
            lv_label_set_text_fmt(s_alarm_ring_time_label, "%02d:%02d",
                                  s_alarm_edit.hour, s_alarm_edit.minute);
        if (s_alarm_ring_dismiss_btn)
            lv_obj_remove_state(s_alarm_ring_dismiss_btn, LV_STATE_DISABLED);
        if (s_alarm_ring_dismiss_label)
            lv_label_set_text(s_alarm_ring_dismiss_label, "关闭闹钟");
        if (s_alarm_ring_screen)
            lv_screen_load(s_alarm_ring_screen);
        break;

    case UI_CMD_HIDE_ALARM_RING:
        if (s_alarm_ringing)
        {
            s_alarm_ringing = RT_FALSE;
            if (s_main_screen)
                lv_screen_load(s_main_screen);
        }
        break;

    case UI_CMD_REFRESH_ALARM:
        alarm_clock_get(&s_alarm_edit);
        alarm_refresh_labels();
        break;

    case UI_CMD_SET_ADC:
        if (s_label_adc)
        {
            lv_label_set_text(s_label_adc, msg->data);
        }
        break;

    case UI_CMD_SET_ENVIRONMENT:
        if (s_label_info && !s_snore_mode && !s_network_overlay_active)
        {
            lv_label_set_text(s_label_info, msg->data);
        }
        break;

    case UI_CMD_SET_EMOJI:
        ui_show_emoji(ui_find_emoji_index(msg->data));
        break;

    case UI_CMD_CLEAR_INFO:
        s_network_overlay_active = RT_FALSE;
        if (s_label_info) lv_label_set_text(s_label_info, " ");
        if (s_label_output) lv_label_set_text(s_label_output, " ");
        break;

    case UI_CMD_SHOW_AP_INFO:
        s_network_overlay_active = RT_TRUE;
        if (s_label_status) lv_label_set_text(s_label_status, "连接中...");
        if (s_label_info) lv_label_set_text(s_label_info, "使用手机或电脑连接热点");
        if (s_label_output) lv_label_set_text(s_label_output, "SSID: RT-Thread-AP 密码: 123456789 IP:192.168.169.1");
        break;

    case UI_CMD_SHOW_CONNECTING:
        s_network_overlay_active = RT_TRUE;
        if (s_label_status) lv_label_set_text(s_label_status, "连接中...");
        if (s_label_info) lv_label_set_text(s_label_info, "正在连接已保存的WiFi...");
        if (s_label_output) lv_label_set_text(s_label_output, " ");
        break;

    case UI_CMD_UPDATE_BATTERY:
    {
        int level = atoi(msg->data);
        update_battery_display(level);
    }
    break;

    case UI_CMD_UPDATE_CHARGE_STATUS:
        if (strcmp(msg->data, "charging") == 0)
        {
            /* Update UI to show charging status */
            if (s_label_status)
            {
                const char *current_text = lv_label_get_text(s_label_status);
                char new_text[128];
                rt_snprintf(new_text, sizeof(new_text), "%s [充电中]", current_text);
                lv_label_set_text(s_label_status, new_text);
            }
        }
        else
        {
            /* Remove charging indicator */
            if (s_label_status)
            {
                const char *current_text = lv_label_get_text(s_label_status);
                char *charging_pos = rt_strstr(current_text, " [充电中]");
                if (charging_pos)
                {
                    char new_text[128];
                    int len = charging_pos - current_text;
                    rt_memcpy(new_text, current_text, len);
                    new_text[len] = '\0';
                    lv_label_set_text(s_label_status, new_text);
                }
            }
        }
        break;

    /* UI_CMD_UPDATE_BLE_STATUS - Bluetooth not used */
    /* case UI_CMD_UPDATE_BLE_STATUS: */
    /*     if (s_img_ble) { */
    /*         if (strcmp(msg->data, "open") == 0) { */
    /*             lv_img_set_src(s_img_ble, &ble); */
    /*         } else { */
    /*             lv_img_set_src(s_img_ble, &ble_close); */
    /*         } */
    /*     } */
    /*     break; */

    default:
        LOG_W("Unknown UI command: %d", msg->cmd);
        break;
    }
}

/**
 * @brief UI thread entry
 * @param args Thread arguments (unused)
 */
static void ui_thread_entry(void *args)
{
    ui_msg_t msg;
    rt_uint32_t period_ms;
    lv_font_t *font_36;
    lv_font_t *font_28;
    lv_font_t *font_22;

    (void)args;

    /* Initialize LVGL */
    lv_init();
    lv_tick_set_cb(&rt_tick_get_millisecond);
    lv_port_disp_init();

    extern void lv_port_indev_init(void);
    lv_port_indev_init();

    /* Get screen resolution for scaling */
    lv_coord_t scr_width = lv_disp_get_hor_res(NULL);
    lv_coord_t scr_height = lv_disp_get_ver_res(NULL);
    LOG_I("Screen resolution: %d x %d", scr_width, scr_height);

    /* Calculate scale factor */
    g_scale = get_scale_factor();
    LOG_I("Scale factor: %.2f", g_scale);

    /* Initialize styles with scaled fonts for 800x512 resolution */
    lv_style_init(&s_style_30);
    font_36 = lv_tiny_ttf_create_data(xiaozhi_font, xiaozhi_font_size, (int)(36 * g_scale));
    lv_style_set_text_font(&s_style_30, font_36);
    lv_style_set_text_align(&s_style_30, LV_TEXT_ALIGN_CENTER);
    lv_style_set_text_color(&s_style_30, lv_color_hex(0xffffff));

    lv_style_init(&s_style_24);
    font_28 = lv_tiny_ttf_create_data(xiaozhi_font, xiaozhi_font_size, (int)(28 * g_scale));
    lv_style_set_text_font(&s_style_24, font_28);
    lv_style_set_text_align(&s_style_24, LV_TEXT_ALIGN_CENTER);
    lv_style_set_text_color(&s_style_24, lv_color_hex(0xffffff));

    lv_style_init(&s_style_20);
    font_22 = lv_tiny_ttf_create_data(xiaozhi_font, xiaozhi_font_size, (int)(22 * g_scale));
    lv_style_set_text_font(&s_style_20, font_22);
    lv_style_set_text_align(&s_style_20, LV_TEXT_ALIGN_CENTER);
    lv_style_set_text_color(&s_style_20, lv_color_hex(0xffffff));

    /* Initialize UI objects */
    if (ui_objects_init() != RT_EOK)
    {
        LOG_E("UI objects init failed");
        return;
    }

    /* Set initial display */
    if (s_label_status) lv_label_set_text(s_label_status, "初始化中...");
    if (s_label_info) lv_label_set_text(s_label_info, " ");
    if (s_label_adc) lv_label_set_text(s_label_adc, " ");
    if (s_label_output) lv_label_set_text(s_label_output, " ");
    ui_show_emoji(0);
    lv_task_handler();

    /* Signal initialization complete */
    rt_sem_release(&s_ui_init_sem);
    LOG_I("UI initialized for 800x512 resolution");

    /* Main loop */
    while (1)
    {
        if (rt_mq_recv(&s_ui_mq, &msg, sizeof(msg), RT_WAITING_NO) > 0)
        {
            ui_process_message(&msg);
        }

        period_ms = lv_task_handler();
        if(period_ms == LV_NO_TIMER_READY || period_ms > 100)
            period_ms = 20;

        rt_thread_mdelay(period_ms);
    }
}

/*****************************************************************************
 * Public Functions
 *****************************************************************************/

void xiaozhi_ui_init(void)
{
    rt_thread_t tid;

    /* Initialize synchronization primitives */
    rt_sem_init(&s_ui_init_sem, "ui_sem", 0, RT_IPC_FLAG_PRIO);
    rt_mq_init(&s_ui_mq, "ui_mq", s_mq_pool, sizeof(ui_msg_t),
               sizeof(s_mq_pool), RT_IPC_FLAG_FIFO);

    /* Create UI thread */
    tid = rt_thread_create("xz_ui", ui_thread_entry, RT_NULL,
                           UI_THREAD_STACK, UI_THREAD_PRIORITY, UI_THREAD_TICK);
    if (tid != RT_NULL)
    {
        rt_thread_startup(tid);
    }
    else
    {
        LOG_E("Create UI thread failed");
    }
}

rt_err_t xiaozhi_ui_wait_ready(rt_int32_t timeout)
{
    return rt_sem_take(&s_ui_init_sem, timeout);
}

void xiaozhi_ui_set_status(const char *status)
{
    ui_send_message(UI_CMD_SET_STATUS, status, "");
}

void xiaozhi_ui_set_output(const char *output)
{
    ui_send_message(UI_CMD_SET_OUTPUT, output, "");
}

void xiaozhi_ui_set_snore_result(bool detected, float score)
{
    xiaozhi_ui_set_snore_inference(detected, detected, false, score);
}

void xiaozhi_ui_set_snore_inference(bool model_positive,
                                    bool alert_triggered,
                                    bool alert_suppressed,
                                    float score)
{
    char tmp[48];
    rt_snprintf(tmp, sizeof(tmp), "%d,%d,%d,%.3f",
                model_positive ? 1 : 0,
                alert_triggered ? 1 : 0,
                alert_suppressed ? 1 : 0,
                score);
    ui_send_message(UI_CMD_SET_SNORE_RESULT, tmp, "0,0,0,0.0");
}

void xiaozhi_ui_set_snore_guard_state(bool enabled)
{
    ui_send_message(UI_CMD_SET_SNORE_GUARD,
                    enabled ? "enabled" : "paused",
                    "paused");
}

void xiaozhi_ui_show_alarm_ring(void)
{
    ui_send_message(UI_CMD_SHOW_ALARM_RING, "ring", "ring");
}

void xiaozhi_ui_hide_alarm_ring(void)
{
    ui_send_message(UI_CMD_HIDE_ALARM_RING, "stop", "stop");
}

void xiaozhi_ui_refresh_alarm_clock(void)
{
    ui_send_message(UI_CMD_REFRESH_ALARM, "refresh", "refresh");
}

void xiaozhi_ui_show_emergency(const char *phrase)
{
    ui_send_message(UI_CMD_SHOW_EMERGENCY, phrase, "求助语音");
}

void xiaozhi_ui_set_emergency_resolution(bool success)
{
    ui_send_message(UI_CMD_SET_EMERGENCY_RESOLUTION,
                    success ? "success" : "failed",
                    "failed");
}

void xiaozhi_ui_set_emoji(const char *emoji)
{
    ui_send_message(UI_CMD_SET_EMOJI, emoji, "neutral");
}

void xiaozhi_ui_set_adc(const char *adc_str)
{
    ui_send_message(UI_CMD_SET_ADC, adc_str, "");
}

void xiaozhi_ui_set_environment(float temperature_c,
                                float humidity_pct,
                                bool valid,
                                const char *status)
{
    char tmp[UI_MSG_DATA_SIZE];
    const char *state = (status && status[0] != '\0') ? status : "UNKNOWN";

    if (valid)
    {
        int temp_x10 = (temperature_c >= 0.0f) ?
                       (int)(temperature_c * 10.0f + 0.5f) :
                       (int)(temperature_c * 10.0f - 0.5f);
        int humidity_x10 = (humidity_pct >= 0.0f) ?
                           (int)(humidity_pct * 10.0f + 0.5f) :
                           (int)(humidity_pct * 10.0f - 0.5f);
        int temp_abs = temp_x10 < 0 ? -temp_x10 : temp_x10;
        int humidity_abs = humidity_x10 < 0 ? -humidity_x10 : humidity_x10;

        rt_snprintf(tmp, sizeof(tmp), "Env %s%d.%dC  %d.%d%%RH  %s",
                    temp_x10 < 0 ? "-" : "",
                    temp_abs / 10,
                    temp_abs % 10,
                    humidity_abs / 10,
                    humidity_abs % 10,
                    state);
    }
    else
    {
        rt_snprintf(tmp, sizeof(tmp), "Env sensor %s", state);
    }

    ui_send_message(UI_CMD_SET_ENVIRONMENT, tmp, "");
}

void xiaozhi_ui_clear_info(void)
{
    ui_send_message(UI_CMD_CLEAR_INFO, RT_NULL, RT_NULL);
}

void xiaozhi_ui_show_ap_config(void)
{
    ui_send_message(UI_CMD_SHOW_AP_INFO, RT_NULL, RT_NULL);
}

void xiaozhi_ui_show_connecting(void)
{
    ui_send_message(UI_CMD_SHOW_CONNECTING, RT_NULL, RT_NULL);
}

void xiaozhi_ui_update_battery(int level)
{
    char battery_str[16];
    rt_snprintf(battery_str, sizeof(battery_str), "%d", level);
    ui_send_message(UI_CMD_UPDATE_BATTERY, battery_str, "100");
}

void xiaozhi_ui_update_charging_status(bool is_charging)
{
    const char *status = is_charging ? "charging" : "discharging";
    ui_send_message(UI_CMD_UPDATE_CHARGE_STATUS, status, "discharging");
}

void xiaozhi_ui_update_ble_status(bool connected)
{
    /* Bluetooth functionality not implemented */
    LOG_W("Bluetooth status update not implemented");
    /* If needed in future, implement with different approach */
}


/*****************************************************************************
 * Legacy API Compatibility
 *****************************************************************************/

/* Keep old function names for backward compatibility */
void init_ui(void)
{
    xiaozhi_ui_init();
}

rt_err_t wait_ui_ready(rt_int32_t timeout)
{
    return xiaozhi_ui_wait_ready(timeout);
}

void clean_info(void)
{
    xiaozhi_ui_clear_info();
}

void xiaozhi_ui_chat_status(char *string)
{
    xiaozhi_ui_set_status(string);
}

void xiaozhi_ui_chat_output(char *string)
{
    xiaozhi_ui_set_output(string);
}

void xiaozhi_ui_update_emoji(char *string)
{
    xiaozhi_ui_set_emoji(string);
}

void xiaozhi_ui_update_adc(char *string)
{
    xiaozhi_ui_set_adc(string);
}
