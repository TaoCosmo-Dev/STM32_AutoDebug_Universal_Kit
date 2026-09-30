# AGENTS.md — STM32 固件自主编程・烧录・自愈调试规范

> 适用于任何能读文件、能跑终端命令的 AI Agent。
> 内容是这个工具的用法，以及几条只有踩过坑才知道的事实；怎么设计、怎么实现由你判断。

---

## 0. 退出码

成败以退出码为准，而不是日志里的文字（日志可能混着上一轮的输出）。脚本只有在「编译 0 Error + 烧录成功 + 实机串口输出通过令牌」三件事同时成立时才返回 0。

```bash
python run_autodebug.py --project "MDK-ARM/YourProject.uvprojx"
echo $?    # PowerShell: $LASTEXITCODE
```

| 退出码 | 状态 | 含义 | 你该做什么 |
|---|---|---|---|
| 0 | `TEST_PASSED` | 编译 + 烧录 + 实机验收全通过 | 封版交付，不要再改 |
| 1 | `BUILD_FAILED` | 编译 / 链接错误 | 按报告改源码，重跑 |
| 2 | `FLASH_FAILED` | 探针、接线、供电、读保护问题 | **这不是代码问题**，把接线/供电排查项交给用户，别改代码 |
| 3 | `HARD_FAULT` / `ASSERTION_FAILED` / `TIMEBASE_SKEW` | 运行时崩溃已定位到源码行；或测试通过了但时基实测不对（如 SysTick 慢 8 倍） | 按根因改源码，重跑 |
| 4 | `TIMEOUT` / `SERIAL_UNAVAILABLE` | 没等到通过令牌 / 串口打不开 | 签名是 `TIMEOUT\|no bytes`（一个字节都没收到）时**先查接线与串口链路**；否则检查串口重定向、波特率、测试是否真的跑到输出点 |
| 5 | `STALLED` | 改了代码，失败却和之前完全相同 | 停下来，向用户说明卡点，由用户决定下一步 |
| 6 | `CONFIG_ERROR` | 找不到 Keil 等工具链 | 提示用户装环境或改 `autodebug.config.yaml` |

结构化诊断写在 **`.uvprojx` 所在目录**的 `diagnostic_report.json`，历史与状态在同目录的 `.autodebug/`
（CubeMX 工程里就是 `MDK-ARM/`，不是它的上一级）。失败时日志会打印这两个路径。需要机器可读输出时加 `--json`。

---

## 1. 核心闭环流程（Autonomous Closed Loop）

改完固件后用闭环验证。**完成的标准是退出码 0**：编译通过、烧录成功、实机串口打印出通过令牌。

```bash
python run_autodebug.py --project "MDK-ARM/YourProject.uvprojx"
```

闭环只作用于用户接好的这块开发板：可以直接反复运行，修复本次改动引起的失败后重跑，不用每一步都征求同意。

用脚本而不是自己拼编译 / 烧录命令，它内部的顺序是刻意安排的：

```
编译 → 校验产物是本次新生成的 → 打开探针 → 清除上一轮故障位
     → 烧录并让内核保持 halt → 打开串口 → 再 resume → 抓取判定令牌
     → UART 崩溃自述优先，其次 SWD 读 SCB → 定位源码行 → 出报告
```

> 为什么先 halt 再开串口：固件复位后几十毫秒内就会打印启动横幅，先 resume 再开串口必然丢掉这段，通过令牌永远抓不到。

失败时，`diagnostic_report.json` 的 `ai_repair_prompt` 与 `next_actions` 给出根因与建议。其中两个字段：
- `repeated_failure: true`：和上一轮的失败完全相同，上一次的修改没有起作用。
- `source_unchanged: true`：源码一行没改、失败却和上次相同——根因在接线、探针、串口链路、供电或芯片支持包，不在代码。

每轮 AI 修改前，脚本会用 `git stash create` + tag 打一个**不改动工作区**的还原点（`autodebug/iter-NN`），改坏了可以 `git checkout <sha> -- .` 回滚。

---

## 2. 硬件参数

