# RemotePC 1-Line Universal Setup Script
$ErrorActionPreference = "SilentlyContinue"

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "            RemotePC Automated Fleet Setup              " -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan

# 1. Install to user AppData (Zero elevation required, no Access Denied)
$InstallDir = "$env:LOCALAPPDATA\RemotePC"
if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
}

$ExePath = Join-Path $InstallDir "RemotePC.exe"
$CfgPath = Join-Path $InstallDir "config.json"
$ApkPath = Join-Path $InstallDir "RemotePC-Controller.apk"

# 2. Stop any running instance
Stop-Process -Name RemotePC -Force -ErrorAction SilentlyContinue

# 3. Download executable
Write-Host "[*] Downloading RemotePC.exe..." -ForegroundColor Green
$ExeUrl = "https://github.com/mexxz-01/Project-x-alpha/raw/main/dist/RemotePC.exe"
curl.exe -L -o "$ExePath" "$ExeUrl"

# 4. Download config
Write-Host "[*] Setting credentials (Password: mexxz@2007)..." -ForegroundColor Green
$CfgUrl = "https://raw.githubusercontent.com/mexxz-01/Project-x-alpha/main/config.json"
curl.exe -L -o "$CfgPath" "$CfgUrl"

# 5. Download Android APK
Write-Host "[*] Downloading Android Controller APK..." -ForegroundColor Green
$ApkUrl = "https://github.com/mexxz-01/Project-x-alpha/raw/main/RemotePC-Controller.apk"
curl.exe -L -o "$ApkPath" "$ApkUrl"

# 6. Firewall rule (if admin, otherwise skip gracefully)
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($isAdmin) {
    netsh advfirewall firewall add rule name="RemotePC" dir=in action=allow protocol=TCP localport=8765 >$null 2>&1
}

# 7. Launch RemotePC in background/taskbar
Write-Host "[*] Starting RemotePC..." -ForegroundColor Green
Start-Process -FilePath "$ExePath" -WorkingDirectory "$InstallDir" -WindowStyle Minimized

# 8. Detect local Wi-Fi IP
$ip = (Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias 'Wi-Fi*','Ethernet*' -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -notlike "169.254*" } | Select-Object -First 1).IPAddress
if (-not $ip) { $ip = "127.0.0.1" }

Write-Host ""
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host " [SUCCESS] RemotePC is installed and running!           " -ForegroundColor Green
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host " Local Web URL:    http://localhost:8765" -ForegroundColor Yellow
Write-Host " Network URL:      http://$($ip):8765" -ForegroundColor Yellow
Write-Host " Master Password:  mexxz@2007" -ForegroundColor Yellow
Write-Host " Android APK:      http://$($ip):8765/download/apk" -ForegroundColor Yellow
Write-Host " Install Folder:   $InstallDir" -ForegroundColor Gray
Write-Host "========================================================" -ForegroundColor Cyan

Start-Sleep -Seconds 1
Start-Process "http://localhost:8765"
