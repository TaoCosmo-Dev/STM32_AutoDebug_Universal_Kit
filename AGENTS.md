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

## 2. 需求深度对齐与谋定而后动 (Mandatory Grill-Me Alignment First)
- **严禁盲目动手与预设参数**：收到新项目、新模块或新屏幕时，严禁自行假设晶振频率或引脚。必须通过结构化交互访谈（Grill-Me）逐一追问清楚 **5 大硬件分支决策**：
  1. **时钟树与外部晶振 (HSE)**：8MHz / 12MHz / 25MHz 确切数值（配错直接导致超频死机与延时错乱）；
  2. **开发板型号与引脚冲突**：正点原子/野火/核心板，排查 SPI1/SPI2 引脚是否已被板载 SPI Flash、网络芯片或 LED 占用；
  3. **屏幕光学与显存偏移行列**：ST7735S 80x160 物理窗口偏移（X=26, Y=1）、IPS 颜色反转控制（INVON）；
  4. **通信时序与驱动模式**：硬件 SPI+DMA 双缓冲异步刷屏 vs 轮询；
  5. **系统框架**：裸机 vs FreeRTOS vs LVGL 图形栈。
- **方案先行**：先给出简明的《技术方案与引脚/架构草案》，向用户确认无误、有 100% 把握后再开始具体编码与设计。

---

## 3. 嵌入式固件开发黄金准则 (MISRA-C & BARR-C)

1. **时钟前置**：配置任何外设（GPIO、SPI、UART、TIM）前，第一行代码必须开启对应的 `__HAL_RCC_xxx_CLK_ENABLE()`。
2. **`volatile` 强约束**：中断服务函数（ISR）与主循环/任务共享的全局变量必须声明为 `volatile`。
3. **ISR 极简**：中断内部严禁调用任何阻塞延时（`HAL_Delay`）与大耗时操作，只置标志或存入环形缓冲区。
4. **通信防死锁**：所有硬件等待 `while` 循环必须配备超时退出计数器（Timeout），严禁裸 `while` 死等。
5. **结构体对齐**：通信协议结构体必须显式指定 1 字节对齐（`#pragma pack(1)` 或 `__attribute__((packed))`）。
6. **硬件安全限流**：驱动大功率外设（如 WS2812B 矩阵、电机、MOS 管）时，必须在软件层做全局电流与占空比限幅，防止电源跌落或器件损坏。

---

## 4. 第一性原理与务实工程铁律 (First-Principles & Pragmatic Engineering Mandate)

1. **第一性原理深层归因 (Root-Cause from Silicon)**：
   - 遇到任何异常（如画面镜像、屏幕闪烁、死机卡顿），严禁碰运气式盲改参数；
   - 必须从**芯片寄存器位定义（MADCTL / RCC / SCB）、时钟树倍频公式、物理显存映射与硬件电气特性**出发推导根因并精准解决。
2. **严厉拒绝过度工程 (Zero Over-Engineering & YAGNI)**：
   - 牢记“如无必要，勿增实体”（You Aren't Gonna Need It）；
   - 在裸机状态机足以 33 FPS 丝滑运行且 RAM 充足时，严禁无意义强上复杂 RTOS；
   - 严禁为了“看起来高大上”而添加人类自嗨式的无用网页报表或脱离当前环境的复杂跨平台框架，把算力与精力 100% 聚焦在核心交付目标上。
3. **清晰坚固的交付边界 (Ruthless Definition of Done)**：
   - 软件工程不存在“理论上的绝对完美”；
   - 凡达成 **“Keil 0 Error 全量构建 + JTAG 探针在线烧录 + CPU 存活遥测通过 + 实机功能 100% 验收”**，即达到黄金发布标准，立即封版交付。
4. **全自动无阻塞流水线 (Zero-Interaction Autonomy)**：
   - 多调试探针自动静默仲裁，串口 COM 口自动嗅探，严禁任何阻塞自动化脚本的终端交互弹窗。
