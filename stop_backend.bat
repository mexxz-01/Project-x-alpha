@echo off
setlocal
echo [*] Terminating Project-X-Nano backend processes...
taskkill /F /IM "Project-X-Nano.exe" >nul 2>&1
taskkill /F /IM "RemotePC.exe" >nul 2>&1
wmic process where "commandline like '%%server.py%%'" delete >nul 2>&1
echo [OK] Backend server stopped.
endlocal
