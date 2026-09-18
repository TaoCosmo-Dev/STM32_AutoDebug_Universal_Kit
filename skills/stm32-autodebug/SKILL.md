---
name: stm32-autodebug
description: STM32 / Cortex-M 固件的编译、烧录、上板验证与崩溃归因闭环。当任务涉及以下任一情况时使用：改动或新建 STM32 固件源码（main.c、驱动、HAL 代码）；Keil MDK 工程（.uvprojx）；要求编译、烧录、下载、上板跑、验证固件；板子出现 HardFault、跑飞、死机、复位、串口无输出、卡死；要从零创建 STM32 工程；或工作目录下存在 run_autodebug.py / autodebug.config.yaml / autodebug/ 目录。也用于用户点名"自动调试套件""AutoDebug""闭环调试"时。仅适用于 STM32 / Cortex-M + Keil MDK（Windows），不适用于 ESP32、Arduino、树莓派等其它平台。
---

# STM32 全自动调试套件

给 AI 补上嵌入式开发缺失的反馈回路：编译错误行号、烧录成败、实机串口输出、HardFault 寄存器级归因、崩溃地址反查源码行。

**套件安装位置**：`{{KIT_DIR}}`

---

## 第一步（必做）：读规范

**本 skill 只是入口，不是规范本身。** 完整规范在 `AGENTS.md`，读它，按它执行：

| 情况 | 读哪个 AGENTS.md |
|---|---|
| 当前工程根目录有 `AGENTS.md`（套件注入过）| **读工程里那份**，它优先 |
| 没有（免注入模式，常态）| 读 `{{KIT_DIR}}/AGENTS.md` |

> 规范只有 `AGENTS.md` 一份，这是本套件的刻意设计——同一份内容散成多份只会互相不同步。
> 所以本文件不复述规则，只负责「什么时候该用」和「怎么调用」。

---

## 第二步：判断工程状态

```bash
ls *.uvprojx MDK-ARM/*.uvprojx run_autodebug.py 2>/dev/null
```

| 情况 | 怎么做 |
|---|---|
| 有 `.uvprojx`，**没有** `run_autodebug.py` | **免注入模式**（推荐）。直接用套件绝对路径调用，见下 |
| 有 `.uvprojx`，**也有** `run_autodebug.py` | 套件已注入。用工程内的相对路径调用即可 |
| 连 `.uvprojx` 都没有 | **本套件不生成工程**。告诉用户先拿到一个能编译的 Keil 工程（CubeMX 导出 / 开发板例程 / 教程配套工程均可），再回来接入 |

---

## 第三步：调用

**免注入模式**（工程里没有 `run_autodebug.py` 时）——用套件的绝对路径，`--project` 指向目标工程：

```bash
python "{{KIT_DIR}}/run_autodebug.py" --project "MDK-ARM/App.uvprojx"
```

> 💡 路径一律用**正斜杠** `/`，Windows 的 cmd / PowerShell / Git Bash / Python 全都接受，
> 而反斜杠一旦被放进 Python 或 JSON 字符串就会被当成转义符。**路径含空格时必须带引号。**

引擎的所有路径都从 `--project` 推导：诊断报告、`.autodebug/` 状态目录、`mcu_support/` 拷贝目标都会落在**目标工程**里，套件目录不会被污染。配置走 `显式 --config > 工程内 autodebug.config.yaml > 套件内置默认` 的回退链，**不需要每个工程放配置文件**。

**已注入模式**：

```bash
python run_autodebug.py --project "MDK-ARM/App.uvprojx"
```

---

## 核心契约（细节一律以 AGENTS.md 为准）

三条最容易被违反的，先记住：

1. **退出码是唯一真理。** 严禁凭日志文字判断成败。只有「编译 0 Error + 烧录成功 + 实机串口吐出通过令牌」三者同时成立才返回 0。退出码含义表在 `AGENTS.md` 第 0 节。
2. **改完 STM32 源码不许直接收工**，必须跑完闭环再回话；不要自己拼编译/烧录命令绕过脚本（它内部「先 halt 再开串口后 resume」的顺序是有讲究的）。
3. **谋定而后动。** 新项目 / 新外设先追问 5 类硬件参数（时钟树、引脚冲突、外设指标、驱动模式、系统框架），用户确认后才编码。清单在 `AGENTS.md` 第 2 节。

拿到非 0 退出码：读工程根目录 `diagnostic_report.json` 的 `ai_repair_prompt` 与 `next_actions` → 只改与根因直接相关的文件 → 重跑。若 `repeated_failure: true`，说明上次修改没生效，**换思路，别重复同类改动**。

---

## 常用命令

```bash
# 把下面的 KIT 换成 {{KIT_DIR}}，或在已注入的工程里直接用 run_autodebug.py
python "KIT/run_autodebug.py" --project MDK-ARM/App.uvprojx              # 完整闭环
python "KIT/run_autodebug.py" --project MDK-ARM/App.uvprojx --json       # 机器可读
python "KIT/run_autodebug.py" --project MDK-ARM/App.uvprojx --no-flash   # 只编译
python "KIT/run_autodebug.py" --project MDK-ARM/App.uvprojx --check-firmware   # 固件契约自检
python "KIT/run_autodebug.py" --project MDK-ARM/App.uvprojx --add-source User/new.c
python "KIT/run_autodebug.py" --project MDK-ARM/App.uvprojx --install-tracer --uart USART1
python "KIT/run_autodebug.py" --list-devices                             # 列探针与串口
```

环境没就绪（缺 Keil / 探针 / 串口）时，让用户跑 `{{KIT_DIR}}/setup_env.bat` 自检。

---

## 补充资料（按需读，不用预加载）

- `{{KIT_DIR}}/AGENTS.md` —— **权威规范**，第一步就该读
- `{{KIT_DIR}}/README.md` —— 总览、安装、排错对照表
- `{{KIT_DIR}}/docs/ADVANCED.md` —— 闭环时序、完整配置项、MCP Server 接入、架构
