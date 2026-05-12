@echo off
chcp 65001 >nul 2>&1
title QQ Official Bot
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creating venv...
    python -m venv .venv
    if errorlevel 1 (
        echo Failed to create venv
        pause
        exit /b 1
    )
    echo Installing deps...
    .venv\Scripts\python.exe -m pip install -r requirements.txt -q
)

echo.
echo ========== QQ Official Bot Starting ==========
echo.
.venv\Scripts\python.exe bot.py
echo.
echo Bot exited with code: %errorlevel%
pause
