# 🚀 STM32 全自动开发套件

### 给 AI 装上手和眼睛：自己写代码、编译、烧录、上板跑、崩了自己查

[![GitHub Release](https://img.shields.io/badge/Release-v2.0.0-blue?style=flat-square&logo=github)](https://github.com/TaoCosmo-Dev/STM32_AutoDebug_Universal_Kit/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg?style=flat-square)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-STM32%20%7C%20Cortex--M-orange?style=flat-square)]()
[![Tests](https://img.shields.io/badge/离线自测-61%20项通过-brightgreen?style=flat-square)]()
[![MCP](https://img.shields.io/badge/MCP-stdio%20server-purple?style=flat-square)]()

AI 写嵌入式代码的瓶颈不是不会写，而是**没有反馈**：它看不到 Keil 的报错行号、不知道程序有没有真的跑起来、更不知道 HardFault 时 PC 停在哪。于是只能猜，改一版问一句"好了吗"。

本套件把这条反馈回路补上，并且**只认硬证据**——编译 0 Error + 烧录成功 + 实机串口吐出通过令牌，三者同时成立才算通过，AI 没法"假装做完了"。

| 谁 | 负责什么 |
|---|---|
| **你** | 回答硬件参数（晶振、引脚、外设型号）、照着 AI 给的表插线 |
| **AI** | 需求对齐 → 写驱动 → 编译 → 烧录 → 上板验证 → 崩溃归因 → 改代码 → 重来 |
| **本套件** | 给 AI 提供：Keil CLI 编译与错误解析、SWD 烧录与运行控制、串口捕获、HardFault 寄存器级归因、崩溃地址反查源码行 |

---

## 实际效果

你在 AI 编辑器里说人话，它先反问硬件问题，然后给接线表：

> **你**：我要用 DHT11 读温湿度，串口打印，LED 每秒闪一次。
>
> **AI**：先确认几件事 —— 外部晶振是 8MHz 还是 12MHz？DHT11 数据线接哪个 GPIO？板载 LED 是哪个脚、高电平点亮还是低电平？
>
> ……（确认后）……
>
> **AI**：按下表接线，插好回复"接好了"：
> | DHT11 | 开发板 |
> |---|---|
> | VCC | 3V3 ⚠️ 不可接 5V |
> | GND | GND |
> | DATA | PA1（需 4.7kΩ 上拉） |

你回"接好了"，之后全自动：

```
>>> [第 1 轮] 步骤 1/4  正在用 Keil 编译 ...
[+] 编译通过  0 Error，0 Warning，耗时 12.3s

>>> [第 1 轮] 步骤 2/4  正在烧录到板子（烧完先让 CPU 停住不跑）...
[+] 烧录成功（下载器 0670FF...，芯片 stm32f103c8），CPU 已停在复位入口等待放行。

>>> [第 1 轮] 步骤 3/4  先打开串口监听，再放 CPU 运行 ...
[+] 已监听串口 COM6 @ 115200
  [MCU] system clock 72MHz ready
  [MCU] temp = 26.4 C  humi = 48%
  [MCU] [ALL TESTS PASSED]

>>> [第 1 轮] 步骤 4/4  判定结果并分析根本原因 ...
[+] 实机测试通过！（收到通过信号：[ALL TESTS PASSED]）
```

崩溃时不是"跑飞了"，而是直接给到行：

```
[-] 板子崩溃了（固件通过串口自报了故障现场）
    根本原因：空指针解引用（NULL Pointer Dereference）：程序访问了 NULL 或接近 0 的地址 0x00000004。
[!] 诊断报告已写入：MDK-ARM\diagnostic_report.json

崩溃点: ../User/dht11.c:88（函数 DHT11_Read）
     86 |     /* dev 未判空 */
>>>  88 |     dev->port->BSRR = dev->pin;
```

---

## 前置条件

**硬件**

| 项 | 要求 |
|---|---|
| 开发板 | 任意 STM32（F0/F1/F3/F4/F7/G0/G4/H7/L4/C0 …），型号从 `.uvprojx` 自动读 |
| 调试器 | ST-Link / DAP-Link / CMSIS-DAP，**必需**（SWD 四线：SWDIO、SWCLK、GND、3V3）|
| 串口 | USB-UART（CH340 / CP210x / ST-Link VCP 均可，多数板子已板载）|

**软件**

| 项 | 说明 |
|---|---|
| Python ≥ 3.10 | 安装时勾选 `Add python.exe to PATH` |
| Keil MDK5 | AC5 / AC6 均支持。**装完就不用再打开它了** —— 编译由本套件走 UV4 命令行驱动 |
| AI 编辑器 | Claude Code / Cursor / Windsurf / Cline / Roo Code / GitHub Copilot / Codex CLI / Trae / 通义灵码 / Aider 等均可，见下 |

> 目前仅 Windows。核心依赖 Keil MDK，暂无 Mac / Linux 版。

> Keil 工程里那些必须勾的选项、必须加进工程的文件，全部由套件和 AI 用命令完成，
> 详见 [AI 自动完成的准备工作](#ai-自动完成的准备工作)。

---

## 安装

```bash
git clone https://github.com/TaoCosmo-Dev/STM32_AutoDebug_Universal_Kit.git
cd STM32_AutoDebug_Universal_Kit
```

双击 **`setup_env.bat`**（或 `powershell -ExecutionPolicy Bypass -File setup_env.ps1`），它会装依赖、装常用 CMSIS 器件包，然后自检：

```
[4/4] 自检：工具链 / 探针 / 串口 / 离线单元测试

  Keil UV4   : C:\Keil_v5\UV4\UV4.exe
下载器（调试探针）：
  - STM32 STLink  [050051000E00004D43504D4E]

串口：
  - COM6 - USB-SERIAL CH340 (COM6)

  [READY] 这台电脑已具备 编译 / 烧录 / 自愈调试 能力
```

三行都有内容就绪。`NOT FOUND` / 探针为空 / 串口为空，分别对应 Keil 未装、调试器未插或被占用、缺 USB-UART 驱动。

> **不需要改配置文件。** Keil 装在哪个盘、用 ST-Link 还是 DAP-Link、串口是 COM3 还是 COM12，全部自动识别；
> 配置里写死的路径在本机不存在时也会自动回退到探测结果，所以同一份配置换台电脑照样能用。

---

## 接入工程

**已有 Keil 工程**：把工程文件夹拖到 `inject_to_project.bat` 上。

```
  [+] AGENTS.md（AI 规范，开场白里让 AI 读它即可）
  [+] run_autodebug.py
  [+] autodebug/ 引擎
  [+] autodebug.config.yaml（本工程配置）
  [+] mcu_support/cm_backtrace_lite.c
  找到 Keil 工程：MDK-ARM\Demo.uvprojx
```

规范只有 `AGENTS.md` 一个文件（已存在且不是本套件生成的会保留不覆盖）。不生成 `.cursorrules`、`.clinerules` 这类各家专属副本 —— 同一份内容散成六份只会互相不同步。

**还没有工程**：需要一个能编译的 `.uvprojx` 作为起点——用板厂例程改最快，也可以用 STM32CubeMX 生成。
把这件事直接交给 AI：*"我的芯片是 STM32F103C8T6，帮我搞一个能编译的 Keil 工程，然后按 AGENTS.md 接管"*。
工程建好之后的**所有**结构改动（加文件、加路径、加宏、开调试信息、装崩溃追踪器）都由 AI 用命令完成，不需要你开 Keil。

---

## 用法

用 AI 编辑器打开注入后的工程目录，开场白：

```
读一下 AGENTS.md，按里面的规范来。
我想做：<你的需求，说人话即可>
```

**不挑编辑器**：规范只有 `AGENTS.md` 一个文件，靠开场白那句"读一下 AGENTS.md"生效，
不依赖任何一家的规则自动加载机制。所以**任何能读文件 + 能跑终端命令的 AI** 都能驱动它 ——
Claude Code、Cursor、Windsurf、Cline、Trae、通义灵码、Copilot、Aider、自建 Agent 一视同仁。

之后的流程：

| 阶段 | AI | 你 |
|---|---|---|
| 1 需求对齐 | 追问 5 类硬件参数（时钟树 / 引脚冲突 / 外设指标 / 驱动模式 / 架构选型）| 如实回答，不确定就说"你来定" |
| 2 方案确认 | 输出技术方案 + 引脚对照表 | 过一眼 |
| 3 接线 | 给出杜邦线对照表 + 电气警告 | **插线**（唯一需要动手的地方），回"接好了" |
| 4 闭环 | 写码 → 编译 → 烧录 → 上板 → 崩溃归因 → 自修复 → 重来 | 等 |
| 5 交付 | 报告通过 | 验收 |

AI 也可以直接调命令行（它自己会调，你一般不用）：

```bash
python run_autodebug.py --project MDK-ARM/App.uvprojx        # 完整闭环
python run_autodebug.py --project MDK-ARM/App.uvprojx --json # 机器可读
python run_autodebug.py --list-devices                        # 列探针与串口
```

也可以配成 MCP Server 让编辑器原生调用（10 个工具，见 [ADVANCED](docs/ADVANCED.md#mcp-server-接入)）。

---

## 判定标准

脚本的退出码就是结论，不看日志措辞：

| 码 | 状态 | 含义 |
|:---:|---|---|
| 0 | `TEST_PASSED` | 编译 0 Error + 烧录成功 + 串口收到通过令牌 |
| 1 | `BUILD_FAILED` | 编译 / 链接错误，报告里带 `文件:行号` |
| 2 | `FLASH_FAILED` | 探针 / 接线 / 供电 / 读保护 —— **不是代码问题** |
| 3 | `HARD_FAULT`·`ASSERTION_FAILED` | 运行时崩溃，已定位到源码行 |
| 4 | `TIMEOUT`·`SERIAL_UNAVAILABLE` | 没等到令牌 / 串口打不开 |
| 5 | `STALLED` | 连续两轮完全相同的失败，停机交人工 |
| 6 | `CONFIG_ERROR` | 找不到 Keil |

结构化诊断写在工程根 `diagnostic_report.json`，历史归档在 `.autodebug/`。

---

## AI 自动完成的准备工作

要让崩溃能定位到源码行、让闭环能判定成功，工程需要几项设置。**这些全部由 AI 用命令完成，你不用打开 Keil**：

| 事项 | 谁做 | 怎么做 |
|---|---|---|
| 新写的 `.c` 加入工程 | AI | `--add-source User/dht11.c`（不加就是 `L6218E: Undefined symbol`）|
| 加包含路径 / 宏定义 | AI | `--add-include` / `--add-define` |
| 开启调试信息 | 套件 | 每次编译前自动检查并打开 `.uvprojx` 里的 `<DebugInformation>` |
| 装崩溃追踪器 | AI | `--install-tracer --uart USART1` 一条命令搞定（见下）|
| 打印通过令牌、调用 `cm_backtrace_init()` | AI | 写代码时带上，`--check-firmware` 可自检 |

所有工程改动都**幂等**且首次改动前自动备份为 `*.autodebug.bak`。

### `--install-tracer` 到底做了什么

```bash
python run_autodebug.py --project MDK-ARM/App.uvprojx --install-tracer --uart USART1
```

```
[tracer] 已拷入 mcu_support/: cm_backtrace_lite.c, cm_backtrace_lite.h
[tracer] 已生成 cm_backtrace_port.c（USART1，SR/DR 寄存器组）
[tracer] 已加入工程组 AutoDebug [App]: cm_backtrace_lite.c, cm_backtrace_port.c
[tracer] 已加入包含路径 [App]: ..\mcu_support
[tracer] 已开启调试信息 [App]
[tracer] 已注释 stm32f1xx_it.c 中的空处理函数: HardFault_Handler
```

几个值得说明的点：

- **`putchar` 按芯片系列生成**：F1/F2/F4/L1 用 `SR/DR`，其余用 `ISR/TDR`；直接测 TXE 位（bit 7）
  而不是用宏名，避开 `USART_SR_TXE → USART_ISR_TXE → USART_ISR_TXE_TXFNF` 的改名。
- **不用 `printf`**：故障处理里 `printf`/`HAL_UART_Transmit` 的超时依赖 SysTick，而 HardFault
  优先级 −1 时 SysTick 进不了中断，`HAL_GetTick()` 永不递增 → 死等 → 一个字节都吐不出来。
- **自动消解 `HardFault_Handler` 冲突**：HAL 模板里那个 `while(1){}` 空实现既会导致重复定义，
  又正是它把崩溃变成静默死机。这里把它注释掉（原文保留在注释里，可还原），并自动备份。
- **`--uart` 填应用里已初始化好的那个串口**——这个参数在 Grill-Me 阶段就问清了。

### 闭环超时时会告诉你缺什么

固件没有输出时，脚本不会只说"超时了"，而是先检查固件侧约定：

```
[-] 等了 15s 没等到通过信号（CPU 是否在跑：是）
    [固件契约] 没有任何源文件打印通过令牌 [ALL TESTS PASSED]，闭环无法判定成功
    [固件契约] main() 里没有调用 cm_backtrace_init()，崩溃时拿不到 CFSR 分类与除零陷阱
```

这两条会排在诊断报告 `next_actions` 的最前面——十次静默里有九次不是业务逻辑写错了，
而是压根没让固件开口说话。

---

## 排错

| 现象 | 原因 | 处理 |
|---|---|---|
| 退出码 6 | Keil 未安装或路径不对 | 装 Keil，或在 `autodebug.config.yaml` 写 `keil.uv4_path` |
| 编译卡住后被 kill | Keil 弹了模态框（缺器件包 / License / 工程被 IDE 占用）| 关掉 uVision，手动打开工程确认无弹窗 |
| 退出码 2，无探针 | 调试器未插，或被 Keil / CubeProgrammer 占用 | `--list-devices` 确认；关掉占用程序 |
| 退出码 2，连不上目标 | 固件复用了 SWD 引脚，或芯片读保护 | 保持 `connect_mode: under-reset`；RDP1 需整片擦除解锁 |
| 退出码 4，串口零字节 | 串口重定向未实现 / 波特率不符 / COM 被串口助手占用 | 前两项由 AI 修（`--check-firmware` 会点名）；你只需关掉 SSCOM 等占用串口的程序 |
| 退出码 4，有输出无令牌 | 测试没走到输出点 | 报告会先列出未满足的固件契约，再看 **CPU 存活遥测**：PC 不变 = 卡在死等循环 |
| 崩溃了但无源码行 | 工程未输出调试信息 | 每次编译前会自动打开；只有手动关了 `auto_fix_debug_info` 才需处理 |
| 报告写"故障地址无效" | imprecise 总线错误（写缓冲延迟） | 在可疑写操作后加 `__DSB()` 缩小范围 |
| 连续几轮同一个错 | 上一次修改没生效 | 报告的 `repeated_failure` 会为 true，换思路而不是重复同类改动 |

---

## 目录结构

```
├── setup_env.bat / .ps1        # 环境初始化 + 自检
├── inject_to_project.bat / .py # 工程注入器
├── run_autodebug.py            # 闭环运行器（退出码即契约）
├── mcp_server.py               # MCP stdio 服务端（7 个工具）
├── AGENTS.md                   # AI 开发规范（唯一的规则文件，注入到工程里）
├── docs/ADVANCED.md            # 闭环时序、完整配置、MCP、架构、v2.0 修复清单
├── autodebug/                  # 引擎：编译 / 烧录 / 串口 / 故障分析 / 符号解析 / 报告 / 工程编辑 / 编排
├── mcu_support/                # cm_backtrace_lite：固件侧崩溃追踪器 + HardFault 汇编胶水
├── templates/                  # 硬件访谈与接线指南模板
└── tests/                       # 61 项离线自测（无需硬件）
```

---

## 设计要点（为什么它能跑通）

- **烧录后保持内核 halt，开完串口再 resume。** 固件复位后几十毫秒就打印启动横幅，
  先 resume 再开串口必然丢掉这段，通过令牌永远抓不到 —— 这是"代码明明没问题却一直超时"的根源。
- **产物新鲜度校验。** 只看 `.axf` 存在就烧，可能把上一版固件当成本次修改的验证结果；这里校验 mtime。
- **烧录失败立即中止本轮。** 否则串口读到的是旧固件的行为，诊断报告会把 AI 引向完全错误的方向。
- **BFAR/MMFAR 全链路贯通并按 CFSR 有效位判定。** 有地址才敢说"空指针"，无效时如实写"无效"，不猜。
- **pyOCD 全程 `blocking=False` + 单会话。** 桌上插两个探针不会弹选择菜单卡死；
  也不会因为重连（under-reset）把刚要读的 CFSR 擦掉。
- **工程自修复。** 编译前直接改 `.uvprojx` 打开 `<DebugInformation>`，没它就没有 DWARF 行表，
  崩溃永远定位不到行 —— 但这不该逼用户去开 uVision 勾一个框。改动前自动备份，且只动当前 target。
- **护栏**：每轮改动前 `git stash create` 打还原点（不动工作区）；失败签名连续重复即停机交人工。

细节见 [docs/ADVANCED.md](docs/ADVANCED.md)。

---

## 验证

```bash
python -m unittest discover -s tests -v
```

61 项覆盖闭环关键路径上的纯函数：编译/链接日志解析、CFSR/HFSR 解码、故障地址有效性、
UART 崩溃块解析、断言三种格式、串口打分、配置回退，以及 `.uvprojx` 编辑器的幂等与 XML 完整性。
无需 Keil、探针或板子。

---

## FAQ

<details>
<summary><b>支持哪些芯片？</b></summary>

Cortex-M 内核的 STM32 系列（F0/F1/F3/F4/F7/G0/G4/H7/L0/L4/C0 等）。
芯片型号从 `.uvprojx` 的 `<Device>` 自动推导为 pyOCD target，也可用 `--mcu` 覆盖。
</details>

<details>
<summary><b>它会不会把我的代码改坏？</b></summary>

每轮自动修改前用 `git stash create` + tag 打还原点：不动工作区、不动索引、不在分支上产生提交，
回退用 `git checkout <sha> -- .`。同时连续两轮出现相同失败签名会直接停机交人工，不会无限乱改。
</details>

<details>
<summary><b>为什么必须要有调试器（下载器）？</b></summary>

它是闭环里"烧录"和"读芯片故障寄存器"两个环节的通道。没有它，程序进不去板子，
崩溃时也无法在串口没输出的情况下读到 CFSR/HFSR/BFAR。
</details>

<details>
<summary><b>能不用 MCP，只用命令行吗？</b></summary>

可以。注入后 AI 直接调 `run_autodebug.py` 即可，MCP 只是让编辑器原生调用、少一层 shell。
</details>

---

## License

[MIT](LICENSE) —— 个人、企业均可免费使用、修改、商用。

觉得有用点个 ⭐ Star；问题请提 [Issue](https://github.com/TaoCosmo-Dev/STM32_AutoDebug_Universal_Kit/issues)。
