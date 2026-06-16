#include "env_shared_memory.h"

#include <stddef.h>
#include <string.h>

static inline volatile env_shared_data_t *env_shared_ptr(void)
{
    return (volatile env_shared_data_t *)ENV_SHARED_MEMORY_ADDR;
}

static inline void env_shared_barrier(void)
{
#if defined(__GNUC__)
    __asm volatile("dmb" ::: "memory");
#else
    (void)0;
#endif
}

void env_shared_memory_writer_init(void)
{
    volatile env_shared_data_t *shared = env_shared_ptr();

    shared->magic = ENV_SHARED_MAGIC;
    shared->version = ENV_SHARED_VERSION;
    shared->struct_size = (uint16_t)sizeof(env_shared_data_t);
    shared->temperature_c_x10 = 0;
    shared->humidity_pct_x10 = 0;
    shared->valid = 0;
    shared->status = ENV_SHARED_STATUS_BOOTING;
    shared->updated_ms = 0;
    env_shared_barrier();
    shared->seq = 2;
}

void env_shared_memory_write(int16_t temperature_c_x10,
                             int16_t humidity_pct_x10,
                             uint8_t valid,
                             uint8_t status,
                             uint32_t updated_ms)
{
    volatile env_shared_data_t *shared = env_shared_ptr();
    uint32_t seq = shared->seq;

    if (shared->magic != ENV_SHARED_MAGIC ||
        shared->version != ENV_SHARED_VERSION ||
        shared->struct_size != (uint16_t)sizeof(env_shared_data_t))
    {
        env_shared_memory_writer_init();
        seq = env_shared_ptr()->seq;
    }

    if (seq & 1U)
    {
        seq++;
    }

    shared->seq = seq + 1U;
    env_shared_barrier();

    shared->magic = ENV_SHARED_MAGIC;
    shared->version = ENV_SHARED_VERSION;
    shared->struct_size = (uint16_t)sizeof(env_shared_data_t);
    shared->updated_ms = updated_ms;
    shared->temperature_c_x10 = temperature_c_x10;
    shared->humidity_pct_x10 = humidity_pct_x10;
    shared->valid = valid ? 1U : 0U;
    shared->status = status;
    shared->reserved = 0;

    env_shared_barrier();
    shared->seq = seq + 2U;
}

bool env_shared_memory_read(env_shared_data_t *out)
{
    volatile env_shared_data_t *shared = env_shared_ptr();

    if (out == NULL)
    {
        return false;
    }

    for (int i = 0; i < 3; i++)
    {
        uint32_t seq_start = shared->seq;
        env_shared_data_t snapshot;

        if ((seq_start & 1U) != 0U)
        {
            continue;
        }

        env_shared_barrier();
        snapshot.magic = shared->magic;
        snapshot.version = shared->version;
        snapshot.struct_size = shared->struct_size;
        snapshot.seq = seq_start;
        snapshot.updated_ms = shared->updated_ms;
        snapshot.temperature_c_x10 = shared->temperature_c_x10;
        snapshot.humidity_pct_x10 = shared->humidity_pct_x10;
        snapshot.valid = shared->valid;
        snapshot.status = shared->status;
        snapshot.reserved = shared->reserved;
        env_shared_barrier();

        if (seq_start == shared->seq &&
            snapshot.magic == ENV_SHARED_MAGIC &&
            snapshot.version == ENV_SHARED_VERSION &&
            snapshot.struct_size == (uint16_t)sizeof(env_shared_data_t))
        {
            memcpy(out, &snapshot, sizeof(snapshot));
            return true;
        }
    }

    return false;
}
