#include "audio_capture_hub.h"

#include <rtdevice.h>
#include <stdlib.h>
#include <string.h>

#ifdef RT_USING_FINSH
#include <finsh.h>
#endif

#define DBG_TAG "audio.hub"
#define DBG_LVL DBG_INFO
#include <rtdbg.h>

#ifndef BSP_XIAOZHI_MIC_DEVICE_NAME
#define BSP_XIAOZHI_MIC_DEVICE_NAME "mic0"
#endif

#ifdef ENABLE_STEREO_INPUT_FEED
#define HUB_INPUT_STEREO 1
#else
#define HUB_INPUT_STEREO 0
#endif

#define HUB_CAPTURE_BYTES       1024
#define HUB_VOICE_QUEUE_BYTES   8192
#define HUB_WAKE_QUEUE_BYTES    8192
#define HUB_SNORE_QUEUE_BYTES   16384
#define HUB_THREAD_STACK_SIZE   3072
#define HUB_THREAD_PRIORITY     6

typedef struct
{
    struct rt_ringbuffer ring;
    struct rt_mutex lock;
    struct rt_semaphore data_ready;
    const char *name;
    rt_uint8_t *pool;
    rt_size_t pool_size;
    volatile rt_bool_t enabled;
    volatile rt_uint32_t dropped_bytes;
    rt_uint32_t next_drop_log;
} audio_capture_stream_t;

static rt_uint8_t s_voice_pool[HUB_VOICE_QUEUE_BYTES]
    rt_section(".m33_m55_shared_hyperram");
static rt_uint8_t s_wake_pool[HUB_WAKE_QUEUE_BYTES]
    rt_section(".m33_m55_shared_hyperram");
static rt_uint8_t s_snore_pool[HUB_SNORE_QUEUE_BYTES]
    rt_section(".m33_m55_shared_hyperram");

static audio_capture_stream_t s_streams[AUDIO_CAPTURE_CONSUMER_COUNT];
static rt_device_t s_mic_device = RT_NULL;
static rt_thread_t s_capture_thread = RT_NULL;
static volatile rt_bool_t s_initialized = RT_FALSE;
static volatile rt_bool_t s_microphone_open = RT_FALSE;
static volatile rt_bool_t s_snore_suppressed = RT_FALSE;
static volatile rt_tick_t s_snore_suppressed_until = 0;

static audio_capture_stream_t *stream_for(audio_capture_consumer_t consumer)
{
    if (consumer < AUDIO_CAPTURE_VOICE ||
        consumer >= AUDIO_CAPTURE_CONSUMER_COUNT)
    {
        return RT_NULL;
    }
    return &s_streams[consumer];
}

static void stream_init(audio_capture_stream_t *stream,
                        const char *name,
                        const char *lock_name,
                        const char *sem_name,
                        rt_uint8_t *pool,
                        rt_size_t pool_size)
{
    memset(stream, 0, sizeof(*stream));
    stream->name = name;
    stream->pool = pool;
    stream->pool_size = pool_size;
    stream->next_drop_log = 32768;
    rt_ringbuffer_init(&stream->ring, pool, (rt_int32_t)pool_size);
    rt_mutex_init(&stream->lock, lock_name, RT_IPC_FLAG_FIFO);
    rt_sem_init(&stream->data_ready, sem_name, 0, RT_IPC_FLAG_FIFO);
}

static void stream_reset(audio_capture_stream_t *stream)
{
    if (rt_mutex_take(&stream->lock, RT_WAITING_FOREVER) == RT_EOK)
    {
        rt_ringbuffer_reset(&stream->ring);
        rt_mutex_release(&stream->lock);
    }
    while (rt_sem_take(&stream->data_ready, RT_WAITING_NO) == RT_EOK)
    {
    }
}

static void stream_publish(audio_capture_stream_t *stream,
                           const void *data,
                           rt_size_t length)
{
    if (!stream->enabled || !data || length == 0)
    {
        return;
    }

    if (rt_mutex_take(&stream->lock, RT_WAITING_NO) != RT_EOK)
    {
        stream->dropped_bytes += (rt_uint32_t)length;
    }
    else
    {
        rt_size_t space = rt_ringbuffer_space_len(&stream->ring);
        if (length > space)
        {
            stream->dropped_bytes += (rt_uint32_t)(length - space);
        }
        rt_ringbuffer_put_force(&stream->ring,
                                (const rt_uint8_t *)data, length);
        rt_mutex_release(&stream->lock);
        rt_sem_release(&stream->data_ready);
    }

    if (stream->dropped_bytes >= stream->next_drop_log)
    {
        LOG_W("%s consumer dropped %u bytes",
              stream->name, stream->dropped_bytes);
        stream->next_drop_log = stream->dropped_bytes + 32768;
    }
}

