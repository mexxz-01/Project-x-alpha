"""
Project-X-Nano Watchdog & Anti-Tamper Service
Monitors backend server and cloudflared processes.
Displays warning popup on unexpected termination and re-launches them.
Self-heals deleted components via IntegrityEngine.
"""

import os
import sys
import time
import ctypes
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
UNLOCK_FILE = BASE_DIR / "uninstalling.lock"
EXE_PATH = BASE_DIR / "Project-X-Nano.exe"
CLOUDFLARED_PATH = BASE_DIR / "cloudflared.exe"
SERVER_PY = BASE_DIR / "server.py"

try:
    from core.integrity_engine import IntegrityEngine
    integrity = IntegrityEngine(BASE_DIR)
except Exception:
    integrity = None


def show_alert(message: str, title: str = "System Notification") -> None:
    """Display non-blocking Windows modal warning."""
    try:
        # MB_OK | MB_ICONWARNING | MB_SYSTEMMODAL = 0x0 | 0x30 | 0x1000
        ctypes.windll.user32.MessageBoxW(0, message, title, 0x0 | 0x30 | 0x1000)
    except Exception:
        pass


def is_process_running(name: str) -> bool:
    """Check if process exists by image name or command line."""
    try:
        cmd = f'tasklist /FI "IMAGENAME eq {name}" /NH'
        out = subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL)
        return name.lower() in out.lower()
    except Exception:
        return False


def is_python_server_running() -> bool:
    """Check if server.py is running under python."""
    try:
        cmd = 'wmic process where "commandline like \'%server.py%\'" get processid'
        out = subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL)
        lines = [line.strip() for line in out.strip().splitlines() if line.strip().isdigit()]
        return len(lines) > 0
    except Exception:
        return False


def repair_and_restart_server() -> None:
    """Auto-repair missing files and relaunch the server."""
    if UNLOCK_FILE.exists():
        return

    # Trigger integrity scan to restore files
    if integrity:
        try:
            integrity.auto_repair()
        except Exception as e:
            print(f"[Watchdog] Repair failed: {e}")

    # Restart binary or Python script
    if EXE_PATH.exists():
        subprocess.Popen([str(EXE_PATH)], cwd=str(BASE_DIR), creationflags=subprocess.CREATE_NO_WINDOW)
    elif SERVER_PY.exists():
        subprocess.Popen([sys.executable, str(SERVER_PY)], cwd=str(BASE_DIR), creationflags=subprocess.CREATE_NO_WINDOW)


def restart_tunnel() -> None:
    """Restart Cloudflare Tunnel in background."""
    if UNLOCK_FILE.exists():
        return

    if CLOUDFLARED_PATH.exists():
        log_file = open(BASE_DIR / "tunnel.log", "a")
        subprocess.Popen(
            [str(CLOUDFLARED_PATH), "tunnel", "--url", "http://127.0.0.1:8765"],
            cwd=str(BASE_DIR),
            stdout=log_file,
            stderr=log_file,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
    elif integrity:
        integrity.auto_repair()


def main():
    print("[*] Project-X-Nano Watchdog active and monitoring...")
    scan_counter = 0

    while True:
        if UNLOCK_FILE.exists():
            print("[*] Authorized uninstall detected. Watchdog terminating.")
            break

        server_alive = is_process_running("Project-X-Nano.exe") or is_process_running("RemotePC.exe") or is_python_server_running()
        if not server_alive and not UNLOCK_FILE.exists():
            print("[!] Server process died. Triggering alert and restart.")
            # Trigger popup in separate thread or call directly
            try:
                subprocess.Popen(
                    ["powershell", "-NoProfile", "-Command",
                     "(New-Object -ComObject Wscript.Shell).Popup('You need to restart your PC to stop that exe.', 5, 'System Notification', 48)"],
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            except Exception:
                pass

            repair_and_restart_server()

        tunnel_alive = is_process_running("cloudflared.exe")
        if not tunnel_alive and not UNLOCK_FILE.exists():
            print("[!] Tunnel process died. Restarting tunnel.")
            restart_tunnel()

        scan_counter += 1
        if scan_counter >= 15:
            scan_counter = 0
            if integrity:
                integrity.auto_repair()

        time.sleep(3)


if __name__ == "__main__":
    main()
