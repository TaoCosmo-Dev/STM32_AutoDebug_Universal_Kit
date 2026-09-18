# 🚀 STM32 全自动开发套件

### 给 AI 装上手和眼睛：自己写代码、编译、烧录、上板跑、崩了自己查

[![GitHub Release](https://img.shields.io/badge/Release-v2.3.1-blue?style=flat-square&logo=github)](https://github.com/TaoCosmo-Dev/STM32_AutoDebug_Universal_Kit/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg?style=flat-square)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-STM32%20%7C%20Cortex--M-orange?style=flat-square)]()
[![Tests](https://img.shields.io/badge/离线自测-91%20项通过-brightgreen?style=flat-square)]()
[![MCP](https://img.shields.io/badge/MCP-stdio%20server-purple?style=flat-square)]()

---

## 这是什么

AI 写嵌入式代码的瓶颈不是不会写，是**看不见结果**。

它看不到 Keil 报错在第几行，不知道程序有没有真的在芯片上跑起来，更不知道 HardFault 时 CPU 停在哪。缺少判据，它只能反复试探，每改一版都要回头问你一句"好了吗"——而你得自己编译、自己烧录、自己盯串口，再把结果复述给它。

**本套件把这条反馈回路接上。** 装好之后，AI 自己就能：

| 它现在能做 | 靠什么 |
|---|---|
| 拿到带**文件名和行号**的编译错误 | 命令行驱动 Keil，解析编译日志 |
| 把固件烧进芯片，并控制它跑或停 | SWD 调试口 |
| 知道程序**有没有真的跑通** | 串口收到固件打印的通过令牌 |
| 崩溃时定位到**具体哪一行代码** | 读芯片故障寄存器 + 反查调试信息 |
| 判断自己上次的改动**有没有起作用** | 失败指纹比对 |

并且**只认硬证据**——编译 0 Error **且** 烧录成功 **且** 实机串口吐出通过令牌，三者同时成立才算通过。AI 没法"假装做完了"。

### 谁干什么

| 角色 | 负责 |
|---|---|
| **你** | 回答硬件参数（晶振、引脚、外设型号）、照 AI 给的表插线 |
| **AI** | 需求对齐 → 写驱动 → 编译 → 烧录 → 上板验证 → 崩溃归因 → 改代码 → 重来 |
| **本套件** | 把上面每一步变成 AI 能调用的命令，并把结果变成它能判断的结论 |

---

## 效果

你说人话，AI 先问清硬件，再给接线表：

> **你**：我要用 DHT11 读温湿度，串口打印，LED 每秒闪一次。
>
> **AI**：先确认几件事 —— 外部晶振是 8MHz 还是 12MHz？DHT11 数据线接哪个 GPIO？板载 LED 是哪个脚、高电平点亮还是低电平？
>
> ……（确认后）……
>
> **AI**：按下表接线，插好回复"接好了"：
>
> | DHT11 | 开发板 |
> |---|---|
> | VCC | 3V3 ⚠️ 不可接 5V |
> | GND | GND |
> | DATA | PA1（需 4.7kΩ 上拉） |

确认接线完成后，后续全程自动：

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

程序崩溃时不止步于"跑飞了"，而是定位到具体源码行：

```
[-] 板子崩溃了（固件通过串口自报了故障现场）
    根本原因：空指针解引用（NULL Pointer Dereference）：程序访问了 NULL 或接近 0 的地址 0x00000004。
[!] 诊断报告已写入：MDK-ARM\diagnostic_report.json

崩溃点: ../User/dht11.c:88（函数 DHT11_Read）
     86 |     /* dev 未判空 */
>>>  88 |     dev->port->BSRR = dev->pin;
```

---

## 它是怎么做到的

> 这一节讲原理。急着用可以先跳到 [上手](#上手)，但看懂了才知道出问题时该查哪里。

### 三条互相独立的通道

你的电脑和那块 STM32 之间本来是隔绝的。套件靠三条通道把它们连起来：

| 通道 | 物理连接 | 能做什么 |
|---|---|---|
| **编译** | 不需要接线 | 在电脑本地把 C 代码变成机器码 |
| **SWD 调试口** | SWDIO / SWCLK + GND | **直接读写芯片内部**——内存、寄存器、让 CPU 停或跑 |
| **串口 UART** | TX / RX + GND | 芯片主动"说话"，电脑听 |

**SWD 和串口是两套完全不同的东西，这个区别贯穿整个设计：**

- **串口**是芯片**主动**说话，像打电话——它不说，你就听不到
- **SWD** 是电脑**强行**去翻芯片的内脏，像做 CT——**芯片死了照样能查**

### ① 编译：行号是怎么来的

Keil 的 `UV4.exe` 除了双击打开图形界面，还接受命令行参数。套件用的就是这个——让 Keil 在后台编译，不弹窗口，**装完 Keil 就再也不用打开它**。

编译完 Keil 把过程写进日志，套件读那个日志，把错误抠成结构化字段：

```
..\User\dht11.c(88): error:  #20: identifier "dev" is undefined
   ↓
文件 = dht11.c   行号 = 88   错误码 = #20   描述 = identifier "dev" is undefined
```

AI 拿到的不是一坨日志，是"文件 + 行号 + 原因"。这就是它能直接改对地方的原因。

编译产出一个 `.axf` 文件——**后面所有崩溃定位都靠它**，先记住。

### ② 烧录：什么叫"让 CPU 停住"

ARM 芯片内部除了跑你程序的 CPU 核，还焊了一小块**独立的调试电路**。它有自己的供电和时钟，**不依赖 CPU 是否正常**，通过 SWDIO / SWCLK 两根线对外，能直接读写芯片的任意内存地址、CPU 的全部寄存器，以及让 CPU 暂停或继续。

**CPU 就算跑飞了、死循环了、崩溃了，这块电路照样活着。** 这是崩溃归因能成立的物理基础。

烧录的本质就是通过 SWD：让 CPU 停下 → 往 Flash 写入机器码 → 复位。

### ③ 顺序：整个项目最要命的一处

芯片复位后，**几十毫秒内**就把启动信息打完了。而电脑打开串口要花时间（枚举设备、配置波特率）。

所以如果顺序错了：

```
❌ 烧录 → 放行 → 打开串口
          └─ 这几十毫秒里芯片已经说完话，电脑还没开始听
```

**通过令牌永远收不到。** 表现是"代码明明没问题却一直超时"。

正确顺序是：

```
✅ 烧录 → 按住别跑 → 从容打开串口 → 再放行 → 开始听
```

引擎源码开头的注释就一句话：`Ordering is the whole trick.`

### ④ 崩溃：从一个地址到一行代码

**第一步，问芯片"出事时停在哪"。**

Cortex-M 崩溃时硬件会自动把现场压进栈，其中最关键的是 **PC**（程序计数器）——它记着"出事时正在执行哪个地址的指令"。同时几个故障寄存器记下原因：

| 寄存器 | 记什么 |
|---|---|
| **CFSR** | 崩溃分类（除零？访问非法地址？栈溢出？非对齐访问？） |
| **BFAR** | 如果是访问了非法地址，**那个地址是多少** |
| **MMFAR** | 内存保护相关的非法地址 |
| **HFSR** | 硬故障总标志 |

套件通过 SWD 把这些读出来——**此时 CPU 已经死了，但调试电路还活着**。

> ⚠️ 纪律：**BFAR 只在 CFSR 声明它有效时才采信**，否则如实写"故障地址无效"，不猜。

**第二步，把地址翻译成源码行。**

现在手里是个数字，比如 `0x08001A42`。答案在 `.axf` 里——编译器生成机器码时还塞进去一张对照表（DWARF 调试信息）：

```
0x08001A3C ~ 0x08001A48  ←→  dht11.c 第 88 行，函数 DHT11_Read
0x08001A48 ~ 0x08001A50  ←→  dht11.c 第 89 行
```

套件拆开 `.axf` 读出这张表，二分查找，再把源文件对应几行抠出来贴进报告。

> 💡 这就是为什么套件**每次编译前都强制打开"调试信息"开关**——关了，编译器就不塞这张表，崩溃了就只剩一串数字。

**还有一条备用通道**：套件可以往固件里装一个叫 `cm_backtrace_lite` 的小模块，崩溃瞬间由芯片自己通过串口把现场吐出来。两条通道互为备份。

> ⚠️ 极其反直觉的坑：**崩溃处理里绝对不能用 `printf` / `HAL_UART_Transmit`**。它们靠系统滴答计时超时，而 HardFault 优先级比滴答高——滴答进不了中断，计时器永不递增，于是死等，一个字节都吐不出来。必须用最原始的死等发送。

### ⑤ 让它能自动循环的两个约定

**退出码是唯一真理。** 脚本返回一个数字而不是一段话——文字要理解，理解就可能理解错（AI 看到 "Build finished" 就以为成了），数字没有歧义。

**失败指纹。** 每次失败算一个指纹（`dht11.c:88:#20:...`，或 `FAULT|空指针|PC=…|CFSR=…`）。指纹重复出现 = 上次改的东西完全没起作用，该换思路；反复如此就停机交人工，不烧迭代次数。

### 一句话总结

> **把"程序跑得对不对"这件原本只有人能判断的事，变成一个机器可以判断的数字。**

---

## 能做什么，不能做什么

### ✅ 能

- 自动修**编译错误**（带文件名行号）
- 自动定位**崩溃**（到具体源码行 + 根本原因分类）
- 自动判断**有没有真的跑通**（需要串口）
- 自动改 Keil 工程结构（加源文件、加包含路径、加宏、装崩溃追踪器），**全程不用打开 uVision**
- 判断自己是否在原地打转，卡住时主动停机交人工

### ❌ 不能

| 做不到 | 说明 |
|---|---|
| **从零生成工程** | v2.3.0 起已移除。先用任意方式拿到一个能编译的 Keil 工程（CubeMX 导出、开发板例程、教程配套工程都行），再接入 |
| **Mac / Linux** | 核心依赖 Keil MDK，仅 Windows |
| **非 Keil 工具链** | 不支持 IAR、CMake/GCC、PlatformIO |
| **没有调试器也能用** | ST-Link / DAP-Link 是**必需**的，没有就无法烧录，也读不到崩溃现场 |

### ⚠️ 不接串口会怎样

**能查错，但永远无法验收。**

| 环节 | 没串口 |
|---|---|
| 编译 + 错误行号 | ✅ 正常 |
| 烧录、控制 CPU 停跑 | ✅ 正常 |
| **崩溃定位到源码行** | ✅ **正常**（走 SWD，与串口无关） |
| **判定"通过"** | ❌ **永远拿不到**，退出码卡在 4 |

更要紧的是：**大部分 bug 既不是编译错也不是崩溃**——解帧偏一个字节、时钟配错导致延时全偏、I2C 地址写错屏幕不亮、状态机漏了个分支……这些程序都跑得好好的，只是结果不对。**没有串口，AI 对这一整类问题完全看不见**，还会以为一直失败，继续改本来已经写对的代码。

串口只要 3 根线（TX / RX / GND），而且很多板子的 ST-Link 自带虚拟串口、或板载了 CH340。**强烈建议接上。**

---

## 上手

### 第 1 步：确认环境

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
| Keil MDK5 | AC5 / AC6 均支持。**安装后无需再启动其 GUI** |

### 第 2 步：下载并初始化

```bash
git clone https://github.com/TaoCosmo-Dev/STM32_AutoDebug_Universal_Kit.git
cd STM32_AutoDebug_Universal_Kit
```

**双击 `setup_env.bat`**（或 `powershell -ExecutionPolicy Bypass -File setup_env.ps1`）。

它会装依赖、装常用 CMSIS 器件包，自检，最后把 AI 用的 Skill 装进系统：

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

上面三项都有内容即就绪。`NOT FOUND` / 探针为空 / 串口为空，分别对应 Keil 未装、调试器未插或被占用、缺 USB-UART 驱动。

> **不需要改配置文件。** Keil 装在哪个盘、用 ST-Link 还是 DAP-Link、串口是 COM3 还是 COM12，全部自动识别。

### 第 3 步：开始用

**就这样，什么都不用做了。** 用 AI 编辑器打开**任意** Keil 工程，直接描述需求：

```
我要实现：<用自然语言描述功能>
```

AI 会自己加载规范、追问硬件参数、给接线表，然后跑闭环。**不需要注入，不需要开场白。**

> **为什么能这样**：`setup_env` 最后装的那个 Skill 就是入口。`SKILL.md` 是开放标准，Claude Code / Cursor / Codex CLI / Gemini CLI / Cline / Windsurf / Copilot / Zed 都能读，所以一次安装覆盖整套工具链。
>
> 引擎不需要待在你的工程里——它的所有路径都从 `--project` 推导，诊断报告、状态目录、崩溃追踪器都落在**你的工程**里，套件目录不会被污染。

### 可选：把工具链装进工程

只有两种情况需要 —— ① 想把工具链**随工程一起提交 git**，让队友 clone 就能用；② 编辑器还不支持 Agent Skill。

把工程文件夹**拖到 `inject_to_project.bat` 上**：

```
  [+] AGENTS.md（AI 规范）
  [+] run_autodebug.py
  [+] autodebug/ 引擎
  [+] autodebug.config.yaml（本工程配置）
  [+] mcu_support/cm_backtrace_lite.c
  找到 Keil 工程：MDK-ARM\Demo.uvprojx
```

这条路线下，开场白要加一句让 AI 读规范：

```
读一下 AGENTS.md，按里面的规范来。
我要实现：<用自然语言描述功能>
```

---

## 下载下来的文件都是干什么的

> 日常真正会碰的只有两个：`setup_env.bat` 和 `AGENTS.md`。其余要么是 AI 自己调用，要么是备查。

### 你会直接动的

| 文件 | 什么时候用 | 怎么用 |
|---|---|---|
| **`setup_env.bat`** | **第一次安装**；以及**每次更新或移动套件之后** | 双击。装依赖 + 自检 + 安装 Skill |
| **`inject_to_project.bat`** | 只在走"装进工程"路线时 | 把工程文件夹拖上去 |
| `install_skill.py` | 只想单独管理 Skill 时 | `python install_skill.py` 安装/刷新、`--list` 看装在哪、`--uninstall` 卸载 |

> ⚠️ **更新套件或挪了存放位置后，一定要重跑一次 `setup_env.bat`。** Skill 是**复制**到系统目录里的，源文件改了副本不会自动跟着变。开启 Windows 开发者模式后会改用符号链接，就不必再管这件事。

### AI 会调用的

| 文件 | 作用 |
|---|---|
| **`run_autodebug.py`** | **主入口**。编译 / 烧录 / 上板验证 / 崩溃归因全走它，退出码即结论 |
| `mcp_server.py` | 可选。配成 MCP Server 后编辑器可原生调用这些能力（10 个工具） |
| `autodebug/` | 引擎本体：编译、烧录、串口、故障分析、符号解析、报告、工程编辑、总编排 |

### 规范与素材

| 文件 | 作用 |
|---|---|
| **`AGENTS.md`** | ⭐ **AI 开发规范，全项目唯一的规则文件**。闭环流程、退出码契约、需求对齐清单、嵌入式黄金准则都在里面。**想调整 AI 的行为，改这一个文件就够了** |
| `skills/stm32-autodebug/` | Skill 模板。`install_skill.py` 把它装到系统各处；内容是指向 `AGENTS.md` 的**指针**而非副本，所以规范永远只有一份，不会互相不同步 |
| `mcu_support/` | `cm_backtrace_lite.c/.h` —— 跑在**芯片里**的崩溃追踪器。装 tracer 时会被拷进你的工程、编译进固件 |
| `templates/` | 硬件访谈清单与接线指南模板，AI 在需求对齐阶段参考 |
| `docs/ADVANCED.md` | 闭环时序图、完整配置项、MCP 接入、架构说明 |
| `tests/` | 91 项离线自测，不需要硬件：`python -m unittest discover -s tests` |

### AI 常用的命令（一般不用你手敲）

```bash
python run_autodebug.py --project MDK-ARM/App.uvprojx              # 完整闭环
python run_autodebug.py --project MDK-ARM/App.uvprojx --no-flash   # 只编译，不碰硬件
python run_autodebug.py --project MDK-ARM/App.uvprojx --json       # 机器可读输出
python run_autodebug.py --project MDK-ARM/App.uvprojx --check-firmware   # 固件契约自检
python run_autodebug.py --project MDK-ARM/App.uvprojx --add-source User/new.c
python run_autodebug.py --project MDK-ARM/App.uvprojx --install-tracer --uart USART1
python run_autodebug.py --list-devices                             # 列探针与串口
```

---

## 退出码：唯一的判定标准

脚本的退出码就是结论，不看日志措辞：

| 码 | 状态 | 含义 | 该做什么 |
|:---:|---|---|---|
| **0** | `TEST_PASSED` | 编译 0 Error + 烧录成功 + 串口收到通过令牌 | **封版，别再改** |
| 1 | `BUILD_FAILED` | 编译 / 链接错误，报告里带 `文件:行号` | 按报告改源码，重跑 |
| 2 | `FLASH_FAILED` | 探针 / 接线 / 供电 / 读保护 | **不是代码问题**，别改代码 |
| 3 | `HARD_FAULT`·`ASSERTION_FAILED` | 运行时崩溃，已定位到源码行 | 按根因改，重跑 |
| 4 | `TIMEOUT`·`SERIAL_UNAVAILABLE` | 没等到令牌 / 串口打不开 | 查串口重定向、波特率、测试是否真跑到输出点 |
| 5 | `STALLED` | 反复出现同一个失败 | **停止盲改**，说明卡点并请求人工决策 |
| 6 | `CONFIG_ERROR` | 找不到 Keil | 装环境，或在 `autodebug.config.yaml` 写 `keil.uv4_path` |

结构化诊断写在工程根 `diagnostic_report.json`，历史归档在 `.autodebug/`。

---

## 固件侧必须满足的两件事

绝大多数"跑了没反应"不是业务逻辑写错，而是**没让固件开口说话**。工程设置由 AI 用命令完成，但这两件只有写代码的人知道该放哪：

1. **通过令牌**：测试通过的路径上打印 `[ALL TESTS PASSED]`。**不打印它，闭环永远判不了成功。**
2. **`cm_backtrace_init()`**：`main()` 里外设初始化之前调用，开启子异常分类与除零陷阱。

跑 `--check-firmware` 会逐条列出还缺什么；闭环超时时也会自动附上这份清单，并排在诊断报告 `next_actions` 的最前面。

---

<details>
<summary><b>深入：<code>--install-tracer</code> 到底做了什么</b></summary>

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

其中几处设计值得说明：

- **`putchar` 按芯片系列生成**：F1/F2/F4/L1 用 `SR/DR`，其余用 `ISR/TDR`；直接测 TXE 位（bit 7）而不是用宏名，避开 `USART_SR_TXE → USART_ISR_TXE → USART_ISR_TXE_TXFNF` 的改名。
- **CMSIS 头文件按工程实际使用的库选择**：HAL 用 `stm32f1xx.h`，StdPeriph 用 `stm32f10x.h`。依据工程自身的 `USE_STDPERIPH_DRIVER` / `USE_HAL_DRIVER` 宏判断，其次依据磁盘上实际存在的头文件——仅按芯片系列推导，会在所有 StdPeriph 工程里生成无法编译的 tracer。
- **不用 `printf`**：原因见上文原理一节。
- **自动消解 `HardFault_Handler` 冲突**：HAL 模板里那个 `while(1){}` 空实现既会导致重复定义，又正是它把崩溃变成静默死机。这里把它注释掉（原文保留在注释里，可还原），并自动备份。
- **`--uart` 要填应用里已经初始化好的那个串口。**

所有工程改动都**幂等**，首次改动前自动备份为 `*.autodebug.bak`。

</details>

<details>
<summary><b>深入：排错对照表</b></summary>

| 现象 | 原因 | 处理 |
|---|---|---|
| 退出码 6 | Keil 未安装或路径不对 | 装 Keil，或在 `autodebug.config.yaml` 写 `keil.uv4_path` |
| 编译卡住后被 kill | Keil 弹了模态框（缺器件包 / License / 工程被 IDE 占用）| 关掉 uVision，手动打开工程确认无弹窗 |
| 退出码 2，无探针 | 调试器未插，或被 Keil / CubeProgrammer 占用 | `--list-devices` 确认；关掉占用程序 |
| 退出码 2，`target type X not recognized` | **不是硬件问题**，是缺 CMSIS 器件包 | 按报告提示装对应器件包 |
| 退出码 2，连不上目标 | 固件复用了 SWD 引脚，或芯片读保护 | 保持 `connect_mode: under-reset`；RDP1 需整片擦除解锁 |
| 退出码 4，串口零字节 | 串口重定向未实现 / 波特率不符 / COM 被串口助手占用 | 前两项由 AI 修（`--check-firmware` 会点名）；关掉 SSCOM 等占用串口的程序 |
| 退出码 4，有输出无令牌 | 测试没走到输出点 | 先看未满足的固件契约，再看 **CPU 存活遥测**：PC 不变 = 卡在死等循环 |
| 崩溃了但无源码行 | 工程未输出调试信息 | 每次编译前会自动打开；只有手动关了 `auto_fix_debug_info` 才需处理 |
| 报告写"故障地址无效" | imprecise 总线错误（写缓冲延迟） | 在可疑写操作后加 `__DSB()` 缩小范围 |
| 连续几轮同一个错 | 上一次修改没生效 | 报告的 `repeated_failure` 为 true，换思路而不是重复同类改动 |

</details>

<details>
<summary><b>深入：为什么这些设计能跑通</b></summary>

- **烧录后保持内核 halt，开完串口再 resume。** 固件复位后几十毫秒就打印启动横幅，先 resume 再开串口必然丢掉这段——这是"代码明明没问题却一直超时"的根源。
- **如实汇报停机状态。** 兜底烧录路径会复位并让目标运行；此时若谎称"已停住"，后续超时看起来和固件 bug 一模一样，把人引向源码里根本不存在的问题。现在会向目标查询真实状态，并在未停住时于串口就绪后重启目标补抓。
- **产物新鲜度校验。** 只看 `.axf` 存在就烧，可能把上一版固件当成本次修改的验证结果；这里校验 mtime。
- **烧录失败立即中止本轮。** 否则串口读到的是旧固件的行为，诊断报告会把 AI 引向完全错误的方向。
- **BFAR / MMFAR 全链路贯通并按 CFSR 有效位判定。** 有地址才敢说"空指针"，无效时如实写"无效"，不猜。
- **pyOCD 全程 `blocking=False` + 单会话。** 桌上插两个探针不会弹选择菜单卡死。
- **停机检测跨窗口统计。** 只比相邻两轮的话，AI 在两个错误之间来回改（A→B→A→B）永远触发不了刹车。

</details>

---

## 验证

```bash
python -m unittest discover -s tests     # 91 项离线自测，不需要硬件
```

每次 push 与 PR 由 GitHub Actions 在 Windows + Python 3.10 / 3.12 上自动运行，并校验版本号三处一致与徽章用例数。

---

## FAQ

<details>
<summary><b>必须用 Claude Code 吗？</b></summary>

不是。`SKILL.md` 是开放标准，Claude Code / Cursor / Codex CLI / Gemini CLI / Cline / Windsurf / Copilot / Zed 等都能读。即使编辑器完全不支持 Skill，也可以走"装进工程"路线，靠开场白「读一下 AGENTS.md」生效——**任何能读文件 + 能跑终端命令的 AI 都能驱动它**。

</details>

<details>
<summary><b>能不用 MCP，只用命令行吗？</b></summary>

可以，而且这就是默认方式。MCP Server 是可选的进阶用法，不配完全不影响。

</details>

<details>
<summary><b>我的工程是 StdPeriph（江科大 / 正点原子那套），能用吗？</b></summary>

能。套件不关心你用 HAL 还是 StdPeriph——它只跟 `.uvprojx` 和芯片打交道。崩溃追踪器会按工程实际使用的库选择正确的 CMSIS 头文件。

</details>

<details>
<summary><b>会不会把我的工程改坏？</b></summary>

所有工程改动都**幂等**，首次改动前自动备份为 `*.autodebug.bak`。此外每轮 AI 修改前，引擎会用 `git stash create` 打一个**不改动工作区**的还原点（tag `autodebug/iter-NN`），改坏了可以 `git checkout <sha> -- .` 回滚。

</details>

<details>
<summary><b>为什么移除了从零建工程的功能？</b></summary>

它依赖本机装有 STM32Cube_FW 固件包，而 Keil 的器件包只带标准外设库、不含 HAL。在这种很常见的配置下，它会**静默生成一个引用了不存在源文件、必然编译失败的工程**。修好它需要库探测加模板回退，并且每个新芯片系列都要持续适配——而用户几乎总是已经有工程了。详见 [v2.3.0 发布说明](https://github.com/TaoCosmo-Dev/STM32_AutoDebug_Universal_Kit/releases/tag/v2.3.0)。

</details>

---

## License

[MIT](LICENSE) —— 个人、企业均可免费使用、修改、商用。

觉得有用点个 ⭐ Star；问题请提 [Issue](https://github.com/TaoCosmo-Dev/STM32_AutoDebug_Universal_Kit/issues)。
