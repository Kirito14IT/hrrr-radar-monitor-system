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
    UI_CMD_SET_MEOW_RESULT,
    UI_CMD_SET_EMOJI,
    UI_CMD_SET_ADC,
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

/* Meow detection mode flag */
static rt_bool_t s_meow_mode = RT_FALSE;
static lv_obj_t *s_main_screen = RT_NULL;
static lv_obj_t *s_meow_screen = RT_NULL;
static lv_obj_t *s_meow_label_title = RT_NULL;
static lv_obj_t *s_meow_label_result = RT_NULL;
static lv_obj_t *s_meow_label_score = RT_NULL;
static lv_obj_t *s_meow_panel = RT_NULL;
static lv_obj_t *s_btn_meow = RT_NULL;
static lv_obj_t *s_lbl_meow = RT_NULL;
static lv_obj_t *s_meow_cat_canvas = RT_NULL;

static void meow_back_btn_event_cb(lv_event_t *e);
static void meow_build_screen(void);

/* Large canvas buffer for cat pixel art (ARGB8888) */
static uint8_t s_meow_cat_buf[360 * 240 * 4] rt_section(".m33_m55_shared_hyperram");

static inline void meow_canvas_px(lv_obj_t *canvas, int w, int h, int x, int y, lv_color_t col)
{
    if (!canvas)
        return;
    if (x < 0 || y < 0 || x >= w || y >= h)
        return;
    lv_canvas_set_px(canvas, x, y, col, LV_OPA_COVER);
}

static void meow_draw_cat_pixelart(lv_obj_t *canvas)
{
    if (!canvas)
        return;

    const int W = 360;
    const int H = 240;
    lv_canvas_set_buffer(canvas, s_meow_cat_buf, W, H, LV_COLOR_FORMAT_ARGB8888);
    lv_canvas_fill_bg(canvas, lv_color_black(), LV_OPA_TRANSP);

    const lv_color_t O = lv_color_hex(0x111111);  /* outline */
    const lv_color_t G1 = lv_color_hex(0xB9B9B9); /* fur light */
    const lv_color_t G2 = lv_color_hex(0x8F8F8F); /* fur dark */
    const lv_color_t P = lv_color_hex(0xFF8FB1);  /* cheeks */

    /* helpers */
    const int S = 7; /* pixel scale */
    const int ox = 40;
    const int oy = 10;

    auto_draw:
    (void)S;

    /* draw a scaled pixel */
    #define PX(xx,yy,col) do { \
        for(int sy=0; sy<S; sy++) for(int sx=0; sx<S; sx++) \
            meow_canvas_px(canvas, W, H, (ox + (xx)*S + sx), (oy + (yy)*S + sy), (col)); \
    } while(0)

    /* draw filled rect in scaled pixels */
    #define RECT(x0,y0,x1,y1,col) do { \
        for(int yy=(y0); yy<=(y1); yy++) for(int xx=(x0); xx<=(x1); xx++) PX(xx,yy,(col)); \
    } while(0)

    /* speech bubble */
    RECT(6, 0, 34, 10, lv_color_hex(0xFFFFFF));
    /* border */
    for (int x = 6; x <= 34; x++) { PX(x, 0, O); PX(x, 10, O); }
    for (int y = 0; y <= 10; y++) { PX(6, y, O); PX(34, y, O); }
    /* tail */
    RECT(10, 10, 12, 12, lv_color_hex(0xFFFFFF));
    PX(10, 10, O); PX(11, 11, O); PX(12, 12, O);
    PX(9, 10, O); PX(10, 11, O); PX(11, 12, O);

    /* "MEOW!" block letters (5x7) */
    /* M */
    RECT(9, 2, 9, 8, O); RECT(13, 2, 13, 8, O);
    PX(10, 3, O); PX(11, 4, O); PX(12, 3, O);
    /* E */
    RECT(15, 2, 15, 8, O); RECT(15, 2, 19, 2, O); RECT(15, 5, 18, 5, O); RECT(15, 8, 19, 8, O);
    /* O */
    RECT(21, 2, 25, 2, O); RECT(21, 8, 25, 8, O); RECT(21, 3, 21, 7, O); RECT(25, 3, 25, 7, O);
    /* W */
    RECT(27, 2, 27, 8, O); RECT(31, 2, 31, 8, O);
    PX(28, 7, O); PX(29, 6, O); PX(30, 7, O);
    /* ! */
    RECT(33, 2, 33, 6, O); PX(33, 8, O);

    /* cat body */
    /* base shape */
    RECT(10, 16, 30, 34, G1);
    RECT(12, 14, 28, 15, G1);
    /* ears */
    RECT(12, 12, 15, 14, G1);
    RECT(25, 12, 28, 14, G1);
    /* tail */
    RECT(30, 26, 33, 28, G1);
    RECT(33, 28, 34, 33, G1);

    /* outline (thicker) */
    for (int x = 10; x <= 30; x++) { PX(x, 16, O); PX(x, 34, O); }
    for (int y = 16; y <= 34; y++) { PX(10, y, O); PX(30, y, O); }
    for (int x = 12; x <= 28; x++) { PX(x, 14, O); PX(x, 15, O); }
    PX(12, 13, O); PX(15, 12, O); PX(25, 12, O); PX(28, 13, O);
    /* tail outline */
    for (int x = 30; x <= 33; x++) PX(x, 26, O);
    for (int y = 26; y <= 33; y++) PX(34, y, O);
    PX(33, 33, O); PX(32, 33, O);

    /* simple stripes */
    RECT(12, 20, 13, 22, G2);
    RECT(27, 20, 28, 22, G2);
    RECT(14, 26, 15, 28, G2);
    RECT(25, 26, 26, 28, G2);

    /* face */
    PX(17, 24, O); PX(23, 24, O); /* eyes */
    PX(20, 26, O);                /* nose */
    PX(19, 27, O); PX(21, 27, O); /* mouth */
    PX(16, 26, P); PX(24, 26, P); /* cheeks */

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
 * @brief Meow detect button event callback
 */
