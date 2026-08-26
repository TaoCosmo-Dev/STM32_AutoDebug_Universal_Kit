@echo off
chcp 65001 >nul
title STM32 AutoDebug - New Project Injector

if "%~1"=="" (
    echo =======================================================
    echo   🚀 STM32 自动 Debug 工具链 - 新项目一键注入器
    echo =======================================================
    echo.
    echo 请直接将你的【新项目文件夹】拖拽到本 BAT 图标上，
    echo 或者在下方输入新项目的完整路径：
    echo.
    set /p TARGET="请输入新项目路径: "
) else (
    set TARGET=%~1
)

python "%~dp0inject_to_project.py" "%TARGET%"

echo.
pause
