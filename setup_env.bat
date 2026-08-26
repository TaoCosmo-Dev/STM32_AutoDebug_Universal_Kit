@echo off
setlocal
title STM32 Auto-Debug Universal Kit Setup
echo =======================================================
echo   STM32 Auto-Debug Universal Kit - Environment Setup
echo =======================================================
echo.

:: 1. Check Python
set "PY=python"
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [!] 'python' command not found in PATH. Checking common paths...
    if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
        set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    ) else if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
        set "PY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    ) else if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" (
        set "PY=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    ) else if exist "C:\Python312\python.exe" (
        set "PY=C:\Python312\python.exe"
    ) else if exist "C:\Python311\python.exe" (
        set "PY=C:\Python311\python.exe"
    ) else if exist "C:\Python310\python.exe" (
        set "PY=C:\Python310\python.exe"
    ) else if exist "D:\Python\python.exe" (
        set "PY=D:\Python\python.exe"
    ) else (
        echo.
        echo [ERROR] Python 3.10+ is NOT installed on this computer!
        echo Please download and install Python from: https://www.python.org/downloads/
        echo (IMPORTANT: Check the box 'Add python.exe to PATH' during installation)
        echo.
        pause
        exit /b 1
    )
)

echo [OK] Python found: %PY%
%PY% --version

echo.
echo [1/2] Installing required Python libraries via fast mirror...
%PY% -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn pyocd pyelftools pyserial pyyaml pylink-square
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [!] Mirror failed. Trying default PyPI...
    %PY% -m pip install pyocd pyelftools pyserial pyyaml pylink-square
    if %ERRORLEVEL% NEQ 0 (
        echo [ERROR] pip install failed. Please check network connection.
        pause
        exit /b 1
    )
)

echo.
echo [2/3] Installing STM32F4 CMSIS-Pack for hardware probe...
%PY% -m pyocd pack install stm32f4 >nul 2>&1

echo.
echo [3/3] Running auto-detection self-test (Keil + Probe)...
%PY% -c "import sys; sys.path.insert(0, r'%~dp0'); from autodebug.config import AutoDebugConfig; cfg = AutoDebugConfig.load(); print('  [+] Keil UV4 Path  :', cfg.keil.uv4_path); print('  [+] Detected Probe :', cfg.debugger.probe_id or 'No probe connected (Plug in USB DAP probe anytime)');"

echo.
echo =======================================================
echo   [SUCCESS] Environment is 100%% Ready on this PC!
echo   Next Step: Drag your project folder onto inject_to_project.bat!
echo =======================================================
echo.
pause
