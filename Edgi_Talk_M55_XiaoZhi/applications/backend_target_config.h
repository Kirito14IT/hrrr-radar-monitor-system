#ifndef __BACKEND_TARGET_CONFIG_H__
#define __BACKEND_TARGET_CONFIG_H__

#include <rtthread.h>

#ifdef __cplusplus
extern "C" {
#endif

#define BACKEND_CONFIG_FILE      "/flash/backend_config.json"
#define BACKEND_TARGET_HOST_LEN  64

void backend_target_get(const char *default_host,
                        int default_port,
                        char *host,
                        int host_len,
                        int *port);

rt_err_t backend_target_save(const char *host, int port);
rt_err_t backend_target_clear(void);

#ifdef __cplusplus
}
#endif

#endif /* __BACKEND_TARGET_CONFIG_H__ */
