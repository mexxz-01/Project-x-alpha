@echo off
title Project-X-Nano Uninstaller
setlocal enabledelayedexpansion

echo ========================================================
echo             Project-X-Nano Clean Uninstaller
echo ========================================================
echo.
echo [!] Warning: This will stop and remove Project-X-Nano,
echo     Cloudflare Tunnel, and the Persistent Watchdog.
echo.

set /p "CONFIRM=Are you sure you want to completely uninstall? (Y/N): "
if /i not "%CONFIRM%"=="Y" (
    echo [!] Uninstallation canceled by user.
    pause
    exit /b 0
)

echo.
echo [*] Authorizing shutdown signal...
:: Create unlock token so watchdog knows not to respawn
if exist "%LOCALAPPDATA%\Project-X-Nano" (
    echo unlocked > "%LOCALAPPDATA%\Project-X-Nano\uninstalling.lock"
)
echo unlocked > "%~dp0uninstalling.lock" 2>nul

echo [*] Stopping Watchdog service...
powershell.exe -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"CommandLine LIKE '%%watchdog%%'\" | Invoke-CimMethod -MethodName Terminate" >nul 2>&1

echo [*] Stopping running processes...
taskkill /F /IM Project-X-Nano.exe >nul 2>&1
taskkill /F /IM RemotePC.exe >nul 2>&1
taskkill /F /IM cloudflared.exe >nul 2>&1
powershell.exe -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"CommandLine LIKE '%%server.py%%'\" | Invoke-CimMethod -MethodName Terminate" >nul 2>&1

echo [*] Removing Windows Autostart Registry keys...
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "Project-X-Nano" /f >nul 2>&1
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "Project-X-Nano-Watchdog" /f >nul 2>&1
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "RemotePC" /f >nul 2>&1

echo [*] Removing Windows Scheduled Tasks (if any)...
schtasks /Delete /TN "Project-X-Nano" /F >nul 2>&1
schtasks /Delete /TN "Project-X-Nano-Watchdog" /F >nul 2>&1
schtasks /Delete /TN "RemotePC" /F >nul 2>&1

echo [*] Removing Windows Firewall rules (if any)...
netsh advfirewall firewall delete rule name="Project-X-Nano" >nul 2>&1
netsh advfirewall firewall delete rule name="RemotePC" >nul 2>&1

echo [*] Deleting installation folders and files...
timeout /t 2 /nobreak >nul
if exist "%LOCALAPPDATA%\Project-X-Nano" rmdir /s /q "%LOCALAPPDATA%\Project-X-Nano" >nul 2>&1
if exist "%LOCALAPPDATA%\RemotePC" rmdir /s /q "%LOCALAPPDATA%\RemotePC" >nul 2>&1
if exist "C:\RemotePC" rmdir /s /q "C:\RemotePC" >nul 2>&1

echo.
echo ========================================================
echo [OK] Project-X-Nano has been cleanly uninstalled!
echo ========================================================
echo.
pause
