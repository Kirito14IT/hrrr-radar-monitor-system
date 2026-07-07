#include "imu_fall_monitor.h"

#include <rtdevice.h>
#include <rtthread.h>

#define DBG_TAG "imu.fall"
#define DBG_LVL DBG_INFO
#include <rtdbg.h>

#define LSM6DS_ADDR_LOW             0x6A
#define LSM6DS_ADDR_HIGH            0x6B

#define LSM6DS_REG_WHO_AM_I         0x0F
#define LSM6DS_REG_CTRL1_XL         0x10
#define LSM6DS_REG_CTRL3_C          0x12
#define LSM6DS_REG_WAKE_UP_SRC      0x1B
#define LSM6DS_REG_OUTX_L_XL        0x28
#define LSM6DS_REG_TAP_CFG          0x58
#define LSM6DS_REG_WAKE_UP_DUR      0x5C
#define LSM6DS_REG_FREE_FALL        0x5D

#define LSM6DS_WAKE_UP_SRC_FF_IA    0x20

#define FALL_POLL_INTERVAL_MS       20
#define FALL_HARDWARE_SAMPLES       2
#define FALL_SOFTWARE_SAMPLES       4
#define IMPACT_SOFTWARE_SAMPLES     1
#define FALL_REARM_STABLE_SAMPLES   25
#define FALL_COOLDOWN_MS            60000

/* CTRL1_XL is configured to +/-4 g, so 1 g is about 8192 LSB. */
#define FALL_THRESHOLD_RAW          4506LL
#define FALL_THRESHOLD_SQ           (FALL_THRESHOLD_RAW * FALL_THRESHOLD_RAW)
#define IMPACT_THRESHOLD_RAW        24576LL
#define IMPACT_THRESHOLD_SQ         (IMPACT_THRESHOLD_RAW * IMPACT_THRESHOLD_RAW)
#define STABLE_THRESHOLD_RAW        6144LL
#define STABLE_THRESHOLD_SQ         (STABLE_THRESHOLD_RAW * STABLE_THRESHOLD_RAW)

extern void xz_trigger_emergency_event(const char *source,
                                       const char *phrase,
                                       const char *transcript);

static struct rt_i2c_bus_device *s_i2c_bus = RT_NULL;
static const char *s_i2c_bus_name = RT_NULL;
static rt_uint8_t s_imu_addr = 0;
static rt_uint8_t s_who_am_i = 0;
static rt_thread_t s_monitor_thread = RT_NULL;

static rt_int16_t s_last_x = 0;
static rt_int16_t s_last_y = 0;
static rt_int16_t s_last_z = 0;
static rt_int64_t s_last_magnitude_sq = 0;
static rt_uint8_t s_last_wake_source = 0;
static volatile rt_bool_t s_fall_armed = RT_FALSE;

static rt_err_t lsm6ds_write_reg(rt_uint8_t reg, rt_uint8_t value)
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

static rt_err_t lsm6ds_read_regs(rt_uint8_t reg, rt_uint8_t *data, rt_size_t size)
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

static const char *lsm6ds_chip_name(rt_uint8_t who_am_i)
{
    switch (who_am_i)
    {
    case 0x69:
        return "LSM6DS3/LSM6DSM";
    case 0x6A:
        return "LSM6DSL/LSM6DSR";
    case 0x6C:
        return "LSM6DSO/LSM6DSOX";
    default:
        return "unknown";
    }
}

static rt_bool_t lsm6ds_is_supported_id(rt_uint8_t who_am_i)
{
    return who_am_i == 0x69 || who_am_i == 0x6A || who_am_i == 0x6C;
}

static rt_err_t lsm6ds_detect_address(void)
{
    const rt_uint8_t addresses[] = {LSM6DS_ADDR_LOW, LSM6DS_ADDR_HIGH};

    for (rt_size_t i = 0; i < sizeof(addresses); ++i)
    {
        rt_uint8_t who_am_i = 0;
        s_imu_addr = addresses[i];
        if (lsm6ds_read_regs(LSM6DS_REG_WHO_AM_I, &who_am_i, 1) == RT_EOK)
        {
            LOG_I("IMU probe %s addr=0x%02X who=0x%02X (%s)",
                  s_i2c_bus_name ? s_i2c_bus_name : "?",
                  s_imu_addr,
                  who_am_i,
                  lsm6ds_chip_name(who_am_i));
            if (lsm6ds_is_supported_id(who_am_i))
            {
                s_who_am_i = who_am_i;
                LOG_I("LSM6DS family detected on %s at 0x%02X",
                      s_i2c_bus_name ? s_i2c_bus_name : "?",
                      s_imu_addr);
                return RT_EOK;
            }
        }
    }

    s_imu_addr = 0;
    s_who_am_i = 0;
    return -RT_ERROR;
}

