<div align="center">

# 🖥️ RemotePC (Alpha)
### *Next-Gen Personal Remote Control & Fleet Hub for Windows*

[![Release](https://img.shields.io/badge/Release-pc--remo--alpha-4f8cff.svg?style=for-the-badge)](https://github.com/mexxz-01)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%2F%2011-0078D6.svg?style=for-the-badge&logo=windows)](https://github.com/mexxz-01)
[![Fleet](https://img.shields.io/badge/Fleet%20Capacity-50--100%2B%20Active%20PCs-3ddc97.svg?style=for-the-badge)](https://github.com/mexxz-01)
[![PWA](https://img.shields.io/badge/Mobile-Installable%20PWA-ff5d5d.svg?style=for-the-badge&logo=googlechrome)](https://github.com/mexxz-01)
[![Security](https://img.shields.io/badge/Security-Scrypt%20%2B%20AES-brightgreen.svg?style=for-the-badge)](https://github.com/mexxz-01)

<p align="center">
  <b>Turn your phone or tablet into a unified master controller for your PC fleet.</b><br>
  No subscriptions. No third-party servers required. Available as a standalone Windows <code>.exe</code>.
</p>

---

</div>

## ✨ Key Features

| Category | Highlights |
|---|---|
| **👥 Fleet Manager** | Manage **5, 50, or 100+ active PCs** simultaneously. Real-time CPU/RAM meters, one-tap quick-switching, and broadcast actions (*Lock All*, *Sleep All*). |
| **🖥️ Live Screen Stream** | High-framerate, ultra-low latency desktop streaming with interactive **Tap-to-Click** (tap anywhere on your phone to click on the PC screen). |
| **📹 Live Webcam Stream** | Real-time MJPEG webcam feed straight to your mobile browser, plus instant snapshots. |
| **🖱️ Touchpad & Keyboard** | Smooth gesture touchpad (drag to move, tap to click), 2-finger scroll, full keyboard typing, and system shortcuts (`Alt+Tab`, `Win+D`, `Ctrl+C/V`). |
| **📂 Multi-Drive Explorer** | Instant 1-tap switching between **`C:\`**, **`D:\`**, **`Z:\`**, and USB drives. Download, upload multiple files, or launch files remotely. |
| **💻 Remote Terminal** | Embedded CMD & PowerShell console right from your phone, protected by secondary password authorization. |
| **📋 Clipboard Sync** | Bidirectional clipboard: copy text on your phone and push to PC, or pull PC clipboard to your phone. |
| **🎚️ Hardware Controls** | Smooth sliders for master volume and display brightness (via DDC/CI), plus full media playback keys. |
| **⏻ Power & Sleep** | Shut down, restart, sign out, lock, sleep, hibernate, countdown sleep timers, and cancel pending shutdowns. |
| **📱 Installable PWA** | Add to Home Screen on iOS and Android to run fullscreen with native app aesthetics and zero browser bars. |
| **🚨 Smart Alerts & Watchdog** | Low battery notifications, login alerts, and process watchdog (notifies your phone when long renders/tasks finish). |

---

## 🚀 Quick Start (Zero Python Required)

1. Go to the `dist\` folder and double-click **`RemotePC.exe`**.
2. If Windows Firewall prompts on first launch, check **"Private networks"** and click **Allow**.
3. The console will display your access URL:
   ```
   === RemotePC running ===
   Open on your phone: http://192.168.1.50:8765
   ```
4. Open the link on your phone (connected to same Wi-Fi) and log in:
   - **Default Password**: `mexxz@2007`
   *(Sessions stay active for 7 days so you won't need to re-login every time).*

---

## 👥 Fleet Hub: Controlling 50 to 100+ PCs

Whether you have 5 PCs at home, a mining rig, or a 100-node computer lab, RemotePC manages them all from one screen:

1. **Auto-Discovery**: Click **⚡ Auto-Add Discovered** in the Fleet Hub to scan your network and register all online PCs automatically.
2. **Manual Addition**: Click **➕ Add PC** and enter the node's IP or Tailscale address (e.g. `http://192.168.1.102:8765`).
3. **Instant Search**: Type any PC name, group, or IP in the search bar to filter 100+ machines in real-time.
4. **Emergency Broadcast**: Use **🔒 Lock All PCs** or **🌙 Sleep All** to execute batch actions across the entire network in parallel.

---

## 🌐 Remote Access From Anywhere (Outside Home Wi-Fi)

Want to control your PCs when you are far away on mobile data (4G/5G) or outside Wi-Fi? Here are the best ways:

### 1. Tailscale Mesh VPN (Recommended — 100% Free & Easiest)
* **How it works**: Tailscale connects your phone and all your PCs into a secure, encrypted virtual mesh network without opening router ports or dealing with dynamic IPs.
* **Setup**:
  1. Install [Tailscale](https://tailscale.com) on your PCs and your phone (sign in with the same account).
  2. Each PC gets a permanent `100.x.y.z` address (e.g., `100.85.12.34`).
  3. Open `http://100.85.12.34:8765` from your phone anywhere in the world!
* **Why it's the best**: Supports up to 100 devices completely free, runs 24/7, zero port-forwarding, and direct end-to-end encryption.

### 2. Cloudflare Tunnel (Free Public HTTPS Domain)
* Run Cloudflare's free tunnel daemon (`cloudflared`) on your primary PC to assign a custom domain (e.g. `https://mypc.yourdomain.com`).
* Gives you a real HTTPS URL which enables full browser push notifications and camera permissions.

### 3. Cloud Relay / Render Hosting
* **Can you host the backend on Render?**
  - **Yes, as a Central Fleet Relay**: Render runs in a Linux cloud container, so it cannot interact directly with your physical Windows hardware. However, Render can host a central relay dashboard where your 50–100 Windows PCs connect outbound, allowing you to access all machines through a single cloud dashboard 24/7.
  - **24/7 Availability on Render**:
    - **Free tier**: Automatically spins down after 15 minutes of inactivity and sleeps until a new request arrives (~50s cold start).
    - **Paid tier ($7/mo)**: Stays awake 24/7 indefinitely.
    - *Tip*: Tailscale provides 24/7 always-on access for 100 devices completely free without needing any cloud hosting!

---

## ⚙️ Configuration (`config.json`)

Customize ports, startup behavior, and one-tap saved commands in `config.json`:

```json
{
  "port": 8765,
  "host": "0.0.0.0",
  "terminal_enabled": true,
  "battery_low": 20,
  "commands": {
    "Network Info": "ipconfig",
    "Flush DNS": "ipconfig /flushdns",
    "Disk Space": "wmic logicaldisk get caption,freespace,size",
    "Clean Temp Files": "del /q /f /s %TEMP%\\*",
    "Backup Documents": "robocopy %USERPROFILE%\\Documents %USERPROFILE%\\Documents_Backup /E /XO /R:1 /W:1"
  },
  "apps": {
    "Notepad": "notepad.exe",
    "Calculator": "calc.exe",
    "Chrome": "start chrome"
  },
  "fleet": []
}
```

---

## 🛠️ Build From Source

To compile the standalone Windows executable yourself:

```powershell
# Clone the repository
git clone https://github.com/mexxz-01/remote-pc.git
cd remote-pc

# Install dependencies
pip install -r requirements.txt pyinstaller

# Run the build script
.\build.bat
```
The output executable will be placed in `dist\RemotePC.exe`.

---

## 🛡️ Security Architecture

* **Scrypt Password Hashing**: Passwords are cryptographically salted and hashed using Scrypt (`32768:8:1`).
* **Brute-Force Shield**: Exponential backoff and IP rate limiting after failed attempts.
* **Secondary Terminal Authorization**: The remote command console requires secondary password verification and locks automatically after 10 minutes.
* **Audit Trail**: Every executed command and unlock event is logged with timestamps in `audit.log`.

---

## 📄 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
