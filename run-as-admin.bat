@echo off
REM Starts RemotePC with Administrator rights (Windows will ask you to click "Yes" once, on the PC).
cd /d "%~dp0"
powershell -NoProfile -Command "Start-Process python -ArgumentList 'server.py' -Verb RunAs -WorkingDirectory '%~dp0'"
