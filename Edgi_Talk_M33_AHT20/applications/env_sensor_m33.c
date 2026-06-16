#include <rtthread.h>
#include <rtdevice.h>

#include "aht10.h"
#include "env_shared_memory.h"

#define DBG_TAG "env.m33"
#define DBG_LVL DBG_INFO
#include <rtdbg.h>

#define ENV_SENSOR_THREAD_STACK     2048
#define ENV_SENSOR_THREAD_PRIORITY  20
#define ENV_SENSOR_THREAD_TICK      10
#define ENV_SENSOR_PERIOD_MS        2000

static aht10_device_t s_aht20_dev = RT_NULL;
static float s_last_temperature_c = 0.0f;
static float s_last_humidity_pct = 0.0f;
static rt_bool_t s_last_valid = RT_FALSE;

static int16_t env_float_to_x10(float value)
{
    if (value >= 0.0f)
    {
        return (int16_t)(value * 10.0f + 0.5f);
    }
    return (int16_t)(value * 10.0f - 0.5f);
}

static rt_bool_t env_sample_is_valid(float temperature_c, float humidity_pct)
{
    if (temperature_c <= -45.0f || temperature_c > 85.0f)
    {
        return RT_FALSE;
    }

    if (humidity_pct < 0.0f || humidity_pct > 100.0f)
    {
        return RT_FALSE;
    }

    return RT_TRUE;
}

static void env_sensor_write_error(void)
{
    env_shared_memory_write(0, 0, 0, ENV_SHARED_STATUS_SENSOR_ERROR,
                            rt_tick_get_millisecond());
    s_last_valid = RT_FALSE;
}

static void env_sensor_thread_entry(void *parameter)
{
    (void)parameter;

    env_shared_memory_writer_init();
    LOG_I("Environment shared memory ready at 0x%08x", (unsigned int)ENV_SHARED_MEMORY_ADDR);

    rt_thread_mdelay(2000);

    LOG_I("Initializing AHT20/AHT10 compatible sensor on %s", PKG_AHT10_I2C_BUS_NAME);
    s_aht20_dev = aht10_init(PKG_AHT10_I2C_BUS_NAME);
    if (s_aht20_dev == RT_NULL)
    {
        LOG_E("AHT20 init failed on %s", PKG_AHT10_I2C_BUS_NAME);
        env_sensor_write_error();
    }
    else
    {
        LOG_I("AHT20 initialized");
    }

    while (1)
    {
        if (s_aht20_dev == RT_NULL)
        {
            s_aht20_dev = aht10_init(PKG_AHT10_I2C_BUS_NAME);
            if (s_aht20_dev == RT_NULL)
            {
                env_sensor_write_error();
                rt_thread_mdelay(5000);
                continue;
            }
            LOG_I("AHT20 reinitialized");
        }

        float humidity_pct = aht10_read_humidity(s_aht20_dev);
        float temperature_c = aht10_read_temperature(s_aht20_dev);

        if (env_sample_is_valid(temperature_c, humidity_pct))
        {
            int16_t temp_x10 = env_float_to_x10(temperature_c);
            int16_t humidity_x10 = env_float_to_x10(humidity_pct);

            s_last_temperature_c = temperature_c;
            s_last_humidity_pct = humidity_pct;
            s_last_valid = RT_TRUE;

            env_shared_memory_write(temp_x10, humidity_x10, 1,
                                    ENV_SHARED_STATUS_OK,
                                    rt_tick_get_millisecond());
            LOG_I("AHT20 sample: %d.%d C, %d.%d %%RH",
                  temp_x10 / 10, temp_x10 < 0 ? -(temp_x10 % 10) : temp_x10 % 10,
                  humidity_x10 / 10, humidity_x10 < 0 ? -(humidity_x10 % 10) : humidity_x10 % 10);
        }
        else
        {
            LOG_W("Invalid AHT20 sample: temp=%d.%d humidity=%d.%d",
                  (int)temperature_c, (int)(temperature_c * 10.0f) % 10,
                  (int)humidity_pct, (int)(humidity_pct * 10.0f) % 10);
            env_sensor_write_error();
        }

        rt_thread_mdelay(ENV_SENSOR_PERIOD_MS);
    }
}

int env_sensor_m33_init(void)
{
    rt_thread_t tid = rt_thread_create("env_m33", env_sensor_thread_entry, RT_NULL,
                                       ENV_SENSOR_THREAD_STACK,
                                       ENV_SENSOR_THREAD_PRIORITY,
                                       ENV_SENSOR_THREAD_TICK);
    if (tid == RT_NULL)
    {
        LOG_E("Create env_m33 thread failed");
        return -RT_ERROR;
    }

    rt_thread_startup(tid);
    return RT_EOK;
}
INIT_APP_EXPORT(env_sensor_m33_init);

#ifdef RT_USING_FINSH
#include <finsh.h>

static int env_m33_status(void)
{
    env_shared_data_t data;

    if (env_shared_memory_read(&data))
    {
        rt_kprintf("env_m33: seq=%u valid=%u status=%u temp=%d.%dC humidity=%d.%d%%RH updated_ms=%u\n",
                   data.seq,
                   data.valid,
                   data.status,
                   data.temperature_c_x10 / 10,
                   data.temperature_c_x10 < 0 ? -(data.temperature_c_x10 % 10) : data.temperature_c_x10 % 10,
                   data.humidity_pct_x10 / 10,
                   data.humidity_pct_x10 < 0 ? -(data.humidity_pct_x10 % 10) : data.humidity_pct_x10 % 10,
                   data.updated_ms);
    }
    else
    {
        rt_kprintf("env_m33: shared memory is not initialized\n");
    }

    rt_kprintf("env_m33: last_valid=%d last_temp=%d.%dC last_humidity=%d.%d%%RH\n",
               s_last_valid,
               (int)s_last_temperature_c,
               (int)(s_last_temperature_c * 10.0f) % 10,
               (int)s_last_humidity_pct,
               (int)(s_last_humidity_pct * 10.0f) % 10);
    return 0;
}
MSH_CMD_EXPORT(env_m33_status, Show M33 environment sensor status);
#endif
