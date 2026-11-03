@echo off
setlocal
cd /d "Z:\my projects\remote-pc"
echo ========================================================
echo       Starting Project-X-Nano Host Backend Server
echo ========================================================
set PYTHONW="C:\Users\DELL\AppData\Local\Programs\Python\Python313\pythonw.exe"
if not exist %PYTHONW% set PYTHONW=pythonw.exe

start "" /d "Z:\my projects\remote-pc" %PYTHONW% "Z:\my projects\remote-pc\server.py"
ping 127.0.0.1 -n 3 >nul
echo [OK] Backend server launched in background on port 8765.
echo [*] Open in browser: http://localhost:8765
endlocal
