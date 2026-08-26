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
Write-Host "`n[步骤 3/3] 正在配置 STM32 芯片支持包..." -ForegroundColor Yellow
& $pyPath -m pyocd pack install stm32f4

Write-Host "`n=====================================================================" -ForegroundColor Cyan
Write-Host " 🎉 [环境就绪] 这台电脑已具备 STM32 自动化调试与修复能力！" -ForegroundColor Green
Write-Host "=====================================================================" -ForegroundColor Cyan
Read-Host "按回车键完成"
