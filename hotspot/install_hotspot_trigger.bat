@echo off
setlocal EnableDelayedExpansion
title Project-X-Nano Hotspot Auto-Installer Setup

:: Self-elevation to Administrator
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [*] Elevating to Administrator...
    powershell -NoProfile -Command "Start-Process cmd -ArgumentList '/c """%~f0"""' -Verb RunAs"
    exit /b
)

echo ========================================================
echo       Project-X-Nano Hotspot Auto-Installer Setup
echo ========================================================
echo.

set SCRIPT_DIR=%~dp0
set TARGET_DIR=%ProgramData%\Project-X-Nano
if not exist "%TARGET_DIR%" mkdir "%TARGET_DIR%"

copy /y "%SCRIPT_DIR%hotspot_monitor.ps1" "%TARGET_DIR%\hotspot_monitor.ps1" >nul

echo [1/3] Mobile Hotspot trigger daemon copied to:
echo       %TARGET_DIR%\hotspot_monitor.ps1
echo.

set /p WEBHOOK_URL="Enter Discord / Server Webhook URL (optional, press Enter to skip): "

:: Create Scheduled Task running with highest privileges on system boot/logon
set TASK_NAME=Project-X-Nano-Hotspot-Trigger
schtasks /Delete /TN "%TASK_NAME%" /F >nul 2>&1

set PS_CMD=powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%TARGET_DIR%\hotspot_monitor.ps1"
if not "%WEBHOOK_URL%"=="" (
    set PS_CMD=%PS_CMD% -WebhookUrl "%WEBHOOK_URL%"
)

schtasks /Create /TN "%TASK_NAME%" /TR "%PS_CMD%" /SC ONSTART /RU "SYSTEM" /RL HIGHEST /F >nul 2>&1
if %errorLevel% neq 0 (
    schtasks /Create /TN "%TASK_NAME%" /TR "%PS_CMD%" /SC ONLOGON /RL HIGHEST /F >nul 2>&1
)

echo [2/3] Elevated Scheduled Task '%TASK_NAME%' created successfully (RunLevel Highest).
echo.

echo [3/3] Starting trigger background daemon immediately...
schtasks /Run /TN "%TASK_NAME%" >nul 2>&1

echo.
echo ========================================================
echo  [SUCCESS] Hotspot Auto-Installer is now active!
echo  Logs: %ProgramData%\Project-X-Nano\hotspot-trigger.log
echo ========================================================
echo.
pause
