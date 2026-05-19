/**
 * @file lv_virtual3d.c
 *
 */

/*********************
 *      INCLUDES
 *********************/
#include "lv_virtual3d.h"
#include <stdint.h>
#include "lv_vg_lite_utils.h"

#if 1//LV_USE_LX_VIRTUAL3D
// #include "lv_vglite_buf.h"
#include "lx_vglite_api.h"
#include "cyabs_rtos.h"

/*********************
 *      DEFINES
 *********************/
#define MY_CLASS &lv_virtual3d_class


/**********************
 *      TYPEDEFS
 **********************/


/**********************
 *  STATIC PROTOTYPES
 **********************/
static void virtual3d_constructor(const lv_obj_class_t * class_p, lv_obj_t * obj);
static void virtual3d_destructor(const lv_obj_class_t * class_p, lv_obj_t * obj);
static void virtual3d_event(const lv_obj_class_t * class_p, lv_event_t * e);
static void virtual3d_timer_cb(lv_timer_t* timer);
static void virtual3d_update_pos(lv_obj_t * obj);
static void virtual3d_clear_bg(lv_obj_t * obj);

/**********************
 *  STATIC VARIABLES
 **********************/
const lv_obj_class_t lv_virtual3d_class = {
    .constructor_cb = virtual3d_constructor,
    .destructor_cb = virtual3d_destructor,
    .event_cb = virtual3d_event,
    .width_def = LV_SIZE_CONTENT,
    .height_def = LV_SIZE_CONTENT,
    .instance_size = sizeof(lv_virtual3d_t),
    .base_class = &lv_obj_class
};


/**********************
 *      MACROS
 **********************/

/**********************
 *   GLOBAL FUNCTIONS
 **********************/

/**
* @brief Create virtual 3d object.
* @param parent: parent obj. @ref lv_obj_create
* @return object created.
*/
lv_obj_t * lv_virtual3d_create(lv_obj_t * parent, uint32_t instance, uint32_t bg_color)
{
    lv_obj_t * obj = lv_obj_class_create_obj(MY_CLASS, parent);

    lv_virtual3d_t * virtual3d = (lv_virtual3d_t *)obj;

    virtual3d->vg_buf.width = LX_HOR_RES;
    virtual3d->vg_buf.height = LX_VER_RES;
    virtual3d->handler = 0;
    virtual3d->callback = NULL;
    virtual3d->setuped = false;
    virtual3d->instance = instance;
    virtual3d->bg_color = bg_color;
    virtual3d->last_pos_x = 0;
    virtual3d->last_pos_y = 0;


    lv_obj_class_init_obj(obj);
    lv_obj_set_pos(obj, 0, 0);
    lv_obj_set_width(obj, LX_HOR_RES);
    lv_obj_set_height(obj, LX_VER_RES);

    return obj;
}

void lv_virtual3d_setup(lv_obj_t * obj)
{
    lv_virtual3d_t * virtual3d = (lv_virtual3d_t *)obj;

    if(virtual3d->handler && virtual3d->setuped == false)
    {
        if(virtual3d->callback)
        {
            lx_vglite_user_cb_t cb = (lx_vglite_user_cb_t)virtual3d->callback;
            cb(LX_CMD_ID_INIT, 0, (uint32_t)obj);
        }

        virtual3d_update_pos(obj);
        lx_vglite_setup(virtual3d->handler);
        virtual3d->setuped = true;

        if(virtual3d->anim_timer == NULL)
        {
            virtual3d->anim_timer = lv_timer_create(virtual3d_timer_cb, 50, (void*)virtual3d);
            lv_timer_set_repeat_count(virtual3d->anim_timer, -1);            
        }
    }
}

void lv_virtual3d_teardown(lv_obj_t * obj)
{
    lv_virtual3d_t * virtual3d = (lv_virtual3d_t *)obj;

     if(virtual3d->handler && virtual3d->setuped)
     {
          lx_vglite_teardown(virtual3d->handler);
          virtual3d->setuped = false;

          if(virtual3d->callback)
          {
              lx_vglite_user_cb_t cb = (lx_vglite_user_cb_t)virtual3d->callback;
              cb(LX_CMD_ID_DEINIT, 0, (uint32_t)obj);
          }

          if(virtual3d->anim_timer)
          {
              lv_timer_del(virtual3d->anim_timer);
              virtual3d->anim_timer = NULL;
          }
     }    
}