static void meow_btn_event_cb(lv_event_t *e)
{
    lv_event_code_t code = lv_event_get_code(e);
    if (code != LV_EVENT_CLICKED)
    {
        return;
    }

    /* Main screen button always means "enter meow detector". If already in meow mode,
     * ignore the click (exit is handled by the Back button on the meow screen). */
    if (s_meow_mode)
        return;

    /* Enter meow detect mode: switch screen, suspend voice, start detector */
    if (!s_meow_screen)
    {
        meow_build_screen();
    }
    if (s_meow_screen)
    {
        lv_screen_load(s_meow_screen);
    }

    xz_voice_suspend();
    if (meow_detect_start() == RT_EOK)
    {
        s_meow_mode = RT_TRUE;
        if (s_meow_label_result)
            lv_label_set_text(s_meow_label_result, "Listening...");
        if (s_meow_label_score)
            lv_label_set_text(s_meow_label_score, "-");
    }
    else
    {
        /* Failed to start meow detection, resume voice */
        xz_voice_resume();
        if (s_main_screen)
            lv_screen_load(s_main_screen);
    }
}

void xiaozhi_ui_enter_meow_mode_from_voice(void)
{
    /* 语音指令触发入口：等价于主界面点击一次 Meow detect 按钮 */
    if (s_meow_mode)
        return;

    if (!s_meow_screen)
    {
        meow_build_screen();
    }
    if (s_meow_screen)
    {
        lv_screen_load(s_meow_screen);
    }

    xz_voice_suspend();
    if (meow_detect_start() == RT_EOK)
    {
        s_meow_mode = RT_TRUE;
        if (s_meow_label_result)
            lv_label_set_text(s_meow_label_result, "Listening...");
        if (s_meow_label_score)
            lv_label_set_text(s_meow_label_score, "-");
    }
    else
    {
        xz_voice_resume();
        if (s_main_screen)
            lv_screen_load(s_main_screen);
    }
}

static void meow_back_btn_event_cb(lv_event_t *e)
{
    lv_event_code_t code = lv_event_get_code(e);
    if (code != LV_EVENT_CLICKED)
        return;

    if (s_meow_mode)
    {
        meow_detect_stop();
        xz_voice_resume();
        s_meow_mode = RT_FALSE;
    }

    if (s_main_screen)
        lv_screen_load(s_main_screen);
}

