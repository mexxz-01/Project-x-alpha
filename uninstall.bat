@echo off
title Project-X-Nano Uninstaller
echo ========================================================
echo             Project-X-Nano Clean Uninstaller
echo ========================================================
echo.

echo [*] Stopping running processes...
taskkill /F /IM Project-X-Nano.exe >nul 2>&1
taskkill /F /IM RemotePC.exe >nul 2>&1
for /f "tokens=2" %%i in ('wmic process where "commandline like '%%server.py%%'" get processid ^| findstr [0-9]') do (
    taskkill /F /PID %%i >nul 2>&1
)

echo [*] Removing Windows Autostart Registry keys...
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "Project-X-Nano" /f >nul 2>&1
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "RemotePC" /f >nul 2>&1

echo [*] Removing Windows Scheduled Tasks (if any)...
schtasks /Delete /TN "Project-X-Nano" /F >nul 2>&1
schtasks /Delete /TN "RemotePC" /F >nul 2>&1

echo [*] Removing Windows Firewall rules (if any)...
netsh advfirewall firewall delete rule name="Project-X-Nano" >nul 2>&1
netsh advfirewall firewall delete rule name="RemotePC" >nul 2>&1

echo [*] Deleting installation folders and files...
if exist "%LOCALAPPDATA%\Project-X-Nano" rmdir /s /q "%LOCALAPPDATA%\Project-X-Nano" >nul 2>&1
if exist "%LOCALAPPDATA%\RemotePC" rmdir /s /q "%LOCALAPPDATA%\RemotePC" >nul 2>&1
if exist "C:\RemotePC" rmdir /s /q "C:\RemotePC" >nul 2>&1

echo.
echo ========================================================
echo [OK] Project-X-Nano has been completely uninstalled!
echo ========================================================
echo.
pause
