/**
  ******************************************************************************
  * @file    cm_backtrace_lite.c
  * @brief   Lightweight ARM Cortex-M HardFault tracer (no stdio, no HAL, no malloc).
  *
  * Everything in the fault path is deliberately primitive: a blocking byte sink and
  * hand-rolled hex formatting. printf inside a HardFault handler is a classic hang -
  * a retargeted printf usually ends up in HAL_UART_Transmit, whose timeout is driven by
  * SysTick, and SysTick cannot preempt a fault at priority -1, so HAL_GetTick() never
  * advances and the timeout loop spins forever without emitting one byte.
  ******************************************************************************
  */
#include "cm_backtrace_lite.h"

/* --- Core peripheral addresses (used directly so this file needs no CMSIS header) --- */
#define CM_SCB_CCR      (*(volatile uint32_t *)0xE000ED14UL)
#define CM_SCB_SHCSR    (*(volatile uint32_t *)0xE000ED24UL)
#define CM_SCB_CFSR     (*(volatile uint32_t *)0xE000ED28UL)
#define CM_SCB_HFSR     (*(volatile uint32_t *)0xE000ED2CUL)
#define CM_SCB_DFSR     (*(volatile uint32_t *)0xE000ED30UL)
#define CM_SCB_MMFAR    (*(volatile uint32_t *)0xE000ED34UL)
#define CM_SCB_BFAR     (*(volatile uint32_t *)0xE000ED38UL)
#define CM_SCB_AIRCR    (*(volatile uint32_t *)0xE000ED0CUL)
#define CM_DHCSR        (*(volatile uint32_t *)0xE000EDF0UL)   /* Debug Halting Ctrl/Status */

#define CM_CCR_UNALIGN_TRP  (1UL << 3)
#define CM_CCR_DIV_0_TRP    (1UL << 4)
#define CM_SHCSR_USGFAULTENA (1UL << 18)
#define CM_SHCSR_BUSFAULTENA (1UL << 17)
#define CM_SHCSR_MEMFAULTENA (1UL << 16)
#define CM_DHCSR_C_DEBUGEN   (1UL << 0)

static void (*s_putchar)(char c) = 0;

/* --------------------------------------------------------------------- output ----- */

#if defined(__CC_ARM) || defined(__ARMCC_VERSION) || defined(__GNUC__)
__attribute__((weak))
#endif
void cm_backtrace_putchar(char c)
{
    /* Weak default: no sink configured. Override this function, or call
       cm_backtrace_set_putchar(), otherwise the dump is silent. */
    (void)c;
}

void cm_backtrace_set_putchar(void (*fn)(char c))
{
    s_putchar = fn;
}

static void cm_emit(char c)
{
    if (s_putchar != 0) {
        s_putchar(c);
    } else {
        cm_backtrace_putchar(c);
    }
}

void cm_backtrace_puts(const char *s)
{
    if (s == 0) {
        return;
    }
    while (*s != '\0') {
        cm_emit(*s++);
    }
}

static void cm_put_hex32(uint32_t value)
{
    static const char digits[] = "0123456789ABCDEF";
    int8_t shift;
    cm_emit('0');
    cm_emit('x');
    for (shift = 28; shift >= 0; shift -= 4) {
        cm_emit(digits[(value >> (uint8_t)shift) & 0xFU]);
    }
}

static void cm_put_u32(uint32_t value)
{
    char buf[11];
    uint8_t i = 0U;
    if (value == 0U) {
        cm_emit('0');
        return;
    }
    while (value > 0U && i < sizeof(buf)) {
        buf[i++] = (char)('0' + (value % 10U));
        value /= 10U;
    }
    while (i > 0U) {
        cm_emit(buf[--i]);
    }
}

static void cm_put_kv(const char *name, uint32_t value)
{
    cm_backtrace_puts(name);
    cm_backtrace_puts(" = ");
    cm_put_hex32(value);
}

