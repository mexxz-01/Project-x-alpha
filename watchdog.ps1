# =========================================================================
#  Project-X-Nano Persistent Watchdog & Reverse Cloud Agent Loop
#  Ensures 24/7 reverse connection to Vercel & Neon Postgres Cloud Fleet Hub.
#  Reports real-time CPU, RAM, Battery, OS, Admin status every 15 seconds.
#  Supervises Cloudflare Tunnel for direct 0-config global remote access.
#  Executes queued remote fleet commands with zero port forwarding.
# =========================================================================

param(
    [string]$TargetDir = "",
    [string]$BackendUrl = "https://project-x-alpha-lake.vercel.app"
)

$ErrorActionPreference = "SilentlyContinue"

# 1. Resolve working directory
if (-not $TargetDir -or -not (Test-Path $TargetDir)) {
    $TargetDir = Split-Path -Parent $MyInvocation.MyCommand.Path
}
if (-not (Test-Path $TargetDir)) {
    $TargetDir = "$env:LOCALAPPDATA\Project-X-Nano"
}

$ExePath = Join-Path $TargetDir "Project-X-Nano.exe"
$CfgPath = Join-Path $TargetDir "config.json"
$CloudflaredExe = Join-Path $TargetDir "cloudflared.exe"
$CloudflaredLog = Join-Path $TargetDir "cloudflared.log"
$PublicUrlFile = Join-Path $TargetDir "public_url.txt"
$UnlockFile = Join-Path $TargetDir "uninstalling.lock"

# Read Backend URL from config.json if available
if (Test-Path $CfgPath) {
    try {
        $cfgData = Get-Content $CfgPath -Raw | ConvertFrom-Json
        if ($cfgData.cloud_coordinator_url) {
            $BackendUrl = $cfgData.cloud_coordinator_url.TrimEnd('/')
        }
    } catch {}
}

$GITHUB_RAW_BASE = "https://raw.githubusercontent.com/mexxz-01/Project-x-alpha/main"
$EXE_URL = "https://github.com/mexxz-01/Project-x-alpha/raw/main/dist/Project-X-Nano.exe"

$computer = $env:COMPUTERNAME
$devName = $computer
$deviceId = "pc_" + ($computer.ToLower() -replace '[^a-z0-9_-]', '_')

function Get-TunnelUrl {
    if (Test-Path $PublicUrlFile) {
        $u = (Get-Content $PublicUrlFile -Raw).Trim()
        if ($u -match "https://[a-zA-Z0-9-]+\.trycloudflare\.com") {
            return $u
        }
    }
    if (Test-Path $CloudflaredLog) {
        $m = Select-String -Path $CloudflaredLog -Pattern "https://[a-zA-Z0-9-]+\.trycloudflare\.com" | Select-Object -Last 1
        if ($m) {
            $u = $m.Matches[0].Value
            Set-Content $PublicUrlFile -Value $u -Force
            return $u
        }
    }
    return ""
}