/*=====================
 * Setter functions
 *====================*/
 /**
* @brief  add 1 item.
* @param  obj: virtual 3d object
* @param  image: item image.
* @return int16_t : item id added or -1 if error happend.
*/
void lv_virtual3d_set_image_ex(lv_obj_t * obj, uint8_t index, const lv_image_dsc_t* image, uint32_t prop)
{
    lv_virtual3d_t * virtual3d = (lv_virtual3d_t *)obj;

    if(virtual3d->handler)
    {
        LV_LOG("lv_virtual3d_set_image_ex  image->header.cf =%d\n",image->header.cf);
        vg_lite_buffer_format_t format = (vg_lite_buffer_format_t)lv_vg_lite_vg_fmt((lv_color_format_t)image->header.cf);
        void* image_data = (void*)image->data;
        LV_LOG("lv_virtual3d_set_image_ex  format =%d\n",format);

         /*
        if(image->header.cf == LV_COLOR_FORMAT_RGB565A8)
        {
            format = vglite_get_buf_format(LV_COLOR_FORMAT_RGB565A8);
        }
        else if(image->header.cf == LV_COLOR_FORMAT_RGB888)
        {
            format = vglite_get_buf_format(LV_COLOR_FORMAT_RGB888);
        }        
        else if(image->header.cf == LV_COLOR_FORMAT_ARGB8888)
        {
            format = vglite_get_buf_format(LV_COLOR_FORMAT_ARGB8888);;
        }
        else if(image->header.cf == LV_COLOR_FORMAT_ETC2)
        {
            format = vglite_get_buf_format(LV_COLOR_FORMAT_ETC2);
        }
         */

        lx_vglite_set_image_ex(virtual3d->handler, index, image_data, format, image->header.w, image->header.h, prop);
    }

}

void lv_virtual3d_set_image(lv_obj_t * obj, uint8_t index, const lv_image_dsc_t* image)
{
    lv_virtual3d_set_image_ex(obj, index, image, 0);
}


void lv_virtual3d_set_texture_ex(lv_obj_t * obj, uint8_t index, const lv_image_dsc_t* image, uint32_t prop)
{
    lv_virtual3d_t * virtual3d = (lv_virtual3d_t *)obj;

    if(virtual3d->handler)
    {
        vg_lite_buffer_format_t format = (vg_lite_buffer_format_t)lv_vg_lite_vg_fmt(image->header.cf);
        void* image_data = (void*)image->data;

        lx_vglite_set_texture_ex(virtual3d->handler, index, image_data, format, image->header.w, image->header.h, prop);
    }

}

void lv_virtual3d_set_texture(lv_obj_t * obj, uint8_t index, const lv_image_dsc_t* image)
{
    lv_virtual3d_set_texture_ex(obj, index, image, 0);
}


void lv_virtual3d_set_model(lv_obj_t * obj, uint8_t index, void* data, uint32_t size)
{
    lv_virtual3d_t * virtual3d = (lv_virtual3d_t *)obj;

    if(virtual3d->handler)
    {
        lx_vglite_set_model(virtual3d->handler, index, data, size);
    }
}

void lv_virtual3d_set_param(lv_obj_t * obj, uint16_t cmd, uint32_t param)
{
    lv_virtual3d_t * virtual3d = (lv_virtual3d_t *)obj;

    if(virtual3d->handler)
    {
        lx_vglite_set_param(virtual3d->handler, cmd, param);
    }

}

void lv_virtual3d_set_param2(lv_obj_t * obj,  const char* cmd, uint32_t param)
{
    lv_virtual3d_t * virtual3d = (lv_virtual3d_t *)obj;

    if(virtual3d->handler)
    {
        lx_vglite_set_param2(virtual3d->handler, cmd, param);
    }

}