static void cm_newline(void)
{
    cm_emit('\r');
    cm_emit('\n');
}

/* --------------------------------------------------------------------- init ------- */

void cm_backtrace_init(void)
{
#if (CM_BACKTRACE_PROVIDE_SUBFAULTS == 1)
    /* Enable UsageFault, BusFault and MemManage so faults are classified instead of
       escalating straight to a bare HardFault with no information. */
    CM_SCB_SHCSR |= (CM_SHCSR_USGFAULTENA | CM_SHCSR_BUSFAULTENA | CM_SHCSR_MEMFAULTENA);
#endif
#if (CM_BACKTRACE_TRAP_DIV0 == 1)
    CM_SCB_CCR |= CM_CCR_DIV_0_TRP;
#endif
#if (CM_BACKTRACE_TRAP_UNALIGNED == 1)
    CM_SCB_CCR |= CM_CCR_UNALIGN_TRP;
#endif
}

/* --------------------------------------------------------------------- park ------- */

static void cm_park(void)
{
#if (CM_BACKTRACE_RESET_AFTER_DUMP == 1)
    CM_SCB_AIRCR = (0x5FAUL << 16) | (1UL << 2);   /* SYSRESETREQ */
#endif
    for (;;) {
        /* A BKPT with no debugger attached escalates to a HardFault and can drive the
           core into LOCKUP, so only break when a debugger is actually connected. */
        if ((CM_DHCSR & CM_DHCSR_C_DEBUGEN) != 0U) {
#if defined(__CC_ARM) || defined(__ARMCC_VERSION) || defined(__GNUC__)
            __asm volatile ("BKPT #0");
#endif
        }
    }
}

/* --------------------------------------------------------------------- dump ------- */

void cm_backtrace_fault_handler(uint32_t *stack_frame, uint32_t lr_exc)
{
    uint32_t cfsr  = CM_SCB_CFSR;
    uint32_t hfsr  = CM_SCB_HFSR;
    uint32_t bfar  = CM_SCB_BFAR;
    uint32_t mmfar = CM_SCB_MMFAR;
    uint32_t r0 = 0U, r1 = 0U, r2 = 0U, r3 = 0U, r12 = 0U, lr = 0U, pc = 0U, xpsr = 0U;

    if (stack_frame != 0) {
        r0   = stack_frame[0];
        r1   = stack_frame[1];
        r2   = stack_frame[2];
        r3   = stack_frame[3];
        r12  = stack_frame[4];
        lr   = stack_frame[5];
        pc   = stack_frame[6];
        xpsr = stack_frame[7];
    }

    cm_newline();
    cm_backtrace_puts(CM_BT_MARK_BEGIN);
    cm_newline();

    cm_put_kv("LR_EXC", lr_exc);
    cm_backtrace_puts(((lr_exc & 0x4U) != 0U) ? " (PSP)" : " (MSP)");
    cm_newline();

    cm_put_kv("R0", r0);   cm_backtrace_puts(", ");
    cm_put_kv("R1", r1);   cm_backtrace_puts(", ");
    cm_put_kv("R2", r2);   cm_backtrace_puts(", ");
    cm_put_kv("R3", r3);
    cm_newline();

    cm_put_kv("R12", r12); cm_backtrace_puts(", ");
    cm_put_kv("LR", lr);   cm_backtrace_puts(", ");
    cm_put_kv("PC", pc);   cm_backtrace_puts(", ");
    cm_put_kv("XPSR", xpsr);
    cm_newline();

    cm_put_kv("CFSR", cfsr);   cm_backtrace_puts(", ");
    cm_put_kv("HFSR", hfsr);   cm_backtrace_puts(", ");
    cm_put_kv("BFAR", bfar);   cm_backtrace_puts(", ");
    cm_put_kv("MMFAR", mmfar); cm_backtrace_puts(", ");
    cm_put_kv("DFSR", CM_SCB_DFSR);
    cm_newline();

    cm_backtrace_puts("[Backtrace] >> ");
    cm_put_hex32(pc);
    cm_emit(' ');
    cm_put_hex32(lr);
    cm_newline();

    cm_backtrace_puts(CM_BT_MARK_END);
    cm_newline();

    cm_park();
}

