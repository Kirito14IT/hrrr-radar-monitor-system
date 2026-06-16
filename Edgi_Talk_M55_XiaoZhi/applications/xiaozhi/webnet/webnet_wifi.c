/*
 * Copyright (c) 2006-2024, RT-Thread Development Team
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * Change Logs:
 * Date           Author       Notes
 * 2024-01-01     RT-Thread    First version
 */

#include <rtthread.h>
#include <webnet.h>
#include <wn_module.h>
#include <wlan_mgnt.h>
#include <dfs_file.h>
#include <unistd.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <cJSON.h>
#include "wifi_manager.h"
#include "xiaozhi_ui.h"

/* Declare xiaozhi init function to avoid including xiaozhi.h which has lwIP conflicts */
extern int ws_xiaozhi_init(void);

/*****************************************************************************
 * Macro Definitions
 *****************************************************************************/
#define DBG_TAG    "wifi.mgr"
#define DBG_LVL    DBG_INFO
#include <rtdbg.h>

#define RESULT_BUF_SIZE         4096
#define MAX_SCAN_RESULTS        32
#define WIFI_CONNECT_MAX_RETRY  3
#define WIFI_CONNECT_TIMEOUT_S  15
#define WLAN_DEVICE_TIMEOUT_S   15
#define FLASH_MOUNT_TIMEOUT_S   10
#define WIFI_CONFIG_TMP_FILE    "/flash/wifi_config.tmp"
#define WIFI_STORAGE_TEST_FILE  "/flash/.wifi_store_test"
#define FLASH_TEST_FILE         "/flash/flash_test.bin"
#define FLASH_TEST_RENAMED_FILE "/flash/flash_test.renamed"
#define FLASH_TEST_DATA_SIZE    256

/*****************************************************************************
 * Static Variables
 *****************************************************************************/
static char s_result_buffer[RESULT_BUF_SIZE];
static rt_bool_t s_sta_connected = RT_FALSE;

/* Temporary storage for current WiFi credentials */
static char s_saved_ssid[64] = {0};
static char s_saved_password[64] = {0};

/* WiFi scan results */
static struct rt_wlan_info s_scan_result[MAX_SCAN_RESULTS];
static int s_scan_cnt = 0;
static struct rt_wlan_info *s_scan_filter = RT_NULL;

/*****************************************************************************
 * Private Functions - Configuration
 *****************************************************************************/

static rt_err_t wifi_wait_device(const char *device_name)
{
    if (!device_name)
    {
        return -RT_EINVAL;
    }

    for (int i = 0; i < (WLAN_DEVICE_TIMEOUT_S * 10); i++)
    {
        if (rt_device_find(device_name) != RT_NULL)
        {
            return RT_EOK;
        }
        rt_thread_mdelay(100);
    }

    LOG_E("WLAN device %s was not registered within %d seconds",
          device_name, WLAN_DEVICE_TIMEOUT_S);
    return -RT_ETIMEOUT;
}

