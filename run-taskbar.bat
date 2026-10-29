@echo off
REM Launches RemotePC minimized on the Windows Taskbar as Administrator
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process cmd.exe -ArgumentList '/c \"\"%~dp0run-as-admin.bat\"\"' -WindowStyle Hidden"
