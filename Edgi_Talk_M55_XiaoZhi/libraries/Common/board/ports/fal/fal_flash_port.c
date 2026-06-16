/*
 * Copyright (c) 2006-2018, RT-Thread Development Team
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * Change Logs:
 * Date           Author       Notes
 * 2018-01-26     armink       the first version
 */

#include <fal.h>
#include "cycfg_qspi_memslot.h"
#include <string.h>
#include "cy_smif.h"

#define LOG_TAG                "drv.fal_flash"
#include <drv_log.h>

/* Objects for serial memory */
static cy_stc_smif_context_t smif_context;

#define smifMemConfigs smif0MemConfigs
#define MEM_SLOT_NUM                     (0U)
#ifndef FAL_USING_NOR_FLASH_DEV_NAME
#define FAL_USING_NOR_FLASH_DEV_NAME             "norflash0"
#endif

/* Flash device configuration */
#define SMIF_BASE_ADDRESS      0x60000000
#define FLASH_START_ADDRESS    0x60E00000
#define FLASH_SIZE             (2 * 1024 * 1024) /* 2MB */
#define FLASH_SECTOR_SIZE      (64 * 1024) /* S25FS128S main-array erase size */
#define FLASH_END_ADDRESS      (FLASH_START_ADDRESS + FLASH_SIZE)

static int init(void);
static int read(long offset, uint8_t *buf, size_t size);
static int write(long offset, const uint8_t *buf, size_t size);
static int erase(long offset, size_t size);

struct rt_device *flash_dev;
struct fal_flash_dev nor_flash0 =
{
    .name       = FAL_USING_NOR_FLASH_DEV_NAME,
    .addr       = FLASH_START_ADDRESS,
    .len        = FLASH_SIZE,
    .blk_size   = FLASH_SECTOR_SIZE,
    .ops        = {init, read, write, erase},
    .write_gran = 1
};

static int init(void)
{
    /* SMIF already initialized by cybsp_init() */
    LOG_I("FAL flash ready: start=%#lx size=%lu erase_size=%lu",
          (unsigned long)FLASH_START_ADDRESS,
          (unsigned long)FLASH_SIZE,
          (unsigned long)FLASH_SECTOR_SIZE);
    return 0;
}

static int read(long offset, uint8_t *buf, size_t size)
{
    uint32_t mapped_address;

    if (offset < 0 || size > FLASH_SIZE ||
        (size_t)offset > FLASH_SIZE - size)
    {
        LOG_E("read out of range: offset=%ld size=%lu flash_size=%lu",
              offset, (unsigned long)size, (unsigned long)FLASH_SIZE);
        return -RT_EINVAL;
    }

    mapped_address = (uint32_t)offset + (FLASH_START_ADDRESS - SMIF_BASE_ADDRESS);
    LOG_D("FAL read: offset=%#lx mapped=%#lx absolute=%#lx size=%lu",
          offset, (unsigned long)mapped_address,
          (unsigned long)(FLASH_START_ADDRESS + offset),
          (unsigned long)size);
    cy_en_smif_status_t result;
    result = Cy_SMIF_MemRead(SMIF0_CORE, smifMemConfigs[MEM_SLOT_NUM],
                             mapped_address, buf, size, &smif_context);
    if (result != CY_SMIF_SUCCESS)
    {
        LOG_E("SMIF read failed: status=%d offset=%#lx mapped=%#lx absolute=%#lx size=%lu",
              result, offset, (unsigned long)mapped_address,
              (unsigned long)(FLASH_START_ADDRESS + offset),
              (unsigned long)size);
        return -RT_ERROR;
    }

    return size;
}

static int write(long offset, const uint8_t *buf, size_t size)
{
    uint32_t mapped_address;

    if (!buf || size == 0)
    {
        LOG_E("invalid write input: buf=%p size=%lu",
              buf, (unsigned long)size);
        return -RT_EINVAL;
    }

    if (offset < 0 || size > FLASH_SIZE ||
        (size_t)offset > FLASH_SIZE - size)
    {
        LOG_E("write out of range: offset=%ld size=%lu flash_size=%lu",
              offset, (unsigned long)size, (unsigned long)FLASH_SIZE);
        return -RT_EINVAL;
    }

    mapped_address = (uint32_t)offset + (FLASH_START_ADDRESS - SMIF_BASE_ADDRESS);
    LOG_D("FAL write: offset=%#lx mapped=%#lx absolute=%#lx size=%lu",
          offset, (unsigned long)mapped_address,
          (unsigned long)(FLASH_START_ADDRESS + offset),
          (unsigned long)size);
    cy_en_smif_status_t result;
    result = Cy_SMIF_MemWrite(SMIF0_CORE, smifMemConfigs[MEM_SLOT_NUM],
                              mapped_address, buf, size, &smif_context);
    if (result != CY_SMIF_SUCCESS)
    {
        LOG_E("SMIF write failed: status=%d offset=%#lx mapped=%#lx absolute=%#lx size=%lu",
              result, offset, (unsigned long)mapped_address,
              (unsigned long)(FLASH_START_ADDRESS + offset),
              (unsigned long)size);
        return -RT_ERROR;
    }

    return size;
}

static int erase(long offset, size_t size)
{
    uint32_t mapped_address;

    if (offset < 0 || size == 0 || size > FLASH_SIZE ||
        (size_t)offset > FLASH_SIZE - size)
    {
        LOG_E("erase out of range: offset=%ld size=%lu flash_size=%lu",
              offset, (unsigned long)size, (unsigned long)FLASH_SIZE);
        return -RT_EINVAL;
    }

    if (((uint32_t)offset % FLASH_SECTOR_SIZE) != 0 ||
        (size % FLASH_SECTOR_SIZE) != 0)
    {
        LOG_E("erase is not aligned: offset=%#lx size=%lu erase_size=%lu",
              offset, (unsigned long)size,
              (unsigned long)FLASH_SECTOR_SIZE);
        return -RT_EINVAL;
    }

    mapped_address = (uint32_t)offset + (FLASH_START_ADDRESS - SMIF_BASE_ADDRESS);
    LOG_D("FAL erase: offset=%#lx mapped=%#lx absolute=%#lx size=%lu",
          offset, (unsigned long)mapped_address,
          (unsigned long)(FLASH_START_ADDRESS + offset),
          (unsigned long)size);
    cy_en_smif_status_t result;
    result = Cy_SMIF_MemEraseSector(SMIF0_CORE, smifMemConfigs[MEM_SLOT_NUM],
                                    mapped_address, size, &smif_context);
    if (result != CY_SMIF_SUCCESS)
    {
        LOG_E("SMIF erase failed: status=%d offset=%#lx mapped=%#lx absolute=%#lx size=%lu",
              result, offset, (unsigned long)mapped_address,
              (unsigned long)(FLASH_START_ADDRESS + offset),
              (unsigned long)size);
        return -RT_ERROR;
    }
    return size;
}
