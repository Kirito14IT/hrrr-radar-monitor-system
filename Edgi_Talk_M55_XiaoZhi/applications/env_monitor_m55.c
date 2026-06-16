#include <rtthread.h>
#include <rtdevice.h>

#include <arpa/inet.h>
#include <errno.h>
#include <netinet/in.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

#include "backend_target_config.h"
#include "env_shared_memory.h"
#include "xiaozhi/ui/xiaozhi_ui.h"
#include "xiaozhi/webnet/wifi_manager.h"

#define DBG_TAG "env.m55"
#define DBG_LVL DBG_INFO
#include <rtdbg.h>

#ifndef ENV_BACKEND_TARGET_IP
#define ENV_BACKEND_TARGET_IP "192.168.0.101"
#endif

#ifndef ENV_BACKEND_TARGET_PORT
#define ENV_BACKEND_TARGET_PORT 8081
#endif

#define ENV_MONITOR_THREAD_STACK     4096
#define ENV_MONITOR_THREAD_PRIORITY  24
#define ENV_MONITOR_THREAD_TICK      10
#define ENV_MONITOR_PERIOD_MS        2000
#define ENV_MONITOR_POST_MS          5000
#define ENV_MONITOR_STALE_MS         10000

typedef struct
{
    rt_bool_t shared_ready;
    rt_bool_t valid;
    rt_bool_t stale;
    uint8_t status;
    uint32_t seq;
    int16_t temperature_c_x10;
    int16_t humidity_pct_x10;
    float temperature_c;
    float humidity_pct;
} env_monitor_state_t;

static env_monitor_state_t s_env_state;
static rt_tick_t s_last_seq_change_tick;
static rt_tick_t s_last_post_tick;

static const char *env_status_text(uint8_t status, rt_bool_t stale, rt_bool_t shared_ready)
{
    if (!shared_ready)
    {
        return "NO_DATA";
    }

    if (stale)
    {
        return "STALE";
    }

    switch (status)
    {
    case ENV_SHARED_STATUS_BOOTING:
        return "BOOTING";
    case ENV_SHARED_STATUS_OK:
        return "OK";
    case ENV_SHARED_STATUS_SENSOR_ERROR:
        return "SENSOR_ERROR";
    case ENV_SHARED_STATUS_STALE:
        return "STALE";
    default:
        return "UNKNOWN";
    }
}

static rt_bool_t tick_elapsed(rt_tick_t start, uint32_t ms)
{
    rt_tick_t elapsed = rt_tick_get() - start;
    return elapsed >= rt_tick_from_millisecond(ms);
}

static int env_send_all(int sockfd, const char *data, int len)
{
    int sent_total = 0;

    while (sent_total < len)
    {
        int sent = (int)send(sockfd, data + sent_total, len - sent_total, 0);
        if (sent <= 0)
        {
            return -RT_ERROR;
        }
        sent_total += sent;
    }

    return RT_EOK;
}

static void env_format_x10(char *buf, int len, int value_x10)
{
    int abs_value = value_x10 < 0 ? -value_x10 : value_x10;

    rt_snprintf(buf, len, "%s%d.%d",
                value_x10 < 0 ? "-" : "",
                abs_value / 10,
                abs_value % 10);
}

