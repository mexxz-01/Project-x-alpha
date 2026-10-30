import os
import sys
import time
import json
import re
import urllib.request
import subprocess
import threading
import atexit
from pathlib import Path

BASE = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
CLOUDFLARED_EXE = BASE / "cloudflared.exe"
CLOUDFLARED_URL = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"

_tunnel_process = None
_public_url = None

def get_public_url():
    global _public_url
    return _public_url

def ensure_tunnel_binary():
    """Ensure cloudflared.exe exists locally in the install directory."""
    if CLOUDFLARED_EXE.exists() and CLOUDFLARED_EXE.stat().st_size > 10000000:
        return True

    print("[Tunnel] Downloading official Cloudflare Tunnel engine...")
    try:
        req = urllib.request.Request(CLOUDFLARED_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = resp.read()
        with open(CLOUDFLARED_EXE, "wb") as f:
            f.write(data)
        print(f"[Tunnel] Tunnel engine installed successfully ({len(data)} bytes).")
        return True
    except Exception as e:
        print(f"[Tunnel] Failed to download tunnel engine: {e}")
        return False

def start_tunnel(port: int = 8765, report_url: str = "") -> str:
    """Start Cloudflare tunnel in background, retrieve the public URL, and report it."""
    global _tunnel_process, _public_url

    if not ensure_tunnel_binary():
        return ""

    # Terminate any previous tunnel process
    try:
        subprocess.run(["taskkill", "/F", "/IM", "cloudflared.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.5)
    except Exception:
        pass

    cmd = [str(CLOUDFLARED_EXE), "tunnel", "--url", f"http://127.0.0.1:{port}"]
    try:
        _tunnel_process = subprocess.Popen(
            cmd,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
    except Exception as e:
        print(f"[Tunnel] Failed to start tunnel process: {e}")
        return ""

    def cleanup():
        global _tunnel_process
        if _tunnel_process:
            try:
                _tunnel_process.terminate()
            except Exception:
                pass
            _tunnel_process = None
    atexit.register(cleanup)

    # Read output to capture the trycloudflare.com URL
    url = None
    start_time = time.time()
    while time.time() - start_time < 25:
        line = _tunnel_process.stderr.readline()
        if not line:
            time.sleep(0.1)
            continue
        m = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", line)
        if m:
            url = m.group(0)
            break

    if url:
        _public_url = url
        print(f"[Tunnel] Public tunnel URL ready: {url}")
        if report_url:
            report_public_url(url, report_url)
        return url
    else:
        print("[Tunnel] Could not capture tunnel URL within timeout.")
        return ""

def report_public_url(url: str, report_url: str):
    """POST public tunnel link to remote central server/webhook."""
    if not report_url or not url:
        return

    def _post():
        try:
            payload = json.dumps({
                "app": "Project-X-Nano",
                "public_url": url,
                "timestamp": time.time()
            }).encode("utf-8")
            req = urllib.request.Request(
                report_url,
                data=payload,
                headers={"Content-Type": "application/json", "User-Agent": "Project-X-Nano-Tunnel"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                print(f"[Tunnel] Public URL successfully reported to: {report_url}")
        except Exception as e:
            print(f"[Tunnel] Failed to report URL to {report_url}: {e}")

    threading.Thread(target=_post, daemon=True).start()