void lv_virtual3d_set_user_callback(lv_obj_t * obj, void* callback, uint32_t user_data)
{
     lv_virtual3d_t * virtual3d = (lv_virtual3d_t *)obj;

     if(virtual3d->handler)
     {
        virtual3d->callback = callback;
        lx_vglite_set_user_callback(virtual3d->handler, (lx_vglite_user_cb_t)callback, user_data);
     }
}

/*=====================
 * Getter functions
 *====================*/
uint32_t lx_virtual3d_get_vglite_format(lv_color_format_t cf)
{
    vg_lite_buffer_format_t vg_buffer_format = VG_LITE_RGB565;

    switch(cf) {
        case LV_COLOR_FORMAT_L8:
            vg_buffer_format = VG_LITE_L8;
            break;
        case LV_COLOR_FORMAT_A4:
            vg_buffer_format = VG_LITE_A4;
            break;
        case LV_COLOR_FORMAT_A8:
            vg_buffer_format = VG_LITE_A8;
            break;
        case LV_COLOR_FORMAT_I1:
            vg_buffer_format = VG_LITE_INDEX_1;
            break;
        case LV_COLOR_FORMAT_I2:
            vg_buffer_format = VG_LITE_INDEX_2;
            break;
        case LV_COLOR_FORMAT_I4:
            vg_buffer_format = VG_LITE_INDEX_4;
            break;
        case LV_COLOR_FORMAT_I8:
            vg_buffer_format = VG_LITE_INDEX_8;
            break;
        case LV_COLOR_FORMAT_RGB565:
            vg_buffer_format = VG_LITE_RGB565;
            break;
        case LV_COLOR_FORMAT_RGB565A8:
            vg_buffer_format = VG_LITE_ARGB8565;
            break;
        case LV_COLOR_FORMAT_RGB888:
            vg_buffer_format = VG_LITE_RGB888;
            break;
        case LV_COLOR_FORMAT_ARGB8888:
            vg_buffer_format = VG_LITE_RGBA8888;
            break;
        case LV_COLOR_FORMAT_XRGB8888:
            vg_buffer_format = VG_LITE_RGBX8888;
            break;
/*        case LV_COLOR_FORMAT_ETC2:
            vg_buffer_format = VG_LITE_RGBA8888_ETC2_EAC;
            break;*/

        default:
            break;
    }

    return (uint32_t)vg_buffer_format;
}

/**********************
 *   STATIC FUNCTIONS
 **********************/
static void virtual3d_constructor(const lv_obj_class_t * class_p, lv_obj_t * obj)
{
     lv_virtual3d_t * virtual3d = (lv_virtual3d_t *)obj;

     virtual3d->handler = lx_vglite_init(virtual3d->instance, (vg_lite_buffer_t *)&virtual3d->vg_buf, LX_HOR_RES, LX_VER_RES);

}

static void virtual3d_destructor(const lv_obj_class_t * class_p, lv_obj_t * obj)
{
     lv_virtual3d_t * virtual3d = (lv_virtual3d_t *)obj;

     if(virtual3d->handler)
     {
          lv_virtual3d_teardown(obj);

          lx_vglite_deinit(virtual3d->handler);
          virtual3d->handler = 0;
     }
}