void cm_assert_failed(const char *file, uint32_t line, const char *expr)
{
    cm_newline();
    cm_backtrace_puts("[ASSERTION_FAILED] ");
    cm_backtrace_puts(expr != 0 ? expr : "(null)");
    cm_backtrace_puts(" at file ");
    cm_backtrace_puts(file != 0 ? file : "(unknown)");
    cm_backtrace_puts(", line ");
    cm_put_u32(line);
    cm_newline();
    cm_park();
}

/* ------------------------------------------------------- exception entry shims ----- */
/*
 * The shim exists to hand the C dumper the RIGHT stack pointer. The core pushes the
 * exception frame onto MSP or PSP depending on which stack was active, and EXC_RETURN
 * bit 2 in LR says which. Reading "sp" from inside a C handler would give the handler's
 * own stack, not the frame.
 */
#if (CM_BACKTRACE_PROVIDE_HANDLER == 1)

#if defined(__CC_ARM) && (!defined(__ARMCC_VERSION) || (__ARMCC_VERSION < 6000000))   /* Arm Compiler 5 */

__asm void HardFault_Handler(void)
{
    IMPORT cm_backtrace_fault_handler
    TST     LR, #4
    ITE     EQ
    MRSEQ   R0, MSP
    MRSNE   R0, PSP
    MOV     R1, LR
    LDR     R2, =cm_backtrace_fault_handler
    BX      R2
    ALIGN
}

#if (CM_BACKTRACE_PROVIDE_SUBFAULTS == 1)
__asm void MemManage_Handler(void)
{
    IMPORT cm_backtrace_fault_handler
    TST     LR, #4
    ITE     EQ
    MRSEQ   R0, MSP
    MRSNE   R0, PSP
    MOV     R1, LR
    LDR     R2, =cm_backtrace_fault_handler
    BX      R2
    ALIGN
}

__asm void BusFault_Handler(void)
{
    IMPORT cm_backtrace_fault_handler
    TST     LR, #4
    ITE     EQ
    MRSEQ   R0, MSP
    MRSNE   R0, PSP
    MOV     R1, LR
    LDR     R2, =cm_backtrace_fault_handler
    BX      R2
    ALIGN
}

__asm void UsageFault_Handler(void)
{
    IMPORT cm_backtrace_fault_handler
    TST     LR, #4
    ITE     EQ
    MRSEQ   R0, MSP
    MRSNE   R0, PSP
    MOV     R1, LR
    LDR     R2, =cm_backtrace_fault_handler
    BX      R2
    ALIGN
}
#endif /* subfaults */

#elif defined(__GNUC__) || (defined(__ARMCC_VERSION) && (__ARMCC_VERSION >= 6000000))  /* AC6 / GCC */

#define CM_FAULT_SHIM(name)                                    \
    __attribute__((naked)) void name(void)                     \
    {                                                          \
        __asm volatile (                                       \
            "tst   lr, #4                          \n"         \
            "ite   eq                              \n"         \
            "mrseq r0, msp                         \n"         \
            "mrsne r0, psp                         \n"         \
            "mov   r1, lr                          \n"         \
            "ldr   r2, =cm_backtrace_fault_handler \n"         \
            "bx    r2                              \n"         \
        );                                                     \
    }

CM_FAULT_SHIM(HardFault_Handler)
#if (CM_BACKTRACE_PROVIDE_SUBFAULTS == 1)
CM_FAULT_SHIM(MemManage_Handler)
CM_FAULT_SHIM(BusFault_Handler)
CM_FAULT_SHIM(UsageFault_Handler)
#endif

#endif /* compiler */

#endif /* CM_BACKTRACE_PROVIDE_HANDLER */
