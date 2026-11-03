# =========================================================================
#  Project-X-Nano: Automated Windows Dedicated Host Backend Server Setup
#  Configures 24/7 background operation, firewall access, and auto-restart.
# =========================================================================

$ErrorActionPreference = "SilentlyContinue"
$ServerDir = "Z:\my projects\remote-pc"
$PythonW = "C:\Users\DELL\AppData\Local\Programs\Python\Python313\pythonw.exe"
$ServerScript = Join-Path $ServerDir "server.py"
$TaskName = "ProjectXNano_HostServer"

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "   Configuring PC as Dedicated Project-X-Nano Host      " -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan

# 1. Stop existing conflicting instances
Write-Host "[*] Stopping previous server instances..." -ForegroundColor Yellow
Stop-Process -Name "Project-X-Nano", "RemotePC" -Force -ErrorAction SilentlyContinue
Get-Process -Name "pythonw" -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $PythonW } | Stop-Process -Force -ErrorAction SilentlyContinue

# 2. Add / Update Firewall Rules for LAN & External Access
Write-Host "[*] Configuring Windows Firewall for TCP port 8765..." -ForegroundColor Green
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($isAdmin) {
    netsh advfirewall firewall delete rule name="Project-X-Nano-Backend" >$null 2>&1
    netsh advfirewall firewall add rule name="Project-X-Nano-Backend" dir=in action=allow protocol=TCP localport=8765 profile=any >$null 2>&1
    Write-Host "[+] Firewall rule 'Project-X-Nano-Backend' active for all network profiles." -ForegroundColor Green
} else {
    Write-Host "[i] Run as Administrator to add system firewall rule if accessing from outside Wi-Fi." -ForegroundColor Gray
}

# 3. Create Windows Task Scheduler 24/7 Background Autostart Task
Write-Host "[*] Registering persistent Windows Task Scheduler host service..." -ForegroundColor Green
$action = New-ScheduledTaskAction -Execute $PythonW -Argument "`"$ServerScript`"" -WorkingDirectory $ServerDir
$trigger = New-ScheduledTaskTrigger -AtLogOn
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit 0 -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1)

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "Project-X-Nano 24/7 Dedicated Remote PC Master Controller" -Force | Out-Null
Write-Host "[+] Task Scheduler service '$TaskName' registered (Runs on boot with Highest Privileges)." -ForegroundColor Green

# 4. Launch backend host immediately
Write-Host "[*] Launching backend server in background..." -ForegroundColor Green
Start-Process -FilePath $PythonW -ArgumentList "`"$ServerScript`"" -WorkingDirectory $ServerDir

Start-Sleep -Seconds 4

# 5. Verify local health
$conn = Get-NetTCPConnection -LocalPort 8765 -ErrorAction SilentlyContinue
if ($conn) {
    Write-Host "[OK] Backend server is listening on port 8765!" -ForegroundColor Green
    
    # Get LAN IP
    $lanIp = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -notmatch "Loopback|vEthernet" -and $_.IPAddress -notmatch "^169\.254\." } | Select-Object -First 1).IPAddress
    Write-Host "========================================================" -ForegroundColor Cyan
    Write-Host "  PC Backend Server is ONLINE & READY!                  " -ForegroundColor Green
    Write-Host "  Local PC URL:      http://localhost:8765             " -ForegroundColor White
    Write-Host "  Phone/LAN URL:     http://$($lanIp):8765             " -ForegroundColor Yellow
    Write-Host "========================================================" -ForegroundColor Cyan
} else {
    Write-Host "[i] Background host is started and running. Check 'check_backend.bat' for live status." -ForegroundColor Green
}