static rt_err_t lsm6ds_configure_fall_detection(void)
{
    /*
     * CTRL1_XL: accelerometer 104 Hz, +/-4 g.
     * CTRL3_C: block-data-update and register auto-increment.
     * FREE_FALL is best effort. Software low-g/impact detection is also used.
     */
    if (lsm6ds_write_reg(LSM6DS_REG_CTRL3_C, 0x44) != RT_EOK ||
        lsm6ds_write_reg(LSM6DS_REG_CTRL1_XL, 0x48) != RT_EOK ||
        lsm6ds_write_reg(LSM6DS_REG_TAP_CFG, 0x80) != RT_EOK ||
        lsm6ds_write_reg(LSM6DS_REG_WAKE_UP_DUR, 0x00) != RT_EOK ||
        lsm6ds_write_reg(LSM6DS_REG_FREE_FALL, 0x33) != RT_EOK)
    {
        return -RT_ERROR;
    }

    rt_uint8_t clear_source = 0;
    lsm6ds_read_regs(LSM6DS_REG_WAKE_UP_SRC, &clear_source, 1);
    return RT_EOK;
}

static rt_err_t lsm6ds_read_acceleration_sq(rt_int64_t *magnitude_sq)
{
    rt_uint8_t raw[6];
    if (!magnitude_sq ||
        lsm6ds_read_regs(LSM6DS_REG_OUTX_L_XL, raw, sizeof(raw)) != RT_EOK)
    {
        return -RT_ERROR;
    }

    const rt_int16_t x = (rt_int16_t)((raw[1] << 8) | raw[0]);
    const rt_int16_t y = (rt_int16_t)((raw[3] << 8) | raw[2]);
    const rt_int16_t z = (rt_int16_t)((raw[5] << 8) | raw[4]);

    *magnitude_sq = (rt_int64_t)x * x + (rt_int64_t)y * y + (rt_int64_t)z * z;
    s_last_x = x;
    s_last_y = y;
    s_last_z = z;
    s_last_magnitude_sq = *magnitude_sq;
    return RT_EOK;
}