static void meow_build_screen(void)
{
    s_meow_screen = lv_obj_create(NULL);
    lv_obj_clear_flag(s_meow_screen, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_bg_color(s_meow_screen, lv_color_hex(0x0A0D12), LV_PART_MAIN | LV_STATE_DEFAULT);

    /* Center panel (outer frame) */
    s_meow_panel = lv_obj_create(s_meow_screen);
    lv_obj_remove_flag(s_meow_panel, LV_OBJ_FLAG_SCROLLABLE);
    /* 稍微缩小一点并完全居中，避免右侧被裁剪 */
    lv_obj_set_size(s_meow_panel, LV_PCT(90), LV_PCT(86));
    lv_obj_center(s_meow_panel);
    lv_obj_set_style_bg_color(s_meow_panel, lv_color_hex(0x101722), LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_set_style_bg_opa(s_meow_panel, LV_OPA_COVER, LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_set_style_radius(s_meow_panel, SCALE_DPX(18), LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_set_style_border_width(s_meow_panel, 2, LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_set_style_border_color(s_meow_panel, lv_color_hex(0x2B3A55), LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_set_style_pad_all(s_meow_panel, SCALE_DPX(18), LV_PART_MAIN | LV_STATE_DEFAULT);

    /* Title */
    s_meow_label_title = lv_label_create(s_meow_panel);
    lv_label_set_text(s_meow_label_title, "Meow detector");
    lv_obj_add_style(s_meow_label_title, &s_style_30, 0);
    lv_obj_set_width(s_meow_label_title, LV_PCT(100));
    lv_obj_set_style_text_align(s_meow_label_title, LV_TEXT_ALIGN_CENTER, LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_align(s_meow_label_title, LV_ALIGN_TOP_MID, 0, 0);

    /* Cat pixel art (shown only when detected) */
    s_meow_cat_canvas = lv_canvas_create(s_meow_panel);
    lv_obj_set_size(s_meow_cat_canvas, SCALE_DPX(360), SCALE_DPX(240));
    lv_obj_align(s_meow_cat_canvas, LV_ALIGN_TOP_MID, 0, SCALE_DPX(55));
    meow_draw_cat_pixelart(s_meow_cat_canvas);
    lv_obj_add_flag(s_meow_cat_canvas, LV_OBJ_FLAG_HIDDEN);

    /* Result */
    s_meow_label_result = lv_label_create(s_meow_panel);
    lv_label_set_text(s_meow_label_result, "Listening...");
    lv_obj_add_style(s_meow_label_result, &s_style_30, 0);
    lv_obj_set_style_text_color(s_meow_label_result, lv_color_hex(0xffffff), LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_set_width(s_meow_label_result, LV_PCT(100));
    lv_obj_set_style_text_align(s_meow_label_result, LV_TEXT_ALIGN_CENTER, LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_align_to(s_meow_label_result, s_meow_cat_canvas, LV_ALIGN_OUT_BOTTOM_MID, 0, SCALE_DPX(10));

    /* Score */
    s_meow_label_score = lv_label_create(s_meow_panel);
    lv_label_set_text(s_meow_label_score, "-");
    lv_obj_add_style(s_meow_label_score, &s_style_24, 0);
    lv_obj_set_style_text_color(s_meow_label_score, lv_color_hex(0xC7D2FE), LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_set_width(s_meow_label_score, LV_PCT(100));
    lv_obj_set_style_text_align(s_meow_label_score, LV_TEXT_ALIGN_CENTER, LV_PART_MAIN | LV_STATE_DEFAULT);
    lv_obj_align_to(s_meow_label_score, s_meow_label_result, LV_ALIGN_OUT_BOTTOM_MID, 0, SCALE_DPX(6));

    /* Back button */
    lv_obj_t *btn_back = lv_button_create(s_meow_panel);
    lv_obj_set_size(btn_back, SCALE_DPX(180), SCALE_DPX(54));
    lv_obj_align(btn_back, LV_ALIGN_BOTTOM_MID, 0, 0);
    lv_obj_add_event_cb(btn_back, meow_back_btn_event_cb, LV_EVENT_ALL, NULL);
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

    /* Meow detect button (main screen) */
    s_btn_meow = lv_button_create(screen);
    lv_obj_set_size(s_btn_meow, SCALE_DPX(200), SCALE_DPX(56));
    /* Place it above AP/SSID info area (as in the red box) */
    lv_obj_align(s_btn_meow, LV_ALIGN_CENTER, 0, SCALE_DPX(120));
    lv_obj_add_event_cb(s_btn_meow, meow_btn_event_cb, LV_EVENT_ALL, NULL);

    s_lbl_meow = lv_label_create(s_btn_meow);
    lv_label_set_text(s_lbl_meow, "Snore detect");
    lv_obj_center(s_lbl_meow);

    /* Force LED state to "stopped" at boot:
     * red on, green off, blue off (active-low handled in driver). */
    meow_detect_stop();

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

    case UI_CMD_SET_MEOW_RESULT:
        if (s_meow_label_result)
        {
            /* msg->data format: "<0/1>,<score>" */
            int det = 0;
            float score = 0.0f;
            sscanf(msg->data, "%d,%f", &det, &score);
            if (det)
            {
                lv_label_set_text(s_meow_label_result, "SNORE DETECTED");
                lv_obj_set_style_text_color(s_meow_label_result, lv_color_hex(0xff4040), LV_PART_MAIN | LV_STATE_DEFAULT);
                if (s_meow_cat_canvas)
                    lv_obj_clear_flag(s_meow_cat_canvas, LV_OBJ_FLAG_HIDDEN);
            }
            else
            {
                lv_label_set_text(s_meow_label_result, "NO SNORE");
                lv_obj_set_style_text_color(s_meow_label_result, lv_color_hex(0x888888), LV_PART_MAIN | LV_STATE_DEFAULT);
                if (s_meow_cat_canvas)
                    lv_obj_add_flag(s_meow_cat_canvas, LV_OBJ_FLAG_HIDDEN);
            }
            if (s_meow_label_score)
            {
                char tmp[32];
                rt_snprintf(tmp, sizeof(tmp), "score: %.2f", score);
                lv_label_set_text(s_meow_label_score, tmp);
                lv_obj_set_style_text_color(s_meow_label_score,
                                            det ? lv_color_hex(0xffffff) : lv_color_hex(0x888888),
                                            LV_PART_MAIN | LV_STATE_DEFAULT);
            }
        }
        break;

    case UI_CMD_SET_ADC:
        if (s_label_adc)
        {
            lv_label_set_text(s_label_adc, msg->data);
        }
        break;

    case UI_CMD_SET_EMOJI:
        ui_show_emoji(ui_find_emoji_index(msg->data));
        break;

    case UI_CMD_CLEAR_INFO:
        if (s_label_info) lv_label_set_text(s_label_info, " ");
        if (s_label_output) lv_label_set_text(s_label_output, " ");
        break;

    case UI_CMD_SHOW_AP_INFO:
        if (s_label_status) lv_label_set_text(s_label_status, "连接中...");
        if (s_label_info) lv_label_set_text(s_label_info, "使用手机或电脑连接热点");
        if (s_label_output) lv_label_set_text(s_label_output, "SSID: RT-Thread-AP 密码: 123456789 IP:192.168.169.1");
        break;

    case UI_CMD_SHOW_CONNECTING:
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

void xiaozhi_ui_set_meow_result(bool detected, float score)
{
    char tmp[32];
    rt_snprintf(tmp, sizeof(tmp), "%d,%.3f", detected ? 1 : 0, score);
    ui_send_message(UI_CMD_SET_MEOW_RESULT, tmp, "0,0.0");
}

void xiaozhi_ui_set_emoji(const char *emoji)
{
    ui_send_message(UI_CMD_SET_EMOJI, emoji, "neutral");
}

void xiaozhi_ui_set_adc(const char *adc_str)
{
    ui_send_message(UI_CMD_SET_ADC, adc_str, "");
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
