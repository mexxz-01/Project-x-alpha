#!/usr/bin/env bash
# =========================================================================
#  Project-X-Nano 1-Line Universal Automated Setup & Remote Cloud Hub
#  Platform: Linux (Ubuntu, Debian, Raspberry Pi OS, Arch, Fedora, CentOS)
#  Downloads all files, starts Cloudflare Tunnel automatically, and reports
#  the secure remote access URL to your central server / Discord webhook.
# =========================================================================

set -e

REPORT_URL=""
PORT="8765"

# Parse arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        -ReportUrl|--report-url) REPORT_URL="$2"; shift ;;
        -Port|--port) PORT="$2"; shift ;;
        *) ;;
    esac
    shift
done

if [ -z "$REPORT_URL" ] && [ -n "$TUNNEL_REPORT_URL" ]; then
    REPORT_URL="$TUNNEL_REPORT_URL"
fi

echo -e "\033[1;36m========================================================\033[0m"
echo -e "\033[1;36m      Project-X-Nano Linux Automated Cloud Fleet Setup  \033[0m"
echo -e "\033[1;36m========================================================\033[0m"

# 1. Target Directory in User Local Share
INSTALL_DIR="$HOME/.local/share/project-x-nano"
mkdir -p "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR/core"

GITHUB_RAW="https://raw.githubusercontent.com/mexxz-01/Project-x-alpha/main"

# 2. Check & Install Python 3 and Curl dependencies
echo -e "\033[1;32m[*] Checking runtime dependencies (Python3, Curl)...\033[0m"
if ! command -v curl &> /dev/null || ! command -v python3 &> /dev/null; then
    echo -e "\033[1;33m[*] Installing missing prerequisites via package manager...\033[0m"
    if command -v apt-get &> /dev/null; then
        sudo apt-get update -qq && sudo apt-get install -y -qq python3 python3-pip curl python3-venv xclip
    elif command -v dnf &> /dev/null; then
        sudo dnf install -y -q python3 python3-pip curl xclip
    elif command -v pacman &> /dev/null; then
        sudo pacman -Sy --noconfirm python python-pip curl xclip
    fi
fi

# 3. Detect CPU Architecture and Cloudflare binary
ARCH=$(uname -m)
CLOUDFLARED_URL=""
if [[ "$ARCH" == "x86_64" ]]; then
    CLOUDFLARED_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64"
elif [[ "$ARCH" == "aarch64" || "$ARCH" == "arm64" ]]; then
    CLOUDFLARED_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64"
elif [[ "$ARCH" == *"arm"* ]]; then
    CLOUDFLARED_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm"
else
    CLOUDFLARED_URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64"
fi

# 4. Terminate any previous instances
echo -e "\033[1;33m[*] Stopping any previous instances...\033[0m"
pkill -f "project-x-nano" 2>/dev/null || true
pkill -f "cloudflared" 2>/dev/null || true

# 5. Download Project Files from GitHub
echo -e "\033[1;32m[*] Downloading Project-X-Nano components from GitHub...\033[0m"
curl -sSL -o "$INSTALL_DIR/server.py" "$GITHUB_RAW/server.py"
curl -sSL -o "$INSTALL_DIR/tunnel.py" "$GITHUB_RAW/tunnel.py"
curl -sSL -o "$INSTALL_DIR/config.json" "$GITHUB_RAW/config.json"
curl -sSL -o "$INSTALL_DIR/version.json" "$GITHUB_RAW/version.json"
curl -sSL -o "$INSTALL_DIR/favicon.png" "$GITHUB_RAW/favicon.png" 2>/dev/null || true
curl -sSL -o "$INSTALL_DIR/icon-192.png" "$GITHUB_RAW/icon-192.png" 2>/dev/null || true
curl -sSL -o "$INSTALL_DIR/icon.ico" "$GITHUB_RAW/icon.ico" 2>/dev/null || true
curl -sSL -o "$INSTALL_DIR/watchdog.py" "$GITHUB_RAW/watchdog.py"
curl -sSL -o "$INSTALL_DIR/watchdog.sh" "$GITHUB_RAW/watchdog.sh"
curl -sSL -o "$INSTALL_DIR/uninstall.sh" "$GITHUB_RAW/uninstall.sh"

