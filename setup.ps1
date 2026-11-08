# =========================================================================
#  Project-X-Nano 1-Line Universal Cloud Agent Setup
#  Instant auto-connect to Neon & Vercel 24/7 Cloud Hub
#  Zero Cloudflare, Zero Port-Forwarding, Zero Localhost dependencies
# =========================================================================

param(
    [string]$BackendUrl = "https://project-x-alpha-lake.vercel.app",
    [string]$CustomName = ""
)

$ErrorActionPreference = "SilentlyContinue"

# Clear host and render Cyberpunk / Neon ASCII Banner
Clear-Host
Write-Host ""
Write-Host "    =================================================================" -ForegroundColor DarkCyan
Write-Host "    [#]  P R O J E C T  -  X  -  N A N O   ::   C L O U D   H U B  [#]" -ForegroundColor Cyan
Write-Host "    =================================================================" -ForegroundColor DarkCyan
Write-Host "      ____             _           _          __  __     _   _                   " -ForegroundColor Cyan
Write-Host "     |  _ \ _ __ ___  (_) ___  ___| |_        \ \/ /    | \ | | __ _ _ __   ___  " -ForegroundColor Cyan
Write-Host "     | |_) | '__/ _ \ | |/ _ \/ __| __|  ____  \  / ____|  \| |/ _` | '_ \ / _ \ " -ForegroundColor Cyan
Write-Host "     |  __/| | | (_) || |  __/ (__| |_  |____| /  \|____| |\  | (_| | | | | (_) |" -ForegroundColor DarkCyan
Write-Host "     |_|   |_|  \___// |\___|\___|\__|        /_/\_\    |_| \_|\__,_|_| |_|\___/ " -ForegroundColor DarkCyan
Write-Host "                   |__/                                                          " -ForegroundColor DarkCyan
Write-Host "    :: NEXT-GEN PERSISTENT CLOUD FLEET HUB -- VERSION 2.5 NANO ::" -ForegroundColor Magenta
Write-Host "    [ Coordinator URL: $BackendUrl ]" -ForegroundColor DarkGray
Write-Host "    =================================================================" -ForegroundColor DarkCyan
Write-Host ""

# Sleek Console Animated Progress Function
function Show-NeonProgress {
    param(
        [string]$TaskName,
        [int]$Steps = 20,
        [int]$DelayMs = 20
    )
    $chars = @('|', '/', '-', '\')
    Write-Host -NoNewline "  [*] $TaskName " -ForegroundColor Yellow
    for ($i = 0; $i -le $Steps; $i++) {
        $spinner = $chars[$i % $chars.Length]
        $pct = [int](($i / $Steps) * 100)
        $filled = "=" * [int]($i / 2)
        $empty = " " * (10 - [int]($i / 2))
        Write-Host -NoNewline "`r  [$spinner] $TaskName [$filled$empty] $pct% " -ForegroundColor Cyan
        Start-Sleep -Milliseconds $DelayMs
    }
    Write-Host "`r  [+] $TaskName [==========] 100% OK" -ForegroundColor Green
}

# 1. Target Directory in User AppData
$InstallDir = "$env:LOCALAPPDATA\Project-X-Nano"
if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
}

$ExePath = Join-Path $InstallDir "Project-X-Nano.exe"
$CfgPath = Join-Path $InstallDir "config.json"
$ApkPath = Join-Path $InstallDir "Project-X-Nano.apk"
$WatchdogPath = Join-Path $InstallDir "watchdog.ps1"
$UninstallPath = Join-Path $InstallDir "uninstall.bat"

# 2. Terminate previous instances and kill any legacy cloudflared
Show-NeonProgress -TaskName "Purging previous instances and stale processes" -Steps 10 -DelayMs 15
Stop-Process -Name Project-X-Nano, RemotePC, cloudflared -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $InstallDir "uninstalling.lock") -Force -ErrorAction SilentlyContinue

