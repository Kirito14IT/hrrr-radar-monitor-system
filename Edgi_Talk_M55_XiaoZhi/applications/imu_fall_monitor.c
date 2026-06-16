#include "imu_fall_monitor.h"

#include <rtdevice.h>
#include <rtthread.h>

#define DBG_TAG "imu.fall"
#define DBG_LVL DBG_INFO
#include <rtdbg.h>

#define LSM6DS3_I2C_BUS_NAME       "i2c0"
#define LSM6DS3_ADDR_LOW           0x6A
#define LSM6DS3_ADDR_HIGH          0x6B

#define LSM6DS3_REG_WHO_AM_I       0x0F
#define LSM6DS3_REG_CTRL1_XL       0x10
#define LSM6DS3_REG_CTRL3_C        0x12
#define LSM6DS3_REG_WAKE_UP_SRC    0x1B
#define LSM6DS3_REG_OUTX_L_XL      0x28
#define LSM6DS3_REG_TAP_CFG        0x58
#define LSM6DS3_REG_WAKE_UP_DUR    0x5C
#define LSM6DS3_REG_FREE_FALL      0x5D

#define LSM6DS3_WHO_AM_I_VALUE     0x69
#define LSM6DS3_WAKE_UP_SRC_FF_IA  0x20

#define FALL_POLL_INTERVAL_MS      20
#define FALL_SOFTWARE_SAMPLES      4
#define FALL_REARM_STABLE_SAMPLES  25
#define FALL_COOLDOWN_MS           60000

/* At +/-2 g, 1 g is about 16384 LSB. This threshold is about 0.35 g. */
#define FALL_THRESHOLD_RAW         5734LL
#define FALL_THRESHOLD_SQ          (FALL_THRESHOLD_RAW * FALL_THRESHOLD_RAW)
/* Require at least 0.70 g for 500 ms before accepting another fall. */
#define STABLE_THRESHOLD_RAW       11469LL
#define STABLE_THRESHOLD_SQ        (STABLE_THRESHOLD_RAW * STABLE_THRESHOLD_RAW)

extern void xz_trigger_emergency_event(const char *source,
                                       const char *phrase,
                                       const char *transcript);

static struct rt_i2c_bus_device *s_i2c_bus = RT_NULL;
static rt_uint8_t s_imu_addr = 0;
static rt_thread_t s_monitor_thread = RT_NULL;

static rt_err_t lsm6ds3_write_reg(rt_uint8_t reg, rt_uint8_t value)
{
    rt_uint8_t data[2] = {reg, value};
    struct rt_i2c_msg message = {
        .addr = s_imu_addr,
        .flags = RT_I2C_WR,
        .len = sizeof(data),
        .buf = data,
    };

    return rt_i2c_transfer(s_i2c_bus, &message, 1) == 1 ? RT_EOK : -RT_ERROR;
}

static rt_err_t lsm6ds3_read_regs(rt_uint8_t reg, rt_uint8_t *data, rt_size_t size)
{
    struct rt_i2c_msg messages[2] = {
        {
            .addr = s_imu_addr,
            .flags = RT_I2C_WR,
            .len = 1,
            .buf = &reg,
        },
        {
            .addr = s_imu_addr,
            .flags = RT_I2C_RD,
            .len = size,
            .buf = data,
        },
    };

    return rt_i2c_transfer(s_i2c_bus, messages, 2) == 2 ? RT_EOK : -RT_ERROR;
}

static rt_err_t lsm6ds3_detect_address(void)
{
    const rt_uint8_t addresses[] = {LSM6DS3_ADDR_LOW, LSM6DS3_ADDR_HIGH};

    for (rt_size_t i = 0; i < sizeof(addresses); ++i)
    {
        rt_uint8_t who_am_i = 0;
        s_imu_addr = addresses[i];
        if (lsm6ds3_read_regs(LSM6DS3_REG_WHO_AM_I, &who_am_i, 1) == RT_EOK &&
            who_am_i == LSM6DS3_WHO_AM_I_VALUE)
        {
            LOG_I("LSM6DS3 detected on %s at 0x%02X", LSM6DS3_I2C_BUS_NAME, s_imu_addr);
            return RT_EOK;
        }
    }

    s_imu_addr = 0;
    return -RT_ERROR;
}

static rt_err_t lsm6ds3_configure_free_fall(void)
{
    /*
     * CTRL1_XL: accelerometer 104 Hz, +/-2 g.
     * CTRL3_C: block-data-update and register auto-increment.
     * FREE_FALL: about 312 mg threshold for 6 samples (about 58 ms).
     * WAKE_UP_SRC is polled, so no physical interrupt pin is required.
     */
    if (lsm6ds3_write_reg(LSM6DS3_REG_CTRL3_C, 0x44) != RT_EOK ||
        lsm6ds3_write_reg(LSM6DS3_REG_CTRL1_XL, 0x40) != RT_EOK ||
        lsm6ds3_write_reg(LSM6DS3_REG_TAP_CFG, 0x80) != RT_EOK ||
        lsm6ds3_write_reg(LSM6DS3_REG_WAKE_UP_DUR, 0x00) != RT_EOK ||
        lsm6ds3_write_reg(LSM6DS3_REG_FREE_FALL, 0x33) != RT_EOK)
    {
        return -RT_ERROR;
    }

    rt_uint8_t clear_source = 0;
    lsm6ds3_read_regs(LSM6DS3_REG_WAKE_UP_SRC, &clear_source, 1);
    return RT_EOK;
}