static void virtual3d_event(const lv_obj_class_t * class_p, lv_event_t * e)
{
      LV_UNUSED(class_p);
      lv_res_t res;
      /*Call the ancestor's event handler*/
      res = lv_obj_event_base(MY_CLASS, e);
      if(res != LV_RES_OK)
      {
          return;
      }
      lv_event_code_t code = lv_event_get_code(e);
      lv_obj_t* obj = lv_event_get_target(e);

      lv_virtual3d_t *virtual3d = (lv_virtual3d_t*)obj;

      if(code == LV_EVENT_PRESSED)
      {
          lv_point_t pt = { 0 };	
          
          lv_indev_get_point(lv_indev_get_act(), &pt);

          if(virtual3d->setuped)
          {
              lx_vglite_touch(virtual3d->handler, LX_TOUCH_DOWN, pt.x, pt.y);
          }
      }
      else if(code == LV_EVENT_PRESSING)
      {
          lv_point_t pt = { 0 };	
          
          lv_indev_get_point(lv_indev_get_act(), &pt);	

          if(virtual3d->setuped)
          {
              lx_vglite_touch(virtual3d->handler, LX_TOUCH_MOVE, pt.x, pt.y);
          }          
      }
      else if(code == LV_EVENT_RELEASED)
      {
          lv_point_t pt = { 0 };	
          
          lv_indev_get_point(lv_indev_get_act(), &pt);	

          if(virtual3d->setuped)
          {
              lx_vglite_touch(virtual3d->handler, LX_TOUCH_UP, pt.x, pt.y);
          }          
      }
      else if(code == LV_EVENT_DRAW_MAIN)
      {
          if(virtual3d->setuped)
          {
              lv_layer_t* layer = lv_event_get_layer(e);

              lv_vg_lite_buffer_from_draw_buf(&virtual3d->vg_buf, layer->draw_buf);

              if(virtual3d->bg_color)
              {
                  virtual3d_clear_bg(obj);
              }
              
              uint32_t start_time_ms = (xTaskGetTickCount() * portTICK_PERIOD_MS);
              lx_vglite_render(virtual3d->handler, 
                              layer->buf_area.x1,
                              layer->buf_area.y1,
                              layer->buf_area.x2,
                              layer->buf_area.y2);
              //printf("lx_vglite_render: %d ms x1 = %d, y1 = %d\n", (xTaskGetTickCount() * portTICK_PERIOD_MS) - start_time_ms, layer->buf_area.x1, layer->buf_area.y1);

              vg_lite_finish();
          }
      }
      else if(code == LV_EVENT_GET_SELF_SIZE)
      {
          lv_point_t * p = lv_event_get_param(e);
          p->x = LX_HOR_RES;
          p->y = LX_VER_RES;
      }
}

/**
* @brief  rotation anim timer callback.
* @param  timer
* @return none
*/
static void virtual3d_timer_cb(lv_timer_t* timer)
{
    lv_virtual3d_t * virtual3d = (lv_virtual3d_t *)timer->user_data;

    if(virtual3d->handler)
    {
        virtual3d_update_pos((lv_obj_t *)virtual3d);
        
        uint32_t start_time_ms = (xTaskGetTickCount() * portTICK_PERIOD_MS);
        lx_vglite_update(virtual3d->handler);
        //printf("lx_vglite_update: %d ms\n", (xTaskGetTickCount() * portTICK_PERIOD_MS) - start_time_ms);

        lv_obj_invalidate((const lv_obj_t *)virtual3d);
    }
}

static void virtual3d_update_pos(lv_obj_t * obj)
{
    lv_virtual3d_t * virtual3d = (lv_virtual3d_t *)obj;

    lv_area_t area = { 0 };

    lv_obj_get_coords(obj, &area);

    if(virtual3d->last_pos_x != area.x1 || virtual3d->last_pos_y != area.y1)
    {
        uint32_t pos = (area.x1 << 16) | (area.y1 & 0xffff);
        lx_vglite_set_param(virtual3d->handler, LX_CMD_ID_SET_POS, (uintptr_t)pos);

        virtual3d->last_pos_x = area.x1;
        virtual3d->last_pos_y = area.y1;
    }
}

static void virtual3d_clear_bg(lv_obj_t * obj)
{
    lv_virtual3d_t * virtual3d = (lv_virtual3d_t *)obj;

    /*vg_lite_rectangle_t rect = { 0 };

    rect.x = virtual3d->last_pos_x;
    rect.y = virtual3d->last_pos_y;
    rect.width = LX_HOR_RES;
    rect.height = LX_VER_RES;*/

    vg_lite_clear((vg_lite_buffer_t *)&virtual3d->vg_buf, NULL, virtual3d->bg_color);    
}

#endif //LV_USE_LX_VIRTUAL3D