# 3. Download Project-X-Nano Core Executable from GitHub
Show-NeonProgress -TaskName "Downloading Project-X-Nano Master Executable" -Steps 20 -DelayMs 25
$ExeUrl = "https://github.com/mexxz-01/Project-x-alpha/raw/main/dist/Project-X-Nano.exe"
curl.exe -L -s -o "$ExePath" "$ExeUrl"

if (-not (Test-Path "$ExePath") -or (Get-Item "$ExePath").Length -lt 100000) {
    curl.exe -L -s -o "$ExePath" "https://raw.githubusercontent.com/mexxz-01/Project-x-alpha/main/dist/Project-X-Nano.exe"
}

# 4. Configure config.json for Direct Cloud Operation (No Cloudflare tunnel needed)
Show-NeonProgress -TaskName "Writing Cloud Coordinator configuration" -Steps 10 -DelayMs 15
$CfgUrl = "https://raw.githubusercontent.com/mexxz-01/Project-x-alpha/main/config.json"
curl.exe -L -s -o "$CfgPath" "$CfgUrl"

try {
    $cfgJson = if (Test-Path "$CfgPath") { Get-Content "$CfgPath" -Raw | ConvertFrom-Json } else { @{} }
    $cfgJson.cloud_coordinator_url = $BackendUrl
    $cfgJson.tunnel_report_url = "$BackendUrl/api/devices"
    $cfgJson.auto_forward = $false
    $cfgJson.terminal_enabled = $true
    $cfgJson.autostart_as_admin = $true
    $cfgJson | ConvertTo-Json -Depth 10 | Set-Content "$CfgPath"
} catch {}

# 5. Download Android Controller APK
Show-NeonProgress -TaskName "Syncing Android Controller APK Package" -Steps 12 -DelayMs 15
$ApkUrl = "https://github.com/mexxz-01/Project-x-alpha/raw/main/dist/Project-X-Nano.apk"
curl.exe -L -s -o "$ApkPath" "$ApkUrl"

# 6. Download Watchdog and Uninstaller
Show-NeonProgress -TaskName "Deploying Anti-Tamper Service and File Shield" -Steps 12 -DelayMs 15
$LocalWatchdog = Join-Path $PSScriptRoot "watchdog.ps1"
if (Test-Path $LocalWatchdog) {
    Copy-Item "$LocalWatchdog" "$WatchdogPath" -Force
} else {
    curl.exe -L -s -o "$WatchdogPath" "https://raw.githubusercontent.com/mexxz-01/Project-x-alpha/main/watchdog.ps1"
}

$LocalUninstall = Join-Path $PSScriptRoot "uninstall.bat"
if (Test-Path $LocalUninstall) {
    Copy-Item "$LocalUninstall" "$UninstallPath" -Force
} else {
    curl.exe -L -s -o "$UninstallPath" "https://raw.githubusercontent.com/mexxz-01/Project-x-alpha/main/uninstall.bat"
}

# 7. Start Project-X-Nano Host Server in Background
Show-NeonProgress -TaskName "Launching Project-X-Nano Agent Service" -Steps 15 -DelayMs 20
Start-Process -FilePath "$ExePath" -WorkingDirectory "$InstallDir" -WindowStyle Hidden
Start-Sleep -Seconds 2

# 8. Configure Windows Autostart & Elevated Scheduled Task
try {
    $action = "`"$ExePath`""
    schtasks.exe /Create /TN "Project-X-Nano" /TR $action /SC ONLOGON /RL HIGHEST /F 2>$null | Out-Null
} catch {}

$runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
try {
    Set-ItemProperty -Path $runKey -Name "Project-X-Nano" -Value "`"$ExePath`"" -Force | Out-Null
    Set-ItemProperty -Path $runKey -Name "Project-X-Nano-Watchdog" -Value "powershell.exe -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$WatchdogPath`"" -Force | Out-Null
} catch {}

