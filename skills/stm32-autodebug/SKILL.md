---
name: stm32-autodebug
description: 在 Keil MDK 工程上编译、烧录 STM32 固件并在实机上验证，或把 HardFault、死机、串口无输出定位到源码行。用于改完固件需要上板验证、板子运行异常需要定位、或要新建 STM32F103C8 工程时。仅限 STM32 / Cortex-M + Keil MDK（Windows）。
---

# STM32 全自动调试套件

给 AI 补上嵌入式开发缺失的反馈回路：编译错误行号、烧录成败、实机串口输出、HardFault 寄存器级归因、崩溃地址反查源码行。

**套件安装位置**：`{{KIT_DIR}}`

---

## 详细说明在哪

本文件只负责「怎么调用」。细节在 `AGENTS.md`：工程根目录有注入的那份就用它，否则用 `{{KIT_DIR}}/AGENTS.md`。按需查：

| 需要什么 | 看哪里 |
|---|---|
| 退出码含义、诊断报告字段 | AGENTS.md §0、§1 |
| 硬件参数缺失时问什么 | AGENTS.md §2 |
| 加源文件 / 包含路径 / 宏、启用 HAL 外设、装崩溃追踪器、固件里要写的两件事 | AGENTS.md §3 |
| AC5 中文字符串、测时间的方法等坑 | AGENTS.md §4 |

---

## 判断工程状态

```bash
ls *.uvprojx MDK-ARM/*.uvprojx run_autodebug.py 2>/dev/null
```

| 情况 | 怎么做 |
|---|---|
| 有 `.uvprojx`，**没有** `run_autodebug.py` | **免注入模式**（推荐）。直接用套件绝对路径调用，见下 |
| 有 `.uvprojx`，**也有** `run_autodebug.py` | 套件已注入。用工程内的相对路径调用即可 |
| 连 `.uvprojx` 都没有，芯片是 STM32F103C8(T6) | 下载模板工程，解压即用（命令见下）。默认用 **HAL 版**；用户明确说用标准库时才用标准库版。库、CMSIS、崩溃追踪器都已就位 |
| 连 `.uvprojx` 都没有，其他芯片 | **本套件不生成工程**。告诉用户先拿到一个能编译的 Keil 工程（CubeMX 导出 / 开发板例程 / 教程配套工程均可），再回来接入 |

```bash
# HAL 版（默认）：得到 STM32F103C8_HAL_Template/，工程在其 MDK-ARM/Template.uvprojx
curl.exe -L -o template.zip https://github.com/TaoCosmo-Dev/STM32_AutoDebug_Universal_Kit/releases/download/template-f103c8-hal-v1.1/STM32F103C8_HAL_Template.zip
# 标准库版：把上面的地址换成
#   .../releases/download/template-f103c8-v1.0/STM32F103C8_StdPeriph_Template.zip
python -m zipfile -e template.zip .
```

解压用 `python -m zipfile`：任何终端都能用。Git Bash 里的 `tar` 是 GNU tar，不认 zip。

HAL 版的代码只能写在 `USER CODE BEGIN/END` 区块内，否则用户用 CubeMX 重新生成时会被覆盖。
要用模板里还没启用的外设（ADC、I2C…）时，运行 `--enable-hal adc i2c`，不要手动改 hal_conf.h 和工程文件。

> 不要自己手写 `.uvprojx`。手写工程是首次接入最大的耗时来源，而且出错时不受退出码契约保护。

---

## 调用

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

## 什么算完成

退出码 0：编译通过、烧录成功、实机串口打印出通过令牌。闭环只作用于用户接好的这块开发板，可以直接反复运行、修复本次改动引起的失败后重跑，不用每步征求同意。

失败时读 `.uvprojx` 所在目录（CubeMX 工程是 `MDK-ARM/`）的 `diagnostic_report.json`，字段含义见 AGENTS.md §0–§1。

---

## 常用命令

```bash
# 把下面的 KIT 换成 {{KIT_DIR}}，或在已注入的工程里直接用 run_autodebug.py
python "KIT/run_autodebug.py" --project MDK-ARM/App.uvprojx              # 完整闭环
python "KIT/run_autodebug.py" --project MDK-ARM/App.uvprojx --json       # 机器可读
python "KIT/run_autodebug.py" --project MDK-ARM/App.uvprojx --no-flash   # 只编译
python "KIT/run_autodebug.py" --project MDK-ARM/App.uvprojx --check-firmware   # 固件契约自检
python "KIT/run_autodebug.py" --project MDK-ARM/App.uvprojx --add-source User/new.c
python "KIT/run_autodebug.py" --project MDK-ARM/App.uvprojx --enable-hal adc i2c   # HAL 启用新外设
python "KIT/run_autodebug.py" --project MDK-ARM/App.uvprojx --install-tracer --uart USART1
python "KIT/run_autodebug.py" --list-devices                             # 列探针与串口
```

环境没就绪（缺 Keil / 探针 / 串口）时，让用户跑 `{{KIT_DIR}}/setup_env.bat` 自检。

---

## 补充资料（按需读，不用预加载）

- `{{KIT_DIR}}/AGENTS.md` —— 退出码、报告字段、工程命令、踩坑清单
- `{{KIT_DIR}}/README.md` —— 总览、安装、排错对照表
- `{{KIT_DIR}}/docs/ADVANCED.md` —— 闭环时序、完整配置项、MCP Server 接入、架构
