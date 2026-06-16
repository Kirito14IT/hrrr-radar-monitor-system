#ifndef AUDIO_CAPTURE_HUB_H
#define AUDIO_CAPTURE_HUB_H

#include <rtthread.h>
#include <rtdef.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum
{
    AUDIO_CAPTURE_VOICE = 0,
    AUDIO_CAPTURE_WAKEWORD,
    AUDIO_CAPTURE_SNORE,
    AUDIO_CAPTURE_CONSUMER_COUNT
} audio_capture_consumer_t;

typedef struct
{
    rt_bool_t initialized;
    rt_bool_t microphone_open;
    rt_bool_t voice_enabled;
    rt_bool_t wakeword_enabled;
    rt_bool_t snore_enabled;
    rt_uint32_t voice_dropped_bytes;
    rt_uint32_t wakeword_dropped_bytes;
    rt_uint32_t snore_dropped_bytes;
} audio_capture_hub_status_t;

int audio_capture_hub_init(void);
int audio_capture_hub_set_enabled(audio_capture_consumer_t consumer, rt_bool_t enabled);
rt_size_t audio_capture_hub_read(audio_capture_consumer_t consumer,
                                 void *buffer,
                                 rt_size_t size,
                                 rt_int32_t timeout);
void audio_capture_hub_suppress_snore(rt_bool_t suppressed);
void audio_capture_hub_suppress_snore_for(rt_uint32_t duration_ms);
rt_bool_t audio_capture_hub_is_snore_suppressed(void);
void audio_capture_hub_get_status(audio_capture_hub_status_t *status);

#ifdef __cplusplus
}
#endif

#endif