static rt_err_t lsm6ds3_read_acceleration_sq(rt_int64_t *magnitude_sq)
{
    rt_uint8_t raw[6];
    if (!magnitude_sq ||
        lsm6ds3_read_regs(LSM6DS3_REG_OUTX_L_XL, raw, sizeof(raw)) != RT_EOK)
    {
        return -RT_ERROR;
    }

    const rt_int16_t x = (rt_int16_t)((raw[1] << 8) | raw[0]);
    const rt_int16_t y = (rt_int16_t)((raw[3] << 8) | raw[2]);
    const rt_int16_t z = (rt_int16_t)((raw[5] << 8) | raw[4]);
    *magnitude_sq = (rt_int64_t)x * x + (rt_int64_t)y * y + (rt_int64_t)z * z;
    return RT_EOK;
}

static void imu_fall_monitor_entry(void *parameter)
{
    (void)parameter;
    int low_g_samples = 0;
    int stable_samples = FALL_REARM_STABLE_SAMPLES;
    rt_bool_t armed = RT_TRUE;
    rt_tick_t last_trigger_tick = 0;

    while (1)
    {
        rt_uint8_t wake_up_source = 0;
        rt_int64_t magnitude_sq = 0;
        const rt_bool_t source_valid =
            lsm6ds3_read_regs(LSM6DS3_REG_WAKE_UP_SRC, &wake_up_source, 1) == RT_EOK;
        const rt_bool_t acceleration_valid =
            lsm6ds3_read_acceleration_sq(&magnitude_sq) == RT_EOK;

        if (!source_valid || !acceleration_valid)
        {
            low_g_samples = 0;
            rt_thread_mdelay(100);
            continue;
        }

        if (magnitude_sq < FALL_THRESHOLD_SQ)
        {
            ++low_g_samples;
            stable_samples = 0;
        }
        else
        {
            low_g_samples = 0;
            if (magnitude_sq > STABLE_THRESHOLD_SQ &&
                stable_samples < FALL_REARM_STABLE_SAMPLES)
            {
                ++stable_samples;
            }
        }

        const rt_tick_t now = rt_tick_get();
        const rt_bool_t cooldown_finished =
            last_trigger_tick == 0 ||
            (rt_tick_t)(now - last_trigger_tick) >=
                rt_tick_from_millisecond(FALL_COOLDOWN_MS);

        if (!armed && cooldown_finished &&
            stable_samples >= FALL_REARM_STABLE_SAMPLES)
        {
            armed = RT_TRUE;
            LOG_I("free-fall detector rearmed");
        }

        const rt_bool_t hardware_fall =
            (wake_up_source & LSM6DS3_WAKE_UP_SRC_FF_IA) != 0;
        const rt_bool_t software_fall =
            low_g_samples >= FALL_SOFTWARE_SAMPLES;

        if (armed && (hardware_fall || software_fall))
        {
            armed = RT_FALSE;
            last_trigger_tick = now;
            low_g_samples = 0;
            stable_samples = 0;

            LOG_W("free fall detected (source=0x%02X)", wake_up_source);
            xz_trigger_emergency_event(
                "xiaozhi_imu_board",
                "设备自由落体",
                "LSM6DS3检测到开发板自由落体，疑似设备被打翻");
        }

        rt_thread_mdelay(FALL_POLL_INTERVAL_MS);
    }
}

int imu_fall_monitor_init(void)
{
    if (s_monitor_thread != RT_NULL)
    {
        return RT_EOK;
    }

    s_i2c_bus = (struct rt_i2c_bus_device *)rt_device_find(LSM6DS3_I2C_BUS_NAME);
    if (s_i2c_bus == RT_NULL)
    {
        LOG_E("I2C bus %s not found", LSM6DS3_I2C_BUS_NAME);
        return -RT_ERROR;
    }

    if (lsm6ds3_detect_address() != RT_EOK)
    {
        LOG_E("LSM6DS3 not found at 0x6A or 0x6B");
        return -RT_ERROR;
    }

    if (lsm6ds3_configure_free_fall() != RT_EOK)
    {
        LOG_E("LSM6DS3 free-fall configuration failed");
        return -RT_ERROR;
    }

    s_monitor_thread = rt_thread_create(
        "imu_fall",
        imu_fall_monitor_entry,
        RT_NULL,
        2048,
        19,
        10);
    if (s_monitor_thread == RT_NULL)
    {
        LOG_E("failed to create IMU monitor thread");
        return -RT_ENOMEM;
    }

    rt_thread_startup(s_monitor_thread);
    LOG_I("free-fall monitor started");
    return RT_EOK;
}
