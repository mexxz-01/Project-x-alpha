@echo off
setlocal enabledelayedexpansion
title Project-X-Nano Agent Auto-Installer

echo ========================================================
echo        Project-X-Nano 1-Click Remote Agent Installer    
echo ========================================================
echo.
echo [*] Initializing installation environment...

:: Check if Webhook parameter was passed
set "REPORT_URL=%~1"

if "%REPORT_URL%"=="" (
    echo [?] Enter your Discord Webhook or Laptop Backend URL to receive the remote link:
    echo     (Leave blank and press ENTER if you do not have one right now)
    set /p "REPORT_URL=> "
)

echo.
echo [*] Executing automated cloud setup script...
echo.

if not "%REPORT_URL%"=="" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" -ReportUrl "%REPORT_URL%"
) else (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
)

echo.
echo ========================================================
echo [OK] Setup completed! Project-X-Nano agent is active.
echo ========================================================
echo.
pause
