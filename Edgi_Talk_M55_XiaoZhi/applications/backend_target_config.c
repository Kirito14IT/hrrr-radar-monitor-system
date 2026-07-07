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
#define DEVICE_CONFIG_TMP_FILE  "/flash/device_config.tmp"
#define BACKEND_DEFAULT_HOST    BOARD_BACKEND_HOST
#define BACKEND_DEFAULT_PORT    BOARD_BACKEND_PORT
#define BACKEND_CONFIG_VERSION  2
#define DEVICE_CONFIG_VERSION   1

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

#if BOARD_USE_FLASH_BACKEND_CONFIG
    if (backend_target_load(host, host_len, port) == RT_EOK)
    {
        return;
    }
#endif

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

static rt_bool_t device_identity_token_valid(const char *text, int max_len)
{
    int i;

    if (!text || text[0] == '\0' || rt_strlen(text) >= (rt_size_t)max_len)
    {
        return RT_FALSE;
    }

    for (i = 0; text[i] != '\0'; ++i)
    {
        const char ch = text[i];
        if ((ch >= 'a' && ch <= 'z') ||
            (ch >= 'A' && ch <= 'Z') ||
            (ch >= '0' && ch <= '9') ||
            ch == '-' || ch == '_' || ch == '.')
        {
            continue;
        }
        return RT_FALSE;
    }

    return RT_TRUE;
}

static rt_err_t device_identity_load(char *bed_id,
                                     int bed_id_len,
                                     char *device_id,
                                     int device_id_len,
                                     char *source,
                                     int source_len)
{
    char buf[256] = {0};
    cJSON *root = RT_NULL;
    cJSON *item = RT_NULL;
    int fd;
    int len;

    if (!bed_id || bed_id_len <= 0 || !device_id || device_id_len <= 0 || !source || source_len <= 0)
    {
        return -RT_EINVAL;
    }

    fd = open(DEVICE_CONFIG_FILE, O_RDONLY);
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
    if (!item || !cJSON_IsNumber(item) || item->valueint != DEVICE_CONFIG_VERSION)
    {
        cJSON_Delete(root);
        return -RT_ERROR;
    }

    item = cJSON_GetObjectItem(root, "bed_id");
    if (!item || !cJSON_IsString(item) || !device_identity_token_valid(item->valuestring, bed_id_len))
    {
        cJSON_Delete(root);
        return -RT_ERROR;
    }
    rt_strncpy(bed_id, item->valuestring, bed_id_len - 1);
    bed_id[bed_id_len - 1] = '\0';

    item = cJSON_GetObjectItem(root, "device_id");
    if (!item || !cJSON_IsString(item) || !device_identity_token_valid(item->valuestring, device_id_len))
    {
        cJSON_Delete(root);
        return -RT_ERROR;
    }
    rt_strncpy(device_id, item->valuestring, device_id_len - 1);
    device_id[device_id_len - 1] = '\0';

    item = cJSON_GetObjectItem(root, "source");
    if (!item || !cJSON_IsString(item) || !device_identity_token_valid(item->valuestring, source_len))
    {
        cJSON_Delete(root);
        return -RT_ERROR;
    }
    rt_strncpy(source, item->valuestring, source_len - 1);
    source[source_len - 1] = '\0';

    cJSON_Delete(root);
    return RT_EOK;
}

void device_identity_get(const char *default_bed_id,
                         const char *default_device_id,
                         const char *default_source,
                         char *bed_id,
                         int bed_id_len,
                         char *device_id,
                         int device_id_len,
                         char *source,
                         int source_len)
{
    if (!bed_id || bed_id_len <= 0 || !device_id || device_id_len <= 0 || !source || source_len <= 0)
    {
        return;
    }

#if BOARD_USE_FLASH_DEVICE_CONFIG
    if (device_identity_load(bed_id, bed_id_len, device_id, device_id_len, source, source_len) == RT_EOK)
    {
        return;
    }
#endif

    rt_strncpy(bed_id, default_bed_id ? default_bed_id : BOARD_BED_ID, bed_id_len - 1);
    bed_id[bed_id_len - 1] = '\0';
    rt_strncpy(device_id, default_device_id ? default_device_id : BOARD_DEVICE_ID, device_id_len - 1);
    device_id[device_id_len - 1] = '\0';
    rt_strncpy(source, default_source ? default_source : BOARD_EDGI_SOURCE, source_len - 1);
    source[source_len - 1] = '\0';
}

