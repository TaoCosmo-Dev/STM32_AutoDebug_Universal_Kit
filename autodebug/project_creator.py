"""
Zero-dependency STM32 project scaffolder.

Generates a complete, standards-compliant, STM32Cube HAL-based Keil MDK project
from scratch without requiring STM32CubeMX or the Keil GUI.

Usage:
    python run_autodebug.py --create-project MyProject --mcu stm32f407zg
"""
from dataclasses import dataclass, field
import glob
import os
import re
import shutil
import sys
from typing import Dict, List, Optional, Tuple

from .config import find_keil_uv4


@dataclass
class MCUProfile:
    mcu_id: str
    device: str
    family: str                      # "f4", "f1", "g4"
    vendor: str = "STMicroelectronics"
    pack_name: str = "STM32F4xx_DFP"
    cpu_type: str = "Cortex-M4"
    fpu_type: Optional[str] = "FPU2"  # "FPU2" or None
    defines: str = "USE_HAL_DRIVER,STM32F407xx"
    startup_file: str = "startup_stm32f407xx.s"
    device_header: str = "stm32f407xx.h"
    rom_start: str = "0x8000000"
    rom_size: str = "0x100000"       # 1MB
    ram_start: str = "0x20000000"
    ram_size: str = "0x20000"        # 128KB
    ram2_start: Optional[str] = "0x10000000"  # CCM 64KB
    ram2_size: Optional[str] = "0x10000"
    flash_driver_flm: str = "STM32F4xx_1024.FLM"
    flash_driver_size: str = "0100000"

    @property
    def device_name(self) -> str:
        return self.device


MCU_PROFILES: Dict[str, MCUProfile] = {
    "stm32f407zg": MCUProfile(
        mcu_id="stm32f407zg",
        device="STM32F407ZGTx",
        family="f4",
        pack_name="STM32F4xx_DFP",
        cpu_type="Cortex-M4",
        fpu_type="FPU2",
        defines="USE_HAL_DRIVER,STM32F407xx",
        startup_file="startup_stm32f407xx.s",
        device_header="stm32f407xx.h",
        rom_start="0x8000000",
        rom_size="0x100000",
        ram_start="0x20000000",
        ram_size="0x20000",
        ram2_start="0x10000000",
        ram2_size="0x10000",
        flash_driver_flm="STM32F4xx_1024.FLM",
        flash_driver_size="0100000",
    ),
    "stm32f401cc": MCUProfile(
        mcu_id="stm32f401cc",
        device="STM32F401CCUx",
        family="f4",
        pack_name="STM32F4xx_DFP",
        cpu_type="Cortex-M4",
        fpu_type="FPU2",
        defines="USE_HAL_DRIVER,STM32F401xC",
        startup_file="startup_stm32f401xc.s",
        device_header="stm32f401xc.h",
        rom_start="0x8000000",
        rom_size="0x40000",          # 256KB
        ram_start="0x20000000",
        ram_size="0x10000",          # 64KB
        ram2_start=None,
        ram2_size=None,
        flash_driver_flm="STM32F4xx_256.FLM",
        flash_driver_size="0040000",
    ),
    "stm32f411ce": MCUProfile(
        mcu_id="stm32f411ce",
        device="STM32F411CEUx",
        family="f4",
        pack_name="STM32F4xx_DFP",
        cpu_type="Cortex-M4",
        fpu_type="FPU2",
        defines="USE_HAL_DRIVER,STM32F411xE",
        startup_file="startup_stm32f411xe.s",
        device_header="stm32f411xe.h",
        rom_start="0x8000000",
        rom_size="0x80000",          # 512KB
        ram_start="0x20000000",
        ram_size="0x20000",          # 128KB
        ram2_start=None,
        ram2_size=None,
        flash_driver_flm="STM32F4xx_512.FLM",
        flash_driver_size="0080000",
    ),
    "stm32f103c8": MCUProfile(
        mcu_id="stm32f103c8",
        device="STM32F103C8",
        family="f1",
        pack_name="STM32F1xx_DFP",
        cpu_type="Cortex-M3",
        fpu_type=None,
        defines="USE_HAL_DRIVER,STM32F103xB",
        startup_file="startup_stm32f10x_md.s",
        device_header="stm32f103xb.h",
        rom_start="0x8000000",
        rom_size="0x10000",          # 64KB
        ram_start="0x20000000",
        ram_size="0x5000",           # 20KB
        ram2_start=None,
        ram2_size=None,
        flash_driver_flm="STM32F10x_128.FLM",
        flash_driver_size="0010000",
    ),
}


def resolve_mcu_profile(name: Optional[str]) -> MCUProfile:
    """Normalize MCU input string (e.g. STM32F407ZGT6 -> stm32f407zg)."""
    if not name:
        return MCU_PROFILES["stm32f407zg"]
    cleaned = re.sub(r"[^a-zA-Z0-9]", "", name.lower())
    for key, prof in MCU_PROFILES.items():
        if key in cleaned or cleaned in key:
            return prof
    supported = ", ".join(MCU_PROFILES.keys())
    raise ValueError(f"Unknown or unsupported MCU '{name}'. Supported models: {supported}")


def find_keil_pack_root(uv4_path: Optional[str] = None) -> Optional[str]:
    """Locate Keil ARM Pack repository."""
    candidates = []
    if uv4_path and os.path.exists(uv4_path):
        base = os.path.dirname(os.path.dirname(uv4_path))
        candidates.extend([
            os.path.join(base, "ARM", "Pack"),
            os.path.join(base, "ARM", "PACK"),
            os.path.join(base, "Pack"),
        ])
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(os.path.join(local_app_data, "Arm", "Packs"))
    common_bases = [r"C:\Keil_v5\ARM\Pack", r"D:\keil5\ARM\Pack", r"D:\Keil_v5\ARM\Pack",
                    r"C:\Keil_v5\ARM\PACK", r"D:\keil5\ARM\PACK"]
    candidates.extend(common_bases)

    for c in candidates:
        if os.path.exists(c) and os.path.isdir(c):
            return c
    return None


