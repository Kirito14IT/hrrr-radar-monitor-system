/******************************************************************************
* Copyright (c) 2021 Shanghai QDay Technology Co., Ltd.
* All rights reserved.
*
* This file is part of the LiteGFX 0.0.1 distribution.
*
* This software is licensed under terms that can be found in the LICENSE file in
* the root directory of this software component.
* If no LICENSE file comes with this software, it is provided AS-IS.
*
* Author:LiteGFX Team
* Date:2021.12.05
*******************************************************************************/

/*********************
 *      INCLUDES
 *********************/
#include "lx_platform_time.h"
#include <time.h>
#include "cyabs_rtos.h"

 /*********************
 *      DEFINES
 *********************/


 /**********************
 *      TYPEDEFS
 **********************/


 /**********************
 *  STATIC PROTOTYPES
 **********************/


 /**********************
  *  STATIC VARIABLES
  **********************/


/**********************
*  GLOBAL VARIABLES
**********************/


/**********************
*      MACROS
**********************/


/**********************
*   GLOBAL FUNCTIONS
**********************/
void lx_platform_get_time(lx_platform_time_t* time_p)
{
    static uint32_t start_ms = 0;
    static uint8_t last_sec = 0;

    struct tm *p_tm;
    time_t now = time(NULL);
    p_tm = localtime(&now);

    if(last_sec != p_tm->tm_sec)
    {
      start_ms = (xTaskGetTickCount() * portTICK_PERIOD_MS);
    }

    last_sec = p_tm->tm_sec;

    time_p->year = p_tm->tm_year + 1900;
    time_p->month = p_tm->tm_mon + 1;
    time_p->mday = p_tm->tm_mday;
    time_p->hour = p_tm->tm_hour;
    time_p->minute = p_tm->tm_min;
    time_p->second = p_tm->tm_sec;
    time_p->weekday = p_tm->tm_wday;
    time_p->millisecond = (xTaskGetTickCount() * portTICK_PERIOD_MS) - start_ms;
}

/**********************
 *   STATIC FUNCTIONS
 **********************/