static rt_bool_t wifi_storage_ready(void)
{
    static const char test_magic[] = "wifi-storage-ready";
    char read_buf[sizeof(test_magic)] = {0};
    int fd;
    int len;

    fd = open(WIFI_STORAGE_TEST_FILE, O_WRONLY | O_CREAT | O_TRUNC, 0);
    if (fd < 0)
    {
        int err = rt_get_errno();
        LOG_W("WiFi storage not writable yet: open %s failed, errno=%d",
              WIFI_STORAGE_TEST_FILE, err);
        return RT_FALSE;
    }

    len = write(fd, test_magic, sizeof(test_magic) - 1);
    if (len != (int)(sizeof(test_magic) - 1))
    {
        int err = rt_get_errno();
        LOG_W("WiFi storage write probe failed: wrote %d/%d bytes, errno=%d",
              len, (int)(sizeof(test_magic) - 1), err);
        close(fd);
        unlink(WIFI_STORAGE_TEST_FILE);
        return RT_FALSE;
    }
    if (close(fd) != 0)
    {
        int err = rt_get_errno();
        LOG_W("WiFi storage write probe close failed, errno=%d", err);
        unlink(WIFI_STORAGE_TEST_FILE);
        return RT_FALSE;
    }

    fd = open(WIFI_STORAGE_TEST_FILE, O_RDONLY);
    if (fd < 0)
    {
        int err = rt_get_errno();
        LOG_W("WiFi storage readback probe open failed, errno=%d", err);
        unlink(WIFI_STORAGE_TEST_FILE);
        return RT_FALSE;
    }

    len = read(fd, read_buf, sizeof(read_buf) - 1);
    if (len < 0)
    {
        int err = rt_get_errno();
        LOG_W("WiFi storage readback probe failed, errno=%d", err);
        close(fd);
        unlink(WIFI_STORAGE_TEST_FILE);
        return RT_FALSE;
    }
    if (close(fd) != 0)
    {
        int err = rt_get_errno();
        LOG_W("WiFi storage readback close failed, errno=%d", err);
        unlink(WIFI_STORAGE_TEST_FILE);
        return RT_FALSE;
    }

    if (len != (int)(sizeof(test_magic) - 1) ||
        rt_memcmp(read_buf, test_magic, sizeof(test_magic) - 1) != 0)
    {
        LOG_W("WiFi storage readback probe mismatch: read %d/%d bytes",
              len, (int)(sizeof(test_magic) - 1));
        unlink(WIFI_STORAGE_TEST_FILE);
        return RT_FALSE;
    }

    if (unlink(WIFI_STORAGE_TEST_FILE) != 0)
    {
        int err = rt_get_errno();
        LOG_W("WiFi storage probe cleanup failed: unlink %s, errno=%d",
              WIFI_STORAGE_TEST_FILE, err);
        return RT_FALSE;
    }

    return RT_TRUE;
}

static rt_err_t wifi_write_text_file(const char *path, const char *text)
{
    int fd;
    int len;
    int written;

    if (!path || !text)
    {
        return -RT_EINVAL;
    }

    fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0);
    if (fd < 0)
    {
        int err = rt_get_errno();
        LOG_E("Open %s failed, errno=%d", path, err);
        return -RT_ERROR;
    }

    len = rt_strlen(text);
    written = write(fd, text, len);
    if (written != len)
    {
        int err = rt_get_errno();
        LOG_E("Write %s failed: wrote %d/%d bytes, errno=%d",
              path, written, len, err);
        close(fd);
        unlink(path);
        return -RT_ERROR;
    }

    if (close(fd) != 0)
    {
        int err = rt_get_errno();
        LOG_E("Close %s after write failed, errno=%d", path, err);
        unlink(path);
        return -RT_ERROR;
    }

    return RT_EOK;
}

static rt_err_t wifi_config_load_from_path(const char *path,
                                           char *ssid,
                                           int ssid_len,
                                           char *password,
                                           int password_len)
{
    int fd;
    char buf[256] = {0};
    cJSON *root = RT_NULL;
    cJSON *item = RT_NULL;

    if (!path || !ssid || !password)
    {
        return -RT_EINVAL;
    }

    fd = open(path, O_RDONLY);
    if (fd < 0)
    {
        int err = rt_get_errno();
        LOG_D("Config file open failed: %s, errno=%d", path, err);
        (void)err;
        return -RT_ENOSYS;
    }

    int len = read(fd, buf, sizeof(buf) - 1);
    if (len <= 0)
    {
        int err = rt_get_errno();
        LOG_E("Read config file failed: %s, len=%d, errno=%d", path, len, err);
        close(fd);
        return -RT_ERROR;
    }
    if (close(fd) != 0)
    {
        int err = rt_get_errno();
        LOG_E("Close config file failed: %s, errno=%d", path, err);
        return -RT_ERROR;
    }

    buf[len] = '\0';

    root = cJSON_Parse(buf);
    if (!root)
    {
        LOG_E("Parse config JSON failed: %s", path);
        return -RT_ERROR;
    }

    item = cJSON_GetObjectItem(root, "ssid");
    if (item && cJSON_IsString(item) && item->valuestring)
    {
        rt_strncpy(ssid, item->valuestring, ssid_len - 1);
        ssid[ssid_len - 1] = '\0';
    }
    else
    {
        LOG_E("Config missing SSID: %s", path);
        cJSON_Delete(root);
        return -RT_ERROR;
    }

    item = cJSON_GetObjectItem(root, "password");
    if (item && cJSON_IsString(item) && item->valuestring)
    {
        rt_strncpy(password, item->valuestring, password_len - 1);
        password[password_len - 1] = '\0';
    }
    else
    {
        password[0] = '\0';
    }

    cJSON_Delete(root);
    return RT_EOK;
}

