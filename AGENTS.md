# AGENTS.md / .cursorrules / CLAUDE.md — STM32 固件自主编程・烧录・自愈调试规范

> 适用于任何 AI Agent（Claude Code / Cursor / Windsurf / Aider / ChatGPT / DeepSeek）。
> 接入本工程后，以下闭环与嵌入式黄金法则是硬约束。

---

## 0. 唯一真理来源：退出码

**严禁凭日志文字判断成败，只认退出码。** 脚本只有在「编译 0 Error + 烧录成功 + 实机串口输出通过令牌」三件事同时成立时才返回 0。

```bash
python run_autodebug.py --project "MDK-ARM/YourProject.uvprojx"
echo $?    # PowerShell: $LASTEXITCODE
```

| 退出码 | 状态 | 含义 | 你该做什么 |
|---|---|---|---|
| 0 | `TEST_PASSED` | 编译 + 烧录 + 实机验收全通过 | 封版交付，不要再改 |
| 1 | `BUILD_FAILED` | 编译 / 链接错误 | 按报告改源码，重跑 |
| 2 | `FLASH_FAILED` | 探针、接线、供电、读保护问题 | **这不是代码问题**，把接线/供电排查项交给用户，别改代码 |
| 3 | `HARD_FAULT` / `ASSERTION_FAILED` | 运行时崩溃，已定位到源码行 | 按根因改源码，重跑 |
| 4 | `TIMEOUT` / `SERIAL_UNAVAILABLE` | 没等到通过令牌 / 串口打不开 | 检查串口重定向、波特率、测试是否真的跑到输出点 |
| 5 | `STALLED` | 连续两轮完全相同的失败 | **停止盲改**，向用户说明卡点并请求决策 |
| 6 | `CONFIG_ERROR` | 找不到 Keil 等工具链 | 提示用户装环境或改 `autodebug.config.yaml` |

结构化诊断始终写在工程根目录 `diagnostic_report.json`，历史归档在 `.autodebug/`。
需要机器可读输出时加 `--json`。

---

## 1. 核心闭环流程（Autonomous Closed Loop）

改动任何 STM32 C 源码后，**严禁直接结束对话**，必须跑完闭环：

```bash
python run_autodebug.py --project "MDK-ARM/YourProject.uvprojx"
```

脚本内部顺序是固定的，不要绕过它自己拼命令：

```
编译 → 校验产物是本次新生成的 → 打开探针 → 清除上一轮故障位
     → 烧录并让内核保持 halt → 打开串口 → 再 resume → 抓取判定令牌
     → UART 崩溃自述优先，其次 SWD 读 SCB → 定位源码行 → 出报告
```

> 为什么先 halt 再开串口：固件复位后几十毫秒内就会打印启动横幅，先 resume 再开串口必然丢掉这段，通过令牌永远抓不到。

拿到非 0 退出码后：
1. 读 `diagnostic_report.json` 的 `ai_repair_prompt` 与 `next_actions`；
2. 只改与根因直接相关的文件；
3. 重跑闭环；
4. 若报告里 `repeated_failure: true`，说明**你上一次的修改完全没有生效**，换思路，不要重复同类改动。

每轮 AI 修改前，脚本会用 `git stash create` + tag 打一个**不改动工作区**的还原点（`autodebug/iter-NN`），改坏了可以 `git checkout <sha> -- .` 回滚。

---

## 2. 需求深度对齐：谋定而后动（Grill-Me）

**严禁盲目动手与预设参数。** 收到新项目 / 新外设时，必须先追问清楚 5 大硬件分支，再产出方案，用户确认后才编码：

1. **时钟树与外部晶振 (HSE)**：8MHz / 12MHz / 25MHz 的确切数值，以及 PLL 倍频系数（配错直接超频死机或延时错乱）；
2. **开发板型号与引脚冲突**：目标 SPI / I2C / UART / PWM / ADC 引脚是否已被板载 SPI Flash、以太网 PHY、板载 LED 占用；
3. **外设核心物理指标**：
   - 显示面板：ST7735S / ST7789 / SSD1306 的显存偏置、RGB565 与颜色反转；
   - 电机与逆变器：极对数、编码器 CPR / 霍尔、死区时间、驱动芯片型号；
   - 传感器：IMU / 温湿度的 I2C 从机地址、量程、采样率；
   - 总线模组：CAN / RS485 波特率、滤波器、流控引脚；
