@echo off
title Build RemotePC Android Controller APK
cd /d "%~dp0"
echo ========================================================
echo       Building RemotePC Android Controller APK
echo ========================================================
python android\build_apk.py
echo.
pause