static int env_http_post_heartbeat(int16_t temperature_c_x10,
                                   int16_t humidity_pct_x10,
                                   rt_bool_t sensor_ok)
{
    char body[192];
    char header[256];
    char response[96];
    char temp_text[16];
    char humidity_text[16];
    char backend_host[BACKEND_TARGET_HOST_LEN] = {0};
    int backend_port = ENV_BACKEND_TARGET_PORT;
    struct sockaddr_in server_addr;
    int sockfd;
    int body_len;
    int header_len;

    backend_target_get(ENV_BACKEND_TARGET_IP, ENV_BACKEND_TARGET_PORT,
                       backend_host, sizeof(backend_host), &backend_port);

    env_format_x10(temp_text, sizeof(temp_text), temperature_c_x10);
    env_format_x10(humidity_text, sizeof(humidity_text), humidity_pct_x10);

    body_len = rt_snprintf(body, sizeof(body),
                           "{\"temperature_c\":%s,\"humidity_pct\":%s,"
                           "\"sensor_ok\":%s,\"source\":\"edgi_talk_m55\"}",
                           temp_text,
                           humidity_text,
                           sensor_ok ? "true" : "false");
    if (body_len <= 0 || body_len >= (int)sizeof(body))
    {
        LOG_W("Environment heartbeat body overflow");
        return -RT_ERROR;
    }

    header_len = rt_snprintf(header, sizeof(header),
                             "POST /mock/environment-heartbeat HTTP/1.1\r\n"
                             "Host: %s:%d\r\n"
                             "Content-Type: application/json\r\n"
                             "Content-Length: %d\r\n"
                             "Connection: close\r\n"
                             "\r\n",
                             backend_host,
                             backend_port,
                             body_len);
    if (header_len <= 0 || header_len >= (int)sizeof(header))
    {
        LOG_W("Environment heartbeat header overflow");
        return -RT_ERROR;
    }

    sockfd = socket(AF_INET, SOCK_STREAM, 0);
    if (sockfd < 0)
    {
        LOG_W("Environment heartbeat socket failed, errno=%d", errno);
        return -RT_ERROR;
    }

    memset(&server_addr, 0, sizeof(server_addr));
    server_addr.sin_family = AF_INET;
    server_addr.sin_port = htons(backend_port);
    server_addr.sin_addr.s_addr = inet_addr(backend_host);

    if (connect(sockfd, (struct sockaddr *)&server_addr, sizeof(server_addr)) != 0)
    {
        LOG_W("Environment heartbeat connect %s:%d failed, errno=%d",
              backend_host, backend_port, errno);
        close(sockfd);
        return -RT_ERROR;
    }

    if (env_send_all(sockfd, header, header_len) != RT_EOK ||
        env_send_all(sockfd, body, body_len) != RT_EOK)
    {
        LOG_W("Environment heartbeat send failed, errno=%d", errno);
        close(sockfd);
        return -RT_ERROR;
    }

    memset(response, 0, sizeof(response));
    int received = (int)recv(sockfd, response, sizeof(response) - 1, 0);
    close(sockfd);

    if (received <= 0 ||
        (strstr(response, " 200 ") == RT_NULL && strstr(response, " 201 ") == RT_NULL))
    {
        LOG_W("Environment heartbeat rejected by %s:%d: %s",
              backend_host, backend_port, received > 0 ? response : "no response");
        return -RT_ERROR;
    }

    LOG_I("Environment heartbeat posted: temp=%s humidity=%s ok=%d",
          temp_text, humidity_text, sensor_ok);
    return RT_EOK;
}

static void env_monitor_read_state(void)
{
    env_shared_data_t data;
    rt_tick_t now = rt_tick_get();

    if (!env_shared_memory_read(&data))
    {
        s_env_state.shared_ready = RT_FALSE;
        s_env_state.valid = RT_FALSE;
        s_env_state.stale = RT_FALSE;
        s_env_state.status = ENV_SHARED_STATUS_BOOTING;
        return;
    }

    if (s_env_state.seq != data.seq)
    {
        s_env_state.seq = data.seq;
        s_last_seq_change_tick = now;
    }

    s_env_state.shared_ready = RT_TRUE;
    s_env_state.status = data.status;
    s_env_state.temperature_c_x10 = data.temperature_c_x10;
    s_env_state.humidity_pct_x10 = data.humidity_pct_x10;
    s_env_state.temperature_c = (float)data.temperature_c_x10 / 10.0f;
    s_env_state.humidity_pct = (float)data.humidity_pct_x10 / 10.0f;
    s_env_state.stale = tick_elapsed(s_last_seq_change_tick, ENV_MONITOR_STALE_MS);
    s_env_state.valid = data.valid &&
                        data.status == ENV_SHARED_STATUS_OK &&
                        !s_env_state.stale;
}

static void env_monitor_update_ui(void)
{
    const char *status = env_status_text(s_env_state.status,
                                         s_env_state.stale,
                                         s_env_state.shared_ready);

    xiaozhi_ui_set_environment(s_env_state.temperature_c,
                               s_env_state.humidity_pct,
                               s_env_state.valid,
                               status);
}