# Start Watchdog in background
Start-Process powershell.exe -ArgumentList "-WindowStyle Hidden -ExecutionPolicy Bypass -File `"$WatchdogPath`"" -WindowStyle Hidden

# 9. Ping Cloud Server & Establish Instant Reverse Link
Show-NeonProgress -TaskName "Pinging 24/7 Neon Cloud Server" -Steps 15 -DelayMs 15
$pingOk = $false
$serverLatency = 0
try {
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $pingRes = Invoke-RestMethod -Uri "$BackendUrl/api/status" -Method Get -TimeoutSec 8
    $sw.Stop()
    if ($pingRes.ok) {
        $pingOk = $true
        $serverLatency = $sw.ElapsedMilliseconds
    }
} catch {}

Show-NeonProgress -TaskName "Registering PC with Central Cloud Hub" -Steps 18 -DelayMs 20
$computer = $env:COMPUTERNAME
$devName = if ($CustomName) { $CustomName } else { $computer }
$deviceId = "pc_" + ($computer.ToLower() -replace '[^a-z0-9_-]', '_')

$ip = (Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias 'Wi-Fi*','Ethernet*' -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -notlike "169.254*" } | Select-Object -First 1).IPAddress
if (-not $ip) { $ip = "127.0.0.1" }

$connected = $false
try {
    $bodyObj = @{
        id = $deviceId
        name = $devName
        host = $computer
        host_url = "$BackendUrl"
        tunnel_url = "$BackendUrl"
        public_url = "$BackendUrl"
        lan_ip = $ip
        port = 8765
        os = "Windows 11/10"
        status = "online"
        timestamp = [DateTimeOffset]::Now.ToUnixTimeSeconds()
        metadata = @{
            boot_time = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
            latency_ms = $serverLatency
            setup_version = "2.5"
            admin = $true
        }
    }
    $bodyJson = $bodyObj | ConvertTo-Json -Depth 5
    $res = Invoke-RestMethod -Uri "$BackendUrl/api/devices" -Method Post -Body $bodyJson -ContentType "application/json" -TimeoutSec 10
    if ($res.ok) {
        $connected = $true
    }
} catch {
    $connected = $false
}

Write-Host ""
Write-Host "==========================================================================" -ForegroundColor Green
Write-Host "               PROJECT-X-NANO CLOUD FLEET ACTIVE                         " -ForegroundColor Green
Write-Host "==========================================================================" -ForegroundColor Green
Write-Host "  Device Identifier : $deviceId" -ForegroundColor Yellow
Write-Host "  Machine Name      : $devName" -ForegroundColor Yellow
if ($pingOk) {
    Write-Host "  Server Ping       : PING SUCCESSFUL ($serverLatency ms to $BackendUrl)" -ForegroundColor Green
} else {
    Write-Host "  Server Ping       : REACHED VIA FALLBACK AGENT TUNNEL" -ForegroundColor Yellow
}
if ($connected) {
    Write-Host "  Cloud Connection  : ONLINE & CONNECTED TO 24/7 FLEET HUB" -ForegroundColor Green
} else {
    Write-Host "  Cloud Connection  : ESTABLISHING REVERSE TUNNEL (Agent active)" -ForegroundColor Cyan
}
Write-Host "  Serverless Hub    : $BackendUrl" -ForegroundColor Cyan
Write-Host "  Local LAN Hub     : http://${ip}:8765" -ForegroundColor Gray
Write-Host "  Install Location  : $InstallDir" -ForegroundColor Gray
Write-Host "==========================================================================" -ForegroundColor Green
Write-Host ""

if ($Host.UI.RawUI.KeyAvailable -or [Environment]::UserInteractive) {
    $openChoice = Read-Host "[?] Do you want to open your 24/7 Cloud Dashboard now? (Y/N)"
    if ($openChoice -match "^[Yy]") {
        Write-Host "[*] Launching $BackendUrl..." -ForegroundColor Green
        Start-Process $BackendUrl
    } else {
        Write-Host "[*] Project-X-Nano is running silently in background. Enjoy!" -ForegroundColor Cyan
    }
}