/**
 * @brief Save WiFi configuration to flash filesystem
 * @param ssid WiFi SSID
 * @param password WiFi password
 * @return RT_EOK on success, other values on failure
 */
static rt_err_t wifi_config_save(const char *ssid, const char *password)
{
    cJSON *root = RT_NULL;
    char *json_str = RT_NULL;
    rt_err_t ret;
    char verify_ssid[64] = {0};
    char verify_password[64] = {0};
    const char *save_password = password ? password : "";

    if (!ssid || rt_strlen(ssid) == 0)
    {
        LOG_E("Save config failed: SSID is empty");
        return -RT_EINVAL;
    }

    if (!wifi_storage_ready())
    {
        LOG_E("Save config failed: /flash is not writable/readable");
        return -RT_ERROR;
    }

    /* Create JSON object */
    root = cJSON_CreateObject();
    if (!root)
    {
        LOG_E("Create JSON object failed");
        return -RT_ENOMEM;
    }

    cJSON_AddStringToObject(root, "ssid", ssid);
    cJSON_AddStringToObject(root, "password", save_password);

    /* Convert to JSON string */
    json_str = cJSON_Print(root);
    if (!json_str)
    {
        LOG_E("JSON print failed");
        cJSON_Delete(root);
        return -RT_ENOMEM;
    }

    if (unlink(WIFI_CONFIG_TMP_FILE) != 0)
    {
        int err = rt_get_errno();
        LOG_D("No stale temp config removed: %s, errno=%d",
              WIFI_CONFIG_TMP_FILE, err);
        (void)err;
    }
    ret = wifi_write_text_file(WIFI_CONFIG_TMP_FILE, json_str);
    if (ret != RT_EOK)
    {
        goto cleanup;
    }

    ret = wifi_config_load_from_path(WIFI_CONFIG_TMP_FILE,
                                     verify_ssid, sizeof(verify_ssid),
                                     verify_password, sizeof(verify_password));
    if (ret != RT_EOK ||
        rt_strcmp(verify_ssid, ssid) != 0 ||
        rt_strcmp(verify_password, save_password) != 0)
    {
        LOG_E("Temp WiFi config readback verification failed");
        ret = -RT_ERROR;
        if (unlink(WIFI_CONFIG_TMP_FILE) != 0)
        {
            int err = rt_get_errno();
            LOG_W("Remove invalid temp config failed, errno=%d", err);
        }
        goto cleanup;
    }

    if (unlink(WIFI_CONFIG_FILE) != 0)
    {
        int err = rt_get_errno();
        LOG_D("No previous WiFi config removed: %s, errno=%d",
              WIFI_CONFIG_FILE, err);
        (void)err;
    }
    if (rename(WIFI_CONFIG_TMP_FILE, WIFI_CONFIG_FILE) != 0)
    {
        int err = rt_get_errno();
        LOG_W("Rename %s to %s failed, errno=%d; writing final file directly",
              WIFI_CONFIG_TMP_FILE, WIFI_CONFIG_FILE, err);
        ret = wifi_write_text_file(WIFI_CONFIG_FILE, json_str);
        if (unlink(WIFI_CONFIG_TMP_FILE) != 0)
        {
            err = rt_get_errno();
            LOG_W("Remove temp WiFi config after fallback failed, errno=%d", err);
        }
    }
    else
    {
        ret = RT_EOK;
    }

    if (ret == RT_EOK)
    {
        rt_memset(verify_ssid, 0, sizeof(verify_ssid));
        rt_memset(verify_password, 0, sizeof(verify_password));
        ret = wifi_config_load_from_path(WIFI_CONFIG_FILE,
                                         verify_ssid, sizeof(verify_ssid),
                                         verify_password, sizeof(verify_password));
        if (ret == RT_EOK &&
            rt_strcmp(verify_ssid, ssid) == 0 &&
            rt_strcmp(verify_password, save_password) == 0)
        {
            LOG_I("Config saved and verified: %s", WIFI_CONFIG_FILE);
        }
        else
        {
            LOG_E("Final WiFi config verification failed");
            ret = -RT_ERROR;
        }
    }

cleanup:
    cJSON_free(json_str);
    cJSON_Delete(root);

    return ret;
}