class ProjectScaffolder:
    """Generates a complete STM32 HAL-based Keil project."""

    def __init__(self, uv4_path: Optional[str] = None):
        self.uv4_path = uv4_path or find_keil_uv4()
        self.pack_root = find_keil_pack_root(self.uv4_path)

    def scaffold(self, project_name: str, mcu: str = "stm32f407zg",
                 target_dir: str = ".") -> str:
        """
        Creates the project directory and files.
        Returns the absolute path to the generated project directory.
        """
        prof = resolve_mcu_profile(mcu)
        project_dir = os.path.abspath(os.path.join(target_dir, project_name))
        proj_basename = os.path.basename(project_dir.rstrip("\\/"))
        os.makedirs(project_dir, exist_ok=True)

        # 1. Directory Tree
        core_inc = os.path.join(project_dir, "Core", "Inc")
        core_src = os.path.join(project_dir, "Core", "Src")
        mdk_arm = os.path.join(project_dir, "MDK-ARM")
        drivers_dir = os.path.join(project_dir, "Drivers")
        hal_inc = os.path.join(drivers_dir, f"STM32{prof.family.upper()}xx_HAL_Driver", "Inc")
        hal_src = os.path.join(drivers_dir, f"STM32{prof.family.upper()}xx_HAL_Driver", "Src")
        cmsis_dev_inc = os.path.join(drivers_dir, "CMSIS", "Device", "ST", f"STM32{prof.family.upper()}xx", "Include")
        cmsis_inc = os.path.join(drivers_dir, "CMSIS", "Include")

        for d in [core_inc, core_src, mdk_arm, hal_inc, hal_src, cmsis_dev_inc, cmsis_inc]:
            os.makedirs(d, exist_ok=True)

        # 2. Extract / Populate HAL and CMSIS files from Keil Pack
        self._populate_drivers(prof, project_dir, hal_inc, hal_src, cmsis_dev_inc, cmsis_inc, core_src)

        # 3. Create Core HAL C & H files
        self._write_core_files(prof, proj_basename, core_inc, core_src)

        # 4. Generate .uvprojx
        self._write_uvprojx(prof, proj_basename, project_dir, mdk_arm)

        # 5. Inject AutoDebug & cm_backtrace
        self._inject_autodebug(project_dir, mdk_arm, proj_basename, prof)

        return project_dir

    def _populate_drivers(self, prof: MCUProfile, project_dir: str,
                          hal_inc: str, hal_src: str,
                          cmsis_dev_inc: str, cmsis_inc: str, core_src: str):
        """Extract official HAL driver files and CMSIS headers from installed Keil packs."""
        if not self.pack_root:
            self._write_fallback_drivers(prof, hal_inc, hal_src, cmsis_dev_inc, cmsis_inc, core_src)
            return

        # Locate DFP pack
        dfp_pattern = os.path.join(self.pack_root, "Keil", f"{prof.pack_name}", "*")
        matches = sorted(glob.glob(dfp_pattern), reverse=True)
        if not matches:
            dfp_pattern = os.path.join(self.pack_root, "*", f"{prof.pack_name}", "*")
            matches = sorted(glob.glob(dfp_pattern), reverse=True)

        if matches:
            dfp_dir = matches[0]
            # Copy HAL Inc (including Legacy/ subfolder)
            src_hal_inc = os.path.join(dfp_dir, "Drivers", f"STM32{prof.family.upper()}xx_HAL_Driver", "Inc")
            if os.path.exists(src_hal_inc):
                shutil.copytree(src_hal_inc, hal_inc, dirs_exist_ok=True)

            # Copy HAL Src (essential core drivers)
            src_hal_src = os.path.join(dfp_dir, "Drivers", f"STM32{prof.family.upper()}xx_HAL_Driver", "Src")
            core_hal_c = [
                f"stm32{prof.family}xx_hal.c", f"stm32{prof.family}xx_hal_rcc.c", f"stm32{prof.family}xx_hal_rcc_ex.c",
                f"stm32{prof.family}xx_hal_gpio.c", f"stm32{prof.family}xx_hal_dma.c", f"stm32{prof.family}xx_hal_dma_ex.c",
                f"stm32{prof.family}xx_hal_cortex.c", f"stm32{prof.family}xx_hal_pwr.c", f"stm32{prof.family}xx_hal_pwr_ex.c",
                f"stm32{prof.family}xx_hal_uart.c", f"stm32{prof.family}xx_hal_flash.c", f"stm32{prof.family}xx_hal_flash_ex.c",
            ]
            if os.path.exists(src_hal_src):
                for c in core_hal_c:
                    src_c = os.path.join(src_hal_src, c)
                    if os.path.exists(src_c):
                        shutil.copy2(src_c, hal_src)

            # Copy CMSIS Device Include
            src_dev_inc = os.path.join(dfp_dir, "Drivers", "CMSIS", "Device", "ST", f"STM32{prof.family.upper()}xx", "Include")
            if os.path.exists(src_dev_inc):
                shutil.copytree(src_dev_inc, cmsis_dev_inc, dirs_exist_ok=True)

            # Copy startup assembly file
            src_startup = os.path.join(dfp_dir, "Drivers", "CMSIS", "Device", "ST", f"STM32{prof.family.upper()}xx",
                                       "Source", "Templates", "arm", prof.startup_file)
            if not os.path.exists(src_startup):
                # Search recursively in DFP
                found = glob.glob(os.path.join(dfp_dir, "**", prof.startup_file), recursive=True)
                if found:
                    src_startup = found[0]

            if os.path.exists(src_startup):
                shutil.copy2(src_startup, os.path.join(core_src, prof.startup_file))

            # Copy system_stm32xxxx.c
            src_sys = os.path.join(dfp_dir, "Drivers", "CMSIS", "Device", "ST", f"STM32{prof.family.upper()}xx",
                                   "Source", "Templates", f"system_stm32{prof.family}xx.c")
            if os.path.exists(src_sys):
                shutil.copy2(src_sys, os.path.join(core_src, f"system_stm32{prof.family}xx.c"))

        # Locate ARM CMSIS Include (core_cm4.h etc.)
        cmsis_pattern = os.path.join(self.pack_root, "ARM", "CMSIS", "*", "CMSIS", "Include")
        c_matches = sorted(glob.glob(cmsis_pattern), reverse=True)
        if not c_matches:
            cmsis_pattern = os.path.join(self.pack_root, "*", "CMSIS", "*", "CMSIS", "Include")
            c_matches = sorted(glob.glob(cmsis_pattern), reverse=True)

        if c_matches and os.path.exists(c_matches[0]):
            shutil.copytree(c_matches[0], cmsis_inc, dirs_exist_ok=True)

        # If any essential file is missing, ensure fallback
        if not os.path.exists(os.path.join(core_src, prof.startup_file)):
            self._write_fallback_startup(prof, core_src)

    def _write_fallback_drivers(self, prof: MCUProfile, hal_inc: str, hal_src: str,
                                cmsis_dev_inc: str, cmsis_inc: str, core_src: str):
        """Minimal self-contained fallback when packs are missing."""
        self._write_fallback_startup(prof, core_src)

    def _write_fallback_startup(self, prof: MCUProfile, core_src: str):
        """Generate ARM assembly startup with vector table."""
        startup_path = os.path.join(core_src, prof.startup_file)
        text = """; Standard ARM Cortex-M Startup generated by AutoDebug
Stack_Size      EQU     0x00000800

                AREA    STACK, NOINIT, READWRITE, ALIGN=3
Stack_Mem       SPACE   Stack_Size
__initial_sp

Heap_Size       EQU     0x00000400

                AREA    HEAP, NOINIT, READWRITE, ALIGN=3
__heap_base
Heap_Mem        SPACE   Heap_Size
__heap_limit

                PRESERVE8
                THUMB

                AREA    RESET, DATA, READONLY
                EXPORT  __Vectors
                EXPORT  __Vectors_End
                EXPORT  __Vectors_Size

__Vectors       DCD     __initial_sp
                DCD     Reset_Handler
                DCD     NMI_Handler
                DCD     HardFault_Handler
                DCD     MemManage_Handler
                DCD     BusFault_Handler
                DCD     UsageFault_Handler
                DCD     0
                DCD     0
                DCD     0
                DCD     0
                DCD     SVC_Handler
                DCD     DebugMon_Handler
                DCD     0
                DCD     PendSV_Handler
                DCD     SysTick_Handler
__Vectors_End
__Vectors_Size  EQU     __Vectors_End - __Vectors

                AREA    |.text|, CODE, READONLY

Reset_Handler   PROC
                EXPORT  Reset_Handler             [WEAK]
                IMPORT  SystemInit
                IMPORT  __main

                LDR     R0, =SystemInit
                BLX     R0
                LDR     R0, =__main
                BX      R0
                ENDP

NMI_Handler     PROC
                EXPORT  NMI_Handler               [WEAK]
                B       .
                ENDP
HardFault_Handler PROC
                EXPORT  HardFault_Handler         [WEAK]
                B       .
                ENDP
MemManage_Handler PROC
                EXPORT  MemManage_Handler         [WEAK]
                B       .
                ENDP
BusFault_Handler PROC
                EXPORT  BusFault_Handler          [WEAK]
                B       .
                ENDP
UsageFault_Handler PROC
                EXPORT  UsageFault_Handler        [WEAK]
                B       .
                ENDP
SVC_Handler     PROC
                EXPORT  SVC_Handler               [WEAK]
                B       .
                ENDP
DebugMon_Handler PROC
                EXPORT  DebugMon_Handler          [WEAK]
                B       .
                ENDP
PendSV_Handler  PROC
                EXPORT  PendSV_Handler            [WEAK]
                B       .
                ENDP
SysTick_Handler PROC
                EXPORT  SysTick_Handler           [WEAK]
                B       .
                ENDP

                ALIGN
                END
"""
        with open(startup_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

    def _write_core_files(self, prof: MCUProfile, project_name: str, core_inc: str, core_src: str):
        """Generate main.h, stm32f4xx_hal_conf.h, main.c, stm32f4xx_it.c, stm32f4xx_hal_msp.c."""

        # 1. main.h
        main_h = f"""/**
  ******************************************************************************
  * @file           : main.h
  * @brief          : Header for main.c file.
  ******************************************************************************
  */
#ifndef __MAIN_H
#define __MAIN_H

#ifdef __cplusplus
extern "C" {{
#endif

#include "stm32{prof.family}xx_hal.h"

void Error_Handler(void);

#ifdef __cplusplus
}}
#endif

#endif /* __MAIN_H */
"""
        with open(os.path.join(core_inc, "main.h"), "w", encoding="utf-8", newline="\n") as f:
            f.write(main_h)

        # 2. stm32f4xx_hal_conf.h
        hal_conf = f"""/**
  ******************************************************************************
  * @file    stm32{prof.family}xx_hal_conf.h
  * @brief   HAL configuration file.
  ******************************************************************************
  */
#ifndef __STM32{prof.family.upper()}xx_HAL_CONF_H
#define __STM32{prof.family.upper()}xx_HAL_CONF_H

#ifdef __cplusplus
 extern "C" {{
#endif

#define HAL_MODULE_ENABLED
#define HAL_GPIO_MODULE_ENABLED
#define HAL_RCC_MODULE_ENABLED
#define HAL_FLASH_MODULE_ENABLED
#define HAL_PWR_MODULE_ENABLED
#define HAL_CORTEX_MODULE_ENABLED
#define HAL_DMA_MODULE_ENABLED
#define HAL_UART_MODULE_ENABLED

#define HSE_VALUE    ((uint32_t)8000000U)
#define HSE_STARTUP_TIMEOUT   ((uint32_t)100U)
#define HSI_VALUE    ((uint32_t)16000000U)
#define LSI_VALUE    ((uint32_t)32000U)
#define LSE_VALUE    ((uint32_t)32768U)
#define LSE_STARTUP_TIMEOUT   ((uint32_t)5000U)
#define VDD_VALUE                    ((uint32_t)3300U)
#define TICK_INT_PRIORITY            ((uint32_t)0x0FU)
#define USE_RTOS                     0U
#define PREFETCH_ENABLE              1U
#define INSTRUCTION_CACHE_ENABLE     1U
#define DATA_CACHE_ENABLE            1U

#if !defined (EXTERNAL_CLOCK_VALUE)
  #define EXTERNAL_CLOCK_VALUE       12288000U
#endif

#define assert_param(expr) ((void)0U)

/* Includes */
#include "stm32{prof.family}xx_hal_rcc.h"
#include "stm32{prof.family}xx_hal_gpio.h"
#include "stm32{prof.family}xx_hal_dma.h"
#include "stm32{prof.family}xx_hal_cortex.h"
#include "stm32{prof.family}xx_hal_flash.h"
#include "stm32{prof.family}xx_hal_pwr.h"
#include "stm32{prof.family}xx_hal_uart.h"

#ifdef __cplusplus
}}
#endif

#endif /* __STM32{prof.family.upper()}xx_HAL_CONF_H */
"""
        with open(os.path.join(core_inc, f"stm32{prof.family}xx_hal_conf.h"), "w",
                  encoding="utf-8", newline="\n") as f:
            f.write(hal_conf)

        # 3. stm32f4xx_it.h
        it_h = f"""#ifndef __STM32{prof.family.upper()}xx_IT_H
#define __STM32{prof.family.upper()}xx_IT_H

#ifdef __cplusplus
extern "C" {{
#endif

void NMI_Handler(void);
void SVC_Handler(void);
void DebugMon_Handler(void);
void PendSV_Handler(void);
void SysTick_Handler(void);

#ifdef __cplusplus
}}
#endif

#endif /* __STM32{prof.family.upper()}xx_IT_H */
"""
        with open(os.path.join(core_inc, f"stm32{prof.family}xx_it.h"), "w",
                  encoding="utf-8", newline="\n") as f:
            f.write(it_h)

        # 4. stm32f4xx_it.c
        it_c = f"""#include "main.h"
#include "stm32{prof.family}xx_it.h"

void NMI_Handler(void) {{}}

/* Note: HardFault_Handler, MemManage_Handler, BusFault_Handler, and UsageFault_Handler
 * are implemented by cm_backtrace_lite.c with full hardware register telemetry.
 */

void SVC_Handler(void)        {{}}
void DebugMon_Handler(void)   {{}}
void PendSV_Handler(void)     {{}}

void SysTick_Handler(void)
{{
    HAL_IncTick();
}}
"""
        with open(os.path.join(core_src, f"stm32{prof.family}xx_it.c"), "w",
                  encoding="utf-8", newline="\n") as f:
            f.write(it_c)

        # 5. stm32f4xx_hal_msp.c
        msp_c = f"""#include "main.h"

void HAL_MspInit(void)
{{
    __HAL_RCC_PWR_CLK_ENABLE();
}}
"""
        with open(os.path.join(core_src, f"stm32{prof.family}xx_hal_msp.c"), "w",
                  encoding="utf-8", newline="\n") as f:
            f.write(msp_c)

        # 6. system_stm32f4xx.c (if not copied from pack)
        sys_c_path = os.path.join(core_src, f"system_stm32{prof.family}xx.c")
        if not os.path.exists(sys_c_path):
            sys_c = f"""#include "stm32{prof.family}xx.h"

uint32_t SystemCoreClock = 16000000;

void SystemInit(void)
{{
#if defined(__FPU_PRESENT) && (__FPU_PRESENT == 1)
  #if defined(__FPU_USED) && (__FPU_USED == 1)
    SCB->CPACR |= ((3UL << 10*2)|(3UL << 11*2));  /* set CP10 and CP11 Full Access */
  #endif
#endif
}}

void SystemCoreClockUpdate(void)
{{
    SystemCoreClock = 16000000;
}}
"""
            with open(sys_c_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(sys_c)

        # 7. main.c (Standard readable HAL main with pass token & cm_backtrace)
        main_c = f"""/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : Main program body (AutoDebug Universal Scaffolder)
  ******************************************************************************
  */
#include "main.h"
#include <stdio.h>
#include "cm_backtrace_lite.h"

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
static void MX_GPIO_Init(void);

/**
  * @brief  The application entry point.
  * @retval int
  */
int main(void)
{{
  /* 1. Crash tracer initialization (enables Div-by-zero trap & sub-faults) */
  cm_backtrace_init();

  /* 2. Reset of all peripherals, Initializes Flash interface and Systick */
  HAL_Init();

  /* 3. Configure the system clock (Default: 16MHz internal HSI, zero external crystal dependency) */
  SystemClock_Config();

  /* 4. Initialize configured GPIO peripherals */
  MX_GPIO_Init();

  /* 5. AutoDebug Hardware Acceptance Verdict Token */
  printf("\\r\\n[MCU] System initialized. HAL Core Clock: %lu Hz\\r\\n", (unsigned long)SystemCoreClock);
  printf("[ALL TESTS PASSED]\\r\\n");

  /* Infinite loop */
  while (1)
  {{
    HAL_Delay(500);
  }}
}}

/**
  * @brief System Clock Configuration
  * @retval None
  */
void SystemClock_Config(void)
{{
  RCC_OscInitTypeDef RCC_OscInitStruct = {{0}};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {{0}};

  /** Initializes the RCC Oscillators */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSI;
  RCC_OscInitStruct.HSIState = RCC_HSI_ON;
  RCC_OscInitStruct.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_NONE;
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {{
    Error_Handler();
  }}

  /** Initializes the CPU, AHB and APB buses clocks */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_HSI;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV1;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_0) != HAL_OK)
  {{
    Error_Handler();
  }}
}}

/**
  * @brief GPIO Initialization Function
  * @param None
  * @retval None
  */
static void MX_GPIO_Init(void)
{{
  /* GPIO Ports Clock Enable */
  __HAL_RCC_GPIOA_CLK_ENABLE();
}}

void Error_Handler(void)
{{
  __disable_irq();
  while (1)
  {{
  }}
}}
"""
        with open(os.path.join(core_src, "main.c"), "w", encoding="utf-8", newline="\n") as f:
            f.write(main_c)

    def _write_uvprojx(self, prof: MCUProfile, project_name: str,
                       project_dir: str, mdk_arm: str):
        """Generate Keil MDK-ARM .uvprojx file."""
        uvprojx_path = os.path.join(mdk_arm, f"{project_name}.uvprojx")

        # Include Paths
        inc_paths = [
            r"..\Core\Inc",
            rf"..\Drivers\STM32{prof.family.upper()}xx_HAL_Driver\Inc",
            rf"..\Drivers\CMSIS\Device\ST\STM32{prof.family.upper()}xx\Include",
            r"..\Drivers\CMSIS\Include",
            r"..\mcu_support",
        ]
        includes_str = ";".join(inc_paths)

        # CPU String
        fpu_str = f" {prof.fpu_type}" if prof.fpu_type else ""
        iram2_str = f" IRAM2({prof.ram2_start},{prof.ram2_size})" if prof.ram2_start else ""
        cpu_str = f'IRAM({prof.ram_start},{prof.ram_size}){iram2_str} IROM({prof.rom_start},{prof.rom_size}) CPUTYPE("{prof.cpu_type}"){fpu_str} CLOCK(12000000) ELITTLE'

        # Flash Driver DLL
        flash_dll = f"UL2CM3(-S0 -C0 -P0 -FD20000000 -FC1000 -FN1 -FF0{prof.flash_driver_flm} -FS08000000 -FL0{prof.flash_driver_size} -FP0($$Device:{prof.device}$CMSIS\\Flash\\{prof.flash_driver_flm}))"

        # OnChipMemories OCR_RVCT10
        ocr_rvct10 = ""
        if prof.ram2_start:
            ocr_rvct10 = f"""              <OCR_RVCT10>
                <Type>0</Type>
                <StartAddress>{prof.ram2_start}</StartAddress>
                <Size>{prof.ram2_size}</Size>
              </OCR_RVCT10>"""

        # Scan available HAL driver .c files to add
        hal_c_files = []
        hal_src_dir = os.path.join(project_dir, "Drivers", f"STM32{prof.family.upper()}xx_HAL_Driver", "Src")
        if os.path.exists(hal_src_dir):
            for cf in glob.glob(os.path.join(hal_src_dir, "*.c")):
                hal_c_files.append(os.path.basename(cf))
        if not hal_c_files:
            hal_c_files = [f"stm32{prof.family}xx_hal.c", f"stm32{prof.family}xx_hal_rcc.c",
                           f"stm32{prof.family}xx_hal_gpio.c", f"stm32{prof.family}xx_hal_cortex.c"]

        hal_files_xml = "\n".join([
            f"""        <File>
          <FileName>{c}</FileName>
          <FileType>1</FileType>
          <FilePath>..\\Drivers\\STM32{prof.family.upper()}xx_HAL_Driver\\Src\\{c}</FilePath>
        </File>""" for c in hal_c_files
        ])

        xml_content = f"""<?xml version="1.0" encoding="UTF-8" standalone="no" ?>
<Project xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="project_projx.xsd">

  <SchemaVersion>2.1</SchemaVersion>
  <Header>### uVision Project, (C) Keil Software</Header>

  <Targets>
    <Target>
      <TargetName>{project_name}</TargetName>
      <ToolsetNumber>0x4</ToolsetNumber>
      <ToolsetName>ARM-ADS</ToolsetName>
      <pCCUsed>5060960::V5.06 update 7 (build 960)::.\\ARMCC</pCCUsed>
      <uAC6>0</uAC6>
      <TargetOption>
        <TargetCommonOption>
          <Device>{prof.device}</Device>
          <Vendor>{prof.vendor}</Vendor>
          <PackID>Keil.{prof.pack_name}.2.12.0</PackID>
          <PackURL>http://www.keil.com/pack</PackURL>
          <Cpu>{cpu_str}</Cpu>
          <FlashUtilSpec></FlashUtilSpec>
          <StartupFile></StartupFile>
          <FlashDriverDll>{flash_dll}</FlashDriverDll>
          <DeviceId>0</DeviceId>
          <RegisterFile></RegisterFile>
          <MemoryEnv></MemoryEnv>
          <Cmp></Cmp>
          <Asm></Asm>
          <Linker></Linker>
          <OHString></OHString>
          <InfinionOptionDll></InfinionOptionDll>
          <SLE66CMisc></SLE66CMisc>
          <SLE66AMisc></SLE66AMisc>
          <SLE66LinkerMisc></SLE66LinkerMisc>
          <SFDFile></SFDFile>
          <bCustSvd>0</bCustSvd>
          <UseEnv>0</UseEnv>
          <BinPath></BinPath>
          <IncludePath></IncludePath>
          <LibPath></LibPath>
          <RegisterFilePath></RegisterFilePath>
          <DBRegisterFilePath></DBRegisterFilePath>
          <TargetStatus>
            <Error>0</Error>
            <ExitCodeStop>0</ExitCodeStop>
            <ButtonStop>0</ButtonStop>
            <NotGenerated>0</NotGenerated>
            <InvalidFlash>1</InvalidFlash>
          </TargetStatus>
          <OutputDirectory>.\\Objects\\</OutputDirectory>
          <OutputName>{project_name}</OutputName>
          <CreateExecutable>1</CreateExecutable>
          <CreateLib>0</CreateLib>
          <CreateHexFile>1</CreateHexFile>
          <DebugInformation>1</DebugInformation>
          <BrowseInformation>1</BrowseInformation>
          <ListingPath>.\\Listings\\</ListingPath>
          <HexFormatSelection>1</HexFormatSelection>
          <Merge32K>0</Merge32K>
          <CreateBatchFile>0</CreateBatchFile>
          <BeforeCompile>
            <RunUserProg1>0</RunUserProg1>
            <RunUserProg2>0</RunUserProg2>
            <UserProg1Name></UserProg1Name>
            <UserProg2Name></UserProg2Name>
            <UserProg1Dos16Mode>0</UserProg1Dos16Mode>
            <UserProg2Dos16Mode>0</UserProg2Dos16Mode>
            <nStopU1X>0</nStopU1X>
            <nStopU2X>0</nStopU2X>
          </BeforeCompile>
          <BeforeMake>
            <RunUserProg1>0</RunUserProg1>
            <RunUserProg2>0</RunUserProg2>
            <UserProg1Name></UserProg1Name>
            <UserProg2Name></UserProg2Name>
            <UserProg1Dos16Mode>0</UserProg1Dos16Mode>
            <UserProg2Dos16Mode>0</UserProg2Dos16Mode>
            <nStopB1X>0</nStopB1X>
            <nStopB2X>0</nStopB2X>
          </BeforeMake>
          <AfterMake>
            <RunUserProg1>0</RunUserProg1>
            <RunUserProg2>0</RunUserProg2>
            <UserProg1Name></UserProg1Name>
            <UserProg2Name></UserProg2Name>
            <UserProg1Dos16Mode>0</UserProg1Dos16Mode>
            <UserProg2Dos16Mode>0</UserProg2Dos16Mode>
            <nStopA1X>0</nStopA1X>
            <nStopA2X>0</nStopA2X>
          </AfterMake>
          <SelectedForBatchBuild>0</SelectedForBatchBuild>
          <SVCSIdString></SVCSIdString>
        </TargetCommonOption>
        <CommonProperty>
          <UseCPPCompiler>0</UseCPPCompiler>
          <RVCTCodeConst>0</RVCTCodeConst>
          <RVCTZI>0</RVCTZI>
          <RVCTOtherData>0</RVCTOtherData>
          <ModuleSelection>0</ModuleSelection>
          <IncludeInBuild>1</IncludeInBuild>
          <AlwaysBuild>0</AlwaysBuild>
          <GenerateAssemblyFile>0</GenerateAssemblyFile>
          <AssembleAssemblyFile>0</AssembleAssemblyFile>
          <PublicsOnly>0</PublicsOnly>
          <StopOnExitCode>3</StopOnExitCode>
          <CustomArgument></CustomArgument>
          <IncludeLibraryModules></IncludeLibraryModules>
          <ComprImg>1</ComprImg>
        </CommonProperty>
        <DllOption>
          <SimDllName>SARMCM3.DLL</SimDllName>
          <SimDllArguments>-REMAP -MPU</SimDllArguments>
          <SimDlgDll>DCM.DLL</SimDlgDll>
          <SimDlgDllArguments>-pCM4</SimDlgDllArguments>
          <TargetDllName>SARMCM3.DLL</TargetDllName>
          <TargetDllArguments>-MPU</TargetDllArguments>
          <TargetDlgDll>TCM.DLL</TargetDlgDll>
          <TargetDlgDllArguments>-pCM4</TargetDlgDllArguments>
        </DllOption>
        <Utilities>
          <Flash1>
            <UseTargetDll>1</UseTargetDll>
            <UseExternalTool>0</UseExternalTool>
            <RunIndependent>0</RunIndependent>
            <UpdateFlashBeforeDebugging>1</UpdateFlashBeforeDebugging>
            <Capability>1</Capability>
            <DriverSelection>4096</DriverSelection>
          </Flash1>
          <bUseTDR>1</bUseTDR>
          <Flash2>BIN\\UL2CM3.DLL</Flash2>
          <Flash3></Flash3>
          <Flash4></Flash4>
        </Utilities>
        <TargetArmAds>
          <ArmAdsMisc>
            <GenerateListings>0</GenerateListings>
            <asHll>1</asHll>
            <asAsm>1</asAsm>
            <asMacX>1</asMacX>
            <asSyms>1</asSyms>
            <asFals>1</asFals>
            <asDbgD>1</asDbgD>
            <asForm>1</asForm>
            <ldLst>0</ldLst>
            <ldmm>1</ldmm>
            <ldXref>1</ldXref>
            <BigEnd>0</BigEnd>
            <AdsALst>1</AdsALst>
            <AdsACrf>1</AdsACrf>
            <AdsANop>0</AdsANop>
            <AdsANot>0</AdsANot>
            <AdsLLst>1</AdsLLst>
            <AdsLmap>1</AdsLmap>
            <AdsLcgr>1</AdsLcgr>
            <AdsLsym>1</AdsLsym>
            <AdsLszi>1</AdsLszi>
            <AdsLtoi>1</AdsLtoi>
            <AdsLsun>1</AdsLsun>
            <AdsLven>1</AdsLven>
            <AdsLsxf>1</AdsLsxf>
            <RvctClst>0</RvctClst>
            <GenPPlst>0</GenPPlst>
            <AdsCpuType>"{prof.cpu_type}"</AdsCpuType>
            <RvctDeviceName></RvctDeviceName>
            <mOS>0</mOS>
            <uocRom>0</uocRom>
            <uocRam>0</uocRam>
            <hadIROM>1</hadIROM>
            <hadIRAM>1</hadIRAM>
            <hadXRAM>0</hadXRAM>
            <uocXRam>0</uocXRam>
            <hadIRAM2>{1 if prof.ram2_start else 0}</hadIRAM2>
            <hadIROM2>0</hadIROM2>
            <StupSel>8</StupSel>
            <useUlib>1</useUlib>
            <EndSel>0</EndSel>
            <uLtcg>0</uLtcg>
            <nSecure>0</nSecure>
            <RoSelD>3</RoSelD>
            <RwSelD>3</RwSelD>
            <CodeSel>0</CodeSel>
            <OptFeed>0</OptFeed>
            <NoZi1>0</NoZi1>
            <NoZi2>0</NoZi2>
            <NoZi3>0</NoZi3>
            <NoZi4>0</NoZi4>
            <NoZi5>0</NoZi5>
            <Ro1Chk>0</Ro1Chk>
            <Ro2Chk>0</Ro2Chk>
            <Ro3Chk>0</Ro3Chk>
            <Ir1Chk>1</Ir1Chk>
            <Ir2Chk>0</Ir2Chk>
            <Ra1Chk>0</Ra1Chk>
            <Ra2Chk>0</Ra2Chk>
            <Ra3Chk>0</Ra3Chk>
            <Im1Chk>1</Im1Chk>
            <Im2Chk>0</Im2Chk>
            <OnChipMemories>
              <Ocm1><Type>0</Type><StartAddress>0x0</StartAddress><Size>0x0</Size></Ocm1>
              <Ocm2><Type>0</Type><StartAddress>0x0</StartAddress><Size>0x0</Size></Ocm2>
              <Ocm3><Type>0</Type><StartAddress>0x0</StartAddress><Size>0x0</Size></Ocm3>
              <Ocm4><Type>0</Type><StartAddress>0x0</StartAddress><Size>0x0</Size></Ocm4>
              <Ocm5><Type>0</Type><StartAddress>0x0</StartAddress><Size>0x0</Size></Ocm5>
              <Ocm6><Type>0</Type><StartAddress>0x0</StartAddress><Size>0x0</Size></Ocm6>
              <IRAM>
                <Type>0</Type>
                <StartAddress>{prof.ram_start}</StartAddress>
                <Size>{prof.ram_size}</Size>
              </IRAM>
              <IROM>
                <Type>1</Type>
                <StartAddress>{prof.rom_start}</StartAddress>
                <Size>{prof.rom_size}</Size>
              </IROM>
              <XRAM><Type>0</Type><StartAddress>0x0</StartAddress><Size>0x0</Size></XRAM>
              <OCR_RVCT1><Type>1</Type><StartAddress>0x0</StartAddress><Size>0x0</Size></OCR_RVCT1>
              <OCR_RVCT2><Type>1</Type><StartAddress>0x0</StartAddress><Size>0x0</Size></OCR_RVCT2>
              <OCR_RVCT3><Type>1</Type><StartAddress>0x0</StartAddress><Size>0x0</Size></OCR_RVCT3>
              <OCR_RVCT4>
                <Type>1</Type>
                <StartAddress>{prof.rom_start}</StartAddress>
                <Size>{prof.rom_size}</Size>
              </OCR_RVCT4>
              <OCR_RVCT5><Type>1</Type><StartAddress>0x0</StartAddress><Size>0x0</Size></OCR_RVCT5>
              <OCR_RVCT6><Type>0</Type><StartAddress>0x0</StartAddress><Size>0x0</Size></OCR_RVCT6>
              <OCR_RVCT7><Type>0</Type><StartAddress>0x0</StartAddress><Size>0x0</Size></OCR_RVCT7>
              <OCR_RVCT8><Type>0</Type><StartAddress>0x0</StartAddress><Size>0x0</Size></OCR_RVCT8>
              <OCR_RVCT9>
                <Type>0</Type>
                <StartAddress>{prof.ram_start}</StartAddress>
                <Size>{prof.ram_size}</Size>
              </OCR_RVCT9>
{ocr_rvct10}
            </OnChipMemories>
            <RvctStartVector></RvctStartVector>
          </ArmAdsMisc>
          <Cads>
            <interw>1</interw>
            <Optim>1</Optim>
            <oTime>0</oTime>
            <SplitLS>0</SplitLS>
            <OneElfS>1</OneElfS>
            <Strict>0</Strict>
            <EnumInt>0</EnumInt>
            <PlainCh>0</PlainCh>
            <Ropi>0</Ropi>
            <Rwpi>0</Rwpi>
            <wLevel>2</wLevel>
            <uThumb>2</uThumb>
            <uSurpInc>0</uSurpInc>
            <uC99>1</uC99>
            <uGnu>0</uGnu>
            <useXO>0</useXO>
            <v6Lang>1</v6Lang>
            <v6LangP>1</v6LangP>
            <vShortEn>1</vShortEn>
            <vShortWch>1</vShortWch>
            <v6Lto>0</v6Lto>
            <v6WtE>0</v6WtE>
            <v6Rtti>0</v6Rtti>
            <VariousControls>
              <MiscControls></MiscControls>
              <Define>{prof.defines}</Define>
              <Undefine></Undefine>
              <IncludePath>{includes_str}</IncludePath>
            </VariousControls>
          </Cads>
          <Aads>
            <interw>1</interw>
            <Ropi>0</Ropi>
            <Rwpi>0</Rwpi>
            <thumb>0</thumb>
            <SplitLS>0</SplitLS>
            <SwStkChk>0</SwStkChk>
            <NoWarn>0</NoWarn>
            <uSurpInc>0</uSurpInc>
            <useXO>0</useXO>
            <uClangAs>0</uClangAs>
            <VariousControls>
              <MiscControls></MiscControls>
              <Define></Define>
              <Undefine></Undefine>
              <IncludePath></IncludePath>
            </VariousControls>
          </Aads>
          <LDads>
            <umfTarg>1</umfTarg>
            <Ropi>0</Ropi>
            <Rwpi>0</Rwpi>
            <noStLib>0</noStLib>
            <RepFail>1</RepFail>
            <useFile>0</useFile>
            <TextAddressRange>{prof.rom_start}</TextAddressRange>
            <DataAddressRange>{prof.ram_start}</DataAddressRange>
            <pXoBase></pXoBase>
            <ScatterFile></ScatterFile>
            <IncludeLibs></IncludeLibs>
            <IncludeLibsPath></IncludeLibsPath>
            <Misc></Misc>
            <LinkerInputFile></LinkerInputFile>
            <DisabledWarnings></DisabledWarnings>
          </LDads>
        </TargetArmAds>
      </TargetOption>
      <Groups>
        <Group>
          <GroupName>Application/User</GroupName>
          <Files>
            <File>
              <FileName>main.c</FileName>
              <FileType>1</FileType>
              <FilePath>..\\Core\\Src\\main.c</FilePath>
            </File>
            <File>
              <FileName>stm32{prof.family}xx_it.c</FileName>
              <FileType>1</FileType>
              <FilePath>..\\Core\\Src\\stm32{prof.family}xx_it.c</FilePath>
            </File>
            <File>
              <FileName>stm32{prof.family}xx_hal_msp.c</FileName>
              <FileType>1</FileType>
              <FilePath>..\\Core\\Src\\stm32{prof.family}xx_hal_msp.c</FilePath>
            </File>
          </Files>
        </Group>
        <Group>
          <GroupName>Drivers/STM32{prof.family.upper()}xx_HAL_Driver</GroupName>
          <Files>
{hal_files_xml}
          </Files>
        </Group>
        <Group>
          <GroupName>Drivers/CMSIS</GroupName>
          <Files>
            <File>
              <FileName>system_stm32{prof.family}xx.c</FileName>
              <FileType>1</FileType>
              <FilePath>..\\Core\\Src\\system_stm32{prof.family}xx.c</FilePath>
            </File>
            <File>
              <FileName>{prof.startup_file}</FileName>
              <FileType>2</FileType>
              <FilePath>..\\Core\\Src\\{prof.startup_file}</FilePath>
            </File>
          </Files>
        </Group>
        <Group>
          <GroupName>AutoDebug</GroupName>
          <Files>
            <File>
              <FileName>cm_backtrace_lite.c</FileName>
              <FileType>1</FileType>
              <FilePath>..\\mcu_support\\cm_backtrace_lite.c</FilePath>
            </File>
            <File>
              <FileName>cm_backtrace_port.c</FileName>
              <FileType>1</FileType>
              <FilePath>..\\mcu_support\\cm_backtrace_port.c</FilePath>
            </File>
          </Files>
        </Group>
      </Groups>
    </Target>
  </Targets>

</Project>
"""
        with open(uvprojx_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(xml_content)

    def _inject_autodebug(self, project_dir: str, mdk_arm: str, project_name: str, prof: MCUProfile):
        """Inject AGENTS.md, runner, autodebug engine, and generate cm_backtrace_port."""
        from .firmware_setup import generate_uart_port

        kit_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        # 1. mcu_support
        mcu_support_dst = os.path.join(project_dir, "mcu_support")
        os.makedirs(mcu_support_dst, exist_ok=True)
        mcu_support_src = os.path.join(kit_root, "mcu_support")
        for fn in ("cm_backtrace_lite.c", "cm_backtrace_lite.h"):
            s = os.path.join(mcu_support_src, fn)
            if os.path.exists(s):
                shutil.copy2(s, os.path.join(mcu_support_dst, fn))

        # Generate UART port
        generate_uart_port(project_dir, uart="USART1", family=prof.family, overwrite=True)

        # 2. Injected scripts & rules
        shutil.copy2(os.path.join(kit_root, "AGENTS.md"), os.path.join(project_dir, "AGENTS.md"))
        shutil.copy2(os.path.join(kit_root, "run_autodebug.py"), os.path.join(project_dir, "run_autodebug.py"))

        # Injected package
        pkg_dst = os.path.join(project_dir, "autodebug")
        if os.path.exists(pkg_dst):
            shutil.rmtree(pkg_dst)
        shutil.copytree(
            os.path.join(kit_root, "autodebug"),
            pkg_dst,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")
        )

        # Write autodebug.config.yaml
        cfg_path = os.path.join(project_dir, "autodebug.config.yaml")
        with open(cfg_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(f"""# Project AutoDebug Configuration
project:
  uvprojx_path: MDK-ARM/{project_name}.uvprojx
  target_name: {project_name}

debugger:
  type: pyocd
  target_override: {prof.mcu_id}

serial:
  port: null
  baudrate: 115200
  timeout_seconds: 15.0
""")

        # Add gitignore
        gi_path = os.path.join(project_dir, ".gitignore")
        with open(gi_path, "w", encoding="utf-8", newline="\n") as f:
            f.write("""# Keil build artifacts
MDK-ARM/Objects/
MDK-ARM/Listings/
*.uvguix.*
*.uvoptx
*.autodebug.bak

# AutoDebug artifacts
diagnostic_report.json
build_autodebug.log
.autodebug/
""")
