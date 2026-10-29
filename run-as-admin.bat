@echo off
title Project-X-Nano Admin Launcher
cd /d "%~dp0"

REM Check if already running as admin
net session >nul 2>&1
if %errorlevel% == 0 (
    echo [OK] Running with Administrator privileges.
    if exist "%~dp0dist\Project-X-Nano.exe" (
        start "Project-X-Nano" "%~dp0dist\Project-X-Nano.exe"
    ) else if exist "%~dp0dist\RemotePC.exe" (
        start "Project-X-Nano" "%~dp0dist\RemotePC.exe"
    ) else (
        start "Project-X-Nano" python server.py
    )
    timeout /t 2 /nobreak >nul
    start http://localhost:8765
    exit
) else (
    echo Elevating to Administrator...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process cmd.exe -ArgumentList '/c \"\"%~f0\"\"' -Verb RunAs"
    exit
)