/**
 * @brief Load WiFi configuration from flash filesystem
 * @param ssid Output buffer for WiFi SSID
 * @param ssid_len Length of ssid buffer
 * @param password Output buffer for WiFi password
 * @param password_len Length of password buffer
 * @return RT_EOK on success, other values on failure
 */
static rt_err_t wifi_config_load(char *ssid, int ssid_len, char *password, int password_len)
{
    if (!ssid || !password)
    {
        return -RT_EINVAL;
    }

    if (!wifi_storage_ready())
    {
        LOG_W("Cannot load WiFi config: /flash storage is not writable/readable");
        return -RT_ERROR;
    }

    rt_err_t ret = wifi_config_load_from_path(WIFI_CONFIG_FILE,
                                              ssid, ssid_len,
                                              password, password_len);
    if (ret == RT_EOK)
    {
        LOG_I("Config loaded: SSID=%s", ssid);
    }
    return ret;
}

/*****************************************************************************
 * Private Functions - WiFi Scan
 *****************************************************************************/

static void wifi_scan_result_clean(void)
{
    s_scan_cnt = 0;
    rt_memset(s_scan_result, 0, sizeof(s_scan_result));
}

static int wifi_scan_result_cache(struct rt_wlan_info *info)
{
    if (s_scan_cnt >= MAX_SCAN_RESULTS)
        return -RT_EFULL;

    rt_memcpy(&s_scan_result[s_scan_cnt], info, sizeof(struct rt_wlan_info));
    s_scan_cnt++;
    return RT_EOK;
}

static void user_ap_info_callback(int event, struct rt_wlan_buff *buff, void *parameter)
{
    struct rt_wlan_info *info = (struct rt_wlan_info *)buff->data;
    int index = *((int *)parameter);

    if (wifi_scan_result_cache(info) == RT_EOK)
    {
        if (s_scan_filter == RT_NULL ||
            (s_scan_filter->ssid.len == info->ssid.len &&
             rt_memcmp(s_scan_filter->ssid.val, info->ssid.val, s_scan_filter->ssid.len) == 0))
        {
            index++;
            *((int *)parameter) = index;
        }
    }
}

static void cgi_wifi_scan(struct webnet_session *session)
{
    int ret;
    int index = 0;
    struct rt_wlan_info *info = RT_NULL;

    wifi_scan_result_clean();
    s_scan_filter = RT_NULL;

    rt_wlan_register_event_handler(RT_WLAN_EVT_SCAN_REPORT,
                                   user_ap_info_callback, &index);

    ret = rt_wlan_scan_with_info(info);
    if (ret != RT_EOK)
    {
        LOG_W("Scan failed: %d", ret);
    }

    int len = rt_snprintf(s_result_buffer, RESULT_BUF_SIZE, "[");

    for (int i = 0; i < s_scan_cnt; i++)
    {
        len += rt_snprintf(s_result_buffer + len,
                           RESULT_BUF_SIZE - len,
                           "{\"ssid\":\"%s\",\"rssi\":%d}%s",
                           s_scan_result[i].ssid.val,
                           s_scan_result[i].rssi,
                           (i == s_scan_cnt - 1) ? "" : ",");
    }

    len += rt_snprintf(s_result_buffer + len, RESULT_BUF_SIZE - len, "]");
    webnet_session_set_header(session, "application/json", 200, "OK", len);
    webnet_session_write(session, (rt_uint8_t *)s_result_buffer, len);
}

static void wlan_ready_handler(int event, struct rt_wlan_buff *buff, void *parameter)
{
    if (event == RT_WLAN_EVT_READY && !s_sta_connected)
    {
        s_sta_connected = RT_TRUE;
        LOG_I("STA connected to router successfully");

        /* Save WiFi config to flash filesystem */
        if (s_saved_ssid[0] != '\0')
        {
            wifi_config_save(s_saved_ssid, s_saved_password);
        }

        rt_thread_mdelay(3000);

        rt_wlan_ap_stop();
        LOG_I("Soft-AP stopped. Configuration completed");

        xiaozhi_ui_clear_info();
        ws_xiaozhi_init();
    }
}

