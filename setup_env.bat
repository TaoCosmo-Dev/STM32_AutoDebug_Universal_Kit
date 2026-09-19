@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title STM32 全自动开发套件 - 环境初始化
cd /d "%~dp0"

echo =======================================================
echo   STM32 全自动开发套件 - 环境初始化
echo =======================================================
echo.

:: ---------------------------------------------------------------- 1/5 Python
:: NOTE: this file MUST stay UTF-8 *with* BOM. Without one, cmd.exe reads the
:: batch in fixed-size blocks and a multi-byte character straddling a block
:: boundary gets torn in half -- the tail of the line is then run as a command
:: ("'xxx' is not recognized"). Which line breaks depends purely on byte offsets,
:: so any edit anywhere can silently break a different line. Verified: without a
:: BOM 1 of 11 padding offsets failed; with a BOM, 0 of 11.
:: tests/test_setup_scripts.py guards this.
::
:: The 3.10 floor comes from pyelftools 0.33+ (DWARF line tables, crash address
:: to source line). This kit's own code uses no 3.10-only syntax.
:: Checking only that python exists is not enough: on an older interpreter pip
:: silently resolves an older pyelftools whose DWARF 5 support is weaker, so crash
:: attribution degrades without raising anything. Hence the explicit check below.
:: Keep these comment lines ASCII and free of redirection characters -- cmd still
:: scans a "::" line for them and would run whatever follows as a command.
set "PY="
set "PY_BAD="

python --version >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
    if !ERRORLEVEL! EQU 0 (
        set "PY=python"
    ) else (
        for /f "delims=" %%V in ('python -c "import sys;print('.'.join(map(str,sys.version_info[:3])))" 2^>nul') do set "PY_BAD=%%V"
        for /f "delims=" %%W in ('where python 2^>nul') do if not defined PY_WHERE set "PY_WHERE=%%W"
    )
)

if not defined PY (
    if defined PY_BAD (
        echo [提示] PATH 里的 Python 是 !PY_BAD!，低于所需的 3.10，正在别处查找...
    ) else (
        echo [!] PATH 里没有 python，正在常见安装位置查找...
    )
    for %%P in (
        "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
        "C:\Python313\python.exe"
        "C:\Python312\python.exe"
        "C:\Python311\python.exe"
        "C:\Python310\python.exe"
        "D:\Python\python.exe"
    ) do (
        if not defined PY if exist %%P set "PY=%%~P"
    )
)

if defined PY goto :py_ok

echo.
if defined PY_BAD echo [错误] 检测到 Python !PY_BAD!，低于本套件所需的 3.10。
if defined PY_BAD echo        当前使用：!PY_WHERE!
if not defined PY_BAD echo [错误] 没有找到 Python 3.10 或更高版本。
echo.
echo   为什么需要 3.10：崩溃定位依赖 pyelftools 解析 DWARF 调试信息，
echo   该库 0.33 版起要求 Python 3.10。这是本套件唯一的版本下限来源。
echo.
echo   下载地址：https://www.python.org/downloads/
echo   安装时务必勾选 "Add python.exe to PATH"，不勾这个后面全白装。
echo.
echo   已经装了新版却仍然报这个错？说明 PATH 里旧版排在前面。
echo   打开「系统环境变量 → Path」，把新版 Python 的两条路径移到最上面。
echo.
pause
exit /b 1

:py_ok
if not defined PY_BAD goto :py_done
echo [提示] PATH 里的 Python 是 !PY_BAD!（不满足要求），已改用：!PY!
echo     建议调整 PATH 顺序，否则其它工具仍会用到旧版。
:py_done

echo [1/5] Python: %PY%
"%PY%" --version

:: ---------------------------------------------------------------- 2/5 依赖
echo.
echo [2/5] 正在安装 Python 依赖库（清华镜像，快）...
"%PY%" -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn -r requirements.txt
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [!] 镜像源失败，改用官方源重试...
    "%PY%" -m pip install -r requirements.txt
    if !ERRORLEVEL! NEQ 0 (
        echo [错误] 依赖安装失败，请检查网络后重新双击本文件。
        pause
        exit /b 1
    )
)

:: ---------------------------------------------------------------- 3/5 芯片包
echo.
if /I "%~1"=="--with-packs" goto :install_packs
echo [3/5] 芯片支持包：跳过预装（首次烧录时按需自动下载，约 20-60 秒）
echo       需要一次性装齐以便离线使用，请运行：setup_env.bat --with-packs
goto :after_packs

:install_packs
echo [3/5] 正在预装常用 STM32 芯片支持包（约 250MB，请耐心等待）...
"%PY%" -m pyocd pack install stm32f0 stm32f1 stm32f3 stm32f4 stm32f7 stm32g0 stm32g4 stm32h7 stm32l4 stm32c0
:after_packs

:: ---------------------------------------------------------------- 4/5 自检
echo.
echo [4/5] 自检：工具链 / 探针 / 串口 / 离线单元测试
echo.
"%PY%" -m unittest discover -s tests -q
if %ERRORLEVEL% NEQ 0 (
    echo [!] 离线自测有失败项，详见上方输出。
)
echo.
"%PY%" -c "from autodebug.config import AutoDebugConfig; c=AutoDebugConfig.load(); print('  Keil UV4   :', c.keil.uv4_path or 'NOT FOUND - 请先安装 Keil MDK5'); print('  fromelf    :', c.keil.fromelf_path or 'not found')"
echo.
"%PY%" run_autodebug.py --list-devices

echo.
echo [5/5] 安装 Agent Skill（让 AI 在任意工程里自动加载本套件）
"%PY%" "%~dp0install_skill.py"

echo.
echo =======================================================
echo   [READY] 这台电脑已具备 编译 / 烧录 / 自愈调试 能力
echo.
echo   下一步：用 AI 编辑器打开任意 Keil 工程，直接说需求即可。
echo   （不需要注入，不需要开场白 —— Skill 已全局生效）
echo.
echo   仍想把工具链随工程提交 git？把工程文件夹拖到 inject_to_project.bat
echo.
echo   （进阶）MCP 服务端路径，填进 AI 编辑器的 MCP 配置：
echo     %~dp0mcp_server.py
echo =======================================================
echo.
pause
