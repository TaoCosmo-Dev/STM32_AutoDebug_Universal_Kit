# 🚀 STM32 硬件在环全流程固件架构师与自愈开发套件
### (STM32 AutoDebug & Firmware Copilot Universal Kit)

[![GitHub Release](https://img.shields.io/badge/Release-v1.1.1-blue?style=flat-square&logo=github)](https://github.com/TaoCosmo-Dev/STM32_AutoDebug_Universal_Kit/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg?style=flat-square)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-STM32%20%7C%20Cortex--M-orange?style=flat-square)]()
[![First-Principles](https://img.shields.io/badge/Engineering-First--Principles-brightgreen?style=flat-square)]()

> **核心信仰**：**谋定而后动，系统稳定与硬件安全压倒一切。第一性原理深层归因，拒绝过度工程。**  
> **拒绝盲目动手！** 从用户的模糊想法出发，强制执行 **Grill-Me 5大硬件决策访谈**（时钟晶振、引脚复用排查、外设物理指标、通信驱动模式、系统架构选型），输出**小白防呆型硬件接线指南**。用户只需负责照图插线，剩下的代码编写、Keil 0 Error 编译自愈、JTAG 多探针免阻塞在线烧录、串口自动嗅探、CPU 寄存器遥测与交互控制台全部由 AI 全自动闭环完成！

---

## 💡 第一性原理与务实工程铁律 (First-Principles Mandate)

本项目坚决践行**“第一性原理与零过度工程”**四大工程铁律：
1. 🔬 **第一性原理深层归因 (Root-Cause from Silicon)**：遇 Bug（如显存镜像、闪烁、死锁）必须追溯至芯片寄存器位定义（MADCTL / RCC / SCB）、时钟树与物理层机制，严禁碰运气式盲改参数；
2. 🚫 **严厉拒绝过度工程与虚假需求 (Zero Over-Engineering & YAGNI)**：当轻量架构与基础状态机足以满足系统指标时，严禁为了“形式高大上”无意义引入过度复杂的中间件；仅在存在真实多任务/多协议栈并发需求时才正规引入 RTOS；
3. 🏁 **清晰坚固的交付边界 (Ruthless Definition of Done)**：凡达成 “Keil 0 Error 全量构建 + JTAG 探针在线烧录 + CPU 存活遥测通过 + 实机功能 100% 验收”，即达到黄金发布标准立即封版；
4. ⚡ **全自动无阻塞流水线 (Zero-Interaction Autonomy)**：多调试探针自动静默仲裁，串口 COM 口自动嗅探，杜绝任何阻塞自动化脚本的终端交互弹窗。

---

## 🌟 核心全生命周期 (The 4-Stage Lifecycle)

```mermaid
graph TD
    subgraph 阶段 1: Grill-Me 深度访谈对齐
        A[用户提出新需求/新想法] --> B[AI 强制启动 Grill-Me 5大硬件分支追问]
        B --> B1[分支1: 外部晶振 HSE 频率与系统主频时钟树]
        B --> B2[分支2: 开发板型号与 SPI/I2C/UART/PWM/ADC 引脚复用冲突排查]
        B --> B3[分支3: 外设物理指标 显存偏置/传感器量程/电机极对数/总线波特率]
        B --> B4[分支4: 通信驱动模式 硬件 DMA 双缓冲 / 中断环形缓冲区 vs 轮询]
        B --> B5[分支5: 系统架构 裸机状态机 vs RTOS 多任务并发 vs 协议栈]
        B1 & B2 & B3 & B4 & B5 --> C[生成《技术实施方案与架构草案》由用户确认]
    end
    
    subgraph 阶段 2: 小白防呆接线交付
        C --> D[输出《杜邦线引脚对照表 + 电气安全预警》]
        D --> E[【唯一人工操作】用户插好杜邦线并回复'接好了']
    end
    
    subgraph 阶段 3: 固件开发与在环自愈
        E --> F[AI 编写符合 MISRA-C/BARR-C 工业级驱动源码]
        F --> G[调用 Keil UV4 全量编译]
        G -- 编译报错 --> H[自动分析 AST 与行号，读取 diagnostic_report 自愈修复]
        H --> G
        G -- 达成 0 Error --> I[PyOCD JTAG 在线擦除与烧录]
        I --> J[探针遥测 CPU PC/CFSR 寄存器与 HardFault 自愈排错]
    end
    
    subgraph 阶段 4: 成果交付与交互控制台
        J --> K[生成 1:1 硬件像素遥测/控制页面]
        K --> L[交付实机验收！]
    end
```

---

## 📋 Grill-Me 5大硬件决策访谈标准 (Hardware Decision Tree)

在进入任何编码或接线前，AI 必须严格执行以下追问与排查：

1. ⏱️ **时钟源与外部晶振 (HSE)**：
   - 确切晶振频率（`8.000MHz` / `12.000MHz` / `25.000MHz`）；
   - 精准计算 PLL 倍频系数（$\text{SYSCLK} = \frac{\text{HSE}}{\text{PLL\_M}} \times \frac{\text{PLL\_N}}{\text{PLL\_P}}$），杜绝超频死机或延时倍速失效。
2. 🔌 **开发板型号与引脚冲突排查**：
   - 核对板载资源（正点原子 / 野火 / 立创 / 自定义板），排查目标引脚（SPI/I2C/UART/PWM/ADC）是否已被板载 SPI Flash、以太网 PHY、板载 LED 占用。
3. ⚙️ **外设与执行机构核心物理指标 (Peripherals & Actuators)**：
   - **显示面板**：ST7735S / ST7789 / SSD1306 显存偏置、RGB565 格式与颜色反转；
   - **电机与逆变器**：极对数、编码器 CPR/霍尔、死区时间与驱动芯片类型 (DRV8302/TMC2209)；
   - **传感器与采样**：IMU 陀螺仪 / 温湿度 I2C 从机地址、量程与采样率；
   - **通信总线模组**：CAN / RS485 波特率、滤波器与流控引脚。
4. ⚡ **通信时序与驱动模式**：
   - 硬件 DMA 双缓冲 / 中断环形缓冲区 (Ring Buffer) 异步高速传输 vs 阻塞轮询。
5. 🏗️ **系统框架与架构选型**：
   - 裸机前后台状态机 vs RTOS (FreeRTOS/RT-Thread) 多任务并发调度 vs 图形/网络协议栈。

---

## 🛠️ 新电脑 30 秒一键初始化 (New PC Setup)

当你在一台全新的电脑上克隆本项目时：

### 第 1 步：克隆代码仓库
```bash
git clone https://github.com/TaoCosmo-Dev/STM32_AutoDebug_Universal_Kit.git
cd STM32_AutoDebug_Universal_Kit
```

### 第 2 步：双击运行一键环境初始化
直接双击运行：
👉 **`setup_env.bat`**
- ⚡ 自动通过国内清华源高速安装 `pyocd`、`pyserial`、`websockets` 依赖；
- ⚡ 自动检索 Windows 注册表与全盘驱动器定位 Keil `UV4.exe`；
- ⚡ 自动识别已连接的硬件调试探针（CMSIS-DAP / ST-Link）并完成自检。

---

## 🎮 接入任意新项目 / 存量工程

### 方式 A：1秒拖拽注入（最简单）
将任意 Keil / CubeMX 工程文件夹直接拖拽到：
👉 **`inject_to_project.bat`**
- 1 秒自动将 AI 规范（`AGENTS.md`、`.cursorrules`）与自愈引擎注入目标工程；
- 在新项目窗口对 AI 说：“*根据 AGENTS.md 规范开始编写代码并自动验证*”，AI 立即全自动接管！

### 方式 B：配置全局 MCP Server（零拷贝通用）
在 **Cursor**、**Windsurf** 或 **Claude Code** 的 MCP 配置中添加：
```json
{
  "mcpServers": {
    "stm32-copilot": {
      "command": "python",
      "args": [
        "C:\\Users\\77517\\Desktop\\STM32_AutoDebug_Universal_Kit\\mcp_server.py"
      ]
    }
  }
}
```

---

## 📁 目录结构说明

```
STM32_AutoDebug_Universal_Kit/
├── setup_env.bat             # [1-Click] 新电脑一键环境初始化脚本
├── setup_env.ps1             # [1-Click] PowerShell 版本一键初始化脚本
├── inject_to_project.bat      # [1-Click] 存量/新工程拖拽注入器
├── inject_to_project.py       # 工程注入核心 Python 逻辑
├── mcp_server.py             # 跨编辑器通用 MCP 服务端
├── AGENTS.md                 # 通用 AI 智能体开发规范（内置 Grill-Me SOP）
├── .cursorrules              # Cursor / Windsurf 专用规则
├── autodebug/                # 自动化构建、烧录、寄存器遥测核心引擎
│   ├── config.py             # 注册表扫描与探针自适应模块
│   ├── builder.py            # Keil UV4 驱动与编译日志解析器
│   ├── hardware_probe.py     # PyOCD JTAG 探针（多探针自动静默仲裁）
│   ├── serial_monitor.py     # 智能串口监听器（COM口自动嗅探+断言解析）
│   ├── fault_analyzer.py     # Cortex-M HardFault 智能故障诊断器
│   ├── diagnostic_report.py  # 结构化诊断上下文生成器
│   └── symbol_resolver.py    # AXF/ELF 符号与源码行号映射器
└── templates/                # 标准规范模板库
    ├── grill_me_hardware_checklist.md # 5大分支 Grill-Me 访谈标准模板
    └── wiring_guide_template.md       # 小白防呆型硬件接线规范模板
```

---

## 📄 开源许可证 (License)
本项目基于 [MIT License](LICENSE) 开源，允许任何个人或企业免费使用、修改与商用。
