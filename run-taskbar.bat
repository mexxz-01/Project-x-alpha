@echo off
REM Launches Project-X-Nano as background process
cd /d "%~dp0"
if exist "%~dp0dist\Project-X-Nano.exe" (
    start "Project-X-Nano" "%~dp0dist\Project-X-Nano.exe"
) else if exist "%~dp0dist\RemotePC.exe" (
    start "Project-X-Nano" "%~dp0dist\RemotePC.exe"
) else (
    start "Project-X-Nano" python server.py
)
