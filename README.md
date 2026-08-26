# 🚀 STM32 硬件在环全自动固件架构师与自愈开发套件
### (STM32 AutoDebug & Firmware Copilot Universal Kit)

> **核心信仰**：谋定而后动，系统稳定与硬件安全压倒一切。  
> **用户只需负责照图插好杜邦线，剩下的需求对齐、代码编写、Keil 0 Error 编译自愈、JTAG 在线烧录、CPU 寄存器遥测全部由 AI 全自动闭环完成！**

---

## 🌟 核心特性 (Features)

1. 🎯 **从“模糊想法”到“实物运行”全生命周期**：支持从一个灵感出发，AI 自动访谈对齐参数，输出小白防呆接线表；
2. 🔌 **小白防呆型硬件接线指引**：杜邦线引脚对照表、3.3V/5V 防烧预警、I2C 上拉与去耦电容提示；
3. ⚙️ **Keil UV4 自动化构建与编译自愈**：修改代码后自动调用 Keil 编译器全量构建，遇错自动分析 AST 与行号自愈修复，达成 `0 Error(s)`；
4. ⚡ **PyOCD JTAG 在线烧录与硬件探针自适应**：自动枚举当前连接的 CMSIS-DAP / ST-Link / DAP-Link 探针；
5. 🔍 **硬件在环故障诊断 (HardFault Healer)**：硬件崩溃时自动读取 PC、LR、CFSR、BFAR 寄存器与反汇编切片进行自愈；
6. 🌐 **跨电脑 100% 绿色即用**：自动读取 Windows 注册表扫描 Keil 路径，无需手动配置环境。

---

## 🛠️ 新电脑 30 秒一键初始化指南 (New PC Setup)

当你在一台全新的电脑上克隆或解压本项目时：

### 第 1 步：克隆代码仓库
```bash
git clone https://github.com/TaoCosmo-Dev/STM32_AutoDebug_Universal_Kit.git
cd STM32_AutoDebug_Universal_Kit
```

### 第 2 步：双击运行一键环境初始化
直接双击运行：
👉 **`setup_env.bat`**
- ⚡ 自动通过国内清华源高速安装 `pyocd`、`pyserial`、`websockets` 等依赖；
- ⚡ 自动检索 Windows 注册表和全盘驱动器定位 Keil `UV4.exe`；
- ⚡ 自动识别已连接的硬件调试探针并完成自检。

---

## 🎮 新工程开发与存量项目接入 (How to Use)

### 方式 A：拖拽注入任意新工程（最简单独立）
只需将你的 **Keil / CubeMX 新工程文件夹** 拖拽到：
👉 **`inject_to_project.bat`**
- 1 秒内自动将 AI 规范（`AGENTS.md`、`.cursorrules`）与调试自愈引擎注入目标工程；
- 在新项目窗口中对 AI 说：“*根据 AGENTS.md 规范开始编写代码并自动验证*”，AI 立即全自动接管！

### 方式 B：配置全局 MCP Server（零拷贝，所有新窗口免配置）
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
├── inject_to_project.bat      # [1-Click] 存量/新工程拖拽注入器
├── inject_to_project.py       # 工程注入核心 Python 逻辑
├── mcp_server.py             # 跨编辑器通用 MCP 服务端
├── AGENTS.md                 # 通用 AI 智能体开发规范与执行 SOP
├── .cursorrules              # Cursor / Windsurf 专用规则软链
├── autodebug/                # 自动化构建、烧录、寄存器遥测核心引擎
│   ├── config.py             # 注册表扫描与探针自适应模块
│   ├── builder.py            # Keil UV4 驱动与编译日志解析器
│   ├── hardware_probe.py     # PyOCD JTAG 探针与寄存器读取器
│   ├── fault_analyzer.py     # Cortex-M HardFault 智能故障诊断器
│   └── symbol_resolver.py    # AXF/ELF 符号与源码行号映射器
└── templates/                # 模板库
    └── wiring_guide_template.md # 小白防呆型硬件接线指引规范模板
```