static void cgi_wifi_connect(struct webnet_session *session)
{
    struct webnet_request *request = session->request;
    const char *ssid     = webnet_request_get_query(request, "ssid");
    const char *password = webnet_request_get_query(request, "password");
    const char *mimetype = mime_get_type(".html");
    int len;

    if (!ssid || rt_strlen(ssid) == 0)
    {
        len = rt_snprintf(s_result_buffer, RESULT_BUF_SIZE,
            "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
            "<style>body{font-family:Arial;text-align:center;padding:100px;background:#f7f9fc}</style>"
            "</head><body>"
            "<h2 style=\"color:red\">Error: WiFi name (SSID) cannot be empty!</h2>"
            "<p><a href=\"/index.html\">Back</a></p>"
            "</body></html>");
    }
    else
    {
        /* Save SSID and password to temp cache, write to file after connection success */
        rt_strncpy(s_saved_ssid, ssid, sizeof(s_saved_ssid) - 1);
        s_saved_ssid[sizeof(s_saved_ssid) - 1] = '\0';
        if (password && rt_strlen(password) > 0)
        {
            rt_strncpy(s_saved_password, password, sizeof(s_saved_password) - 1);
            s_saved_password[sizeof(s_saved_password) - 1] = '\0';
        }
        else
        {
            s_saved_password[0] = '\0';
        }

        LOG_I("Connecting to SSID: %s", ssid);
        rt_err_t ret = rt_wlan_connect(ssid,
                     (password && rt_strlen(password) > 0) ? password : RT_NULL);

        if (ret == RT_EOK)
        {
            len = rt_snprintf(s_result_buffer, RESULT_BUF_SIZE,
                "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
                "<style>body{font-family:Arial;text-align:center;padding:80px;background:#f7f9fc}</style>"
                "</head><body>"
                "<h2>Connecting to WiFi...</h2>"
                "<h3><strong>%s</strong></h3>"
                "<p style=\"color:green;font-size:20px\">Connected successfully!</p>"
                "Your Board will switch to the WiFi automatically.</p>"
                "</body></html>", ssid);
        }
        else
        {
            /* Connection failed, clear temp saved config */
            s_saved_ssid[0] = '\0';
            s_saved_password[0] = '\0';

            len = rt_snprintf(s_result_buffer, RESULT_BUF_SIZE,
                "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
                "<style>body{font-family:Arial;text-align:center;padding:80px;background:#f7f9fc}</style>"
                "</head><body>"
                "<h2 style=\"color:red\">Connection failed!</h2>"
                "<p>Error code: %d<br>"
                "Possible reasons: wrong password, weak signal, or router rejected.</p>"
                "<br><a href=\"/index.html\">Try again</a>"
                "</body></html>", ret);
        }
    }

    session->request->result_code = 200;
    webnet_session_set_header(session, mimetype, 200, "Ok", len);
    webnet_session_write(session, (const rt_uint8_t*)s_result_buffer, len);
}

/**
 * @brief Start AP configuration mode
 */
static void start_ap_config_mode(void)
{
    rt_err_t ret;

    LOG_I("Waiting for WLAN AP device %s...", RT_WLAN_DEVICE_AP_NAME);
    if (wifi_wait_device(RT_WLAN_DEVICE_AP_NAME) != RT_EOK)
    {
        return;
    }

    ret = rt_wlan_set_mode(RT_WLAN_DEVICE_AP_NAME, RT_WLAN_AP);
    if (ret != RT_EOK)
    {
        LOG_E("Set WLAN AP mode failed: %d", ret);
        return;
    }

    /* Start AP */
    ret = rt_wlan_start_ap("RT-Thread-AP", "123456789");
    if (ret != RT_EOK)
    {
        LOG_E("Start AP failed: %d", ret);
        return;
    }
    LOG_I("AP Started -> SSID: RT-Thread-AP Password: 123456789");

    /* Wait for AP network interface ready */
    rt_thread_mdelay(1000);

    /* Start HTTP server after AP is fully ready */
    webnet_init();
    LOG_I("HTTP Server started");

    webnet_cgi_register("wifi_connect", cgi_wifi_connect);
    webnet_cgi_register("wifi_scan", cgi_wifi_scan);

    LOG_I("=== WiFi Config Portal Ready ===");
    LOG_I("Open browser -> http://192.168.169.1");
}

