# AGENTS.md / .cursorrules: STM32 固件全自动调试与自愈开发规范

> 本规范适用于任何 AI Agent（Cursor / Claude Code / Windsurf / Aider / ChatGPT / DeepSeek）。当你接入本工程时，必须严格遵守以下自动化闭环与嵌入式黄金法则。

---

## 1. 核心闭环流程 (Autonomous Closed Loop)

当你修改或新增任何 STM32 C 源码后，**严禁直接结束对话**，必须主动在终端调用自动化工具链进行验证：

```bash
# 1. 驱动 Keil MDK 全量构建与自愈
python run_autodebug.py --project "MDK-ARM/STM32F446_WS2812B.uvprojx"

# 2. 检查返回状态：
#    - 若构建失败：自动读取 diagnostic_report.json，分析报错行号并修改源码，重新构建直至 0 Error(s)。
#    - 若硬件崩溃 (HardFault)：读取 diagnostic_report.json 中的 PC/LR/CFSR/BFAR 寄存器与代码切片，修复内存越界/野指针/除零错误，重编译并重烧。
#    - 若串口返回 [PASS]：确认功能正常，交付给用户。
```

---

## 2. 嵌入式固件开发黄金准则 (MISRA-C & BARR-C)

1. **时钟前置**：配置任何外设（GPIO、SPI、UART、TIM）前，第一行代码必须开启对应的 `__HAL_RCC_xxx_CLK_ENABLE()`。
2. **`volatile` 强约束**：中断服务函数（ISR）与主循环/任务共享的全局变量必须声明为 `volatile`。
3. **ISR 极简**：中断内部严禁调用任何阻塞延时（`HAL_Delay`）与大耗时操作，只置标志或存入环形缓冲区。
4. **通信防死锁**：所有硬件等待 `while` 循环必须配备超时退出计数器（Timeout），严禁裸 `while` 死等。
5. **结构体对齐**：通信协议结构体必须显式指定 1 字节对齐（`#pragma pack(1)` 或 `__attribute__((packed))`）。
6. **硬件安全限流**：驱动大功率外设（如 WS2812B 矩阵、电机、MOS 管）时，必须在软件层做全局电流与占空比限幅，防止电源跌落或器件损坏。