晶振频率、引脚是否被板载器件占用、传感器地址与量程这类参数，猜错了编译照样通过，只有上板才暴露。
缺少且会影响正确性的，先问用户；已知的或无关的不用问。常见项的清单见 `templates/grill_me_hardware_checklist.md`，
需要给用户接线说明时可参考 `templates/wiring_guide_template.md`。

---

## 3. 工程结构用命令改

加源文件、改包含路径与宏、启用外设、装崩溃追踪器都有对应命令，直接用即可，不需要用户打开 Keil。

### 3.0 还没有工程时

本套件不生成工程，也**不要自己手写 `.uvprojx`**，那是首次接入最大的耗时来源。

- 芯片是 STM32F103C8(T6)：下载模板工程，解压即用。库、CMSIS、崩溃追踪器、通过令牌都已就位。
  默认用 **HAL 版**（CubeMX 生成，带 `Template.ioc`）；用户明确说用标准库时才用标准库版：

  ```bash
  curl.exe -L -o template.zip https://github.com/TaoCosmo-Dev/STM32_AutoDebug_Universal_Kit/releases/download/template-f103c8-hal-v1.1/STM32F103C8_HAL_Template.zip
  # 标准库版：.../releases/download/template-f103c8-v1.0/STM32F103C8_StdPeriph_Template.zip
  python -m zipfile -e template.zip .
  ```

  解压用 `python -m zipfile`：任何终端都能用。Git Bash 里的 `tar` 是 GNU tar，不认 zip。

  HAL 工程里你写的代码必须放在 `/* USER CODE BEGIN ... */` 与 `/* USER CODE END ... */` 之间，
  否则用户用 CubeMX 重新生成时会被覆盖。

- 其他芯片：请用户提供一个能编译的 Keil 工程（CubeMX 导出 / 开发板例程均可）。

### 3.1 新建源文件后必须注册到工程

你写的 `.c` 在加入 `.uvprojx` 之前对链接器不存在，必然报 `L6218E: Undefined symbol`：

```bash
python run_autodebug.py --project MDK-ARM/App.uvprojx --add-source User/dht11.c --add-include User
```

| 需要 | 命令 |
|---|---|
| 加源文件 | `--add-source a.c b.c`（可加 `--group 组名`） |
| 加包含路径 | `--add-include Drivers/Inc` |
| 加宏定义 | `--add-define USE_FULL_ASSERT` |
| HAL 工程用上新外设 | `--enable-hal adc i2c`：一次完成「打开 hal_conf.h 里的模块宏 + 补驱动文件 + 注册进工程」 |

以上均**幂等**，重复执行不会重复添加；同一个参数可以写多次（`--add-include A --add-include B`），都会生效；
执行后会回显当前完整的包含路径 / 宏定义列表，核对一眼。首次改动会自动备份 `*.uvprojx.autodebug.bak`。

编译报 `cannot open source input file "stm32f1xx_hal_adc.h"`、`ADC_HandleTypeDef is undefined`、
`Undefined symbol HAL_ADC_Init` 这类错误，就是缺 HAL 模块，报告会直接给出对应的 `--enable-hal` 命令。
驱动文件先从工程里找，再从本机 CubeMX 仓库（`%USERPROFILE%\STM32Cube\Repository`）按 `.ioc` 记录的版本拷。
工程带 `.ioc` 的，长期要用的外设最好也在 CubeMX 里启用，否则下次重新生成会被还原。
调试信息（Debug Information）在每次编译前自动打开，无需处理。

### 3.2 崩溃追踪器一条命令装好

```bash
python run_autodebug.py --project MDK-ARM/App.uvprojx --install-tracer --uart USART1
```

它会自动完成：拷入 `cm_backtrace_lite.{c,h}` → 按芯片系列生成阻塞式 `cm_backtrace_putchar`
（F1/F2/F4/L1 用 `SR/DR`，其余用 `ISR/TDR`，直接测 TXE 位避开宏改名）→ 注册进 Keil 工程与包含路径
→ 注释掉 `stm32xxxx_it.c` 里那个吞掉崩溃的空 `HardFault_Handler`。