/**
 * @brief Disconnect event handler
 */
static void wlan_disconnect_handler(int event, struct rt_wlan_buff *buff, void *parameter)
{
    if (event == RT_WLAN_EVT_STA_DISCONNECTED)
    {
        LOG_W("STA disconnected from router");
        s_sta_connected = RT_FALSE;
    }
}

/**
 * @brief Try to connect WiFi with saved configuration
 * @return RT_EOK on success, other values on failure
 */
static rt_err_t try_connect_with_saved_config(void)
{
    char ssid[64] = {0};
    char password[64] = {0};
    rt_err_t ret;
    int retry_cnt = 0;
    const int max_retry = 3;

    /* Load WiFi config from flash filesystem */
    if (wifi_config_load(ssid, sizeof(ssid), password, sizeof(password)) != RT_EOK)
    {
        LOG_I("No saved config found");
        return -RT_ENOSYS;
    }

    LOG_I("Trying to connect with saved config: %s", ssid);

    /* Show connecting status on UI */
    xiaozhi_ui_show_connecting();

    /* Save to temp cache for re-saving */
    rt_strncpy(s_saved_ssid, ssid, sizeof(s_saved_ssid) - 1);
    s_saved_ssid[sizeof(s_saved_ssid) - 1] = '\0';
    rt_strncpy(s_saved_password, password, sizeof(s_saved_password) - 1);
    s_saved_password[sizeof(s_saved_password) - 1] = '\0';

    /* Ensure WLAN STA mode is set */
    LOG_I("Waiting for WLAN STA device %s...", RT_WLAN_DEVICE_STA_NAME);
    if (wifi_wait_device(RT_WLAN_DEVICE_STA_NAME) != RT_EOK)
    {
        return -RT_ETIMEOUT;
    }

    ret = rt_wlan_set_mode(RT_WLAN_DEVICE_STA_NAME, RT_WLAN_STATION);
    if (ret != RT_EOK)
    {
        LOG_E("Set WLAN station mode failed: %d", ret);
        return ret;
    }
    rt_thread_mdelay(100);

    /* Try to connect WiFi with retry mechanism */
    while (retry_cnt < max_retry)
    {
        ret = rt_wlan_connect(ssid, (password[0] != '\0') ? password : RT_NULL);
        if (ret == RT_EOK)
        {
            break;
        }

        retry_cnt++;
        LOG_W("Connect attempt %d failed: %d, retrying...", retry_cnt, ret);
        rt_thread_mdelay(1000);
    }

    if (ret != RT_EOK)
    {
        LOG_E("Connect with saved config failed after %d retries: %d", max_retry, ret);
        /* Clear temp cache */
        s_saved_ssid[0] = '\0';
        s_saved_password[0] = '\0';
        return ret;
    }

    /* Wait for connection result */
    LOG_I("Waiting for connection...");
    for (int i = 0; i < (WIFI_CONNECT_TIMEOUT_S * 2); i++)
    {
        rt_thread_mdelay(500);
        if (rt_wlan_is_connected())
        {
            LOG_I("Connected to %s successfully", ssid);
            s_sta_connected = RT_TRUE;

            xiaozhi_ui_clear_info();
            ws_xiaozhi_init();
            return RT_EOK;
        }
    }

    LOG_W("Connection timeout");
    rt_wlan_disconnect();
    s_saved_ssid[0] = '\0';
    s_saved_password[0] = '\0';
    return -RT_ETIMEOUT;
}

/*****************************************************************************
 * Public Functions
 *****************************************************************************/

