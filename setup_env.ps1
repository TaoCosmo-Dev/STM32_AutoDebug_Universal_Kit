# PowerShell One-Click Environment Installer for STM32 Auto-Debug
Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host "   STM32 Auto-Debug Universal Kit - PowerShell 环境一键安装器" -ForegroundColor Cyan
Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host ""

# 1. 寻找 Python
Write-Host "[步骤 1/3] 正在检测 Python..." -ForegroundColor Yellow
$pyPath = Get-Command python.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source
if (-not $pyPath) {
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
        "C:\Python312\python.exe",
        "C:\Python311\python.exe",
        "C:\Python310\python.exe",
        "D:\Python\python.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { $pyPath = $c; break }
    }
}

if (-not $pyPath) {
    Write-Host "❌ 错误：未检测到 Python 解释器！" -ForegroundColor Red
    Write-Host "请先在终端运行: winget install Python.Python.3.11 或访问 https://www.python.org/downloads/ 安装。" -ForegroundColor White
    Read-Host "按回车键退出"
    exit 1
}

Write-Host "✅ 找到 Python: $pyPath" -ForegroundColor Green
& $pyPath --version

# 2. 安装 pip 依赖
Write-Host "`n[步骤 2/3] 正在安装驱动库 (清华大学高速镜像源)..." -ForegroundColor Yellow
& $pyPath -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn pyocd pyelftools pyserial pyyaml pylink-square

# 3. 安装 STM32 CMSIS Pack
Write-Host "`n[步骤 3/4] 正在配置 STM32 常用芯片支持包 (F1 / F4 / G4 / H7)..." -ForegroundColor Yellow
& $pyPath -m pyocd pack install stm32f1 stm32f4 stm32g4 stm32h7 *>$null

# 4. 运行自检
Write-Host "`n[步骤 4/4] 正在运行 Keil 与硬件探针自适应检测..." -ForegroundColor Yellow
& $pyPath -c "import sys; sys.path.insert(0, '$PSScriptRoot'); from autodebug.config import AutoDebugConfig; cfg = AutoDebugConfig.load(); print('  [+] Keil UV4 路径 :', cfg.keil.uv4_path); print('  [+] 检测到探针   :', cfg.debugger.probe_id or '未连接探针(随时插入USB即可)');"

Write-Host "`n=====================================================================" -ForegroundColor Cyan
Write-Host " 🎉 [环境就绪] 这台电脑已具备 STM32 自动化调试与自愈能力！" -ForegroundColor Green
Write-Host " 下一步：直接将你的新工程文件夹拖拽到 inject_to_project.bat 即可！" -ForegroundColor Yellow
Write-Host "=====================================================================" -ForegroundColor Cyan
Read-Host "按回车键完成"
