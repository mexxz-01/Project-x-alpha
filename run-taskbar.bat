@echo off
REM Launches RemotePC minimized on the Windows Taskbar
cd /d "%~dp0"
if exist "%~dp0dist\RemotePC.exe" (
    start "RemotePC" /min "%~dp0dist\RemotePC.exe"
) else (
    start "RemotePC" /min python server.py
)
