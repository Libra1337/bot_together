@echo off
chcp 65001 >nul 2>&1
title QQ Bot (Auto Restart)
cd /d "%~dp0"

echo ==============================
echo   QQ Bot - Auto Restart Mode
echo   Press Ctrl+C to stop
echo ==============================

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
        set PYTHON_CMD=python
        goto loop
    )
    echo [SETUP] Installing dependencies...
    .venv\Scripts\pip install pyyaml websockets httpx
    echo.
)

set PYTHON_CMD=.venv\Scripts\python.exe

:loop
echo.
echo [%date% %time%] Starting Bot...
echo.

%PYTHON_CMD% bot.py

echo.
echo [%date% %time%] Bot exited, restarting in 5 seconds...
echo Press Ctrl+C to cancel restart
timeout /t 5 /nobreak >nul

goto loop
