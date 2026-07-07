#ifndef __BACKEND_TARGET_CONFIG_H__
#define __BACKEND_TARGET_CONFIG_H__

#include <rtthread.h>
#include "board_device_config.h"

#ifdef __cplusplus
extern "C" {
#endif

#define BACKEND_CONFIG_FILE      "/flash/backend_config.json"
#define DEVICE_CONFIG_FILE       "/flash/device_config.json"
#define BACKEND_TARGET_HOST_LEN  64
#define DEVICE_CONFIG_BED_ID_LEN 32
#define DEVICE_CONFIG_ID_LEN     64
#define DEVICE_CONFIG_SOURCE_LEN 64

void backend_target_get(const char *default_host,
                        int default_port,
                        char *host,
                        int host_len,
                        int *port);

rt_err_t backend_target_save(const char *host, int port);
rt_err_t backend_target_clear(void);

void device_identity_get(const char *default_bed_id,
                         const char *default_device_id,
                         const char *default_source,
                         char *bed_id,
                         int bed_id_len,
                         char *device_id,
                         int device_id_len,
                         char *source,
                         int source_len);

rt_err_t device_identity_save(const char *bed_id,
                              const char *device_id,
                              const char *source);
rt_err_t device_identity_clear(void);

#ifdef __cplusplus
}
#endif

#endif /* __BACKEND_TARGET_CONFIG_H__ */