static int open_microphone(void)
{
    if (s_microphone_open)
    {
        return RT_EOK;
    }

    if (!s_mic_device)
    {
        s_mic_device = rt_device_find(BSP_XIAOZHI_MIC_DEVICE_NAME);
    }
    if (!s_mic_device)
    {
        LOG_E("cannot find %s", BSP_XIAOZHI_MIC_DEVICE_NAME);
        return -RT_ERROR;
    }

    if (rt_device_open(s_mic_device, RT_DEVICE_OFLAG_RDONLY) != RT_EOK)
    {
        LOG_E("cannot open %s", BSP_XIAOZHI_MIC_DEVICE_NAME);
        return -RT_ERROR;
    }

    s_microphone_open = RT_TRUE;
    LOG_I("%s opened by shared capture hub", BSP_XIAOZHI_MIC_DEVICE_NAME);
    return RT_EOK;
}

static void audio_capture_thread(void *parameter)
{
    rt_uint8_t stereo_frame[HUB_CAPTURE_BYTES];
    rt_int16_t mono_frame[HUB_CAPTURE_BYTES / sizeof(rt_int16_t)];
    (void)parameter;

    while (RT_TRUE)
    {
        if (open_microphone() != RT_EOK)
        {
            rt_thread_mdelay(1000);
            continue;
        }

        rt_size_t length = rt_device_read(s_mic_device, 0,
                                          stereo_frame, sizeof(stereo_frame));
        if (length == 0)
        {
            rt_thread_mdelay(1);
            continue;
        }

        stream_publish(&s_streams[AUDIO_CAPTURE_VOICE],
                       stereo_frame, length);

        const rt_int16_t *input = (const rt_int16_t *)stereo_frame;
        rt_size_t input_samples = length / sizeof(rt_int16_t);
        rt_size_t mono_samples = 0;
#if HUB_INPUT_STEREO
        mono_samples = input_samples / 2;
        for (rt_size_t i = 0; i < mono_samples; ++i)
        {
            mono_frame[i] = input[i * 2 + 1];
        }
#else
        mono_samples = input_samples;
        memcpy(mono_frame, input, mono_samples * sizeof(rt_int16_t));
#endif

        stream_publish(&s_streams[AUDIO_CAPTURE_WAKEWORD],
                       mono_frame, mono_samples * sizeof(rt_int16_t));
        stream_publish(&s_streams[AUDIO_CAPTURE_SNORE],
                       mono_frame, mono_samples * sizeof(rt_int16_t));
    }
}

int audio_capture_hub_init(void)
{
    if (s_initialized)
    {
        return RT_EOK;
    }

    stream_init(&s_streams[AUDIO_CAPTURE_VOICE],
                "voice",
                "hubvlock", "hubvsem",
                s_voice_pool, sizeof(s_voice_pool));
    stream_init(&s_streams[AUDIO_CAPTURE_WAKEWORD],
                "wakeword",
                "hubwlock", "hubwsem",
                s_wake_pool, sizeof(s_wake_pool));
    stream_init(&s_streams[AUDIO_CAPTURE_SNORE],
                "snore",
                "hubslock", "hubssem",
                s_snore_pool, sizeof(s_snore_pool));

    s_capture_thread = rt_thread_create("audio_hub",
                                        audio_capture_thread,
                                        RT_NULL,
                                        HUB_THREAD_STACK_SIZE,
                                        HUB_THREAD_PRIORITY,
                                        10);
    if (!s_capture_thread)
    {
        LOG_E("capture thread create failed");
        return -RT_ENOMEM;
    }

    s_initialized = RT_TRUE;
    if (rt_thread_startup(s_capture_thread) != RT_EOK)
    {
        LOG_E("capture thread startup failed");
        s_initialized = RT_FALSE;
        rt_thread_delete(s_capture_thread);
        s_capture_thread = RT_NULL;
        return -RT_ERROR;
    }
    return RT_EOK;
}

int audio_capture_hub_set_enabled(audio_capture_consumer_t consumer,
                                  rt_bool_t enabled)
{
    audio_capture_stream_t *stream = stream_for(consumer);
    if (!stream)
    {
        return -RT_EINVAL;
    }
    if (!s_initialized && audio_capture_hub_init() != RT_EOK)
    {
        return -RT_ERROR;
    }

    if (stream->enabled == enabled)
    {
        return RT_EOK;
    }

    stream->enabled = RT_FALSE;
    stream_reset(stream);
    stream->enabled = enabled ? RT_TRUE : RT_FALSE;
    LOG_I("consumer %d %s", consumer, enabled ? "enabled" : "disabled");
    return RT_EOK;
}

