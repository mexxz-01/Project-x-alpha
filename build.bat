@echo off
REM Builds RemotePC.exe (run this on your Windows PC, needs Python installed)
REM   build.bat         -> normal exe
REM   build.bat admin   -> exe that always starts as Administrator (Windows shows a UAC prompt on start)
set UAC=
if /i "%1"=="admin" set UAC=--uac-admin
pip install -r requirements.txt pyinstaller
pyinstaller --onefile --name RemotePC %UAC% ^
  --collect-submodules pycaw --collect-submodules comtypes ^
  --collect-submodules screen_brightness_control ^
  server.py
echo.
echo Done! Your program is dist\RemotePC.exe  (double-click it to start)
echo config.json and the first-run password are created next to the exe.
echo Tip: run it once normally to see the password, then turn on "Start with PC" in the app.
pause