function Ensure-TunnelAndServer {
    if (Test-Path $UnlockFile) { return }

    # 1. Ensure Local Server is running
    $procServer = Get-Process -Name "Project-X-Nano", "RemotePC" -ErrorAction SilentlyContinue
    $pythonServer = Get-CimInstance Win32_Process -Filter "CommandLine LIKE '%server.py%'" -ErrorAction SilentlyContinue

    if (-not $procServer -and -not $pythonServer) {
        if (Test-Path (Join-Path $TargetDir "server.py")) {
            Start-Process -FilePath "python.exe" -ArgumentList "server.py --no-elevate" -WorkingDirectory "$TargetDir" -WindowStyle Hidden
        } elseif (Test-Path $ExePath) {
            Start-Process -FilePath "$ExePath" -WorkingDirectory "$TargetDir" -WindowStyle Hidden
        }
    }

    # 2. Ensure Cloudflare Tunnel is running
    $procTunnel = Get-Process -Name "cloudflared" -ErrorAction SilentlyContinue
    if (-not $procTunnel -and (Test-Path $CloudflaredExe)) {
        Start-Process -FilePath "$CloudflaredExe" -ArgumentList "tunnel --url http://127.0.0.1:8765 --logfile `"$CloudflaredLog`"" -WorkingDirectory "$TargetDir" -WindowStyle Hidden
    }
}

function Send-FleetHeartbeat {
    try {
        $ip = (Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias 'Wi-Fi*','Ethernet*' -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -notlike "169.254*" } | Select-Object -First 1).IPAddress
        if (-not $ip) { $ip = "127.0.0.1" }

        $tunnelUrl = Get-TunnelUrl
        $activeUrl = if ($tunnelUrl) { $tunnelUrl } else { $BackendUrl }

        # System Metrics
        $cpuLoad = 0
        try {
            $cpuObj = Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average
            $cpuLoad = [math]::Round($cpuObj.Average, 1)
        } catch { $cpuLoad = 0 }

        $ramPercent = 0
        try {
            $osObj = Get-CimInstance Win32_OperatingSystem
            if ($osObj.TotalVisibleMemorySize -gt 0) {
                $ramPercent = [math]::Round((($osObj.TotalVisibleMemorySize - $osObj.FreePhysicalMemory) / $osObj.TotalVisibleMemorySize) * 100, 1)
            }
        } catch { $ramPercent = 0 }

        $batPercent = $null
        try {
            $batObj = Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue
            if ($batObj) { $batPercent = $batObj.EstimatedChargeRemaining }
        } catch {}

        $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
        $osCaption = (Get-CimInstance Win32_OperatingSystem).Caption
        if (-not $osCaption) { $osCaption = "Windows 11/10" }

        $bodyObj = @{
            id = $deviceId
            name = $devName
            host = $computer
            host_url = $activeUrl
            tunnel_url = $tunnelUrl
            public_url = $activeUrl
            lan_ip = $ip
            port = 8765
            cpu = $cpuLoad
            ram = $ramPercent
            os = $osCaption
            status = "online"
            metadata = @{
                admin = $isAdmin
                battery = $batPercent
                boot_time = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
                platform = "Windows"
                tunnel = if ($tunnelUrl) { "active" } else { "none" }
            }
        }

        $bodyJson = $bodyObj | ConvertTo-Json -Depth 5
        Invoke-RestMethod -Uri "$BackendUrl/api/devices" -Method Post -Body $bodyJson -ContentType "application/json" -TimeoutSec 8 | Out-Null
    } catch {}
}

function Poll-FleetCommands {
    try {
        $pollRes = Invoke-RestMethod -Uri "$BackendUrl/api/commands?device_id=$deviceId&poll=1" -Method Get -TimeoutSec 6
        if ($pollRes.ok -and $pollRes.command) {
            $cmd = $pollRes.command
            $cmdId = $cmd.id
            $cmdAction = "$($cmd.command)".ToLower().Trim()
            $payload = $cmd.payload

            $outText = ""
            $errText = ""

            try {
                if ($cmdAction -eq "exec" -or $cmdAction -eq "shell" -or $cmdAction -eq "terminal") {
                    $rawCmd = if ($payload.cmd) { $payload.cmd } else { $payload.command }
                    if ($rawCmd) {
                        $outText = powershell.exe -NoProfile -Command $rawCmd 2>&1 | Out-String
                    }
                }
                elseif ($cmdAction -eq "power") {
                    $act = if ($payload.action) { $payload.action } else { $payload.act }
                    if ($act -eq "lock") {
                        rundll32.exe user32.dll,LockWorkStation
                        $outText = "Host PC screen locked."
                    } elseif ($act -eq "shutdown") {
                        shutdown.exe /s /t 10 /c "Shutdown dispatched from Project-X-Nano Cloud Hub"
                        $outText = "Host PC shutting down in 10s."
                    } elseif ($act -eq "restart") {
                        shutdown.exe /r /t 10 /c "Restart dispatched from Project-X-Nano Cloud Hub"
                        $outText = "Host PC restarting in 10s."
                    }
                }
                elseif ($cmdAction -eq "elevate") {
                    Start-Process powershell.exe -Verb RunAs -ArgumentList "-NoProfile -Command Start-Process '$ExePath' -WorkingDirectory '$TargetDir'"
                    $outText = "UAC Elevation triggered."
                }
                else {
                    $outText = "Command '$cmdAction' acknowledged."
                }
            } catch {
                $errText = $_.Exception.Message
            }

            # Return execution result to Cloud Coordinator
            $resBody = @{
                action = "result"
                command_id = $cmdId
                status = if ($errText) { "failed" } else { "completed" }
                result = @{
                    output = $outText
                    error = $errText
                }
            } | ConvertTo-Json -Depth 5

            Invoke-RestMethod -Uri "$BackendUrl/api/commands" -Method Post -Body $resBody -ContentType "application/json" -TimeoutSec 8 | Out-Null
        }
    } catch {}
}

# Initial Startup
Ensure-TunnelAndServer
Start-Sleep -Seconds 2
Send-FleetHeartbeat

# Main Loop
$loopCounter = 0

while ($true) {
    if (Test-Path $UnlockFile) {
        break
    }

    Poll-FleetCommands

    $loopCounter++
    if ($loopCounter -ge 5) {
        $loopCounter = 0
        Ensure-TunnelAndServer
        Send-FleetHeartbeat
    }

    Start-Sleep -Seconds 3
}
