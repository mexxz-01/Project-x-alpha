# Project-X-Nano 1-Line Universal Setup Script
$ErrorActionPreference = "SilentlyContinue"

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "          Project-X-Nano Automated Fleet Setup          " -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan

# 1. Install to user AppData
$InstallDir = "$env:LOCALAPPDATA\Project-X-Nano"
if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
}

$ExePath = Join-Path $InstallDir "Project-X-Nano.exe"
$CfgPath = Join-Path $InstallDir "config.json"
$ApkPath = Join-Path $InstallDir "Project-X-Nano.apk"

# 2. Stop any running instance
Stop-Process -Name Project-X-Nano, RemotePC, Project-X-Nano -Force -ErrorAction SilentlyContinue

# 3. Download executable
Write-Host "[*] Downloading Project-X-Nano.exe..." -ForegroundColor Green
$ExeUrl = "https://github.com/mexxz-01/Project-x-alpha/raw/main/dist/Project-X-Nano.exe"
curl.exe -L -o "$ExePath" "$ExeUrl"
if (-not (Test-Path "$ExePath")) {
    $FallbackUrl = "https://github.com/mexxz-01/Project-x-alpha/raw/main/dist/Project-X-Nano.exe"
    curl.exe -L -o "$ExePath" "$FallbackUrl"
}

# 4. Download config
Write-Host "[*] Configuring security settings..." -ForegroundColor Green
$CfgUrl = "https://raw.githubusercontent.com/mexxz-01/Project-x-alpha/main/config.json"
curl.exe -L -o "$CfgPath" "$CfgUrl"

# 5. Download Android APK
Write-Host "[*] Downloading Android Controller APK..." -ForegroundColor Green
$ApkUrl = "https://github.com/mexxz-01/Project-x-alpha/raw/main/dist/Project-X-Nano.apk"
curl.exe -L -o "$ApkPath" "$ApkUrl"

# 6. Firewall rule (if admin, otherwise skip gracefully)
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($isAdmin) {
    netsh advfirewall firewall add rule name="Project-X-Nano" dir=in action=allow protocol=TCP localport=8765 >$null 2>&1
}

# 7. Launch Project-X-Nano as background process (no console window)
Write-Host "[*] Starting Project-X-Nano in background..." -ForegroundColor Green
Start-Process -FilePath "$ExePath" -WorkingDirectory "$InstallDir" -WindowStyle Hidden

# 7b. Register Windows Autostart (starts automatically on PC startup with port forwarding)
$runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$runName = "Project-X-Nano"
$runValue = "`"$ExePath`" --forward"
try {
    Set-ItemProperty -Path $runKey -Name $runName -Value $runValue -Force | Out-Null
    Write-Host "[*] Windows Startup configured with --forward" -ForegroundColor Green
} catch {
    Write-Host "[!] Could not set autostart registry key: $_" -ForegroundColor Yellow
}

# 8. Detect local Wi-Fi IP
$ip = (Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias 'Wi-Fi*','Ethernet*' -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -notlike "169.254*" } | Select-Object -First 1).IPAddress
if (-not $ip) { $ip = "127.0.0.1" }

Write-Host ""
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host " [SUCCESS] Project-X-Nano is installed and running!     " -ForegroundColor Green
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host " Local Web URL:    http://localhost:8765" -ForegroundColor Yellow
Write-Host " Network URL:      http://$($ip):8765" -ForegroundColor Yellow
Write-Host " Android APK:      http://$($ip):8765/download/apk" -ForegroundColor Yellow
Write-Host " Install Folder:   $InstallDir" -ForegroundColor Gray
Write-Host "========================================================" -ForegroundColor Cyan

Start-Sleep -Seconds 1
Start-Process "http://localhost:8765"
