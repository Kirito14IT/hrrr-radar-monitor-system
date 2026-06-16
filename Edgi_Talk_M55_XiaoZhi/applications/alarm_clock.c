#include "alarm_clock.h"

#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#include "xiaozhi/xiaozhi.h"
#include "xiaozhi/ui/xiaozhi_ui.h"

#ifdef RT_USING_FINSH
#include <finsh.h>
#endif

#define DBG_TAG "alarm.clock"
#define DBG_LVL DBG_INFO
#include <rtdbg.h>

#define ALARM_CONFIG_FILE "/flash/alarm.cfg"
#define ALARM_CONFIG_TMP_FILE "/flash/alarm.tmp"

static alarm_clock_config_t s_config = {RT_FALSE, 7, 0};
static struct rt_mutex s_config_lock;
static rt_bool_t s_lock_ready = RT_FALSE;
static rt_bool_t s_config_loaded = RT_FALSE;
static int s_last_fired_day = -1;

static void alarm_clock_lock(void)
{
    if (s_lock_ready)
    {
        rt_mutex_take(&s_config_lock, RT_WAITING_FOREVER);
    }
}

static void alarm_clock_unlock(void)
{
    if (s_lock_ready)
    {
        rt_mutex_release(&s_config_lock);
    }
}

static int alarm_clock_load(void)
{
    char text[24] = {0};
    int enabled = 0;
    int hour = 7;
    int minute = 0;
    int fd = open(ALARM_CONFIG_FILE, O_RDONLY);
    if (fd < 0)
    {
        return -RT_ERROR;
    }

    int length = read(fd, text, sizeof(text) - 1);
    close(fd);
    if (length <= 0 || sscanf(text, "%d,%d,%d", &enabled, &hour, &minute) != 3)
    {
        return -RT_ERROR;
    }
    if (hour < 0 || hour > 23 || minute < 0 || minute > 59)
    {
        return -RT_EINVAL;
    }

    alarm_clock_lock();
    s_config.enabled = enabled ? RT_TRUE : RT_FALSE;
    s_config.hour = hour;
    s_config.minute = minute;
    alarm_clock_unlock();
    return RT_EOK;
}

static int alarm_clock_save(const alarm_clock_config_t *config)
{
    char text[24];
    int length = rt_snprintf(text, sizeof(text), "%d,%d,%d\n",
                             config->enabled ? 1 : 0,
                             config->hour,
                             config->minute);
    int fd = open(ALARM_CONFIG_TMP_FILE, O_WRONLY | O_CREAT | O_TRUNC, 0);
    if (fd < 0)
    {
        LOG_W("open config failed");
        return -RT_ERROR;
    }

    int written = write(fd, text, length);
    if (written == length)
    {
        fsync(fd);
    }
    close(fd);
    if (written != length)
    {
        unlink(ALARM_CONFIG_TMP_FILE);
        return -RT_ERROR;
    }

    unlink(ALARM_CONFIG_FILE);
    if (rename(ALARM_CONFIG_TMP_FILE, ALARM_CONFIG_FILE) != 0)
    {
        unlink(ALARM_CONFIG_TMP_FILE);
        return -RT_ERROR;
    }
    return RT_EOK;
}

void alarm_clock_get(alarm_clock_config_t *config)
{
    if (!config)
    {
        return;
    }
    alarm_clock_lock();
    *config = s_config;
    alarm_clock_unlock();
}

int alarm_clock_set(const alarm_clock_config_t *config)
{
    if (!config || config->hour < 0 || config->hour > 23 ||
        config->minute < 0 || config->minute > 59)
    {
        return -RT_EINVAL;
    }

    alarm_clock_lock();
    s_config = *config;
    alarm_clock_unlock();
    s_last_fired_day = -1;
    return alarm_clock_save(config);
}

void alarm_clock_dismiss(void)
{
    xz_stop_alarm_clock();
}

static void alarm_clock_thread(void *parameter)
{
    (void)parameter;
    int load_retries = 0;

    while (!s_config_loaded && load_retries++ < 30)
    {
        if (alarm_clock_load() == RT_EOK)
        {
            s_config_loaded = RT_TRUE;
            xiaozhi_ui_refresh_alarm_clock();
            break;
        }
        rt_thread_mdelay(1000);
    }

    while (1)
    {
        time_t now = time(RT_NULL);
        struct tm local_time;
        alarm_clock_config_t config;
        alarm_clock_get(&config);

        if (localtime_r(&now, &local_time) != RT_NULL &&
            local_time.tm_year >= 120)
        {
            int day_key = (local_time.tm_year * 400) + local_time.tm_yday;
            if (config.enabled &&
                local_time.tm_hour == config.hour &&
                local_time.tm_min == config.minute &&
                day_key != s_last_fired_day)
            {
                s_last_fired_day = day_key;
                LOG_I("alarm fired at %02d:%02d", config.hour, config.minute);
                xiaozhi_ui_show_alarm_ring();
                xz_trigger_alarm_clock();
            }
        }
        rt_thread_mdelay(1000);
    }
}

int alarm_clock_init(void)
{
    if (!s_lock_ready)
    {
        rt_mutex_init(&s_config_lock, "alarmcfg", RT_IPC_FLAG_FIFO);
        s_lock_ready = RT_TRUE;
    }

    rt_thread_t tid = rt_thread_create(
        "alarmclk",
        alarm_clock_thread,
        RT_NULL,
        1536,
        24,
        20);
    if (!tid)
    {
        return -RT_ENOMEM;
    }
    rt_thread_startup(tid);
    return RT_EOK;
}

#ifdef RT_USING_FINSH
static int alarm_clock_cmd(int argc, char **argv)
{
    alarm_clock_config_t config;
    alarm_clock_get(&config);
    if (argc == 1)
    {
        rt_kprintf("alarm: enabled=%d time=%02d:%02d\n",
                   config.enabled, config.hour, config.minute);
        return 0;
    }
    if (argc != 4)
    {
        rt_kprintf("usage: alarm_clock <0|1> <hour> <minute>\n");
        return -1;
    }
    config.enabled = atoi(argv[1]) ? RT_TRUE : RT_FALSE;
    config.hour = atoi(argv[2]);
    config.minute = atoi(argv[3]);
    return alarm_clock_set(&config);
}
MSH_CMD_EXPORT_ALIAS(alarm_clock_cmd, alarm_clock, show or set daily alarm);

static int alarm_test(void)
{
    xiaozhi_ui_show_alarm_ring();
    xz_trigger_alarm_clock();
    return RT_EOK;
}
MSH_CMD_EXPORT(alarm_test, Show and play the alarm clock immediately);
#endif