# Core Modules
for mod in __init__.py native_bridge.py screen_engine.py input_engine.py audio_engine.py terminal_engine.py fleet_engine.py integrity_engine.py; do
    curl -sSL -o "$INSTALL_DIR/core/$mod" "$GITHUB_RAW/core/$mod"
done

chmod +x "$INSTALL_DIR/watchdog.sh" 2>/dev/null || true
chmod +x "$INSTALL_DIR/uninstall.sh" 2>/dev/null || true

# 6. Download and Set Executable Cloudflared
echo -e "\033[1;32m[*] Downloading Cloudflare Tunnel engine for Linux ($ARCH)...\033[0m"
curl -sSL -o "$INSTALL_DIR/cloudflared" "$CLOUDFLARED_URL"
chmod +x "$INSTALL_DIR/cloudflared"

# 7. Install Python Requirements
echo -e "\033[1;32m[*] Verifying Python libraries (flask, psutil, pillow)...\033[0m"
python3 -m pip install --quiet --upgrade flask psutil pillow pyperclip 2>/dev/null || \
python3 -m pip install --quiet --upgrade flask psutil pillow pyperclip --break-system-packages 2>/dev/null || true

# 8. Configure Webhook in config.json
if [ -n "$REPORT_URL" ]; then
    python3 -c "
import json
p = '$INSTALL_DIR/config.json'
with open(p, 'r') as f: d = json.load(f)
d['tunnel_report_url'] = '$REPORT_URL'
d['auto_forward'] = True
with open(p, 'w') as f: json.dump(d, f, indent=2)
"
    echo -e "\033[1;32m[+] Webhook / Server report URL configured: $REPORT_URL\033[0m"
fi

# 9. Configure Linux Systemd User Autostart Service
echo -e "\033[1;32m[*] Configuring Linux background systemd service...\033[0m"
SERVICE_DIR="$HOME/.config/systemd/user"
mkdir -p "$SERVICE_DIR"
cat > "$SERVICE_DIR/project-x-nano.service" << EOF
[Unit]
Description=Project-X-Nano Personal Remote PC Hub
After=network.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
ExecStart=/usr/bin/python3 $INSTALL_DIR/server.py
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
EOF

# Desktop autostart fallback
AUTOSTART_DIR="$HOME/.config/autostart"
mkdir -p "$AUTOSTART_DIR"
cat > "$AUTOSTART_DIR/project-x-nano.desktop" << EOF
[Desktop Entry]
Type=Application
Name=Project-X-Nano
Exec=/usr/bin/python3 $INSTALL_DIR/server.py
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
EOF

if command -v systemctl &> /dev/null; then
    systemctl --user daemon-reload 2>/dev/null || true
    systemctl --user enable project-x-nano.service 2>/dev/null || true
    systemctl --user start project-x-nano.service 2>/dev/null || true
fi

# Start directly if systemctl user is not running
if ! pgrep -f "server.py" > /dev/null; then
    nohup python3 "$INSTALL_DIR/server.py" > "$INSTALL_DIR/remotepc.log" 2>&1 &
fi
sleep 2

# 10. Start Cloudflare Tunnel and Extract Public URL
echo -e "\033[1;36m[*] Starting Cloudflare Tunnel and generating secure public URL...\033[0m"
TUNNEL_LOG="$INSTALL_DIR/tunnel.log"
rm -f "$TUNNEL_LOG"

nohup "$INSTALL_DIR/cloudflared" tunnel --url "http://127.0.0.1:8765" > "$TUNNEL_LOG" 2>&1 &

PUBLIC_URL=""
echo -n "[*] Connecting to Cloudflare edge network"
for i in {1..45}; do
    echo -n "."
    if [ -f "$TUNNEL_LOG" ]; then
        MATCH=$(grep -o 'https://[a-zA-Z0-9-]*\.trycloudflare\.com' "$TUNNEL_LOG" | head -n 1 || true)
        if [ -n "$MATCH" ]; then
            PUBLIC_URL="$MATCH"
            break
        fi
    fi
    sleep 1
