@echo off
title Project-X-Nano Remove Hotspot Auto-Installer

:: Self-elevation to Administrator
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [*] Elevating to Administrator...
    powershell -NoProfile -Command "Start-Process cmd -ArgumentList '/c """%~f0"""' -Verb RunAs"
    exit /b
)

echo ========================================================
echo     Removing Project-X-Nano Hotspot Auto-Installer
echo ========================================================
echo.

set TASK_NAME=Project-X-Nano-Hotspot-Trigger
schtasks /End /TN "%TASK_NAME%" >nul 2>&1
schtasks /Delete /TN "%TASK_NAME%" /F >nul 2>&1

:: Stop any running hotspot_monitor PowerShell process
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"CommandLine LIKE '%hotspot_monitor%'\" | Invoke-CimMethod -MethodName Terminate" >nul 2>&1

set TARGET_DIR=%ProgramData%\Project-X-Nano
if exist "%TARGET_DIR%\hotspot_monitor.ps1" del /f /q "%TARGET_DIR%\hotspot_monitor.ps1" >nul 2>&1

echo [+] Scheduled task and trigger daemon removed.
echo.
pause
