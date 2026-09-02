@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title STM32 全自动开发套件 - 环境初始化
cd /d "%~dp0"

echo =======================================================
echo   STM32 全自动开发套件 - 环境初始化
echo =======================================================
echo.

:: ---------------------------------------------------------------- 1/4 Python
set "PY=python"
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [!] PATH 里没有 python，正在常见安装位置查找...
    set "PY="
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
    if not defined PY (
        echo.
        echo [错误] 没有装 Python 3.10 或更高版本。
        echo.
        echo   下载地址: https://www.python.org/downloads/
        echo   ⚠ 安装时务必勾选 "Add python.exe to PATH"，不勾这个后面全白装。
        echo.
        pause
        exit /b 1
    )
)

echo [1/4] Python: %PY%
"%PY%" --version

:: ---------------------------------------------------------------- 2/4 依赖
echo.
echo [2/4] 正在安装 Python 依赖库（清华镜像，快）...
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

:: ---------------------------------------------------------------- 3/4 芯片包
echo.
echo [3/4] 正在安装常用 STM32 芯片支持包...
echo       （装不全没关系，用到哪个会自动下载）
"%PY%" -m pyocd pack install stm32f0 stm32f1 stm32f3 stm32f4 stm32f7 stm32g0 stm32g4 stm32h7 stm32l4 stm32c0 >nul 2>&1

:: ---------------------------------------------------------------- 4/4 自检
echo.
echo [4/4] 自检：工具链 / 探针 / 串口 / 离线单元测试
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
echo =======================================================
echo   [READY] 这台电脑已具备 编译 / 烧录 / 自愈调试 能力
echo.
echo   下一步：把你的工程文件夹拖到 inject_to_project.bat 上
echo.
echo   （进阶）MCP 服务端路径，填进 AI 编辑器的 MCP 配置：
echo     %~dp0mcp_server.py
echo =======================================================
echo.
pause
