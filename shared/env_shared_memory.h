/*
 * Shared environment telemetry between Cortex-M33 and Cortex-M55.
 *
 * M33 owns writes. M55 reads the latest value only and never clears the
 * shared block, so core boot order does not lose the most recent sample.
 */

#ifndef __ENV_SHARED_MEMORY_H__
#define __ENV_SHARED_MEMORY_H__

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define ENV_SHARED_MEMORY_ADDR     (0x261FFF00UL)
#define ENV_SHARED_MAGIC           (0x45564E31UL) /* EVN1 */
#define ENV_SHARED_VERSION         (1U)

typedef enum
{
    ENV_SHARED_STATUS_BOOTING = 0,
    ENV_SHARED_STATUS_OK = 1,
    ENV_SHARED_STATUS_SENSOR_ERROR = 2,
    ENV_SHARED_STATUS_STALE = 3
} env_shared_status_t;

typedef struct
{
    uint32_t magic;
    uint16_t version;
    uint16_t struct_size;
    volatile uint32_t seq;
    uint32_t updated_ms;
    int16_t temperature_c_x10;
    int16_t humidity_pct_x10;
    uint8_t valid;
    uint8_t status;
    uint16_t reserved;
} env_shared_data_t;

void env_shared_memory_writer_init(void);
void env_shared_memory_write(int16_t temperature_c_x10,
                             int16_t humidity_pct_x10,
                             uint8_t valid,
                             uint8_t status,
                             uint32_t updated_ms);
bool env_shared_memory_read(env_shared_data_t *out);

#ifdef __cplusplus
}
#endif

#endif /* __ENV_SHARED_MEMORY_H__ */