done
echo ""

if [ -n "$PUBLIC_URL" ]; then
    echo -e "\033[1;32m========================================================\033[0m"
    echo -e "\033[1;32m >> PUBLIC REMOTE CONTROL URL READY:                    \033[0m"
    echo -e "\033[1;33m    $PUBLIC_URL                                         \033[0m"
    echo -e "\033[1;32m========================================================\033[0m"
    echo "$PUBLIC_URL" > "$INSTALL_DIR/public_url.txt"

    # Report to Webhook if configured
    TARGET_WEBHOOK="$REPORT_URL"
    if [ -z "$TARGET_WEBHOOK" ]; then
        TARGET_WEBHOOK=$(python3 -c "import json; print(json.load(open('$INSTALL_DIR/config.json')).get('tunnel_report_url', ''))" 2>/dev/null || true)
    fi

    if [ -n "$TARGET_WEBHOOK" ]; then
        echo -e "\033[1;36m[*] Uploading remote link to server/webhook: $TARGET_WEBHOOK\033[0m"
        HOST_NAME=$(hostname)
        if [[ "$TARGET_WEBHOOK" == *"discord.com"* ]]; then
            PAYLOAD="{\"content\":\"[Project-X-Nano Online] Linux Host: $HOST_NAME | Remote URL: $PUBLIC_URL\"}"
        else
            PAYLOAD="{\"app\":\"Project-X-Nano\",\"host\":\"$HOST_NAME\",\"public_url\":\"$PUBLIC_URL\",\"os\":\"linux\"}"
        fi
        curl -s -X POST -H "Content-Type: application/json" -d "$PAYLOAD" "$TARGET_WEBHOOK" > /dev/null 2>&1 || true
        echo -e "\033[1;32m[+] Link successfully uploaded to server!\033[0m"
    fi
else
    echo -e "\033[1;33m[!] Cloudflare Tunnel URL timed out. Local network access is still active.\033[0m"
fi

# 11. Start Linux Watchdog
nohup bash "$INSTALL_DIR/watchdog.sh" "$INSTALL_DIR" > /dev/null 2>&1 &

# 12. Local IP detection
LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "127.0.0.1")

echo -e "\033[1;36m========================================================\033[0m"
echo -e "\033[1;32m [SUCCESS] Project-X-Nano is installed and running!     \033[0m"
echo -e "\033[1;36m========================================================\033[0m"
echo -e " Local Web URL:    \033[1;33mhttp://localhost:8765\033[0m"
echo -e " Network URL:      \033[1;33mhttp://${LOCAL_IP}:8765\033[0m"
if [ -n "$PUBLIC_URL" ]; then
    echo -e " Public URL:       \033[1;32m$PUBLIC_URL\033[0m"
fi
echo -e " Install Folder:   $INSTALL_DIR"
echo -e "\033[1;36m========================================================\033[0m"
echo ""

# 13. Prompt to open dashboard
read -p "[?] Do you want to open the dashboard now? (Y/N): " OPEN_CHOICE
if [[ "$OPEN_CHOICE" =~ ^[Yy]$ ]]; then
    read -s -p "[?] Enter master password: " ENTERED_PWD
    echo ""
    if [ "$ENTERED_PWD" == "mexxz@2007" ]; then
        echo -e "\033[1;32m[+] Password verified! Opening dashboard...\033[0m"
        TARGET_DASH="${PUBLIC_URL:-http://localhost:8765}"
        if command -v xdg-open &> /dev/null; then
            xdg-open "$TARGET_DASH" 2>/dev/null || true
        elif command -v sensible-browser &> /dev/null; then
            sensible-browser "$TARGET_DASH" 2>/dev/null || true
        fi
    else
        echo -e "\033[1;31m[-] Incorrect password. Dashboard will not be opened.\033[0m"
    fi
else
    echo -e "\033[1;36m[*] Skipping dashboard launch. Background agent is fully active.\033[0m"
fi