rt_err_t device_identity_save(const char *bed_id,
                              const char *device_id,
                              const char *source)
{
    cJSON *root = RT_NULL;
    char *json_str = RT_NULL;
    char verify_bed_id[DEVICE_CONFIG_BED_ID_LEN] = {0};
    char verify_device_id[DEVICE_CONFIG_ID_LEN] = {0};
    char verify_source[DEVICE_CONFIG_SOURCE_LEN] = {0};
    rt_err_t ret;

    if (!device_identity_token_valid(bed_id, DEVICE_CONFIG_BED_ID_LEN) ||
        !device_identity_token_valid(device_id, DEVICE_CONFIG_ID_LEN) ||
        !device_identity_token_valid(source, DEVICE_CONFIG_SOURCE_LEN))
    {
        return -RT_EINVAL;
    }

    root = cJSON_CreateObject();
    if (!root)
    {
        return -RT_ENOMEM;
    }

    cJSON_AddNumberToObject(root, "version", DEVICE_CONFIG_VERSION);
    cJSON_AddStringToObject(root, "bed_id", bed_id);
    cJSON_AddStringToObject(root, "device_id", device_id);
    cJSON_AddStringToObject(root, "source", source);
    json_str = cJSON_Print(root);
    if (!json_str)
    {
        cJSON_Delete(root);
        return -RT_ENOMEM;
    }

    unlink(DEVICE_CONFIG_TMP_FILE);
    ret = backend_write_text_file(DEVICE_CONFIG_TMP_FILE, json_str);
    if (ret == RT_EOK)
    {
        unlink(DEVICE_CONFIG_FILE);
        if (rename(DEVICE_CONFIG_TMP_FILE, DEVICE_CONFIG_FILE) != 0)
        {
            ret = backend_write_text_file(DEVICE_CONFIG_FILE, json_str);
            unlink(DEVICE_CONFIG_TMP_FILE);
        }
    }

    cJSON_free(json_str);
    cJSON_Delete(root);

    if (ret != RT_EOK)
    {
        return ret;
    }

    ret = device_identity_load(verify_bed_id, sizeof(verify_bed_id),
                               verify_device_id, sizeof(verify_device_id),
                               verify_source, sizeof(verify_source));
    if (ret != RT_EOK ||
        rt_strcmp(verify_bed_id, bed_id) != 0 ||
        rt_strcmp(verify_device_id, device_id) != 0 ||
        rt_strcmp(verify_source, source) != 0)
    {
        return -RT_ERROR;
    }

    LOG_I("Device identity saved: bed=%s device=%s source=%s", bed_id, device_id, source);
    return RT_EOK;
}

rt_err_t device_identity_clear(void)
{
    unlink(DEVICE_CONFIG_TMP_FILE);
    return unlink(DEVICE_CONFIG_FILE) == 0 ? RT_EOK : -RT_ERROR;
}

#ifdef RT_USING_FINSH
static int backend_cfg_status(int argc, char **argv)
{
#if BOARD_USE_FLASH_BACKEND_CONFIG
    char host[BACKEND_TARGET_HOST_LEN] = {0};
    int port = 0;
#endif

    (void)argc;
    (void)argv;

#if BOARD_USE_FLASH_BACKEND_CONFIG
    if (backend_target_load(host, sizeof(host), &port) == RT_EOK)
    {
        rt_kprintf("backend_cfg_status: saved target %s:%d (%s)\n",
                   host, port, BACKEND_CONFIG_FILE);
    }
    else
#endif
    {
        rt_kprintf("backend_cfg_status: compile target %s:%d\n",
                   BACKEND_DEFAULT_HOST, BACKEND_DEFAULT_PORT);
#if !BOARD_USE_FLASH_BACKEND_CONFIG
        rt_kprintf("backend_cfg_status: flash override disabled by board_device_config.h\n");
#endif
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
        rt_kprintf("Example: backend_cfg_set 192.168.31.236 8081\n");
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

static int device_cfg_status(int argc, char **argv)
{
    char bed_id[DEVICE_CONFIG_BED_ID_LEN] = {0};
    char device_id[DEVICE_CONFIG_ID_LEN] = {0};
    char source[DEVICE_CONFIG_SOURCE_LEN] = {0};

    (void)argc;
    (void)argv;

#if BOARD_USE_FLASH_DEVICE_CONFIG
    if (device_identity_load(bed_id, sizeof(bed_id),
                             device_id, sizeof(device_id),
                             source, sizeof(source)) == RT_EOK)
    {
        rt_kprintf("device_cfg_status: saved bed_id=%s device_id=%s source=%s (%s)\n",
                   bed_id, device_id, source, DEVICE_CONFIG_FILE);
    }
    else
#endif
    {
        device_identity_get(BOARD_BED_ID, BOARD_DEVICE_ID, BOARD_EDGI_SOURCE,
                            bed_id, sizeof(bed_id),
                            device_id, sizeof(device_id),
                            source, sizeof(source));
        rt_kprintf("device_cfg_status: compile identity bed_id=%s device_id=%s source=%s\n",
                   bed_id, device_id, source);
#if !BOARD_USE_FLASH_DEVICE_CONFIG
        rt_kprintf("device_cfg_status: flash override disabled by board_device_config.h\n");
#endif
    }
    return RT_EOK;
}
MSH_CMD_EXPORT(device_cfg_status, Show bed_id/device_id/source);

static int device_cfg_set(int argc, char **argv)
{
    const char *bed_id;
    const char *device_id;
    const char *source = BOARD_EDGI_SOURCE;

    if (argc < 3)
    {
        rt_kprintf("Usage: device_cfg_set <bed_id> <device_id> [source]\n");
        rt_kprintf("Example: device_cfg_set bed-002 xiaozhi-bed-002 xiaozhi_board_002\n");
        rt_kprintf("Allowed chars: A-Z a-z 0-9 . _ -\n");
        return -RT_EINVAL;
    }

    bed_id = argv[1];
    device_id = argv[2];
    if (argc >= 4)
    {
        source = argv[3];
    }

    if (device_identity_save(bed_id, device_id, source) == RT_EOK)
    {
        rt_kprintf("device_cfg_set: saved bed_id=%s device_id=%s source=%s\n",
                   bed_id, device_id, source);
        return RT_EOK;
    }

    rt_kprintf("device_cfg_set: save failed, check /flash mount and input\n");
    return -RT_ERROR;
}
MSH_CMD_EXPORT(device_cfg_set, Set device identity: device_cfg_set bed_id device_id source);

static int device_cfg_clear(int argc, char **argv)
{
    (void)argc;
    (void)argv;

    if (device_identity_clear() == RT_EOK)
    {
        rt_kprintf("device_cfg_clear: removed %s\n", DEVICE_CONFIG_FILE);
        return RT_EOK;
    }

    rt_kprintf("device_cfg_clear: no saved identity or remove failed\n");
    return -RT_ERROR;
}
MSH_CMD_EXPORT(device_cfg_clear, Clear saved device identity);
#endif
