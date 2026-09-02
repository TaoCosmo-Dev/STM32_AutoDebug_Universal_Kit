/**
  ******************************************************************************
  * @file    cm_backtrace_lite.h
  * @brief   Lightweight ARM Cortex-M HardFault tracer for the AutoDebug closed loop.
  *
  * What it does
  * ------------
  *   On a hardware exception it prints the stacked exception frame and the SCB fault
  *   status registers between two machine-readable markers. autodebug/serial_monitor.py
  *   parses that block, so the loop can locate the faulting source line WITHOUT a debug
  *   probe attached.
  *
  * How to wire it in (3 steps)
  * ---------------------------
  *   1. Add cm_backtrace_lite.c to your Keil project.
  *   2. Give it a byte sink. Either implement this anywhere in your project:
  *
  *          void cm_backtrace_putchar(char c)
  *          {
  *              while (!(USART1->SR & USART_SR_TXE)) { }     // F1/F4: SR, G0/G4/H7: ISR
  *              USART1->DR = (uint8_t)c;
  *          }
  *
  *      or register one at runtime with cm_backtrace_set_putchar(fn).
  *
  *      IMPORTANT: it must be a *blocking, register-level* write. Do NOT route it through
  *      printf/HAL_UART_Transmit: those depend on SysTick for their timeout, SysTick
  *      cannot preempt a HardFault (priority -1), so the tick never advances and the
  *      handler hangs before emitting a single byte.
  *
  *   3. Call cm_backtrace_init() early in main(), before any peripheral setup.
  *
  *   The file also supplies HardFault_Handler itself. If your project already has one
  *   (usually in stm32xxxx_it.c) the linker will report a duplicate symbol - delete the
  *   HAL stub, or set CM_BACKTRACE_PROVIDE_HANDLER to 0 and call
  *   cm_backtrace_fault_handler() from your own handler.
  ******************************************************************************
  */
#ifndef __CM_BACKTRACE_LITE_H
#define __CM_BACKTRACE_LITE_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ---------------------------------------------------------------- configuration */

/* Provide HardFault_Handler (and the assembly shim that captures the frame). */
#ifndef CM_BACKTRACE_PROVIDE_HANDLER
#define CM_BACKTRACE_PROVIDE_HANDLER   1
#endif

/* Also trap MemManage / BusFault / UsageFault separately for a precise classification. */
#ifndef CM_BACKTRACE_PROVIDE_SUBFAULTS
#define CM_BACKTRACE_PROVIDE_SUBFAULTS 1
#endif

/* Enable the divide-by-zero trap. Without it, x/0 silently returns 0 instead of faulting. */
#ifndef CM_BACKTRACE_TRAP_DIV0
#define CM_BACKTRACE_TRAP_DIV0         1
#endif

/* Enable the unaligned-access trap. Off by default: some vendor libraries rely on
   unaligned accesses being legal. */
#ifndef CM_BACKTRACE_TRAP_UNALIGNED
#define CM_BACKTRACE_TRAP_UNALIGNED    0
#endif

/* Reset the MCU after dumping instead of parking in a loop. Leave at 0 so the debug
   probe can still read the fault state after the dump. */
#ifndef CM_BACKTRACE_RESET_AFTER_DUMP
#define CM_BACKTRACE_RESET_AFTER_DUMP  0
#endif

/* Markers the host-side parser looks for. Keep in sync with autodebug/config.yaml. */
#define CM_BT_MARK_BEGIN  "[AUTODEBUG_CRASH_START]"
#define CM_BT_MARK_END    "[AUTODEBUG_CRASH_END]"

/* ---------------------------------------------------------------- API */

/** Enable the fault traps. Call once, early in main(). */
void cm_backtrace_init(void);

/** Register the blocking byte sink used by the fault dump. */
void cm_backtrace_set_putchar(void (*fn)(char c));

/** Default byte sink. Weak: implement it in your own code to skip the registration call. */
void cm_backtrace_putchar(char c);

/** Emit the crash report. stack_frame points at the 8-word frame the core pushed;
    lr_exc is the EXC_RETURN value in LR on entry to the handler. */
void cm_backtrace_fault_handler(uint32_t *stack_frame, uint32_t lr_exc);

/** Assertion hook. Prints a line the host parser understands, then parks. */
void cm_assert_failed(const char *file, uint32_t line, const char *expr);

/** Print a NUL-terminated string through the registered sink (safe from a fault handler). */
void cm_backtrace_puts(const char *s);

#define AUTO_ASSERT(expr)                                                      \
    do {                                                                       \
        if (!(expr)) {                                                         \
            cm_assert_failed(__FILE__, (uint32_t)__LINE__, #expr);             \
        }                                                                      \
    } while (0)

#ifdef __cplusplus
}
#endif

#endif /* __CM_BACKTRACE_LITE_H */
