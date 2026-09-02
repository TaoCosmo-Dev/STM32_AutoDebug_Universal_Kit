@echo off
setlocal enabledelayedexpansion
title STM32 AutoDebug Universal Kit - Setup
cd /d "%~dp0"

echo =======================================================
echo   STM32 AutoDebug Universal Kit - Environment Setup
echo =======================================================
echo.

:: ---------------------------------------------------------------- 1/4 Python
set "PY=python"
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [!] 'python' not on PATH, checking common install locations...
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
        echo [ERROR] Python 3.10+ is not installed.
        echo Download it from https://www.python.org/downloads/
        echo IMPORTANT: tick "Add python.exe to PATH" during installation.
        echo.
        pause
        exit /b 1
    )
)

echo [1/4] Python: %PY%
"%PY%" --version

:: ---------------------------------------------------------------- 2/4 deps
echo.
echo [2/4] Installing Python dependencies (Tsinghua mirror)...
"%PY%" -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn -r requirements.txt
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [!] Mirror failed, retrying against the default PyPI index...
    "%PY%" -m pip install -r requirements.txt
    if !ERRORLEVEL! NEQ 0 (
        echo [ERROR] pip install failed. Check your network connection.
        pause
        exit /b 1
    )
)

:: ---------------------------------------------------------------- 3/4 CMSIS packs
echo.
echo [3/4] Installing CMSIS device packs for the debug probe...
echo       (skip-safe: pyocd downloads any missing pack on demand later)
"%PY%" -m pyocd pack install stm32f0 stm32f1 stm32f3 stm32f4 stm32f7 stm32g0 stm32g4 stm32h7 stm32l4 stm32c0 >nul 2>&1

:: ---------------------------------------------------------------- 4/4 self-test
echo.
echo [4/4] Self-test: toolchain detection, probes, serial ports, offline unit tests
echo.
"%PY%" -m unittest discover -s tests -q
if %ERRORLEVEL% NEQ 0 (
    echo [!] Offline unit tests reported a failure - see the output above.
)
echo.
"%PY%" -c "from autodebug.config import AutoDebugConfig; c=AutoDebugConfig.load(); print('  Keil UV4   :', c.keil.uv4_path or 'NOT FOUND - install Keil MDK'); print('  fromelf    :', c.keil.fromelf_path or 'not found')"
echo.
"%PY%" run_autodebug.py --list-devices

echo.
echo =======================================================
echo   [READY] This PC can now build, flash and self-debug.
echo.
echo   Next: drag a project folder onto inject_to_project.bat
echo   MCP server path (for Claude Code / Cursor / Windsurf):
echo     %~dp0mcp_server.py
echo =======================================================
echo.
pause
