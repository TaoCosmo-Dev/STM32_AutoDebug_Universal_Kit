# STM32 AutoDebug Universal Kit

**面向 AI 代理的 STM32 闭环开发工具链**：编译、烧录、实机验证、崩溃归因，全部以命令行驱动，结果以退出码交付。

[![GitHub Release](https://img.shields.io/badge/Release-v2.4.0-blue?style=flat-square&logo=github)](https://github.com/TaoCosmo-Dev/STM32_AutoDebug_Universal_Kit/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg?style=flat-square)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-STM32%20%7C%20Cortex--M-orange?style=flat-square)]()
[![Tests](https://img.shields.io/badge/离线自测-114%20项通过-brightgreen?style=flat-square)]()
[![MCP](https://img.shields.io/badge/MCP-stdio%20server-purple?style=flat-square)]()

---

## 目录

- [解决的问题](#解决的问题)
- [工作示例](#工作示例)
- [实现原理](#实现原理)
- [能力边界](#能力边界)
- [环境要求](#环境要求)
- [安装](#安装)
- [接入工程](#接入工程)
- [仓库文件说明](#仓库文件说明)
- [退出码契约](#退出码契约)
- [固件侧前提](#固件侧前提)
- [进阶参考](#进阶参考)
- [常见问题](#常见问题)

---

## 解决的问题

AI 编写嵌入式代码的主要障碍不在语法生成，而在**缺乏执行反馈**。

模型无法获知 Keil 的报错位置，无法确认固件是否在目标芯片上实际运行，也无法在发生 HardFault 时得知程序计数器的停留位置。缺少判据，模型只能反复试探，每次修改后都需要开发者手动编译、烧录、观察串口，再将结果转述回去。

本工具链补全这条反馈回路。部署后，AI 代理可自主完成：

| 能力 | 实现手段 |
|---|---|
| 获取带文件名与行号的编译错误 | 命令行驱动 Keil UV4，解析编译日志 |
| 烧录固件并控制内核运行状态 | SWD 调试接口 |
| 判定固件是否真正通过测试 | 串口捕获固件输出的通过令牌 |
| 将崩溃定位到具体源码行 | 读取故障寄存器，反查调试信息 |
| 判断上一次修改是否生效 | 失败指纹比对 |

判定标准为硬性证据：**编译 0 Error、烧录成功、实机串口输出通过令牌**，三者同时成立方视为通过。

### 职责划分

| 角色 | 职责 |
|---|---|
| 开发者 | 提供硬件参数（晶振频率、引脚分配、外设型号），按代理输出的接线表连接硬件 |
| AI 代理 | 需求对齐、编写驱动、编译、烧录、实机验证、崩溃归因、修复、迭代 |
| 本工具链 | 将上述每一步封装为可调用的命令，并将执行结果转换为可判定的结论 |

---

## 工作示例

代理先确认硬件参数，再输出接线表：

> **输入**：需要读取 DHT11 温湿度，通过串口打印，LED 每秒闪烁一次。
>
> **代理**：请确认以下参数 —— 外部晶振为 8MHz 还是 12MHz？DHT11 数据线连接哪个 GPIO？板载 LED 的引脚编号及点亮电平？
>
> ……（参数确认后）……
>
> **代理**：请按下表接线，完成后告知。
>
> | DHT11 | 开发板 |
> |---|---|
> | VCC | 3V3（注意：不可接 5V） |
> | GND | GND |
> | DATA | PA1（需 4.7kΩ 上拉） |

接线确认后，后续流程全自动执行：

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

运行时崩溃不止于"程序跑飞"的模糊结论，而是定位到具体源码行：

```
[-] 板子崩溃了（固件通过串口自报了故障现场）
    根本原因：空指针解引用（NULL Pointer Dereference）：程序访问了 NULL 或接近 0 的地址 0x00000004。
[!] 诊断报告已写入：MDK-ARM\diagnostic_report.json

崩溃点: ../User/dht11.c:88（函数 DHT11_Read）
     86 |     /* dev 未判空 */
>>>  88 |     dev->port->BSRR = dev->pin;
```

---

## 实现原理

本节说明工具链的工作机制。理解这部分有助于在出现异常时定位问题所在环节。

### 三条独立通道

开发主机与目标芯片之间通过三条彼此独立的通道连接：

| 通道 | 物理连接 | 职能 |
|---|---|---|
| 编译 | 无需连线 | 在主机本地将 C 源码编译为机器码 |
| SWD 调试接口 | SWDIO / SWCLK / GND | 直接读写芯片内部存储与寄存器，控制内核暂停或运行 |
| 串口 UART | TX / RX / GND | 接收芯片主动发送的运行时输出 |

**SWD 与串口的区别贯穿整个设计**：串口依赖固件主动发送数据，固件停止工作即无数据可读；SWD 由主机主动发起访问，**即使内核已停止运行仍可读取芯片状态**。

### 一、编译与错误定位

Keil 的 `UV4.exe` 支持命令行调用。工具链以此方式在后台编译，不触发图形界面，因此 Keil 安装完成后无需再启动其 IDE。

编译结束后，Keil 将过程写入日志文件。工具链解析该日志，将错误信息转换为结构化字段：

```
..\User\dht11.c(88): error:  #20: identifier "dev" is undefined
   ↓
文件 = dht11.c   行号 = 88   错误码 = #20   描述 = identifier "dev" is undefined
```

代理接收到的是「文件 + 行号 + 原因」而非原始日志文本，因此可直接定位到需要修改的位置。

编译产物 `.axf` 文件是后续崩溃定位的依据。

### 二、SWD 与内核状态控制

ARM Cortex-M 芯片内部集成了一块**独立于 CPU 内核的调试电路**。该电路拥有独立的供电与时钟，通过 SWDIO / SWCLK 两根信号线对外，可访问芯片的任意存储地址与全部内核寄存器，并可控制内核暂停或继续执行。

该电路的运行**不依赖 CPU 内核是否正常**。内核进入异常、死循环或完全停止后，调试电路仍可正常响应主机请求。这是崩溃归因功能得以成立的硬件基础。

烧录过程即通过 SWD 完成：暂停内核 → 向 Flash 写入机器码 → 复位。

### 三、执行时序

芯片复位后数十毫秒内即完成启动信息的输出，而主机打开串口需要经历设备枚举与参数配置，耗时更长。

若执行顺序为「烧录 → 释放内核 → 打开串口」，启动阶段的输出将在串口就绪前完成，**通过令牌无法被捕获**。表现为固件逻辑正确但闭环始终超时。

正确顺序为：

```
烧录 → 保持内核暂停 → 打开串口监听 → 释放内核 → 捕获输出
```

引擎源码的首行注释即为此设计的说明：`Ordering is the whole trick.`

### 四、崩溃归因

**第一阶段：读取故障现场**

Cortex-M 内核在进入异常时由硬件自动将现场压栈，其中程序计数器 **PC** 记录了异常发生时正在执行的指令地址。同时，以下故障状态寄存器记录异常原因：

| 寄存器 | 记录内容 |
|---|---|
| CFSR | 异常分类（除零、非法地址访问、栈溢出、非对齐访问等） |
| BFAR | 总线错误对应的非法访问地址 |
| MMFAR | 存储器管理错误对应的非法访问地址 |
| HFSR | 硬故障总标志 |

工具链通过 SWD 读取上述寄存器。此时内核已停止运行，但调试电路仍然可用。

> BFAR 仅在 CFSR 声明其有效时采信。无效时报告明确记录"故障地址无效"，不作推测。

**第二阶段：地址到源码行的转换**

编译器在生成机器码的同时，将地址与源码位置的对照表（DWARF 调试信息）写入 `.axf` 文件：

```
0x08001A3C ~ 0x08001A48  ←→  dht11.c 第 88 行，函数 DHT11_Read
0x08001A48 ~ 0x08001A50  ←→  dht11.c 第 89 行
```

工具链解析 `.axf` 读取该表，以二分查找定位 PC 所属区间，并提取对应源码片段写入诊断报告。

因此工具链在每次编译前强制启用工程的调试信息输出选项。该选项关闭时编译器不生成对照表，崩溃信息将只剩地址数值。

**备用通道**：工具链可向固件植入 `cm_backtrace_lite` 模块，由芯片在异常发生时通过串口主动输出故障现场。两条通道互为备份。

> 异常处理流程中不可使用 `printf` 或 `HAL_UART_Transmit`。二者的超时判定依赖 SysTick，而 HardFault 的异常优先级高于 SysTick，导致其无法进入中断、计数器不再递增，最终在输出首字节前进入死等。工具链生成的输出函数采用轮询方式直接操作串口寄存器。

### 五、闭环判定机制

**退出码作为唯一判据。** 脚本返回整数而非文本结论。文本需要语义理解，存在误判空间；退出码不存在歧义。

**失败指纹用于识别停滞。** 每次失败生成一个指纹（编译错误为 `文件:行号:错误码:描述`，运行时异常为 `故障类型|PC|CFSR`）。同一指纹在窗口期内重复出现，表明上一次修改未产生实际效果，此时应更换排查方向；持续重复则终止自动修复，转交人工判断。

---

## 能力边界

### 支持的能力

- 自动修复编译错误，附带文件名与行号
- 自动定位运行时崩溃至源码行，并给出根本原因分类
- 自动判定固件是否实际通过测试（需串口）
- 自动修改 Keil 工程结构：添加源文件、包含路径、预处理宏、崩溃追踪器，全程无需启动 uVision
- 识别修复停滞并主动终止，交由人工判断

### 不支持的能力

| 限制 | 说明 |
|---|---|
| 不生成新工程 | v2.3.0 起移除。请先通过 STM32CubeMX 导出、开发板附带例程或教程配套工程获得一个可编译的 Keil 工程 |
| 仅支持 Windows | 核心依赖 Keil MDK |
| 仅支持 Keil 工具链 | 不支持 IAR、CMake/GCC、PlatformIO |
| 调试器为必需项 | ST-Link / DAP-Link / CMSIS-DAP 缺一不可，否则无法烧录，亦无法读取崩溃现场 |

### 未连接串口时的表现

**可完成错误排查，但无法完成验收。**

| 环节 | 无串口时 |
|---|---|
| 编译与错误定位 | 正常 |
| 烧录与内核状态控制 | 正常 |
| 崩溃定位至源码行 | **正常**（经由 SWD，与串口无关） |
| 通过判定 | **无法获得**，退出码固定为 4 |

需要特别说明的是，**多数缺陷既非编译错误亦非运行时崩溃**：帧解析偏移、时钟配置错误导致延时失准、I2C 从机地址错误、状态机分支遗漏等，程序均可正常运行，仅执行结果不符合预期。缺少串口时，代理对这一类问题完全不可见，且会因持续判定为失败而继续修改本已正确的代码。

串口连接仅需三根线（TX / RX / GND），多数开发板的 ST-Link 已集成虚拟串口，或板载 CH340 等 USB-UART 芯片。**建议接入。**

---

## 环境要求

### 需自行准备

| 项 | 要求 |
|---|---|
| **Keil MDK5** | AC5 / AC6 均可。安装后无需启动其图形界面 |
| **Python ≥ 3.10** | 安装时勾选 `Add python.exe to PATH` |
| **调试器** | ST-Link / DAP-Link / CMSIS-DAP，SWD 四线：SWDIO、SWCLK、GND、3V3 |
| **目标板** | 任意 STM32（F0/F1/F3/F4/F7/G0/G4/H7/L4/C0 等），型号自 `.uvprojx` 读取 |
| **可编译的 Keil 工程** | 本工具链不生成工程 |
| USB-UART | CH340 / CP210x / ST-Link VCP 均可，多数开发板已板载。非强制但强烈建议 |

### 由安装脚本自动完成

| 项 | 体积 | 耗时 |
|---|---|---|
| Python 依赖（pyocd、pyelftools、pyserial、PyYAML、pylink-square） | 约 20 MB | 约 10–30 秒（默认走清华镜像） |
| Agent Skill 安装至各编辑器目录 | 数 KB | 即时 |
| CMSIS 器件支持包 | 每个 10–60 MB | **默认不预装**，首次烧录时按需下载单个包，约 20–60 秒 |

> **v2.3.2 起默认不再预装器件包。** 此前脚本会一次性下载 10 个 STM32 系列的器件包（合计约 250 MB），是首次安装耗时的主要来源，而其中绝大多数用户并不会用到。pyOCD 在首次烧录时会自动下载目标芯片对应的包，因此预装并非必要。
>
> 如需一次性装齐以便离线使用，执行 `setup_env.bat --with-packs`。

---

## 安装

```bash
git clone https://github.com/TaoCosmo-Dev/STM32_AutoDebug_Universal_Kit.git
cd STM32_AutoDebug_Universal_Kit
```

双击 **`setup_env.bat`**，或执行 `powershell -ExecutionPolicy Bypass -File setup_env.ps1`。

脚本依次执行：检测 Python、安装依赖、跳过器件包预装、环境自检、安装 Agent Skill。

```
[4/5] 自检：工具链 / 探针 / 串口 / 离线单元测试

  Keil UV4   : C:\Keil_v5\UV4\UV4.exe
下载器（调试探针）：
  - STM32 STLink  [050051000E00004D43504D4E]
串口：
  - COM6 - USB-SERIAL CH340 (COM6)

[5/5] 安装 Agent Skill（让 AI 在任意工程里自动加载本套件）
  [*] 已安装  C:\Users\you\.agents\skills     共享约定（Cursor / Codex CLI / Gemini CLI）
  [*] 已链接  C:\Users\you\.claude\skills     Claude Code / Claude Desktop
```

上述三项均有输出即表示环境就绪。`NOT FOUND`、探针为空、串口为空分别对应 Keil 未安装、调试器未连接或被占用、缺少 USB-UART 驱动。

**无需修改配置文件。** Keil 安装路径、调试器型号、串口号均自动识别；配置中的固定路径在本机不存在时会自动回退至探测结果。

---

## 接入工程

### 默认方式：Agent Skill（安装一次，全局生效）

`setup_env` 执行完毕即已生效，无需额外操作。用 AI 编辑器打开任意 Keil 工程，直接描述需求：

```
我要实现：<用自然语言描述功能>
```

代理将自动加载规范、确认硬件参数、输出接线表并执行闭环。

**工作机制**：`setup_env` 最后安装的 Skill 即为入口。`SKILL.md` 是开放标准，Claude Code、Cursor、Codex CLI、Gemini CLI、Cline、Windsurf、Copilot、Zed 等均可读取，一次安装覆盖全部工具链。

引擎无需置于工程目录内：其全部路径均自 `--project` 参数推导，诊断报告、状态目录、崩溃追踪器均生成于目标工程中，工具链目录不受影响。

### 可选方式：注入工程

适用于两种情形：需将工具链随工程一并提交版本库，供协作者直接使用；或所用编辑器尚不支持 Agent Skill。

将工程文件夹拖放至 `inject_to_project.bat`：

```
  [+] AGENTS.md（AI 规范）
  [+] run_autodebug.py
  [+] autodebug/ 引擎
  [+] autodebug.config.yaml（本工程配置）
  [+] mcu_support/cm_backtrace_lite.c
  找到 Keil 工程：MDK-ARM\Demo.uvprojx
```

此方式下需在对话开始时指示代理读取规范：

```
读一下 AGENTS.md，按里面的规范来。
我要实现：<用自然语言描述功能>
```

---

## 仓库文件说明

日常使用涉及的文件仅 `setup_env.bat` 与 `AGENTS.md` 两个，其余由代理调用或供查阅。

### 需要手动执行的

| 文件 | 使用时机 | 方式 |
|---|---|---|
| `setup_env.bat` | 首次安装；**以及每次更新或移动工具链之后** | 双击运行。附加 `--with-packs` 可一次性预装全部器件包 |
| `inject_to_project.bat` | 仅在采用注入方式时 | 将工程文件夹拖放至其上 |
| `install_skill.py` | 单独管理 Skill 时 | `python install_skill.py` 安装或刷新；`--list` 查看安装位置；`--uninstall` 卸载 |

> **更新工具链或变更其存放位置后须重新执行 `setup_env.bat`。** Skill 以文件副本形式分发至各编辑器目录，源文件变更不会自动同步至副本。启用 Windows 开发者模式后，安装脚本将改用符号链接，此后无需手动同步。

### 由代理调用的

| 文件 | 作用 |
|---|---|
| `run_autodebug.py` | 主入口。编译、烧录、实机验证、崩溃归因均经由此脚本，退出码即为结论 |
| `mcp_server.py` | 可选。配置为 MCP Server 后，编辑器可原生调用其能力（10 个工具） |
| `autodebug/` | 引擎实现：编译、烧录、串口、故障分析、符号解析、报告生成、工程编辑、流程编排 |

### 规范与素材

| 文件 | 作用 |
|---|---|
| **`AGENTS.md`** | **AI 开发规范，全项目唯一的规则文件。** 闭环流程、退出码契约、需求对齐清单、嵌入式开发准则均在其中。调整代理行为只需修改此文件 |
| `skills/stm32-autodebug/` | Skill 模板。`install_skill.py` 将其分发至各编辑器目录。内容为指向 `AGENTS.md` 的引用而非副本，规范始终保持单一来源 |
| `mcu_support/` | `cm_backtrace_lite.c/.h`，运行于目标芯片的崩溃追踪器。安装追踪器时复制至工程并编译进固件 |
| `templates/` | 硬件参数确认清单与接线指南模板，供代理在需求对齐阶段参考 |
| `docs/ADVANCED.md` | 闭环时序、完整配置项、MCP 接入、架构说明 |
| `tests/` | 114 项离线自测，无需硬件：`python -m unittest discover -s tests` |

### 代理调用的常用命令

```bash
python run_autodebug.py --project MDK-ARM/App.uvprojx              # 完整闭环
python run_autodebug.py --project MDK-ARM/App.uvprojx --no-flash   # 仅编译，不访问硬件
python run_autodebug.py --project MDK-ARM/App.uvprojx --json       # 机器可读输出
python run_autodebug.py --project MDK-ARM/App.uvprojx --check-firmware   # 固件契约自检
python run_autodebug.py --project MDK-ARM/App.uvprojx --add-source User/new.c
python run_autodebug.py --project MDK-ARM/App.uvprojx --install-tracer --uart USART1
python run_autodebug.py --list-devices                             # 列出调试探针与串口
```

---

## 退出码契约

脚本的退出码即为结论，不依据日志文本判断。

| 码 | 状态 | 含义 | 应采取的措施 |
|:---:|---|---|---|
| **0** | `TEST_PASSED` | 编译 0 Error、烧录成功、串口收到通过令牌 | 交付，停止修改 |
| 1 | `BUILD_FAILED` | 编译或链接错误，报告含 `文件:行号` | 按报告修改源码后重试 |
| 2 | `FLASH_FAILED` | 探针、接线、供电或读保护问题 | 非代码问题，不应修改源码 |
| 3 | `HARD_FAULT` / `ASSERTION_FAILED` | 运行时崩溃，已定位至源码行 | 按根本原因修改后重试 |
| 4 | `TIMEOUT` / `SERIAL_UNAVAILABLE` | 未收到通过令牌，或串口不可用 | 检查串口重定向、波特率、测试路径是否到达输出点 |
| 5 | `STALLED` | 同一失败反复出现 | 终止自动修复，说明卡点并请求人工决策 |
| 6 | `CONFIG_ERROR` | 未找到 Keil | 安装环境，或在 `autodebug.config.yaml` 中指定 `keil.uv4_path` |

结构化诊断写入工程根目录 `diagnostic_report.json`，历史记录归档于 `.autodebug/`。

---

## 固件侧前提

多数"运行无响应"的情形并非业务逻辑错误，而是固件未产生可判定的输出。工程配置由代理通过命令完成，但以下两项需在源码中显式实现：

1. **通过令牌**：在测试通过路径上输出 `[ALL TESTS PASSED]`。未输出该令牌时闭环无法判定成功。
2. **`cm_backtrace_init()`**：在 `main()` 的外设初始化之前调用，以启用子异常分类与除零陷阱。

此外，`--check-firmware` 会扫描源码中含非 ASCII 字符的**字符串字面量**。Keil AC5（`armcc`）按本机代码页解析源文件（中文 Windows 上为 GBK），UTF-8 中文串会报 `#8: missing closing quote` —— 该报错指向引号而非编码，极易把排查引向语法方向。中文应只出现在注释中。

执行 `--check-firmware` 将逐项列出未满足的条件。闭环超时时亦会自动附加该清单，并置于诊断报告 `next_actions` 的首位。

---

## 进阶参考

<details>
<summary><b><code>--install-tracer</code> 的执行内容</b></summary>

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

设计说明：

- **输出函数按芯片系列生成**：F1/F2/F4/L1 使用 `SR/DR` 寄存器组，其余使用 `ISR/TDR`。直接检测 TXE 位（bit 7）而非引用宏名，以规避 `USART_SR_TXE` → `USART_ISR_TXE` → `USART_ISR_TXE_TXFNF` 的命名变更。
- **CMSIS 头文件依据工程实际使用的库选择**：HAL 对应 `stm32f1xx.h`，标准外设库对应 `stm32f10x.h`。判定依据为工程自身的 `USE_STDPERIPH_DRIVER` / `USE_HAL_DRIVER` 宏定义，其次为磁盘上实际存在的头文件。仅按芯片系列推导会导致标准外设库工程中的追踪器无法编译。
- **不使用 `printf`**：原因见[实现原理](#四崩溃归因)一节。
- **自动消解 `HardFault_Handler` 冲突**：HAL 模板中的空实现既导致符号重复定义，亦是崩溃表现为静默死机的成因。工具链将其注释（原文保留于注释中可还原）并自动备份。
- **`--uart` 应填写应用中已完成初始化的串口。**

所有工程修改均为幂等操作，首次修改前自动备份为 `*.autodebug.bak`。

</details>

<details>
<summary><b>故障排查对照表</b></summary>

| 现象 | 原因 | 处理 |
|---|---|---|
| 退出码 6 | Keil 未安装或路径不正确 | 安装 Keil，或在 `autodebug.config.yaml` 中指定 `keil.uv4_path` |
| 编译过程被强制终止 | Keil 弹出模态对话框（缺少器件包、License 异常、工程被 IDE 占用） | 关闭 uVision，手动打开工程确认无弹窗 |
| 退出码 2，未检测到探针 | 调试器未连接，或被 Keil / STM32CubeProgrammer 占用 | 以 `--list-devices` 确认；关闭占用程序 |
| 退出码 2，`target type X not recognized` | 非硬件问题，为缺少 CMSIS 器件包 | v2.4.0 起由 preflight 提前拦截，并直接给出 `python -m pyocd pack install <芯片>` |
| 编译报 `#8: missing closing quote` 但引号无误 | 源码含 UTF-8 中文字面量，AC5 按 GBK 解析 | 中文只放注释；`--check-firmware` 会点名文件与行号 |
| 退出码 2，无法连接目标 | 固件将 SWD 引脚复用为普通 IO，或芯片处于读保护状态 | 保持 `connect_mode: under-reset`；RDP Level 1 需整片擦除解锁 |
| 退出码 4，串口无数据 | 串口重定向未实现、波特率不匹配、COM 口被占用 | 前两项由代理修复（`--check-firmware` 会明确指出）；关闭占用串口的调试助手 |
| 退出码 4，有输出但无令牌 | 测试未到达输出点 | 先查看未满足的固件契约，再参考 CPU 存活遥测：PC 值不变表示停留在死等循环 |
| 崩溃但无源码行 | 工程未输出调试信息 | 每次编译前自动启用；仅在手动关闭 `auto_fix_debug_info` 时需处理 |
| 报告记录"故障地址无效" | imprecise 总线错误（写缓冲延迟所致） | 在可疑的写操作后插入 `__DSB()` 以缩小范围 |
| 连续多轮相同错误 | 上一次修改未生效 | 报告中 `repeated_failure` 为 true，应更换排查方向 |

</details>

<details>
<summary><b>关键设计决策</b></summary>

- **烧录后保持内核暂停，串口就绪后再释放。** 固件复位后数十毫秒即输出启动信息，先释放内核再打开串口必然丢失该段输出，此为"固件逻辑正确但持续超时"的成因。
- **如实上报内核停止状态。** CLI 兜底烧录路径会复位并运行目标。此时若上报"已暂停"，后续超时的表现与固件缺陷完全一致，会将排查方向引向不存在的问题。工具链现向目标查询实际状态，并在内核未暂停时于串口就绪后重启目标以补充捕获。
- **校验编译产物时效性。** 仅检查 `.axf` 是否存在可能将上一版固件的行为当作本次修改的验证结果，故校验其修改时间。
- **烧录失败立即终止本轮。** 否则串口读取到的是旧固件的行为，将导致诊断结论完全错误。
- **BFAR / MMFAR 全链路贯通并依据 CFSR 有效位判定。** 地址有效时方给出"空指针"等结论，无效时如实记录。
- **pyOCD 全程使用 `blocking=False` 与单一会话。** 连接多个探针时不会弹出选择菜单导致阻塞。
- **停滞检测基于窗口统计。** 仅比对相邻两轮时，代理在两个错误之间交替修改（A→B→A→B）将无法触发终止条件。

</details>

---

## 验证

```bash
python -m unittest discover -s tests     # 114 项离线自测，无需硬件
```

每次 push 与 Pull Request 由 GitHub Actions 在 Windows + Python 3.10 / 3.12 环境下自动执行，并校验版本号三处一致性与测试数量徽章。

---

## 常见问题

<details>
<summary><b>是否必须使用 Claude Code？</b></summary>

否。`SKILL.md` 为开放标准，Claude Code、Cursor、Codex CLI、Gemini CLI、Cline、Windsurf、Copilot、Zed 等均可读取。即使所用编辑器完全不支持 Skill，亦可采用注入方式，通过对话开始时的指示生效。任何具备文件读取与终端执行能力的 AI 代理均可驱动本工具链。

</details>

<details>
<summary><b>可否不配置 MCP，仅使用命令行？</b></summary>

可以，命令行即为默认方式。MCP Server 属可选的进阶用法，不配置不影响任何功能。

</details>

<details>
<summary><b>标准外设库工程是否支持？</b></summary>

支持。工具链不区分 HAL 与标准外设库，仅与 `.uvprojx` 及目标芯片交互。崩溃追踪器会依据工程实际使用的库选择正确的 CMSIS 头文件。

</details>

<details>
<summary><b>是否存在损坏现有工程的风险？</b></summary>

所有工程修改均为幂等操作，首次修改前自动备份为 `*.autodebug.bak`。此外，每轮代理修改前引擎会通过 `git stash create` 创建不影响工作区的还原点（tag `autodebug/iter-NN`），可用 `git checkout <sha> -- .` 回滚。

</details>

<details>
<summary><b>为何移除了工程生成功能？</b></summary>

该功能依赖本机安装 STM32Cube_FW 固件包，而 Keil 器件包仅包含标准外设库。在这一常见配置下，它会生成引用不存在源文件、必然编译失败的工程，且不产生任何提示。修复需引入库类型探测与模板回退机制，并对每个新增芯片系列持续适配，而目标用户通常已具备可用工程。详见 [v2.3.0 发布说明](https://github.com/TaoCosmo-Dev/STM32_AutoDebug_Universal_Kit/releases/tag/v2.3.0)。

</details>

---

## License

[MIT](LICENSE)。个人与商业用途均可免费使用、修改、分发。

问题反馈请提交 [Issue](https://github.com/TaoCosmo-Dev/STM32_AutoDebug_Universal_Kit/issues)。
