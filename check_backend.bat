@echo off
setlocal
echo ========================================================
echo       Project-X-Nano Host Backend Server Health Check
echo ========================================================
powershell -NoProfile -Command ^
  "$conn = Get-NetTCPConnection -LocalPort 8765 -ErrorAction SilentlyContinue; if ($conn) { Write-Host '[+] Backend Server Port 8765 is ACTIVE and LISTENING' -ForegroundColor Green; $conn | Format-Table -AutoSize } else { Write-Host '[-] Port 8765 is NOT listening' -ForegroundColor Red }"
echo.
echo [*] Testing HTTP Response from http://127.0.0.1:8765/manifest.json...
powershell -NoProfile -Command ^
  "try { $r = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/manifest.json' -TimeoutSec 3; Write-Host ('[+] Server Responded OK: ' + $r.name) -ForegroundColor Green } catch { Write-Host ('[-] Server not responding: ' + $_.Exception.Message) -ForegroundColor Red }"
echo ========================================================
pause
endlocal
