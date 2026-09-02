# STM32 AutoDebug Universal Kit - PowerShell environment setup
# Usage:  powershell -ExecutionPolicy Bypass -File setup_env.ps1

$ErrorActionPreference = "Continue"
Set-Location -Path $PSScriptRoot

Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host "  STM32 AutoDebug Universal Kit - 环境初始化" -ForegroundColor Cyan
Write-Host "=====================================================================" -ForegroundColor Cyan

# ---------------------------------------------------------------- 1/4 Python
Write-Host "`n[1/4] 检测 Python ..." -ForegroundColor Yellow
$pyPath = $null
$cmd = Get-Command python -ErrorAction SilentlyContinue
if ($cmd) {
    $pyPath = $cmd.Source
} else {
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
        "C:\Python313\python.exe", "C:\Python312\python.exe",
        "C:\Python311\python.exe", "C:\Python310\python.exe",
        "D:\Python\python.exe"
    )
    foreach ($c in $candidates) { if (Test-Path $c) { $pyPath = $c; break } }
}

if (-not $pyPath) {
    Write-Host "[ERROR] 未找到 Python 3.10+，请先安装：https://www.python.org/downloads/" -ForegroundColor Red
    Write-Host "        安装时务必勾选 'Add python.exe to PATH'" -ForegroundColor Red
    Read-Host "按回车退出"
    exit 1
}
Write-Host "  找到 Python: $pyPath" -ForegroundColor Green
& $pyPath --version

# ---------------------------------------------------------------- 2/4 dependencies
Write-Host "`n[2/4] 安装 Python 依赖（清华镜像）..." -ForegroundColor Yellow
& $pyPath -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "  镜像失败，改用官方 PyPI ..." -ForegroundColor Yellow
    & $pyPath -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] 依赖安装失败，请检查网络。" -ForegroundColor Red
        Read-Host "按回车退出"
        exit 1
    }
}

# ---------------------------------------------------------------- 3/4 CMSIS packs
Write-Host "`n[3/4] 安装 CMSIS 器件支持包（缺失的包 pyocd 之后会按需自动下载）..." -ForegroundColor Yellow
& $pyPath -m pyocd pack install stm32f0 stm32f1 stm32f3 stm32f4 stm32f7 stm32g0 stm32g4 stm32h7 stm32l4 stm32c0 *>$null

# ---------------------------------------------------------------- 4/4 self-test
Write-Host "`n[4/4] 自检：工具链 / 探针 / 串口 / 离线单元测试" -ForegroundColor Yellow
& $pyPath -m unittest discover -s tests -q
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [!] 离线单元测试有失败项，详见上方输出。" -ForegroundColor Yellow
}

& $pyPath -c "from autodebug.config import AutoDebugConfig; c=AutoDebugConfig.load(); print('  Keil UV4   :', c.keil.uv4_path or 'NOT FOUND - 请安装 Keil MDK'); print('  fromelf    :', c.keil.fromelf_path or 'not found')"
& $pyPath run_autodebug.py --list-devices

Write-Host "`n=====================================================================" -ForegroundColor Cyan
Write-Host " [环境就绪] 这台电脑已具备 编译 / 烧录 / 自愈调试 能力" -ForegroundColor Green
Write-Host " 下一步：把工程文件夹拖到 inject_to_project.bat" -ForegroundColor Yellow
Write-Host " MCP 服务端路径（Claude Code / Cursor / Windsurf 配置用）：" -ForegroundColor Yellow
Write-Host "   $PSScriptRoot\mcp_server.py" -ForegroundColor White
Write-Host "=====================================================================" -ForegroundColor Cyan
Read-Host "按回车完成"
