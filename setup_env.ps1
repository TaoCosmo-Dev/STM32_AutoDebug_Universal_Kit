# STM32 AutoDebug Universal Kit - PowerShell environment setup
# Usage:  powershell -ExecutionPolicy Bypass -File setup_env.ps1

$ErrorActionPreference = "Continue"
Set-Location -Path $PSScriptRoot

Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host "  STM32 AutoDebug Universal Kit - 环境初始化" -ForegroundColor Cyan
Write-Host "=====================================================================" -ForegroundColor Cyan

# ---------------------------------------------------------------- 1/5 Python
Write-Host "`n[1/5] 检测 Python ..." -ForegroundColor Yellow
# 版本下限 3.10 来自 pyelftools>=0.33（DWARF 行号表，崩溃地址 -> 源码行）。
# 本套件自身的代码没有用到任何 3.10 专属语法。
# 只检查 python 是否存在是不够的：装了旧版时 pip 会静默退回到老版 pyelftools，
# 于是崩溃定位在 DWARF 5 上失准，且不报错。所以这里显式验版本。
function Test-PyVersion($exe) {
    try { & $exe -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" 2>$null; return ($LASTEXITCODE -eq 0) }
    catch { return $false }
}
function Get-PyVersion($exe) {
    try { return (& $exe -c "import sys;print('.'.join(map(str,sys.version_info[:3])))" 2>$null) } catch { return $null }
}

$pyPath = $null
$pyBad = $null
$cmd = Get-Command python -ErrorAction SilentlyContinue
if ($cmd -and (Test-PyVersion $cmd.Source)) {
    $pyPath = $cmd.Source
} else {
    if ($cmd) {
        $pyBad = Get-PyVersion $cmd.Source
        Write-Host "  [!] PATH 里的 Python 是 $pyBad（低于 3.10），正在别处查找 ..." -ForegroundColor Yellow
    }
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
        "C:\Python313\python.exe", "C:\Python312\python.exe",
        "C:\Python311\python.exe", "C:\Python310\python.exe",
        "D:\Python\python.exe"
    )
    foreach ($c in $candidates) { if ((Test-Path $c) -and (Test-PyVersion $c)) { $pyPath = $c; break } }
}

if (-not $pyPath) {
    if ($pyBad) {
        Write-Host "`n[ERROR] 检测到 Python $pyBad，但本套件需要 3.10 或更高版本。" -ForegroundColor Red
        Write-Host "        当前使用: $($cmd.Source)" -ForegroundColor Red
    } else {
        Write-Host "`n[ERROR] 没有找到 Python 3.10 或更高版本。" -ForegroundColor Red
    }
    Write-Host ""
    Write-Host "  为什么需要 3.10：崩溃定位依赖 pyelftools 解析 DWARF 调试信息，" -ForegroundColor Yellow
    Write-Host "  该库 0.33 版起要求 Python 3.10+。这是本套件唯一的版本下限来源。" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  下载地址: https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host "  安装时务必勾选 'Add python.exe to PATH'" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  已经装了新版却仍显示旧版？说明 PATH 里旧版排在前面。" -ForegroundColor DarkGray
    Write-Host "  打开「系统环境变量 -> Path」，把新版 Python 的两条路径上移到最前。" -ForegroundColor DarkGray
    Read-Host "按回车退出"
    exit 1
}
if ($pyBad) {
    Write-Host "  [!] PATH 里的 Python 是 $pyBad（不满足要求），已改用：$pyPath" -ForegroundColor Yellow
    Write-Host "      建议调整 PATH 顺序，否则其它工具仍会用到旧版。" -ForegroundColor DarkGray
}
Write-Host "  找到 Python: $pyPath" -ForegroundColor Green
& $pyPath --version

# ---------------------------------------------------------------- 2/5 dependencies
Write-Host "`n[2/5] 安装 Python 依赖（清华镜像）..." -ForegroundColor Yellow
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

# ---------------------------------------------------------------- 3/5 CMSIS packs
if ($args -contains "--with-packs") {
    Write-Host "`n[3/5] 正在预装常用 STM32 芯片支持包（约 250MB，请耐心等待）..." -ForegroundColor Yellow
& $pyPath -m pyocd pack install stm32f0 stm32f1 stm32f3 stm32f4 stm32f7 stm32g0 stm32g4 stm32h7 stm32l4 stm32c0 *>$null
} else {
    Write-Host "`n[3/5] 芯片支持包：跳过预装（首次烧录时按需自动下载，约 20-60 秒）" -ForegroundColor Yellow
    Write-Host "      需要一次性装齐以便离线使用，请运行： .\setup_env.ps1 --with-packs" -ForegroundColor DarkGray
}

# ---------------------------------------------------------------- 4/5 self-test
Write-Host "`n[4/5] 自检：工具链 / 探针 / 串口 / 离线单元测试" -ForegroundColor Yellow
& $pyPath -m unittest discover -s tests -q
if ($LASTEXITCODE -ne 0) {
    Write-Host "  [!] 离线单元测试有失败项，详见上方输出。" -ForegroundColor Yellow
}

& $pyPath -c "from autodebug.config import AutoDebugConfig; c=AutoDebugConfig.load(); print('  Keil UV4   :', c.keil.uv4_path or 'NOT FOUND - 请安装 Keil MDK'); print('  fromelf    :', c.keil.fromelf_path or 'not found')"
& $pyPath run_autodebug.py --list-devices

Write-Host "`n[5/5] 安装 Agent Skill（让 AI 在任意工程里自动加载本套件）" -ForegroundColor Yellow
& $pyPath (Join-Path $PSScriptRoot "install_skill.py")

Write-Host "`n=====================================================================" -ForegroundColor Cyan
Write-Host " [环境就绪] 这台电脑已具备 编译 / 烧录 / 自愈调试 能力" -ForegroundColor Green
Write-Host " 下一步：用 AI 编辑器打开任意 Keil 工程，直接说需求即可" -ForegroundColor Yellow
Write-Host " （不需要注入，不需要开场白 —— Skill 已全局生效）" -ForegroundColor DarkGray
Write-Host " 仍想把工具链随工程提交 git？把工程文件夹拖到 inject_to_project.bat" -ForegroundColor DarkGray
Write-Host " MCP 服务端路径（Claude Code / Cursor / Windsurf 配置用）：" -ForegroundColor Yellow
Write-Host "   $PSScriptRoot\mcp_server.py" -ForegroundColor White
Write-Host "=====================================================================" -ForegroundColor Cyan
Read-Host "按回车完成"
