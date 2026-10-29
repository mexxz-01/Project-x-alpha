@echo off
title RemotePC Uninstaller
echo ========================================================
echo               RemotePC Clean Uninstaller
echo ========================================================
echo.

echo [*] Stopping running RemotePC processes...
taskkill /F /IM RemotePC.exe >nul 2>&1
for /f "tokens=2" %%i in ('wmic process where "commandline like '%%server.py%%'" get processid ^| findstr [0-9]') do (
    taskkill /F /PID %%i >nul 2>&1
)

echo [*] Removing Windows Autostart Registry key...
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "RemotePC" /f >nul 2>&1

echo [*] Removing Windows Scheduled Tasks (if any)...
schtasks /Delete /TN "RemotePC" /F >nul 2>&1

echo [*] Removing Windows Firewall rules (if any)...
netsh advfirewall firewall delete rule name="RemotePC" >nul 2>&1

echo.
echo ========================================================
echo [OK] RemotePC has been completely uninstalled and stopped!
echo      - Background tasks: TERMINATED
echo      - Autostart startup: REMOVED
echo      - Scheduled tasks: REMOVED
echo ========================================================
echo.
pause