`--uart` 填应用里已经初始化好、并且连到电脑的那个串口（不确定就问用户）。芯片系列自动从 `.uvprojx` 推导。

> 故障处理里不要用 `printf` / `HAL_UART_Transmit`：它们的超时依赖 SysTick，
> 而 HardFault 优先级 -1 时 SysTick 进不了中断，tick 永不递增，会在吐出第一个字节前死锁。

### 3.3 需要写进代码里的两件事

命令能做的都做完了，剩下这两件只有你知道该写在哪：

1. **通过令牌**：测试通过路径上打印 `[ALL TESTS PASSED]`（或 `TESTS_PASSED` / `[PASS]`）。
   不打印它，闭环永远判不了成功。
2. **`cm_backtrace_init()`**：`main()` 里外设初始化之前调用，开启子异常分类与除零陷阱。

断言统一用 `AUTO_ASSERT(expr)`，其输出可被直接解析成 `文件:行号`。
FreeRTOS 的 `configASSERT` 接到同一个出口：在 FreeRTOSConfig.h 里 `#include "cm_backtrace_lite.h"`，
**不要自己再写一遍 `cm_assert_failed` 的原型**（写成 `int line` 会和头文件里的 `uint32_t` 冲突，报 #147-D）。
可直接抄的写法在 `cm_backtrace_lite.h` 中 `cm_assert_failed` 的注释里。

### 3.4 固件自检

```bash
python run_autodebug.py --project MDK-ARM/App.uvprojx --check-firmware
```

逐条列出还缺什么（通过令牌、崩溃追踪器、AC5 下的非 ASCII 字符串）。闭环每轮烧录前会自动做同样的检查，
结果写在日志开头和诊断报告里，所以不必每次手动先跑。源码里找不到通过令牌时，串口只等几秒用来抓崩溃，
报告会说明「只等了 Ns」——这时该补的是令牌，不是业务逻辑。

---

## 4. 容易踩的坑

1. **大电流负载要在软件里限幅**：驱动电机、MOS 管、WS2812B 矩阵时，固件 bug 会直接烧坏硬件，软件层要做电流与占空比限幅。
2. **AC5 下字符串字面量必须纯 ASCII**：`armcc` 按本机代码页解析源文件（中文 Windows 上是 GBK），UTF-8 中文串会报 `main.c(42): error: #8: missing closing quote`。**这个报错指向引号而不是编码，会把人引向语法排查，怎么查都查不出来**。中文只放注释里——注释不参与编译，不受影响。`--check-firmware` 会扫描并点名文件与行号。
3. **测时间用板子上的时钟，不用串口行距**：验证周期、延时是否准确时，在**产生该事件的任务里**打印目标侧的 tick（`HAL_GetTick()` / `xTaskGetTickCount()`）。电脑按「收到一行的时刻」打的时间戳不可信：USB 虚拟串口成批送数据，两行相隔 500 ms 也可能在同一时刻到达。看到物理上不可能的数据（如 0.00 s 间隔），先怀疑量具。
   时基本身是否正确不用你测：测试通过后套件会经 SWD 实测 `uwTick` / `xTickCount` 的走速，偏差超过 5% 判 `TIMEBASE_SKEW`（退出码 3）。

---

## 5. 常用命令

```bash
python run_autodebug.py --project MDK-ARM/App.uvprojx          # 完整闭环
python run_autodebug.py --project MDK-ARM/App.uvprojx --json   # 机器可读
python run_autodebug.py --project MDK-ARM/App.uvprojx --no-flash  # 只编译
python run_autodebug.py --project MDK-ARM/App.uvprojx --add-source User/new.c   # 新文件入工程
python run_autodebug.py --project MDK-ARM/App.uvprojx --enable-hal adc i2c      # HAL 工程启用新外设
python run_autodebug.py --project MDK-ARM/App.uvprojx --install-tracer --uart USART1
python run_autodebug.py --project MDK-ARM/App.uvprojx --check-firmware          # 固件契约自检
python run_autodebug.py --list-devices                          # 列探针与串口
python -m unittest discover -s tests                            # 离线自测（无需硬件）
```
