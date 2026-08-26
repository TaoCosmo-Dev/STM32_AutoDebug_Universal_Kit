/**
  ******************************************************************************
  * @file    cm_backtrace_lite.c
  * @brief   Lightweight ARM Cortex-M HardFault & Exception Tracer
  ******************************************************************************
  */
#include "cm_backtrace_lite.h"
#include <stdio.h>

#define SCB_CFSR    (*(volatile uint32_t *)0xE000ED28UL)
#define SCB_HFSR    (*(volatile uint32_t *)0xE000ED2CUL)
#define SCB_DFSR    (*(volatile uint32_t *)0xE000ED30UL)
#define SCB_MMFAR   (*(volatile uint32_t *)0xE000ED34UL)
#define SCB_BFAR    (*(volatile uint32_t *)0xE000ED38UL)
#define SCB_SHCSR   (*(volatile uint32_t *)0xE000ED24UL)

void cm_backtrace_init(void)
{
    /* Enable UsageFault, BusFault, and MemManage faults (bits 18, 17, 16) */
    SCB_SHCSR |= (1UL << 18) | (1UL << 17) | (1UL << 16);
}

void cm_backtrace_fault_handler(uint32_t *stack_frame, uint32_t lr_exc)
{
    uint32_t r0   = stack_frame[0];
    uint32_t r1   = stack_frame[1];
    uint32_t r2   = stack_frame[2];
    uint32_t r3   = stack_frame[3];
    uint32_t r12  = stack_frame[4];
    uint32_t lr   = stack_frame[5];
    uint32_t pc   = stack_frame[6];
    uint32_t xpsr = stack_frame[7];

    uint32_t cfsr  = SCB_CFSR;
    uint32_t hfsr  = SCB_HFSR;
    uint32_t bfar  = SCB_BFAR;
    uint32_t mmfar = SCB_MMFAR;

    printf("\r\n================ [HARDWARE EXCEPTION TRAPPED] ================\r\n");
    printf("[AUTODEBUG_CRASH_START]\r\n");
    printf("LR_EXC = 0x%08X (%s)\r\n", lr_exc, (lr_exc & 0x4) ? "PSP" : "MSP");
    printf("R0  = 0x%08X, R1  = 0x%08X, R2  = 0x%08X, R3  = 0x%08X\r\n", r0, r1, r2, r3);
    printf("R12 = 0x%08X, LR  = 0x%08X, PC  = 0x%08X, xPSR= 0x%08X\r\n", r12, lr, pc, xpsr);
    printf("CFSR= 0x%08X, HFSR= 0x%08X, BFAR= 0x%08X, MMFAR= 0x%08X\r\n", cfsr, hfsr, bfar, mmfar);
    printf("[Backtrace] >> 0x%08X 0x%08X\r\n", pc, lr);
    printf("[AUTODEBUG_CRASH_END]\r\n");
    printf("===============================================================\r\n");

    /* Infinite loop or break for debugger */
    while (1) {
        __asm volatile ("BKPT #0");
    }
}

void cm_assert_failed(const uint8_t *file, uint32_t line, const char *expr)
{
    printf("\r\n[ASSERTION_FAILED] %s at file %s, line %lu\r\n", expr, file, (unsigned long)line);
    while (1) {
        __asm volatile ("BKPT #0");
    }
}