rt_size_t audio_capture_hub_read(audio_capture_consumer_t consumer,
                                 void *buffer,
                                 rt_size_t size,
                                 rt_int32_t timeout)
{
    audio_capture_stream_t *stream = stream_for(consumer);
    if (!stream || !buffer || size == 0 || !stream->enabled)
    {
        return 0;
    }

    rt_tick_t start = rt_tick_get();
    while (stream->enabled)
    {
        rt_size_t read_size = 0;
        rt_size_t remaining = 0;
        if (rt_mutex_take(&stream->lock, RT_WAITING_FOREVER) == RT_EOK)
        {
            read_size = rt_ringbuffer_get(&stream->ring,
                                          (rt_uint8_t *)buffer,
                                          size);
            remaining = rt_ringbuffer_data_len(&stream->ring);
            rt_mutex_release(&stream->lock);
        }
        if (read_size > 0)
        {
            if (remaining == 0)
            {
                while (rt_sem_take(&stream->data_ready,
                                   RT_WAITING_NO) == RT_EOK)
                {
                }
            }
            return read_size;
        }

        rt_int32_t wait = timeout;
        if (timeout != RT_WAITING_FOREVER)
        {
            rt_tick_t elapsed = rt_tick_get() - start;
            if (elapsed >= (rt_tick_t)timeout)
            {
                return 0;
            }
            wait = (rt_int32_t)((rt_tick_t)timeout - elapsed);
        }
        if (rt_sem_take(&stream->data_ready, wait) != RT_EOK)
        {
            return 0;
        }
    }
    return 0;
}

void audio_capture_hub_suppress_snore(rt_bool_t suppressed)
{
    s_snore_suppressed = suppressed ? RT_TRUE : RT_FALSE;
    if (!suppressed)
    {
        s_snore_suppressed_until = 0;
    }
}

void audio_capture_hub_suppress_snore_for(rt_uint32_t duration_ms)
{
    rt_tick_t deadline =
        rt_tick_get() + rt_tick_from_millisecond(duration_ms);
    if (s_snore_suppressed_until == 0 ||
        (rt_int32_t)(deadline - s_snore_suppressed_until) > 0)
    {
        s_snore_suppressed_until = deadline;
    }
}

rt_bool_t audio_capture_hub_is_snore_suppressed(void)
{
    if (s_snore_suppressed)
    {
        return RT_TRUE;
    }
    if (s_snore_suppressed_until != 0)
    {
        rt_tick_t now = rt_tick_get();
        if ((rt_int32_t)(s_snore_suppressed_until - now) > 0)
        {
            return RT_TRUE;
        }
        s_snore_suppressed_until = 0;
    }
    return RT_FALSE;
}

void audio_capture_hub_get_status(audio_capture_hub_status_t *status)
{
    if (!status)
    {
        return;
    }
    memset(status, 0, sizeof(*status));
    status->initialized = s_initialized;
    status->microphone_open = s_microphone_open;
    status->voice_enabled = s_streams[AUDIO_CAPTURE_VOICE].enabled;
    status->wakeword_enabled = s_streams[AUDIO_CAPTURE_WAKEWORD].enabled;
    status->snore_enabled = s_streams[AUDIO_CAPTURE_SNORE].enabled;
    status->voice_dropped_bytes =
        s_streams[AUDIO_CAPTURE_VOICE].dropped_bytes;
    status->wakeword_dropped_bytes =
        s_streams[AUDIO_CAPTURE_WAKEWORD].dropped_bytes;
    status->snore_dropped_bytes =
        s_streams[AUDIO_CAPTURE_SNORE].dropped_bytes;
}

#ifdef RT_USING_FINSH
static int audio_hub_status(void)
{
    audio_capture_hub_status_t status;
    audio_capture_hub_get_status(&status);
    rt_kprintf("audio_hub: init=%d mic=%d voice=%d wake=%d snore=%d\n",
               status.initialized, status.microphone_open,
               status.voice_enabled, status.wakeword_enabled,
               status.snore_enabled);
    rt_kprintf("audio_hub: dropped voice=%u wake=%u snore=%u bytes\n",
               status.voice_dropped_bytes,
               status.wakeword_dropped_bytes,
               status.snore_dropped_bytes);
    return 0;
}
MSH_CMD_EXPORT(audio_hub_status, Show shared microphone hub status);

static int audio_hub_switch_test(int argc, char **argv)
{
    int count = 50;
    audio_capture_hub_status_t status;

    if (argc > 1)
    {
        count = atoi(argv[1]);
    }
    if (count <= 0 || count > 1000)
    {
        rt_kprintf("usage: audio_hub_switch_test [1..1000]\n");
        return -RT_EINVAL;
    }

    audio_capture_hub_get_status(&status);
    if (status.voice_enabled || status.wakeword_enabled ||
        status.snore_enabled)
    {
        rt_kprintf("audio_hub: stop active consumers before switch test\n");
        return -RT_EBUSY;
    }

    for (int i = 0; i < count; ++i)
    {
        for (int consumer = AUDIO_CAPTURE_VOICE;
             consumer < AUDIO_CAPTURE_CONSUMER_COUNT;
             ++consumer)
        {
            audio_capture_hub_set_enabled(
                (audio_capture_consumer_t)consumer, RT_TRUE);
            audio_capture_hub_set_enabled(
                (audio_capture_consumer_t)consumer, RT_FALSE);
        }
    }

    rt_kprintf("audio_hub: %d switch cycles passed\n", count);
    return RT_EOK;
}
MSH_CMD_EXPORT(audio_hub_switch_test,
               Stress shared microphone subscriber switching);
#endif
