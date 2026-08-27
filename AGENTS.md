# AGENTS.md / .cursorrules: STM32 固件全自动调试与自愈开发规范

> 本规范适用于任何 AI Agent（Cursor / Claude Code / Windsurf / Aider / ChatGPT / DeepSeek）。当你接入本工程时，必须严格遵守以下自动化闭环与嵌入式黄金法则。

---

## 1. 核心闭环流程 (Autonomous Closed Loop)

当你修改或新增任何 STM32 C 源码后，**严禁直接结束对话**，必须主动在终端调用自动化工具链进行验证：

```bash
# 1. 驱动 Keil MDK 全量构建与自愈
python run_autodebug.py --project "path/to/YourProject.uvprojx"

# 2. 检查返回状态：
#    - 若构建失败：自动读取 diagnostic_report.json，分析报错行号并修改源码，重新构建直至 0 Error(s)。
#    - 若硬件崩溃 (HardFault)：读取 diagnostic_report.json 中的 PC/LR/CFSR/BFAR 寄存器与代码切片，修复内存越界/野指针/除零错误，重编译并重烧。
#    - 若串口返回 [PASS]：确认功能正常，交付给用户。
```

---

## 2. 需求深度对齐与谋定而后动 (Mandatory Grill-Me Alignment First)
- **严禁盲目动手与预设参数**：收到新项目、新模块或新外设时，严禁自行假设晶振频率或引脚。必须通过结构化交互访谈（Grill-Me）逐一追问清楚 **5 大硬件分支决策**：
  1. **时钟树与外部晶振 (HSE)**：8MHz / 12MHz / 25MHz 确切数值（配错直接导致超频死机与延时错乱）；
  2. **开发板型号与引脚冲突**：排查 SPI / I2C / UART / PWM / ADC 引脚是否与板载资源发生功能复用冲突；
  3. **外设核心物理指标 (Peripherals & Actuators)**：
     - 显示面板：ST7735S / ST7789 显存偏置、RGB565 格式与颜色反转；
     - 电机与逆变器：极对数、编码器线数、死区时间与驱动芯片类型；
     - 传感器与采样：IMU 陀螺仪 / 温湿度 I2C 从机地址、量程与采样率；
     - 通信总线模组：CAN / RS485 波特率、滤波器与流控引脚。
  4. **通信时序与驱动模式**：硬件 DMA 双缓冲 / 中断环形缓冲区 vs 轮询；
  5. **系统框架**：裸机前后台状态机 vs RTOS 多任务并发调度 vs 图形/协议栈。
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
2. **严厉拒绝过度工程与虚假需求 (Zero Over-Engineering & YAGNI)**：
   - 牢记“如无必要，勿增实体”（You Aren't Gonna Need It）；
   - 当轻量架构与基础状态机足以满足系统的实时性、稳定性与响应指标时，严禁为了“形式高大上”无意义引入过度复杂的中间件与框架；
   - 仅在系统出现真实并发瓶颈、复杂协议栈（如 TCP/IP、USB、CANopen）或硬实时抢占调度需求时，才正规引入 RTOS；
   - 把芯片算力、内存资源与工程精力 100% 聚焦在解决实际工程问题与核心交付目标上。
3. **清晰坚固的交付边界 (Ruthless Definition of Done)**：
   - 软件工程不存在“理论上的绝对完美”；
   - 凡达成 **“Keil 0 Error 全量构建 + JTAG 探针在线烧录 + CPU 存活遥测通过 + 实机功能 100% 验收”**，即达到黄金发布标准，立即封版交付。
4. **全自动无阻塞流水线 (Zero-Interaction Autonomy)**：
   - 多调试探针自动静默仲裁，串口 COM 口自动嗅探，严禁任何阻塞自动化脚本的终端交互弹窗。
