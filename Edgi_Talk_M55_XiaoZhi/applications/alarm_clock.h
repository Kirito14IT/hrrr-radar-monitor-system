#ifndef __ALARM_CLOCK_H__
#define __ALARM_CLOCK_H__

#include <rtthread.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct
{
    rt_bool_t enabled;
    int hour;
    int minute;
} alarm_clock_config_t;

int alarm_clock_init(void);
void alarm_clock_get(alarm_clock_config_t *config);
int alarm_clock_set(const alarm_clock_config_t *config);
void alarm_clock_dismiss(void);

#ifdef __cplusplus
}
#endif

#endif
