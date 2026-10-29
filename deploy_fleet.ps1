# Project-X-Nano Remote Fleet Deployment Tool
# Deploys Project-X-Nano across multiple target PCs over LAN using WinRM

param (
    [string[]]$Targets = @()
)

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "      Project-X-Nano Remote Fleet Deployment Utility     " -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan

if ($Targets.Count -eq 0) {
    Write-Host "Enter target PC IP addresses separated by commas (e.g. 192.168.1.11, 192.168.1.12):" -ForegroundColor Yellow
    $inputTargets = Read-Host
    if ([string]::IsNullOrWhiteSpace($inputTargets)) {
        Write-Host "[!] No target PCs provided. Exiting." -ForegroundColor Red
        exit 1
    }
    $Targets = $inputTargets.Split(',') | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" }
}

Write-Host "[*] Target PCs: $($Targets -join ', ')" -ForegroundColor Green
Write-Host "[*] Prompting for administrator credentials..." -ForegroundColor Yellow
$cred = Get-Credential

Write-Host "[*] Pushing setup script to $($Targets.Count) machines..." -ForegroundColor Green
try {
    Invoke-Command -ComputerName $Targets -Credential $cred -ScriptBlock {
        irm https://raw.githubusercontent.com/mexxz-01/Project-x-alpha/main/setup.ps1 | iex
    }
    Write-Host "[SUCCESS] Fleet deployment completed across target machines!" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] Deployment error: $_" -ForegroundColor Red
    Write-Host "Note: Ensure WinRM is enabled on target PCs (Enable-PSRemoting -Force) and TrustedHosts is configured." -ForegroundColor Yellow
}
