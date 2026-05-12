@echo off
chcp 65001 >nul 2>&1
title QQ Bot
cd /d "%~dp0"

echo ==============================
echo   QQ Bot Starting...
echo ==============================
echo.

set "NEED_VENV=0"
if not exist ".venv\Scripts\python.exe" (
    set "NEED_VENV=1"
) else (
    .venv\Scripts\python.exe --version >nul 2>&1
    if errorlevel 1 (
        echo [WARN] venv broken, rebuilding...
        rmdir /s /q .venv >nul 2>&1
        set "NEED_VENV=1"
    )
)

if "%NEED_VENV%"=="1" (
    echo [SETUP] Creating venv...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create venv, using system Python
        goto use_system
    )
    echo [SETUP] Installing dependencies...
    .venv\Scripts\pip install pyyaml websockets httpx Pillow
    echo.
)

echo [INFO] Using venv Python
.venv\Scripts\python.exe -m pip install Pillow -q 2>nul
".venv\Scripts\python.exe" bot.py
goto done

:use_system
echo [INFO] Using system Python
python bot.py

:done
echo.
if %errorlevel% neq 0 (
    echo Bot exited with error code: %errorlevel%
)
echo.
echo Bot stopped. Press any key to close...
pause >nul
