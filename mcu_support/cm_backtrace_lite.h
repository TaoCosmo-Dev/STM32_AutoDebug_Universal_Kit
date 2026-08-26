/**
  ******************************************************************************
  * @file    cm_backtrace_lite.h
  * @brief   Lightweight ARM Cortex-M HardFault & Exception Tracer for Auto-Debug
  ******************************************************************************
  */
#ifndef __CM_BACKTRACE_LITE_H
#define __CM_BACKTRACE_LITE_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Initialize fault handling hooks */
void cm_backtrace_init(void);

/* Called directly from assembly HardFault_Handler */
void cm_backtrace_fault_handler(uint32_t *stack_frame, uint32_t lr_exc);

/* Assertion hook macro for user code */
#define AUTO_ASSERT(expr) \
    do { \
        if (!(expr)) { \
            cm_assert_failed((const uint8_t *)__FILE__, __LINE__, #expr); \
        } \
    } while (0)

void cm_assert_failed(const uint8_t *file, uint32_t line, const char *expr);

#ifdef __cplusplus
}
#endif

#endif /* __CM_BACKTRACE_LITE_H */
