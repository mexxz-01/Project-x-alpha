@echo off
setlocal enabledelayedexpansion
title Project-X-Nano Cloud Fleet Installer

echo ========================================================
echo        Project-X-Nano 1-Click Cloud Agent Installer    
echo ========================================================
echo.
echo [*] Launching automated cyber installation...
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"

echo.
echo ========================================================
echo [OK] Setup completed! Project-X-Nano is connected.
echo ========================================================
echo.
pause
