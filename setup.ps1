# RemotePC 1-Line Universal Setup Script
$ErrorActionPreference = "Stop"

# 1. Elevate to Administrator if needed
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "[*] Requesting Administrator Privileges..." -ForegroundColor Yellow
    Start-Process powershell -ArgumentList "-NoProfile -ExecutionPolicy Bypass -Command `"irm https://raw.githubusercontent.com/mexxz-01/Project-x-alpha/main/setup.ps1 | iex`"" -Verb RunAs
    exit
}

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "            RemotePC Automated Fleet Setup              " -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan

$InstallDir = "C:\RemotePC"
if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
}

$ExePath = Join-Path $InstallDir "RemotePC.exe"
$CfgPath = Join-Path $InstallDir "config.json"
$ApkPath = Join-Path $InstallDir "RemotePC-Controller.apk"

# 2. Download executable from GitHub
Write-Host "[*] Downloading RemotePC.exe..." -ForegroundColor Green
$ExeUrl = "https://github.com/mexxz-01/Project-x-alpha/raw/main/dist/RemotePC.exe"
curl.exe -L -o $ExePath $ExeUrl

# 3. Download config.json
Write-Host "[*] Configuring credentials (Password: mexxz@2007)..." -ForegroundColor Green
$CfgUrl = "https://raw.githubusercontent.com/mexxz-01/Project-x-alpha/main/config.json"
curl.exe -L -o $CfgPath $CfgUrl

# 4. Download Android APK
Write-Host "[*] Downloading Android Controller APK..." -ForegroundColor Green
$ApkUrl = "https://github.com/mexxz-01/Project-x-alpha/raw/main/RemotePC-Controller.apk"
curl.exe -L -o $ApkPath $ApkUrl

# 5. Open Windows Firewall for port 8765
Write-Host "[*] Allowing port 8765 in Windows Firewall..." -ForegroundColor Green
netsh advfirewall firewall delete rule name="RemotePC" >$null 2>&1
netsh advfirewall firewall add rule name="RemotePC" dir=in action=allow protocol=TCP localport=8765 >$null 2>&1

# 6. Stop any previous instance and launch minimized
Stop-Process -Name RemotePC -Force -ErrorAction SilentlyContinue
Write-Host "[*] Launching RemotePC in background..." -ForegroundColor Green
Start-Process -FilePath $ExePath -WorkingDirectory $InstallDir -WindowStyle Minimized

# 7. Get local IP
$ip = (Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias 'Wi-Fi*','Ethernet*' -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -notlike "169.254*" } | Select-Object -First 1).IPAddress
if (-not $ip) { $ip = "127.0.0.1" }

Write-Host ""
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host " [SUCCESS] RemotePC is installed and running as Admin!  " -ForegroundColor Green
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host " Local Web URL:    http://localhost:8765" -ForegroundColor Yellow
Write-Host " Network URL:      http://$($ip):8765" -ForegroundColor Yellow
Write-Host " Master Password:  mexxz@2007" -ForegroundColor Yellow
Write-Host " Android APK:      http://$($ip):8765/download/apk" -ForegroundColor Yellow
Write-Host "========================================================" -ForegroundColor Cyan

Start-Sleep -Seconds 1
Start-Process "http://localhost:8765"