void wifi_manager_init(void)
{
    static rt_bool_t s_inited = RT_FALSE;

    if (s_inited)
    {
        return;
    }
    s_inited = RT_TRUE;

    /* Register event handlers */
    rt_wlan_register_event_handler(RT_WLAN_EVT_READY, wlan_ready_handler, RT_NULL);
    rt_wlan_register_event_handler(RT_WLAN_EVT_STA_DISCONNECTED, wlan_disconnect_handler, RT_NULL);

    /* Wait until the mounted /flash filesystem is actually writable. */
    LOG_I("Waiting for writable /flash filesystem...");
    rt_bool_t storage_ready = RT_FALSE;
    for (int i = 0; i < (FLASH_MOUNT_TIMEOUT_S * 2); i++)
    {
        if (wifi_storage_ready())
        {
            storage_ready = RT_TRUE;
            break;
        }
        rt_thread_mdelay(500);
    }
    if (!storage_ready)
    {
        LOG_W("/flash filesystem is not writable after %d seconds", FLASH_MOUNT_TIMEOUT_S);
    }

    /* Try to connect with saved config */
    if (try_connect_with_saved_config() == RT_EOK)
    {
        LOG_I("Auto connect succeeded, skip AP config mode");
        return;
    }

    /* Connection failed or no config, start AP config mode */
    LOG_I("Starting AP config mode...");

    /* Show AP config info on UI */
    xiaozhi_ui_show_ap_config();

    start_ap_config_mode();
}

rt_bool_t wifi_manager_is_connected(void)
{
    return s_sta_connected;
}

#ifdef RT_USING_FINSH
#include <finsh.h>

static int wifi_cfg_status(void)
{
    char ssid[64] = {0};
    char password[64] = {0};
    rt_bool_t storage = wifi_storage_ready();

    rt_kprintf("wifi_cfg_status: storage_ready=%d connected=%d path=%s\n",
               storage, s_sta_connected, WIFI_CONFIG_FILE);

    if (storage &&
        wifi_config_load_from_path(WIFI_CONFIG_FILE,
                                   ssid, sizeof(ssid),
                                   password, sizeof(password)) == RT_EOK)
    {
        rt_kprintf("wifi_cfg_status: saved_ssid=%s password_set=%s\n",
                   ssid, password[0] != '\0' ? "yes" : "no");
    }
    else
    {
        rt_kprintf("wifi_cfg_status: no saved WiFi config\n");
    }

    return RT_EOK;
}
MSH_CMD_EXPORT(wifi_cfg_status, Show saved WiFi config and flash storage status);

static int wifi_cfg_clear(void)
{
    if (unlink(WIFI_CONFIG_TMP_FILE) != 0)
    {
        rt_kprintf("wifi_cfg_clear: temp remove skipped, errno=%d\n",
                   rt_get_errno());
    }
    if (unlink(WIFI_CONFIG_FILE) == 0)
    {
        rt_kprintf("wifi_cfg_clear: removed %s\n", WIFI_CONFIG_FILE);
    }
    else
    {
        rt_kprintf("wifi_cfg_clear: no saved config or remove failed\n");
    }

    s_saved_ssid[0] = '\0';
    s_saved_password[0] = '\0';
    return RT_EOK;
}
MSH_CMD_EXPORT(wifi_cfg_clear, Clear saved WiFi config);

static void flash_test_cleanup(void)
{
    unlink(FLASH_TEST_FILE);
    unlink(FLASH_TEST_RENAMED_FILE);
}

