#include "backend_target_config.h"

#include <cJSON.h>
#include <fcntl.h>
#include <stdlib.h>
#include <stdio.h>
#include <unistd.h>

#ifdef RT_USING_FINSH
#include <finsh.h>
#endif

#define DBG_TAG "backend.cfg"
#define DBG_LVL DBG_INFO
#include <rtdbg.h>

#define BACKEND_CONFIG_TMP_FILE "/flash/backend_config.tmp"
#define BACKEND_DEFAULT_HOST    "192.168.0.102"
#define BACKEND_DEFAULT_PORT    8081
#define BACKEND_CONFIG_VERSION  2

static rt_err_t backend_target_load(char *host, int host_len, int *port)
{
    char buf[192] = {0};
    cJSON *root = RT_NULL;
    cJSON *item = RT_NULL;
    int fd;
    int len;

    if (!host || host_len <= 0 || !port)
    {
        return -RT_EINVAL;
    }

    fd = open(BACKEND_CONFIG_FILE, O_RDONLY);
    if (fd < 0)
    {
        return -RT_ENOSYS;
    }

    len = read(fd, buf, sizeof(buf) - 1);
    close(fd);
    if (len <= 0)
    {
        return -RT_ERROR;
    }
    buf[len] = '\0';

    root = cJSON_Parse(buf);
    if (!root)
    {
        return -RT_ERROR;
    }

    item = cJSON_GetObjectItem(root, "version");
    if (!item || !cJSON_IsNumber(item) || item->valueint != BACKEND_CONFIG_VERSION)
    {
        cJSON_Delete(root);
        return -RT_ERROR;
    }

    item = cJSON_GetObjectItem(root, "host");
    if (!item || !cJSON_IsString(item) || !item->valuestring || item->valuestring[0] == '\0')
    {
        cJSON_Delete(root);
        return -RT_ERROR;
    }

    rt_strncpy(host, item->valuestring, host_len - 1);
    host[host_len - 1] = '\0';

    item = cJSON_GetObjectItem(root, "port");
    if (item && cJSON_IsNumber(item) && item->valueint > 0 && item->valueint <= 65535)
    {
        *port = item->valueint;
    }
    else
    {
        *port = BACKEND_DEFAULT_PORT;
    }

    cJSON_Delete(root);
    return RT_EOK;
}

void backend_target_get(const char *default_host,
                        int default_port,
                        char *host,
                        int host_len,
                        int *port)
{
    if (!host || host_len <= 0 || !port)
    {
        return;
    }

    if (backend_target_load(host, host_len, port) == RT_EOK)
    {
        return;
    }

    rt_strncpy(host, default_host ? default_host : BACKEND_DEFAULT_HOST, host_len - 1);
    host[host_len - 1] = '\0';
    *port = default_port > 0 ? default_port : BACKEND_DEFAULT_PORT;
}

static rt_err_t backend_write_text_file(const char *path, const char *text)
{
    int fd;
    int len;
    int written;

    fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0);
    if (fd < 0)
    {
        return -RT_ERROR;
    }

    len = rt_strlen(text);
    written = write(fd, text, len);
    close(fd);

    return written == len ? RT_EOK : -RT_ERROR;
}

rt_err_t backend_target_save(const char *host, int port)
{
    cJSON *root = RT_NULL;
    char *json_str = RT_NULL;
    char verify_host[BACKEND_TARGET_HOST_LEN] = {0};
    int verify_port = 0;
    rt_err_t ret;

    if (!host || host[0] == '\0' || rt_strlen(host) >= BACKEND_TARGET_HOST_LEN)
    {
        return -RT_EINVAL;
    }

    if (port <= 0 || port > 65535)
    {
        return -RT_EINVAL;
    }

    root = cJSON_CreateObject();
    if (!root)
    {
        return -RT_ENOMEM;
    }

    cJSON_AddNumberToObject(root, "version", BACKEND_CONFIG_VERSION);
    cJSON_AddStringToObject(root, "host", host);
    cJSON_AddNumberToObject(root, "port", port);
    json_str = cJSON_Print(root);
    if (!json_str)
    {
        cJSON_Delete(root);
        return -RT_ENOMEM;
    }

    unlink(BACKEND_CONFIG_TMP_FILE);
    ret = backend_write_text_file(BACKEND_CONFIG_TMP_FILE, json_str);
    if (ret == RT_EOK)
    {
        unlink(BACKEND_CONFIG_FILE);
        if (rename(BACKEND_CONFIG_TMP_FILE, BACKEND_CONFIG_FILE) != 0)
        {
            ret = backend_write_text_file(BACKEND_CONFIG_FILE, json_str);
            unlink(BACKEND_CONFIG_TMP_FILE);
        }
    }

    cJSON_free(json_str);
    cJSON_Delete(root);

    if (ret != RT_EOK)
    {
        return ret;
    }

    ret = backend_target_load(verify_host, sizeof(verify_host), &verify_port);
    if (ret != RT_EOK || rt_strcmp(verify_host, host) != 0 || verify_port != port)
    {
        return -RT_ERROR;
    }

    LOG_I("Backend target saved: %s:%d", host, port);
    return RT_EOK;
}

rt_err_t backend_target_clear(void)
{
    unlink(BACKEND_CONFIG_TMP_FILE);
    return unlink(BACKEND_CONFIG_FILE) == 0 ? RT_EOK : -RT_ERROR;
}

#ifdef RT_USING_FINSH
static int backend_cfg_status(int argc, char **argv)
{
    char host[BACKEND_TARGET_HOST_LEN] = {0};
    int port = 0;

    (void)argc;
    (void)argv;

    if (backend_target_load(host, sizeof(host), &port) == RT_EOK)
    {
        rt_kprintf("backend_cfg_status: saved target %s:%d (%s)\n",
                   host, port, BACKEND_CONFIG_FILE);
    }
    else
    {
        rt_kprintf("backend_cfg_status: no saved target, default %s:%d\n",
                   BACKEND_DEFAULT_HOST, BACKEND_DEFAULT_PORT);
    }
    return RT_EOK;
}
MSH_CMD_EXPORT(backend_cfg_status, Show backend target IP and port);

static int backend_cfg_set(int argc, char **argv)
{
    const char *host;
    int port = BACKEND_DEFAULT_PORT;

    if (argc < 2)
    {
        rt_kprintf("Usage: backend_cfg_set <computer_ip> [port]\n");
        rt_kprintf("Example: backend_cfg_set 192.168.0.102 8081\n");
        return -RT_EINVAL;
    }

    host = argv[1];
    if (argc >= 3)
    {
        port = atoi(argv[2]);
    }

    if (backend_target_save(host, port) == RT_EOK)
    {
        rt_kprintf("backend_cfg_set: saved %s:%d\n", host, port);
        return RT_EOK;
    }

    rt_kprintf("backend_cfg_set: save failed, check /flash mount and input\n");
    return -RT_ERROR;
}
MSH_CMD_EXPORT(backend_cfg_set, Set backend target: backend_cfg_set ip port);

static int backend_cfg_clear(int argc, char **argv)
{
    (void)argc;
    (void)argv;

    if (backend_target_clear() == RT_EOK)
    {
        rt_kprintf("backend_cfg_clear: removed %s\n", BACKEND_CONFIG_FILE);
        return RT_EOK;
    }

    rt_kprintf("backend_cfg_clear: no saved target or remove failed\n");
    return -RT_ERROR;
}
MSH_CMD_EXPORT(backend_cfg_clear, Clear saved backend target);
#endif
