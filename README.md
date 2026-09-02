# 🚀 STM32 全自动开发套件

### 你说人话，AI 写代码、编译、烧录、上板调试，全自动

[![GitHub Release](https://img.shields.io/badge/Release-v2.0.0-blue?style=flat-square&logo=github)](https://github.com/TaoCosmo-Dev/STM32_AutoDebug_Universal_Kit/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg?style=flat-square)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-STM32%20%7C%20Cortex--M-orange?style=flat-square)]()
[![Tests](https://img.shields.io/badge/自测-31%20项通过-brightgreen?style=flat-square)]()

> **不用会写 C 语言，不用会用 Keil，不用懂寄存器。**
> 你只需要做三件事：**双击一个 bat → 拖一个文件夹 → 跟 AI 说你想做什么。**
> 剩下的写代码、编译、烧进板子、板子死机了自己查原因再改，全是 AI 干。

---

## 🎬 先看它长什么样

你在 AI 编辑器里打一句话：

> **你**：我想让开发板上的灯每秒闪一次，然后串口打印温度。

AI 不会立刻写代码，它会**先反问你几个硬件问题**（晶振多少 MHz、用哪几个引脚、温度传感器什么型号……），
你答完，它给你一张**接线表**：

> **AI**：请按下表插杜邦线，插好回复"接好了"：
> | 传感器引脚 | 接开发板 |
> |---|---|
> | VCC | 3V3 |
> | GND | GND |
> | SDA | PB7 |
> | SCL | PB6 |
> ⚠️ 注意：这个传感器**不能接 5V**，会烧。

你插好线，回一句"接好了"。然后 AI 就自己开始转了：

```
>>> [第 1 轮] 步骤 1/4  正在用 Keil 编译 ...
[+] 编译通过  0 Error，0 Warning，耗时 12.3s

>>> [第 1 轮] 步骤 2/4  正在烧录到板子（烧完先让 CPU 停住不跑）...
[+] 烧录成功（下载器 0670FF..., 芯片 stm32f103c8），CPU 已停在复位入口等待放行。

>>> [第 1 轮] 步骤 3/4  先打开串口监听，再放 CPU 运行 ...
[+] 已监听串口 COM6 @ 115200
  [MCU] system clock 72MHz ready
  [MCU] temp = 26.4 C
  [MCU] [ALL TESTS PASSED]

>>> [第 1 轮] 步骤 4/4  判定结果并分析根本原因 ...
[+] 实机测试通过！（收到通过信号：[ALL TESTS PASSED]）

  [AUTODEBUG PASS] 编译 + 烧录 + 实机验收 全部通过
```

**如果板子死机了**，AI 也不会问你"是不是没接好"，它会直接告诉你死在哪一行：

```
[-] 板子崩溃了（固件通过串口自报了故障现场）
    根本原因：空指针解引用（NULL Pointer Dereference）：程序访问了 NULL 或接近 0 的地址 0x00000004。
[!] 诊断报告已写入：MDK-ARM\diagnostic_report.json

>>> [第 2 轮] AI 正在自动修复代码 ...
```

报告里还会直接贴出出错的那几行代码：

```
崩溃点: ../User/dht11.c:88（函数 DHT11_Read）
     86 |     if (dev->port == NULL) {
>>>  88 |     dev->port->BSRR = dev->pin;
```

然后它自己改完代码，重新编译烧录，直到跑通为止。

---

## 🧰 第一步：准备东西

### 要买的（可能你已经有了）

| 东西 | 说明 | 参考价 |
|---|---|---|
| **STM32 开发板** | 任意型号都行（正点原子 / 野火 / 立创 / 最小系统板） | 30~150 元 |
| **下载器** | ST-Link V2 或 DAP-Link / CMSIS-DAP，**必须有**，这是 AI 往板子里写程序的通道 | 20~60 元 |
| **USB 线** | 给板子供电 + 传数据 | — |
| **杜邦线** | 接传感器用，母对母 / 公对母各来一把 | 10 元 |
| **USB 转 TTL 串口模块**（CH340） | ⚠️ **很多板子已经自带**，先看板子上有没有写 CH340；没有才买 | 10 元 |

> **为什么必须要下载器？** 没有它，AI 写好的程序进不去板子，闭环就断了。
> 板子上如果有 4 个针脚写着 `SWDIO / SWCLK / GND / 3V3`，把下载器对应插上就行。

### 要装的软件（三个）

| 软件 | 干什么用 | 怎么装 |
|---|---|---|
| **Python 3.10 以上** | 跑本套件的自动化脚本 | [python.org/downloads](https://www.python.org/downloads/) ——⚠️ **安装时一定要勾选 `Add python.exe to PATH`**，这个框不勾后面全白装 |
| **Keil MDK5** | 编译 STM32 程序的官方工具 | 百度 "Keil MDK5 安装" 照做即可，装完打开一次确认没弹窗 |
| **AI 编辑器** | 你跟 AI 对话的地方 | [Claude Code](https://claude.com/claude-code)（推荐）或 [Cursor](https://cursor.com)，二选一 |

---

## 🚀 第二步：装好这个套件（双击一次，30 秒）

1. 点这个仓库右上角绿色的 **`Code` → `Download ZIP`**，解压到桌面
   （会 git 的话：`git clone https://github.com/TaoCosmo-Dev/STM32_AutoDebug_Universal_Kit.git`）

2. 进到文件夹，**双击 `setup_env.bat`**

3. 等它跑完。看到这样就成功了：

```
[4/4] 自检：工具链 / 探针 / 串口 / 离线单元测试

  Keil UV4   : C:\Keil_v5\UV4\UV4.exe
下载器（调试探针）：
  - STM32 STLink  [050051000E00004D43504D4E]

串口：
  - COM6 - USB-SERIAL CH340 (COM6)

  [READY] 这台电脑已具备 编译 / 烧录 / 自愈调试 能力
```

**对照检查这三行：**

| 这行显示 | 说明 | 不对怎么办 |
|---|---|---|
| `Keil UV4 : ...` 有路径 | ✅ 找到 Keil 了 | 显示 `NOT FOUND` → Keil 没装好，重装一次 |
| `下载器（调试探针）：` 下面有东西 | ✅ 认到下载器了 | 显示"未检测到"→ 下载器没插，或换个 USB 口 |
| `串口：` 下面有 COM 口 | ✅ 认到串口了 | 空的 → 板子没插 USB，或缺 CH340 驱动（百度"CH340 驱动"装一下）|

> 💡 **不用改任何配置文件。** Keil 装在 C 盘还是 D 盘、下载器是 ST-Link 还是 DAP-Link、
> 串口是 COM3 还是 COM12，全部自动认。

---

## 🎯 第三步：接入你的工程

### 情况 A：你已经有一个 Keil 工程

**把工程文件夹直接拖到 `inject_to_project.bat` 上**（拖到图标上松手），一秒完成。

### 情况 B：你什么都没有，就想从零做一个

选一条最省事的路：

| 路子 | 怎么做 | 适合谁 |
|---|---|---|
| **抄板子自带例程**（最推荐） | 买板子时商家给的资料里有一堆例程，随便复制一个"点灯"或"串口"例程文件夹出来，拖到 `inject_to_project.bat` | 所有小白 |
| **让 AI 帮你生成** | 装个 [STM32CubeMX](https://www.st.com/en/development-tools/stm32cubemx.html)，跟 AI 说"我的芯片是 STM32F103C8T6，教我用 CubeMX 生成一个 Keil 工程"，它会一步步带你点 | 想学的人 |
| **网上找模板** | GitHub 搜 `STM32F103 HAL template` 之类 | 会翻资料的人 |

> **为什么需要一个"工程"？** Keil 需要一个工程文件（`.uvprojx`）才知道你的芯片型号、
> 时钟怎么配、哪些代码文件要一起编译。它就像一个"项目档案袋"。有了它，AI 才有地方写代码。

拖完你会看到：

```
  [+] AGENTS.md（AI 规范）
  [+] .cursorrules（Cursor / Windsurf 用）
  [+] CLAUDE.md（Claude Code 会自动读）
  [+] run_autodebug.py
  [+] autodebug/ 引擎
  [+] autodebug.config.yaml（本工程配置）
  [+] mcu_support/cm_backtrace_lite.c
  找到 Keil 工程：MDK-ARM\Demo.uvprojx

[完成] 注入成功！用你的 AI 编辑器打开 D:\MyProject
```

---

## 💬 第四步：跟 AI 说话（这才是重点）

用 Claude Code 或 Cursor **打开你刚才那个工程文件夹**，然后**直接说人话**。

### 开场白（复制粘贴就行）

```
读一下 AGENTS.md，按里面的规范来。
我想做：<在这里用大白话写你想要什么>
```

比如：

```
读一下 AGENTS.md，按里面的规范来。
我想做：板子上的 LED 每 500 毫秒闪一次，同时用串口每秒打印一次运行时间。
```

### 接下来会发生什么

| 阶段 | AI 做什么 | **你做什么** |
|---|---|---|
| 1️⃣ 问清楚 | 反问你 5 类硬件问题（晶振频率、用哪些引脚、传感器型号……） | **老实回答**，不知道就说"不知道，帮我查/你决定" |
| 2️⃣ 给方案 | 输出技术方案 + 引脚对照表 | 看一眼，说"可以" |
| 3️⃣ 给接线图 | 一张表告诉你哪根线插哪 | **照着插杜邦线**，插好回"接好了" |
| 4️⃣ 全自动 | 写代码 → 编译 → 烧录 → 上板跑 → 崩了自己查自己改 | **喝水等着** |
| 5️⃣ 交付 | 报告"通过了" | 看板子上的灯 |

> ⚠️ **第 3 步是全流程唯一需要你动手的地方。** 插线前先**断开 USB 断电**，插完再上电。

---

## ✅ 怎么知道成功了？

看 AI 最后一句话里有没有这个：

```
[AUTODEBUG PASS] 编译 + 烧录 + 实机验收 全部通过
```

**注意：这不是 AI 自己吹的。** 这句话只有在同时满足三个条件时才会出现：

1. Keil 编译 **0 个错误**
2. 程序**真的写进了板子**
3. 板子**真的通过串口吐出了通过信号**

只要有一条不满足，脚本会报失败并说明原因，AI 不能"假装成功"糊弄你。
这是本套件和"AI 随便写写说好了"最大的区别。

---

## 🩺 出问题了怎么办

**你不需要看懂任何报错。把现象告诉 AI 就行**——它能看到完整的诊断报告。

| 你看到的现象 | 复制这句话给 AI |
|---|---|
| 报错说找不到 Keil | `setup_env 说找不到 Keil UV4，帮我确认 Keil 装在哪、怎么修` |
| 报错提到 probe / 探针 | `烧录失败说没找到下载器，帮我排查接线和驱动` |
| 说串口没数据 / 超时 | `串口一直没输出，帮我检查串口重定向和波特率` |
| 板子崩溃 / HardFault | `板子崩溃了，读一下 diagnostic_report.json，按报告修` |
| AI 改了好几轮都一样 | `连续几轮都是同一个错，别再重复改了，换个思路，或者告诉我需要我做什么` |
| 完全不知道咋回事 | `跑一下 python run_autodebug.py --list-devices，看看电脑认到了什么` |

### 最常见的 5 个坑

| 坑 | 表现 | 解决 |
|---|---|---|
| Python 装的时候没勾 PATH | 双击 bat 闪一下就没了 | 卸载 Python 重装，**勾上 `Add python.exe to PATH`** |
| Keil 还开着 | 编译卡住不动 | **关掉 Keil 软件**再跑（同一个工程不能被两边同时占用）|
| 下载器被别的软件占了 | 说连不上板子 | 关掉 Keil、STM32CubeProgrammer、串口助手 |
| 串口被串口助手占了 | 说串口打不开 | 关掉 SSCOM / 串口调试助手 / PuTTY |
| 板子没供电 | 什么都认不到 | USB 插紧，换个 USB 口，别用劣质线 |

---

## 🧠 它到底帮你干了什么？（好奇再看）

AI 自己不会用 Keil、不会插下载器、也看不见板子。本套件就是给它装的"手和眼睛"：

| 能力 | 大白话 |
|---|---|
| **手：编译** | 帮 AI 按下 Keil 的编译按钮，把报错整理成"第几个文件第几行错了" |
| **手：烧录** | 帮 AI 把程序写进板子。有两个下载器插着也不会弹窗卡住 |
| **眼：串口** | 帮 AI 盯着串口。**关键细节**：程序烧完先把 CPU 摁住不让跑，等串口监听好了才放开——不然板子开机那几十毫秒打印的东西就丢了，AI 会以为程序没跑起来 |
| **眼：读芯片** | 板子死机后，直接读 CPU 里的故障寄存器，翻译成"空指针，出错地址 0x00000004" |
| **脑：定位到行** | 拿故障地址反查编译产物，直接指出"错在 dht11.c 第 88 行"，并把那几行代码贴出来 |
| **刹车：防乱改** | 每轮改代码前自动存档（可回退）；连续两轮同一个错就停下来叫人，不会越改越乱 |

---

## 📁 文件都是干嘛的

```
STM32_AutoDebug_Universal_Kit/
├── setup_env.bat          ← 【双击这个】装环境
├── inject_to_project.bat  ← 【拖工程到这个】接入你的项目
├── README.md              ← 你正在看的
├── AGENTS.md              ← 给 AI 看的规范（你不用看）
├── docs/ADVANCED.md       ← 工程师向：架构、配置、退出码、排错细节
├── run_autodebug.py       ← AI 会自己调用，你不用管
├── mcp_server.py          ← 进阶：让 AI 编辑器原生调用本工具
├── autodebug/             ← 引擎源码
├── mcu_support/           ← 让板子崩溃时能"自报家门"的 C 代码
├── templates/             ← 硬件访谈 & 接线指南模板
└── tests/                 ← 31 个自测（不用管）
```

---

## 🔧 想深入了解？

- **[docs/ADVANCED.md](docs/ADVANCED.md)** —— 完整闭环时序、退出码契约、全部配置项、
  MCP 接入、`cm_backtrace` 崩溃追踪器接线、排错速查表、v2.0 修复清单

- **想让 AI 编辑器原生调用（不用打命令）**：见 ADVANCED 里的 MCP 配置，一段 JSON 搞定

- **想验证这套东西靠不靠谱**：`python -m unittest discover -s tests -v`
  31 个测试全绿，不需要板子也不需要 Keil

---

## 🙋 常见疑问

<details>
<summary><b>我一行代码都不会写，真的能用吗？</b></summary>

能。你负责的是「说清楚想要什么」和「照着表插线」，这两件事不需要编程知识。
代码、编译、烧录、调试全是 AI 干。但你需要有耐心回答它的硬件提问——
那些问题（晶振多少 MHz、传感器什么型号）答案都在你买板子/模块时商家给的资料里。
</details>

<details>
<summary><b>为什么 AI 要问我这么多问题，不能直接写吗？</b></summary>

因为嵌入式不同于写网页：晶振频率填错 → 板子直接超频死机；引脚选错 → 和板载芯片打架。
这些参数**没法靠猜**，猜错了后面几个小时全白费。先问清楚是最省时间的做法。
</details>

<details>
<summary><b>支持哪些 STM32 型号？</b></summary>

Cortex-M 内核的都支持：F0 / F1 / F3 / F4 / F7 / G0 / G4 / H7 / L0 / L4 / C0 等。
芯片型号从你的 Keil 工程里自动读，不用手填。
</details>

<details>
<summary><b>没有下载器，只用 USB 行不行？</b></summary>

不行。没有下载器，程序进不去板子，闭环的"烧录"这一环就断了。
ST-Link V2 二十几块钱，是这套流程的必需品。
</details>

<details>
<summary><b>它会不会把我的代码改坏？</b></summary>

每轮自动修改前会用 git 打一个还原点（不改动你的工作区、不产生提交），改坏了能退回去。
而且连续两轮出现完全相同的失败时会自动停下来交给人，不会无限乱改。
</details>

<details>
<summary><b>Mac / Linux 能用吗？</b></summary>

暂时不行。核心依赖 Keil MDK，而 Keil 只有 Windows 版。
</details>

---

## 📄 开源许可

[MIT](LICENSE) —— 个人、企业均可免费使用、修改、商用。

觉得有用的话，点个 ⭐ Star 支持一下。遇到问题欢迎提 [Issue](https://github.com/TaoCosmo-Dev/STM32_AutoDebug_Universal_Kit/issues)。