static int flash_test_once(int iteration)
{
    rt_uint8_t write_buf[FLASH_TEST_DATA_SIZE];
    rt_uint8_t read_buf[FLASH_TEST_DATA_SIZE];
    int fd;
    int result;

    for (int i = 0; i < FLASH_TEST_DATA_SIZE; i++)
    {
        write_buf[i] = (rt_uint8_t)((i * 37 + iteration * 13) & 0xff);
    }
    rt_memset(read_buf, 0, sizeof(read_buf));
    flash_test_cleanup();

    fd = open(FLASH_TEST_FILE, O_WRONLY | O_CREAT | O_TRUNC, 0);
    if (fd < 0)
    {
        rt_kprintf("flash_test[%d]: create failed, errno=%d\n",
                   iteration, rt_get_errno());
        return -RT_ERROR;
    }

    result = write(fd, write_buf, sizeof(write_buf));
    if (result != sizeof(write_buf))
    {
        int err = rt_get_errno();
        rt_kprintf("flash_test[%d]: write failed, result=%d/%d errno=%d\n",
                   iteration, result, (int)sizeof(write_buf), err);
        close(fd);
        flash_test_cleanup();
        return -RT_ERROR;
    }
    if (close(fd) != 0)
    {
        rt_kprintf("flash_test[%d]: write close failed, errno=%d\n",
                   iteration, rt_get_errno());
        flash_test_cleanup();
        return -RT_ERROR;
    }

    fd = open(FLASH_TEST_FILE, O_RDONLY);
    if (fd < 0)
    {
        rt_kprintf("flash_test[%d]: readback open failed, errno=%d\n",
                   iteration, rt_get_errno());
        flash_test_cleanup();
        return -RT_ERROR;
    }
    result = read(fd, read_buf, sizeof(read_buf));
    if (result != sizeof(read_buf))
    {
        int err = rt_get_errno();
        rt_kprintf("flash_test[%d]: readback failed, result=%d/%d errno=%d\n",
                   iteration, result, (int)sizeof(read_buf), err);
        close(fd);
        flash_test_cleanup();
        return -RT_ERROR;
    }
    if (close(fd) != 0)
    {
        rt_kprintf("flash_test[%d]: readback close failed, errno=%d\n",
                   iteration, rt_get_errno());
        flash_test_cleanup();
        return -RT_ERROR;
    }
    if (rt_memcmp(write_buf, read_buf, sizeof(write_buf)) != 0)
    {
        rt_kprintf("flash_test[%d]: data mismatch before rename\n", iteration);
        flash_test_cleanup();
        return -RT_ERROR;
    }

    if (rename(FLASH_TEST_FILE, FLASH_TEST_RENAMED_FILE) != 0)
    {
        rt_kprintf("flash_test[%d]: rename failed, errno=%d\n",
                   iteration, rt_get_errno());
        flash_test_cleanup();
        return -RT_ERROR;
    }

    rt_memset(read_buf, 0, sizeof(read_buf));
    fd = open(FLASH_TEST_RENAMED_FILE, O_RDONLY);
    if (fd < 0)
    {
        rt_kprintf("flash_test[%d]: renamed file open failed, errno=%d\n",
                   iteration, rt_get_errno());
        flash_test_cleanup();
        return -RT_ERROR;
    }
    result = read(fd, read_buf, sizeof(read_buf));
    if (result != sizeof(read_buf) ||
        rt_memcmp(write_buf, read_buf, sizeof(write_buf)) != 0)
    {
        int err = rt_get_errno();
        rt_kprintf("flash_test[%d]: renamed file verify failed, result=%d errno=%d\n",
                   iteration, result, err);
        close(fd);
        flash_test_cleanup();
        return -RT_ERROR;
    }
    if (close(fd) != 0)
    {
        rt_kprintf("flash_test[%d]: renamed file close failed, errno=%d\n",
                   iteration, rt_get_errno());
        flash_test_cleanup();
        return -RT_ERROR;
    }

    if (unlink(FLASH_TEST_RENAMED_FILE) != 0)
    {
        rt_kprintf("flash_test[%d]: cleanup unlink failed, errno=%d\n",
                   iteration, rt_get_errno());
        flash_test_cleanup();
        return -RT_ERROR;
    }

    return RT_EOK;
}

static int flash_test(int argc, char **argv)
{
    int count = 1;

    if (argc > 1)
    {
        count = atoi(argv[1]);
        if (count < 1 || count > 100)
        {
            rt_kprintf("usage: flash_test [count 1..100]\n");
            return -RT_EINVAL;
        }
    }

    rt_kprintf("flash_test: start count=%d size=%d path=%s\n",
               count, FLASH_TEST_DATA_SIZE, FLASH_TEST_FILE);
    for (int i = 1; i <= count; i++)
    {
        if (flash_test_once(i) != RT_EOK)
        {
            rt_kprintf("flash_test: FAILED at iteration %d/%d\n", i, count);
            return -RT_ERROR;
        }
        rt_kprintf("flash_test: iteration %d/%d passed\n", i, count);
    }

    rt_kprintf("flash_test: PASS (%d iterations)\n", count);
    return RT_EOK;
}
MSH_CMD_EXPORT(flash_test, Test flash create write read rename and delete);
#endif

/* Legacy API for backward compatibility */
void wifi_init(void)
{
    wifi_manager_init();
}