static void imu_fall_monitor_entry(void *parameter)
{
    (void)parameter;
    int hardware_fall_samples = 0;
    int low_g_samples = 0;
    int impact_samples = 0;
    int stable_samples = FALL_REARM_STABLE_SAMPLES;
    rt_bool_t armed = RT_TRUE;
    rt_tick_t last_trigger_tick = 0;
    s_fall_armed = RT_TRUE;

    while (1)
    {
        rt_uint8_t wake_up_source = 0;
        rt_int64_t magnitude_sq = 0;
        const rt_bool_t source_valid =
            lsm6ds_read_regs(LSM6DS_REG_WAKE_UP_SRC, &wake_up_source, 1) == RT_EOK;
        const rt_bool_t acceleration_valid =
            lsm6ds_read_acceleration_sq(&magnitude_sq) == RT_EOK;
        s_last_wake_source = wake_up_source;

        if (!source_valid || !acceleration_valid)
        {
            hardware_fall_samples = 0;
            low_g_samples = 0;
            impact_samples = 0;
            rt_thread_mdelay(100);
            continue;
        }

        if ((wake_up_source & LSM6DS_WAKE_UP_SRC_FF_IA) != 0)
        {
            ++hardware_fall_samples;
        }
        else
        {
            hardware_fall_samples = 0;
        }

        if (magnitude_sq < FALL_THRESHOLD_SQ)
        {
            ++low_g_samples;
            impact_samples = 0;
            stable_samples = 0;
        }
        else if (magnitude_sq > IMPACT_THRESHOLD_SQ)
        {
            ++impact_samples;
            low_g_samples = 0;
            stable_samples = 0;
        }
        else
        {
            low_g_samples = 0;
            impact_samples = 0;
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
            s_fall_armed = RT_TRUE;
            LOG_I("fall detector rearmed");
        }

        const rt_bool_t hardware_fall =
            hardware_fall_samples >= FALL_HARDWARE_SAMPLES;
        const rt_bool_t software_fall =
            low_g_samples >= FALL_SOFTWARE_SAMPLES;
        const rt_bool_t impact_fall =
            impact_samples >= IMPACT_SOFTWARE_SAMPLES;

        if (armed && (hardware_fall || software_fall || impact_fall))
        {
            armed = RT_FALSE;
            s_fall_armed = RT_FALSE;
            last_trigger_tick = now;
            hardware_fall_samples = 0;
            low_g_samples = 0;
            impact_samples = 0;
            stable_samples = 0;

            LOG_W("board fall detected (wake=0x%02X, mag_sq=%lld)",
                  wake_up_source,
                  magnitude_sq);
            xz_trigger_emergency_event(
                "xiaozhi_imu_board",
                "设备摇晃",
                "IMU检测到开发板低重力或撞击，疑似设备被打翻");
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

    const char *bus_names[] = {"i2c0", "i2c1"};
    rt_err_t detected = -RT_ERROR;

    for (rt_size_t i = 0; i < sizeof(bus_names) / sizeof(bus_names[0]); ++i)
    {
        s_i2c_bus_name = bus_names[i];
        s_i2c_bus = (struct rt_i2c_bus_device *)rt_device_find(s_i2c_bus_name);
        if (s_i2c_bus == RT_NULL)
        {
            LOG_W("I2C bus %s not found", s_i2c_bus_name);
            continue;
        }

        if (lsm6ds_detect_address() == RT_EOK)
        {
            detected = RT_EOK;
            break;
        }
    }

    if (detected != RT_EOK)
    {
        LOG_E("LSM6DS family IMU not found on i2c0/i2c1 at 0x6A/0x6B");
        return -RT_ERROR;
    }

    if (lsm6ds_configure_fall_detection() != RT_EOK)
    {
        LOG_E("LSM6DS fall configuration failed");
        return -RT_ERROR;
    }

    s_monitor_thread = rt_thread_create(
        "imu_fall",
        imu_fall_monitor_entry,
        RT_NULL,
        4096,
        19,
        10);
    if (s_monitor_thread == RT_NULL)
    {
        LOG_E("failed to create IMU monitor thread");
        return -RT_ENOMEM;
    }

    rt_thread_startup(s_monitor_thread);
    LOG_I("board fall monitor started (%s addr=0x%02X who=0x%02X)",
          s_i2c_bus_name ? s_i2c_bus_name : "?",
          s_imu_addr,
          s_who_am_i);
    return RT_EOK;
}

#ifdef RT_USING_FINSH
static void imu_fall_status(void)
{
    rt_kprintf("imu_fall: thread=%s bus=%s addr=0x%02X who=0x%02X armed=%d\n",
               s_monitor_thread ? "running" : "stopped",
               s_i2c_bus_name ? s_i2c_bus_name : "-",
               s_imu_addr,
               s_who_am_i,
               s_fall_armed ? 1 : 0);
    rt_kprintf("accel_raw: x=%d y=%d z=%d mag_sq=%lld wake_src=0x%02X\n",
               s_last_x,
               s_last_y,
               s_last_z,
               s_last_magnitude_sq,
               s_last_wake_source);
    rt_kprintf("thresholds: hw_samples=%d low_g_samples=%d low_g_raw=%lld impact_raw=%lld cooldown_ms=%d\n",
               FALL_HARDWARE_SAMPLES,
               FALL_SOFTWARE_SAMPLES,
               FALL_THRESHOLD_RAW,
               IMPACT_THRESHOLD_RAW,
               FALL_COOLDOWN_MS);
}
MSH_CMD_EXPORT(imu_fall_status, Show IMU fall monitor status);

static void imu_fall_test(void)
{
    xz_trigger_emergency_event(
        "xiaozhi_imu_board",
        "设备摇晃",
        "手动测试IMU摇晃报警");
}
MSH_CMD_EXPORT(imu_fall_test, Trigger IMU fall emergency test);
#endif
