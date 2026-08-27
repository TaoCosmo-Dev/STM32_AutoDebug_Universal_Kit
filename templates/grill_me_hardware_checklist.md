# 📋 Grill-Me 嵌入式硬件与固件深度访谈核对清单 (Hardware Interview Checklist)

> **核心原则**：严禁在未完成以下 5 大分支参数核验前盲目写代码或给出接线表！

---

## 1. 分支 1：时钟树与电源架构 (Clock Tree & Power Rail)
- [ ] **外部高速晶振频率 (HSE)**：确认是 `8.000MHz`、`12.000MHz`、`25.000MHz` 还是内部 HSI。
  - 计算 PLL 参数：$\text{SYSCLK} = \frac{\text{HSE}}{\text{PLL\_M}} \times \frac{\text{PLL\_N}}{\text{PLL\_P}} = 168\text{MHz}$
  - 计算 Systick 滴答定时器重装载值，确保 `HAL_Delay(1000)` 精确等于 1 秒。
- [ ] **电源电压与最大电流负载**：
  - 核心工作电压（3.3V）；
  - 外设供电能力评估（大电流外设需外挂去耦大电容与软硬件限流）。

---

## 2. 分支 2：开发板型号与引脚复用冲突排查 (Pin Multiplexing & Conflicts)
- [ ] **目标板型**：正点原子探索者、野火霸天虎、立创梁山派、自制核心板。
- [ ] **引脚冲突审查**：
  - 拟用 SPI/I2C/UART 引脚是否与板载 SPI Flash（如 W25Q128）、以太网 PHY（LAN8720A）、板载 LED/按键共用引脚；
  - 若有冲突，立即在访谈中提出备选引脚方案。

---

## 3. 分支 3：外设与执行机构核心物理指标 (Peripherals & Actuators)
- [ ] **显示外设**：
  - 控制器子型号：ST7735S、ST7789、SSD1306、ILI9341；
  - 分辨率与窗口偏置（如 0.96寸 80×160 窗口偏移 $X_{\text{offset}}=26, Y_{\text{offset}}=1$）；
  - 颜色模式（RGB565）与 IPS 反转控制（`0x21 INVON`）。
- [ ] **电机与逆变控制**：
  - 电机类型：无刷直流 (BLDC) / 永磁同步 (PMSM) / 步进电机 / 舵机；
  - 极对数 (Pole Pairs)、编码器线数 (CPR) / 霍尔传感器相序；
  - 驱动芯片（DRV8302 / TMC2209）、PWM 载波频率、死区时间 (Dead-time) 与过流保护门限。
- [ ] **传感器与模数转换**：
  - 传感器类型：IMU 六轴/九轴陀螺仪 (MPU6050 / ICM42688)、温湿度 (SHT30)、气压计 (BMP280)；
  - I2C/SPI 从机硬件地址、量程档位、滤波带宽与采样率；
  - ADC 模拟量输入通道、参考基准电压、采样阻抗与分压电阻网络。
- [ ] **通信与总线模组**：
  - CAN / CAN-FD：波特率（如 500kbps / 1Mbps）、采样点、硬件验收滤波器 ID；
  - RS485：半双工收发使能引脚（DE/RE）控制时序；
  - 无线模组：BLE / WiFi (ESP32) / LoRa AT 握手协议与超时机制。

---

## 4. 分支 4：驱动架构与通信模式 (Driver Architecture & Performance)
- [ ] **通信接口**：硬件 SPI（分频系数与 CPOL/CPHA 极性） vs 软件模拟 SPI。
- [ ] **刷屏模式**：
  - DMA 异步无阻塞双缓冲传输（目标 60 FPS）；
  - 阻塞式轮询传输（低 RAM 开销）。
- [ ] **显存分配**：SRAM 帧缓冲区大小与内存占用计算。

---

## 5. 分支 5：系统框架与交付验收 (OS Framework & Acceptance)
- [ ] **运行环境**：裸机前后台轮询 vs FreeRTOS / RT-Thread 操作系统。
- [ ] **图形栈**：轻量级自研点阵/几何绘图引擎 vs LVGL 9.0 图形库。
- [ ] **交付方式**：全屏色彩/几何测试图 + Web Serial 1:1 仿真遥测控制台。