static void env_monitor_maybe_post(void)
{
    if (!wifi_manager_is_connected())
    {
        return;
    }

    if (!tick_elapsed(s_last_post_tick, ENV_MONITOR_POST_MS))
    {
        return;
    }

    s_last_post_tick = rt_tick_get();
    (void)env_http_post_heartbeat(s_env_state.valid ? s_env_state.temperature_c_x10 : 0,
                                  s_env_state.valid ? s_env_state.humidity_pct_x10 : 0,
                                  s_env_state.valid);
}

static void env_monitor_thread_entry(void *parameter)
{
    char backend_host[BACKEND_TARGET_HOST_LEN] = {0};
    int backend_port = ENV_BACKEND_TARGET_PORT;

    (void)parameter;

    s_last_seq_change_tick = rt_tick_get();
    s_last_post_tick = rt_tick_get();
    backend_target_get(ENV_BACKEND_TARGET_IP, ENV_BACKEND_TARGET_PORT,
                       backend_host, sizeof(backend_host), &backend_port);
    LOG_I("Environment monitor started, backend=%s:%d",
          backend_host, backend_port);

    while (1)
    {
        env_monitor_read_state();
        env_monitor_update_ui();
        env_monitor_maybe_post();
        rt_thread_mdelay(ENV_MONITOR_PERIOD_MS);
    }
}

int env_monitor_init(void)
{
    static rt_bool_t s_inited = RT_FALSE;
    rt_thread_t tid;

    if (s_inited)
    {
        return RT_EOK;
    }
    s_inited = RT_TRUE;

    memset(&s_env_state, 0, sizeof(s_env_state));

    tid = rt_thread_create("env_m55", env_monitor_thread_entry, RT_NULL,
                           ENV_MONITOR_THREAD_STACK,
                           ENV_MONITOR_THREAD_PRIORITY,
                           ENV_MONITOR_THREAD_TICK);
    if (tid == RT_NULL)
    {
        LOG_E("Create env_m55 thread failed");
        return -RT_ERROR;
    }

    rt_thread_startup(tid);
    return RT_EOK;
}

#ifdef RT_USING_FINSH
#include <finsh.h>

static int env_status(void)
{
    env_shared_data_t data;
    char temp_text[16];
    char humidity_text[16];
    char backend_host[BACKEND_TARGET_HOST_LEN] = {0};
    int backend_port = ENV_BACKEND_TARGET_PORT;
    const char *status = env_status_text(s_env_state.status,
                                         s_env_state.stale,
                                         s_env_state.shared_ready);

    env_format_x10(temp_text, sizeof(temp_text), s_env_state.temperature_c_x10);
    env_format_x10(humidity_text, sizeof(humidity_text), s_env_state.humidity_pct_x10);
    backend_target_get(ENV_BACKEND_TARGET_IP, ENV_BACKEND_TARGET_PORT,
                       backend_host, sizeof(backend_host), &backend_port);

    rt_kprintf("env_m55: shared_ready=%d valid=%d stale=%d status=%s seq=%u\n",
               s_env_state.shared_ready,
               s_env_state.valid,
               s_env_state.stale,
               status,
               s_env_state.seq);
    rt_kprintf("env_m55: temp=%sC humidity=%s%%RH backend=%s:%d wifi=%d\n",
               temp_text,
               humidity_text,
               backend_host,
               backend_port,
               wifi_manager_is_connected());

    if (env_shared_memory_read(&data))
    {
        rt_kprintf("shared: magic=0x%08x seq=%u valid=%u status=%u updated_ms=%u temp_x10=%d humidity_x10=%d\n",
                   data.magic,
                   data.seq,
                   data.valid,
                   data.status,
                   data.updated_ms,
                   data.temperature_c_x10,
                   data.humidity_pct_x10);
    }
    else
    {
        rt_kprintf("shared: not initialized\n");
    }

    return 0;
}
MSH_CMD_EXPORT(env_status, Show M55 environment monitor status);
#endif
