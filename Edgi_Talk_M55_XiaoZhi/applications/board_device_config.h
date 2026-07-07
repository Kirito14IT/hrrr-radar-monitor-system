#ifndef __BOARD_DEVICE_CONFIG_H__
#define __BOARD_DEVICE_CONFIG_H__

/*
 * 小智/呼噜板编译期配置文件。
 *
 * 多块板可以烧录同一套代码，但每块板烧录前请在这里改成对应床位。
 * 例如第二块板：
 *   BOARD_BED_ID        "bed-002"
 *   BOARD_DEVICE_ID     "xiaozhi-bed-002"
 *   BOARD_EDGI_SOURCE   "xiaozhi_board_002"
 *   BOARD_SNORE_SOURCE  "real_snore_board_002"
 *   BOARD_ENV_SOURCE    "edgi_talk_m55_002"
 *
 * 为了避免旧 Flash 配置覆盖编译配置，下面两个开关默认关闭。
 * 如确实需要串口命令 backend_cfg_set / device_cfg_set 覆盖，再改为 1。
 */

#define BOARD_BACKEND_HOST "192.168.31.236"
#define BOARD_BACKEND_PORT 8081

#define BOARD_BED_ID        "bed-001"
#define BOARD_DEVICE_ID     "xiaozhi-bed-001"
#define BOARD_EDGI_SOURCE   "xiaozhi_board_001"
#define BOARD_SNORE_SOURCE  "real_snore_board_001"
#define BOARD_ENV_SOURCE    "edgi_talk_m55_001"

#define BOARD_USE_FLASH_BACKEND_CONFIG 0
#define BOARD_USE_FLASH_DEVICE_CONFIG  0

#endif /* __BOARD_DEVICE_CONFIG_H__ */