4. **通信时序与驱动模式**：硬件 DMA 双缓冲 / 中断环形缓冲区 vs 轮询；
5. **系统框架**：裸机前后台状态机 vs RTOS 多任务 vs 图形/协议栈。

然后输出《技术方案 + 引脚对照表 + 电气安全预警》，让用户只需照图插线。

---

## 3. 让闭环真正能自愈：固件侧必须做的三件事

没有这三步，脚本只能告诉你「超时了」，给不出根因。

1. **通过令牌**：测试通过路径上必须打印 `[ALL TESTS PASSED]`（或 `TESTS_PASSED` / `[PASS]`）。
2. **崩溃自述**：把 `mcu_support/cm_backtrace_lite.c` 加入 Keil 工程，`main()` 开头调用 `cm_backtrace_init()`，并实现阻塞式字节输出：

   ```c
   void cm_backtrace_putchar(char c)
   {
       while (!(USART1->SR & USART_SR_TXE)) { }   /* F1/F4 用 SR，G0/G4/H7 用 ISR */
       USART1->DR = (uint8_t)c;
   }
   ```

   **严禁**在故障处理里用 `printf` / `HAL_UART_Transmit`：它们的超时依赖 SysTick，而 HardFault 优先级 -1 时 SysTick 进不了中断，tick 永不递增，处理函数会在吐出第一个字节前就死锁。

   若链接器报 `HardFault_Handler` 重复定义，删掉 `stm32xxxx_it.c` 里那个空实现（正是它把崩溃吞掉了）。

3. **断言**：用 `AUTO_ASSERT(expr)`，它输出的格式脚本能直接解析成 `文件:行号`。

---

## 4. 嵌入式固件开发黄金准则（MISRA-C / BARR-C）

1. **时钟前置**：配置任何外设（GPIO / SPI / UART / TIM）前，第一行必须 `__HAL_RCC_xxx_CLK_ENABLE()`。时钟没开就读写外设寄存器 = 总线错误 HardFault。
2. **`volatile` 强约束**：ISR 与主循环共享的全局变量必须 `volatile`。
3. **ISR 极简**：中断内严禁 `HAL_Delay` 与大耗时操作，只置标志或写环形缓冲区。
4. **通信防死锁**：所有硬件等待 `while` 必须带超时计数器，严禁裸 `while` 死等。
5. **结构体对齐**：通信协议结构体显式 1 字节对齐（`#pragma pack(1)` / `__attribute__((packed))`）。
6. **硬件安全限流**：驱动 WS2812B 矩阵、电机、MOS 管前，软件层必须做全局电流与占空比限幅。
7. **栈够用**：大数组不要放局部变量；`MSTKERR`/`STKERR` 就是栈溢出的直接证据。

---

## 5. 第一性原理与务实工程铁律

1. **第一性原理深层归因**：遇到镜像、闪烁、死机，必须从寄存器位定义（MADCTL / RCC / SCB / CFSR）、时钟树公式、物理显存映射推导根因，严禁碰运气式盲改参数。报告里的 `BFAR`、`CFSR` 位、`PC → 源码行`就是给你做这件事用的。
2. **拒绝过度工程（YAGNI）**：轻量状态机够用时严禁引入 RTOS 与中间件；只有出现真实并发瓶颈、复杂协议栈（TCP/IP、USB、CANopen）或硬实时抢占需求才正规引入 RTOS。
3. **清晰的交付边界**：达成「Keil 0 Error + 探针烧录 + 实机验收」即黄金标准，立即封版，不追求理论完美。
4. **全自动无阻塞**：多探针自动静默仲裁、串口自动嗅探，严禁任何阻塞脚本的交互弹窗；发现有阻塞点就修脚本，别让用户手动点。
5. **诚实汇报**：烧录失败时**严禁**把上一版固件的行为当作本次修改的验证结果；跑不通就说跑不通。

---

## 6. 常用命令

```bash
python run_autodebug.py --project MDK-ARM/App.uvprojx          # 完整闭环
python run_autodebug.py --project MDK-ARM/App.uvprojx --json   # 机器可读
python run_autodebug.py --project MDK-ARM/App.uvprojx --no-flash  # 只编译
python run_autodebug.py --list-devices                          # 列探针与串口
python -m unittest discover -s tests                            # 离线自测（无需硬件）
```
